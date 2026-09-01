"""Quote search/detail/create and Quote-to-Order validation tools.

Verified against Ingram Micro's own published OpenAPI spec
(github.com/ingrammicro-xvantage/xi-sdk-openapispec,
openapispec/unified/XI-Resellers-API-Spec.json, checked 2026-09-01).

ingrammicro_search_quotes requires Ingram's IM-CustomerContact header (the
requesting user's email) — exposed here as a tool parameter (requester_email)
rather than a fixed gateway setting, since it identifies the calling
*person*, not the reseller account.
"""

from collections.abc import Callable
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from .._json import dump_json_capped
from ..api_client import IngramMicroClient, IngramMicroError
from ._common import NO_TOKEN

_QUOTE_PRODUCTS_DESC = (
    'Line items: [{"customerLineNumber", "ingramPartNumber", "vendorPartNumber", '
    '"quantity", "specialBid", "lineLevelNotes", "pricingType"}].'
)
_END_USER_INFO_DESC = (
    'Optional end-customer identity: {"companyName", "contact", "addressLine1/2", '
    '"city", "state", "postalCode", "countryCode", "email", "phoneNumber"}.'
)


def register(mcp: FastMCP, client_factory: Callable[[], IngramMicroClient | None]) -> None:

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True))
    async def ingrammicro_search_quotes(
        requester_email: Annotated[
            str, Field(description="Email of the person requesting this search (Ingram requires it).")
        ],
        quote_number: Annotated[
            str | None, Field(description='Quote number, e.g. "QUO-10985-C4C3F7".')
        ] = None,
        special_bid_number: Annotated[str | None, Field(description="Special-pricing bid number.")] = None,
        end_user_contact: Annotated[str | None, Field(description="End-customer name on the quote.")] = None,
        vendor_name: Annotated[str | None, Field(description="Vendor/manufacturer name.")] = None,
        quote_name: Annotated[str | None, Field(description="Quote name given at creation time.")] = None,
        status: Annotated[str | None, Field(description='Quote status, e.g. "Ready to Order".')] = None,
        page_number: Annotated[int | None, Field(description="Page number, default 1.")] = None,
        page_size: Annotated[int | None, Field(description="Records per page, default 25.")] = None,
    ) -> str:
        """Search quotes by number, status, vendor, or end customer. Use
        this to find a quote's number before ingrammicro_get_quote,
        ingrammicro_validate_quote_to_order, or converting it to an order
        with ingrammicro_create_cloud_order.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        params = {
            "quoteNumber": quote_number,
            "specialBidNumber": special_bid_number,
            "endUserContact": end_user_contact,
            "vendorName": vendor_name,
            "quoteName": quote_name,
            "status": status,
            "pageNumber": page_number,
            "pageSize": page_size,
        }
        try:
            result = await client.get(
                "/resellers/v6/quotes/search",
                params=params,
                extra_headers={"IM-CustomerContact": requester_email},
            )
            return dump_json_capped(result)
        except IngramMicroError as e:
            return e.to_envelope()

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True))
    async def ingrammicro_get_quote(
        quote_number: Annotated[str, Field(description='Quote number, e.g. "QUO-10926-Y8G1B3".')],
    ) -> str:
        """Get full detail for one quote — line items, pricing, expiry,
        and current status.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.get(f"/resellers/v6/quotes/{quote_number}")
            return dump_json_capped(result)
        except IngramMicroError as e:
            return e.to_envelope()

    @mcp.tool()
    async def ingrammicro_create_quote(
        requester_email: Annotated[
            str, Field(description="Email of the person creating this quote (Ingram requires it).")
        ],
        products: Annotated[list[dict], Field(description=_QUOTE_PRODUCTS_DESC)],
        quote_name: Annotated[str | None, Field(description="Reference name for the quote.")] = None,
        first_name: Annotated[str | None, Field(description="Requester's first name.")] = None,
        last_name: Annotated[str | None, Field(description="Requester's last name.")] = None,
        quote_expiry_date: Annotated[str | None, Field(description="Date the quote should expire.")] = None,
        customer_need: Annotated[
            str | None, Field(description="Free-text note on what the customer needs.")
        ] = None,
        end_user_info: Annotated[dict | None, Field(description=_END_USER_INFO_DESC)] = None,
        deal_id: Annotated[
            str | None, Field(description="Special-pricing deal id to apply to the quote.")
        ] = None,
        pricing_type: Annotated[str | None, Field(description="Pricing type for the quote.")] = None,
        send_quote_copy: Annotated[
            str | None, Field(description="Comma-separated emails to send the quote to (max 10).")
        ] = None,
    ) -> str:
        """Create a new quote — a price hold, not a purchase. Convert it
        to a real order later with
        ingrammicro_create_cloud_order(quote_number=...) after validating
        with ingrammicro_validate_quote_to_order.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        body: dict = {"CustomerContact": requester_email, "products": products}
        if quote_name is not None:
            body["quoteName"] = quote_name
        if first_name is not None:
            body["firstname"] = first_name
        if last_name is not None:
            body["lastname"] = last_name
        if quote_expiry_date is not None:
            body["quoteExpiryDate"] = quote_expiry_date
        if customer_need is not None:
            body["customerNeed"] = customer_need
        if end_user_info is not None:
            body["endUserInfo"] = end_user_info
        if deal_id is not None:
            body["dealId"] = deal_id
        if pricing_type is not None:
            body["pricingType"] = pricing_type
        if send_quote_copy is not None:
            body["sendQuoteCopy"] = send_quote_copy
        try:
            result = await client.post("/resellers/v6/quotes/create", json_body=body)
            return dump_json_capped(result)
        except IngramMicroError as e:
            return e.to_envelope()

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True))
    async def ingrammicro_validate_quote_to_order(
        quote_number: Annotated[
            str, Field(description='Ingram Micro quote number, e.g. "QUO-14551943-D2Y9L9".')
        ],
    ) -> str:
        """Validate a quote before converting it to an order, and learn
        which fields the vendor requires at header and line level for the
        Quote-to-Order call.

        Always call this before ingrammicro_create_cloud_order(quote_number=...)
        — the response's vmfAdditionalAttributes (header level) and each
        line's vmfAdditionalAttributesLines name the exact vendor-mandatory
        fields to copy into that call's additional_attributes.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.get(
                "/resellers/v6/q2o/validatequote", params={"quoteNumber": quote_number}
            )
            return dump_json_capped(result)
        except IngramMicroError as e:
            return e.to_envelope()
