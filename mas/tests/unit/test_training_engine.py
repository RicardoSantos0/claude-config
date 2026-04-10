"""
Unit Tests — Training Engine
Tests all proposal generation, prioritization, backlog, and approval logic.
No live LLM calls. Uses tmp_path to isolate backlog file.
"""
import pytest
import yaml
from pathlib import Path
from unittest.mock import patch

from core.training_engine import (
    TrainingEngine,
    TrainingProposal,
    PRIORITY_SCORES,
    LOW_THRESHOLD,
    SYSTEMIC_MIN_REPORTS,
    BACKLOG_FILE,
    _proposal_to_dict,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def engine():
    return TrainingEngine()


@pytest.fixture
def backlog_path(tmp_path, monkeypatch):
    """Redirect BACKLOG_FILE to tmp_path for test isolation."""
    fake_backlog = tmp_path / "roster" / "training_backlog.yaml"
    fake_backlog.parent.mkdir(parents=True)
    import core.training_engine as te
    monkeypatch.setattr(te, "BACKLOG_FILE", fake_backlog)
    return fake_backlog


@pytest.fixture
def minimal_report():
    """Evaluation report with no issues — all scores above threshold."""
    return {
        "report_id": "rep-001",
        "project_id": "proj-test-001",
        "project_metrics": [
            {"metric": "documentation_completeness", "score": 80.0, "evidence": "3 docs found"},
            {"metric": "scope_adherence", "score": 100.0, "evidence": "all tasks complete"},
            {"metric": "acceptance_criteria_pass_rate", "score": 100.0, "evidence": "3/3"},
            {"metric": "goal_achievement", "score": 85.0, "evidence": "criteria met"},
            {"metric": "phase_efficiency", "score": 90.0, "evidence": "2 handoffs/phase"},
            {"metric": "decision_quality", "score": 75.0, "evidence": "good rationale"},
        ],
        "agent_evaluations": [],
        "systemic_findings": [],
        "recommendations": {"improvement_areas": []},
    }


@pytest.fixture
def low_score_report():
    """Report with several metrics below threshold."""
    return {
        "report_id": "rep-002",
        "project_id": "proj-test-002",
        "project_metrics": [
            {"metric": "documentation_completeness", "score": 40.0, "evidence": "1/3 docs found"},
            {"metric": "scope_adherence", "score": 60.0, "evidence": "2 tasks blocked"},
            {"metric": "decision_quality", "score": 55.0, "evidence": "no rationale"},
            {"metric": "goal_achievement", "score": 80.0, "evidence": "good"},
            {"metric": "phase_efficiency", "score": 85.0, "evidence": "ok"},
            {"metric": "acceptance_criteria_pass_rate", "score": 90.0, "evidence": "good"},
        ],
        "agent_evaluations": [],
        "systemic_findings": [],
        "recommendations": {"improvement_areas": []},
    }


@pytest.fixture
def report_with_probation():
    """Report flagging an agent for probation."""
    return {
        "report_id": "rep-003",
        "project_id": "proj-test-003",
        "project_metrics": [],
        "agent_evaluations": [
            {
                "agent_id": "project_manager_agent",
                "overall_score": 45.0,
                "recommend_probation": True,
                "issues": ["missed 3 tasks", "no progress reports filed"],
                "strengths": [],
            }
        ],
        "systemic_findings": [],
        "recommendations": {"improvement_areas": []},
    }


@pytest.fixture
def report_with_systemic():
    """Report with explicit systemic findings."""
    return {
        "report_id": "rep-004",
        "project_id": "proj-test-004",
        "project_metrics": [],
        "agent_evaluations": [],
        "systemic_findings": [
            "Agents consistently exceed phase handoff budget",
            "Documentation missing in 3 consecutive projects",
        ],
        "recommendations": {"improvement_areas": ["documentation", "handoff_count"]},
    }


@pytest.fixture
def project_dir(tmp_path):
    d = tmp_path / "projects" / "proj-test-001"
    d.mkdir(parents=True)
    return d


# ---------------------------------------------------------------------------
# Tests: analyze_evaluation_report
# ---------------------------------------------------------------------------

class TestAnalyzeEvaluationReport:

    def test_no_proposals_for_clean_report(self, engine, minimal_report):
        proposals = engine.analyze_evaluation_report(minimal_report)
        # All metrics above threshold, no agent issues, no systemic findings
        assert len(proposals) == 0

    def test_low_metric_generates_proposal(self, engine, low_score_report):
        proposals = engine.analyze_evaluation_report(low_score_report)
        metrics_covered = {p.description for p in proposals}
        # documentation_completeness (40) and scope_adherence (60) and decision_quality (55) are all < 70
        assert len(proposals) >= 3

    def test_probation_agent_generates_boundary_violation(self, engine, report_with_probation):
        proposals = engine.analyze_evaluation_report(report_with_probation)
        boundary_props = [p for p in proposals if p.proposal_type == "boundary_violation"]
        assert len(boundary_props) == 1
        assert boundary_props[0].target_agent == "project_manager_agent"

    def test_systemic_findings_generate_proposals(self, engine, report_with_systemic):
        proposals = engine.analyze_evaluation_report(report_with_systemic)
        governance_props = [p for p in proposals if p.proposal_type == "governance_failure"]
        assert len(governance_props) == 2  # two systemic findings

    def test_improvement_areas_generate_proposals(self, engine, report_with_systemic):
        proposals = engine.analyze_evaluation_report(report_with_systemic)
        efficiency_props = [p for p in proposals if p.proposal_type == "efficiency_improvement"]
        assert len(efficiency_props) == 2  # "documentation" and "handoff_count"

    def test_proposal_has_required_fields(self, engine, low_score_report):
        proposals = engine.analyze_evaluation_report(low_score_report)
        assert len(proposals) > 0
        for p in proposals:
            assert p.proposal_id.startswith("prop-")
            assert p.proposal_type in PRIORITY_SCORES
            assert isinstance(p.priority, int)
            assert p.evidence  # non-empty
            assert p.status == "pending"

    def test_proposal_evidence_contains_report_id(self, engine, low_score_report):
        proposals = engine.analyze_evaluation_report(low_score_report)
        for p in proposals:
            assert "rep-002" in p.evidence

    def test_project_id_stored_in_proposal(self, engine, low_score_report):
        proposals = engine.analyze_evaluation_report(low_score_report, project_id="proj-abc")
        for p in proposals:
            assert "proj-abc" in p.project_ids

    def test_minimum_evidence_met_for_single_report(self, engine, low_score_report):
        proposals = engine.analyze_evaluation_report(low_score_report)
        for p in proposals:
            assert p.minimum_evidence_met is True

    def test_boundary_violation_highest_priority(self, engine, report_with_probation):
        proposals = engine.analyze_evaluation_report(report_with_probation)
        bv = [p for p in proposals if p.proposal_type == "boundary_violation"][0]
        assert bv.priority == 5


# ---------------------------------------------------------------------------
# Tests: analyze_multiple_reports — systemic detection
# ---------------------------------------------------------------------------

class TestAnalyzeMultipleReports:

    def _make_report(self, report_id, project_id, metric, score):
        all_metrics = {
            "documentation_completeness": 80.0,
            "scope_adherence": 100.0,
            "acceptance_criteria_pass_rate": 100.0,
            "goal_achievement": 85.0,
            "phase_efficiency": 90.0,
            "decision_quality": 75.0,
        }
        all_metrics[metric] = score
        return {
            "report_id": report_id,
            "project_id": project_id,
            "project_metrics": [
                {"metric": m, "score": s, "evidence": "test"} for m, s in all_metrics.items()
            ],
            "agent_evaluations": [],
            "systemic_findings": [],
            "recommendations": {"improvement_areas": []},
        }

    def test_same_metric_low_in_two_reports_is_systemic(self, engine):
        r1 = self._make_report("rep-1", "proj-1", "documentation_completeness", 40.0)
        r2 = self._make_report("rep-2", "proj-2", "documentation_completeness", 50.0)
        proposals = engine.analyze_multiple_reports([r1, r2])
        systemic = [p for p in proposals if p.systemic and "documentation_completeness" in p.description]
        assert len(systemic) >= 1

    def test_systemic_proposal_has_multiple_evidence_entries(self, engine):
        r1 = self._make_report("rep-1", "proj-1", "documentation_completeness", 40.0)
        r2 = self._make_report("rep-2", "proj-2", "documentation_completeness", 50.0)
        proposals = engine.analyze_multiple_reports([r1, r2])
        systemic = [p for p in proposals if p.systemic and "documentation_completeness" in p.description]
        assert len(systemic) > 0
        assert len(systemic[0].evidence) >= 2

    def test_metric_low_in_one_report_not_systemic(self, engine):
        r1 = self._make_report("rep-1", "proj-1", "documentation_completeness", 40.0)
        r2 = self._make_report("rep-2", "proj-2", "documentation_completeness", 85.0)  # high
        proposals = engine.analyze_multiple_reports([r1, r2])
        systemic = [p for p in proposals if p.systemic and "documentation_completeness" in p.description]
        # The systemic engine proposal requires 2+ low instances
        assert len(systemic) == 0

    def test_systemic_proposal_bumped_priority(self, engine):
        r1 = self._make_report("rep-1", "proj-1", "documentation_completeness", 40.0)
        r2 = self._make_report("rep-2", "proj-2", "documentation_completeness", 50.0)
        proposals = engine.analyze_multiple_reports([r1, r2])
        systemic = [p for p in proposals if p.systemic and "documentation_completeness" in p.description]
        if systemic:
            base_type = engine._metric_to_proposal_type("documentation_completeness", 45.0)
            base_priority = PRIORITY_SCORES[base_type]
            assert systemic[0].priority == base_priority + 1

    def test_multiple_systemic_patterns_detected(self, engine):
        r1 = self._make_report("rep-1", "proj-1", "scope_adherence", 50.0)
        r2 = self._make_report("rep-2", "proj-2", "scope_adherence", 55.0)
        r3 = self._make_report("rep-3", "proj-3", "documentation_completeness", 45.0)
        r4 = self._make_report("rep-4", "proj-4", "documentation_completeness", 40.0)
        proposals = engine.analyze_multiple_reports([r1, r2, r3, r4])
        systemic = [p for p in proposals if p.systemic and "SYSTEMIC" in p.description]
        assert len(systemic) >= 2


# ---------------------------------------------------------------------------
# Tests: prioritize
# ---------------------------------------------------------------------------

class TestPrioritize:

    def _make_proposal(self, ptype, systemic=False):
        return TrainingProposal(
            proposal_id=f"prop-{ptype[:4]}",
            proposal_type=ptype,
            priority=PRIORITY_SCORES[ptype],
            target_agent="system",
            target_artifact="policies/",
            description=f"Test {ptype}",
            recommended_change="Fix it",
            evidence=["rep-001"],
            tradeoffs="none",
            minimum_evidence_met=True,
            systemic=systemic,
        )

    def test_higher_priority_comes_first(self, engine):
        props = [
            self._make_proposal("prompt_refinement"),
            self._make_proposal("boundary_violation"),
            self._make_proposal("efficiency_improvement"),
        ]
        ordered = engine.prioritize(props)
        assert ordered[0].proposal_type == "boundary_violation"
        assert ordered[-1].proposal_type == "prompt_refinement"

    def test_systemic_before_non_systemic_same_priority(self, engine):
        p1 = self._make_proposal("efficiency_improvement", systemic=False)
        p2 = self._make_proposal("efficiency_improvement", systemic=True)
        ordered = engine.prioritize([p1, p2])
        assert ordered[0].systemic is True

    def test_empty_list_returns_empty(self, engine):
        assert engine.prioritize([]) == []


# ---------------------------------------------------------------------------
# Tests: produce_training_brief
# ---------------------------------------------------------------------------

class TestProduceTrainingBrief:

    def test_brief_file_created(self, engine, low_score_report, project_dir, backlog_path):
        proposals = engine.analyze_evaluation_report(low_score_report)
        path = engine.produce_training_brief("proj-test-001", proposals, project_dir)
        assert path.exists()

    def test_brief_contains_required_fields(self, engine, low_score_report, project_dir, backlog_path):
        proposals = engine.analyze_evaluation_report(low_score_report)
        path = engine.produce_training_brief("proj-test-001", proposals, project_dir)
        with open(path) as f:
            brief = yaml.safe_load(f)
        assert brief["project_id"] == "proj-test-001"
        assert brief["trainer"] == "trainer_agent"
        assert brief["authority_level"] == "L0_advisory"
        assert "proposals" in brief
        assert "proposal_summary" in brief

    def test_brief_proposals_are_prioritized(self, engine, low_score_report, project_dir, backlog_path):
        proposals = engine.analyze_evaluation_report(low_score_report)
        path = engine.produce_training_brief("proj-test-001", proposals, project_dir)
        with open(path) as f:
            brief = yaml.safe_load(f)
        priorities = [p["priority"] for p in brief["proposals"]]
        assert priorities == sorted(priorities, reverse=True)

    def test_brief_note_mentions_advisory(self, engine, project_dir, backlog_path):
        path = engine.produce_training_brief("proj-test-001", [], project_dir)
        with open(path) as f:
            brief = yaml.safe_load(f)
        assert "advisory" in brief["note"].lower()

    def test_empty_proposals_produces_valid_brief(self, engine, project_dir, backlog_path):
        path = engine.produce_training_brief("proj-test-001", [], project_dir)
        with open(path) as f:
            brief = yaml.safe_load(f)
        assert brief["total_proposals"] == 0
        assert brief["proposals"] == []


# ---------------------------------------------------------------------------
# Tests: backlog management
# ---------------------------------------------------------------------------

class TestBacklog:

    def test_load_backlog_missing_file_returns_empty(self, engine, backlog_path):
        backlog = engine.load_backlog()
        assert backlog == {"proposals": [], "last_updated": None}

    def test_update_backlog_adds_proposals(self, engine, low_score_report, backlog_path):
        proposals = engine.analyze_evaluation_report(low_score_report)
        engine.update_backlog(proposals)
        backlog = engine.load_backlog()
        assert len(backlog["proposals"]) == len(proposals)

    def test_update_backlog_deduplicates(self, engine, low_score_report, backlog_path):
        proposals = engine.analyze_evaluation_report(low_score_report)
        engine.update_backlog(proposals)
        engine.update_backlog(proposals)  # second call — same proposals
        backlog = engine.load_backlog()
        assert len(backlog["proposals"]) == len(proposals)

    def test_get_pending_returns_pending_only(self, engine, low_score_report, backlog_path):
        proposals = engine.analyze_evaluation_report(low_score_report)
        engine.update_backlog(proposals)
        pending = engine.get_pending()
        assert all(p["status"] == "pending" for p in pending)
        assert len(pending) == len(proposals)

    def test_approve_proposal_marks_approved(self, engine, low_score_report, backlog_path):
        proposals = engine.analyze_evaluation_report(low_score_report)
        engine.update_backlog(proposals)
        pid = proposals[0].proposal_id
        ok = engine.approve_proposal(pid, "master_orchestrator")
        assert ok
        approved = engine.get_by_status("approved")
        assert any(p["proposal_id"] == pid for p in approved)

    def test_approve_requires_master(self, engine, low_score_report, backlog_path):
        proposals = engine.analyze_evaluation_report(low_score_report)
        engine.update_backlog(proposals)
        pid = proposals[0].proposal_id
        ok = engine.approve_proposal(pid, "trainer_agent")  # wrong agent
        assert not ok

    def test_reject_proposal_marks_rejected(self, engine, low_score_report, backlog_path):
        proposals = engine.analyze_evaluation_report(low_score_report)
        engine.update_backlog(proposals)
        pid = proposals[0].proposal_id
        ok = engine.reject_proposal(pid, "Not enough evidence", "master_orchestrator")
        assert ok
        rejected = engine.get_by_status("rejected")
        assert any(p["proposal_id"] == pid and p["rejection_reason"] == "Not enough evidence"
                   for p in rejected)

    def test_reject_requires_master(self, engine, low_score_report, backlog_path):
        proposals = engine.analyze_evaluation_report(low_score_report)
        engine.update_backlog(proposals)
        pid = proposals[0].proposal_id
        ok = engine.reject_proposal(pid, "reason", "trainer_agent")
        assert not ok

    def test_approve_nonexistent_proposal_returns_false(self, engine, backlog_path):
        ok = engine.approve_proposal("prop-nonexistent", "master_orchestrator")
        assert not ok

    def test_reject_nonexistent_proposal_returns_false(self, engine, backlog_path):
        ok = engine.reject_proposal("prop-nonexistent", "reason", "master_orchestrator")
        assert not ok

    def test_mark_applied_transitions_from_approved(self, engine, low_score_report, backlog_path):
        proposals = engine.analyze_evaluation_report(low_score_report)
        engine.update_backlog(proposals)
        pid = proposals[0].proposal_id
        engine.approve_proposal(pid, "master_orchestrator")
        ok = engine.mark_applied(pid, "master_orchestrator")
        assert ok
        applied = engine.get_by_status("applied")
        assert any(p["proposal_id"] == pid for p in applied)

    def test_mark_applied_fails_if_not_approved(self, engine, low_score_report, backlog_path):
        proposals = engine.analyze_evaluation_report(low_score_report)
        engine.update_backlog(proposals)
        pid = proposals[0].proposal_id
        # Pending → applied should fail
        ok = engine.mark_applied(pid, "master_orchestrator")
        assert not ok

    def test_backlog_last_updated_set_after_update(self, engine, low_score_report, backlog_path):
        proposals = engine.analyze_evaluation_report(low_score_report)
        engine.update_backlog(proposals)
        backlog = engine.load_backlog()
        assert backlog["last_updated"] is not None


# ---------------------------------------------------------------------------
# Tests: proposal_to_dict completeness
# ---------------------------------------------------------------------------

class TestProposalToDict:

    def test_all_required_keys_present(self):
        p = TrainingProposal(
            proposal_id="prop-test",
            proposal_type="prompt_refinement",
            priority=1,
            target_agent="scribe_agent",
            target_artifact="agents/scribe_agent.md",
            description="test",
            recommended_change="change x",
            evidence=["rep-001"],
            tradeoffs="none",
            minimum_evidence_met=True,
            systemic=False,
        )
        d = _proposal_to_dict(p)
        required_keys = [
            "proposal_id", "proposal_type", "priority", "target_agent",
            "target_artifact", "description", "recommended_change", "evidence",
            "tradeoffs", "minimum_evidence_met", "systemic", "status",
            "rejection_reason", "original_proposal_id", "created_at", "project_ids",
        ]
        for k in required_keys:
            assert k in d, f"Missing key: {k}"


# ---------------------------------------------------------------------------
# Tests: priority scores
# ---------------------------------------------------------------------------

class TestPriorityScores:

    def test_boundary_violation_highest(self):
        assert PRIORITY_SCORES["boundary_violation"] == 5

    def test_prompt_refinement_lowest(self):
        assert PRIORITY_SCORES["prompt_refinement"] == 1

    def test_priority_order(self):
        assert (
            PRIORITY_SCORES["boundary_violation"]
            > PRIORITY_SCORES["governance_failure"]
            > PRIORITY_SCORES["repeated_quality_issue"]
            > PRIORITY_SCORES["efficiency_improvement"]
            > PRIORITY_SCORES["prompt_refinement"]
        )

    def test_low_threshold_is_70(self):
        assert LOW_THRESHOLD == 70.0

    def test_systemic_min_reports_is_two(self):
        assert SYSTEMIC_MIN_REPORTS == 2
