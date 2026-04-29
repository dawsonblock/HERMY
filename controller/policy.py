"""Policy enforcement helpers for Cube sandbox operations."""

from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import approval_ledger, event_logger

_CONTROL_OPERATOR_PATTERN = re.compile(r"[;&|<>`]|[$][(]|\n|\r")
_DANGEROUS_FLAG_TOKENS = {"--no-preserve-root", "-delete"}
_DIRECTLY_BLOCKED_EXECUTABLES = {
    "sudo",
    "su",
    "doas",
    "shutdown",
    "reboot",
    "halt",
    "poweroff",
    "mkfs",
    "fdisk",
    "dd",
    ":(){",
}
_SHELL_WRAPPERS = {"sh", "bash", "zsh", "dash", "fish", "ksh"}
_INLINE_INTERPRETERS = {"python", "python3", "python3.11", "node", "perl", "ruby", "php"}
_DANGEROUS_PATTERNS = (
    re.compile(r"(^|\s)(/bin/)?rm(\s|$).*(-r|-rf|-fr|--recursive).*(\s/|\s/\*|\s\*)"),
    re.compile(r"(^|\s)find(\s|$).*(-delete)(\s|$)"),
    re.compile(r"(^|\s)chmod(\s|$).*(-R|--recursive).*(\s777\s/|\s/|\s\*)"),
    re.compile(r"(^|\s)chown(\s|$).*(-R|--recursive).*(\s/|\s\*)"),
)
_DEFAULT_TIMEOUT_SECONDS = 60
_MAX_TIMEOUT_SECONDS = 120
_MAX_FILE_WRITE_BYTES = 1_000_000
_MAX_OUTPUT_BYTES = 200_000
_MAX_CODE_BYTES = 200_000


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str | None = None
    normalized_value: Any = None
    truncated: bool = False


def workspace_root() -> Path:
    """Return the configured workspace root."""
    root = os.environ.get("CUBE_WORKSPACE_DIR", "/workspace")
    return Path(root).expanduser().resolve(strict=False)


def _positive_int_from_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def default_timeout_seconds() -> int:
    return _positive_int_from_env("HERMY_DEFAULT_TIMEOUT_SECONDS", _DEFAULT_TIMEOUT_SECONDS)


def max_timeout_seconds() -> int:
    return _positive_int_from_env("HERMY_MAX_TIMEOUT_SECONDS", _MAX_TIMEOUT_SECONDS)


def max_file_write_bytes() -> int:
    return _positive_int_from_env("HERMY_MAX_FILE_WRITE_BYTES", _MAX_FILE_WRITE_BYTES)


def max_output_bytes() -> int:
    return _positive_int_from_env("HERMY_MAX_OUTPUT_BYTES", _MAX_OUTPUT_BYTES)


def max_code_bytes() -> int:
    return _positive_int_from_env("HERMY_MAX_CODE_BYTES", _MAX_CODE_BYTES)


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").lower() in {"1", "true", "yes", "on"}


def validate_allow_internet(allow_internet: bool | None) -> PolicyDecision:
    """Validate requested sandbox internet access."""
    requested = bool(allow_internet)
    if requested and not _truthy_env("HERMY_ALLOW_INTERNET"):
        return PolicyDecision(False, "internet access requires HERMY_ALLOW_INTERNET=1")
    return PolicyDecision(True, normalized_value=requested)


def validate_workspace_path(path: str) -> PolicyDecision:
    """Resolve ``path`` and ensure it stays inside the workspace root.

    Symlink limitation: this function resolves the path string on the host
    side using Path.resolve(strict=False). It cannot detect symlinks that
    exist *inside* the sandbox filesystem. For example, if a sandbox
    contains /workspace/link -> /etc, the path string "/workspace/link/file"
    passes this check even though the real target is outside /workspace.
    The real confinement boundary must be enforced by the Cube/E2B backend.
    Do not rely on HERMY path validation alone as a security boundary.
    """
    if not path or not str(path).strip():
        return PolicyDecision(False, "path cannot be empty")

    root = workspace_root()
    try:
        target = Path(path).expanduser()
        if not target.is_absolute():
            target = root / target
        resolved = target.resolve(strict=False)
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError):
        return PolicyDecision(False, "path must stay under the workspace root")

    return PolicyDecision(True, normalized_value=str(resolved))


