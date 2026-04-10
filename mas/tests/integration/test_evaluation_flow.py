"""
Integration Test — Evaluation Flow
Tests the full evaluation pipeline after project completion:
  1. Master sends evaluation request to Evaluator
  2. Evaluator collects all project data
  3. Evaluator scores project and agent metrics
  4. Evaluator produces and saves evaluation report
  5. Evaluator writes findings to shared state
  6. Evaluator returns handoff to Master
  7. Governance checks: no violations, report accessible

Tests Python infrastructure only — no live LLM calls.
"""
import pytest
import yaml
import shutil
from pathlib import Path
from datetime import datetime, timezone
from core.shared_state_manager import SharedStateManager
from core.handoff_engine import HandoffEngine
from core.task_board import TaskBoard
from core.metrics_engine import MetricsEngine, EXEMPLARY_THRESHOLD


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def project_id():
    return "proj-20260409-eval-001"


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
    manager.initialize(request_id="req-eval-001")
    return manager


@pytest.fixture
def engine():
    return HandoffEngine()


@pytest.fixture
def metrics(engine):
    return MetricsEngine()


@pytest.fixture
def completed_project(sm, projects_root, project_id, project_dir):
    """
    Build a fully completed project state on disk.
    Creates all required docs, a completed task board, and
    populates shared state with clarified spec + product plan.
    """
    pid = project_id

    # Write clarified spec
    (project_dir / "intake").mkdir()
    clarified_spec = {
        "project_id": pid,
        "created_by": "inquirer_agent",
        "quality_score": 0.92,
        "specification": {
            "project_goal": "Build a web-based sales reporting dashboard",
            "success_criteria": (
                "Dashboard used by >80% of sales team; "
                "pipeline data refreshes every 15 minutes"
            ),
        },
        "unresolved": [],
    }
    with open(project_dir / "intake" / "clarified_spec.yaml", "w") as f:
        yaml.dump(clarified_spec, f)

    # Write product plan
    (project_dir / "planning").mkdir()
    product_plan = {
        "project_id": pid,
        "created_by": "product_manager_agent",
        "status": "approved",
        "product_goal": "Build a web-based sales reporting dashboard",
        "requirements": {
            "must_have": [
                {
                    "id": "req-001",
                    "description": "Dashboard UI",
                    "source": "scope",
                    "acceptance_criteria": [
                        "Dashboard loads in <3 seconds",
                        "Data visible to logged-in users",
                    ],
                },
                {
                    "id": "req-002",
                    "description": "Salesforce integration",
                    "source": "scope",
                    "acceptance_criteria": [
                        "Data refreshes every 15 minutes",
                    ],
                },
            ],
            "should_have": [],
            "could_have": [],
            "wont_have": [],
        },
        "risks": [],
        "approval_status": "approved",
    }
    with open(project_dir / "planning" / "product_plan.yaml", "w") as f:
        yaml.dump(product_plan, f)

    # Write execution plan + task board
    board = TaskBoard(pid, projects_root=projects_root)
    ms1 = board.create_milestone({
        "name": "M1: Foundation",
        "completion_criteria": "Infrastructure ready",
    })
    ms2 = board.create_milestone({
        "name": "M2: Dashboard",
        "completion_criteria": "Dashboard live",
    })
    t1 = board.create_task({
        "description": "Set up AWS infrastructure",
        "milestone": ms1,
        "estimated_effort": "medium",
        "assigned_to": "project_manager_agent",
    })
    t2 = board.create_task({
        "description": "Build Salesforce connector",
        "milestone": ms2,
        "estimated_effort": "large",
        "dependencies": [t1],
        "assigned_to": "project_manager_agent",
    })
    t3 = board.create_task({
        "description": "Build dashboard reporting UI",
        "milestone": ms2,
        "estimated_effort": "large",
        "dependencies": [t1],
        "assigned_to": "project_manager_agent",
    })

    # Complete all tasks
    for tid in [t1, t2, t3]:
        board.update_status(tid, "in_progress")
        board.update_status(tid, "completed")

    board.produce_execution_plan(f"projects/{pid}/planning/product_plan.yaml")

    # Populate shared state
    sm.write("inquirer_agent", "project_definition", "clarified_specification",
             clarified_spec["specification"])
    sm.write("product_manager_agent", "project_definition", "project_goal",
             "Build a web-based sales reporting dashboard")

    return project_dir


