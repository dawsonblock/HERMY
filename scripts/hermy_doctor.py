#!/usr/bin/env python3
"""Environment checker for the HERMY integration scaffold."""

from __future__ import annotations

import argparse
import copy
import importlib
import importlib.util
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from urllib.parse import urlparse


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

REQUIRED_PYTHON = (3, 11)
CUA_RECOMMENDED_PYTHON = (3, 12)
DEFAULT_HERMES_CONFIG = REPO_ROOT / "config" / "hermes_config_template.yaml"
HERMES_SOURCE_DIR = REPO_ROOT / "hermes-agent-2026.4.23"
VENDORED_TREES = (
    "hermes-agent-2026.4.23",
    "cua-main",
    "CubeSandbox-master",
)
REQUIRED_IMPORTS = (
    ("controller", "local controller package"),
    ("cube_bridge", "local Cube MCP bridge package"),
    ("mcp", "MCP Python SDK"),
    ("e2b_code_interpreter", "E2B code interpreter client"),
    ("httpx", "HTTP client used by doctor live checks"),
)
REQUIRED_ENV = ("E2B_API_URL", "E2B_API_KEY", "CUBE_TEMPLATE_ID")
SAFE_CLI_TOOLSETS = (
    "web",
    "browser",
    "vision",
    "image_gen",
    "skills",
    "todo",
    "memory",
    "session_search",
    "clarify",
    "cua",
    "cube",
)
HOST_EXECUTION_TOOLSETS = ("terminal", "file", "code_execution")
HOST_EXECUTION_TOOL_NAMES = (
    "terminal",
    "process",
    "read_file",
    "write_file",
    "patch",
    "search_files",
    "execute_code",
)
HERMES_REGISTRY_TIMEOUT_SECONDS = 30
BRIDGE_TOOLS = (
    "cube_health",
    "cube_create",
    "cube_list_sessions",
    "cube_run_command",
    "cube_run_python",
    "cube_read_file",
    "cube_write_file",
    "cube_destroy",
    "cube_destroy_all",
)


@dataclass(frozen=True)
class CheckResult:
    status: str
    name: str
    detail: str


def _result(status: str, name: str, detail: str) -> CheckResult:
    return CheckResult(status=status, name=name, detail=detail)


def _version_text(version: tuple[int, ...]) -> str:
    return ".".join(str(part) for part in version)


def _check_python() -> CheckResult:
    current = sys.version_info[:3]
    if current < REQUIRED_PYTHON:
        return _result(
            "FAIL",
            "python",
            f"Python {_version_text(current)}; HERMY requires >= {_version_text(REQUIRED_PYTHON)}",
        )
    if current < CUA_RECOMMENDED_PYTHON:
        return _result(
            "PASS",
            "python",
            f"Python {_version_text(current)}; use Python {_version_text(CUA_RECOMMENDED_PYTHON)} for integrated CUA runtime",
        )
    return _result("PASS", "python", f"Python {_version_text(current)}")


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


def _check_archive_structure() -> list[CheckResult]:
    checks: list[CheckResult] = []
    readme_text = ""
    readme_path = REPO_ROOT / "README.md"
    if readme_path.exists():
        try:
            readme_text = readme_path.read_text(encoding="utf-8")
        except OSError:
            readme_text = ""

    for dirname in VENDORED_TREES:
        path = REPO_ROOT / dirname
        if path.is_dir():
            checks.append(_result("PASS", f"archive:{dirname}", "vendored tree is present"))
        elif dirname in readme_text:
            checks.append(_result("FAIL", f"archive:{dirname}", "README claims this vendored tree exists, but it is absent"))
        else:
            checks.append(_result("WARN", f"archive:{dirname}", "vendored tree is absent and README does not claim it"))
    return checks


def _strip_comment(line: str) -> str:
    return line.split("#", 1)[0].rstrip()


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _parse_inline_list(raw: str) -> list[str]:
    raw = raw.strip()
    if not raw.startswith("[") or not raw.endswith("]"):
        return []
    body = raw[1:-1].strip()
    if not body:
        return []
    return [item.strip().strip("\"'") for item in body.split(",") if item.strip()]


