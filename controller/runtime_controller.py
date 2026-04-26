"""Runtime controller for routing GUI and Cube-backed operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import inspect
import time
import uuid
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
    last_used_at: str
    allow_internet: bool
    status: str = "active"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sandbox_id": self.sandbox_id,
            "template_id": self.template_id,
            "created_at": self.created_at,
            "last_used_at": self.last_used_at,
            "allow_internet": self.allow_internet,
            "status": self.status,
            "metadata": self.metadata,
        }


class RuntimeController:
    """Coordinate calls to CUA and Cube based on policy and request type."""

    def __init__(self, cua_client: object | None, cube_client: object) -> None:
        self.cua_client = cua_client
        self.cube_client = cube_client
        self.sessions: dict[str, CubeSession] = {}
        self.started_at = _utc_now()

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

        started = time.perf_counter()
        try:
            result = self._dispatch(self.cua_client, op, request)
        except Exception as exc:
            duration_ms = self._duration_ms(started)
            response = self._error_response("cua", request_id, str(exc), op=op)
            response["warnings"] = self._audit(
                event_type="cua_request",
                request_id=request_id,
                status="error",
                duration_ms=duration_ms,
                payload={"operation": op},
                error=str(exc),
            )
            return response

        duration_ms = self._duration_ms(started)
        result_ok = self._is_success_result(result)
        result_error = self._result_error(result)
        warnings = self._audit(
            event_type="cua_request",
            request_id=request_id,
            status="success" if result_ok else "error",
            duration_ms=duration_ms,
            payload={"operation": op},
            error=result_error,
        )
        response = {
            "ok": result_ok,
            "backend": "cua",
            "request_id": request_id,
            "operation": op,
            "result": result,
            "warnings": warnings,
        }
        if not result_ok and result_error:
            response["error"] = event_logger.redact_tool_output(result_error)
        return response

    def handle_code_request(self, request: dict[str, Any]) -> dict[str, Any]:
        request_id = request.get("request_id") or uuid.uuid4().hex
        op = request.get("op")
        if not op:
            return self._error_response("cube", request_id, "missing code operation")

        try:
            if op == "health":
                response = self._handle_health(request_id)
            elif op == "list_sessions":
                response = self._handle_list_sessions(request_id)
            elif op == "create":
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
            elif op == "destroy_all":
                response = self._handle_destroy_all(request_id)
            else:
                return self._error_response("cube", request_id, f"unsupported code operation: {op}", op=op)
        except Exception as exc:
            sandbox_id = request.get("sandbox_id")
            response = self._error_response("cube", request_id, str(exc), op=op)
            response["warnings"] = self._audit(
                event_type=f"cube_{op}",
                request_id=request_id,
                sandbox_id=str(sandbox_id) if sandbox_id else None,
                status="error",
                payload={"operation": op},
                error=str(exc),
            )
            return response

        response.setdefault("request_id", request_id)
        response.setdefault("backend", "cube")
        response.setdefault("operation", op)
        response.setdefault("warnings", [])
        return response

    def cleanup(self) -> list[dict[str, Any]]:
        """Destroy all active Cube sandboxes and return the per-sandbox results."""
        request_id = uuid.uuid4().hex
        try:
            return self._handle_destroy_all(request_id)["results"]
        except Exception as exc:  # pragma: no cover - defensive shutdown path
            warnings = self._audit(
                event_type="cube_cleanup",
                request_id=request_id,
                status="error",
                payload={"active_session_count": len(self.sessions)},
                error=str(exc),
            )
            return [{"ok": False, "backend": "cube", "operation": "cleanup", "error": str(exc), "warnings": warnings}]

    def _handle_health(self, request_id: str) -> dict[str, Any]:
        return {
            "ok": True,
            "backend": "cube",
            "request_id": request_id,
            "operation": "health",
            "active_session_count": len(self.sessions),
            "started_at": self.started_at,
            "sessions": [session.to_dict() for session in self.sessions.values()],
            "warnings": [],
        }

    def _handle_list_sessions(self, request_id: str) -> dict[str, Any]:
        return {
            "ok": True,
            "backend": "cube",
            "request_id": request_id,
            "operation": "list_sessions",
            "sessions": [session.to_dict() for session in self.sessions.values()],
            "active_session_count": len(self.sessions),
            "warnings": [],
        }

    def _handle_create(self, request_id: str, request: dict[str, Any]) -> dict[str, Any]:
        timeout = None
        if request.get("timeout_seconds") is not None:
            timeout_decision = policy.validate_timeout(request.get("timeout_seconds"))
            if not timeout_decision.allowed:
                return self._denied_response(request_id, "create", timeout_decision.reason or "timeout denied")
            timeout = int(timeout_decision.normalized_value)

        internet_decision = policy.validate_allow_internet(request.get("allow_internet_access"))
        if not internet_decision.allowed:
            return self._denied_response(request_id, "create", internet_decision.reason or "internet access denied")
        allow_internet = bool(internet_decision.normalized_value)
        metadata = request.get("metadata") or {}
        started = time.perf_counter()
        result = self._dispatch(
            self.cube_client,
            "cube_create",
            {
                "template_id": request.get("template_id"),
                "timeout_seconds": timeout,
                "metadata": metadata,
                "allow_internet_access": allow_internet,
            },
        )
        duration_ms = self._duration_ms(started)
        sandbox_id = self._extract_sandbox_id(result)
        now = _utc_now()
        self.sessions[sandbox_id] = CubeSession(
            sandbox_id=sandbox_id,
            template_id=request.get("template_id") or result.get("template_id"),
            created_at=now,
            last_used_at=now,
            allow_internet=allow_internet,
            status="active",
            metadata=metadata,
        )
        warnings = self._audit(
            event_type="cube_create",
            request_id=request_id,
            sandbox_id=sandbox_id,
            status="success",
            duration_ms=duration_ms,
            payload={"template_id": request.get("template_id"), "metadata": metadata, "allow_internet": allow_internet},
        )
        return self._success_response(request_id, "create", result, warnings)

    def _handle_run_command(self, request_id: str, request: dict[str, Any]) -> dict[str, Any]:
        session = self._require_known_session(request)
        approved = bool(request.get("approved_shell") or request.get("approved"))
        approval_id = request.get("approval_id")
        decision = policy.validate_command(request.get("command", ""), approved=approved, approval_id=approval_id)
        if not decision.allowed:
            return self._denied_response(request_id, "run_command", decision.reason or "command denied", session.sandbox_id)
        timeout = policy.validate_timeout(request.get("timeout_seconds"))
        if not timeout.allowed:
            return self._denied_response(request_id, "run_command", timeout.reason or "timeout denied", session.sandbox_id)
        if request.get("cwd"):
            return self._denied_response(
                request_id,
                "run_command",
                "cwd is not supported until native Cube working-directory support is confirmed",
                session.sandbox_id,
            )

        started = time.perf_counter()
        result = self._dispatch(
            self.cube_client,
            "cube_run_command",
            {
                "sandbox_id": session.sandbox_id,
                "command": decision.normalized_value,
                "timeout_seconds": int(timeout.normalized_value),
                "approval_id": approval_id,
            },
        )
        duration_ms = self._duration_ms(started)
        if self._is_success_result(result):
            self._mark_session_used(session.sandbox_id)
        audit_payload: dict[str, Any] = {"command": decision.normalized_value}
        if approved and approval_id:
            audit_payload["approval_id"] = approval_id
        warnings = self._audit(
            event_type="cube_run_command",
            request_id=request_id,
            sandbox_id=session.sandbox_id,
            status="success" if self._is_success_result(result) else "error",
            duration_ms=duration_ms,
            payload=audit_payload,
            error=self._result_error(result),
        )
        return self._success_response(request_id, "run_command", result, warnings)

    def _handle_run_python(self, request_id: str, request: dict[str, Any]) -> dict[str, Any]:
        session = self._require_known_session(request)
        code = request.get("code", "")
        if not code or not str(code).strip():
            return self._denied_response(request_id, "run_python", "python code cannot be empty", session.sandbox_id)
        code_text = str(code)
        code_decision = policy.validate_python_code(code_text)
        if not code_decision.allowed:
            return self._denied_response(request_id, "run_python", code_decision.reason or "python code denied", session.sandbox_id)
        timeout = policy.validate_timeout(request.get("timeout_seconds"))
        if not timeout.allowed:
            return self._denied_response(request_id, "run_python", timeout.reason or "timeout denied", session.sandbox_id)

        started = time.perf_counter()
        result = self._dispatch(
            self.cube_client,
            "cube_run_python",
            {
                "sandbox_id": session.sandbox_id,
                "code": code_text,
                "timeout_seconds": int(timeout.normalized_value),
            },
        )
        duration_ms = self._duration_ms(started)
        if self._is_success_result(result):
            self._mark_session_used(session.sandbox_id)
        warnings = self._audit(
            event_type="cube_run_python",
            request_id=request_id,
            sandbox_id=session.sandbox_id,
            status="success" if self._is_success_result(result) else "error",
            duration_ms=duration_ms,
            payload={
                "code_bytes": code_decision.normalized_value,
                "code_sha256": hashlib.sha256(code_text.encode("utf-8")).hexdigest(),
            },
            error=self._result_error(result),
        )
        return self._success_response(request_id, "run_python", result, warnings)

    def _handle_read_file(self, request_id: str, request: dict[str, Any]) -> dict[str, Any]:
        session = self._require_known_session(request)
        path = request.get("path")
        if not path:
            return self._denied_response(request_id, "read_file", "path is required", session.sandbox_id)
        decision = policy.validate_read_path(path)
        if not decision.allowed:
            return self._denied_response(request_id, "read_file", decision.reason or "read denied", session.sandbox_id)

        started = time.perf_counter()
        result = self._dispatch(
            self.cube_client,
            "cube_read_file",
            {"sandbox_id": session.sandbox_id, "path": decision.normalized_value},
        )
        duration_ms = self._duration_ms(started)
        if self._is_success_result(result):
            self._mark_session_used(session.sandbox_id)
        warnings = self._audit(
            event_type="cube_read_file",
            request_id=request_id,
            sandbox_id=session.sandbox_id,
            status="success" if self._is_success_result(result) else "error",
            duration_ms=duration_ms,
            payload={"path": decision.normalized_value},
            error=self._result_error(result),
        )
        return self._success_response(request_id, "read_file", result, warnings)

    def _handle_write_file(self, request_id: str, request: dict[str, Any]) -> dict[str, Any]:
        session = self._require_known_session(request)
        path = request.get("path", "")
        decision = policy.validate_write_path(path)
        if not decision.allowed:
            return self._denied_response(request_id, "write_file", decision.reason or "write denied", session.sandbox_id)
        content = request.get("content", "")
        content_decision = policy.validate_file_content(str(content))
        if not content_decision.allowed:
            return self._denied_response(request_id, "write_file", content_decision.reason or "content denied", session.sandbox_id)

        started = time.perf_counter()
        result = self._dispatch(
            self.cube_client,
            "cube_write_file",
            {
                "sandbox_id": session.sandbox_id,
                "path": decision.normalized_value,
                "content": str(content),
            },
        )
        duration_ms = self._duration_ms(started)
        if self._is_success_result(result):
            self._mark_session_used(session.sandbox_id)
        warnings = self._audit(
            event_type="cube_write_file",
            request_id=request_id,
            sandbox_id=session.sandbox_id,
            status="success" if self._is_success_result(result) else "error",
            duration_ms=duration_ms,
            payload={"path": decision.normalized_value, "bytes": content_decision.normalized_value},
            error=self._result_error(result),
        )
        return self._success_response(request_id, "write_file", result, warnings)

    def _handle_destroy(self, request_id: str, request: dict[str, Any]) -> dict[str, Any]:
        session = self._require_known_session(request)
        started = time.perf_counter()
        result = self._dispatch(
            self.cube_client,
            "cube_destroy",
            {"sandbox_id": session.sandbox_id},
        )
        duration_ms = self._duration_ms(started)
        if self._is_success_result(result):
            self.sessions.pop(session.sandbox_id, None)
        warnings = self._audit(
            event_type="cube_destroy",
            request_id=request_id,
            sandbox_id=session.sandbox_id,
            status="success" if self._is_success_result(result) else "error",
            duration_ms=duration_ms,
            payload={},
            error=self._result_error(result),
        )
        return self._success_response(request_id, "destroy", result, warnings)

    def _handle_destroy_all(self, request_id: str) -> dict[str, Any]:
        results: list[dict[str, Any]] = []
        for sandbox_id in list(self.sessions):
            child_request_id = f"{request_id}:{sandbox_id}"
            try:
                results.append(self._handle_destroy(child_request_id, {"sandbox_id": sandbox_id}))
            except Exception as exc:
                warnings = self._audit(
                    event_type="cube_destroy",
                    request_id=child_request_id,
                    sandbox_id=sandbox_id,
                    status="error",
                    payload={"cleanup": True},
                    error=str(exc),
                )
                results.append(
                    {
                        "ok": False,
                        "backend": "cube",
                        "request_id": child_request_id,
                        "operation": "destroy",
                        "sandbox_id": sandbox_id,
                        "error": str(exc),
                        "warnings": warnings,
                    }
                )
        return {
            "ok": all(result.get("ok") is not False for result in results),
            "backend": "cube",
            "request_id": request_id,
            "operation": "destroy_all",
            "results": results,
            "active_session_count": len(self.sessions),
            "warnings": [],
        }

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

    def _require_known_session(self, request: dict[str, Any]) -> CubeSession:
        sandbox_id = request.get("sandbox_id")
        if not sandbox_id:
            raise ValueError("sandbox_id is required")
        sandbox_key = str(sandbox_id)
        session = self.sessions.get(sandbox_key)
        if session is None:
            raise ValueError(f"unknown sandbox_id: {sandbox_key}")
        return session

    def _extract_sandbox_id(self, result: Any) -> str:
        if isinstance(result, dict):
            sandbox_id = result.get("sandbox_id")
            if sandbox_id:
                return str(sandbox_id)
        raise RuntimeError("cube_create did not return a sandbox_id")

    def _mark_session_used(self, sandbox_id: str) -> None:
        if sandbox_id in self.sessions:
            self.sessions[sandbox_id].last_used_at = _utc_now()

    def _audit(
        self,
        *,
        event_type: str,
        request_id: str,
        sandbox_id: str | None = None,
        status: str,
        duration_ms: int = 0,
        payload: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> list[str]:
        warnings_list: list[str] = []
        if not event_logger.log_event(
            event_type,
            request_id=request_id,
            sandbox_id=sandbox_id,
            status=status,
            duration_ms=duration_ms,
            payload=payload or {},
            error=error,
        ):
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
        truncated = bool(response.get("truncated", False))
        for key in ("stdout", "stderr", "content", "error"):
            if isinstance(response.get(key), str):
                response[key] = event_logger.redact_tool_output(response[key])
                response[key], was_truncated = policy.truncate_output(response[key])
                truncated = truncated or was_truncated
        response.update(
            {
                "backend": "cube",
                "request_id": request_id,
                "operation": op,
                "truncated": truncated,
                "warnings": warnings,
            }
        )
        return response

    def _denied_response(
        self,
        request_id: str,
        op: str,
        reason: str,
        sandbox_id: str | None = None,
    ) -> dict[str, Any]:
        warnings = self._audit(
            event_type=f"cube_{op}",
            request_id=request_id,
            sandbox_id=sandbox_id,
            status="denied",
            payload={"operation": op},
            error=reason,
        )
        return {
            "ok": False,
            "backend": "cube",
            "request_id": request_id,
            "operation": op,
            "error": event_logger.redact_tool_output(reason),
            "warnings": warnings,
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
            "error": event_logger.redact_tool_output(reason),
            "warnings": [],
        }

    def _is_success_result(self, result: Any) -> bool:
        return not isinstance(result, dict) or result.get("ok") is not False

    def _result_error(self, result: Any) -> str | None:
        if isinstance(result, dict):
            error = result.get("error")
            return str(error) if error else None
        return None

    def _duration_ms(self, started: float) -> int:
        return int((time.perf_counter() - started) * 1000)
