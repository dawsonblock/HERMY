"""Checks for the Hermes config template."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_config_template_declares_cua_http_and_cube_stdio():
    text = (ROOT / "config" / "hermes_config_template.yaml").read_text(encoding="utf-8")

    assert 'url: "http://127.0.0.1:8000/mcp"' in text
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
