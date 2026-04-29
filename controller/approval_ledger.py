"""Approval ledger for HERMY command approvals.

Provides durable, single-use command approvals with replay attack prevention.

Environment:
    HERMY_APPROVAL_LEDGER_FILE: Path to JSONL ledger file. If not set or "none",
        returns None from get_default_ledger(), preserving string-existence-only
        behavior for backward compatibility.

Ledger entries (JSONL format):
    {"id": "uuid", "action": "command", "actor": "user", "created_at": "ISO",
     "expires_at": "ISO", "consumed": false}

Security:
    - Approvals are single-use (consumed on first use)
    - Approvals expire after configurable duration
    - Approvals are bound to specific commands (action matching)
    - Ledger is durable across restarts
    - Destructive commands remain blocked even with valid approval_id
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOG = logging.getLogger(__name__)


def _utc_now() -> str:
    """Return current UTC timestamp in ISO format."""
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


class ApprovalLedger:
    """Abstract base class for approval ledgers."""

    def record(
        self,
        approval_id: str,
        action: str,
        actor: str | None = None,
        expires_at: str | None = None,
    ) -> None:
        """Record a new approval entry.

        Args:
            approval_id: Unique identifier for this approval (UUID recommended)
            action: The command or action being approved
            actor: Optional identifier of who requested approval
            expires_at: Optional ISO timestamp when approval expires
        """
        raise NotImplementedError

    def is_valid(self, approval_id: str, action: str | None = None) -> bool:
        """Return True if the approval_id is valid for the given action.

        Checks:
            - Approval exists in ledger
            - Not already consumed
            - Not expired
            - Action matches (if action parameter provided)
        """
        raise NotImplementedError

    def consume(self, approval_id: str) -> None:
        """Mark an approval as consumed so it cannot be replayed."""
        raise NotImplementedError


class FileApprovalLedger(ApprovalLedger):
    """File-based durable approval ledger using JSONL format.

    Uses atomic file operations (write to temp + rename) for durability.
    Thread-safe with file locking.
    """

    def __init__(self, file_path: Path) -> None:
        self._file = Path(file_path)
        self._lock = threading.Lock()
        # Ensure parent directory exists
        self._file.parent.mkdir(parents=True, exist_ok=True)

    def _load_entries(self) -> dict[str, dict[str, Any]]:
        """Load all ledger entries into memory.

        Returns dict mapping approval_id -> entry.
        """
        entries: dict[str, dict[str, Any]] = {}
        if not self._file.exists():
            return entries

        try:
            with open(self._file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        if "id" in entry:
                            entries[entry["id"]] = entry
                    except json.JSONDecodeError:
                        _LOG.warning("Skipping malformed ledger entry: %s", line)
        except Exception as exc:
            _LOG.error("Could not load ledger from %s: %s", self._file, exc)
            # Fail closed: return empty dict on load error
            return {}

        return entries

    def _save_entries(self, entries: dict[str, dict[str, Any]]) -> None:
        """Save all entries to file atomically."""
        tmp_file = self._file.with_suffix(".tmp")
        try:
            with open(tmp_file, "w", encoding="utf-8") as f:
                for entry in entries.values():
                    f.write(json.dumps(entry, separators=(",", ":")) + "\n")
            # Atomic rename
            os.replace(tmp_file, self._file)
        except Exception as exc:
            _LOG.error("Could not save ledger to %s: %s", self._file, exc)
            raise

    def record(
        self,
        approval_id: str,
        action: str,
        actor: str | None = None,
        expires_at: str | None = None,
    ) -> None:
        """Record a new approval entry."""
        with self._lock:
            entries = self._load_entries()

            if approval_id in entries:
                raise ValueError(f"approval_id {approval_id} already exists")

            entry = {
                "id": approval_id,
                "action": action,
                "actor": actor or "unknown",
                "created_at": _utc_now(),
                "expires_at": expires_at,
                "consumed": False,
            }
            entries[approval_id] = entry
            self._save_entries(entries)
            _LOG.info("Recorded approval %s for action %s", approval_id, action)

    def is_valid(self, approval_id: str, action: str | None = None) -> bool:
        """Return True if the approval_id is valid for the given action."""
        with self._lock:
            entries = self._load_entries()
            entry = entries.get(approval_id)

            if entry is None:
                _LOG.debug("Approval %s not found", approval_id)
                return False

            if entry.get("consumed", False):
                _LOG.debug("Approval %s already consumed", approval_id)
                return False

            # Check expiry
            expires_at = entry.get("expires_at")
            if expires_at:
                try:
                    exp_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                    if datetime.now(tz=timezone.utc) > exp_dt:
                        _LOG.debug("Approval %s expired", approval_id)
                        return False
                except ValueError:
                    _LOG.warning("Invalid expiry format for approval %s", approval_id)
                    return False

            # Check action match
            if action is not None and entry.get("action") != action:
                _LOG.debug(
                    "Approval %s action mismatch: expected %s, got %s",
                    approval_id, action, entry.get("action"),
                )
                return False

            return True

    def consume(self, approval_id: str) -> None:
        """Mark an approval as consumed so it cannot be replayed."""
        with self._lock:
            entries = self._load_entries()
            entry = entries.get(approval_id)

            if entry is None:
                raise ValueError(f"approval_id {approval_id} not found")

            if entry.get("consumed", False):
                raise ValueError(f"approval_id {approval_id} already consumed")

            entry["consumed"] = True
            entry["consumed_at"] = _utc_now()
            self._save_entries(entries)
            _LOG.info("Consumed approval %s", approval_id)


def get_default_ledger() -> ApprovalLedger | None:
    """Return the configured approval ledger, or None for no-op mode.

    Returns None when HERMY_APPROVAL_LEDGER_FILE is not set or "none",
    preserving backward compatibility where approval_id proves only
    string existence.

    Returns FileApprovalLedger when HERMY_APPROVAL_LEDGER_FILE is set
    to a valid file path.
    """
    file_path = os.environ.get("HERMY_APPROVAL_LEDGER_FILE")
    if not file_path or file_path.lower() in ("none", "", "null"):
        return None
    return FileApprovalLedger(Path(file_path))
