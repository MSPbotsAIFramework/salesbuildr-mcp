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
"""Companies: the MSP's customers (and prospects) in Salesbuildr."""

from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..api_client import SalesbuildrClient
from ._common import (
    DESTRUCTIVE,
    READ_ONLY,
    WRITES,
    WRITES_IDEMPOTENT,
    ClientFactory,
    Confirm,
    Query,
    RecordId,
    Size,
    StartFrom,
    compact,
    from_alias,
    run_tool,
    search,
)

Text = Annotated[str | None, Field(description="New value.")]
# Fields of a company that PUT /company/{id} accepts and GET returns.
_KEPT_ON_UPDATE = (
    "name",
    "type",
    "website",
    "aboutUs",
    "telephone",
    "stickyNote",
    "address",
    "currency",
    "labels",
    "parentCompanyId",
    "accountManagerId",
    "quotePaymentTermId",
    "externalIdentifier",
    "deliveryAddresses",
    "defaultDeliveryAddressId",
)


def _address(street: str | None, city: str | None, state: str | None, zip: str | None, country: str | None) -> dict:
    return compact({"street": street, "city": city, "state": state, "zip": zip, "country": country})


def _website(website: str | None, domain: str | None) -> str | None:
    if website:
        return website
    if domain:
        return domain if "://" in domain else f"https://{domain}"
    return None


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    @from_alias
    async def salesbuildr_companies_list(query: Query = None, from_: StartFrom = None, size: Size = None) -> str:
        """Search companies (customers) by name or other text; newest changes first."""

        async def action(client: SalesbuildrClient) -> dict:
            return await search(client, "company", query, {}, from_, size)

        return await run_tool("salesbuildr_companies_list", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def salesbuildr_companies_get(id: RecordId) -> str:
        """Get one company: type, website, phone, address, account manager, labels, custom fields."""

        async def action(client: SalesbuildrClient) -> Any:
            return await client.get(f"company/{id.strip()}")

        return await run_tool("salesbuildr_companies_get", client_factory, action)

    @mcp.tool(annotations=WRITES)
    async def salesbuildr_companies_create(
        name: Annotated[str, Field(description="Company name.", min_length=1)],
        domain: Annotated[str | None, Field(description="Web domain; used as the website when website is not given.")] = None,
        address: Annotated[str | None, Field(description="Street address.")] = None,
        city: Text = None,
        state: Text = None,
        zip: Annotated[str | None, Field(description="Postal code.")] = None,
        country: Text = None,
        phone: Annotated[str | None, Field(description="Main telephone number.")] = None,
        website: Annotated[str | None, Field(description="Website URL.")] = None,
        notes: Annotated[str | None, Field(description="Sticky note shown on the company.")] = None,
        number: Annotated[str | None, Field(description="Company number (the customer number in your PSA).")] = None,
        type: Annotated[str | None, Field(description="Company type, e.g. customer or prospect.")] = None,
    ) -> str:
        """Create a company. Only when the user explicitly asks."""

        async def action(client: SalesbuildrClient) -> Any:
            body = compact(
                {
                    "name": name.strip(),
                    "number": number,
                    "type": type,
                    "website": _website(website, domain),
                    "telephone": phone,
                    "stickyNote": notes,
                    "address": _address(address, city, state, zip, country) or None,
                }
            )
            return await client.post("company", body)

        return await run_tool("salesbuildr_companies_create", client_factory, action)

    @mcp.tool(annotations=WRITES_IDEMPOTENT)
    async def salesbuildr_companies_update(
        id: RecordId,
        name: Text = None,
        domain: Annotated[str | None, Field(description="Web domain; used as the website when website is not given.")] = None,
        address: Annotated[str | None, Field(description="Street address.")] = None,
        city: Text = None,
        state: Text = None,
        zip: Annotated[str | None, Field(description="Postal code.")] = None,
        country: Text = None,
        phone: Annotated[str | None, Field(description="Main telephone number.")] = None,
        website: Annotated[str | None, Field(description="Website URL.")] = None,
        notes: Annotated[str | None, Field(description="Sticky note shown on the company.")] = None,
    ) -> str:
        """Change a company; fields not given keep their current values. Only when the user explicitly asks."""

        async def action(client: SalesbuildrClient) -> Any:
            changes = compact(
                {"name": name, "website": _website(website, domain), "telephone": phone, "stickyNote": notes}
            )
            address_changes = _address(address, city, state, zip, country)
            if not changes and not address_changes:
                raise ValueError("Nothing to update: pass at least one field to change.")
            # PUT replaces the whole company, so start from its current state.
            current = await client.get(f"company/{id.strip()}") or {}
            body = {k: current[k] for k in _KEPT_ON_UPDATE if isinstance(current, dict) and current.get(k) is not None}
            body |= changes
            if address_changes:
                body["address"] = {**(current.get("address") or {}), **address_changes}
            return await client.put(f"company/{id.strip()}", body)

        return await run_tool("salesbuildr_companies_update", client_factory, action)

    @mcp.tool(annotations=DESTRUCTIVE)
    async def salesbuildr_companies_delete(id: RecordId, confirm: Confirm = None) -> str:
        """Delete a company. Irreversible: only when the user explicitly asks, with confirm=true."""

        async def action(client: SalesbuildrClient) -> dict:
            if confirm is not True:
                raise ValueError("Deleting a company is irreversible; ask the user, then call again with confirm=true.")
            await client.delete(f"company/{id.strip()}")
            return {"deleted": True, "id": id.strip()}

        return await run_tool("salesbuildr_companies_delete", client_factory, action)
