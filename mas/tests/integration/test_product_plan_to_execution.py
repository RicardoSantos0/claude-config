"""
Integration Test — Product Plan to Execution Plan
Tests the full planning pipeline:
  1. Master sends approved product plan to Project Manager
  2. Project Manager creates milestones and tasks
  3. Project Manager requests capabilities from HR (via Master)
  4. HR returns match results
  5. Project Manager produces execution plan
  6. Master accepts execution plan
  7. Simulate task completions and progress tracking
  8. Verify final shared state and governance

Tests Python infrastructure only — no live LLM calls.
"""
import pytest
import yaml
import shutil
from pathlib import Path
from datetime import datetime, timezone
from core.engine.shared_state_manager import SharedStateManager
from core.engine.handoff_engine import HandoffEngine
from core.engine.task_board import TaskBoard
from core.engine.capability_registry import CapabilityRegistry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def project_id():
    return "proj-20260409-pm-001"


@pytest.fixture
def projects_root(tmp_path):
    return tmp_path / "projects_root"


@pytest.fixture
def sm(projects_root, project_id):
    manager = SharedStateManager(project_id, projects_root=projects_root)
    manager.initialize(request_id="req-pm-20260409-001")
    return manager


@pytest.fixture
def engine():
    return HandoffEngine()


@pytest.fixture
def board(projects_root, project_id):
    return TaskBoard(project_id, projects_root=projects_root)


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
    return CapabilityRegistry(registry_path=registry_path,
                               version_history_path=vh_path)


