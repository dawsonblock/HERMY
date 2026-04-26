"""Runtime controller for routing GUI and Cube-backed operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import uuid
import inspect
from typing import Any

from . import event_logger, policy

_CUA_DENIED_OPERATION_TERMS = ("command", "shell", "python", "file", "exec", "terminal")


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass
class CubeSession:
    """Represent an active Cube sandbox session."""

    sandbox_id: str
    template_id: str | None
    created_at: str
    metadata: dict[str, Any] = field(default_factory=dict)


class RuntimeController:
    """Coordinate calls to CUA and Cube based on policy and request type."""

    def __init__(self, cua_client: object | None, cube_client: object) -> None:
        self.cua_client = cua_client
        self.cube_client = cube_client
        self.sessions: dict[str, CubeSession] = {}

    def handle_gui_request(self, request: dict[str, Any]) -> dict[str, Any]:
        request_id = request.get("request_id") or uuid.uuid4().hex
        op = request.get("op")
        if not op:
            return self._error_response("cua", request_id, "missing GUI operation")
        if self._is_cube_only_operation(str(op)):
            return self._error_response(
                "cua",
                request_id,
                "CUA is configured for GUI operations only; use Cube for code, shell, and file operations",
                op=op,
            )

        try:
            result = self._dispatch(self.cua_client, op, request)
        except Exception as exc:
            response = self._error_response("cua", request_id, str(exc), op=op)
            response["warnings"] = self._audit(
                event_type="cua_error",
                data={"request_id": request_id, "operation": op, "error": str(exc)},
            )
            return response

        warnings = self._audit(
            event_type="cua_request",
            data={"request_id": request_id, "operation": op},
        )
        return {
            "ok": True,
            "backend": "cua",
            "request_id": request_id,
            "operation": op,
            "result": result,
            "warnings": warnings,
        }

    def handle_code_request(self, request: dict[str, Any]) -> dict[str, Any]:
        request_id = request.get("request_id") or uuid.uuid4().hex
        op = request.get("op")
        if not op:
            return self._error_response("cube", request_id, "missing code operation")

        try:
            if op == "create":
                response = self._handle_create(request_id, request)
            elif op == "run_command":
                response = self._handle_run_command(request_id, request)
            elif op == "run_python":
                response = self._handle_run_python(request_id, request)
            elif op == "read_file":
                response = self._handle_read_file(request_id, request)
            elif op == "write_file":
                response = self._handle_write_file(request_id, request)
            elif op == "destroy":
                response = self._handle_destroy(request_id, request)
            else:
                return self._error_response("cube", request_id, f"unsupported code operation: {op}", op=op)
        except Exception as exc:
            response = self._error_response("cube", request_id, str(exc), op=op)
            response["warnings"] = self._audit(
                event_type="cube_error",
                data={"request_id": request_id, "operation": op, "error": str(exc)},
            )
            return response

        response.setdefault("request_id", request_id)
        response.setdefault("backend", "cube")
        response.setdefault("operation", op)
        response.setdefault("warnings", [])
        return response

    def cleanup(self) -> list[dict[str, Any]]:
        """Destroy all active Cube sandboxes and return the results."""
        results: list[dict[str, Any]] = []
        for sandbox_id in list(self.sessions):
            results.append(
                self.handle_code_request(
                    {"op": "destroy", "sandbox_id": sandbox_id, "request_id": uuid.uuid4().hex}
                )
            )
        return results

    def _handle_create(self, request_id: str, request: dict[str, Any]) -> dict[str, Any]:
        timeout = None
        if request.get("timeout_seconds") is not None:
            timeout_decision = policy.validate_timeout(request.get("timeout_seconds"))
            if not timeout_decision.allowed:
                return self._denied_response(request_id, "create", timeout_decision.reason or "timeout denied")
            timeout = int(timeout_decision.normalized_value or policy.default_timeout_seconds())
        result = self._dispatch(
            self.cube_client,
            "cube_create",
            {
                "template_id": request.get("template_id"),
                "timeout_seconds": timeout,
                "metadata": request.get("metadata") or {},
                "allow_internet_access": request.get("allow_internet_access"),
            },
        )
        sandbox_id = self._extract_sandbox_id(result)
        self.sessions[sandbox_id] = CubeSession(
            sandbox_id=sandbox_id,
            template_id=request.get("template_id") or result.get("template_id"),
            created_at=_utc_now(),
            metadata=request.get("metadata") or {},
        )
        warnings = self._audit(
            event_type="cube_create",
            data={"request_id": request_id, "sandbox_id": sandbox_id},
        )
        return self._success_response(request_id, "create", result, warnings)

    def _handle_run_command(self, request_id: str, request: dict[str, Any]) -> dict[str, Any]:
        sandbox_id = self._require_sandbox_id(request)
        decision = policy.validate_command(request.get("command", ""))
        if not decision.allowed:
            return self._denied_response(request_id, "run_command", decision.reason or "command denied")
        timeout = policy.validate_timeout(request.get("timeout_seconds"))
        if not timeout.allowed:
            return self._denied_response(request_id, "run_command", timeout.reason or "timeout denied")
        cwd = request.get("cwd")
        if cwd:
            cwd_decision = policy.validate_read_path(cwd)
            if not cwd_decision.allowed:
                return self._denied_response(request_id, "run_command", cwd_decision.reason or "cwd denied")
            cwd = cwd_decision.normalized_value
        result = self._dispatch(
            self.cube_client,
            "cube_run_command",
            {
                "sandbox_id": sandbox_id,
                "command": decision.normalized_value,
                "cwd": cwd,
                "timeout_seconds": int(timeout.normalized_value or policy.default_timeout_seconds()),
            },
        )
        warnings = self._audit(
            event_type="cube_command",
            data={"request_id": request_id, "sandbox_id": sandbox_id, "command": decision.normalized_value},
        )
        return self._success_response(request_id, "run_command", result, warnings)

    def _handle_run_python(self, request_id: str, request: dict[str, Any]) -> dict[str, Any]:
        sandbox_id = self._require_sandbox_id(request)
        code = request.get("code", "")
        if not code or not str(code).strip():
            return self._denied_response(request_id, "run_python", "python code cannot be empty")
        timeout = policy.validate_timeout(request.get("timeout_seconds"))
        if not timeout.allowed:
            return self._denied_response(request_id, "run_python", timeout.reason or "timeout denied")
        result = self._dispatch(
            self.cube_client,
            "cube_run_python",
            {
                "sandbox_id": sandbox_id,
                "code": code,
                "timeout_seconds": int(timeout.normalized_value or policy.default_timeout_seconds()),
            },
        )
        warnings = self._audit(
            event_type="cube_python",
            data={"request_id": request_id, "sandbox_id": sandbox_id},
        )
        return self._success_response(request_id, "run_python", result, warnings)

    def _handle_read_file(self, request_id: str, request: dict[str, Any]) -> dict[str, Any]:
        sandbox_id = self._require_sandbox_id(request)
        path = request.get("path")
        if not path:
            return self._denied_response(request_id, "read_file", "path is required")
        decision = policy.validate_read_path(path)
        if not decision.allowed:
            return self._denied_response(request_id, "read_file", decision.reason or "read denied")
        result = self._dispatch(
            self.cube_client,
            "cube_read_file",
            {"sandbox_id": sandbox_id, "path": decision.normalized_value},
        )
        warnings = self._audit(
            event_type="cube_read_file",
            data={"request_id": request_id, "sandbox_id": sandbox_id, "path": decision.normalized_value},
        )
        return self._success_response(request_id, "read_file", result, warnings)

    def _handle_write_file(self, request_id: str, request: dict[str, Any]) -> dict[str, Any]:
        sandbox_id = self._require_sandbox_id(request)
        path = request.get("path", "")
        decision = policy.validate_write_path(path)
        if not decision.allowed:
            return self._denied_response(request_id, "write_file", decision.reason or "write denied")
        content = request.get("content", "")
        content_decision = policy.validate_file_content(str(content))
        if not content_decision.allowed:
            return self._denied_response(request_id, "write_file", content_decision.reason or "content denied")
        result = self._dispatch(
            self.cube_client,
            "cube_write_file",
            {
                "sandbox_id": sandbox_id,
                "path": decision.normalized_value,
                "content": str(content),
            },
        )
        warnings = self._audit(
            event_type="cube_write_file",
            data={"request_id": request_id, "sandbox_id": sandbox_id, "path": decision.normalized_value},
        )
        return self._success_response(request_id, "write_file", result, warnings)

    def _handle_destroy(self, request_id: str, request: dict[str, Any]) -> dict[str, Any]:
        sandbox_id = self._require_sandbox_id(request)
        result = self._dispatch(
            self.cube_client,
            "cube_destroy",
            {"sandbox_id": sandbox_id},
        )
        self.sessions.pop(sandbox_id, None)
        warnings = self._audit(
            event_type="cube_destroy",
            data={"request_id": request_id, "sandbox_id": sandbox_id},
        )
        return self._success_response(request_id, "destroy", result, warnings)

    def _dispatch(self, client: object | None, op: str, payload: dict[str, Any]) -> Any:
        if client is None:
            raise RuntimeError("backend client is not configured")

        if hasattr(client, op):
            method = getattr(client, op)
            kwargs = {
                key: value
                for key, value in payload.items()
                if key not in {"op", "request_id"} and value is not None
            }
            if not kwargs:
                return method()

            signature = inspect.signature(method)
            if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in signature.parameters.values()):
                return method(**kwargs)

            filtered_kwargs = {
                key: value
                for key, value in kwargs.items()
                if key in signature.parameters
            }
            return method(**filtered_kwargs)

        if hasattr(client, "execute"):
            return client.execute({"op": op, **payload})

        raise RuntimeError(f"backend client does not implement {op}")

    def _is_cube_only_operation(self, op: str) -> bool:
        lowered = op.lower()
        return any(term in lowered for term in _CUA_DENIED_OPERATION_TERMS)

    def _require_sandbox_id(self, request: dict[str, Any]) -> str:
        sandbox_id = request.get("sandbox_id")
        if not sandbox_id:
            raise ValueError("sandbox_id is required")
        return str(sandbox_id)

    def _extract_sandbox_id(self, result: Any) -> str:
        if isinstance(result, dict):
            sandbox_id = result.get("sandbox_id")
            if sandbox_id:
                return str(sandbox_id)
        raise RuntimeError("cube_create did not return a sandbox_id")

    def _audit(self, event_type: str, data: dict[str, Any]) -> list[str]:
        warnings_list: list[str] = []
        if not event_logger.log_event(event_type, data):
            warnings_list.append("audit log write failed")
        return warnings_list

    def _success_response(
        self,
        request_id: str,
        op: str,
        result: Any,
        warnings: list[str],
    ) -> dict[str, Any]:
        if isinstance(result, dict):
            response = dict(result)
            response.setdefault("ok", True)
        else:
            response = {"ok": True, "result": result}
        for key in ("stdout", "stderr", "content"):
            if isinstance(response.get(key), str):
                response[key] = policy.truncate_text(response[key])
        response.update(
            {
                "backend": "cube",
                "request_id": request_id,
                "operation": op,
                "warnings": warnings,
            }
        )
        return response

    def _denied_response(self, request_id: str, op: str, reason: str) -> dict[str, Any]:
        return {
            "ok": False,
            "backend": "cube",
            "request_id": request_id,
            "operation": op,
            "error": reason,
            "warnings": [],
        }

    def _error_response(
        self,
        backend: str,
        request_id: str,
        reason: str,
        *,
        op: str | None = None,
    ) -> dict[str, Any]:
        return {
            "ok": False,
            "backend": backend,
            "request_id": request_id,
            "operation": op,
            "error": reason,
            "warnings": [],
        }
