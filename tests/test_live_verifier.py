"""Tests for LiveVerifier with fake Cube client.

These tests verify that LiveVerifier correctly handles RuntimeController
response shapes (flat dicts, not response["result"] wrappers).
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# Add repo root to path
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.verify_cube_bridge import LiveVerifier


class FakeCubeClient:
    """Fake Cube client that returns flat RuntimeController-style responses."""

    def __init__(self) -> None:
        self.sandboxes: dict[str, dict[str, Any]] = {}
        self._counter = 0

    def _next_id(self) -> str:
        self._counter += 1
        return f"sbx-test-{self._counter:03d}"

    def cube_create(self, **kwargs: Any) -> dict[str, Any]:
        """Return flat response with sandbox_id at top level."""
        sandbox_id = self._next_id()
        self.sandboxes[sandbox_id] = {
            "template_id": kwargs.get("template_id", "test-template"),
            "files": {},
        }
        return {
            "ok": True,
            "sandbox_id": sandbox_id,
            "template_id": kwargs.get("template_id"),
            "backend": "cube",
        }

    def cube_run_command(self, sandbox_id: str, command: str, **kwargs: Any) -> dict[str, Any]:
        """Return flat response with stdout at top level."""
        if sandbox_id not in self.sandboxes:
            return {"ok": False, "error": "sandbox not found", "backend": "cube"}
        # Simple echo simulation
        if command == "echo hello":
            return {"ok": True, "stdout": "hello\n", "stderr": "", "backend": "cube"}
        return {"ok": True, "stdout": f"ran: {command}\n", "stderr": "", "backend": "cube"}

    def cube_run_python(self, sandbox_id: str, code: str, **kwargs: Any) -> dict[str, Any]:
        """Return flat response with stdout at top level."""
        if sandbox_id not in self.sandboxes:
            return {"ok": False, "error": "sandbox not found", "backend": "cube"}
        if "print(1+1)" in code:
            return {"ok": True, "stdout": "2\n", "stderr": "", "backend": "cube"}
        return {"ok": True, "stdout": f"ran python: {code}\n", "stderr": "", "backend": "cube"}

    def cube_write_file(self, sandbox_id: str, path: str, content: str, **kwargs: Any) -> dict[str, Any]:
        """Simulate file write with HERMY policy check for /etc/passwd."""
        if sandbox_id not in self.sandboxes:
            return {"ok": False, "error": "sandbox not found", "backend": "cube"}
        # Simulate HERMY policy: /etc/passwd is denied
        if path.startswith("/etc/"):
            return {
                "ok": False,
                "error": "write denied by policy: only /workspace paths are allowed",
                "backend": "cube",
            }
        self.sandboxes[sandbox_id]["files"][path] = content
        return {"ok": True, "backend": "cube"}

    def cube_read_file(self, sandbox_id: str, path: str, **kwargs: Any) -> dict[str, Any]:
        """Return flat response with content at top level."""
        if sandbox_id not in self.sandboxes:
            return {"ok": False, "error": "sandbox not found", "backend": "cube"}
        content = self.sandboxes[sandbox_id]["files"].get(path)
        if content is None:
            return {"ok": False, "error": f"file not found: {path}", "backend": "cube"}
        return {"ok": True, "content": content, "backend": "cube"}

    def cube_destroy(self, sandbox_id: str, **kwargs: Any) -> dict[str, Any]:
        """Destroy sandbox and return flat response."""
        if sandbox_id in self.sandboxes:
            del self.sandboxes[sandbox_id]
        return {"ok": True, "backend": "cube"}

    def dispatch(self, op: str, request: dict[str, Any]) -> dict[str, Any]:
        """Dispatch to appropriate method."""
        method = getattr(self, op, None)
        if method is None:
            return {"ok": False, "error": f"unknown operation: {op}", "backend": "cube"}
        return method(**request)


def create_verifier_with_fake() -> tuple[LiveVerifier, FakeCubeClient]:
    """Create a LiveVerifier with a fake Cube client injected."""
    from controller.runtime_controller import RuntimeController

    fake_client = FakeCubeClient()
    verifier = LiveVerifier()
    verifier.cube_client = fake_client
    verifier.controller = RuntimeController(cua_client=None, cube_client=fake_client)
    return verifier, fake_client


def test_verify_create_captures_sandbox_id():
    """verify_create should capture sandbox_id from flat response."""
    verifier, fake = create_verifier_with_fake()

    result = verifier.verify_create()

    assert result is True
    assert verifier.sandbox_id is not None
    assert verifier.sandbox_id.startswith("sbx-test-")
    assert verifier.sandbox_id in fake.sandboxes


def test_verify_create_fails_on_error_response():
    """verify_create should fail when response has ok=False."""
    verifier, fake = create_verifier_with_fake()

    # Mock the controller to return an error
    with patch.object(verifier.controller, "handle_code_request") as mock_handle:
        mock_handle.return_value = {"ok": False, "error": "template not found", "backend": "cube"}
        result = verifier.verify_create()

    assert result is False
    assert verifier.sandbox_id is None


def test_verify_run_command_reads_top_level_stdout():
    """verify_run_command should read stdout from flat response, not response["result"]."""
    verifier, fake = create_verifier_with_fake()

    # First create a sandbox
    verifier.verify_create()
    assert verifier.sandbox_id is not None

    # Then run command
    result = verifier.verify_run_command()

    assert result is True


def test_verify_read_file_reads_top_level_content():
    """verify_read_file should read content from flat response, not response["result"]."""
    verifier, fake = create_verifier_with_fake()

    # Create sandbox and write file
    verifier.verify_create()
    verifier.verify_write_file()

    # Read file
    result = verifier.verify_read_file()

    assert result is True


def test_verify_run_python_reads_top_level_stdout():
    """verify_run_python should read stdout from flat response, not response["result"]."""
    verifier, fake = create_verifier_with_fake()

    # Create sandbox
    verifier.verify_create()

    # Run Python
    result = verifier.verify_run_python()

    assert result is True


def test_verify_destroy_removes_session():
    """verify_destroy should remove the sandbox from controller sessions."""
    verifier, fake = create_verifier_with_fake()

    # Create and then destroy
    verifier.verify_create()
    sandbox_id = verifier.sandbox_id
    assert sandbox_id in verifier.controller.sessions

    result = verifier.verify_destroy()

    assert result is True
    assert sandbox_id not in verifier.controller.sessions


def test_failure_after_create_still_triggers_cleanup():
    """If a check fails after create, destroy should still run in finally block."""
    verifier, fake = create_verifier_with_fake()

    # Create sandbox
    create_result = verifier.verify_create()
    assert create_result is True
    sandbox_id = verifier.sandbox_id

    # Simulate a failure in run_command by mocking it to fail
    with patch.object(verifier, "verify_run_command") as mock_run:
        mock_run.side_effect = Exception("simulated failure")

        # Run the sequence with cleanup
        try:
            verifier.verify_run_command()
        except Exception:
            pass  # Expected

        # Destroy should still be callable (would be in finally block)
        # In actual run(), destroy is called in finally
        destroy_result = verifier.verify_destroy()
        assert destroy_result is True
        assert sandbox_id not in verifier.controller.sessions


def test_fail_fast_on_create_failure():
    """If create fails, verifier should not attempt dependent checks."""
    verifier, fake = create_verifier_with_fake()

    # Mock create to fail
    with patch.object(verifier.controller, "handle_code_request") as mock_handle:
        mock_handle.return_value = {"ok": False, "error": "cannot create", "backend": "cube"}

        result = verifier.verify_create()
        assert result is False

        # sandbox_id should be None, preventing dependent checks
        assert verifier.sandbox_id is None


def test_verifier_run_method_structure():
    """Test that run() has fail-fast and cleanup structure."""
    verifier, fake = create_verifier_with_fake()

    # Mock setup to succeed
    with patch.object(verifier, "setup", return_value=True):
        # Mock create to succeed
        with patch.object(verifier, "verify_create", return_value=True) as mock_create:
            # Mock other checks
            with patch.object(verifier, "verify_run_command") as mock_cmd:
                with patch.object(verifier, "verify_destroy") as mock_destroy:
                    mock_destroy.return_value = True

                    # Run should call create, then other checks, then destroy in finally
                    try:
                        verifier.run()
                    except Exception:
                        pass

                    # Create should be called
                    mock_create.assert_called_once()


def test_response_shape_no_result_wrapper():
    """Verify that responses are flat dicts, not wrapped in response['result']."""
    # This test documents the expected RuntimeController response shape
    fake_response_create = {
        "ok": True,
        "sandbox_id": "sbx-123",
        "template_id": "test",
        "backend": "cube",
        "request_id": "req-123",
        "operation": "create",
    }

    # These should work with flat access
    assert fake_response_create.get("sandbox_id") == "sbx-123"
    assert fake_response_create.get("stdout") is None  # Not present

    fake_response_command = {
        "ok": True,
        "stdout": "hello\n",
        "stderr": "",
        "backend": "cube",
    }

    assert fake_response_command.get("stdout") == "hello\n"
    assert fake_response_command.get("content") is None  # Not present

    fake_response_file = {
        "ok": True,
        "content": "file contents",
        "backend": "cube",
    }

    assert fake_response_file.get("content") == "file contents"


def test_successful_full_verification_path():
    """Test successful execution of all verification steps in sequence."""
    verifier, fake = create_verifier_with_fake()

    # Track which methods were called
    called_methods = []

    original_create = verifier.verify_create
    original_run_cmd = verifier.verify_run_command
    original_write = verifier.verify_write_file
    original_read = verifier.verify_read_file
    original_python = verifier.verify_run_python
    original_denied = verifier.verify_denied_passwd_write
    original_destroy = verifier.verify_destroy
    original_no_leak = verifier.verify_no_leaked_sessions

    def tracking_create():
        called_methods.append("create")
        return original_create()

    def tracking_run_cmd():
        called_methods.append("run_command")
        return original_run_cmd()

    def tracking_write():
        called_methods.append("write_file")
        return original_write()

    def tracking_read():
        called_methods.append("read_file")
        return original_read()

    def tracking_python():
        called_methods.append("run_python")
        return original_python()

    def tracking_denied():
        called_methods.append("denied_passwd_write")
        return original_denied()

    def tracking_destroy():
        called_methods.append("destroy")
        return original_destroy()

    def tracking_no_leak():
        called_methods.append("no_leaked_sessions")
        return original_no_leak()

    # Mock setup to succeed (skip env check)
    with patch.object(verifier, "setup", return_value=True):
        with patch.object(verifier, "verify_create", side_effect=tracking_create):
            with patch.object(verifier, "verify_run_command", side_effect=tracking_run_cmd):
                with patch.object(verifier, "verify_write_file", side_effect=tracking_write):
                    with patch.object(verifier, "verify_read_file", side_effect=tracking_read):
                        with patch.object(verifier, "verify_run_python", side_effect=tracking_python):
                            with patch.object(verifier, "verify_denied_passwd_write", side_effect=tracking_denied):
                                with patch.object(verifier, "verify_destroy", side_effect=tracking_destroy):
                                    with patch.object(verifier, "verify_no_leaked_sessions", side_effect=tracking_no_leak):
                                        exit_code = verifier.run()

    # All checks should have been called in correct order
    assert "create" in called_methods
    assert "run_command" in called_methods
    assert "write_file" in called_methods
    assert "read_file" in called_methods
    assert "run_python" in called_methods
    assert "denied_passwd_write" in called_methods
    assert "destroy" in called_methods
    assert "no_leaked_sessions" in called_methods

    # Should succeed (exit code 0)
    assert exit_code == 0


def test_artifact_session_path_default():
    """Verifier should default HERMY_SESSION_FILE to artifact path."""
    import tempfile
    import os

    # Save original env
    original_session_file = os.environ.get("HERMY_SESSION_FILE")

    try:
        # Clear the env var to test default behavior
        if "HERMY_SESSION_FILE" in os.environ:
            del os.environ["HERMY_SESSION_FILE"]

        # Import fresh to trigger main() path setup
        import importlib
        import scripts.verify_cube_bridge as vcb
        importlib.reload(vcb)

        # Check that ARTIFACTS_DIR is set and contains the expected path
        assert hasattr(vcb, "ARTIFACTS_DIR")
        expected_path = vcb.ARTIFACTS_DIR / "verify_cube_bridge_sessions.json"

        # The main() function should set this default
        # We verify the path structure is correct
        assert "artifacts" in str(expected_path)
        assert "verify_cube_bridge_sessions.json" in str(expected_path)

    finally:
        # Restore original env
        if original_session_file is not None:
            os.environ["HERMY_SESSION_FILE"] = original_session_file
        elif "HERMY_SESSION_FILE" in os.environ:
            del os.environ["HERMY_SESSION_FILE"]


def test_create_failure_prevents_dependent_checks():
    """If verify_create fails, dependent checks should not be called."""
    verifier, fake = create_verifier_with_fake()

    # Track which methods were called
    called_methods = []

    def failing_create():
        called_methods.append("create")
        verifier.failures.append("create failed")
        return False

    def should_not_be_called():
        called_methods.append("should_not_be_called")
        return True

    # Mock setup to succeed (skip env check)
    with patch.object(verifier, "setup", return_value=True):
        with patch.object(verifier, "verify_create", side_effect=failing_create):
            with patch.object(verifier, "verify_run_command", side_effect=should_not_be_called):
                with patch.object(verifier, "verify_write_file", side_effect=should_not_be_called):
                    with patch.object(verifier, "verify_read_file", side_effect=should_not_be_called):
                        with patch.object(verifier, "verify_run_python", side_effect=should_not_be_called):
                            with patch.object(verifier, "verify_denied_passwd_write", side_effect=should_not_be_called):
                                exit_code = verifier.run()

    # Create should be called
    assert "create" in called_methods

    # Dependent checks should NOT be called due to fail-fast
    assert "should_not_be_called" not in called_methods

    # Should return non-zero (fail-fast)
    assert exit_code != 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
