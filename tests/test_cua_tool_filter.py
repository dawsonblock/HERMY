"""Tests for the HERMY CUA MCP Proxy tool filtering.

This module tests that the CUA proxy correctly filters out dangerous tools
(shell execution, file system access) while allowing safe GUI tools.
"""

from __future__ import annotations

import pytest

from cua_bridge.cua_mcp_proxy import (
    ALLOWED_CUA_TOOLS,
    FORBIDDEN_CUA_TOOLS,
    QUESTIONABLE_CUA_TOOLS,
    ALL_ALLOWED_TOOLS,
    get_upstream_cua_url,
    CuaMcpProxy,
)


class TestToolLists:
    """Test that tool lists are correctly defined."""

    def test_allowed_tools_includes_gui_operations(self):
        """Allowed tools should include basic GUI operations."""
        assert "computer_screenshot" in ALLOWED_CUA_TOOLS
        assert "computer_click" in ALLOWED_CUA_TOOLS
        assert "computer_type" in ALLOWED_CUA_TOOLS
        assert "computer_press_key" in ALLOWED_CUA_TOOLS

    def test_forbidden_tools_includes_shell_and_file(self):
        """Forbidden tools should include shell and file operations."""
        assert "computer_run_command" in FORBIDDEN_CUA_TOOLS
        assert "computer_file_read" in FORBIDDEN_CUA_TOOLS
        assert "computer_file_write" in FORBIDDEN_CUA_TOOLS
        assert "computer_file_exists" in FORBIDDEN_CUA_TOOLS
        assert "computer_list_directory" in FORBIDDEN_CUA_TOOLS
        assert "computer_delete_file" in FORBIDDEN_CUA_TOOLS
        assert "computer_delete_directory" in FORBIDDEN_CUA_TOOLS

    def test_no_overlap_between_allowed_and_forbidden(self):
        """No tool should be both allowed and forbidden."""
        overlap = ALLOWED_CUA_TOOLS & FORBIDDEN_CUA_TOOLS
        assert not overlap, f"Tools in both lists: {overlap}"

    def test_all_allowed_covers_allowed_and_questionable(self):
        """ALL_ALLOWED_TOOLS should include both allowed and questionable."""
        assert ALLOWED_CUA_TOOLS <= ALL_ALLOWED_TOOLS
        assert QUESTIONABLE_CUA_TOOLS <= ALL_ALLOWED_TOOLS


class TestGetUpstreamCuaUrl:
    """Test upstream URL configuration."""

    def test_default_url(self, monkeypatch):
        """Default URL should be localhost:8000."""
        monkeypatch.delenv("HERMY_UPSTREAM_CUA_URL", raising=False)
        assert get_upstream_cua_url() == "http://127.0.0.1:8000/mcp"

    def test_env_override(self, monkeypatch):
        """Environment variable should override default."""
        monkeypatch.setenv("HERMY_UPSTREAM_CUA_URL", "http://cua.example.com/mcp")
        assert get_upstream_cua_url() == "http://cua.example.com/mcp"


class TestCuaMcpProxyToolFiltering:
    """Test that CuaMcpProxy correctly filters tools."""

    def test_proxy_uses_default_url(self):
        """Proxy should use default upstream URL."""
        proxy = CuaMcpProxy()
        assert proxy.upstream_url == "http://127.0.0.1:8000/mcp"

    def test_proxy_accepts_custom_url(self):
        """Proxy should accept custom upstream URL."""
        proxy = CuaMcpProxy("http://custom.example.com/mcp")
        assert proxy.upstream_url == "http://custom.example.com/mcp"

    def test_filter_tools_keeps_allowed(self):
        """Filter should keep allowed tools."""
        proxy = CuaMcpProxy()
        tools = [
            {"name": "computer_screenshot"},
            {"name": "computer_click"},
        ]
        filtered = proxy._filter_tools(tools)
        assert len(filtered) == 2
        assert filtered[0]["name"] == "computer_screenshot"
        assert filtered[1]["name"] == "computer_click"

    def test_filter_tools_removes_forbidden(self):
        """Filter should remove forbidden tools."""
        proxy = CuaMcpProxy()
        tools = [
            {"name": "computer_screenshot"},
            {"name": "computer_run_command"},
            {"name": "computer_file_read"},
        ]
        filtered = proxy._filter_tools(tools)
        assert len(filtered) == 1
        assert filtered[0]["name"] == "computer_screenshot"

    def test_filter_tools_removes_unknown(self):
        """Filter should remove unknown tools for safety."""
        proxy = CuaMcpProxy()
        tools = [
            {"name": "computer_screenshot"},
            {"name": "computer_unknown_tool"},
        ]
        filtered = proxy._filter_tools(tools)
        assert len(filtered) == 1
        assert filtered[0]["name"] == "computer_screenshot"

    def test_filter_tools_keeps_questionable(self):
        """Filter should keep questionable tools (with warning)."""
        proxy = CuaMcpProxy()
        tools = [
            {"name": "computer_clipboard_get"},
            {"name": "computer_clipboard_set"},
        ]
        filtered = proxy._filter_tools(tools)
        assert len(filtered) == 2


