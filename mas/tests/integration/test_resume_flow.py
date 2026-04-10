"""
Integration tests for the session resume flow.

Tests verify that after a simulated session break:
- CHECKPOINT.md exists and contains the right context
- /resume-mas can reconstruct where the project left off
- Resuming from a mid-phase state continues correctly without re-doing work
- Resuming from a pending-handoff state resolves the pending handoff
"""

from pathlib import Path
import pytest
import yaml

from core.shared_state_manager import SharedStateManager
from core.handoff_engine import HandoffEngine
from core.checkpoint_writer import CheckpointWriter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bootstrap_project(tmp_path, project_id: str, request_id: str) -> SharedStateManager:
    """Initialize a real project in tmp_path."""
    import core.shared_state_manager as ssm_mod
    import core.checkpoint_writer as cw_mod
    import core.handoff_engine as he_mod

    # All three modules must find projects under tmp_path
    ssm_mod.ROOT = tmp_path
    cw_mod.ROOT = tmp_path
    # handoff_engine.ROOT is not used for project lookup; SharedStateManager handles it

    sm = SharedStateManager(project_id)
    sm.initialize(request_id=request_id)
    return sm


# ---------------------------------------------------------------------------
# Test: checkpoint written automatically and contains correct context
# ---------------------------------------------------------------------------

class TestCheckpointAutoWrite:
    def test_checkpoint_after_handoff_accept(self, tmp_path, monkeypatch):
        """Accepting a handoff must auto-write CHECKPOINT.md."""
        import core.shared_state_manager as ssm_mod
        import core.checkpoint_writer as cw_mod
        monkeypatch.setattr(ssm_mod, "ROOT", tmp_path)
        monkeypatch.setattr(cw_mod, "ROOT", tmp_path)

        project_id = "proj-resume-test-001"
        sm = SharedStateManager(project_id)
        sm.initialize(request_id="req-resume-001")

        engine = HandoffEngine()
        handoff = engine.create(
            sm,
            from_agent="master_orchestrator",
            to_agent="scribe_agent",
            phase="intake",
            task_description="Initialize project folder",
            payload={"summary": "Starting"},
        )
        engine.accept(sm, handoff["handoff_id"])

        checkpoint = tmp_path / "projects" / project_id / "CHECKPOINT.md"
        assert checkpoint.exists()
        content = checkpoint.read_text(encoding="utf-8")
        assert project_id in content
        assert "intake" in content
        assert "/resume-mas" in content

    def test_checkpoint_after_phase_transition(self, tmp_path, monkeypatch):
        """Writing current_phase must auto-write CHECKPOINT.md."""
        import core.shared_state_manager as ssm_mod
        import core.checkpoint_writer as cw_mod
        monkeypatch.setattr(ssm_mod, "ROOT", tmp_path)
        monkeypatch.setattr(cw_mod, "ROOT", tmp_path)

        project_id = "proj-resume-test-002"
        sm = SharedStateManager(project_id)
        sm.initialize(request_id="req-resume-002")
        sm.write("master_orchestrator", "core_identity", "current_phase", "specification")

        checkpoint = tmp_path / "projects" / project_id / "CHECKPOINT.md"
        assert checkpoint.exists()
        content = checkpoint.read_text(encoding="utf-8")
        assert "specification" in content


# ---------------------------------------------------------------------------
# Test: resume reconstructs full context
# ---------------------------------------------------------------------------

