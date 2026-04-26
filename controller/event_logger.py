"""JSONL event logger for bridge and controller audit events."""

from __future__ import annotations

import datetime as _datetime
import json
import os
import re
import uuid
import warnings
from pathlib import Path
from typing import Any


class EventLogError(RuntimeError):
    """Raised when strict audit logging is enabled and a write fails."""


_SECRET_KEY_PARTS = (
    "api_key",
    "apikey",
    "token",
    "password",
    "passwd",
    "secret",
    "authorization",
    "bearer",
    "cookie",
    "session",
)
_TOKEN_VALUE_PATTERNS = (
    re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(r"(?i)\b(api[_-]?key|token|password|secret|authorization|cookie)\s*[:=]\s*[^ \t\r\n,;]+"),
    re.compile(r"\b(sk-[A-Za-z0-9_-]{12,})\b"),
    re.compile(r"\b(gh[pousr]_[A-Za-z0-9_]{12,})\b"),
)


def _log_path() -> Path:
    """Resolve the path to the JSONL log file."""
    fname = os.environ.get("CUBE_EVENT_LOG", "cube_events.jsonl")
    return Path(fname).expanduser().resolve()


def _strict_logging_enabled() -> bool:
    return os.environ.get("CUBE_STRICT_AUDIT_LOGGING", "").lower() in {"1", "true", "yes", "on"}


def output_redaction_disabled() -> bool:
    """Check if the user has explicitly disabled output redaction (unsafe)."""
    return os.environ.get("HERMY_UNSAFE_DISABLE_OUTPUT_REDACTION", "").lower() in {"1", "true", "yes", "on"}


def output_redaction_enabled() -> bool:
    """Output redaction is enabled by default for safety."""
    return not output_redaction_disabled()


def _is_secret_key(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in _SECRET_KEY_PARTS)


def redact_secret_text(text: str) -> str:
    """Redact simple token-like values from free-form tool output."""
    redacted = text
    redacted = _TOKEN_VALUE_PATTERNS[0].sub(r"\1 [REDACTED]", redacted)
    redacted = _TOKEN_VALUE_PATTERNS[1].sub(lambda match: match.group(1) + "=[REDACTED]", redacted)
    for pattern in _TOKEN_VALUE_PATTERNS[2:]:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def redact_secrets(value: Any, *, redact_values: bool = False) -> Any:
    """Recursively redact secret-like payload keys and, optionally, values."""
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            redacted[key] = "[REDACTED]" if _is_secret_key(str(key)) else redact_secrets(item, redact_values=redact_values)
        return redacted
    if isinstance(value, list):
        return [redact_secrets(item, redact_values=redact_values) for item in value]
    if isinstance(value, tuple):
        return [redact_secrets(item, redact_values=redact_values) for item in value]
    if redact_values and isinstance(value, str):
        return redact_secret_text(value)
    return value


def redact_tool_output(value: Any) -> Any:
    """Redact tool output unless HERMY_UNSAFE_DISABLE_OUTPUT_REDACTION is set."""
    if not output_redaction_enabled():
        return value
    return redact_secrets(value, redact_values=True)


def build_event(
    event_type: str,
    data: dict[str, Any] | None = None,
    *,
    request_id: str | None = None,
    sandbox_id: str | None = None,
    status: str = "success",
    duration_ms: int = 0,
    payload: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    """Build a normalized audit event.

    ``data`` is kept as a backward-compatible alias for ``payload``.
    Top-level request and sandbox IDs are inferred from the payload when
    explicit values are not provided.
    """
    raw_payload = payload if payload is not None else (data or {})
    request_id = request_id or raw_payload.get("request_id")
    sandbox_id = sandbox_id or raw_payload.get("sandbox_id")
    redact_values = output_redaction_enabled()
    return {
        "event_id": uuid.uuid4().hex,
        "timestamp": _datetime.datetime.now(tz=_datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
        "event_type": event_type,
        "request_id": request_id,
        "sandbox_id": sandbox_id,
        "status": status,
        "duration_ms": int(duration_ms),
        "payload": redact_secrets(raw_payload, redact_values=redact_values),
        "error": redact_secret_text(error) if redact_values and isinstance(error, str) else error,
    }


def log_event(
    event_type: str,
    data: dict[str, Any] | None = None,
    *,
    request_id: str | None = None,
    sandbox_id: str | None = None,
    status: str = "success",
    duration_ms: int = 0,
    payload: dict[str, Any] | None = None,
    error: str | None = None,
    strict: bool | None = None,
) -> bool:
    """Append an event to the log file.

    Returns ``True`` on success. When logging fails it emits a warning;
    with strict mode enabled it also raises ``EventLogError``.
    """
    entry = build_event(
        event_type,
        data,
        request_id=request_id,
        sandbox_id=sandbox_id,
        status=status,
        duration_ms=duration_ms,
        payload=payload,
        error=error,
    )
    path = _log_path()
    should_raise = _strict_logging_enabled() if strict is None else strict

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            json.dump(entry, handle, ensure_ascii=False)
            handle.write("\n")
    except Exception as exc:  # pragma: no cover - branch tested via warning/raise behavior
        message = f"failed to write audit log to {path}: {exc}"
        warnings.warn(message, RuntimeWarning, stacklevel=2)
        if should_raise:
            raise EventLogError(message) from exc
        return False

    return True


__all__ = [
    "EventLogError",
    "build_event",
    "log_event",
    "output_redaction_disabled",
    "output_redaction_enabled",
    "redact_secret_text",
    "redact_secrets",
    "redact_tool_output",
]
