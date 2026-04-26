"""Tests for the runtime controller."""

from __future__ import annotations

from controller import policy
from controller.runtime_controller import RuntimeController


class FakeCuaClient:
    def screenshot(self) -> dict[str, str]:
        return {"image": "ok"}


class FailingCuaClient:
    def screenshot(self) -> dict[str, object]:
        return {"ok": False, "error": "screenshot failed"}


class FakeCubeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.next_sandbox_id = "sbx-1"
        self.command_stdout = "ok"

    def cube_create(self, **kwargs):
        self.calls.append(("cube_create", kwargs))
        return {"ok": True, "sandbox_id": self.next_sandbox_id, "template_id": kwargs.get("template_id")}

    def cube_run_command(self, **kwargs):
        self.calls.append(("cube_run_command", kwargs))
        return {
            "ok": True,
            "sandbox_id": kwargs["sandbox_id"],
            "stdout": self.command_stdout,
            "stderr": "",
            "exit_code": 0,
            "error": None,
        }

    def cube_run_python(self, **kwargs):
        self.calls.append(("cube_run_python", kwargs))
        return {"ok": True, "sandbox_id": kwargs["sandbox_id"], "stdout": "1\n", "stderr": "", "exit_code": 0, "error": None}

    def cube_read_file(self, **kwargs):
        self.calls.append(("cube_read_file", kwargs))
        return {"ok": True, "sandbox_id": kwargs["sandbox_id"], "path": kwargs["path"], "content": "hello", "error": None}

    def cube_write_file(self, **kwargs):
        self.calls.append(("cube_write_file", kwargs))
        return {"ok": True, "sandbox_id": kwargs["sandbox_id"], "path": kwargs["path"], "bytes_written": 5, "error": None}

    def cube_destroy(self, **kwargs):
        self.calls.append(("cube_destroy", kwargs))
        return {"ok": True, "sandbox_id": kwargs["sandbox_id"], "error": None}


class FailingDestroyCubeClient(FakeCubeClient):
    def cube_destroy(self, **kwargs):
        self.calls.append(("cube_destroy", kwargs))
        raise RuntimeError("destroy exploded")


def _controller(monkeypatch, cube=None):
    monkeypatch.setattr("controller.runtime_controller.event_logger.log_event", lambda *args, **kwargs: True)
    return RuntimeController(cua_client=FakeCuaClient(), cube_client=cube or FakeCubeClient())


def test_controller_routes_gui_request(monkeypatch):
    controller = _controller(monkeypatch)

    response = controller.handle_gui_request({"op": "screenshot"})

    assert response["ok"] is True
    assert response["backend"] == "cua"
    assert response["result"] == {"image": "ok"}


def test_controller_propagates_failed_cua_result(monkeypatch):
    monkeypatch.setattr("controller.runtime_controller.event_logger.log_event", lambda *args, **kwargs: True)
    controller = RuntimeController(cua_client=FailingCuaClient(), cube_client=FakeCubeClient())

    response = controller.handle_gui_request({"op": "screenshot"})

    assert response["ok"] is False
    assert response["backend"] == "cua"
    assert response["error"] == "screenshot failed"
    assert response["result"] == {"ok": False, "error": "screenshot failed"}


def test_unknown_sandbox_id_is_rejected_before_cube_client_call(monkeypatch):
    cube = FakeCubeClient()
    controller = _controller(monkeypatch, cube)

    response = controller.handle_code_request({"op": "run_command", "sandbox_id": "unknown", "command": "echo ok"})

    assert response["ok"] is False
    assert response["error"] == "unknown sandbox_id: unknown"
    assert cube.calls == []


def test_create_stores_session_metadata(monkeypatch):
    monkeypatch.setenv("HERMY_ALLOW_INTERNET", "1")
    controller = _controller(monkeypatch)

    response = controller.handle_code_request(
        {
            "op": "create",
            "template_id": "tpl-1",
            "allow_internet_access": True,
            "metadata": {"task": "demo"},
        }
    )

    session = controller.sessions[response["sandbox_id"]]
    assert session.sandbox_id == "sbx-1"
    assert session.template_id == "tpl-1"
    assert session.allow_internet is True
    assert session.status == "active"
    assert session.metadata == {"task": "demo"}
    assert session.created_at
    assert session.last_used_at


def test_list_sessions_returns_active_sessions(monkeypatch):
    controller = _controller(monkeypatch)
    controller.handle_code_request({"op": "create", "template_id": "tpl-1"})

    response = controller.handle_code_request({"op": "list_sessions"})

    assert response["ok"] is True
    assert response["active_session_count"] == 1
    assert response["sessions"][0]["sandbox_id"] == "sbx-1"


def test_health_returns_ok_and_active_session_count(monkeypatch):
    controller = _controller(monkeypatch)
    controller.handle_code_request({"op": "create", "template_id": "tpl-1"})

    response = controller.handle_code_request({"op": "health"})

    assert response["ok"] is True
    assert response["active_session_count"] == 1
    assert response["started_at"]


