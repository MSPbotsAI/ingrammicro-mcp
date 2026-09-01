"""Renewal search/detail tools — read-only.

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
    async def ingrammicro_search_renewals(
        customer_order_number: Annotated[str | None, Field(description="Your own PO/order number.")] = None,
        ingram_purchase_order_number: Annotated[
            str | None, Field(description="Ingram Micro sales order number.")
        ] = None,
        serial_number: Annotated[str | None, Field(description="Product serial number.")] = None,
        vendor: Annotated[str | None, Field(description="Vendor/manufacturer name.")] = None,
        end_user: Annotated[str | None, Field(description="End-customer name.")] = None,
        opportunity_status: Annotated[
            str | None, Field(description='Renewal opportunity status: "Open" or "Closed".')
        ] = None,
        opportunity_sub_status: Annotated[
            str | None,
            Field(
                description='Sub-status, e.g. "Ready to order", "Quote pending", "Expired", '
                '"Ordered" — see Ingram Micro docs for the full list.'
            ),
        ] = None,
        page: Annotated[int | None, Field(description="Page number.")] = None,
        size: Annotated[int | None, Field(description="Records per page, default 25.")] = None,
    ) -> str:
        """Search upcoming or past subscription/support renewals by order,
        vendor, end customer, or opportunity status. Use this to find the
        renewal id before ingrammicro_get_renewal.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        body: dict = {}
        if vendor is not None:
            body["vendor"] = vendor
        if end_user is not None:
            body["endUser"] = end_user
        if opportunity_status is not None or opportunity_sub_status is not None:
            body["status"] = {
                "OpporutinyStatus": {
                    "value": opportunity_status,
                    "subStatus": opportunity_sub_status,
                }
            }
        params = {
            "customerOrderNumber": customer_order_number,
            "ingramPurchaseOrderNumber": ingram_purchase_order_number,
            "serialNumber": serial_number,
            "page": page,
            "size": size,
        }
        try:
            result = await client.post(
                "/resellers/v6/renewals/search", json_body=body, params=params
            )
            return dump_json_capped(result)
        except IngramMicroError as e:
            return e.to_envelope()

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True))
    async def ingrammicro_get_renewal(
        renewal_id: Annotated[str, Field(description="Ingram Micro's unique renewal id.")],
    ) -> str:
        """Get full detail for one renewal opportunity."""
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.get(f"/resellers/v6/renewals/{renewal_id}")
            return dump_json_capped(result)
        except IngramMicroError as e:
            return e.to_envelope()
