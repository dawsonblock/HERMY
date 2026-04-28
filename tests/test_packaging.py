"""Packaging checks for the HERMY integration scaffold."""

from __future__ import annotations

from pathlib import Path


try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - fallback for older local Python
    from pip._vendor import tomli as tomllib  # type: ignore


ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_packages_only_local_integration_modules():
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    assert data["project"]["requires-python"] == ">=3.11"
    assert data["tool"]["setuptools"]["packages"] == ["cube_bridge", "cua_bridge", "controller"]
    assert "hermy-cube-mcp" in data["project"]["scripts"]
    assert "hermy-cua-mcp" in data["project"]["scripts"]
    assert "hermy-doctor" not in data["project"].get("scripts", {})


def test_pyproject_does_not_package_vendored_upstreams():
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert "hermes-agent-2026.4.23" not in text
    assert "cua-main" not in text
    assert "CubeSandbox-master" not in text
