"""Special-pricing deal search/detail tools — read-only.

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
    async def ingrammicro_search_deals(
        deal_id: Annotated[str | None, Field(description="Deal/special-bid number.")] = None,
        vendor: Annotated[str | None, Field(description="Vendor/manufacturer name.")] = None,
        end_user: Annotated[str | None, Field(description="End-customer name.")] = None,
        page: Annotated[int | None, Field(description="Page number.")] = None,
        size: Annotated[int | None, Field(description="Records per page, max 100.")] = None,
    ) -> str:
        """Search special-pricing deals (vendor discount bids) by vendor
        or end customer. A deal's id can be passed as special_bid_number
        when placing an order, or as deal_id when creating a quote. Use
        this to find the exact deal id before ingrammicro_get_deal.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        params = {"dealId": deal_id, "vendor": vendor, "endUser": end_user, "Page": page, "Size": size}
        try:
            result = await client.get("/resellers/v6/deals/search", params=params)
            return dump_json_capped(result)
        except IngramMicroError as e:
            return e.to_envelope()

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True))
    async def ingrammicro_get_deal(
        deal_id: Annotated[str, Field(description="Ingram Micro's unique deal id.")],
    ) -> str:
        """Get full detail for one special-pricing deal, including which
        products/vendors it covers.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.get(f"/resellers/v6/deals/{deal_id}")
            return dump_json_capped(result)
        except IngramMicroError as e:
            return e.to_envelope()
