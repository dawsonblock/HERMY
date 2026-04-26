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


def test_read_policy_stays_inside_workspace():
    os.environ["CUBE_WORKSPACE_DIR"] = "/workspace"
    assert policy.is_read_allowed("/workspace/input.txt")
    assert not policy.is_read_allowed("/etc/hosts")


def test_timeout_policy_enforces_maximum(monkeypatch):
    monkeypatch.setenv("HERMY_DEFAULT_TIMEOUT_SECONDS", "20")
    monkeypatch.setenv("HERMY_MAX_TIMEOUT_SECONDS", "30")

    assert policy.validate_timeout(None).normalized_value == "20"
    assert policy.validate_timeout(30).allowed
    assert not policy.validate_timeout(31).allowed


def test_file_content_policy_enforces_size(monkeypatch):
    monkeypatch.setenv("HERMY_MAX_FILE_WRITE_BYTES", "3")

    assert policy.validate_file_content("abc").allowed
    assert not policy.validate_file_content("abcd").allowed


def test_truncate_text_uses_byte_limit(monkeypatch):
    monkeypatch.setenv("HERMY_MAX_OUTPUT_BYTES", "4")

    assert policy.truncate_text("abcdef").startswith("abcd")
    assert "HERMY output truncated" in policy.truncate_text("abcdef")
