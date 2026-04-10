"""
Unit Tests — MetricsEngine
Tests all scoring functions: goal_achievement, acceptance_criteria_pass_rate,
scope_adherence, documentation_completeness, phase_efficiency, decision_quality,
task_completion_rate, handoff_quality, boundary_adherence, aggregation.
"""
import pytest
from pathlib import Path
from core.metrics_engine import (
    MetricsEngine,
    MetricResult,
    AgentEvaluation,
    EvaluationReport,
    EXEMPLARY_THRESHOLD,
    PROBATION_THRESHOLD,
)


@pytest.fixture
def engine():
    return MetricsEngine()


# ---------------------------------------------------------------------------
# goal_achievement
# ---------------------------------------------------------------------------

class TestGoalAchievement:
    def test_all_criteria_met_scores_100(self, engine):
        result = engine.score_goal_achievement(
            success_criteria=["Build a reporting dashboard", "Connect Salesforce API"],
            completed_task_descriptions=["Build reporting dashboard UI", "Connect Salesforce API integration"],
        )
        assert result.score == 100.0
        assert result.metric == "goal_achievement"

    def test_no_criteria_scores_50(self, engine):
        result = engine.score_goal_achievement([], [])
        assert result.score == 50.0

    def test_half_criteria_met_scores_50(self, engine):
        result = engine.score_goal_achievement(
            success_criteria=["Build reporting dashboard", "Connect machine learning pipeline"],
            completed_task_descriptions=["Build reporting dashboard"],
        )
        assert result.score == 50.0

    def test_no_completed_tasks_scores_0(self, engine):
        result = engine.score_goal_achievement(
            success_criteria=["Build dashboard", "Deploy service"],
            completed_task_descriptions=[],
        )
        assert result.score == 0.0

    def test_exemplary_flag_above_threshold(self, engine):
        result = engine.score_goal_achievement(
            success_criteria=["dashboard", "reporting", "salesforce"],
            completed_task_descriptions=["dashboard build", "reporting setup", "salesforce connect"],
        )
        assert result.exemplary is (result.score > EXEMPLARY_THRESHOLD)


# ---------------------------------------------------------------------------
# acceptance_criteria_pass_rate
# ---------------------------------------------------------------------------

class TestAcceptanceCriteriaPassRate:
    def test_all_passed(self, engine):
        result = engine.score_acceptance_criteria_pass_rate(5, 5)
        assert result.score == 100.0

    def test_none_passed(self, engine):
        result = engine.score_acceptance_criteria_pass_rate(5, 0)
        assert result.score == 0.0

    def test_partial_pass(self, engine):
        result = engine.score_acceptance_criteria_pass_rate(10, 7)
        assert result.score == pytest.approx(70.0)

    def test_no_criteria_returns_50(self, engine):
        result = engine.score_acceptance_criteria_pass_rate(0, 0)
        assert result.score == 50.0

    def test_metric_name_correct(self, engine):
        result = engine.score_acceptance_criteria_pass_rate(4, 4)
        assert result.metric == "acceptance_criteria_pass_rate"


# ---------------------------------------------------------------------------
# scope_adherence
# ---------------------------------------------------------------------------

class TestScopeAdherence:
    def test_all_complete_no_issues_scores_100(self, engine):
        result = engine.score_scope_adherence(5, 5, 0, 0, 0)
        assert result.score == 100.0

    def test_zero_tasks_returns_50(self, engine):
        result = engine.score_scope_adherence(0, 0, 0, 0, 0)
        assert result.score == 50.0

    def test_blocked_task_deducts_10(self, engine):
        result = engine.score_scope_adherence(5, 5, 1, 0, 0)
        assert result.score == pytest.approx(90.0)

    def test_failed_task_deducts_10(self, engine):
        result = engine.score_scope_adherence(5, 5, 0, 1, 0)
        assert result.score == pytest.approx(90.0)

    def test_over_effort_task_deducts_5(self, engine):
        result = engine.score_scope_adherence(5, 5, 0, 0, 1)
        assert result.score == pytest.approx(95.0)

    def test_incomplete_tasks_lower_base(self, engine):
        # 3/5 complete = 60% base, no other deductions
        result = engine.score_scope_adherence(5, 3, 0, 0, 0)
        assert result.score == pytest.approx(60.0)

    def test_minimum_is_zero(self, engine):
        # 0% completion + many blocked → can't go below 0
        result = engine.score_scope_adherence(5, 0, 10, 10, 10)
        assert result.score == 0.0

    def test_metric_name_correct(self, engine):
        result = engine.score_scope_adherence(4, 4, 0, 0, 0)
        assert result.metric == "scope_adherence"