def _extract_platform_cli_toolsets(text: str) -> list[str] | None:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if _strip_comment(line).strip() != "platform_toolsets:":
            continue
        base_indent = _indent(line)
        scan_index = index + 1
        while scan_index < len(lines):
            current = _strip_comment(lines[scan_index])
            stripped = current.strip()
            if not stripped:
                scan_index += 1
                continue
            current_indent = _indent(current)
            if current_indent <= base_indent:
                break
            if re.match(r"^cli\s*:", stripped):
                after_colon = stripped.split(":", 1)[1].strip()
                inline = _parse_inline_list(after_colon)
                if inline:
                    return inline
                values: list[str] = []
                item_index = scan_index + 1
                while item_index < len(lines):
                    item_line = _strip_comment(lines[item_index])
                    item_stripped = item_line.strip()
                    if not item_stripped:
                        item_index += 1
                        continue
                    if _indent(item_line) <= current_indent:
                        break
                    if item_stripped.startswith("- "):
                        values.append(item_stripped[2:].strip().strip("\"'"))
                    item_index += 1
                return values
            scan_index += 1
    return None


def _extract_mcp_server_names(text: str) -> set[str]:
    names: set[str] = set()
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if _strip_comment(line).strip() != "mcp_servers:":
            continue
        base_indent = _indent(line)
        scan_index = index + 1
        while scan_index < len(lines):
            current = _strip_comment(lines[scan_index])
            stripped = current.strip()
            if not stripped:
                scan_index += 1
                continue
            current_indent = _indent(current)
            if current_indent <= base_indent:
                break
            match = re.match(r"^([A-Za-z0-9_-]+)\s*:\s*$", stripped)
            if current_indent == base_indent + 2 and match:
                names.add(match.group(1))
            scan_index += 1
        break
    return names


def _has_legacy_terminal_none(text: str) -> bool:
    return bool(re.search(r"(?ms)^terminal:\s*\n(?:\s+.*\n)*?\s+backend:\s*[\"']?none[\"']?", text))


def _check_hermes_config(path: Path) -> list[CheckResult]:
    if not path.exists():
        return [_result("FAIL", "hermes_config", f"not found: {path}")]
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [_result("FAIL", "hermes_config", f"could not read {path}: {exc}")]

    checks: list[CheckResult] = []
    cli_toolsets = _extract_platform_cli_toolsets(text)
    if cli_toolsets is None:
        checks.append(_result("FAIL", "hermes:toolsets", "platform_toolsets.cli is missing"))
        safe_toolsets = False
    else:
        blocked = sorted(set(cli_toolsets) & set(HOST_EXECUTION_TOOLSETS))
        if blocked:
            checks.append(_result("FAIL", "hermes:toolsets", "host execution toolsets enabled: " + ", ".join(blocked)))
            safe_toolsets = False
        else:
            checks.append(_result("PASS", "hermes:toolsets", "CLI host execution toolsets are disabled"))
            safe_toolsets = True

    mcp_servers = _extract_mcp_server_names(text)
    missing_mcp = sorted({"cua", "cube"} - mcp_servers)
    if missing_mcp:
        checks.append(_result("FAIL", "hermes:mcp_servers", "missing MCP servers: " + ", ".join(missing_mcp)))
    else:
        checks.append(_result("PASS", "hermes:mcp_servers", "CUA and Cube MCP servers are configured"))

    if _has_legacy_terminal_none(text) and not safe_toolsets:
        checks.append(_result("WARN", "hermes:terminal_backend", "legacy terminal.backend none is not a supported safety control"))

    return checks


def _load_yaml_config(path: Path) -> dict:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise RuntimeError("PyYAML is required for Hermes registry verification") from exc

    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except OSError as exc:
        raise RuntimeError(f"could not read {path}: {exc}") from exc
    except Exception as exc:
        raise RuntimeError(f"could not parse {path}: {exc}") from exc

    if not isinstance(loaded, dict):
        raise RuntimeError("Hermes config must parse as a mapping")
    return loaded


