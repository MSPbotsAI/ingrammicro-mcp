"""Freight cost estimate tool — read-only.

Verified against Ingram Micro's own published OpenAPI spec
(github.com/ingrammicro-xvantage/xi-sdk-openapispec,
openapispec/unified/XI-Resellers-API-Spec.json, checked 2026-09-01).

Requires Ingram's IM-CustomerContact header (the requesting user's email) —
exposed as a tool parameter (requester_email) for the same reason as in
tools/quotes.py.
"""

from collections.abc import Callable
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from .._json import dump_json_capped
from ..api_client import IngramMicroClient, IngramMicroError
from ._common import NO_TOKEN

_SHIP_TO_ADDRESS_DESC = (
    'Shipping destination(s) (used only if ship_to_address_id is not given): '
    '[{"companyName", "addressLine1/2/3", "city", "state", "postalCode", '
    '"countryCode"}].'
)
_LINES_DESC = (
    'Line items to estimate: [{"customerLineNumber", "ingramPartNumber", '
    '"quantity", "warehouseId", "carrierCode"}].'
)


def register(mcp: FastMCP, client_factory: Callable[[], IngramMicroClient | None]) -> None:

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True))
    async def ingrammicro_get_freight_estimate(
        requester_email: Annotated[
            str, Field(description="Email of the person requesting this estimate (Ingram requires it).")
        ],
        lines: Annotated[list[dict], Field(description=_LINES_DESC)],
        bill_to_address_id: Annotated[
            str | None, Field(description="Billing address suffix from onboarding.")
        ] = None,
        ship_to_address_id: Annotated[
            str | None,
            Field(
                description="Ingram-issued shipping address id from onboarding. "
                "Preferred over ship_to_address."
            ),
        ] = None,
        ship_to_address: Annotated[list[dict] | None, Field(description=_SHIP_TO_ADDRESS_DESC)] = None,
    ) -> str:
        """Estimate freight/shipping cost for a set of SKUs and quantities
        before placing an order — check this when shipping cost matters
        to the customer's decision.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        body: dict = {"lines": lines}
        if bill_to_address_id is not None:
            body["billToAddressId"] = bill_to_address_id
        if ship_to_address_id is not None:
            body["shipToAddressId"] = ship_to_address_id
        if ship_to_address is not None:
            body["shipToAddress"] = ship_to_address
        try:
            result = await client.post(
                "/resellers/v6/freightestimate",
                json_body=body,
                extra_headers={"IM-CustomerContact": requester_email},
            )
            return dump_json_capped(result)
        except IngramMicroError as e:
            return e.to_envelope()
