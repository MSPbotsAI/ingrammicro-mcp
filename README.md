# ingrammicro-mcp

MCP server for the **entire Ingram Micro Reseller purchasing lifecycle** —
a stateless HTTP MCP service wrapping the full non-webhook surface of
Ingram Micro's Reseller REST API: product catalog/pricing, quotes, order
placement/change/cancel/lookup, invoices, renewals, special-pricing deals,
returns, and freight estimates.

**Tech stack:** Python 3.12 + uv + FastMCP (Starlette/Uvicorn)

## Why this exists instead of just using Ingram Micro's own MCP Server

Ingram Micro also publishes its own official, remote-hosted MCP Server
(`developer.ingrammicro.com/reseller/mcp-server`). Verified directly
against that page's own content (2026-09-01): it is **query-only** —
product/pricing search, quotes, invoices, returns, renewals, subscriptions,
and freight estimate. It never mentions "Create Order" or "Place Order"
anywhere, so it cannot place a purchase order.

Rather than deploying two separate Ingram Micro connectors (their query-
only MCP plus a second one just for ordering — which would mean
provisioning two separate sets of credentials for the same vendor, and
the agent having to pick between two connectors for overlapping
capability), this server reimplements the official MCP's query
capabilities itself, directly against the same underlying Reseller REST
API, and adds the order-placement/change/cancel capability the official
one lacks. **One connector, one set of credentials, full coverage** —
this server is meant to fully replace Ingram Micro's own MCP Server for
MSPbots' purposes, not run alongside it.

## Authentication

OAuth2 **client_credentials** grant — pure server-to-server, no browser
redirect — but via Ingram Micro's own documented shape: `GET
/oauth/oauth20/token` with `client_id`/`client_secret` as **query
parameters**, not the more common HTTP Basic Auth header. Verified against
Ingram Micro's own published OpenAPI spec
(`github.com/ingrammicro-xvantage/xi-sdk-openapispec`,
`openapispec/unified/XI-Resellers-API-Spec.json`, checked 2026-09-01), not
guessed.

Every real Orders/Quote-to-Order call additionally requires three
business-context headers Ingram Micro's own docs mark mandatory —
`IM-CustomerNumber`, `IM-CountryCode`, `IM-CorrelationID` — plus an
optional `IM-SenderID`. `IM-CorrelationID` must be unique per transaction,
so this server generates a fresh UUID for every call itself; it is not
something the caller supplies.

**Getting credentials is not self-serve.** Per Ingram Micro's own
onboarding docs, applying for API access requires:
- An **existing, active Ingram Micro reseller account** in good standing
- **Current sales history** with Ingram Micro
- Sandbox testing, then a formal app-approval submission (~2 business days)

This is a real prerequisite, not a formality — confirm the tenant already
has an active Ingram Micro reseller relationship before attempting to
provision credentials for this server.

Since this is a stateless multi-tenant service, the token is **not
cached** — every tool call re-authenticates from scratch (same pattern as
`cisco-umbrella-mcp`/`covedataprotection-mcp`/`webroot-mcp`).

### HEADER 授权参数说明

| Header | 类型 | 是否必填 | 默认值 | 枚举值 | 字段描述 | Example |
|---|---|---|---|---|---|---|
| `X-IngramMicro-Client-Id` | string | 是 | 无 | 无 | OAuth2 client_credentials 的 Client ID | `abc123...` |
| `X-IngramMicro-Client-Secret` | string | 是 | 无 | 无 | OAuth2 client_credentials 的 Client Secret | `xyz789...` |
| `X-IngramMicro-Customer-Number` | string | 是 | 无 | 无 | Ingram Micro 经销商账号（对应上游 `IM-CustomerNumber`），如 `20-222222` | `20-222222` |
| `X-IngramMicro-Country-Code` | string | 是 | 无 | 无 | 两位 ISO 国家代码（对应上游 `IM-CountryCode`） | `US` |

Missing any of the four required headers returns `401 Unauthorized`.

## Quick Start

### Docker (recommended)

```bash
docker compose up --build
```

The server starts on `http://localhost:8080`.

### Local (uv)

```bash
uv sync
python -m ingrammicro_mcp
```

## Health Check

```bash
curl http://localhost:8080/health
# {"status": "ok"}
```

No credentials are required for the health endpoint.

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `MCP_TRANSPORT` | `stdio` | `http` (production) or `stdio` (local dev) |
| `MCP_HTTP_PORT` | `8080` | Listening port |
| `MCP_HTTP_HOST` | `0.0.0.0` | Listening host |
| `AUTH_MODE` | `gateway` | `gateway` (per-request headers, SOP-compliant) or `env` (shared credential, local dev only) |
| `INGRAMMICRO_CLIENT_ID` / `_CLIENT_SECRET` / `_CUSTOMER_NUMBER` / `_COUNTRY_CODE` | — | Only used in `env` mode |
| `INGRAMMICRO_SENDER_ID` | `MSPbots` | `IM-SenderID` value sent on every call |
| `INGRAMMICRO_BASE_URL` | `https://api.ingrammicro.com` | Override for sandbox testing (see Known Gaps — the exact sandbox URL is unverified) |

