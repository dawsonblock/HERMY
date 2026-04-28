"""HERMY Cube Bridge Live Verifier — STUB.

This script is a placeholder for live Cube bridge verification.
Full implementation requires a running E2B-compatible Cube deployment.
"""

# ROADMAP — intended test sequence when implemented:
#
#   1. Require E2B_API_URL, E2B_API_KEY, CUBE_TEMPLATE_ID.
#   2. verify_cube_create:      create a sandbox; assert sandbox_id returned.
#   3. verify_cube_run_command: run "echo hello"; assert stdout == "hello\n".
#   4. verify_cube_write_file:  write /workspace/hermy_probe.txt.
#   5. verify_cube_read_file:   read /workspace/hermy_probe.txt; assert content matches.
#   6. verify_cube_run_python:  run "print(1+1)"; assert stdout == "2\n".
#   7. verify_denied_passwd_write: attempt write to /etc/passwd; assert policy denial.
#   8. verify_cube_destroy:     destroy the sandbox; assert session removed.
#   9. verify_no_leaked_sessions: assert session registry empty after destroy.
#  10. Capture all logs to artifacts/live-proof/ for CI evidence.
#
# All live mutations are opt-in only.
# Run with: python scripts/verify_cube_bridge.py --live
#
# See also: scripts/hermy_doctor.py --live-cube-smoke

from __future__ import annotations

import argparse
import sys


def verify_cube_create() -> None:
    raise NotImplementedError(
        "verify_cube_create: live Cube verification not yet implemented — "
        "see build 14 roadmap in scripts/verify_cube_bridge.py"
    )


def verify_cube_run_command() -> None:
    raise NotImplementedError(
        "verify_cube_run_command: live Cube verification not yet implemented"
    )


def verify_cube_write_file() -> None:
    raise NotImplementedError(
        "verify_cube_write_file: live Cube verification not yet implemented"
    )


def verify_cube_read_file() -> None:
    raise NotImplementedError(
        "verify_cube_read_file: live Cube verification not yet implemented"
    )


def verify_cube_run_python() -> None:
    raise NotImplementedError(
        "verify_cube_run_python: live Cube verification not yet implemented"
    )


def verify_denied_passwd_write() -> None:
    raise NotImplementedError(
        "verify_denied_passwd_write: live Cube verification not yet implemented"
    )


def verify_cube_destroy() -> None:
    raise NotImplementedError(
        "verify_cube_destroy: live Cube verification not yet implemented"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="HERMY live Cube bridge verification (stub)."
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Run live mutations against a real Cube/E2B endpoint.",
    )
    args = parser.parse_args()

    if not args.live:
        print(
            "verify_cube_bridge: NOT IMPLEMENTED\n"
            "\n"
            "This script requires a real Cube/E2B-compatible deployment.\n"
            "See the ROADMAP comment at the top of this file for the\n"
            "intended test sequence.\n"
            "\n"
            "For the existing opt-in smoke test, use:\n"
            "  python scripts/hermy_doctor.py --live-cube-smoke\n"
            "\n"
            "Re-run with --live once the implementation is complete.",
            file=sys.stderr,
        )
        sys.exit(2)

    print("verify_cube_bridge: --live passed but implementation is pending.", file=sys.stderr)
    print("See ROADMAP in scripts/verify_cube_bridge.py.", file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
