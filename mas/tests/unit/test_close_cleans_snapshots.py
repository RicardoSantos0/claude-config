"""Tests for SharedStateManager.cleanup_snapshots."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import yaml

from mas.core.engine.shared_state_manager import SharedStateManager


def _write_state(project_dir: Path, status: str = "active") -> None:
    state = {
        "core_identity": {"project_id": "proj-test", "status": status},
        "workflow": {},
        "decisions": {},
        "_meta": {"governance_violations": []},
    }
    with open(project_dir / "shared_state.yaml", "w") as f:
        yaml.dump(state, f)


def _make_snapshot(project_dir: Path, name: str) -> Path:
    p = project_dir / name
    p.write_text("snapshot")
    return p


@pytest.fixture
def sm_in_tmpdir(tmp_path, monkeypatch):
    """SharedStateManager with project_dir patched to tmp_path."""
    _write_state(tmp_path, status="active")
    # Patch SharedStateManager so it resolves project_dir to tmp_path
    monkeypatch.setattr(
        "mas.core.engine.shared_state_manager.SharedStateManager._get_project_dir",
        lambda self: tmp_path,
        raising=False,
    )
    with patch("mas.core.engine.shared_state_manager.get_logger", return_value=MagicMock()):
        sm = SharedStateManager("proj-test")
    sm.project_dir = tmp_path
    sm.state_path = tmp_path / "shared_state.yaml"
    return sm, tmp_path


def test_cleanup_does_nothing_when_not_closed(sm_in_tmpdir):
    sm, project_dir = sm_in_tmpdir
    _write_state(project_dir, status="active")
    snap = _make_snapshot(project_dir, "shared_state_snapshot_execution_20260101T000000.yaml")
    deleted = sm.cleanup_snapshots()
    assert deleted == []
    assert snap.exists()


def test_cleanup_deletes_all_snapshots_when_closed(sm_in_tmpdir):
    sm, project_dir = sm_in_tmpdir
    _write_state(project_dir, status="closed")
    snap1 = _make_snapshot(project_dir, "shared_state_snapshot_planning_20260101T000000.yaml")
    snap2 = _make_snapshot(project_dir, "shared_state_snapshot_execution_20260102T000000.yaml")
    deleted = sm.cleanup_snapshots()
    assert len(deleted) == 2
    assert not snap1.exists()
    assert not snap2.exists()


def test_cleanup_keeps_latest_when_specified(sm_in_tmpdir):
    sm, project_dir = sm_in_tmpdir
    _write_state(project_dir, status="closed")
    _make_snapshot(project_dir, "shared_state_snapshot_a_20260101T000000.yaml")
    _make_snapshot(project_dir, "shared_state_snapshot_b_20260102T000000.yaml")
    deleted = sm.cleanup_snapshots(keep_latest=1)
    assert len(deleted) == 1
    remaining = list(project_dir.glob("shared_state_snapshot_*.yaml"))
    assert len(remaining) == 1


def test_cleanup_force_ignores_status(sm_in_tmpdir):
    sm, project_dir = sm_in_tmpdir
    _write_state(project_dir, status="active")
    snap = _make_snapshot(project_dir, "shared_state_snapshot_x_20260101T000000.yaml")
    deleted = sm.cleanup_snapshots(force=True)
    assert len(deleted) == 1
    assert not snap.exists()


def test_cleanup_handles_already_deleted_snapshot(sm_in_tmpdir):
    sm, project_dir = sm_in_tmpdir
    _write_state(project_dir, status="closed")
    snap = _make_snapshot(project_dir, "shared_state_snapshot_x_20260101T000000.yaml")
    snap.unlink()
    deleted = sm.cleanup_snapshots()
    assert deleted == []


def test_cleanup_returns_empty_when_no_snapshots(sm_in_tmpdir):
    sm, project_dir = sm_in_tmpdir
    _write_state(project_dir, status="closed")
    deleted = sm.cleanup_snapshots()
    assert deleted == []
