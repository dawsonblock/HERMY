"""Tests for the Cube MCP bridge.

These tests verify that the bridge module can be imported and that
decorated MCP functions are present.  They do not call Cube
Sandbox itself, as that would require a running deployment.  Instead
they focus on sanity checks such as ensuring the module defines the
expected functions and that policy integration is available.
"""

import inspect
import importlib


def test_bridge_importable(tmp_path, monkeypatch):
    # Ensure the cube_mcp_server module can be imported.  Temporarily
    # adjust sys.path so the integration package is discoverable.
    monkeypatch.syspath_prepend(".")
    module = importlib.import_module("cube_bridge.cube_mcp_server", package="integration")
    # Check that the module defines a FastMCP instance named mcp
    assert hasattr(module, "mcp")
    # Verify that the bridge exposes cube_create and cube_destroy
    for name in [
        "cube_create",
        "cube_run_command",
        "cube_run_python",
        "cube_read_file",
        "cube_write_file",
        "cube_destroy",
    ]:
        assert hasattr(module, name)
        assert inspect.isfunction(getattr(module, name))


def test_bridge_rejects_missing_sandbox_id(monkeypatch):
    monkeypatch.syspath_prepend(".")
    module = importlib.import_module("cube_bridge.cube_mcp_server", package="integration")

    response = module.cube_run_command(command="echo ok", sandbox_id="")

    assert response["ok"] is False
    assert response["error"] == "sandbox_id is required"


def test_bridge_rejects_write_outside_workspace(monkeypatch):
    monkeypatch.syspath_prepend(".")
    module = importlib.import_module("cube_bridge.cube_mcp_server", package="integration")

    response = module.cube_write_file(sandbox_id="sbx-1", path="/etc/passwd", content="nope")

    assert response["ok"] is False
    assert "workspace" in response["error"]