# ---------------------------------------------------------------------------
# documentation_completeness
# ---------------------------------------------------------------------------

class TestDocumentationCompleteness:
    def test_all_required_present(self, tmp_path):
        engine = MetricsEngine()
        # Create all required docs
        (tmp_path / "intake").mkdir()
        (tmp_path / "intake" / "clarified_spec.yaml").write_text("x")
        (tmp_path / "planning").mkdir()
        (tmp_path / "planning" / "product_plan.yaml").write_text("x")
        (tmp_path / "execution").mkdir()
        (tmp_path / "execution" / "execution_plan.yaml").write_text("x")

        result = engine.score_documentation_completeness(tmp_path)
        assert result.score == pytest.approx(80.0)

    def test_all_docs_including_recommended(self, tmp_path):
        engine = MetricsEngine()
        for d, f in [
            ("intake", "clarified_spec.yaml"),
            ("planning", "product_plan.yaml"),
            ("execution", "execution_plan.yaml"),
            ("evaluation", "evaluation_report.yaml"),
        ]:
            (tmp_path / d).mkdir(exist_ok=True)
            (tmp_path / d / f).write_text("x")

        result = engine.score_documentation_completeness(tmp_path)
        assert result.score == pytest.approx(100.0)

    def test_no_docs_scores_zero(self, tmp_path):
        engine = MetricsEngine()
        result = engine.score_documentation_completeness(tmp_path)
        assert result.score == 0.0

    def test_partial_docs(self, tmp_path):
        engine = MetricsEngine()
        (tmp_path / "intake").mkdir()
        (tmp_path / "intake" / "clarified_spec.yaml").write_text("x")

        result = engine.score_documentation_completeness(tmp_path)
        # 1/3 required = 33.3% of 80 pts = ~26.7
        assert result.score == pytest.approx(80.0 / 3, abs=0.1)

    def test_metric_name_correct(self, tmp_path):
        engine = MetricsEngine()
        result = engine.score_documentation_completeness(tmp_path)
        assert result.metric == "documentation_completeness"


# ---------------------------------------------------------------------------
# phase_efficiency
# ---------------------------------------------------------------------------

class TestPhaseEfficiency:
    def test_no_handoffs_scores_100(self, engine):
        result = engine.score_phase_efficiency([])
        assert result.score == 100.0

    def test_ideal_two_per_phase(self, engine):
        history = [
            {"phase": "intake", "from_agent": "master_orchestrator", "to_agent": "inquirer_agent"},
            {"phase": "intake", "from_agent": "inquirer_agent", "to_agent": "master_orchestrator"},
            {"phase": "planning", "from_agent": "master_orchestrator", "to_agent": "product_manager_agent"},
            {"phase": "planning", "from_agent": "product_manager_agent", "to_agent": "master_orchestrator"},
        ]
        result = engine.score_phase_efficiency(history)
        assert result.score == 100.0

    def test_extra_handoff_in_phase_deducts(self, engine):
        history = [
            {"phase": "intake", "from_agent": "master_orchestrator", "to_agent": "inquirer_agent"},
            {"phase": "intake", "from_agent": "inquirer_agent", "to_agent": "master_orchestrator"},
            {"phase": "intake", "from_agent": "master_orchestrator", "to_agent": "inquirer_agent"},  # extra
        ]
        result = engine.score_phase_efficiency(history)
        assert result.score == pytest.approx(95.0)  # 1 extra → -5

    def test_minimum_zero(self, engine):
        # 20+ extra handoffs in one phase
        history = [{"phase": "intake", "from_agent": "a", "to_agent": "b"}] * 25
        result = engine.score_phase_efficiency(history)
        assert result.score == 0.0

    def test_metric_name(self, engine):
        result = engine.score_phase_efficiency([])
        assert result.metric == "phase_efficiency"


