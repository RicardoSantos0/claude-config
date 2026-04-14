"""
Integration Test — Inquirer → Master → Product Manager: Intake to Plan
Tests the full flow:
  1. Master sends brief to Inquirer
  2. Inquirer analyzes and builds spec via Q&A
  3. Inquirer hands off to Master
  4. Master hands off to Product Manager
  5. Product Manager output validates against schema

Tests the Python infrastructure, not the agent's reasoning.
"""
import pytest
import yaml
from pathlib import Path
from datetime import datetime, timezone
from core.engine.shared_state_manager import SharedStateManager
from core.engine.handoff_engine import HandoffEngine
from core.intake_checker import IntakeChecker


@pytest.fixture
def project_id():
    return "proj-20260409-002"


@pytest.fixture
def projects_root(tmp_path):
    return tmp_path / "projects_root"


@pytest.fixture
def sm(projects_root, project_id):
    manager = SharedStateManager(project_id, projects_root=projects_root)
    manager.initialize(request_id="req-20260409-002")
    return manager


@pytest.fixture
def engine():
    return HandoffEngine()


@pytest.fixture
def checker():
    return IntakeChecker()


@pytest.fixture
def raw_brief():
    return "We need a sales reporting dashboard that connects to Salesforce and shows pipeline metrics."


@pytest.fixture
def clarified_spec():
    """Spec that reaches quality threshold after one Q&A round."""
    return {
        "project_goal": "Build a web-based sales reporting dashboard integrated with Salesforce",
        "problem_statement": "Sales team lacks real-time visibility into pipeline metrics, causing delayed forecasting",
        "scope": {
            "inclusions": ["Dashboard UI", "Salesforce CRM integration", "Pipeline metric views"],
            "exclusions": ["Mobile app", "Real-time push notifications", "Custom reports builder"],
        },
        "constraints": "Must use existing AWS infrastructure; budget capped at $40k; 3-person team",
        "success_criteria": "Dashboard adopted by >80% of sales team within 30 days of launch; pipeline data refreshed every 15 minutes",
        "expected_outputs": ["Deployed web dashboard", "Admin setup guide", "User documentation"],
        "stakeholders": "VP Sales (sponsor), Sales Ops (primary users), Engineering (maintainers)",
        "dependencies": "Salesforce CRM API, AWS account with existing VPC, internal SSO service",
        "timeline_expectations": "Production launch by end of Q2 2026 (June 30)",
        "quality_expectations": "Production-ready; >99% uptime; WCAG 2.1 AA accessibility",
        "prior_art": "Previous Tableau attempt abandoned Q4 2025 due to licensing cost and performance issues",
    }


def simulate_inquirer(
    sm: SharedStateManager,
    engine: HandoffEngine,
    checker: IntakeChecker,
    master_handoff: dict,
    spec: dict,
    projects_root: Path,
) -> dict:
    """
    Simulate the Inquirer's intake processing.
    In production the agent does this; here we test the infrastructure.
    """
    pid = sm.project_id
    handoff_id = master_handoff["handoff_id"]

    # 1. Accept the handoff from Master
    engine.accept(sm, handoff_id)

    # 2. Store original brief
    sm.write("inquirer_agent", "project_definition", "original_brief",
             master_handoff["payload"]["original_brief"])

    # 3. Analyze spec
    result = checker.analyze(spec)
    assert result.ready_for_handoff, (
        f"Test spec should be ready for handoff, score={result.score}"
    )

    # 4. Write clarified spec to disk
    intake_dir = projects_root / pid / "intake"
    intake_dir.mkdir(parents=True, exist_ok=True)
    import core.intake_checker as ic
    # Write via the checker (uses ROOT path) — we'll write directly for testing
    spec_output = {
        "project_id": pid,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": "inquirer_agent",
        "quality_score": result.score,
        "ready_for_handoff": result.ready_for_handoff,
        "specification": spec,
        "unresolved": result.required_missing + result.ambiguous,
    }
    spec_path = intake_dir / "clarified_spec.yaml"
    with open(spec_path, "w", encoding="utf-8") as f:
        yaml.dump(spec_output, f, default_flow_style=False,
                  allow_unicode=True, sort_keys=False)

    # 5. Update shared state with clarified spec
    sm.write("inquirer_agent", "project_definition", "clarified_specification", spec)

    # 6. Return handoff to Master
    return engine.create(
        sm,
        from_agent="inquirer_agent",
        to_agent="master_orchestrator",
        phase="intake",
        task_description="Deliver clarified specification",
        payload={
            "summary": (
                f"Specification complete. Score: {result.score:.4f}. "
                f"Ready: {result.ready_for_handoff}. "
                f"Spec at: projects/{pid}/intake/clarified_spec.yaml"
            ),
            "artifacts_produced": [],
            "decisions_made": [],
            "open_questions": result.required_missing,
            "constraints_for_next": [],
            "shared_state_fields_modified": [
                "project_definition.original_brief",
                "project_definition.clarified_specification",
            ],
            "quality_score": result.score,
            "ready_for_handoff": result.ready_for_handoff,
        },
    )


