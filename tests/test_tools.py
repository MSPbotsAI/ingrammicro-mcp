"""tools/list snapshot + error-envelope mapping tests.

No network calls: tool enumeration goes through FastMCP's in-process
list_tools(), and the error-code mapping is tested directly against
IngramMicroError, independent of any real HTTP request.
"""

import pytest

from ingrammicro_mcp.api_client import IngramMicroError
from ingrammicro_mcp.config import Settings
from ingrammicro_mcp.server import create_mcp_server

# name -> (required params, expected annotation hint set to True)
EXPECTED_TOOLS = {
    "ingrammicro_create_order": ({"customer_order_number", "lines"}, {"destructiveHint"}),
    "ingrammicro_create_cloud_order": (set(), {"destructiveHint"}),
    "ingrammicro_modify_order": ({"order_number"}, {"idempotentHint"}),
    "ingrammicro_cancel_order": ({"order_number"}, {"destructiveHint", "idempotentHint"}),
    "ingrammicro_validate_quote_to_order": ({"quote_number"}, {"readOnlyHint", "idempotentHint"}),
}

# Tools whose docstrings deliberately exceed the SOP's 500-char description
# guideline (§2.2, a "should" not a hard rule): they carry load-bearing
# safety/disambiguation guidance (real-money order placement, narrow
# modify/cancel eligibility windows) an agent needs before calling them.
_LONG_DESCRIPTION_EXCEPTIONS = {
    "ingrammicro_create_order",
    "ingrammicro_create_cloud_order",
}


@pytest.mark.asyncio
async def test_tools_list_snapshot():
    mcp = create_mcp_server(Settings())
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    assert names == set(EXPECTED_TOOLS), f"unexpected tool set: {names}"

    by_name = {t.name: t for t in tools}
    for name, (expected_required, expected_hints) in EXPECTED_TOOLS.items():
        tool = by_name[name]
        required = set(tool.inputSchema.get("required", []))
        assert required == expected_required, f"{name}: required={required}"

        description = tool.description or ""
        if name not in _LONG_DESCRIPTION_EXCEPTIONS:
            assert len(description) <= 500, f"{name}: description too long ({len(description)})"
        first_line = description.strip().splitlines()[0] if description.strip() else ""
        assert len(first_line) <= 100, f"{name}: first line too long: {first_line!r}"
        assert "GET /" not in description and "POST /" not in description, (
            f"{name}: leaked implementation detail"
        )

        annotations = tool.annotations
        actual_hints = set()
        if annotations is not None:
            for hint in ("readOnlyHint", "destructiveHint", "idempotentHint"):
                if getattr(annotations, hint, None) is True:
                    actual_hints.add(hint)
        assert actual_hints == expected_hints, f"{name}: hints={actual_hints}"


@pytest.mark.asyncio
async def test_service_instructions_present_and_bounded():
    mcp = create_mcp_server(Settings())
    assert mcp.instructions
    assert len(mcp.instructions) <= 1500


@pytest.mark.asyncio
async def test_create_cloud_order_rejects_neither_quote_nor_lines():
    """Confirm the manual guardrail actually runs — since neither
    quote_number nor lines is in the JSON Schema `required` array (both are
    individually optional; the API needs at least one), this must be
    enforced in the tool body, not by schema validation alone.
    """
    from mcp.server.fastmcp import FastMCP

    from ingrammicro_mcp.tools import orders

    captured = {}

    class _StubClient:
        async def post(self, path, json_body=None):
            captured["called"] = path
            return {"ok": True}

    mcp = FastMCP(name="test")
    orders.register(mcp, lambda: _StubClient())
    result = await mcp.call_tool("ingrammicro_create_cloud_order", {})
    content = result[0] if isinstance(result, tuple) else result
    text = content[0].text if isinstance(content, list) else str(content)
    assert "invalid_argument" in text
    assert "called" not in captured, "must reject before ever calling the API"


@pytest.mark.parametrize(
    "status_code,expected_code,expected_retryable",
    [
        (0, "upstream_error", True),
        (400, "invalid_argument", False),
        (401, "unauthorized", False),
        (403, "unauthorized", False),
        (404, "not_found", False),
        (422, "invalid_argument", False),
        (429, "rate_limited", True),
        (500, "upstream_error", True),
        (503, "upstream_error", True),
    ],
)
def test_error_envelope_mapping(status_code, expected_code, expected_retryable):
    import json

    err = IngramMicroError(status_code, "boom")
    envelope = json.loads(err.to_envelope())
    assert envelope["error"]["code"] == expected_code
    assert envelope["error"]["retryable"] is expected_retryable
    assert envelope["error"]["message"] == "boom"