## Tool List

24 tools, covering every non-webhook endpoint in Ingram Micro's Resellers
API. Every order-placing/modifying tool spends real money against the
reseller's Ingram Micro net-terms account — **Ingram Micro does not
support credit-card API ordering**, only net-terms trade credit, so a
mistaken order is a real invoice, not a rejected charge.

### Catalog（对应官方MCP：Product Info & Pricing）

| Tool | 功能 | 方法+路径 |
|---|---|---|
| `ingrammicro_search_products` | 按关键词/厂商/分类搜索产品目录 | GET /resellers/v6/catalog |
| `ingrammicro_get_product_detail` | 按Ingram Part Number查产品详情 | GET /resellers/v6/catalog/details/{ingramPartNumber} |
| `ingrammicro_get_product_detail_by_reference` | 按厂商料号/订阅计划id或名查产品详情 | GET /resellers/v6/catalog/details |
| `ingrammicro_get_price_and_availability` | 查实时价格与库存 | POST /resellers/v6/catalog/priceandavailability |

### Quotes（对应官方MCP：Quotes）

| Tool | 功能 | 方法+路径 |
|---|---|---|
| `ingrammicro_search_quotes` | 搜索报价单 | GET /resellers/v6/quotes/search |
| `ingrammicro_get_quote` | 查报价单详情 | GET /resellers/v6/quotes/{quoteNumber} |
| `ingrammicro_create_quote` | 创建报价单（占价，不是下单） | POST /resellers/v6/quotes/create |
| `ingrammicro_validate_quote_to_order` | 转单前校验报价，返回必填字段 | GET /resellers/v6/q2o/validatequote |

### Orders（对应官方MCP：Orders，但官方只读；下单/改单/取消是官方没有的能力）

| Tool | 功能 | 方法+路径 | 主要参数 |
|---|---|---|---|
| `ingrammicro_create_order` | 下单：库存/直发/授权/保修类SKU | POST /resellers/v6/orders | `customer_order_number`(必填), `lines`(必填), `ship_to_info`, `end_user_info`, `reseller_info`, `shipment_details`, `vendor_auth_number`(保修单必填) |
| `ingrammicro_create_cloud_order` | 下单：云订阅 / Quote-to-Order / Configure-to-Order（异步，结果通过webhook推送，不在本次响应里） | POST /resellers/v7/orders | `quote_number` 或 `lines` 二选一(必须给一个) |
| `ingrammicro_modify_order` | 改单：仅限带customer-hold标记、下单后24小时内的订单 | PUT /resellers/v6/orders/{orderNumber} | `order_number`(必填), `action_code`(如"release"), `lines`(ADD/UPDATE/DELETE) |
| `ingrammicro_cancel_order` | 取消订单：仅限尚未放行到仓库前 | DELETE /resellers/v6/orders/{OrderNumber} | `order_number`(必填) |
| `ingrammicro_get_order` | 查单个订单详情/物流状态 | GET /resellers/v6.1/orders/{ordernumber} |
| `ingrammicro_search_orders` | 按PO号/状态/产品搜索订单 | GET /resellers/v6/orders/search |

### Invoices（对应官方MCP：Invoices）

| Tool | 功能 | 方法+路径 |
|---|---|---|
| `ingrammicro_search_invoices` | 搜索发票 | GET /resellers/v6/invoices |
| `ingrammicro_get_invoice` | 查发票详情 | GET /resellers/v6.1/invoices/{invoiceNumber} |

### Renewals（对应官方MCP：Subscriptions/Renewals）

| Tool | 功能 | 方法+路径 |
|---|---|---|
| `ingrammicro_search_renewals` | 搜索续订机会 | POST /resellers/v6/renewals/search |
| `ingrammicro_get_renewal` | 查续订详情 | GET /resellers/v6/renewals/{renewalId} |

### Deals（特价/Special Bid，官方MCP未单独列出，但同属查询类能力）

| Tool | 功能 | 方法+路径 |
|---|---|---|
| `ingrammicro_search_deals` | 搜索特价/Special Bid | GET /resellers/v6/deals/search |
| `ingrammicro_get_deal` | 查特价详情 | GET /resellers/v6/deals/{dealId} |

### Returns（对应官方MCP：Returns）