def _disable_mcp_for_schema_resolution(config: dict) -> dict:
    safe_config = copy.deepcopy(config)
    servers = safe_config.get("mcp_servers")
    if isinstance(servers, dict):
        for server_cfg in servers.values():
            if isinstance(server_cfg, dict):
                server_cfg["enabled"] = False
    return safe_config


def _resolve_hermes_registry(config: dict) -> tuple[set[str], set[str]]:
    """Resolve Hermes CLI toolsets and schemas without connecting live MCP."""
    if not HERMES_SOURCE_DIR.exists():
        raise RuntimeError(f"vendored Hermes source not found: {HERMES_SOURCE_DIR}")

    safe_config = _disable_mcp_for_schema_resolution(config)
    with tempfile.TemporaryDirectory(prefix="hermy-hermes-home-") as temp_dir:
        temp_home = Path(temp_dir)
        (temp_home / "config.yaml").write_text(json.dumps(safe_config), encoding="utf-8")
        code = f"""
import json
import os
import sys

sys.path.insert(0, {str(HERMES_SOURCE_DIR)!r})

from hermes_cli.config import load_config
from hermes_cli.tools_config import _get_platform_tools

config = load_config()
enabled = sorted(_get_platform_tools(config, "cli"))

from model_tools import get_tool_definitions

schemas = get_tool_definitions(enabled_toolsets=enabled, quiet_mode=True)
tool_names = sorted(
    schema.get("function", {{}}).get("name", "")
    for schema in schemas
    if schema.get("function", {{}}).get("name")
)
print("HERMY_REGISTRY_JSON=" + json.dumps({{"toolsets": enabled, "tool_names": tool_names}}))
"""
        env = os.environ.copy()
        env["HERMES_HOME"] = str(temp_home)
        env["HERMES_IGNORE_USER_CONFIG"] = "0"
        env["PYTHONPATH"] = str(HERMES_SOURCE_DIR) + os.pathsep + env.get("PYTHONPATH", "")
        proc = subprocess.run(
            [sys.executable, "-c", code],
            env=env,
            text=True,
            capture_output=True,
            timeout=HERMES_REGISTRY_TIMEOUT_SECONDS,
            check=False,
        )

    marker = "HERMY_REGISTRY_JSON="
    payload_line = next((line for line in reversed(proc.stdout.splitlines()) if line.startswith(marker)), "")
    if proc.returncode != 0 or not payload_line:
        detail = (proc.stderr or proc.stdout or "Hermes registry subprocess produced no output").strip()
        raise RuntimeError(detail)

    payload = json.loads(payload_line[len(marker):])
    return set(payload.get("toolsets", [])), set(payload.get("tool_names", []))


def _check_hermes_tool_registry(path: Path) -> list[CheckResult]:
    try:
        config = _load_yaml_config(path)
        resolved_toolsets, tool_names = _resolve_hermes_registry(config)
    except subprocess.TimeoutExpired:
        return [_result("FAIL", "hermes:registry", "Hermes registry verification timed out")]
    except Exception as exc:
        return [_result("FAIL", "hermes:registry", str(exc))]

    checks: list[CheckResult] = []
    blocked_toolsets = sorted(resolved_toolsets & set(HOST_EXECUTION_TOOLSETS))
    if blocked_toolsets:
        checks.append(_result("FAIL", "hermes:registry_toolsets", "resolved host execution toolsets: " + ", ".join(blocked_toolsets)))
    else:
        checks.append(_result("PASS", "hermes:registry_toolsets", "resolved CLI toolsets exclude host execution"))

    blocked_tools = sorted(tool_names & set(HOST_EXECUTION_TOOL_NAMES))
    if blocked_tools:
        checks.append(_result("FAIL", "hermes:registry_tools", "resolved host execution tools: " + ", ".join(blocked_tools)))
    else:
        checks.append(_result("PASS", "hermes:registry_tools", "resolved tool schemas exclude host execution"))

    return checks


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


