"""
Unit Tests — TaskBoard
Tests task/milestone CRUD, status transitions, dependency chain,
progress reports, execution plan serialization, and blocker alerts.
"""
import pytest
import yaml
from pathlib import Path
from core.task_board import (
    TaskBoard,
    VALID_TASK_STATUSES,
    VALID_EFFORT_TIERS,
    VALID_MILESTONE_STATUSES,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def board(tmp_path):
    return TaskBoard("proj-test-tb-001", projects_root=tmp_path / "projects")


@pytest.fixture
def ms_id(board):
    return board.create_milestone({
        "name": "M1: Foundation",
        "description": "Core infrastructure setup",
        "completion_criteria": "All infrastructure components deployed",
    })


@pytest.fixture
def ms2_id(board):
    return board.create_milestone({
        "name": "M2: Core Features",
        "description": "Main feature implementation",
        "completion_criteria": "All must-have requirements implemented",
    })


@pytest.fixture
def task_id(board, ms_id):
    return board.create_task({
        "description": "Set up VPC networking",
        "milestone": ms_id,
        "required_inputs": ["AWS account"],
        "expected_outputs": ["VPC configured"],
        "dependencies": [],
        "estimated_effort": "medium",
    })


@pytest.fixture
def populated_board(board, ms_id, ms2_id):
    """Board with 4 tasks across 2 milestones, with dependencies."""
    t1 = board.create_task({
        "description": "Set up VPC",
        "milestone": ms_id,
        "dependencies": [],
        "estimated_effort": "medium",
    })
    t2 = board.create_task({
        "description": "Deploy database",
        "milestone": ms_id,
        "dependencies": [t1],
        "estimated_effort": "medium",
    })
    t3 = board.create_task({
        "description": "Build dashboard UI",
        "milestone": ms2_id,
        "dependencies": [t2],
        "estimated_effort": "large",
    })
    t4 = board.create_task({
        "description": "Connect Salesforce API",
        "milestone": ms2_id,
        "dependencies": [t2],
        "estimated_effort": "large",
    })
    return board, {"t1": t1, "t2": t2, "t3": t3, "t4": t4}


# ---------------------------------------------------------------------------
# Milestone tests
# ---------------------------------------------------------------------------

class TestMilestones:
    def test_create_milestone_returns_id(self, board):
        ms_id = board.create_milestone({
            "name": "M1",
            "completion_criteria": "All done",
        })
        assert ms_id.startswith("ms-")

    def test_create_milestone_persists(self, board):
        ms_id = board.create_milestone({
            "name": "M1",
            "completion_criteria": "All done",
        })
        ms = board.get_milestone(ms_id)
        assert ms is not None
        assert ms["name"] == "M1"
        assert ms["status"] == "pending"

    def test_duplicate_milestone_raises(self, board, ms_id):
        with pytest.raises(ValueError, match="already exists"):
            board.create_milestone({
                "milestone_id": ms_id,
                "name": "Duplicate",
                "completion_criteria": "Test",
            })

    def test_missing_name_raises(self, board):
        with pytest.raises(ValueError):
            board.create_milestone({"completion_criteria": "Test"})

    def test_milestone_status_empty(self, board, ms_id):
        status = board.get_milestone_status(ms_id)
        assert status["total_tasks"] == 0
        assert status["pct_complete"] == 0.0
        assert status["all_complete"] is False

    def test_milestone_status_all_complete(self, board, ms_id):
        t1 = board.create_task({
            "description": "Task A",
            "milestone": ms_id,
            "dependencies": [],
            "estimated_effort": "small",
        })
        t2 = board.create_task({
            "description": "Task B",
            "milestone": ms_id,
            "dependencies": [],
            "estimated_effort": "small",
        })
        board.update_status(t1, "completed")
        board.update_status(t2, "completed")
        status = board.get_milestone_status(ms_id)
        assert status["pct_complete"] == 100.0
        assert status["all_complete"] is True
        assert status["status"] == "completed"

    def test_milestone_auto_advances_to_in_progress(self, board, ms_id):
        t1 = board.create_task({
            "description": "Task A",
            "milestone": ms_id,
            "dependencies": [],
            "estimated_effort": "small",
        })
        board.update_status(t1, "in_progress")
        ms = board.get_milestone(ms_id)
        assert ms["status"] == "in_progress"

    def test_milestone_not_found_raises(self, board):
        with pytest.raises(ValueError, match="not found"):
            board.get_milestone_status("ms-nonexistent")


# ---------------------------------------------------------------------------
# Task creation tests
# ---------------------------------------------------------------------------

class TestTaskCreation:
    def test_create_task_returns_id(self, board, ms_id):
        task_id = board.create_task({
            "description": "Build something",
            "milestone": ms_id,
            "estimated_effort": "small",
        })
        assert task_id.startswith("task-")

    def test_create_task_persists(self, board, ms_id):
        task_id = board.create_task({
            "description": "Build something",
            "milestone": ms_id,
            "estimated_effort": "small",
        })
        task = board.get_task(task_id)
        assert task is not None
        assert task["status"] == "planned"
        assert task["estimated_effort"] == "small"

    def test_task_registered_in_milestone(self, board, ms_id):
        task_id = board.create_task({
            "description": "Task in milestone",
            "milestone": ms_id,
            "estimated_effort": "small",
        })
        ms = board.get_milestone(ms_id)
        assert task_id in ms["task_ids"]

    def test_duplicate_task_raises(self, board, task_id):
        with pytest.raises(ValueError, match="already exists"):
            board.create_task({
                "task_id": task_id,
                "description": "Dup",
                "milestone": "ms-x",
                "estimated_effort": "small",
            })

    def test_missing_description_raises(self, board, ms_id):
        with pytest.raises(ValueError):
            board.create_task({"milestone": ms_id, "estimated_effort": "small"})

    def test_invalid_effort_raises(self, board, ms_id):
        with pytest.raises(ValueError, match="Invalid estimated_effort"):
            board.create_task({
                "description": "Bad effort",
                "milestone": ms_id,
                "estimated_effort": "ginormous",
            })

    def test_all_valid_effort_tiers_accepted(self, board, ms_id):
        for tier in VALID_EFFORT_TIERS:
            tid = board.create_task({
                "description": f"Task with {tier} effort",
                "milestone": ms_id,
                "estimated_effort": tier,
            })
            assert tid is not None


# ---------------------------------------------------------------------------
# Task status update tests
# ---------------------------------------------------------------------------

class TestTaskStatusUpdates:
    def test_update_status_planned_to_in_progress(self, board, task_id):
        result = board.update_status(task_id, "in_progress")
        assert result is True
        task = board.get_task(task_id)
        assert task["status"] == "in_progress"
        assert task["started_at"] is not None

    def test_update_status_to_completed(self, board, task_id):
        board.update_status(task_id, "in_progress")
        board.update_status(task_id, "completed")
        task = board.get_task(task_id)
        assert task["status"] == "completed"
        assert task["completed_at"] is not None

    def test_update_status_to_blocked_with_description(self, board, task_id):
        board.update_status(
            task_id, "blocked",
            blocker_description="Missing API credentials"
        )
        task = board.get_task(task_id)
        assert task["status"] == "blocked"
        assert task["blocker_description"] == "Missing API credentials"

    def test_complete_clears_blocker(self, board, task_id):
        board.update_status(task_id, "blocked",
                            blocker_description="Some blocker")
        board.update_status(task_id, "completed")
        task = board.get_task(task_id)
        assert task["blocker_description"] is None

    def test_invalid_status_raises(self, board, task_id):
        with pytest.raises(ValueError, match="Invalid status"):
            board.update_status(task_id, "flying")

    def test_nonexistent_task_returns_false(self, board):
        result = board.update_status("task-fake-000", "in_progress")
        assert result is False

    def test_notes_are_saved(self, board, task_id):
        board.update_status(task_id, "in_progress", notes="Started deployment")
        task = board.get_task(task_id)
        assert task["notes"] == "Started deployment"

    def test_actual_effort_saved(self, board, task_id):
        board.update_status(task_id, "completed", actual_effort="large")
        task = board.get_task(task_id)
        assert task["actual_effort"] == "large"

    def test_over_effort_flagged(self, board, ms_id):
        """Effort 2+ tiers above estimated → over_effort=True."""
        tid = board.create_task({
            "description": "Small task",
            "milestone": ms_id,
            "estimated_effort": "trivial",
        })
        # trivial=0, small=1, medium=2 → 2 tiers above → over_effort
        board.update_status(tid, "completed", actual_effort="medium")
        task = board.get_task(tid)
        assert task["over_effort"] is True

    def test_one_tier_above_not_over_effort(self, board, ms_id):
        """One tier above estimated → NOT over_effort."""
        tid = board.create_task({
            "description": "Small task",
            "milestone": ms_id,
            "estimated_effort": "small",
        })
        board.update_status(tid, "completed", actual_effort="medium")
        task = board.get_task(tid)
        assert task["over_effort"] is False


# ---------------------------------------------------------------------------
# List and filter tests
# ---------------------------------------------------------------------------

class TestListAndFilter:
    def test_list_all_tasks(self, populated_board):
        board, ids = populated_board
        tasks = board.list_tasks()
        assert len(tasks) == 4

    def test_list_by_status(self, populated_board):
        board, ids = populated_board
        board.update_status(ids["t1"], "in_progress")
        in_prog = board.list_tasks(status="in_progress")
        assert len(in_prog) == 1
        assert in_prog[0]["task_id"] == ids["t1"]

    def test_list_by_milestone(self, populated_board, ms_id, ms2_id):
        board, ids = populated_board
        ms1_tasks = board.list_tasks(milestone=ms_id)
        ms2_tasks = board.list_tasks(milestone=ms2_id)
        assert len(ms1_tasks) == 2
        assert len(ms2_tasks) == 2

    def test_get_blocked_returns_only_blocked(self, populated_board):
        board, ids = populated_board
        board.update_status(ids["t1"], "blocked",
                            blocker_description="Missing infra")
        blocked = board.get_blocked()
        assert len(blocked) == 1
        assert blocked[0]["task_id"] == ids["t1"]

    def test_get_ready_excludes_tasks_with_unmet_deps(self, populated_board):
        board, ids = populated_board
        # t2 depends on t1 (not complete) → not ready
        # t1 has no deps → ready
        ready = board.get_ready()
        ready_ids = {t["task_id"] for t in ready}
        assert ids["t1"] in ready_ids
        assert ids["t2"] not in ready_ids

    def test_get_ready_includes_after_dep_completed(self, populated_board):
        board, ids = populated_board
        board.update_status(ids["t1"], "completed")
        ready = board.get_ready()
        ready_ids = {t["task_id"] for t in ready}
        assert ids["t2"] in ready_ids


# ---------------------------------------------------------------------------
# Dependency chain tests
# ---------------------------------------------------------------------------

class TestDependencyChain:
    def test_no_deps_returns_empty(self, board, task_id):
        chain = board.get_dependency_chain(task_id)
        assert chain == []

    def test_direct_dep_returned(self, populated_board):
        board, ids = populated_board
        # t2 depends on t1
        chain = board.get_dependency_chain(ids["t2"])
        assert ids["t1"] in chain

    def test_transitive_deps_returned(self, populated_board):
        board, ids = populated_board
        # t3 depends on t2, t2 depends on t1 → chain includes both
        chain = board.get_dependency_chain(ids["t3"])
        assert ids["t2"] in chain
        assert ids["t1"] in chain

    def test_nonexistent_task_raises(self, board):
        with pytest.raises(ValueError, match="not found"):
            board.get_dependency_chain("task-fake-999")

    def test_circular_dep_raises(self, board, ms_id):
        t1 = board.create_task({
            "description": "T1",
            "milestone": ms_id,
            "estimated_effort": "small",
        })
        t2 = board.create_task({
            "description": "T2",
            "milestone": ms_id,
            "dependencies": [t1],
            "estimated_effort": "small",
        })
        # Manually inject circular dep
        data = board._load()
        for t in data["tasks"]:
            if t["task_id"] == t1:
                t["dependencies"] = [t2]
        board._save(data)

        with pytest.raises(ValueError, match="Circular"):
            board.get_dependency_chain(t1)


# ---------------------------------------------------------------------------
# Progress report tests
# ---------------------------------------------------------------------------

class TestProgressReport:
    def test_progress_report_full_project(self, populated_board):
        board, ids = populated_board
        report = board.produce_progress_report()
        assert report["project_id"] == board.project_id
        assert report["total_tasks"] == 4
        assert report["pct_complete"] == 0.0
        assert report["scope"] == "project"

    def test_progress_report_milestone_scoped(self, populated_board, ms_id):
        board, ids = populated_board
        report = board.produce_progress_report(milestone_id=ms_id)
        assert report["scope"] == f"milestone:{ms_id}"
        assert report["total_tasks"] == 2

    def test_progress_report_reflects_completions(self, populated_board):
        board, ids = populated_board
        board.update_status(ids["t1"], "completed")
        board.update_status(ids["t2"], "completed")
        report = board.produce_progress_report()
        assert report["by_status"]["completed"] == 2
        assert report["pct_complete"] == 50.0

    def test_blocked_tasks_in_report(self, populated_board):
        board, ids = populated_board
        board.update_status(ids["t1"], "blocked",
                            blocker_description="No access")
        report = board.produce_progress_report()
        assert len(report["blocked_tasks"]) == 1
        assert "risks" in report
        assert any("blocked" in r.lower() for r in report["risks"])

    def test_over_effort_in_report(self, populated_board):
        board, ids = populated_board
        board.update_status(ids["t1"], "completed", actual_effort="extra-large")
        report = board.produce_progress_report()
        assert len(report["over_effort_tasks"]) == 1


# ---------------------------------------------------------------------------
# Execution plan tests
# ---------------------------------------------------------------------------

class TestExecutionPlan:
    def test_plan_written_to_disk(self, populated_board):
        board, _ = populated_board
        plan = board.produce_execution_plan("projects/proj/planning/product_plan.yaml")
        assert board.plan_path.exists()

    def test_plan_is_valid_yaml(self, populated_board):
        board, _ = populated_board
        board.produce_execution_plan("projects/proj/planning/product_plan.yaml")
        with open(board.plan_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert data["project_id"] == board.project_id
        assert data["created_by"] == "project_manager_agent"
        assert data["approval_status"] == "pending_master_review"

    def test_plan_includes_all_tasks(self, populated_board):
        board, _ = populated_board
        plan = board.produce_execution_plan("projects/proj/planning/product_plan.yaml")
        assert plan["total_tasks"] == 4
        assert plan["total_milestones"] == 2

    def test_plan_includes_dependency_summary(self, populated_board):
        board, ids = populated_board
        plan = board.produce_execution_plan("projects/proj/planning/product_plan.yaml")
        dep_summary = plan["dependency_summary"]
        assert ids["t2"] in dep_summary  # t2 has deps
        assert ids["t1"] not in dep_summary  # t1 has none


# ---------------------------------------------------------------------------
# Blocker alert tests
# ---------------------------------------------------------------------------

class TestBlockerAlerts:
    def test_build_blocker_alert(self, board, task_id):
        board.update_status(task_id, "blocked",
                            blocker_description="API key missing")
        alert = board.build_blocker_alert(task_id)
        assert alert["task_id"] == task_id
        assert "API key missing" in alert["blocker_description"]
        assert alert["resolved"] is False
        assert alert["alert_id"].startswith("block-")

    def test_non_blocked_task_raises(self, board, task_id):
        with pytest.raises(ValueError, match="not blocked"):
            board.build_blocker_alert(task_id)

    def test_nonexistent_task_raises(self, board):
        with pytest.raises(ValueError, match="not found"):
            board.build_blocker_alert("task-fake-000")