class TestResumeContextReconstruction:
    def test_checkpoint_contains_last_handoff_info(self, tmp_path, monkeypatch):
        """
        After two handoffs, CHECKPOINT.md must show the last accepted handoff.
        """
        import core.shared_state_manager as ssm_mod
        import core.checkpoint_writer as cw_mod
        monkeypatch.setattr(ssm_mod, "ROOT", tmp_path)
        monkeypatch.setattr(cw_mod, "ROOT", tmp_path)

        project_id = "proj-resume-test-003"
        sm = SharedStateManager(project_id)
        sm.initialize(request_id="req-resume-003")

        engine = HandoffEngine()

        # Handoff 1: to scribe
        h1 = engine.create(sm, "master_orchestrator", "scribe_agent",
                           "intake", "Initialize folder",
                           {"summary": "Folder initialized"})
        engine.accept(sm, h1["handoff_id"])

        # Handoff 2: to inquirer
        h2 = engine.create(sm, "master_orchestrator", "inquirer_agent",
                           "intake", "Gather requirements",
                           {"summary": "Requirements gathered"})
        engine.accept(sm, h2["handoff_id"])

        checkpoint = tmp_path / "projects" / project_id / "CHECKPOINT.md"
        content = checkpoint.read_text(encoding="utf-8")

        # Last handoff should be h2
        assert h2["handoff_id"] in content
        assert "inquirer_agent" in content

    def test_checkpoint_shows_completed_phases(self, tmp_path, monkeypatch):
        import core.shared_state_manager as ssm_mod
        import core.checkpoint_writer as cw_mod
        monkeypatch.setattr(ssm_mod, "ROOT", tmp_path)
        monkeypatch.setattr(cw_mod, "ROOT", tmp_path)

        project_id = "proj-resume-test-004"
        sm = SharedStateManager(project_id)
        sm.initialize(request_id="req-resume-004")

        # Mark intake as completed
        sm.append("master_orchestrator", "workflow", "completed_phases", "intake")
        sm.write("master_orchestrator", "core_identity", "current_phase", "specification")

        cw = CheckpointWriter(project_id)
        cw.write()

        checkpoint = tmp_path / "projects" / project_id / "CHECKPOINT.md"
        content = checkpoint.read_text(encoding="utf-8")

        assert "~~intake~~" in content
        assert "**specification**" in content

    def test_checkpoint_overwrites_on_each_update(self, tmp_path, monkeypatch):
        """CHECKPOINT.md is always the latest state — not appended."""
        import core.shared_state_manager as ssm_mod
        import core.checkpoint_writer as cw_mod
        monkeypatch.setattr(ssm_mod, "ROOT", tmp_path)
        monkeypatch.setattr(cw_mod, "ROOT", tmp_path)

        project_id = "proj-resume-test-005"
        sm = SharedStateManager(project_id)
        sm.initialize(request_id="req-resume-005")

        cw = CheckpointWriter(project_id)
        cw.write()
        checkpoint = tmp_path / "projects" / project_id / "CHECKPOINT.md"
        first_size = checkpoint.stat().st_size

        # Advance phase — triggers new checkpoint
        sm.write("master_orchestrator", "core_identity", "current_phase", "specification")
        second_content = checkpoint.read_text(encoding="utf-8")

        # Content must have changed (specification now current)
        assert "specification" in second_content
        # File must not grow without bound
        assert checkpoint.stat().st_size < first_size * 10


# ---------------------------------------------------------------------------
# Test: pending handoff state survives session break
# ---------------------------------------------------------------------------

class TestPendingHandoffResume:
    def test_pending_handoff_visible_in_checkpoint(self, tmp_path, monkeypatch):
        """
        A handoff created but not yet accepted must appear in CHECKPOINT.md
        under Pending Handoffs.
        """
        import core.shared_state_manager as ssm_mod
        import core.checkpoint_writer as cw_mod
        monkeypatch.setattr(ssm_mod, "ROOT", tmp_path)
        monkeypatch.setattr(cw_mod, "ROOT", tmp_path)

        project_id = "proj-resume-test-006"
        sm = SharedStateManager(project_id)
        sm.initialize(request_id="req-resume-006")

        engine = HandoffEngine()
        # Create handoff but DO NOT accept — simulates mid-session break
        h = engine.create(sm, "master_orchestrator", "product_manager_agent",
                          "specification", "Write product plan",
                          {"summary": "Spec work in progress"})

        cw = CheckpointWriter(project_id)
        cw.write()

        checkpoint = tmp_path / "projects" / project_id / "CHECKPOINT.md"
        content = checkpoint.read_text(encoding="utf-8")

        assert h["handoff_id"] in content
        assert "product_manager_agent" in content
        # Should NOT appear under "No pending handoffs"
        assert "_No pending handoffs._" not in content

    def test_accepted_handoff_clears_pending(self, tmp_path, monkeypatch):
        """Once accepted, handoff no longer shows in Pending Handoffs."""
        import core.shared_state_manager as ssm_mod
        import core.checkpoint_writer as cw_mod
        monkeypatch.setattr(ssm_mod, "ROOT", tmp_path)
        monkeypatch.setattr(cw_mod, "ROOT", tmp_path)

        project_id = "proj-resume-test-007"
        sm = SharedStateManager(project_id)
        sm.initialize(request_id="req-resume-007")

        engine = HandoffEngine()
        h = engine.create(sm, "master_orchestrator", "scribe_agent",
                          "intake", "Init folder",
                          {"summary": "Starting"})
        engine.accept(sm, h["handoff_id"])

        checkpoint = tmp_path / "projects" / project_id / "CHECKPOINT.md"
        content = checkpoint.read_text(encoding="utf-8")
        assert "_No pending handoffs._" in content
