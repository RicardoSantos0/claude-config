"""
Tests for `mas status <project_id>` output correctness.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from core.cli import main


@pytest.fixture()
def runner():
    return CliRunner()


def _base_state() -> dict:
    return {
        "core_identity": {
            "project_id": "proj-status-test",
            "current_phase": "execution",
            "status": "active",
            "updated_at": "2026-04-19T09:30:00+00:00",
        },
        "workflow": {
            "mode": "standard",
            "current_owner": "master_orchestrator",
            "completed_phases": ["intake", "specification"],
            "handoff_history": [],
        },
        "_meta": {
            "governance_violations": [],
        },
    }


def test_status_uses_core_identity_updated_at(runner, tmp_path, monkeypatch):
    projects_dir = tmp_path / "projects"
    project_id = "proj-status-test"
    (projects_dir / project_id).mkdir(parents=True)

    import core.cli as cli_mod
    monkeypatch.setattr(cli_mod, "_get_projects_dir", lambda: projects_dir)
    monkeypatch.setattr(cli_mod, "_load_state", lambda _pid: _base_state())

    import core.db as db_mod
    monkeypatch.setattr(
        db_mod,
        "query_token_usage",
        lambda _project_id: {"total": 0, "live_calls": 0, "dry_calls": 0},
    )

    result = runner.invoke(main, ["status", project_id])
    assert result.exit_code == 0
    assert "Updated  : 2026-04-19T09:30:00+00:00" in result.output


def test_status_counts_pending_from_acceptance_object(runner, tmp_path, monkeypatch):
    projects_dir = tmp_path / "projects"
    project_id = "proj-status-test"
    (projects_dir / project_id).mkdir(parents=True)

    state = _base_state()
    state["workflow"]["handoff_history"] = [
        {
            "handoff_id": "ho-001",
            "from_agent": "master_orchestrator",
            "to_agent": "scribe_agent",
            "task_description": "write docs",
            "acceptance": {"status": "pending"},
        },
        {
            "handoff_id": "ho-002",
            "from_agent": "master_orchestrator",
            "to_agent": "project_manager_agent",
            "task_description": "plan tasks",
            "acceptance": {"status": "accepted"},
        },
    ]

    import core.cli as cli_mod
    monkeypatch.setattr(cli_mod, "_get_projects_dir", lambda: projects_dir)
    monkeypatch.setattr(cli_mod, "_load_state", lambda _pid: state)

    import core.db as db_mod
    monkeypatch.setattr(
        db_mod,
        "query_token_usage",
        lambda _project_id: {"total": 0, "live_calls": 0, "dry_calls": 0},
    )

    result = runner.invoke(main, ["status", project_id])
    assert result.exit_code == 0
    assert "Pending handoffs : 1" in result.output
    assert "[ho-001]" in result.output
    assert "write docs" in result.output
