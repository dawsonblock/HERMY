"""Tests for the Cube MCP bridge."""

import importlib
import inspect
from types import SimpleNamespace

from controller.runtime_controller import RuntimeController


REQUIRED_TOOLS = [
    "cube_health",
    "cube_create",
    "cube_list_sessions",
    "cube_run_command",
    "cube_run_python",
    "cube_read_file",
    "cube_write_file",
    "cube_destroy",
    "cube_destroy_all",
]


class FakeCubeClient:
    def __init__(self):
        self.calls = []

    def cube_create(self, **kwargs):
        self.calls.append(("cube_create", kwargs))
        return {"ok": True, "sandbox_id": "sbx-1", "template_id": kwargs.get("template_id")}

    def cube_run_command(self, **kwargs):
        self.calls.append(("cube_run_command", kwargs))
        return {"ok": True, "sandbox_id": kwargs["sandbox_id"], "stdout": "ok", "stderr": "", "exit_code": 0, "error": None}

    def cube_read_file(self, **kwargs):
        self.calls.append(("cube_read_file", kwargs))
        return {"ok": True, "sandbox_id": kwargs["sandbox_id"], "path": kwargs["path"], "content": "ok", "error": None}

    def cube_write_file(self, **kwargs):
        self.calls.append(("cube_write_file", kwargs))
        return {"ok": True, "sandbox_id": kwargs["sandbox_id"], "path": kwargs["path"], "bytes_written": 2, "error": None}

    def cube_destroy(self, **kwargs):
        self.calls.append(("cube_destroy", kwargs))
        return {"ok": True, "sandbox_id": kwargs["sandbox_id"], "error": None}


def _bridge(monkeypatch):
    monkeypatch.syspath_prepend(".")
    module = importlib.import_module("cube_bridge.cube_mcp_server", package="integration")
    module.set_runtime_controller(None)
    return module


def test_bridge_importable(monkeypatch):
    module = _bridge(monkeypatch)

    assert hasattr(module, "mcp")
    for name in REQUIRED_TOOLS:
        assert hasattr(module, name)
        assert inspect.isfunction(getattr(module, name))


def test_tool_registration_includes_required_tools(monkeypatch):
    module = _bridge(monkeypatch)

    class DummyFastMCP:
        def __init__(self, name, instructions=None):
            self.name = name
            self.instructions = instructions
            self.tools = {}

        def tool(self, fn=None):
            def decorate(func):
                self.tools[func.__name__] = func
                return func

            return decorate(fn) if fn else decorate

    monkeypatch.setattr(module, "FastMCP", DummyFastMCP)
    server = module.create_mcp_server(controller=RuntimeController(cua_client=None, cube_client=FakeCubeClient()))

    assert set(REQUIRED_TOOLS).issubset(set(server.tools))


def test_bridge_rejects_missing_sandbox_id(monkeypatch):
    module = _bridge(monkeypatch)

    response = module.cube_run_command(command="echo ok", sandbox_id="")

    assert response["ok"] is False
    assert response["error"] == "sandbox_id is required"


def test_bridge_rejects_write_outside_workspace(monkeypatch):
    module = _bridge(monkeypatch)
    controller = RuntimeController(cua_client=None, cube_client=FakeCubeClient())
    module.set_runtime_controller(controller)
    module.cube_create(template_id="tpl")

    response = module.cube_write_file(sandbox_id="sbx-1", path="/etc/passwd", content="nope")

    assert response["ok"] is False
    assert "workspace" in response["error"]


def test_bridge_rejects_read_outside_workspace(monkeypatch):
    module = _bridge(monkeypatch)
    controller = RuntimeController(cua_client=None, cube_client=FakeCubeClient())
    module.set_runtime_controller(controller)
    module.cube_create(template_id="tpl")

    response = module.cube_read_file(sandbox_id="sbx-1", path="/etc/passwd")

    assert response["ok"] is False
    assert "workspace" in response["error"]


