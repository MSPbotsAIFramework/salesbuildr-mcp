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
"""Contacts: people at companies, who receive and approve quotes."""

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
CompanyId = Annotated[str | None, Field(description="Company id (\"primary\" links the contact to your own company).")]
# Fields of a contact that PUT /contact/{id} accepts and GET returns.
_KEPT_ON_UPDATE = ("firstName", "middleName", "lastName", "email", "phone", "mobilePhone", "companyId", "externalIdentifier")


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    @from_alias
    async def salesbuildr_contacts_list(
        query: Query = None,
        companyId: Annotated[str | None, Field(description="Only contacts of this company.")] = None,
        from_: StartFrom = None,
        size: Size = None,
    ) -> str:
        """Search contacts by name, email or other text, optionally within one company."""

        async def action(client: SalesbuildrClient) -> dict:
            return await search(client, "contact", query, {"company.id": companyId}, from_, size)

        return await run_tool("salesbuildr_contacts_list", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def salesbuildr_contacts_get(id: RecordId) -> str:
        """Get one contact: name, email, phones, company and labels."""

        async def action(client: SalesbuildrClient) -> Any:
            return await client.get(f"contact/{id.strip()}")

        return await run_tool("salesbuildr_contacts_get", client_factory, action)

    @mcp.tool(annotations=WRITES)
    async def salesbuildr_contacts_create(
        firstName: Annotated[str, Field(description="First name.", min_length=1)],
        lastName: Annotated[str, Field(description="Last name.", min_length=1)],
        email: Annotated[str | None, Field(description="Email address.")] = None,
        phone: Annotated[str | None, Field(description="Phone number.")] = None,
        companyId: CompanyId = None,
        mobilePhone: Annotated[str | None, Field(description="Mobile number.")] = None,
    ) -> str:
        """Create a contact, usually linked to a company. Only when the user explicitly asks."""

        async def action(client: SalesbuildrClient) -> Any:
            body = compact(
                {
                    "firstName": firstName.strip(),
                    "lastName": lastName.strip(),
                    "email": email,
                    "phone": phone,
                    "mobilePhone": mobilePhone,
                    "companyId": companyId,
                }
            )
            return await client.post("contact", body)

        return await run_tool("salesbuildr_contacts_create", client_factory, action)

    @mcp.tool(annotations=WRITES_IDEMPOTENT)
    async def salesbuildr_contacts_update(
        id: RecordId,
        firstName: Text = None,
        lastName: Text = None,
        email: Text = None,
        phone: Text = None,
        companyId: CompanyId = None,
        mobilePhone: Text = None,
    ) -> str:
        """Change a contact; fields not given keep their current values. Only when the user explicitly asks."""

        async def action(client: SalesbuildrClient) -> Any:
            changes = compact(
                {
                    "firstName": firstName,
                    "lastName": lastName,
                    "email": email,
                    "phone": phone,
                    "mobilePhone": mobilePhone,
                    "companyId": companyId,
                }
            )
            if not changes:
                raise ValueError("Nothing to update: pass at least one field to change.")
            # PUT replaces the whole contact, so start from its current state.
            current = await client.get(f"contact/{id.strip()}") or {}
            body = {k: current[k] for k in _KEPT_ON_UPDATE if isinstance(current, dict) and current.get(k) is not None}
            return await client.put(f"contact/{id.strip()}", body | changes)

        return await run_tool("salesbuildr_contacts_update", client_factory, action)

    @mcp.tool(annotations=DESTRUCTIVE)
    async def salesbuildr_contacts_delete(id: RecordId, confirm: Confirm = None) -> str:
        """Delete a contact. Only when the user explicitly asks, with confirm=true."""

        async def action(client: SalesbuildrClient) -> dict:
            if confirm is not True:
                raise ValueError("Deleting a contact needs confirm=true; ask the user first.")
            await client.delete(f"contact/{id.strip()}")
            return {"deleted": True, "id": id.strip()}

        return await run_tool("salesbuildr_contacts_delete", client_factory, action)
