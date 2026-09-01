"""Invoice search/detail tools — read-only.

Verified against Ingram Micro's own published OpenAPI spec
(github.com/ingrammicro-xvantage/xi-sdk-openapispec,
openapispec/unified/XI-Resellers-API-Spec.json, checked 2026-09-01).
"""

from collections.abc import Callable
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from .._json import dump_json_capped
from ..api_client import IngramMicroClient, IngramMicroError
from ._common import NO_TOKEN


def register(mcp: FastMCP, client_factory: Callable[[], IngramMicroClient | None]) -> None:

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True))
    async def ingrammicro_search_invoices(
        invoice_number: Annotated[str | None, Field(description="Ingram Micro invoice number.")] = None,
        order_number: Annotated[str | None, Field(description="Order number the invoice is for.")] = None,
        customer_order_number: Annotated[str | None, Field(description="Your own PO/order number.")] = None,
        end_customer_order_number: Annotated[
            str | None, Field(description="The end customer's own PO number.")
        ] = None,
        invoice_status: Annotated[str | None, Field(description="Invoice status.")] = None,
        invoice_type: Annotated[str | None, Field(description="Invoice type.")] = None,
        invoice_date: Annotated[str | None, Field(description="Invoice date, YYYY-MM-DD.")] = None,
        invoice_from_date: Annotated[
            str | None, Field(description="Invoice date range start, YYYY-MM-DD.")
        ] = None,
        invoice_to_date: Annotated[
            str | None, Field(description="Invoice date range end, YYYY-MM-DD.")
        ] = None,
        invoice_due_date: Annotated[str | None, Field(description="Invoice due date, YYYY-MM-DD.")] = None,
        special_bid_number: Annotated[str | None, Field(description="Special-pricing bid number.")] = None,
        delivery_number: Annotated[str | None, Field(description="Delivery number.")] = None,
        serial_number: Annotated[str | None, Field(description="Product serial number.")] = None,
        page_number: Annotated[int | None, Field(description="Page number, default 1.")] = None,
        page_size: Annotated[int | None, Field(description="Records per page, max 100, default 25.")] = None,
    ) -> str:
        """Search invoices by order, invoice number, date range, or
        status. Use this to find the exact invoice number before calling
        ingrammicro_get_invoice.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        params = {
            "invoiceNumber": invoice_number,
            "orderNumber": order_number,
            "customerOrderNumber": customer_order_number,
            "endCustomerOrderNumber": end_customer_order_number,
            "invoiceStatus": invoice_status,
            "invoiceType": invoice_type,
            "invoiceDate": invoice_date,
            "invoiceFromDate": invoice_from_date,
            "invoiceToDate": invoice_to_date,
            "invoiceDueDate": invoice_due_date,
            "specialBidNumber": special_bid_number,
            "DeliveryNumber": delivery_number,
            "serialNumber": serial_number,
            "pageNumber": page_number,
            "pageSize": page_size,
        }
        try:
            result = await client.get("/resellers/v6/invoices", params=params)
            return dump_json_capped(result)
        except IngramMicroError as e:
            return e.to_envelope()

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True))
    async def ingrammicro_get_invoice(
        invoice_number: Annotated[str, Field(description="Ingram Micro invoice number.")],
        include_serial_numbers: Annotated[
            bool | None, Field(description="Include per-unit serial numbers in the response.")
        ] = None,
    ) -> str:
        """Get full line-level detail for one invoice."""
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.get(
                f"/resellers/v6.1/invoices/{invoice_number}",
                params={"includeSerialNumbers": include_serial_numbers},
            )
            return dump_json_capped(result)
        except IngramMicroError as e:
            return e.to_envelope()
