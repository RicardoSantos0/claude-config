"""
Unit Tests — Lite Mode

Tests mas init --mode=lite creates the correct state,
mas status shows [lite], and spawn is blocked in lite projects.
"""
import pytest
from pathlib import Path

from core.engine.shared_state_manager import (
    SharedStateManager,
    create_initial_state,
    LITE_PHASES,
    STANDARD_PHASES,
)
from core.engine.spawn_policy import SpawnPolicyEngine, DENY


# ---------------------------------------------------------------------------
# create_initial_state
# ---------------------------------------------------------------------------

class TestCreateInitialState:

    def test_standard_mode_default(self):
        state = create_initial_state("proj-1", "req-1")
        assert state["workflow"]["mode"] == "standard"

    def test_lite_mode_sets_flag(self):
        state = create_initial_state("proj-1", "req-1", mode="lite")
        assert state["workflow"]["mode"] == "lite"

    def test_invalid_mode_falls_back_to_standard(self):
        state = create_initial_state("proj-1", "req-1", mode="turbo")
        assert state["workflow"]["mode"] == "standard"

    def test_lite_phases_constant(self):
        assert LITE_PHASES == ("intake", "execution", "closed")

    def test_standard_phases_constant(self):
        assert len(STANDARD_PHASES) == 9
        assert STANDARD_PHASES[0] == "intake"
        assert STANDARD_PHASES[-1] == "closed"


# ---------------------------------------------------------------------------
# SharedStateManager.initialize
# ---------------------------------------------------------------------------

class TestInitialize:

    def test_lite_mode_persisted(self, tmp_path):
        sm = SharedStateManager("proj-lite-test", projects_root=tmp_path)
        sm.initialize(request_id="req-001", mode="lite")
        state = sm.load()
        assert state["workflow"]["mode"] == "lite"

    def test_standard_mode_persisted(self, tmp_path):
        sm = SharedStateManager("proj-std-test", projects_root=tmp_path)
        sm.initialize(request_id="req-001", mode="standard")
        state = sm.load()
        assert state["workflow"]["mode"] == "standard"

    def test_default_is_standard(self, tmp_path):
        sm = SharedStateManager("proj-default-test", projects_root=tmp_path)
        sm.initialize(request_id="req-001")
        state = sm.load()
        assert state["workflow"]["mode"] == "standard"


# ---------------------------------------------------------------------------
# Spawn blocked in lite mode
# ---------------------------------------------------------------------------

class TestLiteModeBlocksSpawn:

    def test_spawn_denied_in_lite_project(self, tmp_path):
        """Spawn must be denied when workflow.mode == 'lite'."""
        sm = SharedStateManager("proj-lite-spawn", projects_root=tmp_path)
        sm.initialize(request_id="req-001", mode="lite")

        engine = SpawnPolicyEngine()
        spawn_request = {
            "spawn_request_id": "sr-001",
            "requested_by": "master_orchestrator",
            "agent_name": "new_agent",
            "phase": "execution",
            "gap_certificate_id": "gap-001",
            "task_description": "Handle X",
            "bounded": True,
            "recurring": True,
            "verifiable": True,
            "no_existing_match": True,
        }
        gap_cert = {
            "gap_id": "gap-001",
            "master_approved": True,
            "approved_by": "master_orchestrator",
        }
        registry_data = {"agents": []}

        result = engine.validate(
            spawn_request,
            registry_data,
            sm.project_dir,
            gap_cert=gap_cert,
        )
        assert result.decision == DENY
        assert any("LITE_MODE_NO_SPAWN" == v.code
                   for v in result.all_violations)

    def test_spawn_allowed_in_standard_project(self, tmp_path):
        """Spawn policy should NOT be blocked by lite check in standard mode."""
        sm = SharedStateManager("proj-std-spawn", projects_root=tmp_path)
        sm.initialize(request_id="req-001", mode="standard")

        engine = SpawnPolicyEngine()
        spawn_request = {
            "spawn_request_id": "sr-002",
            "requested_by": "master_orchestrator",
            "agent_name": "new_agent",
            "phase": "execution",
            "gap_certificate_id": "gap-001",
            "task_description": "Handle X",
            "bounded": True,
            "recurring": True,
            "verifiable": True,
            "no_existing_match": True,
        }
        gap_cert = {
            "gap_id": "gap-001",
            "master_approved": True,
            "approved_by": "master_orchestrator",
        }
        registry_data = {"agents": []}

        result = engine.validate(
            spawn_request,
            registry_data,
            sm.project_dir,
            gap_cert=gap_cert,
        )
        # Not blocked by lite check — standard policy applies
        assert not any("LITE_MODE_NO_SPAWN" == v.code
                       for v in result.all_violations)
