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
"""Tool discovery (kept for compatibility) and the connection check."""

from typing import Annotated, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from .._json import compact as to_json
from ..api_client import SalesbuildrClient
from ._common import LOCAL, READ_ONLY, ClientFactory, run_tool

DOMAINS: dict[str, tuple[str, list[str]]] = {
    "companies": (
        "Customers: search, get, create, update, delete.",
        [
            "salesbuildr_companies_list",
            "salesbuildr_companies_get",
            "salesbuildr_companies_create",
            "salesbuildr_companies_update",
            "salesbuildr_companies_delete",
        ],
    ),
    "contacts": (
        "People at companies: search, get, create, update, delete.",
        [
            "salesbuildr_contacts_list",
            "salesbuildr_contacts_get",
            "salesbuildr_contacts_create",
            "salesbuildr_contacts_update",
            "salesbuildr_contacts_delete",
        ],
    ),
    "products": ("The product catalog: search, get.", ["salesbuildr_products_list", "salesbuildr_products_get"]),
    "opportunities": (
        "Pipeline deals: search, get, create, update.",
        [
            "salesbuildr_opportunities_list",
            "salesbuildr_opportunities_get",
            "salesbuildr_opportunities_create",
            "salesbuildr_opportunities_update",
        ],
    ),
    "quotes": (
        "Quotes for opportunities: search, get, create a draft.",
        ["salesbuildr_quotes_list", "salesbuildr_quotes_get", "salesbuildr_quotes_create"],
    ),
}


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=LOCAL)
    async def salesbuildr_navigate(
        domain: Annotated[
            Literal["companies", "contacts", "products", "opportunities", "quotes"], Field(description="Area to describe.")
        ],
    ) -> str:
        """Describe the tools of one Salesbuildr area. All tools are already callable; this changes nothing."""
        summary, tools = DOMAINS[domain]
        return to_json({"domain": domain, "summary": summary, "tools": tools})

    @mcp.tool(annotations=READ_ONLY)
    async def salesbuildr_status() -> str:
        """Check the Salesbuildr connection (the API key works) and list the tool areas."""

        async def action(client: SalesbuildrClient) -> dict:
            await client.get("product", {"size": 1})
            return {
                "connected": True,
                "base_url": client.base_url,
                "domains": {name: summary for name, (summary, _tools) in DOMAINS.items()},
            }

        return await run_tool("salesbuildr_status", client_factory, action)
