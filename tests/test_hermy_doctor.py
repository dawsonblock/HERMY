"""Tests for the standalone doctor script."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCTOR_PATH = ROOT / "scripts" / "hermy_doctor.py"


def _load_doctor():
    spec = importlib.util.spec_from_file_location("hermy_doctor", DOCTOR_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_doctor_can_skip_env_for_source_checks(monkeypatch, capsys):
    doctor = _load_doctor()
    monkeypatch.setattr(doctor, "REQUIRED_PYTHON", (0, 0))
    monkeypatch.setattr(doctor, "REQUIRED_IMPORTS", ())
    monkeypatch.setattr(doctor, "_check_bridge_tools", lambda: doctor._result("PASS", "bridge:tools", "ok"))

    exit_code = doctor.main(["--skip-env"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "PASS python" in captured.out
    assert "WARN live:cua_mcp" in captured.out


def test_doctor_fails_when_required_env_is_missing(monkeypatch):
    doctor = _load_doctor()
    monkeypatch.setattr(doctor, "REQUIRED_PYTHON", (0, 0))
    monkeypatch.setattr(doctor, "REQUIRED_IMPORTS", ())
    monkeypatch.setattr(doctor, "_check_bridge_tools", lambda: doctor._result("PASS", "bridge:tools", "ok"))
    for name in doctor.REQUIRED_ENV:
        monkeypatch.delenv(name, raising=False)

    checks = doctor.collect_checks(doctor.build_parser().parse_args([]))

    failed = {check.name for check in checks if check.status == "FAIL"}
    assert "env:E2B_API_URL" in failed
    assert "env:E2B_API_KEY" in failed
    assert "env:CUBE_TEMPLATE_ID" in failed


def test_doctor_live_rejects_invalid_url(monkeypatch):
    doctor = _load_doctor()
    monkeypatch.setattr(doctor, "REQUIRED_PYTHON", (0, 0))
    monkeypatch.setattr(doctor, "REQUIRED_IMPORTS", ())
    monkeypatch.setattr(doctor, "_check_bridge_tools", lambda: doctor._result("PASS", "bridge:tools", "ok"))
    args = doctor.build_parser().parse_args(["--skip-env", "--live", "--cua-url", "not-a-url"])

    checks = doctor.collect_checks(args)

    assert any(check.name == "live:cua_mcp" and check.status == "FAIL" for check in checks)


def test_doctor_live_fails_cleanly_on_unreachable_service(monkeypatch):
    doctor = _load_doctor()
    monkeypatch.setattr(doctor, "REQUIRED_PYTHON", (0, 0))
    monkeypatch.setattr(doctor, "REQUIRED_IMPORTS", ())
    monkeypatch.setattr(doctor, "_check_bridge_tools", lambda: doctor._result("PASS", "bridge:tools", "ok"))
    args = doctor.build_parser().parse_args(
        ["--skip-env", "--live", "--cua-url", "http://127.0.0.1:9/mcp", "--cube-url", "http://127.0.0.1:9"]
    )

    exit_failures = [check for check in doctor.collect_checks(args) if check.status == "FAIL"]

    assert any(check.name == "live:cua_mcp" for check in exit_failures)
    assert any(check.name == "live:cube_api" for check in exit_failures)


def test_doctor_checks_bridge_tool_surface(monkeypatch):
    doctor = _load_doctor()
    monkeypatch.setattr(doctor, "REQUIRED_PYTHON", (0, 0))
    monkeypatch.setattr(doctor, "REQUIRED_IMPORTS", ())

    check = doctor._check_bridge_tools()

    assert check.status == "PASS"


def test_doctor_bridge_tools_include_health_list_destroy_all():
    doctor = _load_doctor()

    assert "cube_health" in doctor.BRIDGE_TOOLS
    assert "cube_list_sessions" in doctor.BRIDGE_TOOLS
    assert "cube_destroy_all" in doctor.BRIDGE_TOOLS
