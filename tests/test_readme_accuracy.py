"""README accuracy checks for HERMY scaffold claims."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
VENDORED_TREES = (
    "hermes-agent-2026.4.23",
    "cua-main",
    "CubeSandbox-master",
)


def test_readme_names_only_existing_vendored_trees():
    text = README.read_text(encoding="utf-8")

    for dirname in VENDORED_TREES:
        assert dirname in text
        assert (ROOT / dirname).is_dir()


def test_readme_documents_test_local_script():
    text = README.read_text(encoding="utf-8")

    assert "scripts/test_local.sh" in text


def test_readme_documents_default_tests_need_no_live_infrastructure():
    text = README.read_text(encoding="utf-8")

    assert "Default tests do not require live CUA, live Cube, KVM, Docker, API keys, or network." in text


def test_run_local_tests_delegates_to_test_local():
    text = (ROOT / "scripts" / "run_local_tests.sh").read_text(encoding="utf-8")

    assert "test_local.sh" in text


def test_test_local_script_runs_compileall_and_pytest():
    text = (ROOT / "scripts" / "test_local.sh").read_text(encoding="utf-8")

    assert "python -m compileall -q" in text
    assert "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest -q" in text
