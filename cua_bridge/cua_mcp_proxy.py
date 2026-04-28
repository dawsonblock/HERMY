"""HERMY CUA MCP Proxy - Filters dangerous tools from upstream CUA.

This module provides a proxy MCP server that connects to the upstream CUA
MCP HTTP server but only exposes an allowlist of safe GUI tools. Dangerous
tools like shell execution and filesystem operations are blocked.

Architecture:
    Hermes -> HERMY CUA Proxy (stdio MCP) -> Raw CUA (HTTP MCP)
    Hermes -> HERMY Cube Bridge (stdio MCP) -> Cube Sandbox

This ensures Hermes never has direct access to CUA's shell/file tools.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from typing import Any

# Import FastMCP for creating the proxy server
try:  # pragma: no cover
    from mcp.server.fastmcp import FastMCP
    from mcp.server.fastmcp.utilities.types import Image

    _MCP_AVAILABLE = True
except ImportError:  # pragma: no cover
    _MCP_AVAILABLE = False

    class FastMCP:  # type: ignore[override]
        def __init__(self, name: str, instructions: str | None = None) -> None:
            self.name = name
            self.instructions = instructions
            self.tools: dict[str, Any] = {}

        def tool(self, fn: Any | None = None) -> Any:
            def decorate(func: Any) -> Any:
                self.tools[func.__name__] = func
                return func

            if fn is not None:
                return decorate(fn)
            return decorate

        async def run_stdio_async(self) -> None:
            raise ImportError(
                "MCP server requires the 'mcp' package. "
                f"Install with: {sys.executable} -m pip install mcp"
            )

    class Image:  # type: ignore[override]
        def __init__(self, data: bytes, format: str = "png") -> None:
            self.data = data
            self.format = format


try:  # pragma: no cover
    import httpx

    _HTTPX_AVAILABLE = True
except ImportError:  # pragma: no cover
    _HTTPX_AVAILABLE = False


LOGGER = logging.getLogger(__name__)

# Safe GUI tools that are allowed through the proxy
ALLOWED_CUA_TOOLS: frozenset[str] = frozenset([
    # Screen and mouse
    "computer_screenshot",
    "computer_get_screen_size",
    "computer_get_cursor_position",
    "computer_click",
    "computer_double_click",
    "computer_move",
    "computer_drag",
    "computer_scroll",
    "computer_mouse_down",
    "computer_mouse_up",
    # Keyboard
    "computer_type",
    "computer_press_key",
    "computer_hotkey",
    "computer_key_down",
    "computer_key_up",
    # Window management
    "computer_get_active_window",
    "computer_get_window_name",
    "computer_get_window_size",
    "computer_get_window_position",
    "computer_set_window_size",
    "computer_set_window_position",
    "computer_activate_window",
    "computer_minimize_window",
    "computer_maximize_window",
    "computer_close_window",
    "computer_get_app_windows",
    # Accessibility
    "computer_get_accessibility_tree",
    "computer_find_element",
])

# Questionable tools - included but logged as potentially risky
# These could be used to open files or URLs, which might have security implications
QUESTIONABLE_CUA_TOOLS: frozenset[str] = frozenset([
    "computer_clipboard_get",
    "computer_clipboard_set",
    "computer_open",
    "computer_launch_app",
    "computer_set_wallpaper",
])

# Forbidden tools - these will be explicitly rejected
FORBIDDEN_CUA_TOOLS: frozenset[str] = frozenset([
    "computer_run_command",  # Shell execution
    "computer_file_read",    # File system access
    "computer_file_write",
    "computer_file_exists",
    "computer_directory_exists",
    "computer_list_directory",
    "computer_create_directory",
    "computer_delete_file",
    "computer_delete_directory",
    "computer_get_file_size",
])

ALL_ALLOWED_TOOLS = ALLOWED_CUA_TOOLS | QUESTIONABLE_CUA_TOOLS


def get_upstream_cua_url() -> str:
    """Get the upstream CUA MCP URL from environment or default."""
    return os.environ.get("HERMY_UPSTREAM_CUA_URL", "http://127.0.0.1:8000/mcp")


class CuaMcpProxy:
    """Proxy that filters CUA tools to only allow safe GUI operations."""

    def __init__(self, upstream_url: str | None = None) -> None:
        self.upstream_url = upstream_url or get_upstream_cua_url()
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            if not _HTTPX_AVAILABLE:
                raise ImportError(
                    "CUA proxy requires 'httpx'. "
                    f"Install with: {sys.executable} -m pip install httpx"
                )
            self._client = httpx.AsyncClient(timeout=60.0)
        return self._client

    async def _call_upstream(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Call the upstream CUA MCP server."""
        client = await self._get_client()
        request = {
            "jsonrpc": "2.0",
            "id": "hermy-proxy",
            "method": method,
            "params": params or {},
        }
        headers = {
            "accept": "application/json, text/event-stream",
            "content-type": "application/json",
        }
        response = await client.post(self.upstream_url, json=request, headers=headers)
        response.raise_for_status()

        # Handle SSE or JSON response
        text = response.text.strip()
        if text.startswith("event:"):
            data_lines = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")]
            if data_lines:
                text = data_lines[-1]

        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid JSON response from upstream: {exc}") from exc

    async def list_upstream_tools(self) -> list[dict[str, Any]]:
        """List tools available from upstream CUA."""
        result = await self._call_upstream("tools/list")
        return result.get("result", {}).get("tools", [])

    def _filter_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Filter tools to only allow safe GUI operations."""
        filtered = []
        for tool in tools:
            name = tool.get("name", "")
            if name in ALLOWED_CUA_TOOLS:
                filtered.append(tool)
            elif name in QUESTIONABLE_CUA_TOOLS:
                LOGGER.warning(f"Including questionable tool: {name}")
                filtered.append(tool)
            elif name in FORBIDDEN_CUA_TOOLS:
                LOGGER.info(f"Filtering out forbidden tool: {name}")
            else:
                # Unknown tool - block it for safety
                LOGGER.warning(f"Blocking unknown tool: {name}")
        return filtered

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Call a tool on the upstream CUA server."""
        if name in FORBIDDEN_CUA_TOOLS:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"Tool '{name}' is blocked by HERMY policy. Use Cube for shell/file operations.",
                    }
                ],
                "isError": True,
            }

        if name not in ALL_ALLOWED_TOOLS:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"Unknown tool '{name}' rejected by HERMY CUA proxy.",
                    }
                ],
                "isError": True,
            }

        result = await self._call_upstream("tools/call", {
            "name": name,
            "arguments": arguments,
        })
        return result.get("result", {})

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None


