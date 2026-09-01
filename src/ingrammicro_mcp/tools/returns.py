"""Product return (RMA) search/detail/create tools.

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

_RETURN_LIST_DESC = (
    'Return line requests: [{"invoiceNumber" (required), "invoiceDate" '
    '(required, YYYY-MM-DD), "customerOrderNumber", "ingramPartNumber", '
    '"vendorPartNumber", "serialNumber", "quantity" (required), '
    '"primaryReason" (required), "secondaryReason" (required), "notes", '
    '"referenceNumber", "billToAddressId", "numberOfBoxes" (required), '
    '"shipFromInfo" (required): [{"companyName", "contact", "addressLine1", '
    '"city", "state", "postalCode", "countryCode", "email" — all required, '
    '"addressLine2/3", "phoneNumber" optional}]}].'
)


def register(mcp: FastMCP, client_factory: Callable[[], IngramMicroClient | None]) -> None:

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True))
    async def ingrammicro_search_returns(
        case_request_number: Annotated[
            str | None, Field(description="Unique return request number.")
        ] = None,
        invoice_number: Annotated[
            str | None, Field(description="Invoice number the return is against.")
        ] = None,
        return_claim_id: Annotated[str | None, Field(description="Unique return claim id.")] = None,
        reference_number: Annotated[str | None, Field(description="Return reference number.")] = None,
        ingram_part_number: Annotated[
            str | None, Field(description="Ingram Micro SKU being returned.")
        ] = None,
        vendor_part_number: Annotated[
            str | None, Field(description="Vendor SKU being returned.")
        ] = None,
        return_status: Annotated[
            str | None,
            Field(
                description="Comma-separated statuses: Open, Approved, "
                "Partially Approved, Denied, Voided."
            ),
        ] = None,
        page: Annotated[int | None, Field(description="Page number.")] = None,
        size: Annotated[int | None, Field(description="Records per page, default 25.")] = None,
    ) -> str:
        """Search return (RMA) requests by invoice, product, or status.
        Use this to find the exact case_request_number before calling
        ingrammicro_get_return.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        params = {
            "caseRequestNumber": case_request_number,
            "invoiceNumber": invoice_number,
            "returnClaimId": return_claim_id,
            "referenceNumber": reference_number,
            "ingramPartNumber": ingram_part_number,
            "vendorPartNumber": vendor_part_number,
            "returnStatus-in": return_status,
            "page": page,
            "size": size,
        }
        try:
            result = await client.get("/resellers/v6/returns/search", params=params)
            return dump_json_capped(result)
        except IngramMicroError as e:
            return e.to_envelope()

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True))
    async def ingrammicro_get_return(
        case_request_number: Annotated[str, Field(description="Unique return request number.")],
    ) -> str:
        """Get full detail and current status for one return (RMA) request."""
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.get(f"/resellers/v6/returns/{case_request_number}")
            return dump_json_capped(result)
        except IngramMicroError as e:
            return e.to_envelope()

    @mcp.tool(annotations=ToolAnnotations(destructiveHint=True, idempotentHint=False))
    async def ingrammicro_create_return(
        returns: Annotated[list[dict], Field(description=_RETURN_LIST_DESC)],
    ) -> str:
        """File one or more return (RMA) requests against already-invoiced
        product. Each entry needs the original invoice, a quantity,
        primary/secondary reason, box count, and a full ship-from address
        — Ingram rejects a request missing any of those. Confirm with a
        human before filing; a filed return cannot be un-filed through
        this API.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.post("/resellers/v6/returns/create", json_body={"list": returns})
            return dump_json_capped(result)
        except IngramMicroError as e:
            return e.to_envelope()
