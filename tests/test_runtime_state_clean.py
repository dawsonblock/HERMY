"""Test that runtime state files are not committed to repository.

This test ensures that hermy_sessions.json is not in the repo and that
runtime-generated files go to appropriate locations.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Add repo root to path
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pytest


def test_hermy_sessions_json_not_in_repo() -> None:
    """hermy_sessions.json must not exist in repository root."""
    repo_root = Path(__file__).resolve().parents[1]
    session_file = repo_root / "hermy_sessions.json"

    assert not session_file.exists(), (
        f"hermy_sessions.json must not be committed to repository. "
        f"Runtime state files should go to artifacts/, temp dirs, or paths "
        f"explicitly set by env vars like HERMY_SESSION_FILE."
    )


def test_hermy_sessions_example_exists() -> None:
    """hermy_sessions.example.json must exist with empty object."""
    repo_root = Path(__file__).resolve().parents[1]
    example_file = repo_root / "hermy_sessions.example.json"

    assert example_file.exists(), "hermy_sessions.example.json must exist as template"

    content = example_file.read_text().strip()
    assert content == "{}", f"hermy_sessions.example.json should contain empty object, got: {content}"


def test_gitignore_ignores_session_file() -> None:
    """.gitignore must ignore hermy_sessions.json."""
    repo_root = Path(__file__).resolve().parents[1]
    gitignore = repo_root / ".gitignore"

    assert gitignore.exists(), ".gitignore must exist"

    content = gitignore.read_text()
    assert "hermy_sessions.json" in content, ".gitignore must ignore hermy_sessions.json"


def test_artifacts_dir_not_committed() -> None:
    """artifacts/ directory should not be committed (runtime generated)."""
    repo_root = Path(__file__).resolve().parents[1]
    artifacts_dir = repo_root / "artifacts"

    # It's OK if it exists (from running tests), but it should be in .gitignore
    gitignore = repo_root / ".gitignore"
    if gitignore.exists():
        content = gitignore.read_text()
        if artifacts_dir.exists():
            # If directory exists, it should be in gitignore
            assert "artifacts/" in content or "artifacts" in content, \
                "artifacts/ should be in .gitignore if present"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
