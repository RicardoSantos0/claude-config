"""
CLI integration flow — init → handoff lifecycle → prompt assembly.

Verifies real state transitions and substantive outputs, not just exit codes.
"""

import re
from pathlib import Path

import pytest
from click.testing import CliRunner

from core.cli import main
from core.engine.handoff_engine import HandoffEngine
from core.engine.shared_state_manager import SharedStateManager
from core.engine.audit_logger import AuditLogger


@pytest.fixture()
def runner():
    return CliRunner()


@pytest.fixture()
def patched_roots(monkeypatch, tmp_path):
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


def _extract_project_id(output: str) -> str:
    m = re.search(r"Project ID\s+:\s+([^\r\n]+)", output)
    assert m, f"Project ID not found in output:\n{output}"
    return m.group(1).strip()


class TestProjectInitState:
    """init produces the correct initial phase, owner, and mode in shared state."""

    def test_init_creates_intake_phase(self, runner, patched_roots):
        result = runner.invoke(main, ["init", "integration-test"])
        assert result.exit_code == 0
        pid = _extract_project_id(result.output)

        status = runner.invoke(main, ["status", pid])
        assert status.exit_code == 0
        assert "Phase    : intake" in status.output
        assert "Status   : active" in status.output
        assert "Owner    : master_orchestrator" in status.output

    def test_init_starts_with_no_handoffs(self, runner, patched_roots):
        result = runner.invoke(main, ["init", "no-handoff-test"])
        pid = _extract_project_id(result.output)

        pending = runner.invoke(main, ["pending", pid])
        assert pending.exit_code == 0
        assert "No pending handoffs." in pending.output

    def test_lite_mode_init(self, runner, patched_roots):
        result = runner.invoke(main, ["init", "--mode=lite", "lite-proj"])
        assert result.exit_code == 0
        pid = _extract_project_id(result.output)

        status = runner.invoke(main, ["status", pid])
        assert "Mode     : lite" in status.output


class TestHandoffLifecycle:
    """Handoffs are reflected in pending, status, and prompt — then cleared on accept."""

    def test_pending_handoff_appears_in_pending(self, runner, patched_roots, tmp_path):
        result = runner.invoke(main, ["init", "handoff-lifecycle"])
        pid = _extract_project_id(result.output)

        projects_dir = patched_roots
        al = AuditLogger(log_path=projects_dir / pid / "audit.log")
        sm = SharedStateManager(pid, projects_root=projects_dir, audit_logger=al)
        he = HandoffEngine(audit_logger=al)

        ho = he.create(
            sm=sm,
            from_agent="master_orchestrator",
            to_agent="inquirer_agent",
            phase="intake",
            task_description="Conduct structured intake of the project brief",
            payload={"summary": "Intake task — gather clarifications"},
        )

        pending = runner.invoke(main, ["pending", pid])
        assert pending.exit_code == 0
        assert ho["handoff_id"] in pending.output
        assert "inquirer_agent" in pending.output
        assert "Conduct structured intake" in pending.output

    def test_pending_count_in_status(self, runner, patched_roots):
        result = runner.invoke(main, ["init", "status-pending-count"])
        pid = _extract_project_id(result.output)

        projects_dir = patched_roots
        al = AuditLogger(log_path=projects_dir / pid / "audit.log")
        sm = SharedStateManager(pid, projects_root=projects_dir, audit_logger=al)
        he = HandoffEngine(audit_logger=al)

        he.create(
            sm=sm,
            from_agent="master_orchestrator",
            to_agent="scribe_agent",
            phase="intake",
            task_description="Initialize project folder",
            payload={"summary": "Scribe task"},
        )

        status = runner.invoke(main, ["status", pid])
        assert "Pending handoffs : 1" in status.output

    def test_accepted_handoff_clears_from_pending(self, runner, patched_roots):
        result = runner.invoke(main, ["init", "accept-clears"])
        pid = _extract_project_id(result.output)

        projects_dir = patched_roots
        al = AuditLogger(log_path=projects_dir / pid / "audit.log")
        sm = SharedStateManager(pid, projects_root=projects_dir, audit_logger=al)
        he = HandoffEngine(audit_logger=al)

        ho = he.create(
            sm=sm,
            from_agent="master_orchestrator",
            to_agent="scribe_agent",
            phase="intake",
            task_description="Initialize project folder",
            payload={"summary": "Scribe task"},
        )
        he.accept(sm=sm, handoff_id=ho["handoff_id"])

        pending = runner.invoke(main, ["pending", pid])
        assert pending.exit_code == 0
        assert "No pending handoffs." in pending.output


class TestPromptAssembly:
    """prompt assembles real agent definition content based on actual project state."""

    def test_prompt_targets_master_on_fresh_project(self, runner, patched_roots):
        result = runner.invoke(main, ["init", "prompt-master"])
        pid = _extract_project_id(result.output)

        prompt = runner.invoke(main, ["prompt", pid])
        assert prompt.exit_code == 0
        assert "# Agent: master_orchestrator" in prompt.output
        assert pid in prompt.output

    def test_prompt_targets_pending_agent(self, runner, patched_roots):
        result = runner.invoke(main, ["init", "prompt-target-agent"])
        pid = _extract_project_id(result.output)

        projects_dir = patched_roots
        al = AuditLogger(log_path=projects_dir / pid / "audit.log")
        sm = SharedStateManager(pid, projects_root=projects_dir, audit_logger=al)
        he = HandoffEngine(audit_logger=al)

        he.create(
            sm=sm,
            from_agent="master_orchestrator",
            to_agent="inquirer_agent",
            phase="intake",
            task_description="Conduct intake",
            payload={"summary": "Intake task"},
        )

        prompt = runner.invoke(main, ["prompt", pid])
        assert prompt.exit_code == 0
        assert "# Agent: inquirer_agent" in prompt.output

    def test_explicit_agent_override(self, runner, patched_roots):
        result = runner.invoke(main, ["init", "prompt-explicit"])
        pid = _extract_project_id(result.output)

        prompt = runner.invoke(main, ["prompt", pid, "scribe_agent"])
        assert prompt.exit_code == 0
        assert "# Agent: scribe_agent" in prompt.output

    def test_explicit_agent_alias_override(self, runner, patched_roots):
        result = runner.invoke(main, ["init", "prompt-explicit-alias"])
        pid = _extract_project_id(result.output)

        prompt = runner.invoke(main, ["prompt", pid, "hr"])
        assert prompt.exit_code == 0
        assert "# Agent: hr_agent" in prompt.output

    def test_prompt_contains_project_state_section(self, runner, patched_roots):
        result = runner.invoke(main, ["init", "prompt-state-section"])
        pid = _extract_project_id(result.output)

        prompt = runner.invoke(main, ["prompt", pid])
        assert prompt.exit_code == 0
        # Prompt must include injected project context — not just agent definition
        assert pid in prompt.output
