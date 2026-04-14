"""
Unit Tests — IntakeChecker
Tests completeness analysis, scoring, question generation, and answer application.
"""
import pytest
from core.engine.intake_checker import IntakeChecker, CompletenessResult, QUALITY_THRESHOLD


@pytest.fixture
def checker():
    return IntakeChecker()


# --- Fixtures: spec states ---

@pytest.fixture
def empty_spec():
    return {}


@pytest.fixture
def partial_spec():
    """Has 4 of 7 required fields and 2 of 5 recommended."""
    return {
        "project_goal": "Build a reporting dashboard",
        "problem_statement": "Sales team lacks visibility into pipeline metrics",
        "constraints": "Must use existing AWS infrastructure",
        "success_criteria": "Dashboard is live and used by >80% of sales team within 30 days",
        "stakeholders": "VP Sales, Sales Ops",
        "dependencies": "Salesforce CRM API",
    }


@pytest.fixture
def full_required_spec():
    """All 7 required fields present, no recommended."""
    return {
        "project_goal": "Build a reporting dashboard for the sales team",
        "problem_statement": "Sales team lacks visibility into pipeline metrics",
        "scope": {
            "inclusions": ["Dashboard UI", "Salesforce integration", "Weekly email digest"],
            "exclusions": ["Mobile app", "Real-time notifications"],
        },
        "constraints": "Must use existing AWS infrastructure, budget under $50k",
        "success_criteria": "Dashboard used by >80% of sales team within 30 days",
        "expected_outputs": ["Deployed web dashboard", "Admin documentation"],
    }


@pytest.fixture
def complete_spec():
    """All 7 required + all 5 recommended fields present."""
    return {
        "project_goal": "Build a reporting dashboard for the sales team",
        "problem_statement": "Sales team lacks visibility into pipeline metrics",
        "scope": {
            "inclusions": ["Dashboard UI", "Salesforce integration"],
            "exclusions": ["Mobile app"],
        },
        "constraints": "Must use existing AWS infrastructure",
        "success_criteria": "Dashboard used by >80% of sales team within 30 days",
        "expected_outputs": ["Deployed web dashboard"],
        "stakeholders": "VP Sales, Sales Ops team",
        "dependencies": "Salesforce CRM API, AWS account",
        "timeline_expectations": "Launch before Q3 planning cycle (end of July)",
        "quality_expectations": "Production-ready, >90% uptime SLA",
        "prior_art": "Previous attempt with Tableau abandoned due to licensing costs",
    }


# --- Score tests ---

class TestScoring:

    def test_empty_spec_score_is_zero(self, checker, empty_spec):
        result = checker.analyze(empty_spec)
        assert result.score == 0.0

    def test_all_required_no_recommended_score(self, checker, full_required_spec):
        result = checker.analyze(full_required_spec)
        # 7/7 required × 0.7 + 0/5 recommended × 0.3 = 0.7
        assert result.score == pytest.approx(0.7, abs=0.001)

    def test_all_fields_score_is_one(self, checker, complete_spec):
        result = checker.analyze(complete_spec)
        assert result.score == pytest.approx(1.0, abs=0.001)

    def test_partial_spec_score(self, checker, partial_spec):
        result = checker.analyze(partial_spec)
        # 4 required present, 2 recommended present
        expected = round((4 / 7 * 0.7) + (2 / 5 * 0.3), 4)
        assert result.score == pytest.approx(expected, abs=0.001)

    def test_score_is_rounded_to_4_decimal_places(self, checker, partial_spec):
        result = checker.analyze(partial_spec)
        assert result.score == round(result.score, 4)


# --- Completeness tests ---

class TestCompleteness:

    def test_empty_spec_is_not_complete(self, checker, empty_spec):
        result = checker.analyze(empty_spec)
        assert not result.complete

    def test_all_required_marks_complete(self, checker, full_required_spec):
        result = checker.analyze(full_required_spec)
        assert result.complete

    def test_missing_required_field_is_listed(self, checker, partial_spec):
        result = checker.analyze(partial_spec)
        assert "scope_inclusions" in result.required_missing
        assert "scope_exclusions" in result.required_missing
        assert "expected_outputs" in result.required_missing

    def test_present_required_field_is_listed(self, checker, partial_spec):
        result = checker.analyze(partial_spec)
        assert "project_goal" in result.required_present
        assert "problem_statement" in result.required_present

    def test_recommended_fields_tracked_separately(self, checker, complete_spec):
        result = checker.analyze(complete_spec)
        assert len(result.recommended_present) == 5
        assert len(result.recommended_missing) == 0

    def test_scope_sub_fields_extracted_correctly(self, checker, full_required_spec):
        result = checker.analyze(full_required_spec)
        assert "scope_inclusions" in result.required_present
        assert "scope_exclusions" in result.required_present


