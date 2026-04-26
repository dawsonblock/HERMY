"""Tests for audit log behavior."""

from __future__ import annotations

import json
import warnings

import pytest

from controller import event_logger


def test_event_logger_writes_jsonl(tmp_path, monkeypatch):
    log_path = tmp_path / "events.jsonl"
    monkeypatch.setenv("CUBE_EVENT_LOG", str(log_path))

    assert event_logger.log_event("cube_command", {"sandbox_id": "sbx-1"})

    payload = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert payload["event_type"] == "cube_command"
    assert payload["data"]["sandbox_id"] == "sbx-1"


def test_event_logger_warns_when_write_fails(tmp_path, monkeypatch):
    blocked_dir = tmp_path / "blocked"
    blocked_dir.write_text("not a directory", encoding="utf-8")
    log_path = blocked_dir / "events.jsonl"
    monkeypatch.setenv("CUBE_EVENT_LOG", str(log_path))

    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        assert not event_logger.log_event("cube_command", {"sandbox_id": "sbx-1"})

    assert recorded
    assert "failed to write audit log" in str(recorded[0].message)


def test_event_logger_can_fail_closed(tmp_path, monkeypatch):
    blocked_dir = tmp_path / "blocked"
    blocked_dir.write_text("not a directory", encoding="utf-8")
    monkeypatch.setenv("CUBE_EVENT_LOG", str(blocked_dir / "events.jsonl"))

    with pytest.raises(event_logger.EventLogError):
        event_logger.log_event("cube_command", {"sandbox_id": "sbx-1"}, strict=True)
