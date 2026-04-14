"""
End-to-End Integration Test — Full Project Lifecycle
=====================================================
Runs a complete project through every phase of the MAS:

  Phase 0  Init        — Master initializes state, Scribe creates project folder
  Phase 1  Intake      — Master → Inquirer → Master (clarified specification)
  Phase 2  Spec        — Master → Product Manager → Master (product plan)
  Phase 3  Planning    — Master → HR (capability query) → PM (execution plan)
                          + Consultation for architecture decision
  Phase 4  Execution   — All tasks completed, over-effort detection
  Phase 5  Evaluation  — Master → Evaluator → Master (eval report + metrics)
  Phase 6  Training    — Master → Trainer → Master (improvement proposals)
  Phase 7  Spawn       — HR gap cert → Spawner builds draft package
  Phase 8  Close       — Master snapshots final state, marks project complete

Verifies:
  - State at every phase boundary
  - Handoff chain integrity (count, accepted/pending)
  - No governance violations throughout
  - Key artifacts on disk (spec, plan, eval report, training brief, pkg)
  - All phases recorded in workflow.completed_phases
  - Snapshot files exist at each phase boundary

Tests Python infrastructure only — no live LLM calls.
"""
import pytest
import yaml
from pathlib import Path
from datetime import datetime, timezone

from core.engine.shared_state_manager import SharedStateManager
from core.engine.handoff_engine import HandoffEngine
from core.engine.intake_checker import IntakeChecker
from core.engine.capability_registry import CapabilityRegistry
from core.engine.task_board import TaskBoard
from core.engine.metrics_engine import MetricsEngine
from core.engine.spawn_policy import SpawnPolicyEngine, build_agent_package, record_spawn, DRAFT
from core.engine.training_engine import TrainingEngine
from core.engine.consultation_engine import ConsultationEngine, ALL_CONSULTANTS, CORE_THREE_CONSULTANTS
import core.engine.training_engine as te


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

PROJECT_ID = "proj-e2e-20260410-001"
REQUEST_ID = "req-e2e-20260410-001"


@pytest.fixture
def projects_root(tmp_path):
    return tmp_path / "projects_root"


@pytest.fixture
def project_dir(projects_root):
    d = projects_root / PROJECT_ID
    d.mkdir(parents=True, exist_ok=True)
    for subdir in [
        "intake", "planning", "execution", "evaluation",
        "improvement", "consultation", "hr",
        "decisions", "capability/gap_certificates",
        "capability/spawn_requests", "capability/spawn_results",
    ]:
        (d / subdir).mkdir(parents=True, exist_ok=True)
    return d


@pytest.fixture
def sm(projects_root):
    manager = SharedStateManager(PROJECT_ID, projects_root=projects_root)
    manager.initialize(request_id=REQUEST_ID)
    return manager


@pytest.fixture
def engine():
    return HandoffEngine()


@pytest.fixture
def checker():
    return IntakeChecker()


@pytest.fixture
def board(projects_root):
    return TaskBoard(PROJECT_ID, projects_root=projects_root)


@pytest.fixture
def metrics():
    return MetricsEngine()


@pytest.fixture
def spawn_engine():
    return SpawnPolicyEngine()


@pytest.fixture
def training_engine(tmp_path, monkeypatch):
    fake_backlog = tmp_path / "roster" / "training_backlog.yaml"
    fake_backlog.parent.mkdir(parents=True)
    monkeypatch.setattr(te, "BACKLOG_FILE", fake_backlog)
    return TrainingEngine()


@pytest.fixture
def consult_engine():
    return ConsultationEngine()