def test_missing_env_vars_produce_clear_create_error(monkeypatch):
    module = _bridge(monkeypatch)
    monkeypatch.delenv("CUBE_TEMPLATE_ID", raising=False)
    controller = RuntimeController(cua_client=None, cube_client=module.CubeSandboxClient(template_id=None, sandbox_cls=SimpleNamespace()))
    module.set_runtime_controller(controller)

    response = module.cube_create()

    assert response["ok"] is False
    assert "template_id is required" in response["error"]


def test_fake_controller_path_works(monkeypatch):
    module = _bridge(monkeypatch)

    class FakeController:
        def __init__(self):
            self.requests = []

        def handle_code_request(self, request):
            self.requests.append(request)
            return {"ok": True, "operation": request["op"]}

    controller = FakeController()
    module.set_runtime_controller(controller)

    response = module.cube_health()

    assert response == {"ok": True, "operation": "health"}
    assert controller.requests == [{"op": "health"}]


def test_python_fallback_writes_scratch_under_workspace(monkeypatch):
    module = _bridge(monkeypatch)
    monkeypatch.setenv("CUBE_WORKSPACE_DIR", "/workspace")

    class FakeCommands:
        def __init__(self):
            self.commands = []

        def run(self, command, timeout=None):
            self.commands.append((command, timeout))
            return SimpleNamespace(stdout="ok", stderr="", exit_code=0)

    class FakeFiles:
        def __init__(self):
            self.writes = []

        def write(self, path, content):
            self.writes.append((path, content))

    class FakeSandbox:
        sandbox_id = "sbx-1"

        def __init__(self):
            self.commands = FakeCommands()
            self.files = FakeFiles()

    client = module.CubeSandboxClient(template_id="tpl", sandbox_cls=SimpleNamespace(create=lambda **_: FakeSandbox()))
    client.cube_create()
    response = client.cube_run_python("sbx-1", "print('ok')", timeout_seconds=10)

    sandbox = client._sandboxes["sbx-1"]
    assert response["ok"] is True
    assert sandbox.files.writes[0][0].startswith("/workspace/.hermy/tmp/")
    assert sandbox.commands.commands[0][0] == "mkdir -p /workspace/.hermy/tmp"


def test_command_list_is_converted_to_quoted_shell_command(monkeypatch):
    module = _bridge(monkeypatch)

    class FakeCommands:
        def __init__(self):
            self.commands = []

        def run(self, command, timeout=None):
            self.commands.append((command, timeout))
            return SimpleNamespace(stdout="ok", stderr="", exit_code=0)

    class FakeSandbox:
        sandbox_id = "sbx-1"

        def __init__(self):
            self.commands = FakeCommands()

    client = module.CubeSandboxClient(template_id="tpl", sandbox_cls=SimpleNamespace(create=lambda **_: FakeSandbox()))
    client.cube_create()

    response = client.cube_run_command("sbx-1", ["echo", "ok && whoami"], timeout_seconds=10)

    sandbox = client._sandboxes["sbx-1"]
    assert response["ok"] is True
    assert sandbox.commands.commands == [("echo 'ok && whoami'", 10)]


def test_mcp_bridge_forwards_approval_id_to_controller(monkeypatch):
    """MCP bridge forwards approval_id to RuntimeController."""
    module = _bridge(monkeypatch)

    class FakeController:
        def __init__(self):
            self.requests = []

        def handle_code_request(self, request):
            self.requests.append(request)
            return {"ok": True, "operation": request["op"], "approval_id": request.get("approval_id")}

    controller = FakeController()
    module.set_runtime_controller(controller)

    response = module.cube_run_command(
        sandbox_id="sbx-1",
        command="echo ok && whoami",
        approved_shell=True,
        approval_id="app-123",
    )

    assert response["ok"] is True
    assert controller.requests == [
        {
            "op": "run_command",
            "sandbox_id": "sbx-1",
            "command": "echo ok && whoami",
            "cwd": None,
            "timeout_seconds": None,
            "approved_shell": True,
            "approval_id": "app-123",
        }
    ]
