"""
Integration Test — Training Flow
Tests the full training pipeline after an evaluation cycle:
  1. Master sends training request to Trainer
  2. Trainer reads evaluation report and quality findings
  3. Trainer produces proposals and training brief
  4. Trainer writes proposals to shared state
  5. Trainer returns handoff to Master
  6. Master can approve/reject proposals
  7. Governance: trainer cannot approve own proposals, cannot write to approvals

Tests Python infrastructure only — no live LLM calls.
"""
import pytest
import yaml
from pathlib import Path
from datetime import datetime, timezone
from core.shared_state_manager import SharedStateManager
from core.handoff_engine import HandoffEngine
from core.training_engine import TrainingEngine, TrainingProposal, PRIORITY_SCORES
import core.training_engine as te


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def project_id():
    return "proj-20260409-train-001"


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
    manager.initialize(request_id="req-train-001")
    return manager


@pytest.fixture
def engine():
    return HandoffEngine()


@pytest.fixture
def training_engine(tmp_path, monkeypatch):
    fake_backlog = tmp_path / "roster" / "training_backlog.yaml"
    fake_backlog.parent.mkdir(parents=True)
    monkeypatch.setattr(te, "BACKLOG_FILE", fake_backlog)
    return TrainingEngine()


@pytest.fixture
def evaluation_report(project_dir):
    """Write and return a completed evaluation report with some low scores."""
    report_dir = project_dir / "evaluation"
    report_dir.mkdir(parents=True, exist_ok=True)

    report = {
        "report_id": "eval-rep-train-001",
        "project_id": "proj-20260409-train-001",
        "evaluator": "evaluator_agent",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "overall_project_score": 72.0,
        "project_metrics": [
            {"metric": "documentation_completeness", "score": 40.0,
             "evidence": "Only 1 of 3 required docs found", "findings": "Missing product_plan and execution_plan"},
            {"metric": "scope_adherence", "score": 100.0,
             "evidence": "All 3 tasks completed", "findings": ""},
            {"metric": "acceptance_criteria_pass_rate", "score": 100.0,
             "evidence": "3/3 ACs passed", "findings": ""},
            {"metric": "goal_achievement", "score": 85.0,
             "evidence": "success criteria matched", "findings": ""},
            {"metric": "phase_efficiency", "score": 65.0,
             "evidence": "4 handoffs in evaluation phase (ideal: 2)", "findings": "Excess handoffs"},
            {"metric": "decision_quality", "score": 80.0,
             "evidence": "decisions logged with rationale", "findings": ""},
        ],
        "agent_evaluations": [
            {
                "agent_id": "project_manager_agent",
                "overall_score": 55.0,
                "recommend_probation": True,
                "exemplary": False,
                "strengths": ["task decomposition"],
                "issues": ["missed progress reports", "2 tasks blocked"],
                "recommendations": ["improve progress reporting"],
            }
        ],
        "systemic_findings": [],
        "recommendations": {
            "improvement_areas": ["documentation_completeness", "phase_efficiency"]
        },
    }

    with open(report_dir / "evaluation_report.yaml", "w") as f:
        yaml.dump(report, f)

    return report


