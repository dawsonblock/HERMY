"""Tests for CUA proxy tool filtering and call-gating logic.

These tests mock the upstream CUA interface so no live CUA server is required.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from cua_bridge.cua_mcp_proxy import (
    ALLOWED_CUA_TOOLS,
    FORBIDDEN_CUA_TOOLS,
    QUESTIONABLE_CUA_TOOLS,
    CuaMcpProxy,
    _enabled_questionable_tools,
    run_proxy_server,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tool(name: str, description: str = "") -> dict:
    return {"name": name, "description": description, "inputSchema": {"type": "object", "properties": {}}}


def _all_upstream_tools() -> list[dict]:
    tools = []
    for name in ALLOWED_CUA_TOOLS:
        tools.append(_tool(name))
    for name in QUESTIONABLE_CUA_TOOLS:
        tools.append(_tool(name))
    for name in FORBIDDEN_CUA_TOOLS:
        tools.append(_tool(name))
    tools.append(_tool("computer_unknown_future_tool"))
    return tools


# ---------------------------------------------------------------------------
# _filter_tools_static tests (pure logic, no upstream call)
# ---------------------------------------------------------------------------

def test_filter_removes_forbidden_tools(monkeypatch):
    monkeypatch.delenv("HERMY_ALLOW_CUA_CLIPBOARD", raising=False)
    monkeypatch.delenv("HERMY_ALLOW_CUA_OPEN", raising=False)
    monkeypatch.delenv("HERMY_ALLOW_CUA_LAUNCH_APP", raising=False)
    monkeypatch.delenv("HERMY_ALLOW_CUA_WALLPAPER", raising=False)

    proxy = CuaMcpProxy.__new__(CuaMcpProxy)
    result = proxy._filter_tools(_all_upstream_tools())
    names = {t["name"] for t in result}

    for forbidden in FORBIDDEN_CUA_TOOLS:
        assert forbidden not in names, f"forbidden tool leaked: {forbidden}"


def test_filter_keeps_allowed_gui_tools(monkeypatch):
    monkeypatch.delenv("HERMY_ALLOW_CUA_CLIPBOARD", raising=False)

    proxy = CuaMcpProxy.__new__(CuaMcpProxy)
    result = proxy._filter_tools(_all_upstream_tools())
    names = {t["name"] for t in result}

    for allowed in ALLOWED_CUA_TOOLS:
        assert allowed in names, f"expected allowed tool missing: {allowed}"


def test_filter_blocks_questionable_tools_by_default(monkeypatch):
    for flag in ("HERMY_ALLOW_CUA_CLIPBOARD", "HERMY_ALLOW_CUA_OPEN",
                 "HERMY_ALLOW_CUA_LAUNCH_APP", "HERMY_ALLOW_CUA_WALLPAPER"):
        monkeypatch.delenv(flag, raising=False)

    proxy = CuaMcpProxy.__new__(CuaMcpProxy)
    result = proxy._filter_tools(_all_upstream_tools())
    names = {t["name"] for t in result}

    for q_tool in QUESTIONABLE_CUA_TOOLS:
        assert q_tool not in names, f"questionable tool should be absent by default: {q_tool}"


def test_filter_allows_questionable_when_flag_set(monkeypatch):
    monkeypatch.setenv("HERMY_ALLOW_CUA_CLIPBOARD", "1")

    proxy = CuaMcpProxy.__new__(CuaMcpProxy)
    result = proxy._filter_tools(_all_upstream_tools())
    names = {t["name"] for t in result}

    assert "computer_clipboard_get" in names
    assert "computer_clipboard_set" in names


def test_filter_blocks_unknown_tools(monkeypatch):
    proxy = CuaMcpProxy.__new__(CuaMcpProxy)
    result = proxy._filter_tools([_tool("computer_unknown_future_tool")])
    assert result == []


# ---------------------------------------------------------------------------
# CuaMcpProxy.call_tool gate tests
# ---------------------------------------------------------------------------

def test_call_tool_blocks_forbidden_without_upstream_call():
    proxy = CuaMcpProxy.__new__(CuaMcpProxy)
    proxy.upstream_url = "http://fake"
    proxy._client = None

    result = asyncio.run(proxy.call_tool("computer_run_command", {"cmd": "ls"}))

    assert result.get("isError") is True
    text = result["content"][0]["text"].lower()
    assert "blocked" in text or "policy" in text


def test_call_tool_blocks_questionable_when_flag_not_set(monkeypatch):
    monkeypatch.delenv("HERMY_ALLOW_CUA_CLIPBOARD", raising=False)

    proxy = CuaMcpProxy.__new__(CuaMcpProxy)
    proxy.upstream_url = "http://fake"
    proxy._client = None

    result = asyncio.run(proxy.call_tool("computer_clipboard_get", {}))

    assert result.get("isError") is True
    text = result["content"][0]["text"]
    assert "disabled" in text.lower() or "HERMY_ALLOW_CUA" in text


def test_call_tool_passes_allowed_tool_to_upstream(monkeypatch):
    monkeypatch.setattr(
        "cua_bridge.cua_mcp_proxy.CuaMcpProxy._call_upstream",
        AsyncMock(return_value={"result": {"content": [{"type": "text", "text": "screenshot_data"}]}}),
    )

    proxy = CuaMcpProxy("http://fake")
    result = asyncio.run(proxy.call_tool("computer_screenshot", {}))

    assert result == {"content": [{"type": "text", "text": "screenshot_data"}]}


def test_call_tool_blocks_unknown_tool():
    proxy = CuaMcpProxy.__new__(CuaMcpProxy)
    proxy.upstream_url = "http://fake"
    proxy._client = None

    result = asyncio.run(proxy.call_tool("computer_unknown_future_tool", {}))

    assert result.get("isError") is True


# ---------------------------------------------------------------------------
# _enabled_questionable_tools
# ---------------------------------------------------------------------------

def test_no_questionable_tools_enabled_by_default(monkeypatch):
    for flag in ("HERMY_ALLOW_CUA_CLIPBOARD", "HERMY_ALLOW_CUA_OPEN",
                 "HERMY_ALLOW_CUA_LAUNCH_APP", "HERMY_ALLOW_CUA_WALLPAPER"):
        monkeypatch.delenv(flag, raising=False)

    enabled = _enabled_questionable_tools()
    assert len(enabled) == 0


def test_clipboard_tools_enabled_by_flag(monkeypatch):
    monkeypatch.setenv("HERMY_ALLOW_CUA_CLIPBOARD", "1")
    enabled = _enabled_questionable_tools()
    assert "computer_clipboard_get" in enabled
    assert "computer_clipboard_set" in enabled


def test_open_tool_enabled_by_flag(monkeypatch):
    monkeypatch.delenv("HERMY_ALLOW_CUA_CLIPBOARD", raising=False)
    monkeypatch.setenv("HERMY_ALLOW_CUA_OPEN", "1")
    enabled = _enabled_questionable_tools()
    assert "computer_open" in enabled
    assert "computer_clipboard_get" not in enabled


# ---------------------------------------------------------------------------
# Async startup regression test
# ---------------------------------------------------------------------------

def test_run_proxy_server_uses_async_creation_path():
    """Verify run_proxy_server calls create_proxy_mcp_server_async, not sync wrapper.

    This is a regression test for the bug where run_proxy_server used
    create_proxy_mcp_server() which internally calls asyncio.run(),
    causing a RuntimeError when an event loop was already running.
    """
    import inspect

    # Verify the source code of run_proxy_server uses await create_proxy_mcp_server_async
    source = inspect.getsource(run_proxy_server)

    # Should call the async version, not the sync wrapper
    assert "await create_proxy_mcp_server_async" in source, (
        "run_proxy_server must await create_proxy_mcp_server_async() directly"
    )
    # Should NOT call the sync wrapper that uses asyncio.run()
    assert "create_proxy_mcp_server(" not in source or "create_proxy_mcp_server_async" in source, (
        "run_proxy_server should not call create_proxy_mcp_server() sync wrapper"
    )
