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
"""Shared argument types, search / paging helpers and the error-handling wrapper."""

import functools
import inspect
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from .._json import dump_json_capped, error_envelope
from ..api_client import SalesbuildrClient, SalesbuildrError

logger = logging.getLogger("salesbuildr_mcp.tools")

ClientFactory = Callable[[], SalesbuildrClient | None]

READ_ONLY = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=True)
LOCAL = ToolAnnotations(readOnlyHint=True, idempotentHint=True, openWorldHint=False)
WRITES = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)
WRITES_IDEMPOTENT = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=True)
DESTRUCTIVE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=True)

NOT_CONFIGURED = error_envelope(
    "not_configured", "Salesbuildr credentials are missing for this request (X-SalesBuildr-API-Key).", False
)

DEFAULT_SIZE = 25

Query = Annotated[str | None, Field(description="Free-text search.")]
Size = Annotated[int | None, Field(description=f"Results per page, 1-100 (default {DEFAULT_SIZE}).", ge=1, le=100)]
RecordId = Annotated[str, Field(description="Salesbuildr id.", min_length=1)]
Confirm = Annotated[bool | None, Field(description="Must be true to delete; ask the user first.")]


def from_alias(function: Callable[..., Awaitable[str]]) -> Callable[..., Awaitable[str]]:
    """Expose a ``from_`` parameter as ``from`` (a Python keyword).

    FastMCP calls the tool with the alias as the keyword, so it is renamed back
    before the call; the published signature keeps ``from_`` with alias "from".
    """

    @functools.wraps(function)
    async def wrapper(**kwargs: Any) -> str:
        if "from" in kwargs:
            kwargs["from_"] = kwargs.pop("from")
        return await function(**kwargs)

    wrapper.__signature__ = inspect.signature(function)  # type: ignore[attr-defined]
    return wrapper


StartFrom = Annotated[
    int | None,
    Field(alias="from", description="Results to skip (default 0); use next_from from the previous page.", ge=0),
]


def compact(values: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in values.items() if v is not None}


def filter_string(filters: dict[str, str | None]) -> str | None:
    """Salesbuildr's filter syntax: field:value pairs joined by commas."""
    pairs = []
    for field, value in filters.items():
        if value is None or not str(value).strip():
            continue
        text = str(value).strip()
        if any(ch in text for ch in ",|:"):
            raise ValueError(f"{field} must not contain ',', '|' or ':' (got {text!r}).")
        pairs.append(f"{field}:{text}")
    return ",".join(pairs) or None


async def search(
    client: SalesbuildrClient,
    path: str,
    query: str | None,
    filters: dict[str, str | None],
    start: int | None,
    size: int | None,
    sort: str | None = "-updatedDate",
) -> dict:
    """GET a search endpoint and return {items, count, total, from, has_more, next_from}."""
    offset, page = start or 0, size or DEFAULT_SIZE
    params = compact(
        {
            "query": (query or "").strip() or None,
            "filters": filter_string(filters),
            "from": offset,
            "size": page,
            "sort": sort,
        }
    )
    payload = await client.get(path, params) or {}
    items = payload.get("results") if isinstance(payload, dict) else payload
    items = items if isinstance(items, list) else []
    total = payload.get("total") if isinstance(payload, dict) else None
    more = offset + len(items) < total if isinstance(total, int) else len(items) >= page
    return compact(
        {
            "items": items,
            "count": len(items),
            "total": total,
            "from": offset,
            "has_more": more,
            "next_from": offset + len(items) if more else None,
        }
    )


async def run_tool(
    name: str,
    client_factory: ClientFactory,
    action: Callable[[SalesbuildrClient], Awaitable[Any]],
) -> str:
    """Resolve the caller's client, run ``action``, and always return a string.

    Errors never escape as exceptions: they become the standard error envelope.
    """
    client = client_factory()
    if client is None:
        return NOT_CONFIGURED
    started = time.monotonic()
    try:
        result = await action(client)
    except SalesbuildrError as e:
        logger.info("tool=%s outcome=error status=%s ms=%d", name, e.status_code, _ms(started))
        return e.to_envelope()
    except ValueError as e:
        logger.info("tool=%s outcome=invalid_argument ms=%d", name, _ms(started))
        return error_envelope("invalid_argument", str(e), False)
    except Exception as e:  # noqa: BLE001 - tools must never raise
        logger.warning("tool=%s outcome=unexpected error=%s ms=%d", name, type(e).__name__, _ms(started))
        return error_envelope("upstream_error", f"Unexpected error: {type(e).__name__}", True)
    logger.info("tool=%s outcome=ok ms=%d", name, _ms(started))
    if result is None:
        result = {"result": None, "note": "Salesbuildr returned an empty response."}
    return result if isinstance(result, str) else dump_json_capped(result)


def _ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
