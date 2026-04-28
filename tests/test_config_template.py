"""Checks for the Hermes config template."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_config_template_declares_hermy_cua_proxy_and_cube_stdio():
    text = (ROOT / "config" / "hermes_config_template.yaml").read_text(encoding="utf-8")

    # HERMY CUA Proxy (stdio MCP) instead of direct HTTP to raw CUA
    assert 'command: "hermy-cua-mcp"' in text
    assert "HERMY_UPSTREAM_CUA_URL" in text
    # Raw CUA URL should NOT be in config (direct connection bypasses HERMY proxy)
    assert 'url: "http://127.0.0.1:8000/mcp"' not in text
    assert 'command: "hermy-cube-mcp"' in text
    assert "platform_toolsets:" in text
    assert '"cua", "cube"' in text
    assert "terminal:" not in text
    assert '"terminal"' not in text
    assert '"file"' not in text
    assert '"code_execution"' not in text
    assert "HERMY_MAX_TIMEOUT_SECONDS" in text
    assert "HERMY_MAX_CODE_BYTES" in text
    assert "HERMY_UNSAFE_DISABLE_OUTPUT_REDACTION" in text