def create_proxy_mcp_server(upstream_url: str | None = None) -> FastMCP:
    """Create the HERMY CUA MCP proxy server.

    This server exposes only safe GUI tools from upstream CUA.
    Shell and file operations are blocked.
    """
    proxy = CuaMcpProxy(upstream_url)

    mcp = FastMCP(
        name="hermy-cua-proxy",
        instructions="""HERMY CUA Proxy - Safe GUI Operations Only

This MCP server provides filtered access to CUA (Computer Use Agent) tools.
Only GUI operations like screenshots, clicks, typing, and window management
are allowed. Shell commands and file operations are blocked.

For shell/file operations, use the HERMY Cube MCP bridge instead.
""",
    )

    # Register allowed tools dynamically
    for tool_name in sorted(ALLOWED_CUA_TOOLS):
        _register_tool_proxy(mcp, proxy, tool_name)

    # Register questionable tools with warning
    for tool_name in sorted(QUESTIONABLE_CUA_TOOLS):
        _register_tool_proxy(mcp, proxy, tool_name, questionable=True)

    # Store proxy reference for cleanup
    mcp._hermy_proxy = proxy  # type: ignore[attr-defined]

    return mcp


def _register_tool_proxy(
    mcp: FastMCP, proxy: CuaMcpProxy, name: str, questionable: bool = False
) -> None:
    """Register a tool proxy function."""

    async def tool_proxy(**kwargs: Any) -> Any:
        if questionable:
            LOGGER.warning(f"Questionable tool called: {name}")
        return await proxy.call_tool(name, kwargs)

    # Copy name for the tool
    tool_proxy.__name__ = name

    # Register with MCP
    mcp.tool()(tool_proxy)


async def run_proxy_server(
    upstream_url: str | None = None, verbose: bool = False
) -> None:
    """Run the CUA MCP proxy server on stdio."""
    if not _MCP_AVAILABLE:
        print(
            "Error: MCP server requires the 'mcp' package.\n"
            f"Install with: {sys.executable} -m pip install mcp",
            file=sys.stderr,
        )
        sys.exit(1)

    if not _HTTPX_AVAILABLE:
        print(
            "Error: CUA proxy requires 'httpx'.\n"
            f"Install with: {sys.executable} -m pip install httpx",
            file=sys.stderr,
        )
        sys.exit(1)

    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )

    mcp = create_proxy_mcp_server(upstream_url)

    LOGGER.info(f"Starting HERMY CUA proxy (upstream: {get_upstream_cua_url()})")

    try:
        await mcp.run_stdio_async()
    finally:
        await mcp._hermy_proxy.close()  # type: ignore[attr-defined]


def main() -> None:
    """Console-script entry point for hermy-cua-mcp."""
    verbose = os.environ.get("HERMY_MCP_VERBOSE", "").lower() in {"1", "true", "yes", "on"}
    upstream_url = os.environ.get("HERMY_UPSTREAM_CUA_URL")
    asyncio.run(run_proxy_server(upstream_url=upstream_url, verbose=verbose))


if __name__ == "__main__":
    main()