# ---------------------------------------------------------------------------
# decision_quality
# ---------------------------------------------------------------------------

class TestDecisionQuality:
    def test_no_decisions_returns_50(self, engine):
        result = engine.score_decision_quality([])
        assert result.score == 50.0

    def test_documented_only_gives_base(self, engine):
        decisions = [
            {"decision_id": "d1", "description": "Choose AWS"},
            {"decision_id": "d2", "description": "Use React"},
        ]
        result = engine.score_decision_quality(decisions)
        assert result.score == pytest.approx(51.0)

    def test_with_rationale_bonus(self, engine):
        decisions = [
            {"decision_id": "d1", "rationale": "AWS is already provisioned"},
        ]
        result = engine.score_decision_quality(decisions)
        assert result.score > 51.0

    def test_full_quality_approaches_100(self, engine):
        decisions = [
            {
                "decision_id": "d1",
                "rationale": "AWS is already provisioned",
                "alternatives_considered": ["GCP", "Azure"],
                "related_to": "infrastructure_setup",
            },
        ]
        result = engine.score_decision_quality(decisions)
        assert result.score > 80.0

    def test_metric_name(self, engine):
        result = engine.score_decision_quality([])
        assert result.metric == "decision_quality"


# ---------------------------------------------------------------------------
# task_completion_rate
# ---------------------------------------------------------------------------

class TestTaskCompletionRate:
    def test_all_completed(self, engine):
        tasks = [
            {"task_id": "t1", "assigned_to": "agent_a", "status": "completed"},
            {"task_id": "t2", "assigned_to": "agent_a", "status": "completed"},
        ]
        result = engine.score_task_completion_rate("agent_a", tasks)
        assert result.score == 100.0

    def test_none_completed(self, engine):
        tasks = [
            {"task_id": "t1", "assigned_to": "agent_a", "status": "blocked"},
        ]
        result = engine.score_task_completion_rate("agent_a", tasks)
        assert result.score == 0.0

    def test_unassigned_agent_scores_100(self, engine):
        tasks = [
            {"task_id": "t1", "assigned_to": "agent_b", "status": "completed"},
        ]
        result = engine.score_task_completion_rate("agent_a", tasks)
        assert result.score == 100.0

    def test_partial_completion(self, engine):
        tasks = [
            {"task_id": "t1", "assigned_to": "agent_a", "status": "completed"},
            {"task_id": "t2", "assigned_to": "agent_a", "status": "blocked"},
            {"task_id": "t3", "assigned_to": "agent_a", "status": "completed"},
            {"task_id": "t4", "assigned_to": "agent_a", "status": "planned"},
        ]
        result = engine.score_task_completion_rate("agent_a", tasks)
        assert result.score == pytest.approx(50.0)

    def test_metric_name(self, engine):
        result = engine.score_task_completion_rate("agent_a", [])
        assert result.metric == "task_completion_rate"


# ---------------------------------------------------------------------------
# handoff_quality
# ---------------------------------------------------------------------------

