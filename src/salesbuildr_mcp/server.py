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
"""FastMCP factory and the per-request credential middleware."""

import contextvars
import re
import uuid
from collections.abc import Callable
from urllib.parse import urlsplit

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .api_client import SalesbuildrClient, SalesbuildrCredentials
from .config import DEFAULT_BASE_URL, Settings

HEADER_API_KEY = "X-SalesBuildr-API-Key"
HEADER_BASE_URL = "X-SalesBuildr-Base-Url"

_PLACEHOLDER = re.compile(r"^\$\{.*\}$")

# Per-request isolation: the middleware sets these for the duration of one
# HTTP request and resets them in `finally`. Nothing credential-related is
# ever stored at module level.
_credentials_var: contextvars.ContextVar[SalesbuildrCredentials | None] = contextvars.ContextVar(
    "salesbuildr_credentials", default=None
)
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("salesbuildr_request_id", default="-")

INSTRUCTIONS = (
    "Salesbuildr is a quoting and sales platform for MSPs: companies "
    "(customers) and their contacts, a product catalog, opportunities (deals in "
    "a pipeline) and quotes built from catalog products.\n"
    "Usage:\n"
    "- Find records with the *_list tools (query = free-text search; lists page "
    "with from + size and return total).\n"
    "- A quote always belongs to an opportunity: find or create the "
    "opportunity first, then salesbuildr_quotes_create(opportunityId, title, "
    "items of catalog productId + quantity) creates a draft quote.\n"
    "- Updates change only the fields you pass; the server keeps the rest.\n"
    "Creating, updating and deleting change the customer's sales records: call "
    "those tools only when the user explicitly asks. Deletes need confirm=true."
)


def get_client_from_context() -> SalesbuildrClient | None:
    """The client for the current request, or None outside a request."""
    credentials = _credentials_var.get()
    if credentials is None:
        return None
    return SalesbuildrClient(credentials)


def _clean(value: str | None) -> str | None:
    text = (value or "").strip()
    if not text or _PLACEHOLDER.match(text):
        return None
    return text


def normalize_base_url(value: str) -> str | None:
    """https origin + /public-api; None when the URL is unusable."""
    text = value.strip()
    if "://" not in text:
        text = f"https://{text}"
    parts = urlsplit(text)
    if parts.scheme != "https" or not parts.hostname:
        return None
    return f"https://{parts.netloc}/public-api"


class GatewayCredentialsMiddleware:
    """Reads X-SalesBuildr-API-Key (and the optional base URL) on /mcp requests; 401 without a key."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith("/mcp"):
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        api_key = _clean(request.headers.get(HEADER_API_KEY))
        if not api_key:
            await JSONResponse(
                {
                    "error": "Missing credentials",
                    "message": f"Send the Salesbuildr API key in the {HEADER_API_KEY} header",
                    "required_headers": [HEADER_API_KEY],
                    "optional_headers": [HEADER_BASE_URL],
                },
                status_code=401,
            )(scope, receive, send)
            return

        base_raw = _clean(request.headers.get(HEADER_BASE_URL))
        base_url = normalize_base_url(base_raw) if base_raw else DEFAULT_BASE_URL
        if base_url is None:
            await JSONResponse(
                {"error": "Invalid header", "message": f"{HEADER_BASE_URL} must be an https URL"}, status_code=400
            )(scope, receive, send)
            return

        request_id = (request.headers.get("x-request-id") or "").strip()[:64] or uuid.uuid4().hex[:12]
        creds_token = _credentials_var.set(SalesbuildrCredentials(api_key=api_key, base_url=base_url))
        rid_token = request_id_var.set(request_id)
        try:
            await self.app(scope, receive, send)
        finally:
            _credentials_var.reset(creds_token)
            request_id_var.reset(rid_token)


def create_mcp_server(settings: Settings | None = None) -> FastMCP:
    """Build the FastMCP server and register every tool."""
    mcp = FastMCP(
        name="salesbuildr-mcp",
        instructions=INSTRUCTIONS,
        # The service sits behind the gateway, so Host is never localhost;
        # DNS-rebinding protection would reject those requests with 421.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        stateless_http=True,
    )

    client_factory: Callable[[], SalesbuildrClient | None] = get_client_from_context

    from .tools import companies, contacts, navigation, opportunities, products, quotes

    for module in (navigation, companies, contacts, products, opportunities, quotes):
        module.register(mcp, client_factory)

    return mcp