def resolve_workspace_path(path: str) -> Path:
    """Backward-compatible Path wrapper around ``validate_workspace_path``."""
    decision = validate_workspace_path(path)
    if not decision.allowed:
        raise ValueError(decision.reason)
    return Path(str(decision.normalized_value))


def _executable_name(parts: list[str]) -> str:
    return Path(parts[0]).name if parts else ""


def _has_shell_wrapper(parts: list[str]) -> bool:
    executable = _executable_name(parts)
    if executable in _SHELL_WRAPPERS and any(flag in {"-c", "-lc", "-ic"} for flag in parts[1:]):
        return True
    if executable == "env" and len(parts) >= 3:
        wrapped = Path(parts[1]).name
        return wrapped in _SHELL_WRAPPERS and any(flag in {"-c", "-lc", "-ic"} for flag in parts[2:])
    return False


def _has_inline_interpreter(parts: list[str]) -> bool:
    executable = _executable_name(parts)
    return executable in _INLINE_INTERPRETERS and any(flag in {"-c", "-e"} for flag in parts[1:])


def _validate_argv_parts(parts: list[str], normalized: str) -> PolicyDecision:
    if not parts:
        return PolicyDecision(False, "command cannot be empty")

    executable = _executable_name(parts)
    if executable in _DIRECTLY_BLOCKED_EXECUTABLES:
        return PolicyDecision(False, f"blocked executable: {executable}")
    if _has_shell_wrapper(parts):
        return PolicyDecision(False, "shell wrapper execution is not allowed")
    if _has_inline_interpreter(parts):
        return PolicyDecision(False, "inline interpreter execution is not allowed")
    if any(token in _DANGEROUS_FLAG_TOKENS for token in parts):
        return PolicyDecision(False, "dangerous command flags are not allowed")
    for pattern in _DANGEROUS_PATTERNS:
        if pattern.search(normalized):
            return PolicyDecision(False, "destructive command pattern is blocked")
    return PolicyDecision(True)


def validate_command(
    command: str | list[str],
    approved: bool = False,
    approval_id: str | None = None,
) -> PolicyDecision:
    """Validate a command in argv-list or shell-string form.

    ``list[str]`` is preferred because policy validation can inspect explicit
    arguments. The Cube client may still convert it to a quoted shell command
    when the backend lacks a native argv API. ``str`` is treated as shell mode.
    Shell control operators require explicit approval with a valid approval_id,
    and destructive commands remain blocked even when approved.

    When HERMY_APPROVAL_LEDGER_FILE is set, approval_id is validated against
    the durable ledger (single-use, expiry-checked). When not set, approval_id
    proves only string existence for backward compatibility.
    """
    if isinstance(command, list):
        if not command:
            return PolicyDecision(False, "command argv cannot be empty")
        if not all(isinstance(part, str) and part for part in command):
            return PolicyDecision(False, "command argv entries must be non-empty strings")
        normalized = shlex.join(command)
        decision = _validate_argv_parts(command, normalized)
        if not decision.allowed:
            return decision
        return PolicyDecision(True, normalized_value=list(command))

    if not isinstance(command, str) or not command.strip():
        return PolicyDecision(False, "command cannot be empty")

    if _CONTROL_OPERATOR_PATTERN.search(command):
        if not approved:
            return PolicyDecision(False, "shell control operators are not allowed without approval")
        if not approval_id or not str(approval_id).strip():
            return PolicyDecision(False, "shell control operators require a valid approval_id")

        # Validate against ledger if configured
        ledger = approval_ledger.get_default_ledger()
        if ledger is not None:
            if not ledger.is_valid(approval_id, command):
                return PolicyDecision(
                    False,
                    "approval_id is invalid, expired, or was already used"
                )
            # Consume the approval (single-use)
            try:
                ledger.consume(approval_id)
            except Exception as exc:
                return PolicyDecision(False, f"could not consume approval: {exc}")

    try:
        parts = shlex.split(command, posix=True)
    except ValueError:
        return PolicyDecision(False, "command could not be parsed safely")

    normalized = " ".join(parts)
    decision = _validate_argv_parts(parts, normalized)
    if not decision.allowed:
        return decision
    return PolicyDecision(True, normalized_value=normalized)


