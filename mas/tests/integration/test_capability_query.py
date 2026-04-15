"""
Integration Test — Capability Query Flow
Tests the full flow:
  1. Master requests capability discovery from HR Agent
  2. HR Agent searches registry
  3a. HR returns match recommendation  (when match exists)
  3b. HR produces Gap Certificate       (when no match exists)
  4. Master accepts HR's handoff
  5. Governance checks: no violations, proper handoff chain

Tests the Python infrastructure, not the agent's reasoning.
"""
import pytest
import yaml
from pathlib import Path
from datetime import datetime, timezone
from core.engine.shared_state_manager import SharedStateManager
from core.engine.handoff_engine import HandoffEngine
from core.engine.capability_registry import CapabilityRegistry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def project_id():
    return "proj-20260409-hr-001"


@pytest.fixture
def projects_root(tmp_path):
    return tmp_path / "projects_root"


@pytest.fixture
def sm(projects_root, project_id):
    manager = SharedStateManager(project_id, projects_root=projects_root)
    # manager.initialize(request_id="req-hr-20260409-001")  # disabled: avoid creating real projects during migration-focused runs
    return manager


@pytest.fixture
def engine():
    return HandoffEngine()


@pytest.fixture
def registry(tmp_path):
    roster_dst = tmp_path / "roster"
    roster_dst.mkdir()

    registry_path = roster_dst / "registry_index.yaml"
    registry_path.write_text(
        "registry:\n"
        "  version: '1.0.0'\n"
        "  last_updated: ''\n"
        "  maintained_by: hr_agent\n"
        "  agents: []\n"
        "  skills: []\n"
        "  tools: []\n"
        "counts:\n"
        "  active_agents: 0\n"
        "  active_skills: 0\n"
        "  retired_agents: 0\n"
        "  spawned_total: 0\n",
        encoding="utf-8",
    )
    vh_path = roster_dst / "version_history.yaml"
    vh_path.write_text(
        "version_history:\n"
        "  maintained_by: hr_agent\n"
        "  entries: []\n",
        encoding="utf-8",
    )
    return CapabilityRegistry(
        registry_path=registry_path,
        version_history_path=vh_path,
    )


@pytest.fixture
def registry_with_reporting_agent(registry):
    registry.register_agent({
        "agent_id": "reporting_agent",
        "name": "Reporting Agent",
        "version": "1.0.0",
        "trust_tier": "T1_established",
        "status": "active",
        "capabilities": ["reporting", "dashboard", "data-visualization",
                         "salesforce", "charts"],
        "performance_score": 82.0,
        "spawn_origin": None,
        "created_at": "2026-01-01T00:00:00+00:00",
    })
    return registry


# ---------------------------------------------------------------------------
# Simulation helpers
# ---------------------------------------------------------------------------

def simulate_hr_search(
    sm: SharedStateManager,
    engine: HandoffEngine,
    registry: CapabilityRegistry,
    master_handoff: dict,
    projects_root: Path,
) -> dict:
    """
    Simulate HR Agent performing a capability search and returning to Master.
    """
    pid = sm.project_id
    handoff_id = master_handoff["handoff_id"]
    payload = master_handoff["payload"]

    required_tags = payload.get("required_capabilities", [])
    need_description = payload.get("need_description", "")
    requesting_agent = payload.get("requesting_agent", "master_orchestrator")

    # 1. Accept the handoff
    engine.accept(sm, handoff_id)

    # 2. Search the registry
    results = registry.search(required_tags)
    strong = [r for r in results if r.match_type == "strong"]
    partial = [r for r in results if r.match_type == "partial"]

    if strong:
        best = strong[0]
        return engine.create(
            sm,
            from_agent="hr_agent",
            to_agent="master_orchestrator",
            phase="capability_discovery",
            task_description="Return capability match recommendation",
            payload={
                "summary": (
                    f"Strong match found: '{best.agent_id}' "
                    f"(score={best.score:.1f}%). Recommendation: {best.recommendation}"
                ),
                "artifacts_produced": [],
                "decisions_made": [],
                "open_questions": [],
                "constraints_for_next": [],
                "shared_state_fields_modified": [],
                "match_type": "strong",
                "recommended_agent_id": best.agent_id,
                "score": best.score,
                "recommendation": best.recommendation,
            },
        )

    # No strong match — produce gap certificate
    cert = registry.produce_gap_certificate(
        need_description=need_description,
        required_capabilities=required_tags,
        project_id=pid,
        requested_by=requesting_agent,
    )
    cert_path = registry.save_gap_certificate(cert, pid, projects_root=projects_root)

    return engine.create(
        sm,
        from_agent="hr_agent",
        to_agent="master_orchestrator",
        phase="capability_discovery",
        task_description="Return Capability Gap Certificate",
        payload={
            "summary": (
                f"No strong match found for capabilities: {required_tags}. "
                f"Gap Certificate '{cert.certificate_id}' produced at {cert_path}."
            ),
            "artifacts_produced": [str(cert_path)],
            "decisions_made": [],
            "open_questions": [],
            "constraints_for_next": [],
            "shared_state_fields_modified": [],
            "match_type": "none",
            "certificate_id": cert.certificate_id,
            "certificate_path": str(cert_path),
            "spawn_recommendation": cert.spawn_recommendation,
        },
    )


