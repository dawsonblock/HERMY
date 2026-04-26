"""MCP bridge for routing Hermes code execution into CubeSandbox."""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
import sys
import uuid
from typing import Any

from controller import policy
from controller.runtime_controller import RuntimeController


try:  # pragma: no cover - exercised indirectly when dependency is installed
    from mcp.server.fastmcp import FastMCP

    _MCP_SERVER_AVAILABLE = True
except ImportError:  # pragma: no cover - covered by import tests using fallback
    _MCP_SERVER_AVAILABLE = False

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


LOGGER = logging.getLogger(__name__)


class CubeSandboxClient:
    """Thin wrapper around ``e2b_code_interpreter.Sandbox``."""

    def __init__(self, template_id: str | None = None, sandbox_cls: Any | None = None) -> None:
        self.template_id = template_id or os.environ.get("CUBE_TEMPLATE_ID")
        self._sandbox_cls = sandbox_cls
        self._sandboxes: dict[str, Any] = {}

    def cube_create(
        self,
        template_id: str | None = None,
        timeout_seconds: int | None = None,
        metadata: dict[str, Any] | None = None,
        allow_internet_access: bool | None = None,
    ) -> dict[str, Any]:
        template = template_id or self.template_id
        if not template:
            raise RuntimeError("template_id is required or CUBE_TEMPLATE_ID must be set")

        sandbox_cls = self._load_sandbox_class()
        kwargs: dict[str, Any] = {"template": template}
        if timeout_seconds is not None:
            kwargs["timeout"] = timeout_seconds
        if metadata:
            kwargs["metadata"] = metadata
        if allow_internet_access is not None:
            kwargs["allow_internet_access"] = allow_internet_access

        sandbox = sandbox_cls.create(**kwargs)
        sandbox_id = getattr(sandbox, "sandbox_id", None)
        if not sandbox_id:
            raise RuntimeError("Cube sandbox did not return a sandbox_id")
        self._sandboxes[str(sandbox_id)] = sandbox
        return {
            "ok": True,
            "sandbox_id": str(sandbox_id),
            "template_id": template,
            "error": None,
        }

    def cube_run_command(
        self,
        sandbox_id: str,
        command: str,
        cwd: str | None = None,
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        sandbox = self._require_sandbox(sandbox_id)
        final_command = self._build_command(command, cwd=cwd)
        result = sandbox.commands.run(final_command, timeout=timeout_seconds)
        return self._format_command_result(sandbox_id, result)

    def cube_run_python(
        self,
        sandbox_id: str,
        code: str,
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        sandbox = self._require_sandbox(sandbox_id)
        if hasattr(sandbox, "run_code"):
            execution = sandbox.run_code(code, timeout=timeout_seconds)
            return self._format_python_result(sandbox_id, execution)

        scratch_path = f"/tmp/{uuid.uuid4().hex}.py"
        sandbox.files.write(scratch_path, code)
        result = sandbox.commands.run(f"python {shlex.quote(scratch_path)}", timeout=timeout_seconds)
        return self._format_command_result(sandbox_id, result)

    def cube_read_file(self, sandbox_id: str, path: str) -> dict[str, Any]:
        sandbox = self._require_sandbox(sandbox_id)
        content = sandbox.files.read(path)
        return {
            "ok": True,
            "sandbox_id": sandbox_id,
            "path": path,
            "content": content,
            "error": None,
        }

    def cube_write_file(self, sandbox_id: str, path: str, content: str) -> dict[str, Any]:
        sandbox = self._require_sandbox(sandbox_id)
        sandbox.files.write(path, content)
        return {
            "ok": True,
            "sandbox_id": sandbox_id,
            "path": path,
            "bytes_written": len(content.encode("utf-8")),
            "error": None,
        }

    def cube_destroy(self, sandbox_id: str) -> dict[str, Any]:
        sandbox = self._require_sandbox(sandbox_id)
        if hasattr(sandbox, "kill"):
            sandbox.kill()
        elif hasattr(sandbox, "close"):
            sandbox.close()
        else:
            raise RuntimeError("sandbox object does not support kill() or close()")
        self._sandboxes.pop(sandbox_id, None)
        return {"ok": True, "sandbox_id": sandbox_id, "error": None}

    def _load_sandbox_class(self) -> Any:
        if self._sandbox_cls is not None:
            return self._sandbox_cls
        try:
            from e2b_code_interpreter import Sandbox
        except ImportError as exc:
            raise ImportError(
                "Cube bridge requires 'e2b_code_interpreter'. "
                f"Install with: {sys.executable} -m pip install e2b-code-interpreter"
            ) from exc
        self._sandbox_cls = Sandbox
        return self._sandbox_cls

    def _require_sandbox(self, sandbox_id: str) -> Any:
        sandbox = self._sandboxes.get(str(sandbox_id))
        if sandbox is None:
            raise ValueError(f"unknown sandbox_id: {sandbox_id}")
        return sandbox

    def _build_command(self, command: str, *, cwd: str | None) -> str:
        if not cwd:
            return command
        resolved_cwd = policy.resolve_workspace_path(cwd)
        return f"cd {shlex.quote(str(resolved_cwd))} && {command}"

    def _format_command_result(self, sandbox_id: str, result: Any) -> dict[str, Any]:
        return {
            "ok": getattr(result, "exit_code", 0) == 0,
            "sandbox_id": sandbox_id,
            "stdout": getattr(result, "stdout", ""),
            "stderr": getattr(result, "stderr", ""),
            "exit_code": getattr(result, "exit_code", 0),
            "error": None if getattr(result, "exit_code", 0) == 0 else getattr(result, "stderr", "") or "command failed",
        }

    def _format_python_result(self, sandbox_id: str, execution: Any) -> dict[str, Any]:
        logs = getattr(execution, "logs", None)
        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []
        if logs:
            stdout_chunks.extend(getattr(logs, "stdout", []) or [])
            stderr_chunks.extend(getattr(logs, "stderr", []) or [])
        error_obj = getattr(execution, "error", None)
        error_message = None
        if error_obj is not None:
            error_message = getattr(error_obj, "value", None) or str(error_obj)
        return {
            "ok": error_message is None,
            "sandbox_id": sandbox_id,
            "stdout": "".join(stdout_chunks),
            "stderr": "".join(stderr_chunks),
            "exit_code": 0 if error_message is None else 1,
            "error": error_message,
        }


class NullCuaClient:
    """Placeholder CUA client used until a real GUI backend is wired in."""

    def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "ok": False,
            "backend": "cua",
            "operation": payload.get("op"),
            "error": "CUA client is not configured in this bridge",
        }


_runtime_controller: RuntimeController | None = None


def get_runtime_controller() -> RuntimeController:
    global _runtime_controller
    if _runtime_controller is None:
        _runtime_controller = RuntimeController(
            cua_client=NullCuaClient(),
            cube_client=CubeSandboxClient(),
        )
    return _runtime_controller


def set_runtime_controller(controller: RuntimeController | None) -> None:
    global _runtime_controller
    _runtime_controller = controller


def cube_create(
    template_id: str | None = None,
    timeout_seconds: int | None = None,
    allow_internet_access: bool | None = None,
) -> dict[str, Any]:
    return get_runtime_controller().handle_code_request(
        {
            "op": "create",
            "template_id": template_id,
            "timeout_seconds": timeout_seconds,
            "allow_internet_access": allow_internet_access,
        }
    )


def cube_run_command(
    sandbox_id: str,
    command: str,
    cwd: str | None = None,
    timeout_seconds: int | None = None,
) -> dict[str, Any]:
    return get_runtime_controller().handle_code_request(
        {
            "op": "run_command",
            "sandbox_id": sandbox_id,
            "command": command,
            "cwd": cwd,
            "timeout_seconds": timeout_seconds,
        }
    )


def cube_run_python(
    sandbox_id: str,
    code: str,
    timeout_seconds: int | None = None,
) -> dict[str, Any]:
    return get_runtime_controller().handle_code_request(
        {
            "op": "run_python",
            "sandbox_id": sandbox_id,
            "code": code,
            "timeout_seconds": timeout_seconds,
        }
    )


def cube_read_file(sandbox_id: str, path: str) -> dict[str, Any]:
    return get_runtime_controller().handle_code_request(
        {
            "op": "read_file",
            "sandbox_id": sandbox_id,
            "path": path,
        }
    )


def cube_write_file(sandbox_id: str, path: str, content: str) -> dict[str, Any]:
    return get_runtime_controller().handle_code_request(
        {
            "op": "write_file",
            "sandbox_id": sandbox_id,
            "path": path,
            "content": content,
        }
    )


def cube_destroy(sandbox_id: str) -> dict[str, Any]:
    return get_runtime_controller().handle_code_request(
        {
            "op": "destroy",
            "sandbox_id": sandbox_id,
        }
    )


def create_mcp_server(controller: RuntimeController | None = None) -> FastMCP:
    mcp_server = FastMCP(
        "cube",
        instructions=(
            "Use these tools to create Cube sandboxes, execute commands or Python, "
            "and read or write sandbox files under /workspace."
        ),
    )

    if controller is not None:
        set_runtime_controller(controller)

    mcp_server.tool()(cube_create)
    mcp_server.tool()(cube_run_command)
    mcp_server.tool()(cube_run_python)
    mcp_server.tool()(cube_read_file)
    mcp_server.tool()(cube_write_file)
    mcp_server.tool()(cube_destroy)

    return mcp_server


mcp = create_mcp_server()


def run_mcp_server(verbose: bool = False) -> None:
    """Start the bridge on stdio."""
    if not _MCP_SERVER_AVAILABLE:
        print(
            "Error: MCP server requires the 'mcp' package.\n"
            f"Install with: {sys.executable} -m pip install mcp",
            file=sys.stderr,
        )
        sys.exit(1)

    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )
    controller = get_runtime_controller()

    async def _run() -> None:
        try:
            await mcp.run_stdio_async()
        finally:
            controller.cleanup()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        LOGGER.info("Cube MCP server interrupted")


if __name__ == "__main__":
    run_mcp_server()
