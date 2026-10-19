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
"""Products: the catalog quotes are built from (read-only here)."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from ..api_client import SalesbuildrClient
from ._common import READ_ONLY, ClientFactory, Query, RecordId, Size, StartFrom, from_alias, run_tool, search


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    @from_alias
    async def salesbuildr_products_list(query: Query = None, from_: StartFrom = None, size: Size = None) -> str:
        """Search the product catalog by name, MPN or other text: price, cost, term, category, vendor."""

        async def action(client: SalesbuildrClient) -> dict:
            return await search(client, "product", query, {}, from_, size, sort=None)

        return await run_tool("salesbuildr_products_list", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def salesbuildr_products_get(id: RecordId) -> str:
        """Get one product: descriptions, pricing (cost, price, setup, MSRP), term, taxes, labels."""

        async def action(client: SalesbuildrClient) -> Any:
            return await client.get(f"product/{id.strip()}")

        return await run_tool("salesbuildr_products_get", client_factory, action)
