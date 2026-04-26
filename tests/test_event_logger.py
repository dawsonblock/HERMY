"""Tests for audit log behavior."""

from __future__ import annotations

import json
import warnings

import pytest

from controller import event_logger


def test_event_logger_writes_new_jsonl_shape(tmp_path, monkeypatch):
    log_path = tmp_path / "events.jsonl"
    monkeypatch.setenv("CUBE_EVENT_LOG", str(log_path))

    assert event_logger.log_event(
        "cube_command",
        request_id="req-1",
        sandbox_id="sbx-1",
        status="success",
        duration_ms=12,
        payload={"command": "echo ok"},
    )

    payload = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert payload["event_id"]
    assert payload["event_type"] == "cube_command"
    assert payload["request_id"] == "req-1"
    assert payload["sandbox_id"] == "sbx-1"
    assert payload["status"] == "success"
    assert payload["duration_ms"] == 12
    assert payload["payload"] == {"command": "echo ok"}
    assert payload["error"] is None


def test_event_logger_infers_top_level_ids_from_payload(tmp_path, monkeypatch):
    log_path = tmp_path / "events.jsonl"
    monkeypatch.setenv("CUBE_EVENT_LOG", str(log_path))

    event_logger.log_event("cube_command", {"request_id": "req-1", "sandbox_id": "sbx-1"})

    payload = json.loads(log_path.read_text(encoding="utf-8").strip())
    assert payload["request_id"] == "req-1"
    assert payload["sandbox_id"] == "sbx-1"


def test_event_logger_redacts_nested_secret_payload(tmp_path, monkeypatch):
    log_path = tmp_path / "events.jsonl"
    monkeypatch.setenv("CUBE_EVENT_LOG", str(log_path))

    event_logger.log_event(
        "cube_create",
        payload={
            "api_key": "raw-api-key",
            "nested": {
                "token": "raw-token",
                "password": "raw-password",
                "headers": [{"authorization": "Bearer raw"}, {"cookie": "raw-cookie"}],
            },
        },
    )

    text = log_path.read_text(encoding="utf-8")
    assert "raw-api-key" not in text
    assert "raw-token" not in text
    assert "raw-password" not in text
    assert "Bearer raw" not in text
    assert "raw-cookie" not in text
    payload = json.loads(text)
    assert payload["payload"]["api_key"] == "[REDACTED]"
    assert payload["payload"]["nested"]["token"] == "[REDACTED]"
    assert payload["payload"]["nested"]["headers"][0]["authorization"] == "[REDACTED]"


def test_event_logger_redacts_output_values_when_enabled(tmp_path, monkeypatch):
    log_path = tmp_path / "events.jsonl"
    monkeypatch.setenv("CUBE_EVENT_LOG", str(log_path))
    monkeypatch.setenv("HERMY_REDACT_TOOL_OUTPUT", "1")

    event_logger.log_event(
        "cube_run_command",
        payload={"stdout": "token=raw-token-value", "stderr": "Authorization: Bearer rawbearertoken"},
        error="password=raw-password-value",
    )

    text = log_path.read_text(encoding="utf-8")
    assert "raw-token-value" not in text
    assert "rawbearertoken" not in text
    assert "raw-password-value" not in text
    payload = json.loads(text)
    assert "token=[REDACTED]" in payload["payload"]["stdout"]
    assert "password=[REDACTED]" in payload["error"]


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