def test_destroy_removes_known_session(monkeypatch):
    controller = _controller(monkeypatch)
    controller.handle_code_request({"op": "create", "template_id": "tpl-1"})

    response = controller.handle_code_request({"op": "destroy", "sandbox_id": "sbx-1"})

    assert response["ok"] is True
    assert "sbx-1" not in controller.sessions


def test_destroy_unknown_session_fails(monkeypatch):
    cube = FakeCubeClient()
    controller = _controller(monkeypatch, cube)

    response = controller.handle_code_request({"op": "destroy", "sandbox_id": "unknown"})

    assert response["ok"] is False
    assert response["error"] == "unknown sandbox_id: unknown"
    assert cube.calls == []


def test_destroy_all_destroys_all_known_sessions(monkeypatch):
    cube = FakeCubeClient()
    controller = _controller(monkeypatch, cube)
    controller.handle_code_request({"op": "create", "template_id": "tpl-1"})
    cube.next_sandbox_id = "sbx-2"
    controller.handle_code_request({"op": "create", "template_id": "tpl-2"})

    response = controller.handle_code_request({"op": "destroy_all"})

    assert response["ok"] is True
    assert response["active_session_count"] == 0
    assert not controller.sessions
    assert ("cube_destroy", {"sandbox_id": "sbx-1"}) in cube.calls
    assert ("cube_destroy", {"sandbox_id": "sbx-2"}) in cube.calls


def test_cleanup_is_best_effort_when_destroy_raises(monkeypatch):
    cube = FailingDestroyCubeClient()
    controller = _controller(monkeypatch, cube)
    controller.handle_code_request({"op": "create", "template_id": "tpl-1"})

    results = controller.cleanup()

    assert len(results) == 1
    assert results[0]["ok"] is False
    assert results[0]["sandbox_id"] == "sbx-1"
    assert "destroy exploded" in results[0]["error"]
    assert "sbx-1" in controller.sessions


def test_run_command_updates_last_used_at(monkeypatch):
    values = iter(["2026-01-01T00:00:00Z", "2026-01-01T00:00:01Z", "2026-01-01T00:00:02Z"])
    monkeypatch.setattr("controller.runtime_controller._utc_now", lambda: next(values))
    controller = _controller(monkeypatch)
    controller.handle_code_request({"op": "create", "template_id": "tpl-1"})

    before = controller.sessions["sbx-1"].last_used_at
    response = controller.handle_code_request({"op": "run_command", "sandbox_id": "sbx-1", "command": "echo ok"})

    assert response["ok"] is True
    assert controller.sessions["sbx-1"].last_used_at != before
    assert controller.sessions["sbx-1"].last_used_at == "2026-01-01T00:00:02Z"


def test_output_truncation_sets_flag(monkeypatch):
    monkeypatch.setenv("HERMY_MAX_OUTPUT_BYTES", "3")
    cube = FakeCubeClient()
    cube.command_stdout = "abcdef"
    controller = _controller(monkeypatch, cube)
    controller.handle_code_request({"op": "create", "template_id": "tpl-1"})

    response = controller.handle_code_request({"op": "run_command", "sandbox_id": "sbx-1", "command": "echo ok"})

    assert response["truncated"] is True
    assert response["stdout"].startswith("abc")


def test_output_redaction_removes_token_like_values_by_default(monkeypatch):
    """By default, token-like values are redacted from output."""
    cube = FakeCubeClient()
    cube.command_stdout = "token=raw-secret-value"
    controller = _controller(monkeypatch, cube)
    controller.handle_code_request({"op": "create", "template_id": "tpl-1"})

    response = controller.handle_code_request({"op": "run_command", "sandbox_id": "sbx-1", "command": "echo ok"})

    assert "raw-secret-value" not in response["stdout"]
    assert "token=[REDACTED]" in response["stdout"]


def test_approved_shell_without_approval_id_is_rejected(monkeypatch):
    """approved_shell=True without approval_id is rejected before client call."""
    cube = FakeCubeClient()
    controller = _controller(monkeypatch, cube)
    controller.handle_code_request({"op": "create", "template_id": "tpl-1"})

    response = controller.handle_code_request(
        {"op": "run_command", "sandbox_id": "sbx-1", "command": "echo ok && whoami", "approved_shell": True}
    )

    assert response["ok"] is False
    assert "approval_id" in response["error"].lower() or "approval" in response["error"].lower()
    # Should not call cube client when command is denied by policy
    assert not any(call[0] == "cube_run_command" for call in cube.calls)


def test_approved_shell_with_approval_id_allows_command(monkeypatch):
    """approved_shell=True with valid approval_id allows harmless shell composition."""
    cube = FakeCubeClient()
    controller = _controller(monkeypatch, cube)
    controller.handle_code_request({"op": "create", "template_id": "tpl-1"})

    response = controller.handle_code_request(
        {
            "op": "run_command",
            "sandbox_id": "sbx-1",
            "command": "echo ok && whoami",
            "approved_shell": True,
            "approval_id": "app-123",
        }
    )

    assert response["ok"] is True
    assert any(call[0] == "cube_run_command" for call in cube.calls)