# ---------------------------------------------------------------------------
# Tests: strong match path
# ---------------------------------------------------------------------------

class TestCapabilityQueryStrongMatch:

    def test_master_sends_capability_query_to_hr(
        self, sm, engine, registry_with_reporting_agent
    ):
        handoff = engine.create(
            sm,
            from_agent="master_orchestrator",
            to_agent="hr_agent",
            phase="capability_discovery",
            task_description="Discover reporting capability",
            payload={
                "summary": "Search for a reporting dashboard agent.",
                "artifacts_produced": [],
                "decisions_made": [],
                "open_questions": [],
                "constraints_for_next": [],
                "shared_state_fields_modified": [],
                "need_description": "Need a reporting dashboard agent",
                "required_capabilities": ["reporting", "dashboard", "salesforce"],
                "requesting_agent": "product_manager_agent",
            },
        )
        assert handoff["to_agent"] == "hr_agent"
        assert "reporting" in handoff["payload"]["required_capabilities"]

    def test_hr_returns_strong_match(
        self, sm, engine, registry_with_reporting_agent, projects_root
    ):
        master_handoff = engine.create(
            sm,
            from_agent="master_orchestrator",
            to_agent="hr_agent",
            phase="capability_discovery",
            task_description="Discover reporting capability",
            payload={
                "summary": "Search for reporting agent.",
                "artifacts_produced": [],
                "decisions_made": [],
                "open_questions": [],
                "constraints_for_next": [],
                "shared_state_fields_modified": [],
                "need_description": "Need a reporting dashboard agent",
                "required_capabilities": ["reporting", "dashboard", "salesforce",
                                           "data-visualization"],
                "requesting_agent": "product_manager_agent",
            },
        )

        hr_return = simulate_hr_search(
            sm, engine, registry_with_reporting_agent, master_handoff, projects_root
        )

        assert hr_return["from_agent"] == "hr_agent"
        assert hr_return["to_agent"] == "master_orchestrator"
        assert hr_return["payload"]["match_type"] == "strong"
        assert hr_return["payload"]["recommended_agent_id"] == "reporting_agent"
        assert hr_return["payload"]["score"] >= 80.0

    def test_master_accepts_hr_return(
        self, sm, engine, registry_with_reporting_agent, projects_root
    ):
        master_handoff = engine.create(
            sm,
            from_agent="master_orchestrator",
            to_agent="hr_agent",
            phase="capability_discovery",
            task_description="Discover reporting capability",
            payload={
                "summary": "Search.",
                "artifacts_produced": [],
                "decisions_made": [],
                "open_questions": [],
                "constraints_for_next": [],
                "shared_state_fields_modified": [],
                "need_description": "Need a reporting dashboard agent",
                "required_capabilities": ["reporting", "dashboard"],
                "requesting_agent": "master_orchestrator",
            },
        )

        hr_return = simulate_hr_search(
            sm, engine, registry_with_reporting_agent, master_handoff, projects_root
        )
        engine.accept(sm, hr_return["handoff_id"])

        pending = engine.get_pending(sm)
        assert len(pending) == 0

        history = sm.read("workflow.handoff_history")
        assert len(history) == 2


# ---------------------------------------------------------------------------
# Tests: gap certificate path
# ---------------------------------------------------------------------------

