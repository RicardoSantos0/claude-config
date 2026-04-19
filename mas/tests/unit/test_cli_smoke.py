"""
Lightweight CLI smoke flow:
init -> status -> pending -> prompt
"""

import re

import pytest
from click.testing import CliRunner

from core.cli import main


@pytest.fixture()
def runner():
    return CliRunner()


def test_cli_smoke_flow(runner, monkeypatch, tmp_path):
    mas_root = tmp_path / "mas"
    projects_dir = mas_root / "projects"
    projects_dir.mkdir(parents=True, exist_ok=True)

    import core.engine.shared_state_manager as sm_mod
    import core.engine.checkpoint_writer as cw_mod
    import core.cli as cli_mod

    monkeypatch.setattr(sm_mod, "ROOT", mas_root)
    monkeypatch.setattr(cw_mod, "ROOT", mas_root)
    monkeypatch.setattr(cli_mod, "_get_projects_dir", lambda: projects_dir)

    init_result = runner.invoke(main, ["init", "smoke-flow"])
    assert init_result.exit_code == 0
    m = re.search(r"Project ID\s+:\s+([^\r\n]+)", init_result.output)
    assert m, init_result.output
    project_id = m.group(1).strip()

    status_result = runner.invoke(main, ["status", project_id])
    assert status_result.exit_code == 0
    assert "Phase    : intake" in status_result.output

    pending_result = runner.invoke(main, ["pending", project_id])
    assert pending_result.exit_code == 0
    assert "No pending handoffs." in pending_result.output

    prompt_result = runner.invoke(main, ["prompt", project_id])
    assert prompt_result.exit_code == 0
    assert "# Agent: master_orchestrator" in prompt_result.output