def test_approval_id_is_included_in_audit_payload(monkeypatch):
    """approval_id is included in audit payload when approved shell is used."""
    events = []

    def capture_event(*args, **kwargs):
        events.append(kwargs)
        return True

    monkeypatch.setattr("controller.runtime_controller.event_logger.log_event", capture_event)
    cube = FakeCubeClient()
    controller = RuntimeController(cua_client=FakeCuaClient(), cube_client=cube)
    controller.handle_code_request({"op": "create", "template_id": "tpl-1"})

    controller.handle_code_request(
        {
            "op": "run_command",
            "sandbox_id": "sbx-1",
            "command": "echo ok && whoami",
            "approved_shell": True,
            "approval_id": "app-123",
        }
    )

    # Find event by looking for approval_id in payload
    command_event = next(event for event in events if event.get("payload", {}).get("approval_id"))
    assert command_event["payload"].get("approval_id") == "app-123"


def test_run_python_rejects_code_over_policy_limit(monkeypatch):
    monkeypatch.setenv("HERMY_MAX_CODE_BYTES", "3")
    cube = FakeCubeClient()
    controller = _controller(monkeypatch, cube)
    controller.handle_code_request({"op": "create", "template_id": "tpl-1"})

    response = controller.handle_code_request({"op": "run_python", "sandbox_id": "sbx-1", "code": "print(1)"})

    assert response["ok"] is False
    assert "python code exceeds maximum" in response["error"]
    assert not any(call[0] == "cube_run_python" for call in cube.calls)


def test_run_python_audit_includes_code_hash_and_size(monkeypatch):
    events = []

    def capture_event(*args, **kwargs):
        events.append(kwargs)
        return True

    monkeypatch.setattr("controller.runtime_controller.event_logger.log_event", capture_event)
    controller = RuntimeController(cua_client=FakeCuaClient(), cube_client=FakeCubeClient())
    controller.handle_code_request({"op": "create", "template_id": "tpl-1"})

    controller.handle_code_request({"op": "run_python", "sandbox_id": "sbx-1", "code": "print(1)"})

    python_event = next(event for event in events if event["payload"].get("code_sha256"))
    assert python_event["payload"]["code_bytes"] == len("print(1)".encode("utf-8"))
    assert len(python_event["payload"]["code_sha256"]) == 64


def test_controller_routes_code_request(monkeypatch):
    monkeypatch.setenv("HERMY_DEFAULT_TIMEOUT_SECONDS", "60")
    cube = FakeCubeClient()
    controller = _controller(monkeypatch, cube)

    created = controller.handle_code_request({"op": "create", "template_id": "tpl-1"})
    assert created["ok"] is True
    assert created["sandbox_id"] == "sbx-1"

    ran = controller.handle_code_request({"op": "run_command", "sandbox_id": "sbx-1", "command": "echo ok"})
    assert ran["ok"] is True
    assert ran["stdout"] == "ok"

    assert ("cube_create", {"template_id": "tpl-1", "metadata": {}, "allow_internet_access": False}) in cube.calls
    assert ("cube_run_command", {"sandbox_id": "sbx-1", "command": "echo ok", "timeout_seconds": 60}) in cube.calls


def test_controller_rejects_write_outside_workspace(monkeypatch):
    controller = _controller(monkeypatch)
    controller.handle_code_request({"op": "create", "template_id": "tpl-1"})

    response = controller.handle_code_request(
        {"op": "write_file", "sandbox_id": "sbx-1", "path": "/etc/passwd", "content": "nope"}
    )

    assert response["ok"] is False
    assert "workspace" in response["error"]


def test_controller_rejects_read_outside_workspace(monkeypatch):
    controller = _controller(monkeypatch)
    controller.handle_code_request({"op": "create", "template_id": "tpl-1"})

    response = controller.handle_code_request({"op": "read_file", "sandbox_id": "sbx-1", "path": "/etc/passwd"})

    assert response["ok"] is False
    assert "workspace" in response["error"]


def test_controller_rejects_cua_code_operation(monkeypatch):
    controller = _controller(monkeypatch)

    response = controller.handle_gui_request({"op": "run_command", "command": "echo no"})

    assert response["ok"] is False
    assert response["backend"] == "cua"
    assert "GUI operations only" in response["error"]


def test_controller_rejects_timeout_above_policy(monkeypatch):
    monkeypatch.setenv("HERMY_MAX_TIMEOUT_SECONDS", "30")
    controller = _controller(monkeypatch)
    controller.handle_code_request({"op": "create", "template_id": "tpl-1"})

    response = controller.handle_code_request(
        {"op": "run_command", "sandbox_id": "sbx-1", "command": "echo ok", "timeout_seconds": 31}
    )

    assert response["ok"] is False
    assert "timeout exceeds maximum" in response["error"]


def test_controller_requires_sandbox_id(monkeypatch):
    controller = _controller(monkeypatch)

    response = controller.handle_code_request({"op": "run_command", "command": "echo ok"})

    assert response["ok"] is False
    assert response["error"] == "sandbox_id is required"


def test_policy_max_code_bytes_reads_env(monkeypatch):
    monkeypatch.setenv("HERMY_MAX_CODE_BYTES", "123")

    assert policy.max_code_bytes() == 123
