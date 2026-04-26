"""Checks for the Hermes config template."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_config_template_declares_cua_http_and_cube_stdio():
    text = (ROOT / "config" / "hermes_config_template.yaml").read_text(encoding="utf-8")

    assert 'url: "http://127.0.0.1:8000/mcp"' in text
    assert 'command: "hermy-cube-mcp"' in text
    assert 'backend: "none"' in text
    assert "HERMY_MAX_TIMEOUT_SECONDS" in text