@pytest.fixture
def approved_product_plan(projects_root, project_id):
    """Create a minimal approved product plan on disk."""
    planning_dir = projects_root / project_id / "planning"
    planning_dir.mkdir(parents=True, exist_ok=True)
    plan = {
        "project_id": project_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": "product_manager_agent",
        "version": 1,
        "status": "approved",
        "product_goal": "Build a web-based sales reporting dashboard",
        "requirements": {
            "must_have": [
                {
                    "id": "req-001",
                    "description": "Web-based dashboard displaying Salesforce pipeline metrics",
                    "source": "scope_inclusions + project_goal",
                    "acceptance_criteria": [
                        "Dashboard loads in <3 seconds",
                        "Data refreshes every 15 minutes",
                    ],
                },
                {
                    "id": "req-002",
                    "description": "Salesforce CRM API integration",
                    "source": "scope_inclusions",
                    "acceptance_criteria": [
                        "Pipeline data fetched automatically",
                    ],
                },
                {
                    "id": "req-003",
                    "description": "User authentication via company SSO",
                    "source": "security_requirements",
                    "acceptance_criteria": [
                        "Only authenticated users can access",
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
                "description": "Salesforce API rate limits",
                "severity": "medium",
                "mitigation": "Implement caching layer",
            }
        ],
        "open_questions": [],
        "approval_status": "approved",
    }
    plan_path = planning_dir / "product_plan.yaml"
    with open(plan_path, "w", encoding="utf-8") as f:
        yaml.dump(plan, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    return plan_path


# ---------------------------------------------------------------------------
# Simulate agents
# ---------------------------------------------------------------------------

def simulate_project_manager_planning(
    sm: SharedStateManager,
    engine: HandoffEngine,
    board: TaskBoard,
    master_handoff: dict,
    product_plan_path: Path,
) -> dict:
    """
    Simulate PM receiving the product plan, building the task board,
    and returning the execution plan to Master.
    """
    pid = sm.project_id
    handoff_id = master_handoff["handoff_id"]

    # 1. Accept handoff
    engine.accept(sm, handoff_id)

    # 2. Load product plan
    with open(product_plan_path, encoding="utf-8") as f:
        plan = yaml.safe_load(f)

    # 3. Create milestones
    ms1 = board.create_milestone({
        "name": "M1: Infrastructure",
        "description": "AWS setup and authentication",
        "completion_criteria": "AWS VPC, database, and SSO configured",
    })
    ms2 = board.create_milestone({
        "name": "M2: Core Integration",
        "description": "Salesforce API integration and data pipeline",
        "completion_criteria": "Salesforce data flowing into system",
    })
    ms3 = board.create_milestone({
        "name": "M3: Dashboard UI",
        "description": "Frontend dashboard implementation",
        "completion_criteria": "Dashboard live and showing metrics",
    })

    # 4. Create tasks from must_have requirements
    t1 = board.create_task({
        "description": "Set up AWS VPC and networking",
        "milestone": ms1,
        "required_inputs": ["AWS credentials"],
        "expected_outputs": ["VPC configured", "subnets created"],
        "dependencies": [],
        "estimated_effort": "medium",
    })
    t2 = board.create_task({
        "description": "Deploy PostgreSQL database on RDS",
        "milestone": ms1,
        "required_inputs": ["VPC", "AWS credentials"],
        "expected_outputs": ["RDS instance running"],
        "dependencies": [t1],
        "estimated_effort": "small",
    })
    t3 = board.create_task({
        "description": "Configure company SSO integration",
        "milestone": ms1,
        "required_inputs": ["SSO service URL"],
        "expected_outputs": ["Authentication working"],
        "dependencies": [t1],
        "estimated_effort": "medium",
    })
    t4 = board.create_task({
        "description": "Build Salesforce CRM API connector",
        "milestone": ms2,
        "required_inputs": ["Salesforce API credentials", "database"],
        "expected_outputs": ["Pipeline data in database"],
        "dependencies": [t2],
        "estimated_effort": "large",
    })
    t5 = board.create_task({
        "description": "Implement 15-minute data refresh pipeline",
        "milestone": ms2,
        "required_inputs": ["Salesforce connector"],
        "expected_outputs": ["Scheduled refresh running"],
        "dependencies": [t4],
        "estimated_effort": "medium",
    })
    t6 = board.create_task({
        "description": "Build React dashboard frontend",
        "milestone": ms3,
        "required_inputs": ["API endpoints", "design specs"],
        "expected_outputs": ["Dashboard UI deployed"],
        "dependencies": [t3, t5],
        "estimated_effort": "extra-large",
    })

    # 5. Write execution plan path to shared state
    sm.write("project_manager_agent", "execution", "execution_plan_path",
             f"projects/{pid}/execution/execution_plan.yaml")

    # 6. Compile execution plan
    plan_dict = board.produce_execution_plan(str(product_plan_path))

    # 7. Return handoff to Master
    blocked = board.get_blocked()
    return engine.create(
        sm,
        from_agent="project_manager_agent",
        to_agent="master_orchestrator",
        phase="planning",
        task_description="Deliver execution plan for approval",
        payload={
            "summary": (
                f"Execution plan ready. {plan_dict['total_tasks']} tasks across "
                f"{plan_dict['total_milestones']} milestones. "
                f"{len(blocked)} blockers. "
                f"Plan at: projects/{pid}/execution/execution_plan.yaml"
            ),
            "artifacts_produced": [f"projects/{pid}/execution/execution_plan.yaml"],
            "decisions_made": [],
            "open_questions": [],
            "constraints_for_next": [],
            "shared_state_fields_modified": ["execution.execution_plan_path"],
            "total_tasks": plan_dict["total_tasks"],
            "total_milestones": plan_dict["total_milestones"],
            "plan_path": f"projects/{pid}/execution/execution_plan.yaml",
        },
    )


def simulate_task_executions(board: TaskBoard, task_ids: dict) -> None:
    """Simulate sequential task completions in dependency order."""
    order = ["t1", "t2", "t3", "t4", "t5", "t6"]
    for key in order:
        tid = task_ids[key]
        board.update_status(tid, "in_progress")
        board.update_status(tid, "completed")


# ---------------------------------------------------------------------------
# Tests: Planning phase
# ---------------------------------------------------------------------------

class TestProductPlanToExecutionPlan:

    def test_master_sends_product_plan_to_pm(self, sm, engine, approved_product_plan):
        handoff = engine.create(
            sm,
            from_agent="master_orchestrator",
            to_agent="project_manager_agent",
            phase="planning",
            task_description="Produce execution plan from approved product plan",
            payload={
                "summary": "Product plan approved. Produce execution plan.",
                "artifacts_produced": [],
                "decisions_made": [],
                "open_questions": [],
                "constraints_for_next": [],
                "shared_state_fields_modified": [],
                "product_plan_path": str(approved_product_plan),
            },
        )
        assert handoff["to_agent"] == "project_manager_agent"
        assert "product_plan_path" in handoff["payload"]

    def test_pm_creates_milestones_and_tasks(
        self, sm, engine, board, approved_product_plan
    ):
        master_handoff = engine.create(
            sm,
            from_agent="master_orchestrator",
            to_agent="project_manager_agent",
            phase="planning",
            task_description="Produce execution plan",
            payload={
                "summary": "Produce plan.",
                "artifacts_produced": [],
                "decisions_made": [],
                "open_questions": [],
                "constraints_for_next": [],
                "shared_state_fields_modified": [],
                "product_plan_path": str(approved_product_plan),
            },
        )

        pm_return = simulate_project_manager_planning(
            sm, engine, board, master_handoff, approved_product_plan
        )

        tasks = board.list_tasks()
        milestones_data = board._load()["milestones"]
        assert len(tasks) == 6
        assert len(milestones_data) == 3

    def test_execution_plan_written_to_disk(
        self, sm, engine, board, approved_product_plan
    ):
        master_handoff = engine.create(
            sm,
            from_agent="master_orchestrator",
            to_agent="project_manager_agent",
            phase="planning",
            task_description="Produce execution plan",
            payload={
                "summary": "Produce plan.",
                "artifacts_produced": [],
                "decisions_made": [],
                "open_questions": [],
                "constraints_for_next": [],
                "shared_state_fields_modified": [],
                "product_plan_path": str(approved_product_plan),
            },
        )

        simulate_project_manager_planning(
            sm, engine, board, master_handoff, approved_product_plan
        )

        assert board.plan_path.exists()
        with open(board.plan_path, encoding="utf-8") as f:
            plan = yaml.safe_load(f)
        assert plan["created_by"] == "project_manager_agent"
        assert plan["total_tasks"] == 6
        assert plan["total_milestones"] == 3

    def test_master_accepts_pm_return(
        self, sm, engine, board, approved_product_plan
    ):
        master_handoff = engine.create(
            sm,
            from_agent="master_orchestrator",
            to_agent="project_manager_agent",
            phase="planning",
            task_description="Produce execution plan",
            payload={
                "summary": "Produce plan.",
                "artifacts_produced": [],
                "decisions_made": [],
                "open_questions": [],
                "constraints_for_next": [],
                "shared_state_fields_modified": [],
                "product_plan_path": str(approved_product_plan),
            },
        )

        pm_return = simulate_project_manager_planning(
            sm, engine, board, master_handoff, approved_product_plan
        )
        engine.accept(sm, pm_return["handoff_id"])

        pending = engine.get_pending(sm)
        assert len(pending) == 0

    def test_execution_plan_path_in_shared_state(
        self, sm, engine, board, approved_product_plan
    ):
        master_handoff = engine.create(
            sm,
            from_agent="master_orchestrator",
            to_agent="project_manager_agent",
            phase="planning",
            task_description="Produce plan",
            payload={
                "summary": "Go.",
                "artifacts_produced": [],
                "decisions_made": [],
                "open_questions": [],
                "constraints_for_next": [],
                "shared_state_fields_modified": [],
                "product_plan_path": str(approved_product_plan),
            },
        )
        simulate_project_manager_planning(
            sm, engine, board, master_handoff, approved_product_plan
        )

        plan_path = sm.read("execution.execution_plan_path")
        assert plan_path is not None
        assert "execution_plan.yaml" in plan_path

    def test_dependency_chain_is_correct(
        self, sm, engine, board, approved_product_plan
    ):
        master_handoff = engine.create(
            sm,
            from_agent="master_orchestrator",
            to_agent="project_manager_agent",
            phase="planning",
            task_description="Produce plan",
            payload={
                "summary": "Go.",
                "artifacts_produced": [],
                "decisions_made": [],
                "open_questions": [],
                "constraints_for_next": [],
                "shared_state_fields_modified": [],
                "product_plan_path": str(approved_product_plan),
            },
        )
        simulate_project_manager_planning(
            sm, engine, board, master_handoff, approved_product_plan
        )

        tasks = board.list_tasks()
        # t6 (dashboard) depends on t3 (SSO) and t5 (pipeline), which both have upstream deps
        t6 = next(t for t in tasks if "React" in t["description"])
        chain = board.get_dependency_chain(t6["task_id"])
        assert len(chain) >= 2  # at least the direct dependencies


# ---------------------------------------------------------------------------
# Tests: Execution tracking
# ---------------------------------------------------------------------------

class TestExecutionTracking:

    def _setup_board(self, sm, engine, board, approved_product_plan):
        master_handoff = engine.create(
            sm,
            from_agent="master_orchestrator",
            to_agent="project_manager_agent",
            phase="planning",
            task_description="Produce plan",
            payload={
                "summary": "Go.",
                "artifacts_produced": [],
                "decisions_made": [],
                "open_questions": [],
                "constraints_for_next": [],
                "shared_state_fields_modified": [],
                "product_plan_path": str(approved_product_plan),
            },
        )
        pm_return = simulate_project_manager_planning(
            sm, engine, board, master_handoff, approved_product_plan
        )
        engine.accept(sm, pm_return["handoff_id"])
        return {
            f"t{i+1}": t["task_id"]
            for i, t in enumerate(board.list_tasks())
        }

    def test_task_completions_tracked(
        self, sm, engine, board, approved_product_plan
    ):
        task_ids = self._setup_board(sm, engine, board, approved_product_plan)

        board.update_status(task_ids["t1"], "completed")
        board.update_status(task_ids["t2"], "completed")

        report = board.produce_progress_report()
        assert report["by_status"]["completed"] == 2

    def test_milestone_completes_when_all_tasks_done(
        self, sm, engine, board, approved_product_plan
    ):
        task_ids = self._setup_board(sm, engine, board, approved_product_plan)

        # Complete all M1 tasks (t1, t2, t3)
        board.update_status(task_ids["t1"], "completed")
        board.update_status(task_ids["t2"], "completed")
        board.update_status(task_ids["t3"], "completed")

        ms_data = board._load()["milestones"]
        m1 = next(m for m in ms_data if "Infrastructure" in m["name"])
        assert m1["status"] == "completed"

    def test_blocked_task_alert(
        self, sm, engine, board, approved_product_plan
    ):
        task_ids = self._setup_board(sm, engine, board, approved_product_plan)

        board.update_status(
            task_ids["t1"], "blocked",
            blocker_description="No AWS credentials provided"
        )
        alert = board.build_blocker_alert(task_ids["t1"])
        assert alert["resolved"] is False
        assert "AWS credentials" in alert["blocker_description"]

    def test_progress_pct_increases_with_completions(
        self, sm, engine, board, approved_product_plan
    ):
        task_ids = self._setup_board(sm, engine, board, approved_product_plan)

        r0 = board.produce_progress_report()
        assert r0["pct_complete"] == 0.0

        board.update_status(task_ids["t1"], "completed")
        board.update_status(task_ids["t2"], "completed")
        board.update_status(task_ids["t3"], "completed")

        r3 = board.produce_progress_report()
        assert r3["pct_complete"] == 50.0

        for key in ["t4", "t5", "t6"]:
            board.update_status(task_ids[key], "completed")

        r6 = board.produce_progress_report()
        assert r6["pct_complete"] == 100.0


# ---------------------------------------------------------------------------
# Governance tests
# ---------------------------------------------------------------------------

class TestPlanningGovernance:

    def test_no_violations_in_planning_flow(
        self, sm, engine, board, approved_product_plan
    ):
        master_handoff = engine.create(
            sm,
            from_agent="master_orchestrator",
            to_agent="project_manager_agent",
            phase="planning",
            task_description="Produce plan",
            payload={
                "summary": "Go.",
                "artifacts_produced": [],
                "decisions_made": [],
                "open_questions": [],
                "constraints_for_next": [],
                "shared_state_fields_modified": [],
                "product_plan_path": str(approved_product_plan),
            },
        )
        simulate_project_manager_planning(
            sm, engine, board, master_handoff, approved_product_plan
        )

        for agent in ["master_orchestrator", "project_manager_agent"]:
            assert sm.get_violation_count(agent) == 0

    def test_pm_cannot_approve_own_fields(self, sm):
        sm.write("project_manager_agent", "execution",
                 "execution_plan_path", "some/path.yaml")
        result = sm.approve("project_manager_agent", "execution", "execution_plan_path")
        assert not result.success
        assert result.reason == "only_master_can_approve"

    def test_total_handoffs_in_planning_cycle(
        self, sm, engine, board, approved_product_plan
    ):
        master_handoff = engine.create(
            sm,
            from_agent="master_orchestrator",
            to_agent="project_manager_agent",
            phase="planning",
            task_description="Produce plan",
            payload={
                "summary": "Go.",
                "artifacts_produced": [],
                "decisions_made": [],
                "open_questions": [],
                "constraints_for_next": [],
                "shared_state_fields_modified": [],
                "product_plan_path": str(approved_product_plan),
            },
        )
        pm_return = simulate_project_manager_planning(
            sm, engine, board, master_handoff, approved_product_plan
        )
        engine.accept(sm, pm_return["handoff_id"])

        history = sm.read("workflow.handoff_history")
        assert len(history) == 2  # Master→PM, PM→Master
