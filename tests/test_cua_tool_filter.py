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
    _QUESTIONABLE_TOOL_ENV_FLAGS,
    _enabled_questionable_tools,
    get_upstream_cua_url,
    CuaMcpProxy,
    create_proxy_mcp_server,
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

    def test_filter_tools_blocks_questionable_by_default(self, monkeypatch):
        """Filter should block questionable tools when no env flags are set."""
        for flag in set(_QUESTIONABLE_TOOL_ENV_FLAGS.values()):
            monkeypatch.delenv(flag, raising=False)
        proxy = CuaMcpProxy()
        tools = [
            {"name": "computer_clipboard_get"},
            {"name": "computer_clipboard_set"},
            {"name": "computer_open"},
            {"name": "computer_launch_app"},
            {"name": "computer_set_wallpaper"},
        ]
        filtered = proxy._filter_tools(tools)
        assert len(filtered) == 0

    def test_filter_tools_passes_questionable_when_env_flag_set(self, monkeypatch):
        """Filter should pass clipboard tools when HERMY_ALLOW_CUA_CLIPBOARD=1."""
        for flag in set(_QUESTIONABLE_TOOL_ENV_FLAGS.values()):
            monkeypatch.delenv(flag, raising=False)
        monkeypatch.setenv("HERMY_ALLOW_CUA_CLIPBOARD", "1")
        proxy = CuaMcpProxy()
        tools = [
            {"name": "computer_clipboard_get"},
            {"name": "computer_clipboard_set"},
            {"name": "computer_open"},
        ]
        filtered = proxy._filter_tools(tools)
        names = [t["name"] for t in filtered]
        assert "computer_clipboard_get" in names
        assert "computer_clipboard_set" in names
        assert "computer_open" not in names


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


class TestQuestionableToolsDisabledByDefault:
    """Governance tests: questionable tools must be off by default."""

    def test_questionable_tools_disabled_by_default(self, monkeypatch):
        """_enabled_questionable_tools returns empty set when no env flags set."""
        for flag in set(_QUESTIONABLE_TOOL_ENV_FLAGS.values()):
            monkeypatch.delenv(flag, raising=False)
        assert _enabled_questionable_tools() == frozenset()

    def test_enabled_questionable_tools_respects_each_flag(self, monkeypatch):
        """Each env flag enables only its associated tool(s)."""
        for flag in set(_QUESTIONABLE_TOOL_ENV_FLAGS.values()):
            monkeypatch.delenv(flag, raising=False)
        monkeypatch.setenv("HERMY_ALLOW_CUA_OPEN", "1")
        enabled = _enabled_questionable_tools()
        assert "computer_open" in enabled
        assert "computer_clipboard_get" not in enabled
        assert "computer_launch_app" not in enabled

    @pytest.mark.asyncio
    async def test_call_tool_blocks_questionable_tools_by_default(self, monkeypatch):
        """call_tool must reject questionable tools when env flags are absent."""
        for flag in set(_QUESTIONABLE_TOOL_ENV_FLAGS.values()):
            monkeypatch.delenv(flag, raising=False)
        proxy = CuaMcpProxy()
        for tool_name in QUESTIONABLE_CUA_TOOLS:
            result = await proxy.call_tool(tool_name, {})
            assert result["isError"] is True, (
                f"Expected {tool_name} to be blocked by default"
            )
            assert "disabled by default" in result["content"][0]["text"]

    @pytest.mark.asyncio
    async def test_call_tool_allows_questionable_when_flag_set(self, monkeypatch):
        """call_tool passes questionable tools through when the env flag is set
        (the upstream call will fail because there is no real server, but the
        proxy itself should not produce an isError block)."""
        for flag in set(_QUESTIONABLE_TOOL_ENV_FLAGS.values()):
            monkeypatch.delenv(flag, raising=False)
        monkeypatch.setenv("HERMY_ALLOW_CUA_CLIPBOARD", "1")
        proxy = CuaMcpProxy()
        # With the flag set the proxy should try to reach upstream rather than
        # return a policy-denied response.  A connection error is expected here;
        # we only assert the policy block is not returned.
        import httpx
        try:
            result = await proxy.call_tool("computer_clipboard_get", {})
            # If somehow a result came back it must not be a policy block.
            assert "disabled by default" not in result.get("content", [{}])[0].get("text", "")
        except (httpx.ConnectError, httpx.ConnectTimeout, RuntimeError):
            pass  # expected: no upstream server running


class TestForbiddenToolsNeverRegistered:
    """Governance: forbidden CUA tools must never appear in the proxy server."""

    def _make_mock_fastmcp(self):
        class MockFastMCP:
            def __init__(self, name, instructions=None):
                self.name = name
                self.instructions = instructions
                self.tools: dict = {}
                self._hermy_proxy = None

            def tool(self, fn=None):
                def decorate(func):
                    self.tools[func.__name__] = func
                    return func
                return decorate(fn) if fn else decorate

        return MockFastMCP

    def test_cua_forbidden_tools_never_registered(self, monkeypatch):
        """No FORBIDDEN_CUA_TOOL must appear in the proxy server tool registry."""
        from cua_bridge import cua_mcp_proxy

        MockFastMCP = self._make_mock_fastmcp()
        original_fastmcp = cua_mcp_proxy.FastMCP
        cua_mcp_proxy.FastMCP = MockFastMCP
        cua_mcp_proxy._MCP_AVAILABLE = True

        for flag in set(_QUESTIONABLE_TOOL_ENV_FLAGS.values()):
            monkeypatch.delenv(flag, raising=False)

        try:
            server = cua_mcp_proxy.create_proxy_mcp_server()
            registered = set(server.tools.keys())
            overlap = registered & FORBIDDEN_CUA_TOOLS
            assert not overlap, (
                f"Forbidden tools registered in proxy: {overlap}"
            )
        finally:
            cua_mcp_proxy.FastMCP = original_fastmcp

    def test_questionable_tools_not_registered_by_default(self, monkeypatch):
        """Questionable tools must not appear when no env flags are set."""
        from cua_bridge import cua_mcp_proxy

        MockFastMCP = self._make_mock_fastmcp()
        original_fastmcp = cua_mcp_proxy.FastMCP
        cua_mcp_proxy.FastMCP = MockFastMCP
        cua_mcp_proxy._MCP_AVAILABLE = True

        for flag in set(_QUESTIONABLE_TOOL_ENV_FLAGS.values()):
            monkeypatch.delenv(flag, raising=False)

        try:
            server = cua_mcp_proxy.create_proxy_mcp_server()
            registered = set(server.tools.keys())
            overlap = registered & QUESTIONABLE_CUA_TOOLS
            assert not overlap, (
                f"Questionable tools registered without env flag: {overlap}"
            )
        finally:
            cua_mcp_proxy.FastMCP = original_fastmcp