class TestHandoffQuality:
    def test_no_outgoing_scores_100(self, engine):
        result = engine.score_handoff_quality("agent_a", [])
        assert result.score == 100.0

    def test_all_accepted_scores_100(self, engine):
        history = [
            {"from_agent": "agent_a", "to_agent": "master", "status": "accepted"},
            {"from_agent": "agent_a", "to_agent": "master", "status": "accepted"},
        ]
        result = engine.score_handoff_quality("agent_a", history)
        assert result.score == 100.0

    def test_pending_handoffs_lower_score(self, engine):
        history = [
            {"from_agent": "agent_a", "to_agent": "master", "status": "accepted"},
            {"from_agent": "agent_a", "to_agent": "master", "status": "pending"},
        ]
        result = engine.score_handoff_quality("agent_a", history)
        assert result.score == pytest.approx(50.0)

    def test_only_counts_outgoing_from_agent(self, engine):
        history = [
            {"from_agent": "agent_b", "to_agent": "agent_a", "status": "pending"},
            {"from_agent": "agent_a", "to_agent": "master", "status": "accepted"},
        ]
        result = engine.score_handoff_quality("agent_a", history)
        assert result.score == 100.0

    def test_metric_name(self, engine):
        result = engine.score_handoff_quality("agent_a", [])
        assert result.metric == "handoff_quality"


# ---------------------------------------------------------------------------
# boundary_adherence
# ---------------------------------------------------------------------------

class TestBoundaryAdherence:
    def test_no_violations_scores_100(self, engine):
        result = engine.score_boundary_adherence("agent_a", [])
        assert result.score == 100.0

    def test_one_violation_deducts_20(self, engine):
        violations = [{"agent_id": "agent_a", "description": "wrote to master-only field"}]
        result = engine.score_boundary_adherence("agent_a", violations)
        assert result.score == pytest.approx(80.0)

    def test_five_violations_scores_zero(self, engine):
        violations = [{"agent_id": "agent_a"}] * 5
        result = engine.score_boundary_adherence("agent_a", violations)
        assert result.score == 0.0

    def test_other_agent_violations_ignored(self, engine):
        violations = [{"agent_id": "agent_b", "description": "violation"}]
        result = engine.score_boundary_adherence("agent_a", violations)
        assert result.score == 100.0

    def test_metric_name(self, engine):
        result = engine.score_boundary_adherence("agent_a", [])
        assert result.metric == "boundary_adherence"

    def test_exemplary_when_no_violations(self, engine):
        result = engine.score_boundary_adherence("agent_a", [])
        assert result.exemplary is True


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

class TestAggregation:
    def test_equal_weight_average(self, engine):
        results = [
            MetricResult("m1", 80.0, "", ""),
            MetricResult("m2", 60.0, "", ""),
            MetricResult("m3", 100.0, "", ""),
        ]
        avg = engine.aggregate_project_score(results)
        assert avg == pytest.approx(80.0)

    def test_empty_list_returns_zero(self, engine):
        assert engine.aggregate_project_score([]) == 0.0
        assert engine.aggregate_agent_score([]) == 0.0


# ---------------------------------------------------------------------------
# Full agent evaluation
# ---------------------------------------------------------------------------

class TestAgentEvaluation:
    def _make_state(self, violations=None):
        return {
            "workflow": {
                "handoff_history": [
                    {"from_agent": "hr_agent", "to_agent": "master_orchestrator",
                     "status": "accepted", "phase": "capability_discovery"},
                ],
            },
            "_meta": {
                "governance_violations": violations or [],
            },
        }

    def test_agent_eval_produces_three_metrics(self, engine):
        state = self._make_state()
        board = {"tasks": [], "milestones": []}
        result = engine.evaluate_agent("hr_agent", state, board)
        assert len(result.metrics) == 3

    def test_clean_agent_scores_high(self, engine):
        state = self._make_state()
        board = {"tasks": [], "milestones": []}
        result = engine.evaluate_agent("hr_agent", state, board)
        assert result.overall_score >= 80.0

    def test_probation_flag_when_score_below_threshold(self, engine):
        violations = [{"agent_id": "bad_agent"}] * 5  # −100 pts on boundary
        state = self._make_state(violations=violations)
        board = {
            "tasks": [
                {"task_id": "t1", "assigned_to": "bad_agent", "status": "blocked"},
                {"task_id": "t2", "assigned_to": "bad_agent", "status": "failed"},
            ],
            "milestones": [],
        }
        result = engine.evaluate_agent("bad_agent", state, board)
        assert result.recommend_probation is True

    def test_exemplary_flag_when_score_above_threshold(self, engine):
        state = self._make_state()
        board = {
            "tasks": [
                {"task_id": "t1", "assigned_to": "great_agent", "status": "completed"},
                {"task_id": "t2", "assigned_to": "great_agent", "status": "completed"},
            ],
            "milestones": [],
        }
        state["workflow"]["handoff_history"] = [
            {"from_agent": "great_agent", "to_agent": "master",
             "status": "accepted", "phase": "planning"},
            {"from_agent": "great_agent", "to_agent": "master",
             "status": "accepted", "phase": "planning"},
        ]
        result = engine.evaluate_agent("great_agent", state, board)
        assert result.exemplary is (result.overall_score > EXEMPLARY_THRESHOLD)


