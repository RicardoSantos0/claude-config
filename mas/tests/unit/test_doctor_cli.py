"""Tests for mas doctor project-health checks."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_project(tmp_path: Path, phase: str = "intake", status: str = "active") -> Path:
    project_dir = tmp_path / "proj-test-doctor"
    project_dir.mkdir()
    state = {
        "core_identity": {"project_id": "proj-test-doctor", "current_phase": phase, "status": status},
        "workflow": {"pending_handoffs": []},
    }
    (project_dir / "shared_state.yaml").write_text(yaml.dump(state), encoding="utf-8")
    return project_dir


def _load_doctor_helpers():
    """Import the two private doctor helpers from cli.py without importing the full CLI."""
    import importlib.util, sys
    spec = importlib.util.spec_from_file_location(
        "mas_cli_doctor",
        Path(__file__).resolve().parents[2] / "core" / "cli.py",
    )
    module = importlib.util.module_from_spec(spec)
    # Patch ROOT and _get_projects_dir before exec
    return module


# ---------------------------------------------------------------------------
# _doctor_project_health via CLI runner
# ---------------------------------------------------------------------------

@pytest.fixture()
def runner():
    from click.testing import CliRunner
    return CliRunner()


def test_doctor_no_project_id(runner, monkeypatch):
    """mas doctor without project-id runs env checks only."""
    from core.cli import main
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    result = runner.invoke(main, ["doctor"])
    assert result.exit_code == 0
    assert "MAS Doctor" in result.output
    assert "Project Health" not in result.output


def test_doctor_project_missing(runner, monkeypatch, tmp_path):
    """mas doctor with nonexistent project_id reports fail."""
    from core.cli import main
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    # Redirect projects_dir to tmp_path so no real projects interfere
    monkeypatch.setattr("core.cli._get_projects_dir", lambda: tmp_path)
    result = runner.invoke(main, ["doctor", "proj-does-not-exist"])
    assert "project_exists" in result.output
    assert "[fail]" in result.output


def test_doctor_project_healthy(runner, monkeypatch, tmp_path):
    """mas doctor with healthy intake-phase project shows ok project health."""
    from core.cli import main
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr("core.cli._get_projects_dir", lambda: tmp_path)

    project_dir = _make_project(tmp_path, phase="intake")
    (project_dir / "intake").mkdir()
    (project_dir / "intake" / "original_brief.md").write_text("brief", encoding="utf-8")

    result = runner.invoke(main, ["doctor", "proj-test-doctor"])
    assert "Project Health" in result.output
    assert "project_exists" in result.output
    assert "phase=intake" in result.output


def test_doctor_missing_artifact_flagged(runner, monkeypatch, tmp_path):
    """mas doctor flags missing required artifact for current phase."""
    from core.cli import main
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr("core.cli._get_projects_dir", lambda: tmp_path)

    # No original_brief.md created — should be flagged
    _make_project(tmp_path, phase="intake")

    result = runner.invoke(main, ["doctor", "proj-test-doctor"])
    assert "artifact" in result.output
    assert "intake/original_brief.md" in result.output


def test_doctor_open_handoffs_warned(runner, monkeypatch, tmp_path):
    """mas doctor warns when open handoffs exist."""
    from core.cli import main
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr("core.cli._get_projects_dir", lambda: tmp_path)

    project_dir = tmp_path / "proj-test-doctor"
    project_dir.mkdir()
    state = {
        "core_identity": {"project_id": "proj-test-doctor", "current_phase": "execution", "status": "active"},
        "workflow": {"pending_handoffs": [{"handoff_id": "hof-001", "to_agent": "scribe_agent"}]},
    }
    (project_dir / "shared_state.yaml").write_text(yaml.dump(state), encoding="utf-8")

    result = runner.invoke(main, ["doctor", "proj-test-doctor"])
    assert "open_handoffs" in result.output
    assert "[warn]" in result.output


def test_doctor_snapshots_after_close_warned(runner, monkeypatch, tmp_path):
    """mas doctor warns when snapshots remain after project is closed."""
    from core.cli import main
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr("core.cli._get_projects_dir", lambda: tmp_path)

    project_dir = _make_project(tmp_path, phase="closed", status="closed")
    (project_dir / "shared_state_snapshot_001.yaml").write_text("snap", encoding="utf-8")
    (project_dir / "CLOSED.md").write_text("closed", encoding="utf-8")
    (project_dir / "final_shared_state.yaml").write_text("final", encoding="utf-8")

    result = runner.invoke(main, ["doctor", "proj-test-doctor"])
    assert "snapshots_after_close" in result.output
    assert "[warn]" in result.output


def test_doctor_project_health_section_present(runner, monkeypatch, tmp_path):
    """mas doctor with project_id always prints Project Health section."""
    from core.cli import main
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr("core.cli._get_projects_dir", lambda: tmp_path)

    _make_project(tmp_path, phase="intake")
    result = runner.invoke(main, ["doctor", "proj-test-doctor"])
    assert "Project Health" in result.output
    assert "Suggested next action" in result.output


def test_doctor_project_health_has_five_check_categories(runner, monkeypatch, tmp_path):
    """mas doctor project health covers at least 5 named check categories."""
    from core.cli import main
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr("core.cli._get_projects_dir", lambda: tmp_path)

    project_dir = _make_project(tmp_path, phase="intake")
    (project_dir / "intake").mkdir()
    (project_dir / "intake" / "original_brief.md").write_text("brief", encoding="utf-8")

    result = runner.invoke(main, ["doctor", "proj-test-doctor"])
    expected_categories = [
        "project_exists", "shared_state", "phase", "artifacts",
        "open_handoffs", "consultation", "skills",
    ]
    found = sum(1 for cat in expected_categories if cat in result.output)
    assert found >= 5, f"Expected >=5 check categories, found {found}. Output:\n{result.output}"
