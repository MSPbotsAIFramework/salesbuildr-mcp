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
"""Quotes: proposals for an opportunity, built from catalog products."""

from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from ..api_client import SalesbuildrClient
from ._common import (
    READ_ONLY,
    WRITES,
    ClientFactory,
    Query,
    RecordId,
    Size,
    StartFrom,
    compact,
    from_alias,
    run_tool,
    search,
)


class QuoteItem(BaseModel):
    productId: str = Field(description="Catalog product id (from salesbuildr_products_list).")
    quantity: float = Field(description="Quantity.", gt=0)
    unitPrice: float | None = Field(default=None, description="Price override per unit; omit for the catalog price.", ge=0)
    name: str | None = Field(default=None, description="Ignored: lines always use the catalog product's name.")


def _line(item: QuoteItem) -> dict:
    line: dict[str, Any] = {"id": item.productId.strip(), "quantity": item.quantity}
    if item.unitPrice is not None:
        line["price"] = {"price": item.unitPrice}
    return line


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    @from_alias
    async def salesbuildr_quotes_list(
        query: Query = None,
        companyId: Annotated[str | None, Field(description="Only quotes for this company.")] = None,
        opportunityId: Annotated[str | None, Field(description="Only quotes of this opportunity.")] = None,
        from_: StartFrom = None,
        size: Size = None,
    ) -> str:
        """Search quotes: number, title, status, company, contact, opportunity, dates and link."""

        async def action(client: SalesbuildrClient) -> dict:
            filters = {"company.id": companyId, "opportunityId": opportunityId}
            return await search(client, "quote", query, filters, from_, size)

        return await run_tool("salesbuildr_quotes_list", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def salesbuildr_quotes_get(id: RecordId) -> str:
        """Get one quote in full: line items, pricing, discounts, status, approvals and attachments."""

        async def action(client: SalesbuildrClient) -> Any:
            return await client.get(f"quote/{id.strip()}")

        return await run_tool("salesbuildr_quotes_get", client_factory, action)

    @mcp.tool(annotations=WRITES)
    async def salesbuildr_quotes_create(
        title: Annotated[str, Field(description="Quote title.", min_length=1)],
        opportunityId: Annotated[str, Field(description="Opportunity the quote is for (every quote needs one).", min_length=1)],
        items: Annotated[list[QuoteItem] | None, Field(description="Lines: catalog productId and quantity, optional unitPrice.")] = None,
        templateId: Annotated[str | None, Field(description="Quote template id; omit for the default template.")] = None,
    ) -> str:
        """Create a draft quote for an opportunity from catalog products. Only when the user explicitly asks."""

        async def action(client: SalesbuildrClient) -> Any:
            body = compact(
                {
                    "opportunityId": opportunityId.strip(),
                    "title": title.strip(),
                    "templateId": templateId,
                    "products": [_line(item) for item in items] if items else None,
                }
            )
            return await client.post("quote", body)

        return await run_tool("salesbuildr_quotes_create", client_factory, action)
