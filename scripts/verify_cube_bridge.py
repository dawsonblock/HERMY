"""HERMY Cube Bridge Live Verifier.

Runs a complete live verification sequence against a real Cube/E2B deployment:
  1. Create sandbox
  2. Run echo hello
  3. Write /workspace/hermy_probe.txt
  4. Read the file and verify content
  5. Run Python print(1+1)
  6. Verify /etc/passwd write is denied by HERMY policy
  7. Destroy sandbox
  8. Confirm no session remains in RuntimeController
  9. Write logs to artifacts/live-proof/

All mutations require --live flag.

Exit codes:
  0  all checks passed
  1  one or more verification checks failed
  2  setup error (missing env, no --live flag, etc.)

Usage:
  export E2B_API_URL=http://cube-host:3000
  export E2B_API_KEY=dummy
  export CUBE_TEMPLATE_ID=your-template-id
  python scripts/verify_cube_bridge.py --live
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Add repo root to path for imports
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from controller.runtime_controller import RuntimeController
from cube_bridge.cube_mcp_server import CubeSandboxClient


REQUIRED_ENV = ("E2B_API_URL", "E2B_API_KEY", "CUBE_TEMPLATE_ID")
ARTIFACTS_DIR = REPO_ROOT / "artifacts" / "live-proof"


class LiveVerifier:
    """Runs the live Cube verification sequence."""

    def __init__(self) -> None:
        self.cube_client: CubeSandboxClient | None = None
        self.controller: RuntimeController | None = None
        self.sandbox_id: str | None = None
        self.logs: list[dict[str, Any]] = []
        self.failures: list[str] = []

    def log(self, step: str, status: str, detail: str = "") -> None:
        """Record a verification step result."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "step": step,
            "status": status,
            "detail": detail,
        }
        self.logs.append(entry)
        icon = "✓" if status == "PASS" else "✗" if status == "FAIL" else "⚠"
        print(f"  {icon} {step}: {status}" + (f" — {detail}" if detail else ""))

    def check(self, step: str, condition: bool, detail: str = "") -> bool:
        """Check a condition and log the result."""
        status = "PASS" if condition else "FAIL"
        self.log(step, status, detail)
        if not condition:
            self.failures.append(f"{step}: {detail}")
        return condition

    def setup(self) -> bool:
        """Initialize Cube client and controller."""
        print("\n=== HERMY Cube Bridge Live Verification ===\n")
        print("Setup:")

        # Check environment
        missing = [var for var in REQUIRED_ENV if not os.environ.get(var)]
        if missing:
            self.log("env_check", "FAIL", f"Missing required env vars: {', '.join(missing)}")
            return False
        self.log("env_check", "PASS", f"Found {len(REQUIRED_ENV)} required env vars")

        # Initialize client and controller
        try:
            self.cube_client = CubeSandboxClient()
            self.controller = RuntimeController(cua_client=None, cube_client=self.cube_client)
            self.log("client_init", "PASS", "CubeSandboxClient and RuntimeController initialized")
        except Exception as exc:
            self.log("client_init", "FAIL", str(exc))
            return False

        return True

    def verify_create(self) -> bool:
        """Create a sandbox and verify it was created."""
        print("\nVerification: Create sandbox")
        if self.controller is None:
            return self.check("create", False, "controller not initialized")
        try:
            response = self.controller.handle_code_request({"op": "create"})
            if not response.get("ok"):
                return self.check("create", False, response.get("error", "unknown error"))

            self.sandbox_id = response.get("result", {}).get("sandbox_id")
            if not self.sandbox_id:
                return self.check("create", False, "no sandbox_id in response")

            return self.check("create", True, f"sandbox_id={self.sandbox_id}")
        except Exception as exc:
            return self.check("create", False, str(exc))

    def verify_run_command(self) -> bool:
        """Run echo hello and verify stdout."""
        print("\nVerification: Run command")
        if self.controller is None:
            return self.check("run_command", False, "controller not initialized")
        try:
            response = self.controller.handle_code_request({
                "op": "run_command",
                "sandbox_id": self.sandbox_id,
                "command": "echo hello",
            })
            if not response.get("ok"):
                return self.check("run_command", False, response.get("error", "unknown error"))

            stdout = response.get("result", {}).get("stdout", "")
            expected = "hello"
            if stdout.strip() == expected:
                return self.check("run_command", True, f"stdout='{stdout.strip()}'")
            else:
                return self.check("run_command", False, f"expected '{expected}', got '{stdout.strip()}'")
        except Exception as exc:
            return self.check("run_command", False, str(exc))

    def verify_write_file(self) -> bool:
        """Write /workspace/hermy_probe.txt."""
        print("\nVerification: Write file")
        if self.controller is None:
            return self.check("write_file", False, "controller not initialized")
        try:
            response = self.controller.handle_code_request({
                "op": "write_file",
                "sandbox_id": self.sandbox_id,
                "path": "/workspace/hermy_probe.txt",
                "content": "HERMY_PROBE_CONTENT",
            })
            if response.get("ok"):
                return self.check("write_file", True, "/workspace/hermy_probe.txt written")
            else:
                return self.check("write_file", False, response.get("error", "unknown error"))
        except Exception as exc:
            return self.check("write_file", False, str(exc))

    def verify_read_file(self) -> bool:
        """Read /workspace/hermy_probe.txt and verify content."""
        print("\nVerification: Read file")
        if self.controller is None:
            return self.check("read_file", False, "controller not initialized")
        try:
            response = self.controller.handle_code_request({
                "op": "read_file",
                "sandbox_id": self.sandbox_id,
                "path": "/workspace/hermy_probe.txt",
            })
            if not response.get("ok"):
                return self.check("read_file", False, response.get("error", "unknown error"))

            content = response.get("result", {}).get("content", "")
            expected = "HERMY_PROBE_CONTENT"
            if content == expected:
                return self.check("read_file", True, "content matches")
            else:
                return self.check("read_file", False, f"expected '{expected}', got '{content}'")
        except Exception as exc:
            return self.check("read_file", False, str(exc))

    def verify_run_python(self) -> bool:
        """Run Python print(1+1) and verify stdout."""
        print("\nVerification: Run Python")
        if self.controller is None:
            return self.check("run_python", False, "controller not initialized")
        try:
            response = self.controller.handle_code_request({
                "op": "run_python",
                "sandbox_id": self.sandbox_id,
                "code": "print(1+1)",
            })
            if not response.get("ok"):
                return self.check("run_python", False, response.get("error", "unknown error"))

            stdout = response.get("result", {}).get("stdout", "")
            expected = "2"
            if stdout.strip() == expected:
                return self.check("run_python", True, f"stdout='{stdout.strip()}'")
            else:
                return self.check("run_python", False, f"expected '{expected}', got '{stdout.strip()}'")
        except Exception as exc:
            return self.check("run_python", False, str(exc))

    def verify_denied_passwd_write(self) -> bool:
        """Verify that /etc/passwd write is denied by HERMY policy."""
        print("\nVerification: Denied /etc/passwd write (policy check)")
        if self.controller is None:
            return self.check("denied_passwd_write", False, "controller not initialized")
        try:
            response = self.controller.handle_code_request({
                "op": "write_file",
                "sandbox_id": self.sandbox_id,
                "path": "/etc/passwd",
                "content": "should be denied",
            })
            # We expect this to be denied by policy
            if not response.get("ok"):
                error = response.get("error", "").lower()
                if "denied" in error or "policy" in error or "workspace" in error:
                    return self.check("denied_passwd_write", True, f"correctly denied: {response.get('error')}")
                else:
                    return self.check("denied_passwd_write", False, f"denied but not by policy: {response.get('error')}")
            else:
                return self.check("denied_passwd_write", False, "write was allowed (policy should have denied)")
        except Exception as exc:
            # Exception might also indicate policy denial depending on implementation
            error_str = str(exc).lower()
            if "denied" in error_str or "policy" in error_str or "workspace" in error_str:
                return self.check("denied_passwd_write", True, f"correctly denied: {exc}")
            return self.check("denied_passwd_write", False, str(exc))

    def verify_destroy(self) -> bool:
        """Destroy sandbox and verify session removed."""
        print("\nVerification: Destroy sandbox")
        if self.controller is None:
            return self.check("destroy", False, "controller not initialized")
        try:
            response = self.controller.handle_code_request({
                "op": "destroy",
                "sandbox_id": self.sandbox_id,
            })
            if not response.get("ok"):
                return self.check("destroy", False, response.get("error", "unknown error"))

            # Check that session is removed from controller
            if self.sandbox_id in self.controller.sessions:
                return self.check("destroy", False, "sandbox_id still in sessions after destroy")

            return self.check("destroy", True, f"sandbox {self.sandbox_id} destroyed")
        except Exception as exc:
            return self.check("destroy", False, str(exc))

    def verify_no_leaked_sessions(self) -> bool:
        """Verify no sessions remain."""
        print("\nVerification: No leaked sessions")
        if self.controller is None:
            return self.check("no_leaked_sessions", False, "controller not initialized")
        count = len(self.controller.sessions)
        return self.check("no_leaked_sessions", count == 0, f"{count} sessions remaining" if count > 0 else "all sessions cleaned up")

    def save_artifacts(self) -> None:
        """Save logs to artifacts/live-proof/."""
        print("\nSaving artifacts...")
        try:
            ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            log_file = ARTIFACTS_DIR / f"verify_cube_bridge_{timestamp}.json"
            log_file.write_text(json.dumps(self.logs, indent=2), encoding="utf-8")
            self.log("save_artifacts", "PASS", str(log_file))
        except Exception as exc:
            self.log("save_artifacts", "WARN", str(exc))

    def run(self) -> int:
        """Run the full verification sequence."""
        if not self.setup():
            self.save_artifacts()
            return 2

        # Run all verification steps
        self.verify_create()
        self.verify_run_command()
        self.verify_write_file()
        self.verify_read_file()
        self.verify_run_python()
        self.verify_denied_passwd_write()
        self.verify_destroy()
        self.verify_no_leaked_sessions()

        self.save_artifacts()

        # Summary
        print(f"\n{'=' * 50}")
        if self.failures:
            print(f"FAILED: {len(self.failures)} check(s) failed")
            for f in self.failures:
                print(f"  - {f}")
            return 1
        else:
            print("PASSED: All verification checks passed")
            return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="HERMY live Cube bridge verification."
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Run live mutations against a real Cube/E2B endpoint (required).",
    )
    args = parser.parse_args()

    if not args.live:
        print(
            "verify_cube_bridge: NOT RUNNING\n"
            "\n"
            "This script requires a real Cube/E2B-compatible deployment and "
            "the --live flag to perform mutations.\n"
            "\n"
            "Required environment variables:\n"
            "  E2B_API_URL\n"
            "  E2B_API_KEY\n"
            "  CUBE_TEMPLATE_ID\n"
            "\n"
            "Usage:\n"
            "  export E2B_API_URL=http://cube-host:3000\n"
            "  export E2B_API_KEY=dummy\n"
            "  export CUBE_TEMPLATE_ID=your-template-id\n"
            "  python scripts/verify_cube_bridge.py --live\n"
            "\n"
            "For the existing opt-in smoke test, use:\n"
            "  python scripts/hermy_doctor.py --live-cube-smoke",
            file=sys.stderr,
        )
        sys.exit(2)

    verifier = LiveVerifier()
    sys.exit(verifier.run())


if __name__ == "__main__":
    main()