def _check_mcp_http_tools(name: str, url: str, timeout: float) -> CheckResult:
    try:
        import httpx
    except ImportError:
        return _result("FAIL", name, "httpx is required for live MCP discovery")

    request = {"jsonrpc": "2.0", "id": "hermy-doctor-tools", "method": "tools/list", "params": {}}
    headers = {"accept": "application/json, text/event-stream", "content-type": "application/json"}
    try:
        response = httpx.post(url, json=request, headers=headers, timeout=timeout)
        response.raise_for_status()
    except Exception as exc:
        return _result("FAIL", name, f"MCP tools/list failed: {exc}")

    text = response.text.strip()
    if text.startswith("event:"):
        data_lines = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")]
        text = data_lines[-1] if data_lines else ""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return _result("FAIL", name, f"MCP tools/list returned non-JSON response: {exc}")

    tools = payload.get("result", {}).get("tools")
    if not isinstance(tools, list):
        return _result("FAIL", name, "MCP tools/list response did not include result.tools")
    return _result("PASS", name, f"discovered {len(tools)} tool(s)")


def _run_cube_live_smoke(timeout: float) -> list[CheckResult]:
    checks: list[CheckResult] = []
    sandbox_id: str | None = None
    try:
        from cube_bridge.cube_mcp_server import CubeSandboxClient
        from controller.runtime_controller import RuntimeController

        controller = RuntimeController(cua_client=None, cube_client=CubeSandboxClient())
        create = controller.handle_code_request({"op": "create", "timeout_seconds": int(timeout)})
        if create.get("ok") is not True:
            return [_result("FAIL", "smoke:cube_create", str(create.get("error") or create))]
        sandbox_id = str(create["sandbox_id"])
        checks.append(_result("PASS", "smoke:cube_create", sandbox_id))

        write = controller.handle_code_request(
            {"op": "write_file", "sandbox_id": sandbox_id, "path": "/workspace/hermy_probe.txt", "content": "probe"}
        )
        checks.append(_result("PASS" if write.get("ok") is True else "FAIL", "smoke:cube_write", str(write.get("error") or "ok")))

        read = controller.handle_code_request({"op": "read_file", "sandbox_id": sandbox_id, "path": "/workspace/hermy_probe.txt"})
        read_ok = read.get("ok") is True and read.get("content") == "probe"
        checks.append(_result("PASS" if read_ok else "FAIL", "smoke:cube_read", str(read.get("error") or read.get("content"))))

        command = controller.handle_code_request({"op": "run_command", "sandbox_id": sandbox_id, "command": ["echo", "probe"]})
        checks.append(_result("PASS" if command.get("ok") is True else "FAIL", "smoke:cube_command", str(command.get("error") or "ok")))

        python = controller.handle_code_request({"op": "run_python", "sandbox_id": sandbox_id, "code": "print('probe')"})
        checks.append(_result("PASS" if python.get("ok") is True else "FAIL", "smoke:cube_python", str(python.get("error") or "ok")))

        denied = controller.handle_code_request(
            {"op": "write_file", "sandbox_id": sandbox_id, "path": "/etc/passwd", "content": "nope"}
        )
        checks.append(_result("PASS" if denied.get("ok") is False else "FAIL", "smoke:path_reject", str(denied.get("error") or denied)))
    except Exception as exc:
        checks.append(_result("FAIL", "smoke:cube", str(exc)))
    finally:
        if sandbox_id:
            try:
                destroy = controller.handle_code_request({"op": "destroy", "sandbox_id": sandbox_id})  # type: ignore[name-defined]
                checks.append(
                    _result("PASS" if destroy.get("ok") is True else "FAIL", "smoke:cube_destroy", str(destroy.get("error") or "ok"))
                )
            except Exception as exc:  # pragma: no cover - live cleanup fallback
                checks.append(_result("FAIL", "smoke:cube_destroy", str(exc)))
    return checks


def _live_modes(args: argparse.Namespace) -> tuple[bool, bool, bool]:
    live_cua = bool(args.live_cua or args.live or args.live_smoke)
    live_cube = bool(args.live_cube or args.live or args.live_smoke)
    live_cube_smoke = bool(args.live_cube_smoke or args.live_smoke)
    return live_cua, live_cube, live_cube_smoke


