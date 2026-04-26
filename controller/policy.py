"""Policy enforcement helpers for Cube sandbox operations.

The integration layer should expose structured operations such as
``run_command``, ``run_python``, ``read_file`` and ``write_file``.
This module provides conservative validation for those operations so
the runtime can reject risky requests before they reach CubeSandbox.
"""

from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path


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
    re.compile(r"(^|\s)(/bin/)?rm(\s|$).*(-r|-rf|-fr|--recursive)"),
    re.compile(r"(^|\s)find(\s|$).*(-delete)(\s|$)"),
    re.compile(r"(^|\s)chmod(\s|$).*(-R|--recursive).*(\s/|\s\*)"),
    re.compile(r"(^|\s)chown(\s|$).*(-R|--recursive).*(\s/|\s\*)"),
)


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str | None = None
    normalized_value: str | None = None


def workspace_root() -> Path:
    """Return the configured workspace root."""
    root = os.environ.get("CUBE_WORKSPACE_DIR", "/workspace")
    return Path(root).expanduser().resolve(strict=False)


def resolve_workspace_path(path: str) -> Path:
    """Resolve ``path`` and ensure it stays inside the workspace root."""
    root = workspace_root()
    target = Path(path).expanduser()
    if not target.is_absolute():
        target = root / target
    resolved = target.resolve(strict=False)
    resolved.relative_to(root)
    return resolved


def validate_command(cmd: str) -> PolicyDecision:
    """Validate a shell command for the ``run_command`` operation."""
    if not cmd or not cmd.strip():
        return PolicyDecision(False, "command cannot be empty")

    if _CONTROL_OPERATOR_PATTERN.search(cmd):
        return PolicyDecision(False, "shell control operators are not allowed")

    try:
        parts = shlex.split(cmd, posix=True)
    except ValueError:
        return PolicyDecision(False, "command could not be parsed safely")

    if not parts:
        return PolicyDecision(False, "command cannot be empty")

    executable = Path(parts[0]).name
    normalized = " ".join(parts)

    if executable in _DIRECTLY_BLOCKED_EXECUTABLES:
        return PolicyDecision(False, f"blocked executable: {executable}")

    if executable in _SHELL_WRAPPERS and any(flag in {"-c", "-lc", "-ic"} for flag in parts[1:]):
        return PolicyDecision(False, "shell wrapper execution is not allowed")

    if executable == "env" and len(parts) >= 3:
        wrapped = Path(parts[1]).name
        if wrapped in _SHELL_WRAPPERS and any(flag in {"-c", "-lc", "-ic"} for flag in parts[2:]):
            return PolicyDecision(False, "shell wrapper execution is not allowed")

    if executable in _INLINE_INTERPRETERS and any(flag in {"-c", "-e"} for flag in parts[1:]):
        return PolicyDecision(False, "inline interpreter execution is not allowed")

    if any(token in _DANGEROUS_FLAG_TOKENS for token in parts):
        return PolicyDecision(False, "dangerous command flags are not allowed")

    for pattern in _DANGEROUS_PATTERNS:
        if pattern.search(normalized):
            return PolicyDecision(False, "destructive command pattern is blocked")

    return PolicyDecision(True, normalized_value=normalized)


def validate_write_path(path: str) -> PolicyDecision:
    """Validate a sandbox write target and normalize it."""
    if not path or not path.strip():
        return PolicyDecision(False, "path cannot be empty")

    try:
        resolved = resolve_workspace_path(path)
    except (OSError, RuntimeError, ValueError):
        return PolicyDecision(False, "write must stay under the workspace root")

    return PolicyDecision(True, normalized_value=str(resolved))


def is_command_allowed(cmd: str) -> bool:
    """Backward-compatible boolean wrapper around ``validate_command``."""
    return validate_command(cmd).allowed


def is_write_allowed(path: str) -> bool:
    """Backward-compatible boolean wrapper around ``validate_write_path``."""
    return validate_write_path(path).allowed


__all__ = [
    "PolicyDecision",
    "is_command_allowed",
    "is_write_allowed",
    "resolve_workspace_path",
    "validate_command",
    "validate_write_path",
    "workspace_root",
]
