# Copyright 2026 MSPbots.ai
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Request shapes, paging, merges and retries against a mocked Salesbuildr API."""

import json

import httpx
import pytest

from salesbuildr_mcp import api_client
from salesbuildr_mcp.api_client import SalesbuildrClient, SalesbuildrCredentials, SalesbuildrError
from salesbuildr_mcp.server import _credentials_var, create_mcp_server

CREDS = SalesbuildrCredentials(api_key="key-123")


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def instant(_seconds):
        return None

    monkeypatch.setattr(api_client.asyncio, "sleep", instant)


class Recorder:
    """Mock transport: replies by "METHOD path" or path below /public-api/."""

    def __init__(self, routes=None, default=None):
        self.requests: list[httpx.Request] = []
        self.routes = routes or {}
        self.default = default if default is not None else {"results": [], "total": 0}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path.removeprefix("/public-api/")
        reply = self.routes.get(f"{request.method} {path}", self.routes.get(path, self.default))
        if callable(reply):
            return reply(request)
        return httpx.Response(200, json=reply)

    def calls(self, method: str, path: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.method == method and r.url.path == f"/public-api/{path}"]


def body(request: httpx.Request):
    return json.loads(request.content) if request.content else None


async def _call(monkeypatch, recorder: Recorder, tool: str, args: dict):
    http = httpx.AsyncClient(transport=httpx.MockTransport(recorder))
    monkeypatch.setattr(api_client, "_get_shared_http_client", lambda: http)
    ctx = _credentials_var.set(CREDS)
    try:
        content, _ = await create_mcp_server().call_tool(tool, args)
    finally:
        _credentials_var.reset(ctx)
    return json.loads(content[0].text)


def _client(recorder: Recorder) -> SalesbuildrClient:
    return SalesbuildrClient(CREDS, httpx.AsyncClient(transport=httpx.MockTransport(recorder)))


# ---- client ----------------------------------------------------------------


async def test_api_key_header_and_url():
    rec = Recorder()
    await _client(rec).get("company", {"size": 5})
    request = rec.requests[0]
    assert str(request.url) == "https://portal.salesbuildr.com/public-api/company?size=5"
    assert request.headers["api-key"] == "key-123"
    assert "Authorization" not in request.headers


async def test_validation_message_list_is_joined():
    rec = Recorder({"POST company": lambda r: httpx.Response(400, json={"statusCode": 400, "message": ["number must be a string", "type should not be empty"], "error": "Bad Request"})})
    with pytest.raises(SalesbuildrError) as err:
        await _client(rec).post("company", {"name": "x"})
    assert "number must be a string; type should not be empty" in err.value.message


async def test_get_retries_5xx():
    replies = iter([httpx.Response(503), httpx.Response(200, json={"results": [], "total": 0})])
    rec = Recorder({"company": lambda r: next(replies)})
    await _client(rec).get("company")
    assert len(rec.requests) == 2


async def test_writes_are_not_retried_on_5xx():
    rec = Recorder({"POST quote": lambda r: httpx.Response(500, json={"message": "boom"})})
    with pytest.raises(SalesbuildrError):
        await _client(rec).post("quote", {})
    assert len(rec.requests) == 1


# ---- searches --------------------------------------------------------------


async def test_list_paging_and_from_alias(monkeypatch):
    rec = Recorder({"company": {"results": [{"id": "c1"}, {"id": "c2"}], "total": 12}})
    result = await _call(monkeypatch, rec, "salesbuildr_companies_list", {"query": "acme", "from": 4, "size": 2})
    params = rec.requests[0].url.params
    assert (params["query"], params["from"], params["size"], params["sort"]) == ("acme", "4", "2", "-updatedDate")
    assert (result["count"], result["total"], result["has_more"], result["next_from"]) == (2, 12, True, 6)


async def test_contacts_by_company_use_filters(monkeypatch):
    rec = Recorder()
    await _call(monkeypatch, rec, "salesbuildr_contacts_list", {"companyId": "c1"})
    assert rec.requests[0].url.params["filters"] == "company.id:c1"


async def test_quotes_filters_combined(monkeypatch):
    rec = Recorder()
    await _call(monkeypatch, rec, "salesbuildr_quotes_list", {"companyId": "c1", "opportunityId": "o9"})
    assert rec.requests[0].url.params["filters"] == "company.id:c1,opportunityId:o9"


async def test_filter_values_with_separators_are_rejected(monkeypatch):
    rec = Recorder()
    result = await _call(monkeypatch, rec, "salesbuildr_contacts_list", {"companyId": "a,b"})
    assert result["error"]["code"] == "invalid_argument"
    assert rec.requests == []


# ---- companies -------------------------------------------------------------


async def test_company_create_maps_fields(monkeypatch):
    rec = Recorder({"POST company": {"id": "c1"}})
    args = {"name": "Acme", "domain": "acme.example", "address": "1 Main St", "city": "Springfield", "zip": "12345",
            "phone": "555-0100", "notes": "VIP", "number": "C-100", "type": "customer"}
    await _call(monkeypatch, rec, "salesbuildr_companies_create", args)
    assert body(rec.calls("POST", "company")[0]) == {
        "name": "Acme",
        "number": "C-100",
        "type": "customer",
        "website": "https://acme.example",
        "telephone": "555-0100",
        "stickyNote": "VIP",
        "address": {"street": "1 Main St", "city": "Springfield", "zip": "12345"},
    }


async def test_company_update_merges_with_current_state(monkeypatch):
    current = {"id": "c1", "name": "Acme", "type": "customer", "website": "https://acme.example", "telephone": "1",
               "address": {"street": "1 Main St", "city": "Springfield", "zip": "12345", "country": "US"},
               "labels": ["vip"], "social": {"x": "y"}}
    rec = Recorder({"GET company/c1": current, "PUT company/c1": {"id": "c1"}})
    await _call(monkeypatch, rec, "salesbuildr_companies_update", {"id": "c1", "phone": "2", "city": "Shelbyville"})
    sent = body(rec.calls("PUT", "company/c1")[0])
    assert sent["telephone"] == "2" and sent["name"] == "Acme" and sent["labels"] == ["vip"]
    assert sent["address"] == {"street": "1 Main St", "city": "Shelbyville", "zip": "12345", "country": "US"}
    assert "social" not in sent and "id" not in sent


async def test_update_without_changes_is_rejected(monkeypatch):
    rec = Recorder()
    result = await _call(monkeypatch, rec, "salesbuildr_companies_update", {"id": "c1"})
    assert result["error"]["code"] == "invalid_argument"
    assert rec.requests == []


@pytest.mark.parametrize("tool,path", [("salesbuildr_companies_delete", "company/c1"), ("salesbuildr_contacts_delete", "contact/c1")])
async def test_delete_needs_confirm(monkeypatch, tool, path):
    rec = Recorder({f"DELETE {path}": lambda r: httpx.Response(200, content=b"")})
    result = await _call(monkeypatch, rec, tool, {"id": "c1"})
    assert result["error"]["code"] == "invalid_argument"
    assert rec.requests == []
    result = await _call(monkeypatch, rec, tool, {"id": "c1", "confirm": True})
    assert result == {"deleted": True, "id": "c1"}
    assert len(rec.calls("DELETE", path)) == 1


# ---- contacts --------------------------------------------------------------


async def test_contact_update_merges(monkeypatch):
    current = {"id": "p1", "firstName": "Jane", "lastName": "Doe", "email": "jane@example.com", "companyId": "c1", "companyName": "Acme"}
    rec = Recorder({"GET contact/p1": current, "PUT contact/p1": {"id": "p1"}})
    await _call(monkeypatch, rec, "salesbuildr_contacts_update", {"id": "p1", "email": "j.doe@example.com"})
    assert body(rec.calls("PUT", "contact/p1")[0]) == {
        "firstName": "Jane", "lastName": "Doe", "email": "j.doe@example.com", "companyId": "c1"
    }


# ---- opportunities ---------------------------------------------------------


async def test_opportunity_create_maps_fields(monkeypatch):
    rec = Recorder({"POST opportunity": {"id": "o1"}})
    args = {"title": "Firewall refresh", "companyId": "c1", "value": 12000, "monthlyValue": 300, "stage": "st1",
            "probability": 60, "expectedCloseDate": "2026-09-30T00:00:00Z", "notes": "Q3"}
    await _call(monkeypatch, rec, "salesbuildr_opportunities_create", args)
    assert body(rec.calls("POST", "opportunity")[0]) == {
        "name": "Firewall refresh",
        "companyId": "c1",
        "onetimeRevenue": 12000,
        "monthlyRevenue": 300,
        "pipelineStageId": "st1",
        "probability": 0.6,
        "expectedCloseDate": "2026-09-30",
        "description": "Q3",
    }


async def test_opportunity_update_sends_only_changes(monkeypatch):
    rec = Recorder({"PUT opportunity/o1": {"id": "o1"}})
    await _call(monkeypatch, rec, "salesbuildr_opportunities_update", {"id": "o1", "probability": 0.25})
    assert body(rec.calls("PUT", "opportunity/o1")[0]) == {"probability": 0.25}


async def test_bad_close_date(monkeypatch):
    result = await _call(monkeypatch, Recorder(), "salesbuildr_opportunities_create", {"title": "x", "expectedCloseDate": "30/09/2026"})
    assert result["error"]["code"] == "invalid_argument"


# ---- quotes ----------------------------------------------------------------


async def test_quote_create_body(monkeypatch):
    rec = Recorder({"POST quote": {"id": "q1"}})
    args = {"title": "Firewall", "opportunityId": "o1", "templateId": "t1",
            "items": [{"productId": "p1", "quantity": 2}, {"productId": "p2", "quantity": 1, "unitPrice": 99.5, "name": "x"}]}
    await _call(monkeypatch, rec, "salesbuildr_quotes_create", args)
    assert body(rec.calls("POST", "quote")[0]) == {
        "opportunityId": "o1",
        "title": "Firewall",
        "templateId": "t1",
        "products": [{"id": "p1", "quantity": 2}, {"id": "p2", "quantity": 1, "price": {"price": 99.5}}],
    }


async def test_products_list_has_no_sort(monkeypatch):
    rec = Recorder()
    await _call(monkeypatch, rec, "salesbuildr_products_list", {"query": "m365"})
    assert "sort" not in rec.requests[0].url.params


async def test_status(monkeypatch):
    rec = Recorder()
    result = await _call(monkeypatch, rec, "salesbuildr_status", {})
    assert result["connected"] is True
    assert rec.requests[0].url.params["size"] == "1"
