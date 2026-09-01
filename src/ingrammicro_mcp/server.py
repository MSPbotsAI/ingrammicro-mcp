import contextvars
import sys
from collections.abc import Callable

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .api_client import IngramMicroClient
from .config import Settings

# ─────────────────────────────────────────────────────────────────────────────
# Per-request credential contextvar for gateway mode.
# GatewayTokenMiddleware sets this before the MCP handler runs.
# Python asyncio copies context per task, so concurrent requests are isolated.
# Value is (client_id, client_secret, customer_number, country_code).
# ─────────────────────────────────────────────────────────────────────────────
_gateway_creds_var: contextvars.ContextVar[tuple[str, str, str, str] | None] = (
    contextvars.ContextVar("ingrammicro_gateway_creds", default=None)
)


def get_client_from_context(settings: Settings) -> IngramMicroClient | None:
    """Resolve the active IngramMicroClient for the current request context."""
    if settings.auth_mode == "gateway":
        creds = _gateway_creds_var.get()
        if creds is None:
            return None
        client_id, client_secret, customer_number, country_code = creds
    else:
        client_id = settings.ingrammicro_client_id
        client_secret = settings.ingrammicro_client_secret
        customer_number = settings.ingrammicro_customer_number
        country_code = settings.ingrammicro_country_code

    if not client_id or not client_secret or not customer_number or not country_code:
        return None
    return IngramMicroClient(
        client_id,
        client_secret,
        customer_number,
        country_code,
        settings.ingrammicro_sender_id,
        settings.ingrammicro_base_url,
    )


class GatewayTokenMiddleware:
    """ASGI middleware for gateway mode.

    Reads the four configured credential headers from each request and
    stores them in the contextvar for the duration of that request. Returns
    401 if any is missing on /mcp requests.
    """

    def __init__(self, app: ASGIApp, settings: Settings):
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        if not path.startswith("/mcp"):
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        s = self.settings
        # Header lookup is case-insensitive in Starlette.
        client_id = request.headers.get(s.ingrammicro_client_id_header.lower())
        client_secret = request.headers.get(s.ingrammicro_client_secret_header.lower())
        customer_number = request.headers.get(s.ingrammicro_customer_number_header.lower())
        country_code = request.headers.get(s.ingrammicro_country_code_header.lower())
        required_headers = [
            s.ingrammicro_client_id_header,
            s.ingrammicro_client_secret_header,
            s.ingrammicro_customer_number_header,
            s.ingrammicro_country_code_header,
        ]
        if not client_id or not client_secret or not customer_number or not country_code:
            response = JSONResponse(
                {
                    "error": "Missing credentials",
                    "message": f"Gateway mode requires the {', '.join(required_headers)} headers",
                    "required_headers": required_headers,
                },
                status_code=401,
            )
            await response(scope, receive, send)
            return

        ctx_token = _gateway_creds_var.set(
            (client_id, client_secret, customer_number, country_code)
        )
        try:
            await self.app(scope, receive, send)
        finally:
            _gateway_creds_var.reset(ctx_token)


def create_mcp_server(settings: Settings) -> FastMCP:
    """Build the FastMCP server instance and register all tools."""
    # DNS-rebinding protection is disabled because the container runs behind
    # mcp-gateway on an internal Docker network and is never publicly exposed.
    mcp = FastMCP(
        name="ingrammicro-mcp",
        instructions=(
            "Ingram Micro is a technology distributor — resellers buy hardware, "
            "software licenses, and cloud subscriptions through it to fulfill "
            "their own customers' orders. This server wraps the full non-"
            "webhook Ingram Micro Reseller API: product catalog/pricing, "
            "quotes, order placement/change/cancel/lookup, invoices, "
            "renewals, special-pricing deals, returns, and freight "
            "estimates — the single connector for Ingram Micro, no separate "
            "connector needed. Typical flow: ingrammicro_search_products -> "
            "ingrammicro_get_price_and_availability -> "
            "ingrammicro_create_order (stocked/direct-ship/licensing/warranty "
            "SKUs) or ingrammicro_create_cloud_order (cloud subscriptions, "
            "Quote-to-Order/Configure-to-Order — validate first with "
            "ingrammicro_validate_quote_to_order). ingrammicro_modify_order/"
            "ingrammicro_cancel_order only work in a narrow window before "
            "Ingram releases the order to its warehouse. Every order-"
            "placing/modifying call is real spend against the reseller's "
            "net-terms account — always confirm SKU, quantity, and price "
            "with a human before calling."
        ),
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )

    client_factory: Callable[[], IngramMicroClient | None] = lambda: get_client_from_context(  # noqa: E731
        settings
    )

    if not settings.has_credentials:
        print(
            "Warning: No Ingram Micro credentials found. Tools will return "
            "not_configured errors until credentials are supplied.",
            file=sys.stderr,
        )

    from .tools import catalog, deals, freight, invoices, orders, quotes, renewals, returns

    catalog.register(mcp, client_factory)
    orders.register(mcp, client_factory)
    quotes.register(mcp, client_factory)
    invoices.register(mcp, client_factory)
    renewals.register(mcp, client_factory)
    deals.register(mcp, client_factory)
    returns.register(mcp, client_factory)
    freight.register(mcp, client_factory)

    return mcp
