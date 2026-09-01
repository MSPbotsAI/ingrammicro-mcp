"""Product catalog / pricing / availability — read-only lookup tools.

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
    async def ingrammicro_search_products(
        keyword: Annotated[
            list[str] | None,
            Field(
                description="Free-text keyword(s): Ingram/vendor part number, "
                "product title, or vendor name."
            ),
        ] = None,
        vendor: Annotated[list[str] | None, Field(description="Vendor/manufacturer name(s).")] = None,
        vendor_number: Annotated[str | None, Field(description="Vendor number.")] = None,
        vendor_part_number: Annotated[
            list[str] | None, Field(description="Vendor's own part number(s).")
        ] = None,
        category: Annotated[str | None, Field(description='Product category, e.g. "Displays".')] = None,
        sku_type: Annotated[
            str | None,
            Field(description='SKU type: "IM::physical", "IM::digital", or "IM::any".'),
        ] = None,
        has_discounts: Annotated[
            bool | None, Field(description="Filter to products with an available discount.")
        ] = None,
        page_number: Annotated[int | None, Field(description="Page number, default 1.")] = None,
        page_size: Annotated[int | None, Field(description="Records per page, max 100, default 25.")] = None,
    ) -> str:
        """Search Ingram Micro's product catalog by keyword, vendor,
        category, or SKU type. "What's the Ingram part number for Cisco
        switch model X" or "list Microsoft cloud SKUs with discounts" both
        start here. Returns matching products with Ingram/vendor part
        numbers; call ingrammicro_get_price_and_availability next for
        live pricing/stock.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        params = {
            "keyword": keyword,
            "vendor": vendor,
            "vendorNumber": vendor_number,
            "vendorPartNumber": vendor_part_number,
            "category": category,
            "type": sku_type,
            "hasDiscounts": has_discounts,
            "pageNumber": page_number,
            "pageSize": page_size,
        }
        try:
            result = await client.get("/resellers/v6/catalog", params=params)
            return dump_json_capped(result)
        except IngramMicroError as e:
            return e.to_envelope()

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True))
    async def ingrammicro_get_product_detail(
        ingram_part_number: Annotated[
            str, Field(description="Ingram Micro's own unique SKU for the product (max 6 chars).")
        ],
    ) -> str:
        """Get full catalog detail for one product by its Ingram Micro part
        number (from ingrammicro_search_products). Use
        ingrammicro_get_product_detail_by_reference instead if you only
        have the vendor's own part number or a subscription plan id/name.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        try:
            result = await client.get(f"/resellers/v6/catalog/details/{ingram_part_number}")
            return dump_json_capped(result)
        except IngramMicroError as e:
            return e.to_envelope()

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True))
    async def ingrammicro_get_product_detail_by_reference(
        vendor_part_number: Annotated[
            str | None, Field(description="The vendor's own part number for the product.")
        ] = None,
        plan_id: Annotated[
            str | None, Field(description="Subscription plan id (for cloud/subscription SKUs).")
        ] = None,
        plan_name: Annotated[
            str | None, Field(description="Subscription plan name (for cloud/subscription SKUs).")
        ] = None,
    ) -> str:
        """Get catalog detail for a product identified by the vendor's own
        part number, or by subscription plan id/name — for when you don't
        have Ingram's own part number. Exactly one of vendor_part_number,
        plan_id, or plan_name must be given.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        params = {"vendorPartNumber": vendor_part_number, "planId": plan_id, "planName": plan_name}
        try:
            result = await client.get("/resellers/v6/catalog/details", params=params)
            return dump_json_capped(result)
        except IngramMicroError as e:
            return e.to_envelope()

    @mcp.tool(annotations=ToolAnnotations(readOnlyHint=True, idempotentHint=True))
    async def ingrammicro_get_price_and_availability(
        products: Annotated[
            list[dict],
            Field(
                description='Products to price/check: [{"ingramPartNumber"} or '
                '{"vendorPartNumber"}]. Mix of both forms across entries is fine.'
            ),
        ],
        include_pricing: Annotated[
            bool, Field(description="Include live pricing in the response.")
        ] = True,
        include_availability: Annotated[
            bool, Field(description="Include per-warehouse stock availability in the response.")
        ] = True,
        include_product_attributes: Annotated[
            bool | None, Field(description="Also include detailed product attributes.")
        ] = None,
        availability_by_warehouse: Annotated[
            list[dict] | None,
            Field(
                description='Restrict availability to specific warehouses: '
                '[{"availabilityByWarehouseId": <id>}].'
            ),
        ] = None,
    ) -> str:
        """Get real-time price and/or stock availability for one or more
        SKUs — the step before placing an order, to confirm current price
        and that stock exists before calling ingrammicro_create_order.
        """
        client = client_factory()
        if client is None:
            return NO_TOKEN
        body: dict = {"products": products}
        if availability_by_warehouse is not None:
            body["availabilityByWarehouse"] = availability_by_warehouse
        params = {
            "includeAvailability": include_availability,
            "includePricing": include_pricing,
            "includeProductAttributes": include_product_attributes,
        }
        try:
            result = await client.post(
                "/resellers/v6/catalog/priceandavailability", json_body=body, params=params
            )
            return dump_json_capped(result)
        except IngramMicroError as e:
            return e.to_envelope()
