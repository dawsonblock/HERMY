"""Tests for the runtime controller."""

from __future__ import annotations

from controller.runtime_controller import RuntimeController


class FakeCuaClient:
    def screenshot(self) -> dict[str, str]:
        return {"image": "ok"}


class FakeCubeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def cube_create(self, **kwargs):
        self.calls.append(("cube_create", kwargs))
        return {"ok": True, "sandbox_id": "sbx-1", "template_id": kwargs.get("template_id")}

    def cube_run_command(self, **kwargs):
        self.calls.append(("cube_run_command", kwargs))
        return {"ok": True, "sandbox_id": kwargs["sandbox_id"], "stdout": "ok", "stderr": "", "exit_code": 0, "error": None}

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


def test_controller_routes_gui_request(monkeypatch):
    monkeypatch.setattr("controller.runtime_controller.event_logger.log_event", lambda *args, **kwargs: True)
    controller = RuntimeController(cua_client=FakeCuaClient(), cube_client=FakeCubeClient())

    response = controller.handle_gui_request({"op": "screenshot"})

    assert response["ok"] is True
    assert response["backend"] == "cua"
    assert response["result"] == {"image": "ok"}


def test_controller_routes_code_request(monkeypatch):
    monkeypatch.setattr("controller.runtime_controller.event_logger.log_event", lambda *args, **kwargs: True)
    cube = FakeCubeClient()
    controller = RuntimeController(cua_client=None, cube_client=cube)

    created = controller.handle_code_request({"op": "create", "template_id": "tpl-1"})
    assert created["ok"] is True
    assert created["sandbox_id"] == "sbx-1"

    ran = controller.handle_code_request({"op": "run_command", "sandbox_id": "sbx-1", "command": "echo ok"})
    assert ran["ok"] is True
    assert ran["stdout"] == "ok"

    assert ("cube_create", {"template_id": "tpl-1", "metadata": {}}) in cube.calls
    assert ("cube_run_command", {"sandbox_id": "sbx-1", "command": "echo ok"}) in cube.calls


def test_controller_rejects_write_outside_workspace(monkeypatch):
    monkeypatch.setattr("controller.runtime_controller.event_logger.log_event", lambda *args, **kwargs: True)
    controller = RuntimeController(cua_client=None, cube_client=FakeCubeClient())

    response = controller.handle_code_request(
        {"op": "write_file", "sandbox_id": "sbx-1", "path": "/etc/passwd", "content": "nope"}
    )

    assert response["ok"] is False
    assert "workspace" in response["error"]


def test_controller_requires_sandbox_id(monkeypatch):
    monkeypatch.setattr("controller.runtime_controller.event_logger.log_event", lambda *args, **kwargs: True)
    controller = RuntimeController(cua_client=None, cube_client=FakeCubeClient())

    response = controller.handle_code_request({"op": "run_command", "command": "echo ok"})

    assert response["ok"] is False
    assert response["error"] == "sandbox_id is required"