def collect_checks(args: argparse.Namespace) -> list[CheckResult]:
    live_cua, live_cube, live_cube_smoke = _live_modes(args)
    checks = [_check_python()]
    checks.extend(_check_archive_structure())
    checks.extend(_check_import(module_name, label) for module_name, label in REQUIRED_IMPORTS)
    checks.append(_check_bridge_tools())
    checks.extend(_check_hermes_config(Path(args.hermes_config)))
    if args.hermes_tool_registry:
        checks.extend(_check_hermes_tool_registry(Path(args.hermes_config)))

    only_live_cua = live_cua and not live_cube and not live_cube_smoke
    if not args.skip_env and not only_live_cua:
        checks.extend(_check_env(name) for name in REQUIRED_ENV)

    cua_url = args.cua_url or os.environ.get("CUA_MCP_URL", "http://127.0.0.1:8000/mcp")
    cube_url = args.cube_url or os.environ.get("E2B_API_URL", "")

    if live_cua:
        checks.append(_check_tcp_url("live:cua_mcp", cua_url, args.timeout))
        checks.append(_check_mcp_http_tools("live:cua_tools", cua_url, args.timeout))
    if live_cube:
        if cube_url:
            checks.append(_check_tcp_url("live:cube_api", cube_url, args.timeout))
        else:
            checks.append(_result("FAIL", "live:cube_api", "E2B_API_URL is not set"))

    if live_cube_smoke:
        checks.extend(_run_cube_live_smoke(args.timeout))

    return checks


def _print_checks(checks: list[CheckResult]) -> None:
    width = max(len(check.name) for check in checks)
    for check in checks:
        print(f"{check.status:4} {check.name:{width}}  {check.detail}")


def _print_json(checks: list[CheckResult]) -> None:
    import json
    result = [{"status": c.status, "name": c.name, "detail": c.detail} for c in checks]
    print(json.dumps(result))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check HERMY integration prerequisites.")
    parser.add_argument("--live", action="store_true", help="alias for --live-cua --live-cube")
    parser.add_argument("--live-smoke", action="store_true", help="alias for --live-cua --live-cube --live-cube-smoke")
    parser.add_argument("--live-cua", action="store_true", help="check CUA TCP reachability and HTTP MCP tools/list")
    parser.add_argument("--live-cube", action="store_true", help="check Cube/E2B API TCP reachability without sandbox mutation")
    parser.add_argument("--live-cube-smoke", action="store_true", help="run opt-in live Cube create/run/read/write/destroy smoke tests")
    parser.add_argument("--skip-env", action="store_true", help="skip required Cube environment variable checks")
    parser.add_argument("--cua-url", help="CUA MCP URL to check when CUA live checks are used")
    parser.add_argument("--cube-url", help="Cube/E2B-compatible API URL to check when Cube live checks are used")
    parser.add_argument("--hermes-config", default=str(DEFAULT_HERMES_CONFIG), help="Hermes config file to validate")
    parser.add_argument("--hermes-tool-registry", action="store_true", help="verify vendored Hermes resolves no host execution tools")
    parser.add_argument("--timeout", type=float, default=3.0, help="connection and smoke-test timeout in seconds")
    parser.add_argument("--strict", action="store_true", help="turn WARN into failure exit behavior where appropriate")
    parser.add_argument("--json", action="store_true", dest="json_output", help="print machine-readable JSON array with all checks")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    checks = collect_checks(args)
    if args.json_output:
        _print_json(checks)
    else:
        _print_checks(checks)
    # Strict mode: treat WARN as failure for exit code (when appropriate)
    # Missing local dependencies remain FAIL regardless of strict mode
    # Missing live services when not running live checks: warn only unless strict
    has_fail = any(check.status == "FAIL" for check in checks)
    has_warn = any(check.status == "WARN" for check in checks)
    if has_fail:
        return 1
    if args.strict and has_warn:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