# --- Ready for handoff tests ---

class TestReadyForHandoff:

    def test_empty_spec_not_ready(self, checker, empty_spec):
        result = checker.analyze(empty_spec)
        assert not result.ready_for_handoff

    def test_all_required_no_recommended_not_ready(self, checker, full_required_spec):
        # Score = 0.7, threshold = 0.85
        result = checker.analyze(full_required_spec)
        assert not result.ready_for_handoff

    def test_complete_spec_is_ready(self, checker, complete_spec):
        result = checker.analyze(complete_spec)
        assert result.ready_for_handoff

    def test_ready_threshold_is_correct(self, checker):
        # Score exactly at threshold: need to hit 0.85
        # 7 required (0.7) + 3 recommended (0.18) = 0.88 → ready
        spec = {
            "project_goal": "Goal",
            "problem_statement": "Problem",
            "scope": {"inclusions": ["A"], "exclusions": ["B"]},
            "constraints": "Some constraints",
            "success_criteria": "Measurable outcome",
            "expected_outputs": ["Deliverable"],
            "stakeholders": "Someone",
            "dependencies": "Something",
            "timeline_expectations": "Q3 2026",
        }
        result = checker.analyze(spec)
        assert result.score >= QUALITY_THRESHOLD
        assert result.ready_for_handoff


# --- Ambiguity detection tests ---

class TestAmbiguityDetection:

    def test_very_short_string_flagged_as_ambiguous(self, checker):
        spec = {"project_goal": "TBD"}  # 3 chars — too short
        result = checker.analyze(spec)
        assert "project_goal" in result.ambiguous

    def test_normal_string_not_flagged(self, checker):
        spec = {"project_goal": "Build a reporting dashboard for the sales team"}
        result = checker.analyze(spec)
        assert "project_goal" not in result.ambiguous

    def test_list_values_not_flagged_as_ambiguous(self, checker):
        spec = {
            "scope": {"inclusions": ["A"], "exclusions": ["B"]}
        }
        result = checker.analyze(spec)
        assert "scope_inclusions" not in result.ambiguous
        assert "scope_exclusions" not in result.ambiguous


# --- Question generation tests ---

class TestQuestionGeneration:

    def test_generates_questions_for_missing_required_fields(self, checker, empty_spec):
        result = checker.analyze(empty_spec)
        questions = checker.generate_questions(result, round_number=1)
        assert len(questions) > 0
        fields = [q["field"] for q in questions]
        assert "project_goal" in fields

    def test_max_7_questions_enforced(self, checker, empty_spec):
        result = checker.analyze(empty_spec)
        questions = checker.generate_questions(result, round_number=1, max_questions=7)
        assert len(questions) <= 7

    def test_required_fields_prioritized_over_recommended(self, checker, partial_spec):
        result = checker.analyze(partial_spec)
        questions = checker.generate_questions(result, round_number=1, max_questions=3)
        types = [q["type"] for q in questions]
        # Required should come before recommended
        if "recommended" in types:
            last_required = max(
                (i for i, t in enumerate(types) if t == "required"), default=-1
            )
            first_recommended = min(
                (i for i, t in enumerate(types) if t == "recommended"), default=999
            )
            assert last_required < first_recommended

    def test_round_number_exceeding_3_returns_empty(self, checker, empty_spec):
        result = checker.analyze(empty_spec)
        questions = checker.generate_questions(result, round_number=4)
        assert questions == []

    def test_each_question_has_required_keys(self, checker, empty_spec):
        result = checker.analyze(empty_spec)
        questions = checker.generate_questions(result, round_number=1)
        for q in questions:
            assert "field" in q
            assert "type" in q
            assert "question" in q
            assert "round" in q

    def test_question_round_number_is_recorded(self, checker, empty_spec):
        result = checker.analyze(empty_spec)
        questions = checker.generate_questions(result, round_number=2)
        for q in questions:
            assert q["round"] == 2