# ---------------------------------------------------------------------------
# Simulate evaluator
# ---------------------------------------------------------------------------

def simulate_evaluator(
    sm: SharedStateManager,
    handoff_engine: HandoffEngine,
    metrics_engine: MetricsEngine,
    master_handoff: dict,
    project_dir: Path,
    projects_root: Path,
    agents_to_evaluate: list,
) -> dict:
    """
    Simulate the Evaluator Agent performing a full evaluation.
    """
    pid = sm.project_id
    handoff_id = master_handoff["handoff_id"]

    # 1. Accept handoff
    handoff_engine.accept(sm, handoff_id)

    # 2. Load project state
    state = sm.load()

    # 3. Load task board
    board_path = project_dir / "execution" / "task_board.yaml"
    board_data = {"tasks": [], "milestones": []}
    if board_path.exists():
        with open(board_path) as f:
            board_data = yaml.safe_load(f) or board_data

    # 4. Produce report
    report = metrics_engine.produce_report(
        pid, state, project_dir, board_data,
        agents_to_evaluate=agents_to_evaluate,
    )

    # 5. Save report
    report_path = metrics_engine.save_report(report, project_dir)

    # 6. Append each metric to shared state (append_only field)
    for m in report.project_metrics:
        sm.append("evaluator_agent", "evaluation", "performance_metrics", {
            "metric": m.metric,
            "score": round(m.score, 2),
            "timestamp": report.timestamp,
        })

    # 7. Write quality findings for any metric below 70
    for m in report.project_metrics:
        if m.score < 70.0:
            sm.append("evaluator_agent", "evaluation", "quality_findings", {
                "finding_id": f"qf-{m.metric}",
                "category": "performance",
                "description": m.findings,
                "severity": "medium" if m.score >= 50.0 else "high",
                "evidence": m.evidence,
            })

    # 8. Return to Master
    exemplary = [a.agent_id for a in report.agent_evaluations if a.exemplary]
    probation = [a.agent_id for a in report.agent_evaluations if a.recommend_probation]

    return handoff_engine.create(
        sm,
        from_agent="evaluator_agent",
        to_agent="master_orchestrator",
        phase="evaluation",
        task_description="Deliver evaluation report",
        payload={
            "summary": (
                f"Evaluation complete. Overall project score: "
                f"{report.overall_project_score:.1f}/100. "
                f"{len(agents_to_evaluate)} agents evaluated. "
                f"{len(exemplary)} exemplary. {len(probation)} probation risk. "
                f"Report at: {report_path}"
            ),
            "artifacts_produced": [str(report_path)],
            "decisions_made": [],
            "open_questions": [],
            "constraints_for_next": [],
            "shared_state_fields_modified": [
                "evaluation.performance_metrics",
                "evaluation.quality_findings",
            ],
            "report_id": report.report_id,
            "report_path": str(report_path),
            "overall_project_score": report.overall_project_score,
            "agents_exemplary": exemplary,
            "agents_probation_risk": probation,
            "improvement_areas": report.recommendations.get("improvement_areas", []),
        },
    )


# ---------------------------------------------------------------------------
# Tests: Evaluation trigger
# ---------------------------------------------------------------------------