class TestCallToolBlocking:
    """Test that call_tool blocks forbidden tools."""

    @pytest.mark.asyncio
    async def test_call_tool_blocks_forbidden(self):
        """call_tool should block forbidden tools without upstream call."""
        proxy = CuaMcpProxy()
        result = await proxy.call_tool("computer_run_command", {"command": "rm -rf /"})

        assert result["isError"] is True
        assert "blocked by HERMY policy" in result["content"][0]["text"]
        assert "Cube for shell/file operations" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_call_tool_blocks_unknown_tools(self):
        """call_tool should block unknown tools."""
        proxy = CuaMcpProxy()
        result = await proxy.call_tool("computer_unknown_tool", {})

        assert result["isError"] is True
        assert "rejected by HERMY CUA proxy" in result["content"][0]["text"]


class TestProxyMcpServerCreation:
    """Test that create_proxy_mcp_server creates a valid server."""

    def test_create_proxy_server_returns_fastmcp(self, monkeypatch):
        """create_proxy_mcp_server should return a FastMCP instance."""
        # FastMCP is imported at module level, we need to patch the class in the module
        from cua_bridge import cua_mcp_proxy

        class MockFastMCP:
            def __init__(self, name, instructions=None):
                self.name = name
                self.instructions = instructions
                self.tools = {}
                self._hermy_proxy = None

            def tool(self, fn=None):
                def decorate(func):
                    self.tools[func.__name__] = func
                    return func
                return decorate(fn) if fn else decorate

        # Mock the FastMCP class in the module
        original_fastmcp = cua_mcp_proxy.FastMCP
        cua_mcp_proxy.FastMCP = MockFastMCP
        cua_mcp_proxy._MCP_AVAILABLE = True

        try:
            server = cua_mcp_proxy.create_proxy_mcp_server()

            assert server.name == "hermy-cua-proxy"
            assert "HERMY CUA Proxy" in server.instructions
            # Should have registered allowed tools
            assert len(server.tools) > 0
            # All tools should be from allowed set
            for tool_name in server.tools:
                assert tool_name in ALL_ALLOWED_TOOLS
        finally:
            # Restore
            cua_mcp_proxy.FastMCP = original_fastmcp

    def test_proxy_server_has_reference_to_proxy(self, monkeypatch):
        """Server should store reference to CuaMcpProxy for cleanup."""
        from cua_bridge import cua_mcp_proxy

        class MockFastMCP:
            def __init__(self, name, instructions=None):
                self.name = name
                self.instructions = instructions
                self.tools = {}
                self._hermy_proxy = None

            def tool(self, fn=None):
                def decorate(func):
                    self.tools[func.__name__] = func
                    return func
                return decorate(fn) if fn else decorate

        original_fastmcp = cua_mcp_proxy.FastMCP
        cua_mcp_proxy.FastMCP = MockFastMCP
        cua_mcp_proxy._MCP_AVAILABLE = True

        try:
            server = cua_mcp_proxy.create_proxy_mcp_server()
            assert hasattr(server, "_hermy_proxy")
            assert isinstance(server._hermy_proxy, CuaMcpProxy)
        finally:
            cua_mcp_proxy.FastMCP = original_fastmcp


class TestConfigIntegration:
    """Test that config template uses the CUA proxy."""

    def test_config_uses_stdio_command(self):
        """Config should use stdio command instead of HTTP URL."""
        import pathlib

        config_path = pathlib.Path(__file__).parent.parent / "config" / "hermes_config_template.yaml"
        if not config_path.exists():
            pytest.skip("Config file not found")

        content = config_path.read_text()

        # Should use hermy-cua-mcp command
        assert "command: \"hermy-cua-mcp\"" in content
        # Should NOT have raw URL connection to CUA
        assert "url: \"http://127.0.0.1:8000/mcp\"" not in content
        # Should have HERMY_UPSTREAM_CUA_URL env var
        assert "HERMY_UPSTREAM_CUA_URL" in content