@pytest.fixture
def populated_shared_state(sm, evaluation_report):
    """Pre-populate shared state with evaluation findings."""
    for m in evaluation_report["project_metrics"]:
        sm.append("evaluator_agent", "evaluation", "performance_metrics", {
            "metric": m["metric"],
            "score": round(m["score"], 2),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    for m in evaluation_report["project_metrics"]:
        if m["score"] < 70.0:
            sm.append("evaluator_agent", "evaluation", "quality_findings", {
                "finding_id": f"qf-{m['metric']}",
                "category": "performance",
                "description": m["findings"],
                "severity": "medium" if m["score"] >= 50.0 else "high",
                "evidence": m["evidence"],
            })
    return sm


# ---------------------------------------------------------------------------
# Simulate trainer
# ---------------------------------------------------------------------------

def simulate_trainer(
    sm: SharedStateManager,
    handoff_engine: HandoffEngine,
    training_engine: TrainingEngine,
    master_handoff: dict,
    evaluation_report: dict,
    project_dir: Path,
    project_id: str,
) -> dict:
    """Simulate the Trainer Agent processing an evaluation report."""
    handoff_id = master_handoff["handoff_id"]

    # 1. Accept handoff
    handoff_engine.accept(sm, handoff_id)

    # 2. Analyze report
    proposals = training_engine.analyze_evaluation_report(evaluation_report, project_id=project_id)

    # 3. Produce training brief
    brief_path = training_engine.produce_training_brief(project_id, proposals, project_dir)

    # 4. Update backlog
    training_engine.update_backlog(proposals)

    # 5. Write proposals to shared state
    for p in proposals:
        sm.append("trainer_agent", "evaluation", "improvement_proposals", {
            "proposal_id": p.proposal_id,
            "proposal_type": p.proposal_type,
            "priority": p.priority,
            "target_agent": p.target_agent,
            "target_artifact": p.target_artifact,
            "description": p.description[:200],
            "recommended_change": p.recommended_change[:200],
            "evidence": p.evidence,
            "systemic": p.systemic,
            "status": p.status,
        })

    # 6. Return to Master
    prioritized = training_engine.prioritize(proposals)
    top = prioritized[0] if prioritized else None
    systemic_count = sum(1 for p in proposals if p.systemic)

    return handoff_engine.create(
        sm,
        from_agent="trainer_agent",
        to_agent="master_orchestrator",
        phase="improvement",
        task_description="Deliver training brief",
        payload={
            "summary": (
                f"Training analysis complete. {len(proposals)} proposal(s) produced. "
                f"{systemic_count} systemic. "
                f"Training brief at: {brief_path}. Backlog updated."
            ),
            "artifacts_produced": [str(brief_path)],
            "decisions_made": [],
            "open_questions": [],
            "constraints_for_next": [
                "All proposals are advisory. No changes will be applied without Master approval."
            ],
            "shared_state_fields_modified": ["evaluation.improvement_proposals"],
            "training_brief_path": str(brief_path),
            "proposal_count": len(proposals),
            "systemic_count": systemic_count,
            "top_proposal": {
                "proposal_id": top.proposal_id,
                "proposal_type": top.proposal_type,
                "priority": top.priority,
                "description": top.description[:150],
            } if top else None,
        },
    )


# ---------------------------------------------------------------------------
# Tests: Training flow
# ---------------------------------------------------------------------------

class TestTrainingTrigger:

    def test_master_sends_training_request(self, sm, engine, evaluation_report):
        handoff = engine.create(
            sm,
            from_agent="master_orchestrator",
            to_agent="trainer_agent",
            phase="improvement",
            task_description="Produce improvement proposals",
            payload={
                "summary": "Evaluation complete. Please analyze and propose improvements.",
                "artifacts_produced": [],
                "decisions_made": [],
                "open_questions": [],
                "constraints_for_next": [],
                "shared_state_fields_modified": [],
            },
        )
        assert handoff["to_agent"] == "trainer_agent"
        assert handoff["phase"] == "improvement"


class TestFullTrainingFlow:

    def test_full_training_cycle_returns_handoff(
        self, sm, engine, training_engine, evaluation_report,
        project_dir, project_id, populated_shared_state
    ):
        master_handoff = engine.create(
            sm, from_agent="master_orchestrator", to_agent="trainer_agent",
            phase="improvement", task_description="Analyze evaluation",
            payload={"summary": "Go.", "artifacts_produced": [], "decisions_made": [],
                     "open_questions": [], "constraints_for_next": [], "shared_state_fields_modified": []},
        )

        train_return = simulate_trainer(
            sm, engine, training_engine, master_handoff,
            evaluation_report, project_dir, project_id
        )

        assert train_return["from_agent"] == "trainer_agent"
        assert train_return["to_agent"] == "master_orchestrator"
        assert train_return["payload"]["proposal_count"] > 0

    def test_training_brief_file_exists(
        self, sm, engine, training_engine, evaluation_report,
        project_dir, project_id, populated_shared_state
    ):
        master_handoff = engine.create(
            sm, from_agent="master_orchestrator", to_agent="trainer_agent",
            phase="improvement", task_description="Analyze",
            payload={"summary": "Go.", "artifacts_produced": [], "decisions_made": [],
                     "open_questions": [], "constraints_for_next": [], "shared_state_fields_modified": []},
        )

        simulate_trainer(
            sm, engine, training_engine, master_handoff,
            evaluation_report, project_dir, project_id
        )

        brief_path = project_dir / "training" / "training_brief.yaml"
        assert brief_path.exists()
        with open(brief_path) as f:
            brief = yaml.safe_load(f)
        assert brief["project_id"] == project_id
        assert brief["authority_level"] == "L0_advisory"

    def test_proposals_written_to_shared_state(
        self, sm, engine, training_engine, evaluation_report,
        project_dir, project_id, populated_shared_state
    ):
        master_handoff = engine.create(
            sm, from_agent="master_orchestrator", to_agent="trainer_agent",
            phase="improvement", task_description="Analyze",
            payload={"summary": "Go.", "artifacts_produced": [], "decisions_made": [],
                     "open_questions": [], "constraints_for_next": [], "shared_state_fields_modified": []},
        )

        train_return = simulate_trainer(
            sm, engine, training_engine, master_handoff,
            evaluation_report, project_dir, project_id
        )

        proposals_in_state = sm.read("evaluation.improvement_proposals")
        assert proposals_in_state is not None
        assert len(proposals_in_state) == train_return["payload"]["proposal_count"]

    def test_backlog_updated_after_training(
        self, sm, engine, training_engine, evaluation_report,
        project_dir, project_id, populated_shared_state
    ):
        master_handoff = engine.create(
            sm, from_agent="master_orchestrator", to_agent="trainer_agent",
            phase="improvement", task_description="Analyze",
            payload={"summary": "Go.", "artifacts_produced": [], "decisions_made": [],
                     "open_questions": [], "constraints_for_next": [], "shared_state_fields_modified": []},
        )

        train_return = simulate_trainer(
            sm, engine, training_engine, master_handoff,
            evaluation_report, project_dir, project_id
        )

        backlog = training_engine.load_backlog()
        assert len(backlog["proposals"]) == train_return["payload"]["proposal_count"]

    def test_master_accepts_training_return(
        self, sm, engine, training_engine, evaluation_report,
        project_dir, project_id, populated_shared_state
    ):
        master_handoff = engine.create(
            sm, from_agent="master_orchestrator", to_agent="trainer_agent",
            phase="improvement", task_description="Analyze",
            payload={"summary": "Go.", "artifacts_produced": [], "decisions_made": [],
                     "open_questions": [], "constraints_for_next": [], "shared_state_fields_modified": []},
        )

        train_return = simulate_trainer(
            sm, engine, training_engine, master_handoff,
            evaluation_report, project_dir, project_id
        )

        engine.accept(sm, train_return["handoff_id"])
        assert len(engine.get_pending(sm)) == 0

    def test_handoff_count_in_training_phase(
        self, sm, engine, training_engine, evaluation_report,
        project_dir, project_id, populated_shared_state
    ):
        master_handoff = engine.create(
            sm, from_agent="master_orchestrator", to_agent="trainer_agent",
            phase="improvement", task_description="Analyze",
            payload={"summary": "Go.", "artifacts_produced": [], "decisions_made": [],
                     "open_questions": [], "constraints_for_next": [], "shared_state_fields_modified": []},
        )

        train_return = simulate_trainer(
            sm, engine, training_engine, master_handoff,
            evaluation_report, project_dir, project_id
        )
        engine.accept(sm, train_return["handoff_id"])

        history = sm.read("workflow.handoff_history")
        assert len(history) == 2

    def test_top_proposal_is_highest_priority(
        self, sm, engine, training_engine, evaluation_report,
        project_dir, project_id, populated_shared_state
    ):
        master_handoff = engine.create(
            sm, from_agent="master_orchestrator", to_agent="trainer_agent",
            phase="improvement", task_description="Analyze",
            payload={"summary": "Go.", "artifacts_produced": [], "decisions_made": [],
                     "open_questions": [], "constraints_for_next": [], "shared_state_fields_modified": []},
        )

        train_return = simulate_trainer(
            sm, engine, training_engine, master_handoff,
            evaluation_report, project_dir, project_id
        )

        top = train_return["payload"]["top_proposal"]
        assert top is not None
        # The probation agent should generate boundary_violation (priority 5)
        # which is the highest in our test report
        assert top["priority"] == PRIORITY_SCORES["boundary_violation"]


# ---------------------------------------------------------------------------
# Tests: Governance
# ---------------------------------------------------------------------------

class TestTrainingGovernance:

    def test_no_violations_in_training_flow(
        self, sm, engine, training_engine, evaluation_report,
        project_dir, project_id, populated_shared_state
    ):
        master_handoff = engine.create(
            sm, from_agent="master_orchestrator", to_agent="trainer_agent",
            phase="improvement", task_description="Analyze",
            payload={"summary": "Go.", "artifacts_produced": [], "decisions_made": [],
                     "open_questions": [], "constraints_for_next": [], "shared_state_fields_modified": []},
        )

        simulate_trainer(
            sm, engine, training_engine, master_handoff,
            evaluation_report, project_dir, project_id
        )

        for agent in ["master_orchestrator", "trainer_agent"]:
            assert sm.get_violation_count(agent) == 0

    def test_trainer_cannot_approve_own_proposals(self, sm):
        sm.append("trainer_agent", "evaluation", "improvement_proposals", [{"proposal": "test"}])
        result = sm.approve("trainer_agent", "evaluation", "improvement_proposals")
        assert not result.success
        assert result.reason == "only_master_can_approve"

    def test_trainer_cannot_write_to_approvals(self, sm):
        result = sm.write("trainer_agent", "decisions", "approvals", [{"approval": "test"}])
        assert not result.success

    def test_trainer_cannot_write_to_decision_log(self, sm):
        result = sm.write("trainer_agent", "decisions", "decision_log",
                          [{"decision": "something"}])
        assert not result.success

    def test_trainer_proposals_are_append_only(
        self, sm, engine, training_engine, evaluation_report,
        project_dir, project_id, populated_shared_state
    ):
        """Trainer can append proposals but not overwrite the list."""
        master_handoff = engine.create(
            sm, from_agent="master_orchestrator", to_agent="trainer_agent",
            phase="improvement", task_description="Analyze",
            payload={"summary": "Go.", "artifacts_produced": [], "decisions_made": [],
                     "open_questions": [], "constraints_for_next": [], "shared_state_fields_modified": []},
        )

        simulate_trainer(
            sm, engine, training_engine, master_handoff,
            evaluation_report, project_dir, project_id
        )

        # Attempt to overwrite (write not append) the proposals list — must be blocked
        result = sm.write("trainer_agent", "evaluation", "improvement_proposals",
                          [{"proposal_id": "overwrite-attempt"}])
        assert not result.success

    def test_master_can_approve_proposals_in_backlog(
        self, sm, engine, training_engine, evaluation_report,
        project_dir, project_id, populated_shared_state
    ):
        master_handoff = engine.create(
            sm, from_agent="master_orchestrator", to_agent="trainer_agent",
            phase="improvement", task_description="Analyze",
            payload={"summary": "Go.", "artifacts_produced": [], "decisions_made": [],
                     "open_questions": [], "constraints_for_next": [], "shared_state_fields_modified": []},
        )

        simulate_trainer(
            sm, engine, training_engine, master_handoff,
            evaluation_report, project_dir, project_id
        )

        backlog = training_engine.load_backlog()
        first_id = backlog["proposals"][0]["proposal_id"]
        ok = training_engine.approve_proposal(first_id, "master_orchestrator")
        assert ok

        approved = training_engine.get_by_status("approved")
        assert any(p["proposal_id"] == first_id for p in approved)