class TestEvaluationTrigger:

    def test_master_sends_evaluation_request(self, sm, engine, completed_project):
        handoff = engine.create(
            sm,
            from_agent="master_orchestrator",
            to_agent="evaluator_agent",
            phase="evaluation",
            task_description="Evaluate completed project",
            payload={
                "summary": "Project complete. Please evaluate.",
                "artifacts_produced": [],
                "decisions_made": [],
                "open_questions": [],
                "constraints_for_next": [],
                "shared_state_fields_modified": [],
            },
        )
        assert handoff["to_agent"] == "evaluator_agent"
        assert handoff["phase"] == "evaluation"


# ---------------------------------------------------------------------------
# Tests: Metric scoring on completed project
# ---------------------------------------------------------------------------

class TestMetricScoringOnCompletedProject:

    def test_documentation_completeness_with_all_docs(
        self, metrics, completed_project
    ):
        result = metrics.score_documentation_completeness(completed_project)
        # All 3 required docs exist → 80pts
        assert result.score == pytest.approx(80.0)

    def test_scope_adherence_all_complete(
        self, metrics, sm, projects_root, project_id, completed_project
    ):
        board_path = completed_project / "execution" / "task_board.yaml"
        with open(board_path) as f:
            board_data = yaml.safe_load(f)

        tasks = board_data["tasks"]
        planned = len(tasks)
        completed = sum(1 for t in tasks if t["status"] == "completed")
        blocked = sum(1 for t in tasks if t["status"] == "blocked")
        failed = sum(1 for t in tasks if t["status"] == "failed")
        over_effort = sum(1 for t in tasks if t.get("over_effort"))

        result = metrics.score_scope_adherence(
            planned, completed, blocked, failed, over_effort
        )
        assert result.score == 100.0

    def test_acceptance_criteria_pass_rate_all_complete(
        self, metrics, completed_project
    ):
        # All tasks completed → all 3 AC passed
        result = metrics.score_acceptance_criteria_pass_rate(3, 3)
        assert result.score == 100.0


# ---------------------------------------------------------------------------
# Tests: Full evaluation flow
# ---------------------------------------------------------------------------

