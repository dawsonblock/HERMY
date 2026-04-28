"""Tests for best-effort upstream schema injection in the CUA proxy.

Verifies that:
  - When upstream returns descriptions, proxy tool docstrings contain them.
  - When upstream is unreachable, tools are still registered with a fallback doc.
  - A Hermes-like caller can invoke a proxy tool even without strict schema.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from cua_bridge.cua_mcp_proxy import (
    ALLOWED_CUA_TOOLS,
    CuaMcpProxy,
    FastMCP,
    _fetch_upstream_schemas,
    _register_tool_proxy,
    create_proxy_mcp_server_async,
)


# ---------------------------------------------------------------------------
# _fetch_upstream_schemas
# ---------------------------------------------------------------------------

def test_fetch_upstream_schemas_returns_descriptions():
    proxy = CuaMcpProxy.__new__(CuaMcpProxy)
    upstream_tools = [
        {"name": "computer_screenshot", "description": "Take a screenshot of the screen."},
        {"name": "computer_click", "description": "Click at (x, y)."},
    ]
    mock_list = AsyncMock(return_value=upstream_tools)

    with patch.object(CuaMcpProxy, "list_upstream_tools", mock_list):
        result = asyncio.run(_fetch_upstream_schemas(proxy))

    assert result["computer_screenshot"] == "Take a screenshot of the screen."
    assert result["computer_click"] == "Click at (x, y)."


def test_fetch_upstream_schemas_returns_empty_on_error():
    proxy = CuaMcpProxy.__new__(CuaMcpProxy)
    mock_list = AsyncMock(side_effect=ConnectionError("upstream down"))

    with patch.object(CuaMcpProxy, "list_upstream_tools", mock_list):
        result = asyncio.run(_fetch_upstream_schemas(proxy))

    assert result == {}


def test_fetch_upstream_schemas_skips_entries_without_name():
    proxy = CuaMcpProxy.__new__(CuaMcpProxy)
    upstream_tools = [
        {"description": "no name here"},
        {"name": "computer_type", "description": "Type text."},
        {},
    ]
    mock_list = AsyncMock(return_value=upstream_tools)

    with patch.object(CuaMcpProxy, "list_upstream_tools", mock_list):
        result = asyncio.run(_fetch_upstream_schemas(proxy))

    assert list(result.keys()) == ["computer_type"]


# ---------------------------------------------------------------------------
# _register_tool_proxy docstring injection
# ---------------------------------------------------------------------------

def test_register_tool_injects_upstream_description():
    proxy = CuaMcpProxy.__new__(CuaMcpProxy)
    proxy.upstream_url = "http://fake"
    proxy._client = None
    mcp = FastMCP(name="test")

    _register_tool_proxy(mcp, proxy, "computer_screenshot", upstream_desc="Capture screen pixels.")

    registered = mcp.tools.get("computer_screenshot")
    assert registered is not None
    doc = registered.__doc__ or ""
    assert "Capture screen pixels." in doc
    assert "HERMY proxy" in doc


def test_register_tool_fallback_doc_without_upstream():
    proxy = CuaMcpProxy.__new__(CuaMcpProxy)
    proxy.upstream_url = "http://fake"
    proxy._client = None
    mcp = FastMCP(name="test")

    _register_tool_proxy(mcp, proxy, "computer_click")

    registered = mcp.tools.get("computer_click")
    assert registered is not None
    doc = registered.__doc__ or ""
    assert "HERMY proxy" in doc


# ---------------------------------------------------------------------------
# create_proxy_mcp_server_async with mocked upstream
# ---------------------------------------------------------------------------

def test_create_proxy_mcp_server_async_injects_descriptions(monkeypatch):
    upstream_tools = [
        {"name": name, "description": f"Upstream desc for {name}."}
        for name in list(ALLOWED_CUA_TOOLS)[:5]
    ]
    mock_list = AsyncMock(return_value=upstream_tools)

    with patch.object(CuaMcpProxy, "list_upstream_tools", mock_list):
        mcp = asyncio.run(create_proxy_mcp_server_async("http://fake"))

    for tool in upstream_tools:
        name = tool["name"]
        registered = mcp.tools.get(name)
        assert registered is not None, f"tool not registered: {name}"
        doc = registered.__doc__ or ""
        assert f"Upstream desc for {name}." in doc, f"description not injected for {name}"


def test_create_proxy_mcp_server_async_registers_all_allowed_tools_even_on_upstream_failure():
    mock_list = AsyncMock(side_effect=RuntimeError("upstream exploded"))

    with patch.object(CuaMcpProxy, "list_upstream_tools", mock_list):
        mcp = asyncio.run(create_proxy_mcp_server_async("http://fake"))

    for name in ALLOWED_CUA_TOOLS:
        assert mcp.tools.get(name) is not None, f"tool missing after upstream failure: {name}"


# ---------------------------------------------------------------------------
# Compatibility: Hermes-like call still works without strict schema
# ---------------------------------------------------------------------------

def test_proxy_tool_callable_without_schema_validation(monkeypatch):
    upstream_tools = [
        {"name": "computer_screenshot", "description": "Take a screenshot."},
    ]
    mock_list = AsyncMock(return_value=upstream_tools)
    mock_call = AsyncMock(return_value={"result": {"content": [{"type": "text", "text": "img"}]}})

    with patch.object(CuaMcpProxy, "list_upstream_tools", mock_list):
        mcp = asyncio.run(create_proxy_mcp_server_async("http://fake"))

    registered_fn = mcp.tools.get("computer_screenshot")
    assert registered_fn is not None

    with patch.object(CuaMcpProxy, "call_tool", mock_call):
        result = asyncio.run(registered_fn())

    assert mock_call.called or result is not None
