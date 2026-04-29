"""Tests for approval ledger implementation.

Validates FileApprovalLedger record/is_valid/consume flow with replay
prevention, expiry checking, and atomic file operations.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add repo root to path
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest

from controller.approval_ledger import (
    FileApprovalLedger,
    get_default_ledger,
    _utc_now,
)


class TestFileApprovalLedger:
    """Test FileApprovalLedger functionality."""

    def setup_method(self) -> None:
        """Create a temporary directory for each test."""
        self.tmp_dir = tempfile.mkdtemp()
        self.ledger_file = Path(self.tmp_dir) / "approvals.jsonl"
        self.ledger = FileApprovalLedger(self.ledger_file)

    def teardown_method(self) -> None:
        """Clean up temporary files."""
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_record_creates_entry(self) -> None:
        """Recording an approval creates a valid entry."""
        approval_id = str(uuid.uuid4())
        action = "ls -la"
        actor = "test-user"

        self.ledger.record(approval_id, action, actor)

        # Verify file was created
        assert self.ledger_file.exists()
        # Verify entry is valid
        assert self.ledger.is_valid(approval_id, action)

    def test_is_valid_checks_action_match(self) -> None:
        """is_valid returns False if action doesn't match."""
        approval_id = str(uuid.uuid4())
        recorded_action = "ls -la"
        different_action = "cat /etc/passwd"

        self.ledger.record(approval_id, recorded_action)

        # Should be valid for correct action
        assert self.ledger.is_valid(approval_id, recorded_action)
        # Should be invalid for different action
        assert not self.ledger.is_valid(approval_id, different_action)
        # Should be valid when action not specified
        assert self.ledger.is_valid(approval_id)

    def test_is_valid_checks_nonexistent(self) -> None:
        """is_valid returns False for non-existent approval."""
        fake_id = str(uuid.uuid4())
        assert not self.ledger.is_valid(fake_id, "any-action")

    def test_consume_prevents_replay(self) -> None:
        """Consumed approval cannot be reused."""
        approval_id = str(uuid.uuid4())
        action = "ls -la"

        self.ledger.record(approval_id, action)

        # Initially valid
        assert self.ledger.is_valid(approval_id, action)

        # Consume it
        self.ledger.consume(approval_id)

        # No longer valid (single-use)
        assert not self.ledger.is_valid(approval_id, action)

    def test_consume_raises_on_nonexistent(self) -> None:
        """Consuming non-existent approval raises ValueError."""
        fake_id = str(uuid.uuid4())
        with pytest.raises(ValueError, match="not found"):
            self.ledger.consume(fake_id)

    def test_consume_raises_on_already_consumed(self) -> None:
        """Double-consuming raises ValueError."""
        approval_id = str(uuid.uuid4())
        action = "ls -la"

        self.ledger.record(approval_id, action)
        self.ledger.consume(approval_id)

        with pytest.raises(ValueError, match="already consumed"):
            self.ledger.consume(approval_id)

    def test_is_valid_checks_expiry(self) -> None:
        """Expired approvals are rejected."""
        approval_id = str(uuid.uuid4())
        action = "ls -la"

        # Create an expired timestamp (1 hour ago)
        expired_at = (datetime.now(tz=timezone.utc) - timedelta(hours=1)).isoformat()

        self.ledger.record(approval_id, action, expires_at=expired_at)

        # Should be invalid (expired)
        assert not self.ledger.is_valid(approval_id, action)

    def test_is_valid_accepts_non_expired(self) -> None:
        """Non-expired approvals are valid."""
        approval_id = str(uuid.uuid4())
        action = "ls -la"

        # Create a future expiry (1 hour from now)
        future = (datetime.now(tz=timezone.utc) + timedelta(hours=1)).isoformat()

        self.ledger.record(approval_id, action, expires_at=future)

        # Should be valid (not expired)
        assert self.ledger.is_valid(approval_id, action)

    def test_record_raises_on_duplicate(self) -> None:
        """Recording duplicate approval_id raises ValueError."""
        approval_id = str(uuid.uuid4())
        action = "ls -la"

        self.ledger.record(approval_id, action)

        with pytest.raises(ValueError, match="already exists"):
            self.ledger.record(approval_id, "different-action")

    def test_file_format_is_jsonl(self) -> None:
        """Ledger file is valid JSONL format."""
        approval_id = str(uuid.uuid4())
        action = "ls -la"
        actor = "test-user"

        self.ledger.record(approval_id, action, actor)

        # Read and verify file format
        lines = self.ledger_file.read_text().strip().split("\n")
        assert len(lines) == 1

        entry = json.loads(lines[0])
        assert entry["id"] == approval_id
        assert entry["action"] == action
        assert entry["actor"] == actor
        assert entry["consumed"] is False
        assert "created_at" in entry

    def test_file_is_durable_across_instances(self) -> None:
        """Ledger persists across FileApprovalLedger instances."""
        approval_id = str(uuid.uuid4())
        action = "ls -la"

        # Record with first instance
        self.ledger.record(approval_id, action)

        # Create new instance pointing to same file
        ledger2 = FileApprovalLedger(self.ledger_file)

        # Should see the same entry
        assert ledger2.is_valid(approval_id, action)

    def test_consumed_flag_in_file(self) -> None:
        """Consumed status is persisted to file."""
        approval_id = str(uuid.uuid4())
        action = "ls -la"

        self.ledger.record(approval_id, action)
        self.ledger.consume(approval_id)

        # Create new instance
        ledger2 = FileApprovalLedger(self.ledger_file)

        # Should see consumed status
        assert not ledger2.is_valid(approval_id, action)

    def test_consumed_at_timestamp(self) -> None:
        """Consume adds consumed_at timestamp."""
        approval_id = str(uuid.uuid4())
        action = "ls -la"

        self.ledger.record(approval_id, action)
        self.ledger.consume(approval_id)

        # Read file and verify consumed_at
        lines = self.ledger_file.read_text().strip().split("\n")
        entry = json.loads(lines[0])
        assert entry["consumed"] is True
        assert "consumed_at" in entry

    def test_thread_safety(self) -> None:
        """Concurrent operations don't corrupt the ledger."""
        errors = []
        approvals = [(str(uuid.uuid4()), f"cmd-{i}") for i in range(10)]

        def record_approval(approval_id: str, action: str) -> None:
            try:
                self.ledger.record(approval_id, action)
            except Exception as exc:
                errors.append(exc)

        # Spawn threads to record concurrently
        threads = [
            threading.Thread(target=record_approval, args=(aid, act))
            for aid, act in approvals
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # No errors
        assert not errors

        # All approvals should be valid
        for aid, act in approvals:
            assert self.ledger.is_valid(aid, act)

    def test_invalid_expiry_format(self) -> None:
        """Invalid expiry format is treated as expired."""
        approval_id = str(uuid.uuid4())
        action = "ls -la"

        # Record with invalid expiry format
        self.ledger.record(approval_id, action, expires_at="not-a-valid-timestamp")

        # Should be invalid due to parse error
        assert not self.ledger.is_valid(approval_id, action)


class TestGetDefaultLedger:
    """Test get_default_ledger() function."""

    def test_returns_none_when_env_not_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns None when HERMY_APPROVAL_LEDGER_FILE not set."""
        monkeypatch.delenv("HERMY_APPROVAL_LEDGER_FILE", raising=False)
        assert get_default_ledger() is None

    def test_returns_none_for_empty_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns None for empty string."""
        monkeypatch.setenv("HERMY_APPROVAL_LEDGER_FILE", "")
        assert get_default_ledger() is None

    def test_returns_none_for_none_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Returns None for 'none' string (case insensitive)."""
        monkeypatch.setenv("HERMY_APPROVAL_LEDGER_FILE", "NONE")
        assert get_default_ledger() is None

    def test_returns_ledger_for_valid_path(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Returns FileApprovalLedger for valid path."""
        ledger_file = tmp_path / "approvals.jsonl"
        monkeypatch.setenv("HERMY_APPROVAL_LEDGER_FILE", str(ledger_file))

        ledger = get_default_ledger()
        assert ledger is not None
        assert isinstance(ledger, FileApprovalLedger)

    def test_creates_parent_directory(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Creates parent directories if needed."""
        ledger_file = tmp_path / "subdir" / "approvals.jsonl"
        monkeypatch.setenv("HERMY_APPROVAL_LEDGER_FILE", str(ledger_file))

        get_default_ledger()

        assert ledger_file.parent.exists()


class TestIntegrationWithPolicy:
    """Integration tests with policy.validate_command()."""

    def setup_method(self) -> None:
        """Create a temporary directory for each test."""
        self.tmp_dir = tempfile.mkdtemp()
        self.ledger_file = Path(self.tmp_dir) / "approvals.jsonl"
        os.environ["HERMY_APPROVAL_LEDGER_FILE"] = str(self.ledger_file)

    def teardown_method(self) -> None:
        """Clean up."""
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)
        os.environ.pop("HERMY_APPROVAL_LEDGER_FILE", None)

    def test_control_operator_with_ledger(self) -> None:
        """Control operator commands work with ledger approval."""
        from controller.policy import validate_command

        approval_id = str(uuid.uuid4())
        command = "ls | grep foo"

        # Record approval for this command
        ledger = FileApprovalLedger(self.ledger_file)
        ledger.record(approval_id, command)

        # Should be allowed with approval
        decision = validate_command(command, approved=True, approval_id=approval_id)
        assert decision.allowed

    def test_control_operator_replay_blocked(self) -> None:
        """Replay attack blocked by ledger consume."""
        from controller.policy import validate_command

        approval_id = str(uuid.uuid4())
        command = "ls | grep foo"

        # Record approval
        ledger = FileApprovalLedger(self.ledger_file)
        ledger.record(approval_id, command)

        # First use succeeds
        decision1 = validate_command(command, approved=True, approval_id=approval_id)
        assert decision1.allowed

        # Second use (replay) fails - approval was consumed
        decision2 = validate_command(command, approved=True, approval_id=approval_id)
        assert not decision2.allowed
        assert "already used" in decision2.reason.lower() or "invalid" in decision2.reason.lower()

    def test_control_operator_wrong_action(self) -> None:
        """Approval for different command is rejected."""
        from controller.policy import validate_command

        approval_id = str(uuid.uuid4())
        approved_command = "ls -la | grep foo"  # Has control operator
        actual_command = "cat /etc/passwd | grep root"  # Different command with control operator

        # Record approval for different command
        ledger = FileApprovalLedger(self.ledger_file)
        ledger.record(approval_id, approved_command)

        # Try to use for different command
        decision = validate_command(actual_command, approved=True, approval_id=approval_id)
        assert not decision.allowed
        assert "invalid" in decision.reason.lower() or "expired" in decision.reason.lower()

    def test_without_ledger_backward_compatible(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Without ledger, approval_id proves only string existence."""
        from controller.policy import validate_command

        monkeypatch.delenv("HERMY_APPROVAL_LEDGER_FILE", raising=False)

        command = "ls | grep foo"
        approval_id = "any-string-works"

        # Should be allowed with any non-empty approval_id
        decision = validate_command(command, approved=True, approval_id=approval_id)
        assert decision.allowed


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