class TestFullEvaluationFlow:

    def test_full_evaluation_cycle(
        self, sm, engine, metrics, completed_project, projects_root, project_id
    ):
        master_handoff = engine.create(
            sm,
            from_agent="master_orchestrator",
            to_agent="evaluator_agent",
            phase="evaluation",
            task_description="Evaluate completed project",
            payload={
                "summary": "Evaluate project.",
                "artifacts_produced": [],
                "decisions_made": [],
                "open_questions": [],
                "constraints_for_next": [],
                "shared_state_fields_modified": [],
            },
        )

        agents = ["master_orchestrator", "project_manager_agent"]
        eval_return = simulate_evaluator(
            sm, engine, metrics,
            master_handoff, completed_project, projects_root,
            agents_to_evaluate=agents,
        )

        assert eval_return["from_agent"] == "evaluator_agent"
        assert eval_return["to_agent"] == "master_orchestrator"
        assert "overall_project_score" in eval_return["payload"]
        assert eval_return["payload"]["overall_project_score"] > 0

    def test_report_file_exists_after_evaluation(
        self, sm, engine, metrics, completed_project, projects_root, project_id
    ):
        master_handoff = engine.create(
            sm,
            from_agent="master_orchestrator",
            to_agent="evaluator_agent",
            phase="evaluation",
            task_description="Evaluate project",
            payload={
                "summary": "Evaluate.",
                "artifacts_produced": [],
                "decisions_made": [],
                "open_questions": [],
                "constraints_for_next": [],
                "shared_state_fields_modified": [],
            },
        )

        simulate_evaluator(
            sm, engine, metrics,
            master_handoff, completed_project, projects_root,
            agents_to_evaluate=["master_orchestrator"],
        )

        report_path = completed_project / "evaluation" / "evaluation_report.yaml"
        assert report_path.exists()

        with open(report_path) as f:
            data = yaml.safe_load(f)
        assert data["project_id"] == project_id
        assert data["evaluator"] == "evaluator_agent"
        assert len(data["project_metrics"]) == 6

    def test_performance_metrics_written_to_shared_state(
        self, sm, engine, metrics, completed_project, projects_root
    ):
        master_handoff = engine.create(
            sm,
            from_agent="master_orchestrator",
            to_agent="evaluator_agent",
            phase="evaluation",
            task_description="Evaluate project",
            payload={
                "summary": "Evaluate.",
                "artifacts_produced": [],
                "decisions_made": [],
                "open_questions": [],
                "constraints_for_next": [],
                "shared_state_fields_modified": [],
            },
        )

        simulate_evaluator(
            sm, engine, metrics,
            master_handoff, completed_project, projects_root,
            agents_to_evaluate=["master_orchestrator"],
        )

        perf_metrics = sm.read("evaluation.performance_metrics")
        assert perf_metrics is not None
        assert len(perf_metrics) == 6
        for m in perf_metrics:
            assert "metric" in m
            assert "score" in m

    def test_master_accepts_evaluation_return(
        self, sm, engine, metrics, completed_project, projects_root
    ):
        master_handoff = engine.create(
            sm,
            from_agent="master_orchestrator",
            to_agent="evaluator_agent",
            phase="evaluation",
            task_description="Evaluate",
            payload={
                "summary": "Go.",
                "artifacts_produced": [],
                "decisions_made": [],
                "open_questions": [],
                "constraints_for_next": [],
                "shared_state_fields_modified": [],
            },
        )

        eval_return = simulate_evaluator(
            sm, engine, metrics,
            master_handoff, completed_project, projects_root,
            agents_to_evaluate=[],
        )
        engine.accept(sm, eval_return["handoff_id"])

        pending = engine.get_pending(sm)
        assert len(pending) == 0

    def test_handoff_count_in_evaluation_phase(
        self, sm, engine, metrics, completed_project, projects_root
    ):
        master_handoff = engine.create(
            sm,
            from_agent="master_orchestrator",
            to_agent="evaluator_agent",
            phase="evaluation",
            task_description="Evaluate",
            payload={
                "summary": "Go.",
                "artifacts_produced": [],
                "decisions_made": [],
                "open_questions": [],
                "constraints_for_next": [],
                "shared_state_fields_modified": [],
            },
        )

        eval_return = simulate_evaluator(
            sm, engine, metrics,
            master_handoff, completed_project, projects_root,
            agents_to_evaluate=[],
        )
        engine.accept(sm, eval_return["handoff_id"])

        history = sm.read("workflow.handoff_history")
        assert len(history) == 2


# ---------------------------------------------------------------------------
# Governance tests
# ---------------------------------------------------------------------------

class TestEvaluationGovernance:

    def test_no_violations_in_evaluation_flow(
        self, sm, engine, metrics, completed_project, projects_root
    ):
        master_handoff = engine.create(
            sm,
            from_agent="master_orchestrator",
            to_agent="evaluator_agent",
            phase="evaluation",
            task_description="Evaluate",
            payload={
                "summary": "Go.",
                "artifacts_produced": [],
                "decisions_made": [],
                "open_questions": [],
                "constraints_for_next": [],
                "shared_state_fields_modified": [],
            },
        )

        simulate_evaluator(
            sm, engine, metrics,
            master_handoff, completed_project, projects_root,
            agents_to_evaluate=[],
        )

        for agent in ["master_orchestrator", "evaluator_agent"]:
            assert sm.get_violation_count(agent) == 0

    def test_evaluator_cannot_approve_own_findings(self, sm):
        sm.write("evaluator_agent", "evaluation", "performance_metrics", [])
        result = sm.approve("evaluator_agent", "evaluation", "performance_metrics")
        assert not result.success
        assert result.reason == "only_master_can_approve"

    def test_evaluator_cannot_write_to_approvals(self, sm):
        result = sm.write("evaluator_agent", "decisions", "approvals",
                          [{"approval": "test"}])
        assert not result.success
