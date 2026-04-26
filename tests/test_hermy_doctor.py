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
    assert "live:cua_mcp" not in captured.out


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
    monkeypatch.setattr(doctor, "_check_mcp_http_tools", lambda name, url, timeout: doctor._result("FAIL", name, "invalid URL"))
    args = doctor.build_parser().parse_args(["--skip-env", "--live", "--cua-url", "not-a-url"])

    checks = doctor.collect_checks(args)

    assert any(check.name == "live:cua_mcp" and check.status == "FAIL" for check in checks)


def test_doctor_live_fails_cleanly_on_unreachable_service(monkeypatch):
    doctor = _load_doctor()
    monkeypatch.setattr(doctor, "REQUIRED_PYTHON", (0, 0))
    monkeypatch.setattr(doctor, "REQUIRED_IMPORTS", ())
    monkeypatch.setattr(doctor, "_check_bridge_tools", lambda: doctor._result("PASS", "bridge:tools", "ok"))
    monkeypatch.setattr(doctor, "_check_mcp_http_tools", lambda name, url, timeout: doctor._result("FAIL", name, "unreachable"))
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


def test_doctor_config_validation_passes_safe_config(tmp_path):
    doctor = _load_doctor()
    config = tmp_path / "config.yaml"
    config.write_text(
        """
mcp_servers:
  cua:
    url: http://127.0.0.1:8000/mcp
  cube:
    command: hermy-cube-mcp
platform_toolsets:
  cli: ["web", "browser", "cua", "cube"]
""",
        encoding="utf-8",
    )

    checks = doctor._check_hermes_config(config)

    assert any(check.name == "hermes:toolsets" and check.status == "PASS" for check in checks)
    assert any(check.name == "hermes:mcp_servers" and check.status == "PASS" for check in checks)


def test_doctor_config_validation_fails_unsafe_toolsets(tmp_path):
    doctor = _load_doctor()
    config = tmp_path / "config.yaml"
    config.write_text(
        """
mcp_servers:
  cua:
    url: http://127.0.0.1:8000/mcp
  cube:
    command: hermy-cube-mcp
platform_toolsets:
  cli:
    - web
    - terminal
    - file
""",
        encoding="utf-8",
    )

    checks = doctor._check_hermes_config(config)

    failure = next(check for check in checks if check.name == "hermes:toolsets")
    assert failure.status == "FAIL"
    assert "terminal" in failure.detail
    assert "file" in failure.detail


def test_doctor_default_mode_does_not_check_live_services(monkeypatch):
    doctor = _load_doctor()
    monkeypatch.setattr(doctor, "REQUIRED_PYTHON", (0, 0))
    monkeypatch.setattr(doctor, "REQUIRED_IMPORTS", ())
    monkeypatch.setattr(doctor, "_check_bridge_tools", lambda: doctor._result("PASS", "bridge:tools", "ok"))
    args = doctor.build_parser().parse_args(["--skip-env"])

    checks = doctor.collect_checks(args)

    assert not any(check.name.startswith("live:") for check in checks)


def test_doctor_live_smoke_invokes_cube_smoke(monkeypatch):
    doctor = _load_doctor()
    monkeypatch.setattr(doctor, "REQUIRED_PYTHON", (0, 0))
    monkeypatch.setattr(doctor, "REQUIRED_IMPORTS", ())
    monkeypatch.setattr(doctor, "_check_bridge_tools", lambda: doctor._result("PASS", "bridge:tools", "ok"))
    monkeypatch.setattr(doctor, "_check_tcp_url", lambda name, url, timeout: doctor._result("PASS", name, "ok"))
    monkeypatch.setattr(doctor, "_check_mcp_http_tools", lambda name, url, timeout: doctor._result("PASS", name, "ok"))
    monkeypatch.setattr(doctor, "_run_cube_live_smoke", lambda timeout: [doctor._result("PASS", "smoke:cube_create", "ok")])
    args = doctor.build_parser().parse_args(["--skip-env", "--live-smoke", "--cube-url", "http://127.0.0.1:3000"])

    checks = doctor.collect_checks(args)

    assert any(check.name == "smoke:cube_create" and check.status == "PASS" for check in checks)