def validate_write_path(path: str) -> PolicyDecision:
    decision = validate_workspace_path(path)
    if not decision.allowed:
        return PolicyDecision(False, "write must stay under the workspace root")
    return decision


def validate_read_path(path: str) -> PolicyDecision:
    decision = validate_workspace_path(path)
    if not decision.allowed:
        return PolicyDecision(False, "read must stay under the workspace root")
    return decision


def validate_timeout(timeout_seconds: int | None) -> PolicyDecision:
    """Validate and normalize an operation timeout."""
    timeout = default_timeout_seconds() if timeout_seconds is None else timeout_seconds
    try:
        timeout = int(timeout)
    except (TypeError, ValueError):
        return PolicyDecision(False, "timeout must be an integer number of seconds")

    if timeout <= 0:
        return PolicyDecision(False, "timeout must be positive")

    maximum = max_timeout_seconds()
    if timeout > maximum:
        return PolicyDecision(False, f"timeout exceeds maximum of {maximum} seconds")

    return PolicyDecision(True, normalized_value=timeout)


def validate_file_content(content: str) -> PolicyDecision:
    """Validate file write size."""
    size = len(content.encode("utf-8"))
    maximum = max_file_write_bytes()
    if size > maximum:
        return PolicyDecision(False, f"file content exceeds maximum of {maximum} bytes")
    return PolicyDecision(True, normalized_value=size)


def validate_python_code(code: str) -> PolicyDecision:
    """Validate Python source size before execution in Cube."""
    size = len(code.encode("utf-8"))
    maximum = max_code_bytes()
    if size > maximum:
        return PolicyDecision(False, f"python code exceeds maximum of {maximum} bytes", normalized_value=size)
    return PolicyDecision(True, normalized_value=size)


def truncate_output(text: str, max_bytes: int | None = None) -> tuple[str, bool]:
    """Trim large tool payloads and report whether truncation happened."""
    maximum = max_output_bytes() if max_bytes is None else max_bytes
    encoded = text.encode("utf-8")
    if len(encoded) <= maximum:
        return text, False
    clipped = encoded[:maximum].decode("utf-8", errors="ignore")
    return clipped + "\n[HERMY output truncated]\n", True


def truncate_text(value: str, *, limit: int | None = None) -> str:
    """Backward-compatible wrapper returning only truncated text."""
    return truncate_output(value, max_bytes=limit)[0]


def is_command_allowed(cmd: str | list[str]) -> bool:
    return validate_command(cmd).allowed


def is_write_allowed(path: str) -> bool:
    return validate_write_path(path).allowed


def is_read_allowed(path: str) -> bool:
    return validate_read_path(path).allowed


__all__ = [
    "PolicyDecision",
    "default_timeout_seconds",
    "is_command_allowed",
    "is_read_allowed",
    "is_write_allowed",
    "max_code_bytes",
    "max_file_write_bytes",
    "max_output_bytes",
    "max_timeout_seconds",
    "resolve_workspace_path",
    "truncate_output",
    "truncate_text",
    "validate_allow_internet",
    "validate_command",
    "validate_file_content",
    "validate_python_code",
    "validate_read_path",
    "validate_timeout",
    "validate_workspace_path",
    "validate_write_path",
    "workspace_root",
]
