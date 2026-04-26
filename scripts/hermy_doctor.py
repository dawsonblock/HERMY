#!/usr/bin/env python3
"""Environment checker for the HERMY integration scaffold."""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import os
from pathlib import Path
import socket
import sys
from dataclasses import dataclass
from urllib.parse import urlparse


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

REQUIRED_PYTHON = (3, 11)
REQUIRED_IMPORTS = (
    ("controller", "local controller package"),
    ("cube_bridge", "local Cube MCP bridge package"),
    ("mcp", "MCP Python SDK"),
    ("e2b_code_interpreter", "E2B code interpreter client"),
    ("httpx", "HTTP client used by doctor live checks"),
)
REQUIRED_ENV = ("E2B_API_URL", "E2B_API_KEY", "CUBE_TEMPLATE_ID")
BRIDGE_TOOLS = (
    "cube_create",
    "cube_run_command",
    "cube_run_python",
    "cube_read_file",
    "cube_write_file",
    "cube_destroy",
)


@dataclass(frozen=True)
class CheckResult:
    status: str
    name: str
    detail: str


def _result(status: str, name: str, detail: str) -> CheckResult:
    return CheckResult(status=status, name=name, detail=detail)


def _check_python() -> CheckResult:
    current = sys.version_info[:3]
    required = ".".join(str(part) for part in REQUIRED_PYTHON)
    current_text = ".".join(str(part) for part in current)
    if current >= REQUIRED_PYTHON:
        return _result("PASS", "python", f"Python {current_text}")
    return _result("FAIL", "python", f"Python {current_text}; HERMY requires >= {required}")


def _check_import(module_name: str, label: str) -> CheckResult:
    if importlib.util.find_spec(module_name) is None:
        return _result("FAIL", f"import:{module_name}", f"missing {label}")
    try:
        importlib.import_module(module_name)
    except Exception as exc:
        return _result("FAIL", f"import:{module_name}", f"{label} import failed: {exc}")
    return _result("PASS", f"import:{module_name}", f"found {label}")


def _check_env(name: str) -> CheckResult:
    value = os.environ.get(name)
    if value:
        return _result("PASS", f"env:{name}", "set")
    return _result("FAIL", f"env:{name}", "not set")


def _check_bridge_tools() -> CheckResult:
    try:
        module = importlib.import_module("cube_bridge.cube_mcp_server")
    except Exception as exc:
        return _result("FAIL", "bridge:tools", f"bridge import failed: {exc}")

    missing = [name for name in BRIDGE_TOOLS if not callable(getattr(module, name, None))]
    if missing:
        return _result("FAIL", "bridge:tools", "missing tools: " + ", ".join(missing))
    return _result("PASS", "bridge:tools", "Cube MCP tool surface is present")


def _check_tcp_url(name: str, url: str, timeout: float) -> CheckResult:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return _result("FAIL", name, f"invalid URL: {url}")

    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((parsed.hostname, port), timeout=timeout):
            return _result("PASS", name, f"reachable at {parsed.hostname}:{port}")
    except OSError as exc:
        return _result("FAIL", name, f"not reachable at {parsed.hostname}:{port}: {exc}")


def collect_checks(args: argparse.Namespace) -> list[CheckResult]:
    checks = [_check_python()]
    checks.extend(_check_import(module_name, label) for module_name, label in REQUIRED_IMPORTS)
    checks.append(_check_bridge_tools())

    if not args.skip_env:
        checks.extend(_check_env(name) for name in REQUIRED_ENV)

    cua_url = args.cua_url or os.environ.get("CUA_MCP_URL", "http://127.0.0.1:8000/mcp")
    cube_url = args.cube_url or os.environ.get("E2B_API_URL", "")

    if args.live:
        checks.append(_check_tcp_url("live:cua_mcp", cua_url, args.timeout))
        if cube_url:
            checks.append(_check_tcp_url("live:cube_api", cube_url, args.timeout))
        else:
            checks.append(_result("FAIL", "live:cube_api", "E2B_API_URL is not set"))
    else:
        checks.append(_result("WARN", "live:cua_mcp", f"not checked; use --live for {cua_url}"))
        checks.append(_result("WARN", "live:cube_api", "not checked; use --live after setting E2B_API_URL"))

    return checks


def _print_checks(checks: list[CheckResult]) -> None:
    width = max(len(check.name) for check in checks)
    for check in checks:
        print(f"{check.status:4} {check.name:{width}}  {check.detail}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check HERMY integration prerequisites.")
    parser.add_argument("--live", action="store_true", help="also check TCP connectivity to CUA and Cube API URLs")
    parser.add_argument("--skip-env", action="store_true", help="skip required Cube environment variable checks")
    parser.add_argument("--cua-url", help="CUA MCP URL to check when --live is used")
    parser.add_argument("--cube-url", help="Cube/E2B-compatible API URL to check when --live is used")
    parser.add_argument("--timeout", type=float, default=3.0, help="TCP connection timeout in seconds")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    checks = collect_checks(args)
    _print_checks(checks)
    return 1 if any(check.status == "FAIL" for check in checks) else 0


if __name__ == "__main__":
    raise SystemExit(main())
