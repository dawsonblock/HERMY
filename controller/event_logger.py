"""JSONL event logger for bridge and controller audit events."""

from __future__ import annotations

import datetime as _datetime
import json
import os
import warnings
from pathlib import Path
from typing import Any


class EventLogError(RuntimeError):
    """Raised when strict audit logging is enabled and a write fails."""


def _log_path() -> Path:
    """Resolve the path to the JSONL log file."""
    fname = os.environ.get("CUBE_EVENT_LOG", "cube_events.jsonl")
    return Path(fname).expanduser().resolve()


def _strict_logging_enabled() -> bool:
    return os.environ.get("CUBE_STRICT_AUDIT_LOGGING", "").lower() in {"1", "true", "yes", "on"}


def log_event(
    event_type: str,
    data: dict[str, Any] | None = None,
    *,
    strict: bool | None = None,
) -> bool:
    """Append an event to the log file.

    Returns ``True`` on success. When logging fails it emits a warning;
    with strict mode enabled it also raises ``EventLogError``.
    """
    entry = {
        "timestamp": _datetime.datetime.now(tz=_datetime.timezone.utc).isoformat().replace("+00:00", "Z"),
        "event_type": event_type,
        "data": data or {},
    }
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


__all__ = ["EventLogError", "log_event"]
