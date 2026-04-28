"""Shared pytest configuration.

Disables session-file persistence by default so pre-existing tests are not
affected by leftover hermy_sessions.json files in the working directory.
Individual tests that need persistence set HERMY_SESSION_FILE explicitly via
monkeypatch.setenv().
"""

import os

import pytest


@pytest.fixture(autouse=True)
def _disable_session_file_by_default(monkeypatch):
    """Set HERMY_SESSION_FILE=none unless the test overrides it."""
    if "HERMY_SESSION_FILE" not in os.environ:
        monkeypatch.setenv("HERMY_SESSION_FILE", "none")
