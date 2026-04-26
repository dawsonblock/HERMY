"""Unit tests for the policy module."""

import os

from controller import policy


def test_blocked_commands():
    # Commands that start with dangerous prefixes should be denied
    assert not policy.is_command_allowed("rm -rf /")
    assert not policy.is_command_allowed(" sudo rm -rf / ")
    assert not policy.is_command_allowed("shutdown now")
    assert not policy.is_command_allowed("bash -c 'rm -rf /'")
    assert not policy.is_command_allowed("python -c 'import shutil; shutil.rmtree(\"/\")'")
    assert not policy.is_command_allowed("find / -delete")


def test_allowed_commands():
    # Harmless commands should pass
    assert policy.is_command_allowed("echo hello")
    assert policy.is_command_allowed("ls -l /workspace")


def test_workspace_write():
    # Only writes under the workspace should be allowed
    os.environ["CUBE_WORKSPACE_DIR"] = "/workspace"
    assert policy.is_write_allowed("/workspace/output.txt")
    assert policy.is_write_allowed("subdir/notes.md")
    assert not policy.is_write_allowed("/etc/passwd")
    assert not policy.is_write_allowed("../outside.txt")
    assert not policy.is_write_allowed("/workspace_evil/output.txt")


def test_workspace_resolution_uses_relative_to():
    os.environ["CUBE_WORKSPACE_DIR"] = "/workspace"
    decision = policy.validate_write_path("/workspace/project/file.txt")
    assert decision.allowed
    assert decision.normalized_value == "/workspace/project/file.txt"
