"""
End-to-end integration test: checkpoint → session break → resume flow.

Simulates:
1. A project running through intake and specification phases
2. A session break (state persisted on disk, objects discarded)
3. Resume: read checkpoint, reconstruct state from disk, verify continuity
4. Continue: advance through planning phase, verify checkpoint updated
"""

from pathlib import Path
import pytest
import yaml

import core.shared_state_manager as ssm_mod
import core.checkpoint_writer as cw_mod

from core.shared_state_manager import SharedStateManager
from core.handoff_engine import HandoffEngine
from core.checkpoint_writer import CheckpointWriter


# ---------------------------------------------------------------------------
# Fixture: isolated project environment
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def patch_roots(tmp_path, monkeypatch):
    monkeypatch.setattr(ssm_mod, "ROOT", tmp_path)
    monkeypatch.setattr(cw_mod, "ROOT", tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sim_create_handoff(engine, sm, frm, to, phase, task, summary):
    return engine.create(sm, from_agent=frm, to_agent=to, phase=phase,
                         task_description=task, payload={"summary": summary})


def _sim_accept(engine, sm, handoff_id):
    engine.accept(sm, handoff_id)


def _reload_sm(tmp_path, project_id):
    """Simulate a session break by creating a fresh SharedStateManager from disk."""
    sm = SharedStateManager(project_id)
    return sm


# ---------------------------------------------------------------------------
# Test: full checkpoint → break → resume cycle
# ---------------------------------------------------------------------------

class TestCheckpointResumeE2E:
    def test_full_cycle(self, tmp_path):
        """
        Phase 1: Run intake. Verify checkpoint after each handoff.
        Phase 2: Simulate session break (discard objects).
        Phase 3: Resume from disk — verify state continuity.
        Phase 4: Advance to specification. Verify checkpoint updated.
        """
        project_id = "proj-e2e-resume-001"
        engine = HandoffEngine()

        # ---- Phase 1: Intake ----
        sm = SharedStateManager(project_id)
        sm.initialize(request_id="req-e2e-001")

        h1 = _sim_create_handoff(engine, sm, "master_orchestrator", "scribe_agent",
                                 "intake", "Initialize project folder",
                                 "Folder created at mas/projects/proj-e2e-resume-001")
        _sim_accept(engine, sm, h1["handoff_id"])

        checkpoint_path = tmp_path / "projects" / project_id / "CHECKPOINT.md"
        assert checkpoint_path.exists()
        c1 = checkpoint_path.read_text(encoding="utf-8")
        assert h1["handoff_id"] in c1
        assert "intake" in c1

        h2 = _sim_create_handoff(engine, sm, "master_orchestrator", "inquirer_agent",
                                 "intake", "Gather requirements",
                                 "Brief captured. Requirements documented.")
        _sim_accept(engine, sm, h2["handoff_id"])

        c2 = checkpoint_path.read_text(encoding="utf-8")
        assert h2["handoff_id"] in c2  # last handoff updated

        # ---- Phase 2: Simulate session break ----
        # Discard all in-memory objects — only disk state persists
        del sm, engine

        # ---- Phase 3: Resume from disk ----
        sm_resumed = _reload_sm(tmp_path, project_id)
        state = sm_resumed.load()

        # Verify state integrity after reload
        assert state["core_identity"]["project_id"] == project_id
        assert state["core_identity"]["current_phase"] == "intake"
        assert len(state["workflow"]["handoff_history"]) == 2

        # Checkpoint still accurate
        c3 = checkpoint_path.read_text(encoding="utf-8")
        assert h2["handoff_id"] in c3
        assert "_No pending handoffs._" in c3

        # ---- Phase 4: Continue — advance to specification ----
        engine_resumed = HandoffEngine()

        # Complete intake phase
        sm_resumed.append("master_orchestrator", "workflow", "completed_phases", "intake")
        sm_resumed.write("master_orchestrator", "core_identity", "current_phase", "specification")

        c4 = checkpoint_path.read_text(encoding="utf-8")
        assert "~~intake~~" in c4
        assert "**specification**" in c4

        # New handoff in specification phase
        h3 = _sim_create_handoff(engine_resumed, sm_resumed,
                                 "master_orchestrator", "product_manager_agent",
                                 "specification", "Write product plan",
                                 "Product plan outline started")
        _sim_accept(engine_resumed, sm_resumed, h3["handoff_id"])

        c5 = checkpoint_path.read_text(encoding="utf-8")
        assert h3["handoff_id"] in c5
        assert "product_manager_agent" in c5
        assert len(sm_resumed.load()["workflow"]["handoff_history"]) == 3

    def test_pending_handoff_survives_break(self, tmp_path):
        """
        A handoff created but not accepted before session break must still
        appear as pending after reload.
        """
        project_id = "proj-e2e-resume-002"
        engine = HandoffEngine()

        sm = SharedStateManager(project_id)
        sm.initialize(request_id="req-e2e-002")

        h = _sim_create_handoff(engine, sm, "master_orchestrator", "hr_agent",
                                "capability_discovery", "Scan capability registry",
                                "Checking for gaps")
        # NOT accepted — simulate break here

        checkpoint_path = tmp_path / "projects" / project_id / "CHECKPOINT.md"
        cw = CheckpointWriter(project_id)
        cw.write()

        content = checkpoint_path.read_text(encoding="utf-8")
        assert h["handoff_id"] in content
        assert "_No pending handoffs._" not in content

        # After break: reload, verify pending handoff still there
        sm2 = _reload_sm(tmp_path, project_id)
        state = sm2.load()
        history = state["workflow"]["handoff_history"]
        pending = [x for x in history if x.get("acceptance", {}).get("status") == "pending"]
        assert len(pending) == 1
        assert pending[0]["handoff_id"] == h["handoff_id"]

    def test_checkpoint_always_reflects_latest_state(self, tmp_path):
        """
        After multiple writes, CHECKPOINT.md always reflects the latest state,
        not a historical snapshot.
        """
        project_id = "proj-e2e-resume-003"
        engine = HandoffEngine()

        sm = SharedStateManager(project_id)
        sm.initialize(request_id="req-e2e-003")

        checkpoint_path = tmp_path / "projects" / project_id / "CHECKPOINT.md"

        phases = ["intake", "specification", "planning", "capability_discovery", "execution"]
        for i, phase in enumerate(phases):
            sm.write("master_orchestrator", "core_identity", "current_phase", phase)
            content = checkpoint_path.read_text(encoding="utf-8")
            assert f"**{phase}**" in content
            # Verify previous phase not shown as current
            if i > 0:
                prev = phases[i - 1]
                assert f"**{prev}**" not in content


# ---------------------------------------------------------------------------
# Test: checkpoint is non-fatal on error
# ---------------------------------------------------------------------------

class TestCheckpointNonFatal:
    def test_checkpoint_failure_does_not_block_handoff(self, tmp_path, monkeypatch):
        """
        If checkpoint writing fails (e.g., disk full), handoff must still succeed.
        """
        project_id = "proj-e2e-nonfatal-001"

        sm = SharedStateManager(project_id)
        sm.initialize(request_id="req-nonfatal-001")

        # Monkeypatch CheckpointWriter.write to raise
        import core.checkpoint_writer as cw_module
        original_write = cw_module.CheckpointWriter.write

        def bad_write(self):
            raise OSError("disk full simulation")

        monkeypatch.setattr(cw_module.CheckpointWriter, "write", bad_write)

        engine = HandoffEngine()
        h = engine.create(sm, "master_orchestrator", "scribe_agent",
                          "intake", "Init folder", {"summary": "Starting"})

        # This must not raise
        result = engine.accept(sm, h["handoff_id"])
        assert result is True

    def test_phase_write_failure_does_not_block_state_write(self, tmp_path, monkeypatch):
        """
        If checkpoint writing fails during a phase transition write, the state
        write must still succeed.
        """
        project_id = "proj-e2e-nonfatal-002"

        sm = SharedStateManager(project_id)
        sm.initialize(request_id="req-nonfatal-002")

        import core.checkpoint_writer as cw_module

        def bad_write(self):
            raise OSError("no space left")

        monkeypatch.setattr(cw_module.CheckpointWriter, "write", bad_write)

        result = sm.write("master_orchestrator", "core_identity", "current_phase", "specification")
        assert result.success is True

        # State was actually written
        reloaded = sm.load()
        assert reloaded["core_identity"]["current_phase"] == "specification"
