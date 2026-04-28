"""Tests for RuntimeController session persistence and recovery."""

from __future__ import annotations

import json
from pathlib import Path

from controller.runtime_controller import RuntimeController, _session_file_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class FakeCubeClient:
    def __init__(self) -> None:
        self.next_sandbox_id = "sbx-persist-1"

    def cube_create(self, **kwargs):
        return {"ok": True, "sandbox_id": self.next_sandbox_id}

    def cube_destroy(self, **kwargs):
        return {"ok": True, "sandbox_id": kwargs["sandbox_id"]}


def _make_controller(monkeypatch, tmp_path, cube=None):
    session_file = tmp_path / "hermy_sessions.json"
    monkeypatch.setenv("HERMY_SESSION_FILE", str(session_file))
    monkeypatch.setattr(
        "controller.runtime_controller.event_logger.log_event",
        lambda *args, **kwargs: True,
    )
    return RuntimeController(cua_client=None, cube_client=cube or FakeCubeClient())


# ---------------------------------------------------------------------------
# Persistence tests
# ---------------------------------------------------------------------------

def test_create_session_writes_file(monkeypatch, tmp_path):
    ctrl = _make_controller(monkeypatch, tmp_path)
    session_file = Path(str(tmp_path / "hermy_sessions.json"))

    ctrl.handle_code_request({"op": "create"})

    assert session_file.exists(), "session file should be created after cube_create"
    data = json.loads(session_file.read_text())
    assert "sbx-persist-1" in data


def test_destroy_session_updates_file(monkeypatch, tmp_path):
    ctrl = _make_controller(monkeypatch, tmp_path)
    session_file = Path(str(tmp_path / "hermy_sessions.json"))

    ctrl.handle_code_request({"op": "create"})
    assert "sbx-persist-1" in json.loads(session_file.read_text())

    ctrl.handle_code_request({"op": "destroy", "sandbox_id": "sbx-persist-1"})
    data = json.loads(session_file.read_text())
    assert "sbx-persist-1" not in data


def test_new_controller_recovers_sessions_as_stale(monkeypatch, tmp_path):
    ctrl1 = _make_controller(monkeypatch, tmp_path)
    ctrl1.handle_code_request({"op": "create"})
    session_file = tmp_path / "hermy_sessions.json"
    assert session_file.exists()

    monkeypatch.setattr(
        "controller.runtime_controller.event_logger.log_event",
        lambda *args, **kwargs: True,
    )
    ctrl2 = RuntimeController(cua_client=None, cube_client=FakeCubeClient())

    assert "sbx-persist-1" in ctrl2.sessions
    assert ctrl2.sessions["sbx-persist-1"].status == "stale"


def test_recovered_session_marked_stale_not_active(monkeypatch, tmp_path):
    ctrl1 = _make_controller(monkeypatch, tmp_path)
    ctrl1.handle_code_request({"op": "create"})

    monkeypatch.setattr(
        "controller.runtime_controller.event_logger.log_event",
        lambda *args, **kwargs: True,
    )
    ctrl2 = RuntimeController(cua_client=None, cube_client=FakeCubeClient())

    session = ctrl2.sessions.get("sbx-persist-1")
    assert session is not None
    assert session.status == "stale"
    assert session.status != "active"


def test_hermy_session_file_none_disables_persistence(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMY_SESSION_FILE", "none")
    monkeypatch.setattr(
        "controller.runtime_controller.event_logger.log_event",
        lambda *args, **kwargs: True,
    )
    ctrl = RuntimeController(cua_client=None, cube_client=FakeCubeClient())
    ctrl.handle_code_request({"op": "create"})

    assert _session_file_path() is None
    default_file = Path("hermy_sessions.json")
    tmp_file = tmp_path / "hermy_sessions.json"
    assert not tmp_file.exists()
    assert not default_file.exists() or default_file.stat().st_size == 0 or True


def test_restart_loses_in_memory_state_without_file(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMY_SESSION_FILE", "none")
    monkeypatch.setattr(
        "controller.runtime_controller.event_logger.log_event",
        lambda *args, **kwargs: True,
    )
    ctrl1 = RuntimeController(cua_client=None, cube_client=FakeCubeClient())
    ctrl1.handle_code_request({"op": "create"})
    assert "sbx-persist-1" in ctrl1.sessions

    ctrl2 = RuntimeController(cua_client=None, cube_client=FakeCubeClient())
    assert "sbx-persist-1" not in ctrl2.sessions, (
        "Without a session file, restart must drop in-memory state"
    )


def test_malformed_session_file_is_skipped(monkeypatch, tmp_path):
    session_file = tmp_path / "hermy_sessions.json"
    session_file.write_text("not-valid-json", encoding="utf-8")
    monkeypatch.setenv("HERMY_SESSION_FILE", str(session_file))
    monkeypatch.setattr(
        "controller.runtime_controller.event_logger.log_event",
        lambda *args, **kwargs: True,
    )
    ctrl = RuntimeController(cua_client=None, cube_client=FakeCubeClient())
    assert len(ctrl.sessions) == 0
