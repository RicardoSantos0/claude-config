"""
Unit tests for `mas doctor` and `mas resume`.
"""

from pathlib import Path

import pytest
from click.testing import CliRunner

from core.cli import main


@pytest.fixture()
def runner():
    return CliRunner()


def _patch_project_roots(monkeypatch, tmp_path):
    mas_root = tmp_path / "mas"
    projects_dir = mas_root / "projects"
    projects_dir.mkdir(parents=True, exist_ok=True)

    import core.engine.shared_state_manager as sm_mod
    import core.engine.checkpoint_writer as cw_mod
    import core.cli as cli_mod

    monkeypatch.setattr(sm_mod, "ROOT", mas_root)
    monkeypatch.setattr(cw_mod, "ROOT", mas_root)
    monkeypatch.setattr(cli_mod, "_get_projects_dir", lambda: projects_dir)
    return projects_dir


def test_doctor_runs_with_sqlite_backend(runner, monkeypatch, tmp_path):
    projects_dir = _patch_project_roots(monkeypatch, tmp_path)
    db_path = tmp_path / "doctor-episodic.db"

    monkeypatch.setenv("MAS_DATABASE_PROVIDER", "sqlite")
    monkeypatch.setenv("MAS_SQLITE_FALLBACK_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("MAS_VECTOR_ENABLED", "false")

    result = runner.invoke(main, ["doctor"])
    assert result.exit_code == 0
    assert "MAS Doctor" in result.output
    assert "database_backend" in result.output
    assert "Summary:" in result.output
    assert db_path.exists()


def test_resume_shows_pending_handoff(runner, monkeypatch, tmp_path):
    _patch_project_roots(monkeypatch, tmp_path)
    from core.engine.shared_state_manager import SharedStateManager

    project_id = "proj-resume-cli-001"
    sm = SharedStateManager(project_id)
    sm.initialize(request_id="req-001")
    state = sm.load()
    state["workflow"]["handoff_history"] = [
        {
            "handoff_id": "ho-resume-001",
            "from_agent": "master_orchestrator",
            "to_agent": "scribe_agent",
            "task_description": "Record closure notes",
            "acceptance": {"status": "pending"},
        }
    ]
    sm._save(state)

    result = runner.invoke(main, ["resume", project_id])
    assert result.exit_code == 0
    assert "[mas resume]" in result.output
    assert "pending   : 1" in result.output
    assert "ho-resume-001" in result.output
    assert "resolve pending handoff" in result.output