# ---------------------------------------------------------------------------
# Full report
# ---------------------------------------------------------------------------

class TestFullReport:
    def _setup_docs(self, project_dir):
        for d, f in [
            ("intake", "clarified_spec.yaml"),
            ("planning", "product_plan.yaml"),
            ("execution", "execution_plan.yaml"),
        ]:
            (project_dir / d).mkdir(exist_ok=True)
            (project_dir / d / f).write_text(
                "project_id: test\n"
                "requirements:\n"
                "  must_have: []\n"
            )

    def test_report_has_all_sections(self, engine, tmp_path):
        project_dir = tmp_path / "proj-001"
        project_dir.mkdir()
        self._setup_docs(project_dir)

        state = {
            "project_definition": {
                "success_criteria": ["Build dashboard"],
            },
            "workflow": {"handoff_history": []},
            "decisions": {"decision_log": []},
            "_meta": {"governance_violations": []},
        }
        board = {"tasks": [], "milestones": []}

        report = engine.produce_report(
            "proj-001", state, project_dir, board,
            agents_to_evaluate=["master_orchestrator"]
        )
        assert report.project_id == "proj-001"
        assert len(report.project_metrics) == 6
        assert len(report.agent_evaluations) == 1
        assert "bottlenecks" in report.systemic_findings
        assert "improvement_areas" in report.recommendations

    def test_report_saved_to_disk(self, engine, tmp_path):
        project_dir = tmp_path / "proj-002"
        project_dir.mkdir()
        self._setup_docs(project_dir)

        state = {
            "project_definition": {"success_criteria": []},
            "workflow": {"handoff_history": []},
            "decisions": {"decision_log": []},
            "_meta": {"governance_violations": []},
        }
        board = {"tasks": [], "milestones": []}

        report = engine.produce_report(
            "proj-002", state, project_dir, board, agents_to_evaluate=[]
        )
        path = engine.save_report(report, project_dir)
        assert path.exists()

        import yaml
        with open(path) as f:
            data = yaml.safe_load(f)
        assert "report_id" in data
        assert "project_metrics" in data
        assert "agent_evaluations" in data

    def test_report_id_format(self, engine, tmp_path):
        project_dir = tmp_path / "proj-003"
        project_dir.mkdir()
        state = {
            "project_definition": {"success_criteria": []},
            "workflow": {"handoff_history": []},
            "decisions": {"decision_log": []},
            "_meta": {"governance_violations": []},
        }
        board = {"tasks": [], "milestones": []}
        report = engine.produce_report(
            "proj-003", state, project_dir, board, agents_to_evaluate=[]
        )
        assert report.report_id.startswith("eval-proj-003-")

    def test_blocked_tasks_appear_in_systemic_findings(self, engine, tmp_path):
        project_dir = tmp_path / "proj-004"
        project_dir.mkdir()
        state = {
            "project_definition": {"success_criteria": []},
            "workflow": {"handoff_history": []},
            "decisions": {"decision_log": []},
            "_meta": {"governance_violations": []},
        }
        board = {
            "tasks": [
                {"task_id": "t1", "description": "Deploy infra",
                 "status": "blocked", "over_effort": False,
                 "assigned_to": None},
            ],
            "milestones": [],
        }
        report = engine.produce_report(
            "proj-004", state, project_dir, board, agents_to_evaluate=[]
        )
        assert len(report.systemic_findings["bottlenecks"]) >= 1
