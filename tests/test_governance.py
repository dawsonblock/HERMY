"""Governance tests for HERMY security boundaries.

These tests verify the top-level safety rules that the HERMY integration
layer is responsible for enforcing:

- Unknown Cube sandbox IDs are rejected before any backend call.
- Shell control operators require an explicit approval_id.
- Output redaction removes api keys, tokens, and passwords from responses.
- The Hermes config template excludes host-side execution tools.
- Both console entry points are declared in pyproject.toml.
- Workspace write/read paths are rejected outside /workspace.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeCubeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def cube_create(self, **kwargs):
        self.calls.append(("cube_create", kwargs))
        return {"ok": True, "sandbox_id": "sbx-gov-1", "template_id": kwargs.get("template_id")}

    def cube_run_command(self, **kwargs):
        self.calls.append(("cube_run_command", kwargs))
        return {"ok": True, "sandbox_id": kwargs["sandbox_id"], "stdout": "ok", "stderr": "", "exit_code": 0, "error": None}

    def cube_read_file(self, **kwargs):
        self.calls.append(("cube_read_file", kwargs))
        return {"ok": True, "sandbox_id": kwargs["sandbox_id"], "path": kwargs["path"], "content": "data", "error": None}

    def cube_write_file(self, **kwargs):
        self.calls.append(("cube_write_file", kwargs))
        return {"ok": True, "sandbox_id": kwargs["sandbox_id"], "path": kwargs["path"], "bytes_written": 4, "error": None}

    def cube_destroy(self, **kwargs):
        self.calls.append(("cube_destroy", kwargs))
        return {"ok": True, "sandbox_id": kwargs["sandbox_id"], "error": None}


def _make_controller(monkeypatch, cube=None):
    monkeypatch.setattr(
        "controller.runtime_controller.event_logger.log_event",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setenv("CUBE_WORKSPACE_DIR", "/workspace")
    from controller.runtime_controller import RuntimeController
    return RuntimeController(cua_client=None, cube_client=cube or _FakeCubeClient())


def _created_controller(monkeypatch, cube=None):
    """Return a controller that already has sandbox sbx-gov-1 registered."""
    controller = _make_controller(monkeypatch, cube)
    controller.handle_code_request({"op": "create", "template_id": "tpl-1"})
    return controller


# ---------------------------------------------------------------------------
# test_cube_unknown_sandbox_id_rejected_before_backend_call
# ---------------------------------------------------------------------------

def test_cube_unknown_sandbox_id_rejected_before_backend_call(monkeypatch):
    """Unknown sandbox IDs must be rejected and the cube client must not be called."""
    cube = _FakeCubeClient()
    controller = _make_controller(monkeypatch, cube)

    for op in ("run_command", "run_python", "read_file", "write_file", "destroy"):
        cube.calls.clear()
        payload: dict = {"op": op, "sandbox_id": "does-not-exist"}
        if op == "run_command":
            payload["command"] = "echo ok"
        elif op == "run_python":
            payload["code"] = "print(1)"
        elif op in ("read_file", "write_file"):
            payload["path"] = "/workspace/x.txt"
            if op == "write_file":
                payload["content"] = "hi"

        response = controller.handle_code_request(payload)

        assert response["ok"] is False, f"Expected denial for op={op}"
        assert "unknown sandbox_id" in response["error"], f"Wrong error for op={op}"
        assert cube.calls == [], f"Backend was called for op={op} with unknown sandbox_id"


# ---------------------------------------------------------------------------
# test_shell_control_operator_requires_approval_id
# ---------------------------------------------------------------------------

def test_shell_control_operator_requires_approval_id(monkeypatch):
    """Commands with shell control operators must be denied without approval_id."""
    from controller import policy

    assert not policy.validate_command("echo ok && whoami").allowed
    assert not policy.validate_command("echo ok && whoami", approved=True).allowed
    assert not policy.validate_command("echo ok && whoami", approved=True, approval_id="").allowed
    assert not policy.validate_command("echo ok && whoami", approved=True, approval_id="   ").allowed
    assert policy.validate_command("echo ok && whoami", approved=True, approval_id="req-1").allowed


def test_shell_control_operator_still_blocks_destructive_even_with_approval(monkeypatch):
    """Destructive commands remain blocked regardless of approval_id."""
    from controller import policy

    assert not policy.validate_command("rm -rf / && echo done", approved=True, approval_id="req-1").allowed
    assert not policy.validate_command("shutdown now; echo done", approved=True, approval_id="req-1").allowed


# ---------------------------------------------------------------------------
# test_output_redaction_redacts_api_keys_tokens_passwords
# ---------------------------------------------------------------------------

def test_output_redaction_redacts_api_keys_tokens_passwords():
    """redact_tool_output must strip common secret patterns from response text."""
    from controller.event_logger import redact_tool_output

    cases = [
        ("sk-abcdef1234567890abcdef", "[REDACTED]"),
        ("Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig", "[REDACTED]"),
        ("api_key=super-secret-value", "api_key=[REDACTED]"),
        ("token=raw-token-value", "token=[REDACTED]"),
        ("password=hunter2", "password=[REDACTED]"),
        ("Authorization: Bearer rawbearertoken123456", "[REDACTED]"),
        ("ghu_abcdefghijklmnopqrstu", "[REDACTED]"),
    ]
    for raw, expected_fragment in cases:
        result = redact_tool_output(raw)
        assert expected_fragment in result, (
            f"Expected '{expected_fragment}' in redacted output for input '{raw}', got: '{result}'"
        )
        assert raw not in result or expected_fragment == raw, (
            f"Raw secret still present in output for input '{raw}'"
        )


def test_output_redaction_enabled_by_default(monkeypatch):
    """Output redaction must be active when no opt-out env var is set."""
    monkeypatch.delenv("HERMY_UNSAFE_DISABLE_OUTPUT_REDACTION", raising=False)
    from controller import event_logger
    assert event_logger.output_redaction_enabled() is True


# ---------------------------------------------------------------------------
# test_config_excludes_host_execution_tools
# ---------------------------------------------------------------------------

def test_config_excludes_host_execution_tools():
    """hermes_config_template.yaml must not list terminal, file, or code_execution."""
    config_path = ROOT / "config" / "hermes_config_template.yaml"
    if not config_path.exists():
        pytest.skip("config/hermes_config_template.yaml not found")

    content = config_path.read_text(encoding="utf-8")

    for forbidden in ("terminal", "file", "code_execution"):
        assert f'"{forbidden}"' not in content and f"'{forbidden}'" not in content, (
            f"Host execution toolset '{forbidden}' must not appear in the Hermes config template"
        )


def test_config_uses_proxy_command_not_direct_url():
    """The config template must route CUA through the HERMY proxy, not a raw URL."""
    config_path = ROOT / "config" / "hermes_config_template.yaml"
    if not config_path.exists():
        pytest.skip("config/hermes_config_template.yaml not found")

    content = config_path.read_text(encoding="utf-8")

    assert 'command: "hermy-cua-mcp"' in content, (
        "CUA must be configured via hermy-cua-mcp proxy command"
    )
    assert 'url: "http://127.0.0.1:8000/mcp"' not in content, (
        "Direct CUA HTTP URL must not appear as a top-level MCP server config"
    )


# ---------------------------------------------------------------------------
# test_console_entry_points_exist
# ---------------------------------------------------------------------------

def test_console_entry_points_exist():
    """Both hermy-cube-mcp and hermy-cua-mcp must be declared in pyproject.toml."""
    try:
        import tomllib
    except ModuleNotFoundError:
        from pip._vendor import tomli as tomllib  # type: ignore

    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    scripts = data.get("project", {}).get("scripts", {})

    assert "hermy-cube-mcp" in scripts, "hermy-cube-mcp entry point missing from pyproject.toml"
    assert "hermy-cua-mcp" in scripts, "hermy-cua-mcp entry point missing from pyproject.toml"
    assert scripts["hermy-cube-mcp"] == "cube_bridge.cube_mcp_server:main"
    assert scripts["hermy-cua-mcp"] == "cua_bridge.cua_mcp_proxy:main"


# ---------------------------------------------------------------------------
# test_write_outside_workspace_rejected
# test_read_outside_workspace_rejected
# ---------------------------------------------------------------------------

def test_write_outside_workspace_rejected(monkeypatch):
    """Write operations outside /workspace must be denied at the controller level."""
    monkeypatch.setenv("CUBE_WORKSPACE_DIR", "/workspace")
    cube = _FakeCubeClient()
    controller = _created_controller(monkeypatch, cube)

    for bad_path in ("/etc/passwd", "/tmp/evil.sh", "../escape.txt"):
        cube.calls.clear()
        response = controller.handle_code_request({
            "op": "write_file",
            "sandbox_id": "sbx-gov-1",
            "path": bad_path,
            "content": "evil",
        })
        assert response["ok"] is False, f"Expected write to '{bad_path}' to be denied"
        write_calls = [c for c in cube.calls if c[0] == "cube_write_file"]
        assert write_calls == [], f"Backend write was called for forbidden path '{bad_path}'"


def test_read_outside_workspace_rejected(monkeypatch):
    """Read operations outside /workspace must be denied at the controller level."""
    monkeypatch.setenv("CUBE_WORKSPACE_DIR", "/workspace")
    cube = _FakeCubeClient()
    controller = _created_controller(monkeypatch, cube)

    for bad_path in ("/etc/hosts", "/proc/self/environ", "../../etc/shadow"):
        cube.calls.clear()
        response = controller.handle_code_request({
            "op": "read_file",
            "sandbox_id": "sbx-gov-1",
            "path": bad_path,
        })
        assert response["ok"] is False, f"Expected read of '{bad_path}' to be denied"
        read_calls = [c for c in cube.calls if c[0] == "cube_read_file"]
        assert read_calls == [], f"Backend read was called for forbidden path '{bad_path}'"


# ---------------------------------------------------------------------------
# test_shell_wrapper_rejected
# test_inline_interpreter_rejected
# ---------------------------------------------------------------------------

def test_shell_wrapper_rejected():
    """bash -c and sh -c must be blocked by policy."""
    from controller import policy

    assert not policy.validate_command("bash -c 'echo ok'").allowed
    assert not policy.validate_command("sh -c 'ls'").allowed
    assert not policy.validate_command(["bash", "-c", "echo ok"]).allowed
    assert not policy.validate_command(["sh", "-c", "ls"]).allowed


def test_inline_interpreter_rejected():
    """python -c and node -e must be blocked by policy."""
    from controller import policy

    assert not policy.validate_command("python -c 'import os; os.system(\"id\")'").allowed
    assert not policy.validate_command("python3 -c 'print(1)'").allowed
    assert not policy.validate_command("node -e 'console.log(1)'").allowed
    assert not policy.validate_command(["python", "-c", "print(1)"]).allowed
