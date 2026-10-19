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
"""tools/list snapshot and error-envelope mapping. No network access."""

import asyncio
import json

import pytest

from salesbuildr_mcp.api_client import SalesbuildrError
from salesbuildr_mcp.server import INSTRUCTIONS, create_mcp_server

# Tool names are a public contract: existing agents and tenant connections
# depend on them. Changing this snapshot is a breaking change.
EXPECTED_TOOLS: dict[str, set[str]] = {
    "salesbuildr_navigate": {"domain"},
    "salesbuildr_status": set(),
    "salesbuildr_companies_list": set(),
    "salesbuildr_companies_get": {"id"},
    "salesbuildr_companies_create": {"name"},
    "salesbuildr_companies_update": {"id"},
    "salesbuildr_companies_delete": {"id"},
    "salesbuildr_contacts_list": set(),
    "salesbuildr_contacts_get": {"id"},
    "salesbuildr_contacts_create": {"firstName", "lastName"},
    "salesbuildr_contacts_update": {"id"},
    "salesbuildr_contacts_delete": {"id"},
    "salesbuildr_products_list": set(),
    "salesbuildr_products_get": {"id"},
    "salesbuildr_opportunities_list": set(),
    "salesbuildr_opportunities_get": {"id"},
    "salesbuildr_opportunities_create": {"title"},
    "salesbuildr_opportunities_update": {"id"},
    "salesbuildr_quotes_list": set(),
    "salesbuildr_quotes_get": {"id"},
    # The API needs the opportunity a quote belongs to.
    "salesbuildr_quotes_create": {"title", "opportunityId"},
}
WRITE_TOOLS = {
    "salesbuildr_companies_create",
    "salesbuildr_companies_update",
    "salesbuildr_companies_delete",
    "salesbuildr_contacts_create",
    "salesbuildr_contacts_update",
    "salesbuildr_contacts_delete",
    "salesbuildr_opportunities_create",
    "salesbuildr_opportunities_update",
    "salesbuildr_quotes_create",
}
DELETES = {"salesbuildr_companies_delete", "salesbuildr_contacts_delete"}


@pytest.fixture(scope="module")
def tools():
    return {t.name: t for t in asyncio.run(create_mcp_server().list_tools())}


def test_tool_names_are_stable(tools):
    assert set(tools) == set(EXPECTED_TOOLS)


@pytest.mark.parametrize("name", sorted(EXPECTED_TOOLS))
def test_required_params(tools, name):
    assert set(tools[name].inputSchema.get("required", [])) == EXPECTED_TOOLS[name]


@pytest.mark.parametrize("name", sorted(EXPECTED_TOOLS))
def test_description_budget(tools, name):
    description = (tools[name].description or "").strip()
    assert description, f"{name} has no description"
    assert len(description) <= 500
    assert len(description.splitlines()[0]) <= 100


@pytest.mark.parametrize("name", sorted(EXPECTED_TOOLS))
def test_annotations_match_side_effects(tools, name):
    annotations = tools[name].annotations
    assert annotations.readOnlyHint is (name not in WRITE_TOOLS)
    assert bool(annotations.destructiveHint) is (name in DELETES)


@pytest.mark.parametrize("name", sorted(WRITE_TOOLS))
def test_write_tools_say_when_to_use_them(tools, name):
    assert "explicitly asks" in tools[name].description


def test_list_tools_take_from(tools):
    for name in ("salesbuildr_companies_list", "salesbuildr_quotes_list"):
        assert "from" in tools[name].inputSchema["properties"]
        assert "from_" not in tools[name].inputSchema["properties"]


def test_instructions_budget():
    assert len(INSTRUCTIONS) <= 1500


@pytest.mark.parametrize(
    "status,code,retryable",
    [(401, "unauthorized", False), (403, "unauthorized", False), (404, "not_found", False),
     (400, "invalid_argument", False), (429, "rate_limited", True), (500, "upstream_error", True), (0, "upstream_error", True)],
)
def test_error_envelope(status, code, retryable):
    envelope = json.loads(SalesbuildrError(status, "boom").to_envelope())
    assert envelope == {"error": {"code": code, "message": "boom", "retryable": retryable}}


def test_tool_without_credentials_returns_not_configured():
    content, _ = asyncio.run(create_mcp_server().call_tool("salesbuildr_status", {}))
    assert json.loads(content[0].text)["error"]["code"] == "not_configured"
