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


def test_event_logger_redacts_output_values_by_default(tmp_path, monkeypatch):
    """By default, token-like values in free-form strings are redacted."""
    log_path = tmp_path / "events.jsonl"
    monkeypatch.setenv("CUBE_EVENT_LOG", str(log_path))
    # No HERMY_UNSAFE_DISABLE_OUTPUT_REDACTION set - should redact by default

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


def test_event_logger_redacts_bearer_tokens_by_default(tmp_path, monkeypatch):
    """Bearer tokens are redacted in audit logs by default."""
    log_path = tmp_path / "events.jsonl"
    monkeypatch.setenv("CUBE_EVENT_LOG", str(log_path))

    event_logger.log_event(
        "cube_run_command",
        payload={"stdout": "Authorization: Bearer sk-test-secret"},
    )

    text = log_path.read_text(encoding="utf-8")
    assert "sk-test-secret" not in text
    payload = json.loads(text)
    # Redaction pattern converts "Authorization: Bearer ..." to "Authorization=[REDACTED] [REDACTED]"
    assert "[REDACTED]" in payload["payload"]["stdout"]


def test_event_logger_redacts_api_keys_by_default(tmp_path, monkeypatch):
    """API keys are redacted in audit logs by default."""
    log_path = tmp_path / "events.jsonl"
    monkeypatch.setenv("CUBE_EVENT_LOG", str(log_path))

    event_logger.log_event(
        "cube_run_command",
        payload={"stderr": "api_key=sk-abc123abc123abc123"},
    )

    text = log_path.read_text(encoding="utf-8")
    assert "sk-abc123abc123abc123" not in text


def test_event_logger_redacts_passwords_by_default(tmp_path, monkeypatch):
    """Passwords are redacted in audit logs by default."""
    log_path = tmp_path / "events.jsonl"
    monkeypatch.setenv("CUBE_EVENT_LOG", str(log_path))

    event_logger.log_event(
        "cube_run_command",
        error="password=secret-password",
    )

    text = log_path.read_text(encoding="utf-8")
    assert "secret-password" not in text


def test_event_logger_unsafe_opt_out_allows_raw_secrets(tmp_path, monkeypatch):
    """When HERMY_UNSAFE_DISABLE_OUTPUT_REDACTION=1, raw secrets may appear (unsafe)."""
    log_path = tmp_path / "events.jsonl"
    monkeypatch.setenv("CUBE_EVENT_LOG", str(log_path))
    monkeypatch.setenv("HERMY_UNSAFE_DISABLE_OUTPUT_REDACTION", "1")

    event_logger.log_event(
        "cube_run_command",
        payload={"stdout": "token=raw-token-value"},
    )

    text = log_path.read_text(encoding="utf-8")
    # In unsafe mode, raw secrets may appear
    assert "raw-token-value" in text


def test_event_logger_secret_keys_always_redacted_even_when_unsafe(tmp_path, monkeypatch):
    """Secret-like dictionary keys are always redacted regardless of unsafe opt-out."""
    log_path = tmp_path / "events.jsonl"
    monkeypatch.setenv("CUBE_EVENT_LOG", str(log_path))
    monkeypatch.setenv("HERMY_UNSAFE_DISABLE_OUTPUT_REDACTION", "1")

    event_logger.log_event(
        "cube_run_command",
        payload={"api_key": "raw-secret", "nested": {"password": "raw-pass"}},
    )

    text = log_path.read_text(encoding="utf-8")
    # Keys should still be redacted even in unsafe mode
    assert "[REDACTED]" in text
    # But structured data shows keys were redacted
    payload = json.loads(text)
    assert payload["payload"]["api_key"] == "[REDACTED]"
    assert payload["payload"]["nested"]["password"] == "[REDACTED]"


def test_event_logger_new_secret_keys_redacted_by_default(tmp_path, monkeypatch):
    """New secret keys (apikey, passwd, bearer, session) are redacted by default."""
    log_path = tmp_path / "events.jsonl"
    monkeypatch.setenv("CUBE_EVENT_LOG", str(log_path))

    event_logger.log_event(
        "cube_run_command",
        payload={
            "apikey": "raw-apikey",
            "passwd": "raw-passwd",
            "bearer": "raw-bearer",
            "session": "raw-session",
        },
    )

    text = log_path.read_text(encoding="utf-8")
    assert "raw-apikey" not in text
    assert "raw-passwd" not in text
    assert "raw-bearer" not in text
    assert "raw-session" not in text
    payload = json.loads(text)
    assert payload["payload"]["apikey"] == "[REDACTED]"
    assert payload["payload"]["passwd"] == "[REDACTED]"
    assert payload["payload"]["bearer"] == "[REDACTED]"
    assert payload["payload"]["session"] == "[REDACTED]"


def test_event_logger_new_secret_keys_redacted_even_when_unsafe(tmp_path, monkeypatch):
    """New secret keys remain redacted even with HERMY_UNSAFE_DISABLE_OUTPUT_REDACTION=1."""
    log_path = tmp_path / "events.jsonl"
    monkeypatch.setenv("CUBE_EVENT_LOG", str(log_path))
    monkeypatch.setenv("HERMY_UNSAFE_DISABLE_OUTPUT_REDACTION", "1")

    event_logger.log_event(
        "cube_run_command",
        payload={
            "apikey": "raw-apikey",
            "passwd": "raw-passwd",
            "bearer": "raw-bearer",
            "session": "raw-session",
        },
    )

    text = log_path.read_text(encoding="utf-8")
    # These keys should still be redacted even in unsafe mode
    assert "raw-apikey" not in text
    assert "raw-passwd" not in text
    assert "raw-bearer" not in text
    assert "raw-session" not in text
    payload = json.loads(text)
    assert payload["payload"]["apikey"] == "[REDACTED]"
    assert payload["payload"]["passwd"] == "[REDACTED]"
    assert payload["payload"]["bearer"] == "[REDACTED]"
    assert payload["payload"]["session"] == "[REDACTED]"


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