| Tool | 功能 | 方法+路径 |
|---|---|---|
| `ingrammicro_search_returns` | 搜索退货(RMA)申请 | GET /resellers/v6/returns/search |
| `ingrammicro_get_return` | 查退货详情 | GET /resellers/v6/returns/{caseRequestNumber} |
| `ingrammicro_create_return` | 提交退货申请 | POST /resellers/v6/returns/create |

### Freight（对应官方MCP：Freight & Shipping）

| Tool | 功能 | 方法+路径 |
|---|---|---|
| `ingrammicro_get_freight_estimate` | 运费预估 | POST /resellers/v6/freightestimate |

复杂嵌套参数（`lines`/`ship_to_info`/`end_user_info`/`reseller_info`/`shipment_details`/`additional_attributes`/`products`/`returns`等）以 `dict`/`list[dict]` 形式传入，具体字段见每个工具自己的参数说明（已对照官方 OpenAPI spec 核实字段名）。

`ingrammicro_search_quotes`/`ingrammicro_create_quote`/`ingrammicro_get_freight_estimate` 额外要求一个 `requester_email` 参数（对应上游 `IM-CustomerContact`/`CustomerContact`：发起请求的登录用户邮箱）——这是调用方个人身份信息，不是租户级凭据，所以做成工具参数而不是网关 Header。

## 测试示例

```bash
curl -X POST http://localhost:8080/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -H "X-IngramMicro-Client-Id: <client_id>" \
  -H "X-IngramMicro-Client-Secret: <client_secret>" \
  -H "X-IngramMicro-Customer-Number: 20-222222" \
  -H "X-IngramMicro-Country-Code: US" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "ingrammicro_validate_quote_to_order",
      "arguments": { "quote_number": "QUO-14551943-D2Y9L9" }
    }
  }'
```

> ⚠️ 本仓库为公开仓库，请勿在任何提交的文件中写入真实的 client_id/client_secret/customer_number 等敏感信息。

## API Reference

- Official OpenAPI 3.0 spec (source of truth used for this build): https://github.com/ingrammicro-xvantage/xi-sdk-openapispec/blob/main/openapispec/unified/XI-Resellers-API-Spec.json
- Reseller API documentation portal: https://developer.ingrammicro.com/reseller/api-documentation/orders
- Getting started / account prerequisites: https://developer.ingrammicro.com/reseller/getting-started/api-overview
- Ingram Micro's own official MCP Server (query-only; this server supersedes it for MSPbots' purposes — see above): https://developer.ingrammicro.com/reseller/mcp-server

## Known Gaps

- **⚠️ Not yet verified against a real Ingram Micro account.** This build
  was written entirely from Ingram Micro's own published OpenAPI spec —
  schema/tool count confirmed via the real MCP protocol (`tools/list`, 24
  tools) and unit tests passing, but no call has been exercised against
  a real, credentialed Ingram Micro reseller account. Getting one requires
  an existing reseller relationship with sales history (see
  Authentication) — needs re-verification once real sandbox or production
  credentials are available.
- **Sandbox base URL is unconfirmed.** Ingram Micro's own sources
  disagree: the support/auth documentation references a
  `https://api.ingrammicro.com:443/sandbox` path, while the official
  OpenAPI spec's own `servers` block lists a single URL
  (`https://api.ingrammicro.com:443/`) labeled "Sandbox" with no `/sandbox`
  suffix. `INGRAMMICRO_BASE_URL` is fully overridable specifically so this
  can be corrected without a code change once confirmed.
- **`IM-ApplicationID` vs `IM-SenderID`**: Ingram's own spec documents
  Invoices/Deals-details as requiring `IM-ApplicationID` while every other
  endpoint documents the identical concept as `IM-SenderID`. Treated as a
  spec-naming inconsistency rather than two different things — this
  server sends both headers with the same configured sender id on every
  call rather than guessing which name a given endpoint actually
  validates.
- **Webhooks (`Order Status`, `Stock Update`) are out of scope.** These
  are inbound push notifications Ingram Micro sends *to* a callback URL a
  reseller registers — not something an MCP tool (which the agent *calls*)
  can meaningfully wrap. `ingrammicro_create_cloud_order` (v7) is
  documented as asynchronous specifically because its real result arrives
  via this webhook mechanism, not in the tool's own response — there is no
  tool here to receive or poll for that result; a separate webhook
  receiver component would be needed for that, out of scope for this
  build.
- **Complex nested body parameters (`lines`, `ship_to_info`,
  `end_user_info`, `reseller_info`, `shipment_details`,
  `additional_attributes`) are passed through as `dict`/`list[dict]`**
  rather than fully typed as individual Python parameters — the real
  request bodies have dozens of optional nested fields per object
  (verified against the spec, field names are accurate), but modeling
  every one as a typed parameter was out of scope. Field names/shapes are
  documented in each parameter's own description.
