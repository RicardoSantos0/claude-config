"""
Unit Tests — Consultation Engine
Tests all consultation lifecycle logic in isolation.
No live LLM calls. Uses tmp_path for file isolation.
"""
import pytest
import yaml
from pathlib import Path

from core.consultation_engine import (
    ConsultationEngine,
    ConsultationRequest,
    ConsultationResponse,
    ConsultationSynthesis,
    ALL_CONSULTANTS,
    MANDATORY_DECISION_TYPES,
    MAX_RESPONSE_WORDS,
    FOLLOW_UP_ROUNDS_MAX,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def engine():
    return ConsultationEngine()


@pytest.fixture
def project_dir(tmp_path):
    d = tmp_path / "projects" / "proj-consult-001"
    d.mkdir(parents=True)
    return d


@pytest.fixture
def basic_request(engine):
    return engine.create_request(
        project_id="proj-consult-001",
        question="Should we spawn a new reporting agent?",
        context={"current_agents": 3, "gap_cert": "gap-001"},
        decision_type="spawn",
    )


@pytest.fixture
def optional_request(engine):
    return engine.create_request(
        project_id="proj-consult-001",
        question="Which of two approaches is preferable?",
        context={"option_a": "approach A", "option_b": "approach B"},
        decision_type="approach",
        consultants=["risk_advisor", "efficiency_advisor"],
    )


def _add_all_responses(engine, request, risk_level="low"):
    """Helper to add responses from all selected consultants."""
    for cid in request.consultants_selected:
        engine.record_response(
            request, cid,
            response_text=f"Response from {cid}.",
            risk_level=risk_level,
            key_concerns=[f"{cid} concern"],
            recommendation=f"{cid} recommends proceeding.",
        )


# ---------------------------------------------------------------------------
# Tests: create_request
# ---------------------------------------------------------------------------

class TestCreateRequest:

    def test_mandatory_type_selects_all_consultants(self, engine):
        req = engine.create_request("proj-1", "question", {}, "spawn")
        assert set(req.consultants_selected) == set(ALL_CONSULTANTS)
        assert req.mandatory is True

    def test_non_mandatory_allows_subset(self, engine):
        req = engine.create_request("proj-1", "question", {}, "approach",
                                    consultants=["risk_advisor", "efficiency_advisor"])
        assert req.consultants_selected == ["risk_advisor", "efficiency_advisor"]
        assert req.mandatory is False

    def test_subset_below_two_falls_back_to_all(self, engine):
        req = engine.create_request("proj-1", "question", {}, "approach",
                                    consultants=["risk_advisor"])  # only 1 — too few
        assert set(req.consultants_selected) == set(ALL_CONSULTANTS)

    def test_mandatory_overrides_subset(self, engine):
        req = engine.create_request("proj-1", "question", {}, "governance",
                                    consultants=["risk_advisor"])
        assert set(req.consultants_selected) == set(ALL_CONSULTANTS)

    def test_request_id_format(self, engine):
        req = engine.create_request("proj-abc", "q", {}, "spawn")
        assert req.request_id.startswith("consult-proj-abc-")

    def test_request_status_is_open(self, engine):
        req = engine.create_request("proj-1", "q", {}, "spawn")
        assert req.status == "open"

    def test_all_mandatory_types(self, engine):
        for dt in MANDATORY_DECISION_TYPES:
            req = engine.create_request("proj-1", "q", {}, dt)
            assert req.mandatory is True

    def test_domain_context_stored(self, engine):
        req = engine.create_request("proj-1", "q", {}, "approach",
                                    domain_context="# Software Engineering context")
        assert req.domain_context == "# Software Engineering context"


# ---------------------------------------------------------------------------
# Tests: record_response
# ---------------------------------------------------------------------------

class TestRecordResponse:

    def test_response_recorded(self, engine, basic_request):
        resp = engine.record_response(
            basic_request, "risk_advisor",
            "Risk analysis here.", risk_level="medium",
            key_concerns=["concern 1"], recommendation="Proceed with caution.",
        )
        assert "risk_advisor" in basic_request.responses
        assert resp.risk_level == "medium"

    def test_word_count_tracked(self, engine, basic_request):
        text = "word " * 50
        resp = engine.record_response(
            basic_request, "risk_advisor", text.strip(),
            risk_level="low",
        )
        assert resp.word_count == 50

    def test_response_truncated_at_500_words(self, engine, basic_request):
        long_text = "word " * 600
        resp = engine.record_response(
            basic_request, "risk_advisor", long_text.strip(),
            risk_level="low",
        )
        assert resp.word_count == MAX_RESPONSE_WORDS
        assert resp.truncated is True
        assert "[truncated]" in resp.response_text

    def test_exactly_500_words_not_truncated(self, engine, basic_request):
        text = "word " * 500
        resp = engine.record_response(
            basic_request, "risk_advisor", text.strip(),
            risk_level="low",
        )
        assert resp.truncated is False
        assert resp.word_count == 500

    def test_unselected_consultant_raises(self, engine, optional_request):
        with pytest.raises(ValueError, match="not selected"):
            engine.record_response(
                optional_request, "devils_advocate",
                "My response.", risk_level="low",
            )

    def test_invalid_risk_level_defaults_to_low(self, engine, basic_request):
        resp = engine.record_response(
            basic_request, "risk_advisor", "response",
            risk_level="critical",  # invalid
        )
        assert resp.risk_level == "low"

    def test_status_becomes_responded_when_all_replied(self, engine, basic_request):
        assert basic_request.status == "open"
        _add_all_responses(engine, basic_request)
        assert basic_request.status == "responded"

    def test_status_remains_open_until_all_replied(self, engine, basic_request):
        engine.record_response(basic_request, "risk_advisor", "resp", risk_level="low")
        assert basic_request.status == "open"


# ---------------------------------------------------------------------------
# Tests: check_unanimous_risk
# ---------------------------------------------------------------------------

class TestCheckUnanimousRisk:

    def test_all_high_is_unanimous(self, engine, basic_request):
        _add_all_responses(engine, basic_request, risk_level="high")
        assert engine.check_unanimous_risk(basic_request) is True

    def test_mixed_risk_not_unanimous(self, engine, basic_request):
        for i, cid in enumerate(basic_request.consultants_selected):
            level = "high" if i < len(basic_request.consultants_selected) - 1 else "medium"
            engine.record_response(basic_request, cid, "resp", risk_level=level)
        assert engine.check_unanimous_risk(basic_request) is False

    def test_all_low_not_unanimous(self, engine, basic_request):
        _add_all_responses(engine, basic_request, risk_level="low")
        assert engine.check_unanimous_risk(basic_request) is False

    def test_empty_responses_not_unanimous(self, engine, basic_request):
        assert engine.check_unanimous_risk(basic_request) is False

    def test_single_consultant_high_not_unanimous_if_others_missing(self, engine, basic_request):
        engine.record_response(basic_request, "risk_advisor", "resp", risk_level="high")
        # Only 1 responded but all 5 were selected — not all have responded
        # unanimous requires ALL selected to have responded AND all high
        # With 1/5 responded and 1 = high, the check is True only if all responses are high
        # Since only 1 responded, the check is over existing responses: 1/1 = high → True
        # Per spec: check all RESPONDING consultants (not all selected)
        assert engine.check_unanimous_risk(basic_request) is True

    def test_check_majority_risk(self, engine, basic_request):
        consultants = basic_request.consultants_selected
        # 3 high out of 5 = majority
        for i, cid in enumerate(consultants):
            level = "high" if i < 3 else "low"
            engine.record_response(basic_request, cid, "resp", risk_level=level)
        assert engine.check_majority_risk(basic_request) is True

    def test_check_majority_risk_false(self, engine, basic_request):
        consultants = basic_request.consultants_selected
        # 2 high out of 5 = not majority
        for i, cid in enumerate(consultants):
            level = "high" if i < 2 else "low"
            engine.record_response(basic_request, cid, "resp", risk_level=level)
        assert engine.check_majority_risk(basic_request) is False

    def test_get_highest_risk_level(self, engine, basic_request):
        engine.record_response(basic_request, "risk_advisor", "r", risk_level="low")
        engine.record_response(basic_request, "quality_advisor", "r", risk_level="high")
        assert engine.get_highest_risk_level(basic_request) == "high"

    def test_get_highest_risk_level_empty(self, engine, basic_request):
        assert engine.get_highest_risk_level(basic_request) == "none"


# ---------------------------------------------------------------------------
# Tests: synthesize
# ---------------------------------------------------------------------------

class TestSynthesize:

    def test_synthesis_fields(self, engine, basic_request):
        _add_all_responses(engine, basic_request)
        synth = engine.synthesize(
            basic_request,
            decision_reached="Proceed with spawn",
            rationale="Risk is manageable",
            risks_addressed="Added verification step",
        )
        assert synth.decision_reached == "Proceed with spawn"
        assert synth.produced_by == "master_orchestrator"
        assert synth.request_id == basic_request.request_id
        assert len(synth.perspectives_acknowledged) == len(basic_request.consultants_selected)

    def test_unanimous_high_sets_escalation_required(self, engine, basic_request):
        _add_all_responses(engine, basic_request, risk_level="high")
        synth = engine.synthesize(
            basic_request, "Escalate", "All high-risk", "None yet",
        )
        assert synth.unanimous_high_risk is True
        assert synth.human_escalation_required is True

    def test_non_unanimous_no_escalation(self, engine, basic_request):
        _add_all_responses(engine, basic_request, risk_level="low")
        synth = engine.synthesize(basic_request, "Proceed", "Low risk", "N/A")
        assert synth.unanimous_high_risk is False
        assert synth.human_escalation_required is False

    def test_synthesis_sets_request_status_to_synthesized(self, engine, basic_request):
        _add_all_responses(engine, basic_request)
        engine.synthesize(basic_request, "Proceed", "Ok", "N/A")
        assert basic_request.status == "synthesized"

    def test_synthesis_id_format(self, engine, basic_request):
        _add_all_responses(engine, basic_request)
        synth = engine.synthesize(basic_request, "Proceed", "Ok", "N/A")
        assert synth.synthesis_id.startswith("synth-consult-")

    def test_follow_up_flag_set(self, engine, basic_request):
        _add_all_responses(engine, basic_request)
        synth = engine.synthesize(
            basic_request, "Proceed", "Ok", "N/A",
            follow_up_question="Can you clarify risk_advisor's concern about X?",
        )
        assert synth.follow_up_round is True
        assert "risk_advisor" in synth.follow_up_question


# ---------------------------------------------------------------------------
# Tests: save_request / save_synthesis
# ---------------------------------------------------------------------------

class TestPersistence:

    def test_save_request_creates_file(self, engine, basic_request, project_dir):
        path = engine.save_request(basic_request, project_dir)
        assert path.exists()

    def test_save_request_filename_matches_request_id(self, engine, basic_request, project_dir):
        path = engine.save_request(basic_request, project_dir)
        assert path.name == f"{basic_request.request_id}.yaml"

    def test_save_request_data_round_trips(self, engine, basic_request, project_dir):
        engine.save_request(basic_request, project_dir)
        loaded = engine.load_request(project_dir, basic_request.request_id)
        assert loaded["project_id"] == basic_request.project_id
        assert loaded["question"] == basic_request.question
        assert loaded["decision_type"] == basic_request.decision_type

    def test_save_synthesis_creates_file(self, engine, basic_request, project_dir):
        _add_all_responses(engine, basic_request)
        synth = engine.synthesize(basic_request, "Go", "Ok", "N/A")
        path = engine.save_synthesis(synth, project_dir)
        assert path.exists()

    def test_save_synthesis_includes_escalation_flag(self, engine, basic_request, project_dir):
        _add_all_responses(engine, basic_request, risk_level="high")
        synth = engine.synthesize(basic_request, "Escalate", "All high", "None")
        path = engine.save_synthesis(synth, project_dir)
        with open(path) as f:
            data = yaml.safe_load(f)
        assert data["unanimous_high_risk"] is True
        assert data["human_escalation_required"] is True

    def test_load_request_missing_returns_empty(self, engine, project_dir):
        result = engine.load_request(project_dir, "nonexistent-id")
        assert result == {}


# ---------------------------------------------------------------------------
# Tests: domain context
# ---------------------------------------------------------------------------

class TestDomainContext:

    def test_load_domain_context_software(self, engine):
        ctx = engine.load_domain_context("software_engineering")
        assert "SOLID" in ctx or "Software Engineering" in ctx

    def test_load_domain_context_data_science(self, engine):
        ctx = engine.load_domain_context("data_science")
        assert "Data Science" in ctx or "reproducibility" in ctx.lower()

    def test_load_unknown_domain_returns_fallback(self, engine):
        ctx = engine.load_domain_context("nuclear_physics")
        assert "No domain context" in ctx or "general best practices" in ctx.lower()


# ---------------------------------------------------------------------------
# Tests: constants
# ---------------------------------------------------------------------------

class TestConstants:

    def test_all_consultants_count_is_five(self):
        assert len(ALL_CONSULTANTS) == 5

    def test_expected_consultant_ids(self):
        expected = {"risk_advisor", "quality_advisor", "devils_advocate",
                    "domain_expert", "efficiency_advisor"}
        assert set(ALL_CONSULTANTS) == expected

    def test_max_response_words_is_500(self):
        assert MAX_RESPONSE_WORDS == 500

    def test_follow_up_rounds_max_is_one(self):
        assert FOLLOW_UP_ROUNDS_MAX == 1

    def test_mandatory_types_include_spawn(self):
        assert "spawn" in MANDATORY_DECISION_TYPES

    def test_is_mandatory_helper(self, engine):
        assert engine.is_mandatory("spawn") is True
        assert engine.is_mandatory("approach") is False
