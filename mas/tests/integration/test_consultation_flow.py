"""
Integration Test — Consultation Flow
Tests the full consultation pipeline from Master request to synthesis:
  1. Master creates consultation request
  2. All 5 consultants submit responses
  3. Engine checks for unanimous risk
  4. Master synthesizes responses into a decision
  5. Synthesis saved to disk and shared state
  6. Governance: only consultants can write to consultation_responses;
     unanimous high-risk triggers human escalation flag

Tests Python infrastructure only — no live LLM calls.
"""
import pytest
import yaml
from pathlib import Path
from core.shared_state_manager import SharedStateManager
from core.handoff_engine import HandoffEngine
from core.consultation_engine import (
    ConsultationEngine,
    ALL_CONSULTANTS,
    MANDATORY_DECISION_TYPES,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def project_id():
    return "proj-20260409-consult-001"


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
    manager.initialize(request_id="req-consult-001")
    return manager


@pytest.fixture
def handoff_engine():
    return HandoffEngine()


@pytest.fixture
def consult_engine():
    return ConsultationEngine()


# ---------------------------------------------------------------------------
# Simulate the consultant panel
# ---------------------------------------------------------------------------

def simulate_consultation(
    sm: SharedStateManager,
    consult_engine: ConsultationEngine,
    project_dir: Path,
    project_id: str,
    question: str,
    decision_type: str,
    risk_levels: dict,  # consultant_id → risk_level
    domain: str = "software_engineering",
) -> tuple:
    """
    Simulate a full consultation round.
    Returns (request, synthesis, synthesis_path).
    """
    domain_ctx = consult_engine.load_domain_context(domain)

    # 1. Master creates request
    request = consult_engine.create_request(
        project_id=project_id,
        question=question,
        context={"phase": "planning", "decision": question},
        decision_type=decision_type,
        domain_context=domain_ctx,
    )
    consult_engine.save_request(request, project_dir)

    # 2. Write to shared state
    sm.append("master_orchestrator", "consultation", "consultation_requests", {
        "request_id": request.request_id,
        "question": question,
        "decision_type": decision_type,
        "mandatory": request.mandatory,
        "consultants_selected": request.consultants_selected,
    })

    # 3. Each consultant responds
    for cid in request.consultants_selected:
        risk = risk_levels.get(cid, "low")
        consult_engine.record_response(
            request, cid,
            response_text=f"{cid} analysis of '{question[:50]}'. Risk: {risk}.",
            risk_level=risk,
            key_concerns=[f"{cid} primary concern"],
            recommendation=f"{cid} recommends proceeding with caution.",
        )
        # Write to shared state
        sm.append(cid, "consultation", "consultation_responses", {
            "request_id": request.request_id,
            "consultant_id": cid,
            "risk_level": risk,
            "key_concerns": [f"{cid} primary concern"],
            "recommendation": f"{cid} recommends proceeding.",
        })

    # 4. Master synthesizes
    unanimous = consult_engine.check_unanimous_risk(request)
    synthesis = consult_engine.synthesize(
        request,
        decision_reached="Proceed with spawn" if not unanimous else "ESCALATE TO HUMAN",
        rationale="Consultation complete",
        risks_addressed="Mitigation plan added",
    )
    synth_path = consult_engine.save_synthesis(synthesis, project_dir)

    # 5. Write synthesis to shared state
    sm.append("master_orchestrator", "consultation", "synthesis", {
        "synthesis_id": synthesis.synthesis_id,
        "request_id": request.request_id,
        "decision_reached": synthesis.decision_reached,
        "unanimous_high_risk": synthesis.unanimous_high_risk,
        "human_escalation_required": synthesis.human_escalation_required,
    })

    return request, synthesis, synth_path


# ---------------------------------------------------------------------------
# Tests: happy path
# ---------------------------------------------------------------------------

class TestConsultationHappyPath:

    def test_consultation_request_created(self, consult_engine, project_dir, project_id):
        req = consult_engine.create_request(
            project_id, "Should we spawn?", {}, "spawn"
        )
        assert req.mandatory is True
        assert set(req.consultants_selected) == set(ALL_CONSULTANTS)

    def test_full_consultation_cycle_no_unanimous_risk(
        self, sm, consult_engine, project_dir, project_id
    ):
        risk_levels = {c: "low" for c in ALL_CONSULTANTS}
        request, synthesis, _ = simulate_consultation(
            sm, consult_engine, project_dir, project_id,
            "Should we spawn a reporting agent?", "spawn", risk_levels
        )
        assert synthesis.unanimous_high_risk is False
        assert synthesis.human_escalation_required is False
        assert synthesis.decision_reached == "Proceed with spawn"

    def test_all_consultants_responded(
        self, sm, consult_engine, project_dir, project_id
    ):
        risk_levels = {c: "low" for c in ALL_CONSULTANTS}
        request, _, _ = simulate_consultation(
            sm, consult_engine, project_dir, project_id,
            "Question?", "spawn", risk_levels
        )
        assert set(request.responses.keys()) == set(ALL_CONSULTANTS)
        # simulate_consultation calls synthesize after all responses → status is synthesized
        assert request.status == "synthesized"

    def test_synthesis_file_created(
        self, sm, consult_engine, project_dir, project_id
    ):
        risk_levels = {c: "low" for c in ALL_CONSULTANTS}
        _, synthesis, synth_path = simulate_consultation(
            sm, consult_engine, project_dir, project_id,
            "Question?", "spawn", risk_levels
        )
        assert synth_path.exists()
        with open(synth_path) as f:
            data = yaml.safe_load(f)
        assert data["project_id"] == project_id
        assert data["produced_by"] == "master_orchestrator"

    def test_consultation_request_written_to_shared_state(
        self, sm, consult_engine, project_dir, project_id
    ):
        risk_levels = {c: "low" for c in ALL_CONSULTANTS}
        simulate_consultation(
            sm, consult_engine, project_dir, project_id,
            "Question?", "spawn", risk_levels
        )
        requests = sm.read("consultation.consultation_requests")
        assert requests is not None
        assert len(requests) == 1

    def test_responses_written_to_shared_state(
        self, sm, consult_engine, project_dir, project_id
    ):
        risk_levels = {c: "low" for c in ALL_CONSULTANTS}
        simulate_consultation(
            sm, consult_engine, project_dir, project_id,
            "Question?", "spawn", risk_levels
        )
        responses = sm.read("consultation.consultation_responses")
        assert responses is not None
        assert len(responses) == len(ALL_CONSULTANTS)

    def test_synthesis_written_to_shared_state(
        self, sm, consult_engine, project_dir, project_id
    ):
        risk_levels = {c: "low" for c in ALL_CONSULTANTS}
        simulate_consultation(
            sm, consult_engine, project_dir, project_id,
            "Question?", "spawn", risk_levels
        )
        syntheses = sm.read("consultation.synthesis")
        assert syntheses is not None
        assert len(syntheses) == 1

    def test_subset_consultation_optional_type(
        self, sm, consult_engine, project_dir, project_id
    ):
        req = consult_engine.create_request(
            project_id, "Q?", {}, "approach",
            consultants=["risk_advisor", "efficiency_advisor"]
        )
        assert req.mandatory is False
        assert len(req.consultants_selected) == 2


# ---------------------------------------------------------------------------
# Tests: unanimous high-risk escalation
# ---------------------------------------------------------------------------

class TestUnanimousRiskEscalation:

    def test_unanimous_high_sets_escalation(
        self, sm, consult_engine, project_dir, project_id
    ):
        risk_levels = {c: "high" for c in ALL_CONSULTANTS}
        _, synthesis, _ = simulate_consultation(
            sm, consult_engine, project_dir, project_id,
            "Very risky decision?", "spawn", risk_levels
        )
        assert synthesis.unanimous_high_risk is True
        assert synthesis.human_escalation_required is True

    def test_one_non_high_no_escalation(
        self, sm, consult_engine, project_dir, project_id
    ):
        risk_levels = {c: "high" for c in ALL_CONSULTANTS}
        risk_levels["efficiency_advisor"] = "medium"  # one dissents
        _, synthesis, _ = simulate_consultation(
            sm, consult_engine, project_dir, project_id,
            "Somewhat risky?", "spawn", risk_levels
        )
        assert synthesis.unanimous_high_risk is False
        assert synthesis.human_escalation_required is False

    def test_unanimous_high_reflected_in_saved_synthesis(
        self, sm, consult_engine, project_dir, project_id
    ):
        risk_levels = {c: "high" for c in ALL_CONSULTANTS}
        _, synthesis, synth_path = simulate_consultation(
            sm, consult_engine, project_dir, project_id,
            "Very risky?", "spawn", risk_levels
        )
        with open(synth_path) as f:
            data = yaml.safe_load(f)
        assert data["human_escalation_required"] is True


# ---------------------------------------------------------------------------
# Tests: governance
# ---------------------------------------------------------------------------

class TestConsultationGovernance:

    def test_no_violations_in_full_consultation(
        self, sm, consult_engine, project_dir, project_id
    ):
        risk_levels = {c: "low" for c in ALL_CONSULTANTS}
        simulate_consultation(
            sm, consult_engine, project_dir, project_id,
            "Question?", "spawn", risk_levels
        )
        for agent in ["master_orchestrator"] + ALL_CONSULTANTS:
            assert sm.get_violation_count(agent) == 0

    def test_consultant_cannot_write_to_approvals(self, sm):
        result = sm.write("risk_advisor", "decisions", "approvals",
                          [{"approval": "test"}])
        assert not result.success

    def test_consultant_cannot_write_to_decision_log(self, sm):
        result = sm.write("quality_advisor", "decisions", "decision_log",
                          [{"decision": "test"}])
        assert not result.success

    def test_consultant_cannot_write_to_workflow(self, sm):
        result = sm.write("devils_advocate", "workflow", "current_owner", "self")
        assert not result.success

    def test_non_consultant_cannot_write_to_responses(self, sm):
        result = sm.append("trainer_agent", "consultation", "consultation_responses",
                           {"consultant_id": "fake"})
        assert not result.success

    def test_master_can_write_consultation_requests(self, sm):
        result = sm.append("master_orchestrator", "consultation", "consultation_requests",
                           {"request_id": "consult-test-001", "question": "test"})
        assert result.success

    def test_master_can_write_synthesis(self, sm):
        result = sm.append("master_orchestrator", "consultation", "synthesis",
                           {"synthesis_id": "synth-001", "decision": "proceed"})
        assert result.success

    def test_responses_are_append_only(self, sm):
        # Write once
        sm.append("risk_advisor", "consultation", "consultation_responses",
                  {"consultant_id": "risk_advisor", "risk_level": "low"})
        # Attempt to overwrite
        result = sm.write("risk_advisor", "consultation", "consultation_responses",
                          [{"consultant_id": "risk_advisor", "risk_level": "high"}])
        assert not result.success

    def test_each_consultant_can_write_responses(self, sm):
        for cid in ALL_CONSULTANTS:
            result = sm.append(cid, "consultation", "consultation_responses",
                               {"consultant_id": cid, "risk_level": "low"})
            assert result.success, f"{cid} should be able to write responses"
