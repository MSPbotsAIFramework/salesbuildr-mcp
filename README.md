# Salesbuildr MCP Server

An [MCP](https://modelcontextprotocol.io) server for the [Salesbuildr](https://www.salesbuildr.com)
public API, the quoting and sales platform built for MSPs. It lets an AI agent search
companies, contacts, the product catalog, opportunities and quotes and, on explicit request,
create or update companies, contacts and opportunities, delete companies and contacts, and
create draft quotes from catalog products.

- Transport: MCP Streamable HTTP at `POST /mcp`, health probe at `GET /health`
- Stateless and multi-tenant: the API key arrives on every request as an HTTP header and is
  never stored; every tool is listed from the first `tools/list`
- Python 3.12, [uv](https://docs.astral.sh/uv/), FastMCP, httpx
- License: Apache-2.0, Copyright 2026 MSPbots.ai

## Authentication headers

| Header | Required | Type | Default | Allowed values | Description | Example |
|---|---|---|---|---|---|---|
| `X-SalesBuildr-API-Key` | Yes | string | none | - | Salesbuildr public API key | `your-api-key` |
| `X-SalesBuildr-Base-Url` | No | string | `https://portal.salesbuildr.com` | https URL | Portal address, only for a non-default Salesbuildr environment | `https://portal.salesbuildr.com` |

Where to get it: a Salesbuildr administrator creates an API key in the Salesbuildr portal's
integration / API settings. The key acts on the whole Salesbuildr account.

How the key is sent to Salesbuildr: in the `api-key` header of every call to
`https://portal.salesbuildr.com/public-api/...`.

A request to `/mcp` without the key gets HTTP 401; a base URL that is not https gets HTTP 400.

## Tools

All tools return a JSON string. Lists search with `query`, page with `from` (offset) and `size`
(default 25, max 100) and return `{items, count, total, from, has_more, next_from}`, most
recently changed first.

| Tool | Purpose | Parameters (required in **bold**) |
|---|---|---|
| `salesbuildr_navigate` | Describe the tools of one area (changes nothing) | **domain** (`companies`, `contacts`, `products`, `opportunities`, `quotes`) |
| `salesbuildr_status` | Check the connection (the key works) and list the areas | - |
| `salesbuildr_companies_list` | Search companies | query, from, size |
| `salesbuildr_companies_get` | One company | **id** |
| `salesbuildr_companies_create` | Create a company (**write**) | **name**, domain, address, city, state, zip, country, phone, website, notes, number, type |
| `salesbuildr_companies_update` | Change a company; other fields keep their values (**write**) | **id**, name, domain, address, city, state, zip, country, phone, website, notes |
| `salesbuildr_companies_delete` | Delete a company (**write**, needs `confirm: true`) | **id**, confirm |
| `salesbuildr_contacts_list` | Search contacts, optionally in one company | query, companyId, from, size |
| `salesbuildr_contacts_get` | One contact | **id** |
| `salesbuildr_contacts_create` | Create a contact (**write**) | **firstName**, **lastName**, email, phone, companyId, mobilePhone |
| `salesbuildr_contacts_update` | Change a contact; other fields keep their values (**write**) | **id**, firstName, lastName, email, phone, companyId, mobilePhone |
| `salesbuildr_contacts_delete` | Delete a contact (**write**, needs `confirm: true`) | **id**, confirm |
| `salesbuildr_products_list` | Search the product catalog | query, from, size |
| `salesbuildr_products_get` | One product with pricing | **id** |
| `salesbuildr_opportunities_list` | Search pipeline opportunities | query, from, size |
| `salesbuildr_opportunities_get` | One opportunity | **id** |
| `salesbuildr_opportunities_create` | Create an opportunity (**write**) | **title**, companyId, contactId, value, monthlyValue, stage, probability, expectedCloseDate, notes |
| `salesbuildr_opportunities_update` | Change an opportunity (**write**) | **id**, title, companyId, contactId, value, monthlyValue, stage, probability, expectedCloseDate, notes |
| `salesbuildr_quotes_list` | Search quotes, optionally by company or opportunity | query, companyId, opportunityId, from, size |
| `salesbuildr_quotes_get` | One quote with line items | **id** |
| `salesbuildr_quotes_create` | Create a draft quote for an opportunity (**write**) | **title**, **opportunityId**, items [{**productId**, **quantity**, unitPrice}], templateId |

Field mapping to the API: company `phone` -> `telephone`, `notes` -> `stickyNote`, `address` /
`city` / `state` / `zip` / `country` -> the `address` object, `domain` -> `website` when no
website is given; opportunity `title` -> `name`, `value` -> one-time revenue, `monthlyValue` ->
monthly revenue, `stage` -> pipeline stage id, `notes` -> description, `probability` 0-1 (a
percentage above 1 is divided by 100).

Errors come back as a JSON envelope instead of an exception:

```json
{"error": {"code": "invalid_argument", "message": "Salesbuildr returned HTTP 400 for company: number must be a string", "retryable": false}}
```

`code` is one of `not_configured`, `unauthorized`, `not_found`, `invalid_argument`,
`rate_limited`, `upstream_error`. Reads are retried with backoff on 429, 5xx and network
errors; writes are retried only on 429.

## Run locally

```bash
uv sync
uv run python -m salesbuildr_mcp          # listens on 0.0.0.0:8080
```

or with Docker:

```bash
docker build --platform linux/amd64 -t salesbuildr-mcp:dev .
docker run --rm -p 8080:8080 salesbuildr-mcp:dev
```

Configuration (environment variables, all optional): `MCP_HTTP_HOST` (default `0.0.0.0`),
`MCP_HTTP_PORT` (default `8080`), `LOG_LEVEL` (default `INFO`). The key is never read from the
environment.

## Testing example

```bash
# list tools
curl -s http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "X-SalesBuildr-API-Key: your-api-key" \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'

# quotes of one opportunity
curl -s http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "X-SalesBuildr-API-Key: your-api-key" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"salesbuildr_quotes_list","arguments":{"opportunityId":"your-opportunity-id"}}}'
```

Unit tests (no network access needed):

```bash
uv run pytest
```

## Delivery notes

- **Tool count (21).** Kept as is because the tool names are an existing contract.
- **API contract.** Requests follow Salesbuildr's published API reference
  (`https://portal.salesbuildr.com/public-api`). Older versions sent field names the API does
  not have (for example company `phone`, `zip` and `notes` at the top level, opportunity
  `title` / `value` / `stage`, quote `items` with free-text names); those now map to the real
  fields listed above, and parameters with no API field (contact `title` and `notes`, quote
  `companyId` / `contactId` / `notes` / `validUntil`) were removed.
- **Quotes.** The API creates quotes only for an opportunity and only from catalog products,
  so `opportunityId` is required and each line needs a `productId`.
- **Updates.** Company and contact updates replace the whole record in the API; this server
  reads the current record first and changes only the fields given.
- **Deletes** need `confirm: true`.

## License

Apache License 2.0 - see [LICENSE](LICENSE) and [NOTICE](NOTICE).