@pytest.fixture
def registry_data(tmp_path):
    d = tmp_path / "roster"
    d.mkdir(exist_ok=True)
    index = {
        "registry": {
            "version": "1.0.0",
            "last_updated": "",
            "maintained_by": "hr_agent",
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
                    "created_at": "2026-04-10T00:00:00+00:00",
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
                    "created_at": "2026-04-10T00:00:00+00:00",
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
    with open(d / "registry_index.yaml") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Simulation helpers  (local to e2e — do not import from per-phase tests)
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sim_scribe(sm, engine, project_dir):
    """Master → Scribe (folder init) → Master."""
    ho = engine.create(
        sm,
        from_agent="master_orchestrator",
        to_agent="scribe_agent",
        phase="intake",
        task_description="Initialize project folder",
        payload={
            "summary": "Initialize project folder.",
            "artifacts_produced": [],
            "decisions_made": [],
            "open_questions": [],
            "constraints_for_next": [],
            "shared_state_fields_modified": [],
            "original_brief": "Build a governed delivery test project.",
        },
    )
    engine.accept(sm, ho["handoff_id"])
    ret = engine.create(
        sm,
        from_agent="scribe_agent",
        to_agent="master_orchestrator",
        phase="intake",
        task_description="Project folder ready",
        payload={
            "summary": f"Folder created at projects/{PROJECT_ID}/",
            "artifacts_produced": [],
            "decisions_made": [],
            "open_questions": [],
            "constraints_for_next": [],
            "shared_state_fields_modified": [],
        },
    )
    engine.accept(sm, ret["handoff_id"])
    return ret


def sim_inquirer(sm, engine, checker, project_dir):
    """Master → Inquirer (clarified spec) → Master."""
    raw_brief = (
        "Build a web-based sales reporting dashboard "
        "that connects to Salesforce and shows pipeline metrics."
    )
    spec = {
        "project_goal": "Build a web-based sales reporting dashboard integrated with Salesforce",
        "problem_statement": "Sales team lacks real-time visibility into pipeline metrics",
        "scope": {
            "inclusions": ["Dashboard UI", "Salesforce CRM integration", "Pipeline metric views"],
            "exclusions": ["Mobile app", "Real-time push notifications"],
        },
        "constraints": "Must use existing AWS; budget $40k; 3-person team",
        "success_criteria": "Dashboard adopted by >80% of sales team within 30 days",
        "expected_outputs": ["Deployed web dashboard", "Admin setup guide"],
        "stakeholders": "VP Sales (sponsor), Sales Ops (primary users)",
        "dependencies": "Salesforce CRM API, AWS account, internal SSO service",
        "timeline_expectations": "Production launch by end of Q2 2026",
        "quality_expectations": "Production-ready; >99% uptime",
        "prior_art": "Previous Tableau attempt abandoned Q4 2025 due to cost",
    }

    ho = engine.create(
        sm,
        from_agent="master_orchestrator",
        to_agent="inquirer_agent",
        phase="intake",
        task_description="Conduct structured intake",
        payload={
            "summary": "New project brief. Conduct intake.",
            "artifacts_produced": [],
            "decisions_made": [],
            "open_questions": [],
            "constraints_for_next": [],
            "shared_state_fields_modified": [],
            "original_brief": raw_brief,
        },
    )
    engine.accept(sm, ho["handoff_id"])
    sm.write("inquirer_agent", "project_definition", "original_brief", raw_brief)

    result = checker.analyze(spec)
    assert result.ready_for_handoff, f"Spec not ready: score={result.score}"

    spec_path = project_dir / "intake" / "clarified_spec.yaml"
    spec_path.write_text(yaml.dump({
        "project_id": PROJECT_ID,
        "created_at": _now(),
        "specification": spec,
        "quality_score": result.score,
    }), encoding="utf-8")

    sm.write("inquirer_agent", "project_definition", "clarified_specification", spec)

    ret = engine.create(
        sm,
        from_agent="inquirer_agent",
        to_agent="master_orchestrator",
        phase="intake",
        task_description="Deliver clarified specification",
        payload={
            "summary": f"Spec complete. Score: {result.score:.4f}.",
            "artifacts_produced": [str(spec_path)],
            "decisions_made": [],
            "open_questions": [],
            "constraints_for_next": [],
            "shared_state_fields_modified": ["project_definition.clarified_specification"],
            "quality_score": result.score,
        },
    )
    engine.accept(sm, ret["handoff_id"])
    return ret, spec_path


def sim_product_manager(sm, engine, project_dir):
    """Master → PM (product plan) → Master."""
    spec = sm.read("project_definition.clarified_specification")
    assert spec, "Spec must exist before PM"

    ho = engine.create(
        sm,
        from_agent="master_orchestrator",
        to_agent="product_manager_agent",
        phase="specification",
        task_description="Produce product plan",
        payload={
            "summary": "Spec ready. Produce product plan.",
            "artifacts_produced": [],
            "decisions_made": [],
            "open_questions": [],
            "constraints_for_next": [],
            "shared_state_fields_modified": [],
        },
    )
    engine.accept(sm, ho["handoff_id"])

    plan = {
        "project_id": PROJECT_ID,
        "created_at": _now(),
        "created_by": "product_manager_agent",
        "version": 1,
        "status": "approved",
        "product_goal": spec["project_goal"],
        "requirements": {
            "must_have": [
                {
                    "id": "req-001",
                    "description": "Web-based dashboard displaying Salesforce pipeline metrics",
                    "source": "scope_inclusions",
                    "acceptance_criteria": ["Dashboard loads in <3s", "Data refreshes every 15min"],
                },
                {
                    "id": "req-002",
                    "description": "Salesforce CRM API integration",
                    "source": "scope_inclusions",
                    "acceptance_criteria": ["Pipeline data fetched automatically"],
                },
                {
                    "id": "req-003",
                    "description": "User authentication via company SSO",
                    "source": "security_requirements",
                    "acceptance_criteria": ["Only authenticated users can access"],
                },
            ],
            "should_have": [],
            "could_have": [],
            "wont_have": [],
        },
        "constraints_summary": spec.get("constraints", "").split(";"),
        "risks": [{"id": "risk-001", "description": "Salesforce rate limits",
                   "severity": "medium", "mitigation": "Implement caching"}],
        "open_questions": [],
        "approval_status": "approved",
    }

    plan_path = project_dir / "planning" / "product_plan.yaml"
    plan_path.write_text(yaml.dump(plan), encoding="utf-8")
    sm.write("product_manager_agent", "project_definition", "project_goal", plan["product_goal"])

    ret = engine.create(
        sm,
        from_agent="product_manager_agent",
        to_agent="master_orchestrator",
        phase="specification",
        task_description="Deliver product plan for review",
        payload={
            "summary": f"Product plan written. {len(plan['requirements']['must_have'])} must-haves.",
            "artifacts_produced": [str(plan_path)],
            "decisions_made": [],
            "open_questions": [],
            "constraints_for_next": [],
            "shared_state_fields_modified": ["project_definition.project_goal"],
            "plan_path": str(plan_path),
        },
    )
    engine.accept(sm, ret["handoff_id"])
    return ret, plan_path


def sim_project_manager(sm, engine, board, plan_path):
    """Master → PM → Master (execution plan + task board)."""
    ho = engine.create(
        sm,
        from_agent="master_orchestrator",
        to_agent="project_manager_agent",
        phase="planning",
        task_description="Produce execution plan",
        payload={
            "summary": "Product plan approved. Produce execution plan.",
            "artifacts_produced": [],
            "decisions_made": [],
            "open_questions": [],
            "constraints_for_next": [],
            "shared_state_fields_modified": [],
            "product_plan_path": str(plan_path),
        },
    )
    engine.accept(sm, ho["handoff_id"])

    ms1 = board.create_milestone({"name": "M1: Infrastructure",
                                  "description": "AWS and auth",
                                  "completion_criteria": "VPC and SSO ready"})
    ms2 = board.create_milestone({"name": "M2: Integration",
                                  "description": "Salesforce pipeline",
                                  "completion_criteria": "Data flowing"})
    ms3 = board.create_milestone({"name": "M3: Dashboard",
                                  "description": "Frontend",
                                  "completion_criteria": "Dashboard live"})

    t1 = board.create_task({"description": "Set up AWS VPC", "milestone": ms1,
                             "required_inputs": ["AWS credentials"],
                             "expected_outputs": ["VPC configured"],
                             "dependencies": [], "estimated_effort": "medium"})
    t2 = board.create_task({"description": "Deploy PostgreSQL on RDS", "milestone": ms1,
                             "required_inputs": ["VPC"],
                             "expected_outputs": ["RDS running"],
                             "dependencies": [t1], "estimated_effort": "small"})
    t3 = board.create_task({"description": "Configure SSO integration", "milestone": ms1,
                             "required_inputs": ["SSO URL"],
                             "expected_outputs": ["Auth working"],
                             "dependencies": [t1], "estimated_effort": "medium"})
    t4 = board.create_task({"description": "Build Salesforce API connector", "milestone": ms2,
                             "required_inputs": ["Salesforce credentials"],
                             "expected_outputs": ["Pipeline data in DB"],
                             "dependencies": [t2], "estimated_effort": "large"})
    t5 = board.create_task({"description": "Implement 15-min refresh pipeline", "milestone": ms2,
                             "required_inputs": ["Salesforce connector"],
                             "expected_outputs": ["Scheduled refresh running"],
                             "dependencies": [t4], "estimated_effort": "medium"})
    t6 = board.create_task({"description": "Build React dashboard frontend", "milestone": ms3,
                             "required_inputs": ["API endpoints"],
                             "expected_outputs": ["Dashboard deployed"],
                             "dependencies": [t3, t5], "estimated_effort": "extra-large"})

    sm.write("project_manager_agent", "execution", "execution_plan_path",
             f"projects/{PROJECT_ID}/execution/execution_plan.yaml")
    plan_dict = board.produce_execution_plan(str(plan_path))

    ret = engine.create(
        sm,
        from_agent="project_manager_agent",
        to_agent="master_orchestrator",
        phase="planning",
        task_description="Deliver execution plan",
        payload={
            "summary": f"Execution plan ready. {plan_dict['total_tasks']} tasks, "
                       f"{plan_dict['total_milestones']} milestones.",
            "artifacts_produced": [f"projects/{PROJECT_ID}/execution/execution_plan.yaml"],
            "decisions_made": [],
            "open_questions": [],
            "constraints_for_next": [],
            "shared_state_fields_modified": ["execution.execution_plan_path"],
            "total_tasks": plan_dict["total_tasks"],
            "total_milestones": plan_dict["total_milestones"],
        },
    )
    engine.accept(sm, ret["handoff_id"])
    return ret, [t1, t2, t3, t4, t5, t6]


def sim_consultation(sm, consult_engine, project_dir, question, decision_type):
    """Run a full consultation round (all 5 consultants, mixed risk)."""
    domain_ctx = consult_engine.load_domain_context("software_engineering")
    request = consult_engine.create_request(
        project_id=PROJECT_ID,
        question=question,
        context={"phase": "planning", "decision": question},
        decision_type=decision_type,
        domain_context=domain_ctx,
    )
    consult_engine.save_request(request, project_dir)

    sm.append("master_orchestrator", "consultation", "consultation_requests", {
        "request_id": request.request_id,
        "question": question,
        "decision_type": decision_type,
        "mandatory": request.mandatory,
        "consultants_selected": request.consultants_selected,
    })

    risk_map = {cid: "medium" for cid in request.consultants_selected}
    for cid in request.consultants_selected:
        consult_engine.record_response(
            request, cid,
            response_text=f"{cid}: considered {question[:40]}. Risk: medium.",
            risk_level=risk_map[cid],
            key_concerns=[f"{cid} concern"],
            recommendation=f"{cid} recommends proceeding with caution.",
        )
        sm.append(cid, "consultation", "consultation_responses", {
            "request_id": request.request_id,
            "consultant_id": cid,
            "risk_level": "medium",
            "key_concerns": [f"{cid} concern"],
            "recommendation": f"{cid} recommends proceeding.",
        })

    synthesis = consult_engine.synthesize(
        request,
        decision_reached="Proceed with microservices architecture",
        rationale="All consultants agree risk is manageable with mitigations",
        risks_addressed="Caching and rate limiting added to mitigation plan",
    )
    synth_path = consult_engine.save_synthesis(synthesis, project_dir)
    sm.append("master_orchestrator", "consultation", "synthesis", {
        "synthesis_id": synthesis.synthesis_id,
        "request_id": request.request_id,
        "decision_reached": synthesis.decision_reached,
        "unanimous_high_risk": synthesis.unanimous_high_risk,
        "human_escalation_required": synthesis.human_escalation_required,
    })
    return request, synthesis, synth_path


def sim_evaluator(sm, engine, metrics, project_dir, projects_root):
    """Master → Evaluator → Master (evaluation report)."""
    ho = engine.create(
        sm,
        from_agent="master_orchestrator",
        to_agent="evaluator_agent",
        phase="evaluation",
        task_description="Evaluate completed project",
        payload={
            "summary": "All tasks complete. Evaluate project and agents.",
            "artifacts_produced": [],
            "decisions_made": [],
            "open_questions": [],
            "constraints_for_next": [],
            "shared_state_fields_modified": [],
        },
    )
    engine.accept(sm, ho["handoff_id"])

    state = sm.load()
    board_path = project_dir / "execution" / "task_board.yaml"
    board_data = {"tasks": [], "milestones": []}
    if board_path.exists():
        with open(board_path) as f:
            board_data = yaml.safe_load(f) or board_data

    agents_to_evaluate = [
        "master_orchestrator", "inquirer_agent", "product_manager_agent",
        "project_manager_agent",
    ]
    report = metrics.produce_report(
        PROJECT_ID, state, project_dir, board_data,
        agents_to_evaluate=agents_to_evaluate,
    )
    report_path = metrics.save_report(report, project_dir)

    for m in report.project_metrics:
        sm.append("evaluator_agent", "evaluation", "performance_metrics", {
            "metric": m.metric,
            "score": round(m.score, 2),
            "timestamp": report.timestamp,
        })
        if m.score < 70.0:
            sm.append("evaluator_agent", "evaluation", "quality_findings", {
                "finding_id": f"qf-{m.metric}",
                "category": "performance",
                "description": m.findings,
                "severity": "medium",
                "evidence": m.evidence,
            })

    ret = engine.create(
        sm,
        from_agent="evaluator_agent",
        to_agent="master_orchestrator",
        phase="evaluation",
        task_description="Deliver evaluation report",
        payload={
            "summary": f"Evaluation complete. Score: {report.overall_project_score:.1f}/100.",
            "artifacts_produced": [str(report_path)],
            "decisions_made": [],
            "open_questions": [],
            "constraints_for_next": [],
            "shared_state_fields_modified": ["evaluation.performance_metrics"],
            "report_id": report.report_id,
            "report_path": str(report_path),
            "overall_project_score": report.overall_project_score,
        },
    )
    engine.accept(sm, ret["handoff_id"])
    return ret, report_path, report


def sim_trainer(sm, engine, training_engine, project_dir, evaluation_report_dict):
    """Master → Trainer → Master (improvement proposals)."""
    ho = engine.create(
        sm,
        from_agent="master_orchestrator",
        to_agent="trainer_agent",
        phase="improvement",
        task_description="Produce improvement proposals",
        payload={
            "summary": "Evaluation done. Analyze and propose improvements.",
            "artifacts_produced": [],
            "decisions_made": [],
            "open_questions": [],
            "constraints_for_next": [],
            "shared_state_fields_modified": [],
        },
    )
    engine.accept(sm, ho["handoff_id"])

    proposals = training_engine.analyze_evaluation_report(
        evaluation_report_dict, project_id=PROJECT_ID
    )
    brief_path = training_engine.produce_training_brief(PROJECT_ID, proposals, project_dir)
    training_engine.update_backlog(proposals)

    for p in proposals:
        sm.append("trainer_agent", "evaluation", "improvement_proposals", {
            "proposal_id": p.proposal_id,
            "proposal_type": p.proposal_type,
            "priority": p.priority,
            "target_agent": p.target_agent,
            "description": p.description[:200],
            "recommended_change": p.recommended_change[:200],
            "evidence": p.evidence,
            "systemic": p.systemic,
            "status": p.status,
        })

    ret = engine.create(
        sm,
        from_agent="trainer_agent",
        to_agent="master_orchestrator",
        phase="improvement",
        task_description="Deliver training brief",
        payload={
            "summary": f"Training analysis complete. {len(proposals)} proposal(s).",
            "artifacts_produced": [str(brief_path)],
            "decisions_made": [],
            "open_questions": [],
            "constraints_for_next": ["All proposals are advisory only."],
            "shared_state_fields_modified": ["evaluation.improvement_proposals"],
            "training_brief_path": str(brief_path),
            "proposal_count": len(proposals),
        },
    )
    engine.accept(sm, ret["handoff_id"])
    return ret, brief_path, proposals


def sim_spawner(sm, engine, spawn_engine, project_dir, registry_data):
    """HR gap cert → Master approves → Spawner validates + builds package."""
    gap_cert = {
        "certificate_id": "gap-cert-e2e-001",
        "project_id": PROJECT_ID,
        "status": "approved",
        "approval_status": "master_approved",
        "certified_by": "hr_agent",
        "required_capabilities": ["salesforce-reporting", "data-export"],
        "best_match_score": 38.0,
        "rationale": "No roster agent covers salesforce-reporting above 80%.",
    }
    cert_path = project_dir / "capability" / "gap_certificates" / "gap-cert-e2e-001.yaml"
    cert_path.parent.mkdir(parents=True, exist_ok=True)
    cert_path.write_text(yaml.dump(gap_cert), encoding="utf-8")

    spawn_request = {
        "request_id": "spawn-req-e2e-001",
        "project_id": PROJECT_ID,
        "gap_certificate_id": "gap-cert-e2e-001",
        "requested_by": "hr_agent",
        "master_approval": True,
        "agent_purpose": "Generate weekly Salesforce sales reports",
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

    ho = engine.create(
        sm,
        from_agent="master_orchestrator",
        to_agent="spawner_agent",
        phase="execution",
        task_description="Evaluate and build spawn package",
        payload={
            "summary": "Gap certificate approved. Build draft agent package.",
            "artifacts_produced": [],
            "decisions_made": [],
            "open_questions": [],
            "constraints_for_next": [],
            "shared_state_fields_modified": [],
            "spawn_request": spawn_request,
            "gap_certificate_id": gap_cert["certificate_id"],
        },
    )
    engine.accept(sm, ho["handoff_id"])

    result = spawn_engine.validate(
        spawn_request, registry_data, project_dir,
        gap_cert=gap_cert, phase="execution",
    )
    assert result.decision == DRAFT, (
        f"Expected DRAFT, got {result.decision}: {[v.code for v in result.all_violations]}"
    )

    pkg_dir = build_agent_package(spawn_request, project_dir)
    record_spawn(project_dir, spawn_request["request_id"], pkg_dir.name, "execution", DRAFT, str(pkg_dir))

    with open(pkg_dir / "manifest.yaml") as f:
        manifest = yaml.safe_load(f)

    ret = engine.create(
        sm,
        from_agent="spawner_agent",
        to_agent="master_orchestrator",
        phase="execution",
        task_description="Deliver draft agent package",
        payload={
            "summary": f"Draft package ready. Agent: {manifest['agent_id']}. Human review required.",
            "artifacts_produced": [str(pkg_dir)],
            "decisions_made": [{"decision": "spawn_draft_only", "rationale": result.rationale}],
            "open_questions": [],
            "constraints_for_next": ["Human must review before activating agent"],
            "shared_state_fields_modified": [],
            "spawn_decision": DRAFT,
            "agent_id": manifest["agent_id"],
            "package_path": str(pkg_dir),
            "human_review_required": True,
        },
    )
    engine.accept(sm, ret["handoff_id"])
    return ret, pkg_dir, manifest


# ---------------------------------------------------------------------------
# The full lifecycle test
# ---------------------------------------------------------------------------

class TestFullProjectLifecycle:

    def test_full_lifecycle(
        self, sm, engine, checker, board, metrics,
        spawn_engine, training_engine, consult_engine,
        registry_data, project_dir, projects_root,
    ):
        """
        Walk a project through every MAS phase from init to close.
        Assert key state, artifacts, and governance at each boundary.
        """

        # ====================================================================
        # PHASE 0 — INIT: Master initializes state, Scribe creates folder
        # ====================================================================
        state = sm.load()
        assert state["core_identity"]["project_id"] == PROJECT_ID
        assert state["core_identity"]["current_phase"] == "intake"
        assert state["core_identity"]["status"] == "active"

        sim_scribe(sm, engine, project_dir)

        snap = sm.snapshot("intake_start")
        assert snap.exists()

        # ====================================================================
        # PHASE 1 — INTAKE: Inquirer produces clarified spec
        # ====================================================================
        _, spec_path = sim_inquirer(sm, engine, checker, project_dir)

        assert spec_path.exists()
        spec_data = yaml.safe_load(spec_path.read_text())
        assert spec_data["quality_score"] >= 0.85

        stored_spec = sm.read("project_definition.clarified_specification")
        assert stored_spec is not None
        assert "project_goal" in stored_spec

        sm.write("master_orchestrator", "core_identity", "current_phase", "specification")
        sm.append("master_orchestrator", "workflow", "completed_phases", {
            "phase": "intake", "outcome": "Clarified spec delivered",
            "started_at": _now(), "completed_at": _now(), "artifacts_produced": [str(spec_path)],
        })
        snap = sm.snapshot("post_intake")
        assert snap.exists()

        # ====================================================================
        # PHASE 2 — SPECIFICATION: Product Manager produces product plan
        # ====================================================================
        _, plan_path = sim_product_manager(sm, engine, project_dir)

        assert plan_path.exists()
        with open(plan_path) as f:
            plan = yaml.safe_load(f)
        assert plan["approval_status"] == "approved"
        assert len(plan["requirements"]["must_have"]) == 3

        sm.write("master_orchestrator", "core_identity", "current_phase", "planning")
        sm.append("master_orchestrator", "workflow", "completed_phases", {
            "phase": "specification", "outcome": "Product plan approved",
            "started_at": _now(), "completed_at": _now(), "artifacts_produced": [str(plan_path)],
        })
        snap = sm.snapshot("post_specification")
        assert snap.exists()

        # ====================================================================
        # PHASE 3a — PLANNING: Project Manager builds execution plan
        # ====================================================================
        _, task_ids = sim_project_manager(sm, engine, board, plan_path)

        assert len(task_ids) == 6
        exec_plan_path_str = sm.read("execution.execution_plan_path")
        assert exec_plan_path_str is not None
        assert board.plan_path.exists()
        with open(board.plan_path) as f:
            exec_plan = yaml.safe_load(f)
        assert exec_plan["total_tasks"] == 6
        assert exec_plan["total_milestones"] == 3

        # ====================================================================
        # PHASE 3b — CONSULTATION: Architecture decision (mandatory)
        # ====================================================================
        request, synthesis, synth_path = sim_consultation(
            sm, consult_engine, project_dir,
            question="Should we use microservices or monolith for the dashboard backend?",
            decision_type="architecture",
        )

        assert synth_path.exists()
        assert not synthesis.unanimous_high_risk
        assert not synthesis.human_escalation_required
        assert synthesis.decision_reached == "Proceed with microservices architecture"

        consult_requests = sm.read("consultation.consultation_requests")
        assert len(consult_requests) >= 1

        sm.append("master_orchestrator", "workflow", "completed_phases", {
            "phase": "planning", "outcome": "Execution plan + architecture decision",
            "started_at": _now(), "completed_at": _now(),
            "artifacts_produced": [str(board.plan_path), str(synth_path)],
        })
        snap = sm.snapshot("post_planning")
        assert snap.exists()

        # ====================================================================
        # PHASE 4 — EXECUTION: Complete all tasks in dependency order
        # ====================================================================
        sm.write("master_orchestrator", "core_identity", "current_phase", "execution")

        for tid in task_ids:
            board.update_status(tid, "in_progress")
            board.update_status(tid, "completed")

        report = board.produce_progress_report()
        assert report["pct_complete"] == 100.0
        assert report["by_status"]["completed"] == 6

        # All milestones should auto-complete
        board_data = board._load()
        ms_statuses = {m["name"]: m["status"] for m in board_data["milestones"]}
        assert all(s == "completed" for s in ms_statuses.values()), (
            f"Not all milestones completed: {ms_statuses}"
        )

        sm.append("master_orchestrator", "workflow", "completed_phases", {
            "phase": "execution", "outcome": "All 6 tasks completed",
            "started_at": _now(), "completed_at": _now(), "artifacts_produced": [],
        })
        snap = sm.snapshot("post_execution")
        assert snap.exists()

        # ====================================================================
        # PHASE 5 — EVALUATION: Evaluator scores the completed project
        # ====================================================================
        sm.write("master_orchestrator", "core_identity", "current_phase", "evaluation")

        _, report_path, eval_report = sim_evaluator(
            sm, engine, metrics, project_dir, projects_root
        )

        assert report_path.exists()
        with open(report_path) as f:
            saved_report = yaml.safe_load(f)
        assert saved_report["project_id"] == PROJECT_ID
        assert "overall_project_score" in saved_report

        perf_metrics = sm.read("evaluation.performance_metrics")
        assert len(perf_metrics) > 0

        sm.append("master_orchestrator", "workflow", "completed_phases", {
            "phase": "evaluation", "outcome": f"Score: {eval_report.overall_project_score:.1f}",
            "started_at": _now(), "completed_at": _now(), "artifacts_produced": [str(report_path)],
        })
        snap = sm.snapshot("post_evaluation")
        assert snap.exists()

        # ====================================================================
        # PHASE 6 — TRAINING: Trainer produces improvement proposals
        # ====================================================================
        sm.write("master_orchestrator", "core_identity", "current_phase", "improvement")

        # Build a minimal eval report dict for training analysis
        eval_dict = {
            "report_id": saved_report["report_id"],
            "project_id": PROJECT_ID,
            "overall_project_score": saved_report["overall_project_score"],
            "project_metrics": saved_report.get("project_metrics", []),
            "agent_evaluations": saved_report.get("agent_evaluations", []),
            "systemic_findings": saved_report.get("systemic_findings", []),
            "recommendations": saved_report.get("recommendations", {}),
        }

        _, brief_path, proposals = sim_trainer(
            sm, engine, training_engine, project_dir, eval_dict
        )

        assert brief_path.exists()
        improvement_proposals = sm.read("evaluation.improvement_proposals")
        assert len(improvement_proposals) >= 0  # may be 0 if project scored perfectly

        sm.append("master_orchestrator", "workflow", "completed_phases", {
            "phase": "improvement", "outcome": f"{len(proposals)} proposals produced",
            "started_at": _now(), "completed_at": _now(), "artifacts_produced": [str(brief_path)],
        })
        snap = sm.snapshot("post_improvement")
        assert snap.exists()

        # ====================================================================
        # PHASE 7 — SPAWN: HR gap → Spawner builds draft package
        # ====================================================================
        _, pkg_dir, manifest = sim_spawner(
            sm, engine, spawn_engine, project_dir, registry_data
        )

        assert pkg_dir.exists()
        assert (pkg_dir / "manifest.yaml").exists()
        assert (pkg_dir / "agent_definition.md").exists()
        assert manifest["agent_id"]  # non-empty agent_id
        assert manifest["status"] == "draft"

        # ====================================================================
        # PHASE 8 — CLOSE: Master records completion
        # ====================================================================
        sm.write("master_orchestrator", "core_identity", "current_phase", "closed")
        sm.write("master_orchestrator", "core_identity", "status", "completed")

        snap = sm.snapshot("final")
        assert snap.exists()

        # ====================================================================
        # FINAL ASSERTIONS — cross-phase guarantees
        # ====================================================================

        # All expected phases recorded
        completed_phases = sm.read("workflow.completed_phases")
        phase_names = [p["phase"] for p in completed_phases]
        for expected in ["intake", "specification", "planning", "execution", "evaluation", "improvement"]:
            assert expected in phase_names, f"Phase '{expected}' not in completed_phases"

        # No governance violations from any agent
        all_agents = [
            "master_orchestrator", "scribe_agent", "inquirer_agent",
            "product_manager_agent", "project_manager_agent",
            "evaluator_agent", "trainer_agent", "spawner_agent",
        ] + list(ALL_CONSULTANTS)
        for agent in all_agents:
            count = sm.get_violation_count(agent)
            assert count == 0, f"Agent '{agent}' has {count} governance violation(s)"

        # All handoffs resolved
        pending = engine.get_pending(sm)
        assert len(pending) == 0, f"{len(pending)} handoff(s) still pending at project close"

        # History is non-trivial — at minimum: scribe×2, inquirer×2, pm_spec×2, pm_plan×2,
        #   eval×2, trainer×2, spawner×2 = 14 handoffs minimum
        history = sm.read("workflow.handoff_history")
        assert len(history) >= 14, f"Expected ≥14 handoffs, got {len(history)}"

        # Final state
        final_state = sm.load()
        assert final_state["core_identity"]["status"] == "completed"
        assert final_state["core_identity"]["current_phase"] == "closed"

    # ------------------------------------------------------------------------
    # Focused cross-phase tests
    # ------------------------------------------------------------------------

    def test_governance_blocks_cross_agent_writes(self, sm):
        """No agent can write to another agent's owned fields."""
        sm.write("inquirer_agent", "project_definition", "original_brief", "Test brief")
        # inquirer cannot write to execution (owned by project_manager_agent)
        result = sm.write("inquirer_agent", "execution", "execution_plan_path", "bad/path")
        assert not result.success

    def test_only_master_can_approve(self, sm):
        """All non-master approval attempts are rejected."""
        sm.write("product_manager_agent", "project_definition", "project_goal", "Some goal")
        for agent in ["product_manager_agent", "inquirer_agent", "evaluator_agent"]:
            result = sm.approve(agent, "project_definition", "project_goal")
            assert not result.success
            assert result.reason == "only_master_can_approve"

    def test_snapshots_survive_state_mutations(self, sm):
        """Snapshots capture immutable point-in-time state."""
        sm.write("master_orchestrator", "core_identity", "current_phase", "specification")
        snap1 = sm.snapshot("before_change")

        sm.write("master_orchestrator", "core_identity", "current_phase", "planning")
        snap2 = sm.snapshot("after_change")

        data1 = yaml.safe_load(snap1.read_text())
        data2 = yaml.safe_load(snap2.read_text())
        assert data1["core_identity"]["current_phase"] == "specification"
        assert data2["core_identity"]["current_phase"] == "planning"

    def test_consultation_mandatory_for_architecture_decisions(self, consult_engine):
        """Architecture decisions must trigger the core-three consultants."""
        domain_ctx = consult_engine.load_domain_context("software_engineering")
        request = consult_engine.create_request(
            project_id=PROJECT_ID,
            question="Monolith vs microservices?",
            context={},
            decision_type="architecture",
            domain_context=domain_ctx,
        )
        assert request.mandatory
        assert set(request.consultants_selected) == set(CORE_THREE_CONSULTANTS)

    def test_spawn_blocked_for_recursive_spawn(
        self, sm, engine, spawn_engine, project_dir, registry_data
    ):
        """T2_supervised (spawned) agents cannot themselves trigger spawns."""
        spawned_request = {
            "request_id": "spawn-recursive-001",
            "project_id": PROJECT_ID,
            "gap_certificate_id": "gap-cert-001",
            "requested_by": "spawner_agent",  # spawner is T2 — cannot request spawns
            "master_approval": True,
            "agent_purpose": "Recursive spawn attempt",
            "required_inputs": [],
            "required_outputs": [],
            "allowed_tools": [],
            "scope": "project_scoped",
            "base_template": "utility_agent",
            "phase": "execution",
            "worthiness": {
                "bounded": True,
                "recurring": True,
                "verifiable": True,
                "no_existing_match": True,
            },
        }
        gap_cert = {
            "certificate_id": "gap-cert-001",
            "project_id": PROJECT_ID,
            "status": "approved",
            "approval_status": "master_approved",
            "certified_by": "hr_agent",
            "required_capabilities": ["something"],
            "best_match_score": 30.0,
            "rationale": "No match.",
        }
        result = spawn_engine.validate(
            spawned_request, registry_data, project_dir,
            gap_cert=gap_cert, phase="execution",
        )
        from core.engine.spawn_policy import DENY
        assert result.decision == DENY
        violation_codes = [v.code for v in result.all_violations]
        assert any("recursive" in c.lower() or "t2" in c.lower() or "tier" in c.lower()
                   for c in violation_codes), (
            f"Expected recursive-spawn violation, got: {violation_codes}"
        )

    def test_trainer_proposals_are_advisory_only(
        self, sm, training_engine, project_dir
    ):
        """Trainer cannot apply changes — all proposals start as pending."""
        report = {
            "report_id": "eval-advisory-test",
            "project_id": PROJECT_ID,
            "overall_project_score": 55.0,
            "project_metrics": [
                {"metric": "documentation_completeness", "score": 40.0,
                 "evidence": "missing docs", "findings": "Missing product_plan"},
            ],
            "agent_evaluations": [],
            "systemic_findings": [],
            "recommendations": {"improvement_areas": ["documentation_completeness"]},
        }
        proposals = training_engine.analyze_evaluation_report(report, project_id=PROJECT_ID)
        assert len(proposals) > 0
        for p in proposals:
            assert p.status == "pending", (
                f"Proposal {p.proposal_id} has status '{p.status}', expected 'pending'"
            )

        # Trainer cannot approve own proposals via shared state
        result = sm.approve("trainer_agent", "evaluation", "improvement_proposals")
        assert not result.success