def simulate_product_manager(
    sm: SharedStateManager,
    engine: HandoffEngine,
    master_handoff: dict,
    projects_root: Path,
) -> dict:
    """
    Simulate the Product Manager's planning work.
    In production the agent does this; here we test the infrastructure.
    """
    pid = sm.project_id
    handoff_id = master_handoff["handoff_id"]

    # 1. Accept handoff from Master
    engine.accept(sm, handoff_id)

    # 2. Read clarified spec from shared state
    spec = sm.read("project_definition.clarified_specification")
    assert spec is not None, "Clarified specification must be in shared state"

    # 3. Build product plan
    now = datetime.now(timezone.utc).isoformat()
    product_plan = {
        "project_id": pid,
        "created_at": now,
        "created_by": "product_manager_agent",
        "version": 1,
        "status": "draft",
        "product_goal": spec.get("project_goal", ""),
        "requirements": {
            "must_have": [
                {
                    "id": "req-001",
                    "description": "Web-based dashboard displaying Salesforce pipeline metrics",
                    "source": "scope_inclusions + project_goal",
                    "acceptance_criteria": [
                        "Given a logged-in sales user, when they open the dashboard, "
                        "then pipeline metrics are displayed within 3 seconds",
                        "Given dashboard is running, when Salesforce data updates, "
                        "then dashboard reflects changes within 15 minutes",
                    ],
                },
                {
                    "id": "req-002",
                    "description": "Salesforce CRM API integration",
                    "source": "scope_inclusions",
                    "acceptance_criteria": [
                        "Given valid Salesforce credentials, when the integration is configured, "
                        "then pipeline data is fetched without manual intervention",
                    ],
                },
            ],
            "should_have": [],
            "could_have": [],
            "wont_have": [
                {
                    "id": "req-oos-001",
                    "description": "Mobile application",
                    "source": "scope_exclusions",
                    "acceptance_criteria": None,
                },
            ],
        },
        "constraints_summary": [
            "Must use existing AWS infrastructure",
            "Budget capped at $40k",
            "3-person engineering team",
        ],
        "risks": [
            {
                "id": "risk-001",
                "description": "Salesforce API rate limits may affect data freshness",
                "severity": "medium",
                "mitigation": "Implement caching layer with 15-minute refresh",
            }
        ],
        "open_questions": [],
        "approval_status": "pending_master_review",
    }

    # 4. Write plan to disk
    planning_dir = projects_root / pid / "planning"
    planning_dir.mkdir(parents=True, exist_ok=True)
    plan_path = planning_dir / "product_plan.yaml"
    with open(plan_path, "w", encoding="utf-8") as f:
        yaml.dump(product_plan, f, default_flow_style=False,
                  allow_unicode=True, sort_keys=False)

    # 5. Write project goal to shared state
    sm.write("product_manager_agent", "project_definition", "project_goal",
             product_plan["product_goal"])

    # 6. Return handoff to Master
    return engine.create(
        sm,
        from_agent="product_manager_agent",
        to_agent="master_orchestrator",
        phase="specification",
        task_description="Deliver product plan for review",
        payload={
            "summary": (
                f"Product plan written to projects/{pid}/planning/product_plan.yaml. "
                f"{len(product_plan['requirements']['must_have'])} must-have requirements, "
                f"{len(product_plan['risks'])} risks identified. Awaiting Master approval."
            ),
            "artifacts_produced": [],
            "decisions_made": [],
            "open_questions": [],
            "constraints_for_next": [],
            "shared_state_fields_modified": ["project_definition.project_goal"],
            "plan_path": f"projects/{pid}/planning/product_plan.yaml",
        },
    )