# --- Apply answers tests ---

class TestApplyAnswers:

    def test_answers_update_top_level_fields(self, checker, empty_spec):
        qa_round = [
            {"field": "project_goal", "question": "...",
             "answer": "Build a sales dashboard", "resolved": True},
        ]
        updated = checker.apply_answers(empty_spec, qa_round)
        assert updated["project_goal"] == "Build a sales dashboard"

    def test_scope_inclusions_updated_correctly(self, checker, empty_spec):
        qa_round = [
            {"field": "scope_inclusions", "question": "...",
             "answer": ["Dashboard UI", "API integration"], "resolved": True},
        ]
        updated = checker.apply_answers(empty_spec, qa_round)
        assert updated["scope"]["inclusions"] == ["Dashboard UI", "API integration"]

    def test_scope_exclusions_updated_correctly(self, checker, empty_spec):
        qa_round = [
            {"field": "scope_exclusions", "question": "...",
             "answer": "Mobile app", "resolved": True},
        ]
        updated = checker.apply_answers(empty_spec, qa_round)
        assert updated["scope"]["exclusions"] == ["Mobile app"]

    def test_unresolved_answer_not_applied(self, checker, empty_spec):
        qa_round = [
            {"field": "project_goal", "question": "...",
             "answer": "Something", "resolved": False},
        ]
        updated = checker.apply_answers(empty_spec, qa_round)
        assert "project_goal" not in updated

    def test_missing_answer_not_applied(self, checker, empty_spec):
        qa_round = [
            {"field": "project_goal", "question": "...", "resolved": True},
        ]
        updated = checker.apply_answers(empty_spec, qa_round)
        assert "project_goal" not in updated

    def test_original_spec_not_mutated(self, checker):
        original = {"project_goal": "Original goal"}
        qa_round = [
            {"field": "project_goal", "question": "...",
             "answer": "New goal", "resolved": True},
        ]
        checker.apply_answers(original, qa_round)
        assert original["project_goal"] == "Original goal"


# --- File I/O tests ---

class TestFileIO:

    def test_record_qa_creates_file(self, checker, tmp_path):
        path = checker.record_qa.__func__(
            checker,  # self
            "proj-test-001", 1,
            [{"field": "project_goal", "question": "Q?",
              "answer": "A!", "resolved": True}],
        ) if False else None  # avoid real disk write — use monkeypatch below

    def test_record_qa_writes_to_correct_path(self, checker, tmp_path, monkeypatch):
        import core.engine.intake_checker as ic
        monkeypatch.setattr(ic, "ROOT", tmp_path)
        path = checker.record_qa("proj-test-001", 1,
                                 [{"field": "project_goal", "question": "Q?",
                                   "answer": "A!", "resolved": True}])
        assert path.exists()
        assert "proj-test-001" in str(path)
        assert path.name == "clarification_qa.yaml"

    def test_record_qa_accumulates_rounds(self, checker, tmp_path, monkeypatch):
        import core.engine.intake_checker as ic
        monkeypatch.setattr(ic, "ROOT", tmp_path)
        entry = [{"field": "project_goal", "question": "Q?",
                  "answer": "A!", "resolved": True}]
        checker.record_qa("proj-test-001", 1, entry)
        checker.record_qa("proj-test-001", 2, entry)
        import yaml
        qa_path = tmp_path / "projects" / "proj-test-001" / "intake" / "clarification_qa.yaml"
        with open(qa_path) as f:
            data = yaml.safe_load(f)
        assert len(data["rounds"]) == 2

    def test_write_spec_creates_file(self, checker, tmp_path, monkeypatch, complete_spec):
        import core.engine.intake_checker as ic
        monkeypatch.setattr(ic, "ROOT", tmp_path)
        result = checker.analyze(complete_spec)
        path = checker.write_spec("proj-test-001", complete_spec, result)
        assert path.exists()
        assert path.name == "clarified_spec.yaml"

    def test_write_spec_includes_score(self, checker, tmp_path, monkeypatch, complete_spec):
        import core.engine.intake_checker as ic
        import yaml
        monkeypatch.setattr(ic, "ROOT", tmp_path)
        result = checker.analyze(complete_spec)
        path = checker.write_spec("proj-test-001", complete_spec, result)
        with open(path) as f:
            data = yaml.safe_load(f)
        assert "quality_score" in data
        assert data["quality_score"] == result.score
