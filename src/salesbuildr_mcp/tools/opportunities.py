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
"""Opportunities: deals in the sales pipeline; quotes are created for them."""

import re
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ..api_client import SalesbuildrClient
from ._common import (
    READ_ONLY,
    WRITES,
    WRITES_IDEMPOTENT,
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

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

Value = Annotated[float | None, Field(description="One-time revenue of the deal.", ge=0)]
MonthlyValue = Annotated[float | None, Field(description="Monthly recurring revenue of the deal.", ge=0)]
Stage = Annotated[str | None, Field(description="Pipeline stage id.")]
Probability = Annotated[
    float | None, Field(description="Win probability: 0-1, or a percentage 1-100 (converted).", ge=0, le=100)
]
CloseDate = Annotated[str | None, Field(description="Expected close date, YYYY-MM-DD.")]
Notes = Annotated[str | None, Field(description="Description of the opportunity.")]


def _probability(value: float | None) -> float | None:
    if value is None:
        return None
    return value / 100 if value > 1 else value


def _date(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip()[:10]
    if not _DATE.match(text):
        raise ValueError(f"expectedCloseDate must be YYYY-MM-DD (got {value!r}).")
    return text


def _fields(
    title: str | None,
    companyId: str | None,
    contactId: str | None,
    value: float | None,
    monthlyValue: float | None,
    stage: str | None,
    probability: float | None,
    expectedCloseDate: str | None,
    notes: str | None,
) -> dict:
    return compact(
        {
            "name": title.strip() if title else None,
            "companyId": companyId,
            "contactId": contactId,
            "onetimeRevenue": value,
            "monthlyRevenue": monthlyValue,
            "pipelineStageId": stage,
            "probability": _probability(probability),
            "expectedCloseDate": _date(expectedCloseDate),
            "description": notes,
        }
    )


def register(mcp: FastMCP, client_factory: ClientFactory) -> None:
    @mcp.tool(annotations=READ_ONLY)
    @from_alias
    async def salesbuildr_opportunities_list(query: Query = None, from_: StartFrom = None, size: Size = None) -> str:
        """Search opportunities (pipeline deals) with company, stage, revenue, probability and close date."""

        async def action(client: SalesbuildrClient) -> dict:
            return await search(client, "opportunity", query, {}, from_, size)

        return await run_tool("salesbuildr_opportunities_list", client_factory, action)

    @mcp.tool(annotations=READ_ONLY)
    async def salesbuildr_opportunities_get(id: RecordId) -> str:
        """Get one opportunity: company, contact, owner, stage, revenue, probability, dates and status."""

        async def action(client: SalesbuildrClient) -> Any:
            return await client.get(f"opportunity/{id.strip()}")

        return await run_tool("salesbuildr_opportunities_get", client_factory, action)

    @mcp.tool(annotations=WRITES)
    async def salesbuildr_opportunities_create(
        title: Annotated[str, Field(description="Opportunity name.", min_length=1)],
        companyId: Annotated[str | None, Field(description="Company id.")] = None,
        contactId: Annotated[str | None, Field(description="Contact person id.")] = None,
        value: Value = None,
        stage: Stage = None,
        probability: Probability = None,
        expectedCloseDate: CloseDate = None,
        notes: Notes = None,
        monthlyValue: MonthlyValue = None,
    ) -> str:
        """Create an opportunity in the pipeline. Only when the user explicitly asks."""

        async def action(client: SalesbuildrClient) -> Any:
            body = _fields(title, companyId, contactId, value, monthlyValue, stage, probability, expectedCloseDate, notes)
            return await client.post("opportunity", body)

        return await run_tool("salesbuildr_opportunities_create", client_factory, action)

    @mcp.tool(annotations=WRITES_IDEMPOTENT)
    async def salesbuildr_opportunities_update(
        id: RecordId,
        title: Annotated[str | None, Field(description="New name.")] = None,
        companyId: Annotated[str | None, Field(description="Company id.")] = None,
        contactId: Annotated[str | None, Field(description="Contact person id.")] = None,
        value: Value = None,
        stage: Stage = None,
        probability: Probability = None,
        expectedCloseDate: CloseDate = None,
        notes: Notes = None,
        monthlyValue: MonthlyValue = None,
    ) -> str:
        """Change an opportunity; only the fields given change. Only when the user explicitly asks."""

        async def action(client: SalesbuildrClient) -> Any:
            body = _fields(title, companyId, contactId, value, monthlyValue, stage, probability, expectedCloseDate, notes)
            if not body:
                raise ValueError("Nothing to update: pass at least one field to change.")
            return await client.put(f"opportunity/{id.strip()}", body)

        return await run_tool("salesbuildr_opportunities_update", client_factory, action)