class TestIntakeToProductPlan:

    def test_master_sends_brief_to_inquirer(self, sm, engine, raw_brief):
        """Master can create a handoff to Inquirer with a raw brief."""
        handoff = engine.create(
            sm,
            from_agent="master_orchestrator",
            to_agent="inquirer_agent",
            phase="intake",
            task_description="Conduct structured intake of project brief",
            payload={
                "summary": "New project brief received. Conduct intake and produce clarified spec.",
                "artifacts_produced": [],
                "decisions_made": [],
                "open_questions": [],
                "constraints_for_next": [],
                "shared_state_fields_modified": [],
                "original_brief": raw_brief,
            },
        )
        assert handoff["to_agent"] == "inquirer_agent"
        assert handoff["payload"]["original_brief"] == raw_brief

    def test_inquirer_spec_reaches_quality_threshold(self, checker, clarified_spec):
        """The clarified spec fixture must reach quality threshold."""
        result = checker.analyze(clarified_spec)
        assert result.score >= 0.85
        assert result.ready_for_handoff

    def test_full_intake_to_plan_cycle(
        self, sm, engine, checker, clarified_spec, raw_brief, projects_root, project_id
    ):
        """Full cycle: Master → Inquirer → Master → Product Manager → Master."""

        # === Phase: intake ===
        # 1. Master creates project folder (simplified — no Scribe in this test)
        project_dir = projects_root / project_id
        project_dir.mkdir(parents=True, exist_ok=True)

        # 2. Master sends brief to Inquirer
        inquirer_handoff = engine.create(
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

        # 3. Inquirer processes and returns
        inquirer_return = simulate_inquirer(
            sm, engine, checker, inquirer_handoff, clarified_spec, projects_root
        )

        # 4. Master accepts Inquirer's return
        engine.accept(sm, inquirer_return["handoff_id"])

        # Verify: clarified spec is in shared state
        stored_spec = sm.read("project_definition.clarified_specification")
        assert stored_spec is not None
        assert stored_spec["project_goal"] == clarified_spec["project_goal"]

        # Verify: clarified_spec.yaml exists on disk
        spec_path = projects_root / project_id / "intake" / "clarified_spec.yaml"
        assert spec_path.exists()

        # === Phase: specification ===
        # 5. Master advances phase
        sm.write("master_orchestrator", "core_identity", "current_phase", "specification")

        # 6. Master sends spec to Product Manager
        pm_handoff = engine.create(
            sm,
            from_agent="master_orchestrator",
            to_agent="product_manager_agent",
            phase="specification",
            task_description="Produce product plan from clarified specification",
            payload={
                "summary": "Clarified specification ready. Produce product plan.",
                "artifacts_produced": [],
                "decisions_made": [],
                "open_questions": [],
                "constraints_for_next": [],
                "shared_state_fields_modified": [],
            },
        )

        # 7. Product Manager processes and returns
        pm_return = simulate_product_manager(
            sm, engine, pm_handoff, projects_root
        )

        # 8. Master accepts PM's return
        engine.accept(sm, pm_return["handoff_id"])

        # === Verify final outcomes ===

        # Product plan exists on disk
        plan_path = projects_root / project_id / "planning" / "product_plan.yaml"
        assert plan_path.exists()

        # Product plan is valid YAML
        with open(plan_path, encoding="utf-8") as f:
            plan = yaml.safe_load(f)
        assert plan["project_id"] == project_id
        assert plan["created_by"] == "product_manager_agent"
        assert plan["approval_status"] == "pending_master_review"

        # Project goal in shared state
        goal = sm.read("project_definition.project_goal")
        assert goal and len(goal) > 0

        # All handoffs are accepted (none pending)
        pending = engine.get_pending(sm)
        assert len(pending) == 0

        # Total handoffs: Master→Inquirer, Inquirer→Master, Master→PM, PM→Master = 4
        history = sm.read("workflow.handoff_history")
        assert len(history) == 4

    def test_original_brief_stored_in_shared_state(self, sm, engine, checker,
                                                    clarified_spec, raw_brief, projects_root):
        """After intake, original_brief must be in shared state."""
        inquirer_handoff = engine.create(
            sm,
            from_agent="master_orchestrator",
            to_agent="inquirer_agent",
            phase="intake",
            task_description="Intake",
            payload={
                "summary": "Test",
                "artifacts_produced": [],
                "decisions_made": [],
                "open_questions": [],
                "constraints_for_next": [],
                "shared_state_fields_modified": [],
                "original_brief": raw_brief,
            },
        )
        simulate_inquirer(sm, engine, checker, inquirer_handoff, clarified_spec, projects_root)

        stored_brief = sm.read("project_definition.original_brief")
        assert stored_brief == raw_brief

    def test_phase_advances_after_intake(self, sm, engine, checker,
                                         clarified_spec, raw_brief, projects_root):
        """Master can advance to specification phase after intake completes."""
        inquirer_handoff = engine.create(
            sm,
            from_agent="master_orchestrator",
            to_agent="inquirer_agent",
            phase="intake",
            task_description="Intake",
            payload={
                "summary": "Test",
                "artifacts_produced": [],
                "decisions_made": [],
                "open_questions": [],
                "constraints_for_next": [],
                "shared_state_fields_modified": [],
                "original_brief": raw_brief,
            },
        )
        simulate_inquirer(sm, engine, checker, inquirer_handoff, clarified_spec, projects_root)

        result = sm.write("master_orchestrator", "core_identity",
                          "current_phase", "specification")
        assert result.success

        phase = sm.read("core_identity.current_phase")
        assert phase == "specification"

    def test_inquirer_cannot_approve_own_spec(self, sm):
        """Only master_orchestrator can approve fields."""
        sm.write("inquirer_agent", "project_definition", "original_brief", "Brief")
        result = sm.approve("inquirer_agent", "project_definition", "original_brief")
        assert not result.success
        assert result.reason == "only_master_can_approve"

    def test_no_governance_violations_in_normal_flow(
        self, sm, engine, checker, clarified_spec, raw_brief, projects_root
    ):
        """Normal intake flow must not generate governance violations."""
        inquirer_handoff = engine.create(
            sm,
            from_agent="master_orchestrator",
            to_agent="inquirer_agent",
            phase="intake",
            task_description="Intake",
            payload={
                "summary": "Test",
                "artifacts_produced": [],
                "decisions_made": [],
                "open_questions": [],
                "constraints_for_next": [],
                "shared_state_fields_modified": [],
                "original_brief": raw_brief,
            },
        )
        simulate_inquirer(sm, engine, checker, inquirer_handoff, clarified_spec, projects_root)

        for agent in ["master_orchestrator", "inquirer_agent", "product_manager_agent"]:
            assert sm.get_violation_count(agent) == 0
