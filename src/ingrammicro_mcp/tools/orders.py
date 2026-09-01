"""Order placement, modification, and lookup tools.

Verified against Ingram Micro's own published OpenAPI spec
(github.com/ingrammicro-xvantage/xi-sdk-openapispec,
openapispec/unified/XI-Resellers-API-Spec.json, checked 2026-09-01).

Every tool here spends real money against the reseller's Ingram Micro
net-terms account — Ingram does not support credit-card API ordering, only
net-terms trade credit, so a bad order is a real invoice, not a rejected
charge. Always confirm SKU/quantity/price with a human before calling
create_order/create_cloud_order.
"""

from collections.abc import Callable
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from .._json import dump_json_capped, error_envelope
from ..api_client import IngramMicroClient, IngramMicroError
from ._common import NO_TOKEN

_LINES_DESC = (
    'Order line items: [{"customerLineNumber": <unique numeric string, '
    '1-884>, "ingramPartNumber": <Ingram\'s own SKU, required>, '
    '"quantity": <int>, "unitPrice": <optional decimal, not guaranteed>, '
    '"specialBidNumber": <optional, line-level pricing bid>, "notes": '
    '<optional>}]. Resolve ingramPartNumber via Ingram Micro\'s own MCP '
    "Server's product/catalog search first — this server has no catalog "
    "lookup of its own."
)
_RESELLER_INFO_DESC = (
    "Optional reseller identity/address override: {\"resellerId\", "
    '"companyName", "contact", "addressLine1/2/3", "city", "state", '
    '"postalCode", "countryCode", "phoneNumber", "email"}. Omit to use the '
    "account's on-file reseller info."
)
_SHIP_TO_DESC = (
    'Optional shipping destination override: {"addressId" (Ingram-issued '
    'address id from onboarding), "contact", "companyName", "name1", '
    '"name2", "addressLine1/2/3", "city", "state", "postalCode", '
    '"countryCode", "phoneNumber", "email"}. Omit to ship to the address '
    "tied to addressId on the account."
)
_END_USER_INFO_DESC = (
    'Optional end-customer identity, used for pricing/discount purposes: '
    '{"endUserId", "contact", "companyName", "name1", "name2", '
    '"addressLine1/2/3", "city", "state", "postalCode", "countryCode", '
    '"phoneNumber", "email"}.'
)
_SHIPMENT_DETAILS_DESC = (
    'Optional shipping instructions: {"carrierCode", "freightAccountNumber" '
    '(bill reseller\'s own carrier account directly), "shipComplete" '
    '("true"/"C"=hold until all lines ship, "P"=ship-complete per line, '
    '"E"=ship-complete across all distributions), "requestedDeliveryDate" '
    '(date, not guaranteed), "signatureRequired" (bool), '
    '"shippingInstructions"}.'
)
_ADDITIONAL_ATTRIBUTES_DESC = (
    'Optional Ingram-specific flags as [{"attributeName", "attributeValue"}]'
    ' pairs — e.g. allowPartialOrder, allowDuplicateCustomerOrderNumber, '
    "government-order fields (govtProgramType, govtEndUserType, etc). Rarely "
    "needed; omit unless a specific Ingram-documented flag is required."
)


