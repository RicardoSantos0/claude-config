"""Tests for scripts/check_archive_clean.py archive hygiene checks."""

from __future__ import annotations

import importlib.util
import io
import tarfile
import zipfile
from pathlib import Path


def _load_archive_clean_module():
    repo_root = Path(__file__).resolve().parents[3]
    script = repo_root / "scripts" / "check_archive_clean.py"
    spec = importlib.util.spec_from_file_location("check_archive_clean", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_is_blocked_catches_root_and_prefixed_private_paths():
    mod = _load_archive_clean_module()

    blocked = [
        ".env",
        "claude-config/.env",
        ".git/config",
        "claude-config/.git/config",
        ".venv/pyvenv.cfg",
        "claude-config/.venv/pyvenv.cfg",
        "mas/data/episodic.db",
        "claude-config/mas/data/episodic.db",
        "mas/projects/proj-1/shared_state.yaml",
        "claude-config/skills/notebooklm/data/browser_state/state.json",
        "skills/notebooklm/.venv/pyvenv.cfg",
    ]

    for name in blocked:
        assert mod.is_blocked(name), name


def test_is_blocked_allows_source_paths():
    mod = _load_archive_clean_module()

    allowed = [
        "README.md",
        "claude-config/README.md",
        "mas/core/cli.py",
        "skills/notebooklm/README.md",
    ]

    for name in allowed:
        assert not mod.is_blocked(name), name


def test_check_archive_supports_zip_with_prefixed_paths(tmp_path):
    mod = _load_archive_clean_module()
    archive = tmp_path / "dirty.zip"

    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("claude-config/README.md", "ok")
        zf.writestr("claude-config/.env", "SECRET=1")

    assert mod.check_archive(str(archive)) == ["claude-config/.env"]


def test_check_archive_supports_tar_with_prefixed_paths(tmp_path):
    mod = _load_archive_clean_module()
    archive = tmp_path / "dirty.tar"

    with tarfile.open(archive, "w") as tf:
        good = b"ok"
        good_info = tarfile.TarInfo("claude-config/README.md")
        good_info.size = len(good)
        tf.addfile(good_info, io.BytesIO(good))

        bad = b"runtime"
        bad_info = tarfile.TarInfo("claude-config/mas/data/episodic.db")
        bad_info.size = len(bad)
        tf.addfile(bad_info, io.BytesIO(bad))

    assert mod.check_archive(str(archive)) == ["claude-config/mas/data/episodic.db"]