class TestCapabilityQueryGapCert:

    def test_hr_produces_gap_cert_when_no_match(
        self, sm, engine, registry, projects_root
    ):
        master_handoff = engine.create(
            sm,
            from_agent="master_orchestrator",
            to_agent="hr_agent",
            phase="capability_discovery",
            task_description="Discover ML training capability",
            payload={
                "summary": "Search for ML training agent.",
                "artifacts_produced": [],
                "decisions_made": [],
                "open_questions": [],
                "constraints_for_next": [],
                "shared_state_fields_modified": [],
                "need_description": "Need an agent that can train and evaluate ML models",
                "required_capabilities": ["ml-training", "gpu-inference", "model-registry"],
                "requesting_agent": "product_manager_agent",
            },
        )

        hr_return = simulate_hr_search(
            sm, engine, registry, master_handoff, projects_root
        )

        assert hr_return["payload"]["match_type"] == "none"
        assert "certificate_id" in hr_return["payload"]
        assert hr_return["payload"]["certificate_id"].startswith("gap-")

    def test_gap_cert_file_created_on_disk(
        self, sm, engine, registry, projects_root
    ):
        master_handoff = engine.create(
            sm,
            from_agent="master_orchestrator",
            to_agent="hr_agent",
            phase="capability_discovery",
            task_description="Discover ML training capability",
            payload={
                "summary": "Search.",
                "artifacts_produced": [],
                "decisions_made": [],
                "open_questions": [],
                "constraints_for_next": [],
                "shared_state_fields_modified": [],
                "need_description": "ML training",
                "required_capabilities": ["ml-training", "gpu-inference"],
                "requesting_agent": "product_manager_agent",
            },
        )

        hr_return = simulate_hr_search(
            sm, engine, registry, master_handoff, projects_root
        )

        cert_path = Path(hr_return["payload"]["certificate_path"])
        assert cert_path.exists()

        with open(cert_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert "capability_gap_certificate" in data

    def test_gap_cert_has_spawn_recommendation(
        self, sm, engine, registry, projects_root
    ):
        master_handoff = engine.create(
            sm,
            from_agent="master_orchestrator",
            to_agent="hr_agent",
            phase="capability_discovery",
            task_description="Discover capability",
            payload={
                "summary": "Search.",
                "artifacts_produced": [],
                "decisions_made": [],
                "open_questions": [],
                "constraints_for_next": [],
                "shared_state_fields_modified": [],
                "need_description": "Need something new",
                "required_capabilities": ["brand-new-capability"],
                "requesting_agent": "master_orchestrator",
            },
        )

        hr_return = simulate_hr_search(
            sm, engine, registry, master_handoff, projects_root
        )

        spawn_rec = hr_return["payload"]["spawn_recommendation"]
        assert spawn_rec["should_spawn"] is True


# ---------------------------------------------------------------------------
# Governance tests
# ---------------------------------------------------------------------------

class TestCapabilityQueryGovernance:

    def test_no_violations_in_normal_flow(
        self, sm, engine, registry_with_reporting_agent, projects_root
    ):
        master_handoff = engine.create(
            sm,
            from_agent="master_orchestrator",
            to_agent="hr_agent",
            phase="capability_discovery",
            task_description="Discover reporting capability",
            payload={
                "summary": "Test.",
                "artifacts_produced": [],
                "decisions_made": [],
                "open_questions": [],
                "constraints_for_next": [],
                "shared_state_fields_modified": [],
                "need_description": "Reporting",
                "required_capabilities": ["reporting", "dashboard"],
                "requesting_agent": "master_orchestrator",
            },
        )
        simulate_hr_search(
            sm, engine, registry_with_reporting_agent, master_handoff, projects_root
        )

        for agent in ["master_orchestrator", "hr_agent"]:
            assert sm.get_violation_count(agent) == 0

    def test_hr_cannot_approve_own_fields(self, sm):
        sm.write("hr_agent", "capability", "roster_version", "1.0.0")
        result = sm.approve("hr_agent", "capability", "roster_version")
        assert not result.success
        assert result.reason == "only_master_can_approve"

    def test_total_handoffs_in_query_cycle(
        self, sm, engine, registry, projects_root
    ):
        master_handoff = engine.create(
            sm,
            from_agent="master_orchestrator",
            to_agent="hr_agent",
            phase="capability_discovery",
            task_description="Discover capability",
            payload={
                "summary": "Search.",
                "artifacts_produced": [],
                "decisions_made": [],
                "open_questions": [],
                "constraints_for_next": [],
                "shared_state_fields_modified": [],
                "need_description": "Need ML",
                "required_capabilities": ["ml-training"],
                "requesting_agent": "master_orchestrator",
            },
        )
        hr_return = simulate_hr_search(
            sm, engine, registry, master_handoff, projects_root
        )
        engine.accept(sm, hr_return["handoff_id"])

        history = sm.read("workflow.handoff_history")
        assert len(history) == 2
