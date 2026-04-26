"""Unit tests for the policy module."""

import os

from controller import policy


def test_blocked_commands():
    assert not policy.is_command_allowed("rm -rf /")
    assert not policy.is_command_allowed(" sudo rm -rf / ")
    assert not policy.is_command_allowed("shutdown now")
    assert not policy.is_command_allowed("bash -c 'rm -rf /'")
    assert not policy.is_command_allowed("sh -c 'echo ok'")
    assert not policy.is_command_allowed("python -c 'import shutil; shutil.rmtree(\"/\")'")
    assert not policy.is_command_allowed("node -e 'console.log(1)'")
    assert not policy.is_command_allowed("find / -delete")
    assert not policy.is_command_allowed("chmod -R 777 /")
    assert not policy.is_command_allowed("chown -R root /")


def test_validate_command_argv_allows_safe_command():
    decision = policy.validate_command(["echo", "ok"])

    assert decision.allowed
    assert decision.normalized_value == ["echo", "ok"]


def test_validate_command_argv_is_validated_before_backend_shell_conversion():
    decision = policy.validate_command(["echo", "ok && whoami"])

    assert decision.allowed
    assert decision.normalized_value == ["echo", "ok && whoami"]


def test_validate_command_empty_argv_denies():
    assert not policy.validate_command([]).allowed


def test_validate_command_plain_safe_string_allows():
    decision = policy.validate_command("echo ok")

    assert decision.allowed
    assert decision.normalized_value == "echo ok"


def test_validate_command_shell_control_requires_approval():
    assert not policy.validate_command("echo ok && whoami").allowed
    assert policy.validate_command("echo ok && whoami", approved=True).allowed


def test_validate_command_approved_shell_still_blocks_destructive():
    assert not policy.validate_command("rm -rf / && echo done", approved=True).allowed


def test_validate_command_argv_blocks_dangerous_executable():
    assert not policy.validate_command(["sudo", "id"]).allowed


def test_allowed_commands():
    assert policy.is_command_allowed("echo hello")
    assert policy.is_command_allowed("ls -l /workspace")


def test_workspace_write():
    os.environ["CUBE_WORKSPACE_DIR"] = "/workspace"
    assert policy.is_write_allowed("/workspace/output.txt")
    assert policy.is_write_allowed("subdir/notes.md")
    assert not policy.is_write_allowed("/etc/passwd")
    assert not policy.is_write_allowed("../outside.txt")
    assert not policy.is_write_allowed("/workspace_evil/output.txt")


def test_validate_workspace_path_normalizes_relative_path():
    os.environ["CUBE_WORKSPACE_DIR"] = "/workspace"
    decision = policy.validate_workspace_path("project/file.txt")

    assert decision.allowed
    assert decision.normalized_value == "/workspace/project/file.txt"


def test_validate_workspace_path_denies_escape():
    os.environ["CUBE_WORKSPACE_DIR"] = "/workspace"

    assert not policy.validate_workspace_path("../escape").allowed


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

    assert policy.validate_timeout(None).normalized_value == 20
    assert policy.validate_timeout(30).allowed
    assert not policy.validate_timeout(31).allowed


def test_file_content_policy_enforces_size(monkeypatch):
    monkeypatch.setenv("HERMY_MAX_FILE_WRITE_BYTES", "3")

    assert policy.validate_file_content("abc").allowed
    assert not policy.validate_file_content("abcd").allowed


def test_python_code_policy_enforces_size(monkeypatch):
    monkeypatch.setenv("HERMY_MAX_CODE_BYTES", "3")

    assert policy.validate_python_code("abc").allowed
    denied = policy.validate_python_code("abcd")
    assert not denied.allowed
    assert "python code exceeds maximum" in denied.reason


def test_allow_internet_requires_explicit_env(monkeypatch):
    monkeypatch.delenv("HERMY_ALLOW_INTERNET", raising=False)

    assert policy.validate_allow_internet(False).allowed
    assert not policy.validate_allow_internet(True).allowed

    monkeypatch.setenv("HERMY_ALLOW_INTERNET", "1")
    assert policy.validate_allow_internet(True).allowed


def test_truncate_output_returns_text_and_bool(monkeypatch):
    monkeypatch.setenv("HERMY_MAX_OUTPUT_BYTES", "4")

    text, truncated = policy.truncate_output("abcdef")
    assert text.startswith("abcd")
    assert "HERMY output truncated" in text
    assert truncated is True

    text, truncated = policy.truncate_output("abc")
    assert text == "abc"
    assert truncated is False


def test_truncate_text_uses_byte_limit(monkeypatch):
    monkeypatch.setenv("HERMY_MAX_OUTPUT_BYTES", "4")

    assert policy.truncate_text("abcdef").startswith("abcd")
    assert "HERMY output truncated" in policy.truncate_text("abcdef")
