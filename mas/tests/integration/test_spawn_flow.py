"""
Integration Test — Spawn Flow
Tests the full spawn pipeline from gap certificate to agent package:
  1. HR produces a gap certificate
  2. Master approves it and issues a spawn request
  3. Spawner validates policy
  4. Spawner builds agent package
  5. Spawner returns handoff to Master
  6. Package files are accessible and correct
  7. Governance: spawned agents cannot spawn; limits enforced

Tests Python infrastructure only — no live LLM calls.
"""
import pytest
import yaml
from pathlib import Path
from core.engine.shared_state_manager import SharedStateManager
from core.engine.handoff_engine import HandoffEngine
from core.engine.capability_registry import CapabilityRegistry
from core.spawn_policy import (
    SpawnPolicyEngine,
    build_agent_package,
    record_spawn,
    _load_history,
    DENY,
    DRAFT,
    MAX_SPAWNS_PER_PROJECT,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def project_id():
    return "proj-20260409-spawn-001"


@pytest.fixture
def projects_root(tmp_path):
    return tmp_path / "projects_root"


@pytest.fixture
def project_dir(projects_root, project_id):
    d = projects_root / project_id
    d.mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture
def sm(projects_root, project_id):
    manager = SharedStateManager(project_id, projects_root=projects_root)
    manager.initialize(request_id="req-spawn-001")
    return manager


@pytest.fixture
def engine():
    return HandoffEngine()


@pytest.fixture
def spawn_engine():
    return SpawnPolicyEngine()


@pytest.fixture
def registry_dir(tmp_path):
    d = tmp_path / "roster"
    d.mkdir()
    # Minimal registry with core agents
    index = {
        "registry": {
            "version": "1.0.0",
            "agents": [
                {
                    "agent_id": "master_orchestrator",
                    "name": "Master Orchestrator",
                    "version": "1.0.0",
                    "trust_tier": "T0_core",
                    "status": "active",
                    "capabilities": ["orchestration", "governance"],
                    "performance_score": None,
                    "spawn_origin": None,
                    "created_at": "2026-04-09T00:00:00+00:00",
                },
                {
                    "agent_id": "hr_agent",
                    "name": "HR Agent",
                    "version": "1.0.0",
                    "trust_tier": "T1_established",
                    "status": "active",
                    "capabilities": ["capability-discovery", "gap-certification"],
                    "performance_score": None,
                    "spawn_origin": None,
                    "created_at": "2026-04-09T00:00:00+00:00",
                },
            ],
        },
        "counts": {
            "active_agents": 2,
            "active_skills": 0,
            "retired_agents": 0,
            "spawned_total": 0,
        },
    }
    with open(d / "registry_index.yaml", "w") as f:
        yaml.dump(index, f, default_flow_style=False)
    return d


@pytest.fixture
def registry_data(registry_dir):
    with open(registry_dir / "registry_index.yaml") as f:
        return yaml.safe_load(f)


@pytest.fixture
def gap_cert(project_dir):
    """Write and return an approved gap certificate."""
    d = project_dir / "hr"
    d.mkdir(parents=True, exist_ok=True)
    cert = {
        "certificate_id": "gap-cert-spawn-001",
        "project_id": "proj-20260409-spawn-001",
        "status": "approved",
        "approval_status": "master_approved",
        "certified_by": "hr_agent",
        "required_capabilities": ["reporting", "salesforce-integration"],
        "best_match_score": 45.0,
        "rationale": "No roster agent covers salesforce-integration above 80%.",
    }
    with open(d / "gap-cert-spawn-001.yaml", "w") as f:
        yaml.dump(cert, f)
    return cert


@pytest.fixture
def spawn_request(gap_cert):
    return {
        "request_id": "spawn-req-20260409-001",
        "project_id": "proj-20260409-spawn-001",
        "gap_certificate_id": "gap-cert-spawn-001",
        "requested_by": "hr_agent",
        "master_approval": True,
        "agent_purpose": "Generate weekly sales reports from Salesforce data",
        "required_inputs": ["salesforce_export.json", "report_period"],
        "required_outputs": ["weekly_report.yaml", "executive_summary.md"],
        "allowed_tools": ["read", "search"],
        "scope": "project_scoped",
        "base_template": "analysis_agent",
        "phase": "execution",
        "worthiness": {
            "bounded": True,
            "recurring": True,
            "verifiable": True,
            "no_existing_match": True,
        },
    }


# ---------------------------------------------------------------------------
# Helper: simulate spawner
# ---------------------------------------------------------------------------

def simulate_spawner(
    sm: SharedStateManager,
    handoff_engine: HandoffEngine,
    spawn_engine: SpawnPolicyEngine,
    master_handoff: dict,
    spawn_request: dict,
    registry_data: dict,
    project_dir: Path,
    gap_cert: dict,
) -> dict:
    """Simulate the Spawner Agent processing a spawn request."""
    handoff_id = master_handoff["handoff_id"]
    phase = spawn_request.get("phase", "execution")

    # 1. Accept handoff
    handoff_engine.accept(sm, handoff_id)

    # 2. Validate policy
    result = spawn_engine.validate(
        spawn_request, registry_data, project_dir,
        gap_cert=gap_cert, phase=phase
    )

    if result.decision == DENY:
        # Return denial to Master
        return handoff_engine.create(
            sm,
            from_agent="spawner_agent",
            to_agent="master_orchestrator",
            phase=phase,
            task_description="Spawn request denied",
            payload={
                "summary": f"Spawn denied. Violations: {[v.code for v in result.all_violations]}",
                "artifacts_produced": [],
                "decisions_made": [{"decision": "spawn_denied", "rationale": result.rationale}],
                "open_questions": [],
                "constraints_for_next": [],
                "shared_state_fields_modified": [],
                "spawn_decision": DENY,
                "violations": [v.code for v in result.all_violations],
            },
        )

    # 3. Build package
    pkg_dir = build_agent_package(spawn_request, project_dir)

    # 4. Record spawn
    record_spawn(project_dir, spawn_request["request_id"], pkg_dir.name, phase, DRAFT, str(pkg_dir))

    # 5. Return to Master
    with open(pkg_dir / "manifest.yaml") as f:
        manifest = yaml.safe_load(f)

    return handoff_engine.create(
        sm,
        from_agent="spawner_agent",
        to_agent="master_orchestrator",
        phase=phase,
        task_description="Deliver draft agent package",
        payload={
            "summary": (
                f"Draft agent package ready for review. "
                f"Agent ID: {manifest['agent_id']}. "
                f"Package at: {pkg_dir}. "
                f"Human review required before activation."
            ),
            "artifacts_produced": [str(pkg_dir)],
            "decisions_made": [{"decision": "spawn_draft_only", "rationale": result.rationale}],
            "open_questions": [],
            "constraints_for_next": ["Human must review before activating agent"],
            "shared_state_fields_modified": [],
            "spawn_decision": DRAFT,
            "agent_id": manifest["agent_id"],
            "package_path": str(pkg_dir),
            "base_template_used": spawn_request.get("base_template"),
            "capabilities": manifest.get("capabilities", []),
            "human_review_required": True,
        },
    )


# ---------------------------------------------------------------------------
# Tests: Happy path
# ---------------------------------------------------------------------------

class TestSpawnHappyPath:

    def test_master_sends_spawn_request(self, sm, engine, gap_cert):
        handoff = engine.create(
            sm,
            from_agent="master_orchestrator",
            to_agent="spawner_agent",
            phase="execution",
            task_description="Design new agent",
            payload={
                "summary": "Gap certified. Please design the reporting agent.",
                "artifacts_produced": [],
                "decisions_made": [],
                "open_questions": [],
                "constraints_for_next": [],
                "shared_state_fields_modified": [],
                "gap_certificate_id": "gap-cert-spawn-001",
            },
        )
        assert handoff["to_agent"] == "spawner_agent"
        assert handoff["phase"] == "execution"

    def test_full_spawn_cycle_returns_draft_decision(
        self, sm, engine, spawn_engine, spawn_request, registry_data, project_dir, gap_cert
    ):
        master_handoff = engine.create(
            sm,
            from_agent="master_orchestrator",
            to_agent="spawner_agent",
            phase="execution",
            task_description="Design new agent",
            payload={
                "summary": "Gap certified. Design agent.",
                "artifacts_produced": [],
                "decisions_made": [],
                "open_questions": [],
                "constraints_for_next": [],
                "shared_state_fields_modified": [],
            },
        )

        spawn_return = simulate_spawner(
            sm, engine, spawn_engine, master_handoff,
            spawn_request, registry_data, project_dir, gap_cert
        )

        assert spawn_return["from_agent"] == "spawner_agent"
        assert spawn_return["to_agent"] == "master_orchestrator"
        assert spawn_return["payload"]["spawn_decision"] == DRAFT

    def test_package_directory_exists_after_spawn(
        self, sm, engine, spawn_engine, spawn_request, registry_data, project_dir, gap_cert
    ):
        master_handoff = engine.create(
            sm, from_agent="master_orchestrator", to_agent="spawner_agent",
            phase="execution", task_description="Design",
            payload={"summary": "Go.", "artifacts_produced": [], "decisions_made": [],
                     "open_questions": [], "constraints_for_next": [], "shared_state_fields_modified": []},
        )

        spawn_return = simulate_spawner(
            sm, engine, spawn_engine, master_handoff,
            spawn_request, registry_data, project_dir, gap_cert
        )

        pkg_path = Path(spawn_return["payload"]["package_path"])
        assert pkg_path.exists()

    def test_all_package_files_present(
        self, sm, engine, spawn_engine, spawn_request, registry_data, project_dir, gap_cert
    ):
        master_handoff = engine.create(
            sm, from_agent="master_orchestrator", to_agent="spawner_agent",
            phase="execution", task_description="Design",
            payload={"summary": "Go.", "artifacts_produced": [], "decisions_made": [],
                     "open_questions": [], "constraints_for_next": [], "shared_state_fields_modified": []},
        )

        spawn_return = simulate_spawner(
            sm, engine, spawn_engine, master_handoff,
            spawn_request, registry_data, project_dir, gap_cert
        )

        pkg_path = Path(spawn_return["payload"]["package_path"])
        for fname in ["manifest.yaml", "agent_definition.md", "tool_contract.yaml",
                      "verification_plan.yaml", "behavioral_contract.yaml"]:
            assert (pkg_path / fname).exists(), f"Missing file: {fname}"

    def test_spawn_history_recorded(
        self, sm, engine, spawn_engine, spawn_request, registry_data, project_dir, gap_cert
    ):
        master_handoff = engine.create(
            sm, from_agent="master_orchestrator", to_agent="spawner_agent",
            phase="execution", task_description="Design",
            payload={"summary": "Go.", "artifacts_produced": [], "decisions_made": [],
                     "open_questions": [], "constraints_for_next": [], "shared_state_fields_modified": []},
        )

        simulate_spawner(
            sm, engine, spawn_engine, master_handoff,
            spawn_request, registry_data, project_dir, gap_cert
        )

        history = _load_history(project_dir)
        assert len(history["spawns"]) == 1
        assert history["spawns"][0]["decision"] == DRAFT

    def test_master_accepts_spawn_return(
        self, sm, engine, spawn_engine, spawn_request, registry_data, project_dir, gap_cert
    ):
        master_handoff = engine.create(
            sm, from_agent="master_orchestrator", to_agent="spawner_agent",
            phase="execution", task_description="Design",
            payload={"summary": "Go.", "artifacts_produced": [], "decisions_made": [],
                     "open_questions": [], "constraints_for_next": [], "shared_state_fields_modified": []},
        )

        spawn_return = simulate_spawner(
            sm, engine, spawn_engine, master_handoff,
            spawn_request, registry_data, project_dir, gap_cert
        )

        engine.accept(sm, spawn_return["handoff_id"])
        pending = engine.get_pending(sm)
        assert len(pending) == 0

    def test_handoff_count_in_spawn_phase(
        self, sm, engine, spawn_engine, spawn_request, registry_data, project_dir, gap_cert
    ):
        master_handoff = engine.create(
            sm, from_agent="master_orchestrator", to_agent="spawner_agent",
            phase="execution", task_description="Design",
            payload={"summary": "Go.", "artifacts_produced": [], "decisions_made": [],
                     "open_questions": [], "constraints_for_next": [], "shared_state_fields_modified": []},
        )

        spawn_return = simulate_spawner(
            sm, engine, spawn_engine, master_handoff,
            spawn_request, registry_data, project_dir, gap_cert
        )

        engine.accept(sm, spawn_return["handoff_id"])
        history = sm.read("workflow.handoff_history")
        assert len(history) == 2


# ---------------------------------------------------------------------------
# Tests: Policy enforcement
# ---------------------------------------------------------------------------

class TestSpawnPolicyEnforcement:

    def test_missing_cert_returns_deny(
        self, sm, engine, spawn_engine, registry_data, project_dir
    ):
        bad_request = {
            "request_id": "spawn-bad-001",
            "gap_certificate_id": "",
            "requested_by": "hr_agent",
            "master_approval": False,
            "agent_purpose": "Do something",
            "required_inputs": [],
            "required_outputs": [],
            "allowed_tools": [],
            "scope": "project_scoped",
            "phase": "execution",
        }

        master_handoff = engine.create(
            sm, from_agent="master_orchestrator", to_agent="spawner_agent",
            phase="execution", task_description="Design",
            payload={"summary": "Go.", "artifacts_produced": [], "decisions_made": [],
                     "open_questions": [], "constraints_for_next": [], "shared_state_fields_modified": []},
        )

        spawn_return = simulate_spawner(
            sm, engine, spawn_engine, master_handoff,
            bad_request, registry_data, project_dir, gap_cert=None
        )

        assert spawn_return["payload"]["spawn_decision"] == DENY

    def test_project_limit_enforced(
        self, sm, engine, spawn_engine, spawn_request, registry_data, project_dir, gap_cert
    ):
        # Fill up project spawn history
        for i in range(MAX_SPAWNS_PER_PROJECT):
            record_spawn(project_dir, f"req-{i}", f"filler_agent_{i}", f"phase_{i}", DRAFT)

        master_handoff = engine.create(
            sm, from_agent="master_orchestrator", to_agent="spawner_agent",
            phase="new_phase", task_description="Design",
            payload={"summary": "Go.", "artifacts_produced": [], "decisions_made": [],
                     "open_questions": [], "constraints_for_next": [], "shared_state_fields_modified": []},
        )

        spawn_return = simulate_spawner(
            sm, engine, spawn_engine, master_handoff,
            spawn_request, registry_data, project_dir, gap_cert
        )

        assert spawn_return["payload"]["spawn_decision"] == DENY
        assert "LIMIT_PROJECT_EXCEEDED" in spawn_return["payload"]["violations"]

    def test_phase_limit_enforced(
        self, sm, engine, spawn_engine, spawn_request, registry_data, project_dir, gap_cert
    ):
        record_spawn(project_dir, "req-001", "agent_a", "execution", DRAFT)

        master_handoff = engine.create(
            sm, from_agent="master_orchestrator", to_agent="spawner_agent",
            phase="execution", task_description="Design",
            payload={"summary": "Go.", "artifacts_produced": [], "decisions_made": [],
                     "open_questions": [], "constraints_for_next": [], "shared_state_fields_modified": []},
        )

        spawn_return = simulate_spawner(
            sm, engine, spawn_engine, master_handoff,
            dict(spawn_request, phase="execution"),
            registry_data, project_dir, gap_cert
        )

        assert spawn_return["payload"]["spawn_decision"] == DENY
        assert "LIMIT_PHASE_EXCEEDED" in spawn_return["payload"]["violations"]

    def test_no_governance_violations_on_happy_path(
        self, sm, engine, spawn_engine, spawn_request, registry_data, project_dir, gap_cert
    ):
        master_handoff = engine.create(
            sm, from_agent="master_orchestrator", to_agent="spawner_agent",
            phase="execution", task_description="Design",
            payload={"summary": "Go.", "artifacts_produced": [], "decisions_made": [],
                     "open_questions": [], "constraints_for_next": [], "shared_state_fields_modified": []},
        )

        simulate_spawner(
            sm, engine, spawn_engine, master_handoff,
            spawn_request, registry_data, project_dir, gap_cert
        )

        for agent in ["master_orchestrator", "spawner_agent"]:
            assert sm.get_violation_count(agent) == 0

    def test_spawner_cannot_write_to_approvals(self, sm):
        result = sm.write("spawner_agent", "decisions", "approvals", [{"approval": "test"}])
        assert not result.success

    def test_human_review_required_flag_in_payload(
        self, sm, engine, spawn_engine, spawn_request, registry_data, project_dir, gap_cert
    ):
        master_handoff = engine.create(
            sm, from_agent="master_orchestrator", to_agent="spawner_agent",
            phase="execution", task_description="Design",
            payload={"summary": "Go.", "artifacts_produced": [], "decisions_made": [],
                     "open_questions": [], "constraints_for_next": [], "shared_state_fields_modified": []},
        )

        spawn_return = simulate_spawner(
            sm, engine, spawn_engine, master_handoff,
            spawn_request, registry_data, project_dir, gap_cert
        )

        assert spawn_return["payload"].get("human_review_required") is True