def register(mcp: FastMCP, client_factory: Callable[[], IngramMicroClient | None]) -> None:

    @mcp.tool(annotations=ToolAnnotations(destructiveHint=True, idempotentHint=False))
    async def ingrammicro_create_order(
        customer_order_number: Annotated[
            str,
            Field(
                description="Your own unique PO/order number for this order "
                "(max 35 chars). Ingram Micro tracks orders by this, not just "
                "its own order number — reuse of a number that already "
                "exists is rejected unless allowDuplicateCustomerOrderNumber "
                "is set via additional_attributes."
            ),
        ],
        lines: Annotated[list[dict], Field(description=_LINES_DESC)],
        end_customer_order_number: Annotated[
            str | None, Field(description="The end customer's own PO number, if any.")
        ] = None,
        bill_to_address_id: Annotated[
            str | None,
            Field(description="Billing address suffix issued during onboarding. Omit for the default."),
        ] = None,
        special_bid_number: Annotated[
            str | None,
            Field(
                description="Header-level special-pricing bid number from the vendor. "
                "Line-level bids in `lines` take precedence."
            ),
        ] = None,
        notes: Annotated[str | None, Field(description="Order-level notes.")] = None,
        accept_back_order: Annotated[
            bool | None,
            Field(
                description="Accept the order even if a line is backordered. Ignored if "
                "shipment_details.shipComplete is set."
            ),
        ] = None,
        vendor_auth_number: Annotated[
            str | None,
            Field(
                description="Vendor authorization number — REQUIRED for warranty-SKU orders "
                "(the specific vendor mandates this; ask Ingram Micro sales which vendors need "
                "it). Without it, warranty orders are placed on hold."
            ),
        ] = None,
        reseller_info: Annotated[dict | None, Field(description=_RESELLER_INFO_DESC)] = None,
        ship_to_info: Annotated[dict | None, Field(description=_SHIP_TO_DESC)] = None,
        end_user_info: Annotated[dict | None, Field(description=_END_USER_INFO_DESC)] = None,
        shipment_details: Annotated[dict | None, Field(description=_SHIPMENT_DETAILS_DESC)] = None,
        additional_attributes: Annotated[
            list[dict] | None, Field(description=_ADDITIONAL_ATTRIBUTES_DESC)
        ] = None,
    ) -> str:
        """Place a real purchase order for stocked, direct-ship, licensing,
        or warranty SKUs. Real money against the reseller's net-terms
        account — Ingram does not support credit-card API ordering.

        For cloud subscriptions, Quote-to-Order, or Configure-to-Order, use
        ingrammicro_create_cloud_order instead — this tool is for standard
        SKU ordering only. Confirm every SKU/quantity/price with a human
        first; there is no dry-run mode. Returns per-line success/error/
        warning counts and, on partial failure, a rejectedLineItems list
        naming exactly which lines failed and why.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        body: dict = {"customerOrderNumber": customer_order_number, "lines": lines}
        if end_customer_order_number is not None:
            body["endCustomerOrderNumber"] = end_customer_order_number
        if bill_to_address_id is not None:
            body["billToAddressId"] = bill_to_address_id
        if special_bid_number is not None:
            body["specialBidNumber"] = special_bid_number
        if notes is not None:
            body["notes"] = notes
        if accept_back_order is not None:
            body["acceptBackOrder"] = accept_back_order
        if vendor_auth_number is not None:
            body["vmf"] = {"vendAuthNumber": vendor_auth_number}
        if reseller_info is not None:
            body["resellerInfo"] = reseller_info
        if ship_to_info is not None:
            body["shipToInfo"] = ship_to_info
        if end_user_info is not None:
            body["endUserInfo"] = end_user_info
        if shipment_details is not None:
            body["shipmentDetails"] = shipment_details
        if additional_attributes is not None:
            body["additionalAttributes"] = additional_attributes
        try:
            result = await client.post("/resellers/v6/orders", body)
            return dump_json_capped(result)
        except IngramMicroError as e:
            return e.to_envelope()

    @mcp.tool(annotations=ToolAnnotations(destructiveHint=True, idempotentHint=False))
    async def ingrammicro_create_cloud_order(
        customer_order_number: Annotated[
            str | None,
            Field(
                description="Your own order number for reference (max 18 chars). "
                "Strongly recommended even though not strictly required."
            ),
        ] = None,
        quote_number: Annotated[
            str | None,
            Field(
                description="Ingram Micro quote number for Quote-to-Order or "
                "Configure-to-Order. When given, any SKU/quantity/price in "
                "`lines` is IGNORED — the quote's own details are used "
                "instead. Validate it first with "
                "ingrammicro_validate_quote_to_order to learn any vendor-"
                "mandatory fields to pass here."
            ),
        ] = None,
        lines: Annotated[
            list[dict] | None,
            Field(
                description='Standard-order line items (ignored in Quote-to-Order mode): '
                '[{"customerLineNumber", "ingramPartNumber", "vendorPartNumber", '
                '"quantity", "unitPrice", "endUserPrice" (required for export '
                'orders), "specialBidNumber", "notes"}]. Required unless quote_number is given.'
            ),
        ] = None,
        notes: Annotated[str | None, Field(description="Order header-level notes.")] = None,
        bill_to_address_id: Annotated[
            str | None, Field(description="Billing address suffix from onboarding.")
        ] = None,
        special_bid_number: Annotated[
            str | None, Field(description="Header-level special-pricing bid number.")
        ] = None,
        accept_back_order: Annotated[
            bool | None, Field(description="Accept the order even if backordered.")
        ] = None,
        vendor_auth_number: Annotated[
            str | None,
            Field(description="Vendor authorization number, if the specific vendor requires it."),
        ] = None,
        reseller_info: Annotated[dict | None, Field(description=_RESELLER_INFO_DESC)] = None,
        end_user_info: Annotated[dict | None, Field(description=_END_USER_INFO_DESC)] = None,
        ship_to_info: Annotated[dict | None, Field(description=_SHIP_TO_DESC)] = None,
        shipment_details: Annotated[dict | None, Field(description=_SHIPMENT_DETAILS_DESC)] = None,
        additional_attributes: Annotated[
            list[dict] | None, Field(description=_ADDITIONAL_ATTRIBUTES_DESC)
        ] = None,
    ) -> str:
        """Place a cloud-subscription order, or convert an existing Quote
        (Quote-to-Order / Configure-to-Order) into a real order.
        Asynchronous: this call only returns a confirmationNumber
        acknowledging receipt — Ingram Micro pushes the actual order
        result (success or error) later via its own webhook, not in this
        response.

        For standard stocked/direct-ship/licensing/warranty SKUs (not
        cloud, not quote-based), use ingrammicro_create_order instead.
        Real money against the reseller's net-terms account — no dry-run,
        no credit-card ordering. Always validate a quote first with
        ingrammicro_validate_quote_to_order before passing quote_number
        here.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        if not quote_number and not lines:
            return error_envelope(
                "invalid_argument",
                "Provide either quote_number (Quote-to-Order/Configure-to-Order) "
                "or lines (standard cloud order) — neither was given.",
                False,
            )
        body: dict = {}
        if customer_order_number is not None:
            body["customerOrderNumber"] = customer_order_number
        if quote_number is not None:
            body["quoteNumber"] = quote_number
        if lines is not None:
            body["lines"] = lines
        if notes is not None:
            body["notes"] = notes
        if bill_to_address_id is not None:
            body["billToAddressId"] = bill_to_address_id
        if special_bid_number is not None:
            body["specialBidNumber"] = special_bid_number
        if accept_back_order is not None:
            body["acceptBackOrder"] = accept_back_order
        if vendor_auth_number is not None:
            body["vendAuthNumber"] = vendor_auth_number
        if reseller_info is not None:
            body["resellerInfo"] = reseller_info
        if end_user_info is not None:
            body["endUserInfo"] = end_user_info
        if ship_to_info is not None:
            body["shipToInfo"] = ship_to_info
        if shipment_details is not None:
            body["shipmentDetails"] = shipment_details
        if additional_attributes is not None:
            body["additionalAttributes"] = additional_attributes
        try:
            result = await client.post("/resellers/v7/orders", body)
            return dump_json_capped(result)
        except IngramMicroError as e:
            return e.to_envelope()

    @mcp.tool(annotations=ToolAnnotations(idempotentHint=True))
    async def ingrammicro_modify_order(
        order_number: Annotated[
            str, Field(description='Ingram Micro\'s own sales order number, e.g. "20-RC1RD".')
        ],
        action_code: Annotated[
            str | None,
            Field(description='Set to "release" to release an order held with the customer-hold flag.'),
        ] = None,
        notes: Annotated[str | None, Field(description="Shipment-level notes.")] = None,
        ship_to_info: Annotated[dict | None, Field(description=_SHIP_TO_DESC)] = None,
        lines: Annotated[
            list[dict] | None,
            Field(
                description='Line changes: [{"ingramPartNumber", "ingramLineNumber", '
                '"customerLineNumber", "addUpdateDeleteLine": "ADD"|"UPDATE"|"DELETE", '
                '"quantity", "notes"}]. ingramLineNumber identifies an existing line for '
                "UPDATE/DELETE; omit it when adding a new line."
            ),
        ] = None,
        additional_attributes: Annotated[
            list[dict] | None, Field(description=_ADDITIONAL_ATTRIBUTES_DESC)
        ] = None,
    ) -> str:
        """Change an order placed with the customer-hold flag — add/update/
        delete lines, change ship-to, or release the hold.

        ONLY works within roughly 24 hours of placement, and only if the
        order was created with the customer-hold flag (void after 24h if
        never released). An order placed WITHOUT customer-hold cannot be
        modified — this call fails. Confirm with a human before changing
        quantities or the shipping address.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        body: dict = {}
        if notes is not None:
            body["notes"] = notes
        if ship_to_info is not None:
            body["shipToInfo"] = ship_to_info
        if lines is not None:
            body["lines"] = lines
        if additional_attributes is not None:
            body["additionalAttributes"] = additional_attributes
        try:
            result = await client.put(
                f"/resellers/v6/orders/{order_number}",
                params={"actionCode": action_code},
                json_body=body,
            )
            return dump_json_capped(result)
        except IngramMicroError as e:
            return e.to_envelope()

    @mcp.tool(annotations=ToolAnnotations(destructiveHint=True, idempotentHint=True))
    async def ingrammicro_cancel_order(
        order_number: Annotated[
            str, Field(description='Ingram Micro\'s own sales order number, e.g. "20-RD128".')
        ],
    ) -> str:
        """Cancel an order before it reaches Ingram Micro's warehouse.

        Irreversible once it fails: an order already released to the
        warehouse CANNOT be canceled through this API at all — Ingram
        Micro requires the order to still be on customer hold. Confirm
        with a human before calling; there is no way to check "is it too
        late" ahead of time other than trying and reading the error.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.delete(f"/resellers/v6/orders/{order_number}")
            return dump_json_capped(result) if result else dump_json_capped(
                {"orderNumber": order_number, "canceled": True}
            )
        except IngramMicroError as e:
            return e.to_envelope()

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True))
    async def ingrammicro_get_order(
        order_number: Annotated[
            str, Field(description='Ingram Micro\'s own sales order number, e.g. "20-RD3QV".')
        ],
        vendor_number: Annotated[str | None, Field(description="Filter/scope by vendor number.")] = None,
    ) -> str:
        """Get full status/line detail for one order — shipping status,
        tracking, per-line fulfillment. Use ingrammicro_search_orders
        instead if you don't already have the exact order number.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.get(
                f"/resellers/v6.1/orders/{order_number}", params={"vendorNumber": vendor_number}
            )
            return dump_json_capped(result)
        except IngramMicroError as e:
            return e.to_envelope()

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True))
    async def ingrammicro_search_orders(
        customer_order_number: Annotated[
            str | None, Field(description="Your own PO/order number for the order.")
        ] = None,
        ingram_order_number: Annotated[str | None, Field(description="Ingram Micro's order number.")] = None,
        order_status: Annotated[
            str | None,
            Field(description='One of "SHIPPED", "PROCESSING", "ON HOLD", "BACKORDERED", "CANCELLED".'),
        ] = None,
        order_date: Annotated[str | None, Field(description="Order date, YYYY-MM-DD.")] = None,
        end_customer_order_number: Annotated[
            str | None, Field(description="The end customer's own PO number.")
        ] = None,
        ingram_part_number: Annotated[str | None, Field(description="Ingram Micro SKU on the order.")] = None,
        vendor_part_number: Annotated[str | None, Field(description="Vendor's SKU on the order.")] = None,
        vendor_name: Annotated[str | None, Field(description="Vendor/manufacturer name.")] = None,
        serial_number: Annotated[str | None, Field(description="Product serial number.")] = None,
        tracking_number: Annotated[
            str | None, Field(description="Shipment tracking number (not available in Australia).")
        ] = None,
        special_bid_number: Annotated[str | None, Field(description="Special-pricing bid number.")] = None,
        page_number: Annotated[int | None, Field(description="Page number, default 1.")] = None,
        page_size: Annotated[int | None, Field(description="Records per page, max 100, default 25.")] = None,
    ) -> str:
        """Search past/current orders by PO number, status, product, or
        date. Use this to find the exact order number before calling
        ingrammicro_get_order, ingrammicro_modify_order, or
        ingrammicro_cancel_order.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        params = {
            "customerOrderNumber": customer_order_number,
            "ingramOrderNumber": ingram_order_number,
            "orderStatus": order_status,
            "ingramOrderDate": order_date,
            "endCustomerOrderNumber": end_customer_order_number,
            "ingramPartNumber": ingram_part_number,
            "vendorPartNumber": vendor_part_number,
            "vendorName": vendor_name,
            "serialNumber": serial_number,
            "trackingNumber": tracking_number,
            "specialBidNumber": special_bid_number,
            "pageNumber": page_number,
            "pageSize": page_size,
        }
        try:
            result = await client.get("/resellers/v6/orders/search", params=params)
            return dump_json_capped(result)
        except IngramMicroError as e:
            return e.to_envelope()
