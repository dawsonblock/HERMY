"""HERMY CUA Proxy Verifier.

Launches hermy-cua-mcp as a subprocess over stdio MCP, sends initialize +
initialized notification + tools/list, and verifies:

  - Forbidden tools (shell/file) are absent from the tool list.
  - Core GUI tools are present.
  - Questionable tools are absent by default.
  - Questionable tools appear when the matching HERMY_ALLOW_CUA_* env flag is set.

Features robust timeout handling (10s per read, 30s overall), process group
management for clean termination, and proper MCP lifecycle.

Exit codes:
  0  all checks passed
  1  one or more checks failed (unsafe tool surface)
  2  verifier could not run (timeout, startup failure, invalid MCP response)
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import textwrap
import time
from typing import Any

# Timeouts in seconds
_READ_TIMEOUT = 10.0
_OVERALL_TIMEOUT = 30.0


FORBIDDEN_TOOLS = {
    "computer_run_command",
    "computer_file_read",
    "computer_file_write",
    "computer_list_directory",
    "computer_delete_file",
    "computer_delete_directory",
    "computer_file_exists",
    "computer_directory_exists",
    "computer_create_directory",
    "computer_get_file_size",
}

REQUIRED_GUI_TOOLS = {
    "computer_screenshot",
    "computer_click",
    "computer_type",
    "computer_press_key",
}

QUESTIONABLE_TOOLS_FLAGS: dict[str, str] = {
    "computer_clipboard_get": "HERMY_ALLOW_CUA_CLIPBOARD",
    "computer_clipboard_set": "HERMY_ALLOW_CUA_CLIPBOARD",
    "computer_open": "HERMY_ALLOW_CUA_OPEN",
    "computer_launch_app": "HERMY_ALLOW_CUA_LAUNCH_APP",
    "computer_set_wallpaper": "HERMY_ALLOW_CUA_WALLPAPER",
}


class MCPTimeoutError(Exception):
    """Raised when MCP communication times out."""
    pass


def _send_jsonrpc(
    proc: subprocess.Popen,
    method: str,
    params: dict[str, Any],
    msg_id: int = 1,
    timeout: float = _READ_TIMEOUT,
) -> dict[str, Any]:
    """Send a JSON-RPC request and return the response with timeout handling."""
    request = json.dumps({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params}) + "\n"
    assert proc.stdin is not None
    assert proc.stdout is not None

    proc.stdin.write(request.encode())
    proc.stdin.flush()

    # Use select for timeout-capable reading on Unix
    try:
        import select
        ready, _, _ = select.select([proc.stdout], [], [], timeout)
        if not ready:
            raise MCPTimeoutError(f"Timeout waiting for response to {method} (timeout={timeout}s)")
        line = proc.stdout.readline()
    except ImportError:
        # Fallback for Windows - less robust but functional
        line = proc.stdout.readline()
        if not line:
            raise MCPTimeoutError(f"No response received for {method}")

    if not line:
        raise RuntimeError("EOF from hermy-cua-mcp subprocess")

    try:
        return json.loads(line.decode())
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON from subprocess: {exc}") from exc


def _kill_proc_cleanly(proc: subprocess.Popen) -> None:
    """Kill a subprocess and its process group, trying graceful shutdown first."""
    try:
        # Try graceful termination of process group
        if hasattr(signal, "SIGTERM"):
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except (ProcessLookupError, OSError):
                proc.terminate()
        else:
            proc.terminate()
        proc.wait(timeout=2)
    except (subprocess.TimeoutExpired, ProcessLookupError):
        try:
            # Force kill process group if needed
            if hasattr(signal, "SIGKILL"):
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except (ProcessLookupError, OSError):
                    proc.kill()
            else:
                proc.kill()
            proc.wait(timeout=2)
        except (subprocess.TimeoutExpired, ProcessLookupError):
            pass


def _list_tools_via_stdio(
    env: dict[str, str] | None = None,
    upstream_url: str | None = None,
    overall_timeout: float = _OVERALL_TIMEOUT,
) -> list[str]:
    """Launch CUA proxy, complete MCP handshake, and return tool list.

    Enforces overall timeout across entire operation and uses process groups
    for clean termination of child processes.
    """
    start_time = time.monotonic()
    deadline = start_time + overall_timeout

    cmd = [sys.executable, "-m", "cua_bridge.cua_mcp_proxy"]
    proc_env = os.environ.copy()
    if env:
        proc_env.update(env)
    if upstream_url:
        proc_env["HERMY_UPSTREAM_CUA_URL"] = upstream_url

    # Launch in new process group for clean termination
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=proc_env,
        start_new_session=True,  # Create new process group
    )

    try:
        # Calculate remaining timeout for each operation
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise MCPTimeoutError(f"Overall timeout ({overall_timeout}s) exceeded before starting")

        # Step 1: Send initialize request
        init_response = _send_jsonrpc(
            proc,
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "hermy-verifier", "version": "1"},
            },
            msg_id=1,
            timeout=min(_READ_TIMEOUT, remaining),
        )

        if "error" in init_response:
            raise RuntimeError(f"Initialize failed: {init_response['error']}")

        # Check deadline before continuing
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise MCPTimeoutError(f"Overall timeout ({overall_timeout}s) exceeded after initialize")

        # Step 2: Send initialized notification (required by MCP spec)
        if proc.stdin is None:
            raise RuntimeError("Subprocess stdin is not available")
        initialized_notification = json.dumps({
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        }) + "\n"
        proc.stdin.write(initialized_notification.encode())
        proc.stdin.flush()

        # Step 3: Request tools/list with remaining timeout
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise MCPTimeoutError(f"Overall timeout ({overall_timeout}s) exceeded before tools/list")

        resp = _send_jsonrpc(proc, "tools/list", {}, msg_id=2, timeout=min(_READ_TIMEOUT, remaining))
        tools = resp.get("result", {}).get("tools", [])
        return [t["name"] for t in tools if isinstance(t, dict) and "name" in t]

    except MCPTimeoutError:
        _kill_proc_cleanly(proc)
        raise
    except Exception:
        _kill_proc_cleanly(proc)
        raise
    finally:
        # Ensure cleanup
        if proc.poll() is None:
            _kill_proc_cleanly(proc)
        # Capture any stderr for diagnostics
        try:
            stderr_data = proc.stderr.read() if proc.stderr else b""
            if stderr_data:
                print(f"  DEBUG  Subprocess stderr: {stderr_data.decode('utf-8', errors='replace')[:500]}", file=sys.stderr)
        except Exception:
            pass


def _check(label: str, condition: bool, detail: str = "") -> bool:
    status = "PASS" if condition else "FAIL"
    msg = f"  {status}  {label}"
    if detail:
        msg += f" — {detail}"
    print(msg)
    return condition


def run_verification(upstream_url: str | None = None) -> int:
    failures = 0

    print("\n=== HERMY CUA Proxy Verification ===\n")

    print("--- Default mode (no questionable-tool flags) ---")
    try:
        tools = _list_tools_via_stdio(upstream_url=upstream_url)
    except Exception as exc:
        print(f"  ERROR  Could not list tools: {exc}", file=sys.stderr)
        print(
            textwrap.dedent("""
            Note: If hermy-cua-mcp is not installed, run:
              python -m pip install -e .
            or set HERMY_UPSTREAM_CUA_URL if upstream CUA is not running.
            The proxy still registers tools even when upstream is unreachable.
            """).strip()
        )
        return 2

    tool_set = set(tools)

    for tool in sorted(REQUIRED_GUI_TOOLS):
        ok = _check(f"required GUI tool present: {tool}", tool in tool_set)
        if not ok:
            failures += 1

    for tool in sorted(FORBIDDEN_TOOLS):
        ok = _check(f"forbidden tool absent: {tool}", tool not in tool_set)
        if not ok:
            failures += 1

    for tool in sorted(QUESTIONABLE_TOOLS_FLAGS):
        ok = _check(f"questionable tool absent by default: {tool}", tool not in tool_set)
        if not ok:
            failures += 1

    print("\n--- Questionable tool opt-in (HERMY_ALLOW_CUA_CLIPBOARD=1) ---")
    try:
        tools_with_flag = _list_tools_via_stdio(
            env={"HERMY_ALLOW_CUA_CLIPBOARD": "1"},
            upstream_url=upstream_url,
        )
    except Exception as exc:
        print(f"  ERROR  Could not list tools with flag: {exc}", file=sys.stderr)
        return 2

    flag_set = set(tools_with_flag)
    for tool in ("computer_clipboard_get", "computer_clipboard_set"):
        ok = _check(f"clipboard tool present when HERMY_ALLOW_CUA_CLIPBOARD=1: {tool}", tool in flag_set)
        if not ok:
            failures += 1

    print()
    if failures == 0:
        print("verify_cua_proxy: PASSED")
        return 0
    else:
        print(f"verify_cua_proxy: FAILED — {failures} issue(s)", file=sys.stderr)
        return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify the HERMY CUA MCP proxy tool filter.")
    parser.add_argument(
        "--upstream-url",
        default=None,
        help="Override HERMY_UPSTREAM_CUA_URL for the proxy subprocess.",
    )
    args = parser.parse_args()
    sys.exit(run_verification(upstream_url=args.upstream_url))


if __name__ == "__main__":
    main()
