"""
Governance Tests — Unanimous Risk Hard Stop

When all responding consultants flag 'high' risk, the system MUST:
  1. Set unanimous_high_risk = True in the synthesis
  2. Set human_escalation_required = True in the synthesis
  3. Never allow progression past this point without human approval

This is the most consequential governance rule in the consultation system.
"""
import pytest
from core.engine.consultation_engine import (
    ConsultationEngine,
    ConsultationRequest,
    ALL_CONSULTANTS,
    CORE_THREE_CONSULTANTS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_request(project_id: str, consultants: list[str]) -> ConsultationRequest:
    return ConsultationRequest(
        request_id=f"consult-{project_id}-test",
        project_id=project_id,
        timestamp="2026-04-14T00:00:00+00:00",
        requested_by="master_orchestrator",
        question="Should we proceed?",
        context={},
        decision_type="spawn",
        mandatory=True,
        consultants_selected=consultants,
        responses={},
    )


def _high_response(consultant_id: str) -> dict:
    return {
        "consultant_id": consultant_id,
        "risk_level": "high",
        "key_concerns": ["critical concern"],
        "recommendation": "do not proceed",
        "response_text": "This is too risky.",
        "word_count": 5,
    }


def _low_response(consultant_id: str) -> dict:
    return {
        "consultant_id": consultant_id,
        "risk_level": "low",
        "key_concerns": [],
        "recommendation": "proceed",
        "response_text": "Looks fine.",
        "word_count": 2,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestUnanimousRiskHardStop:

    def test_all_five_high_triggers_unanimous(self):
        """When all 5 consultants flag high, unanimous_high_risk is True."""
        engine = ConsultationEngine()
        req = _make_request("proj-test", ALL_CONSULTANTS)
        for c in ALL_CONSULTANTS:
            req.responses[c] = _high_response(c)

        assert engine.check_unanimous_risk(req) is True

    def test_all_three_high_triggers_unanimous(self):
        """When all 3 core consultants flag high, unanimous_high_risk is True."""
        engine = ConsultationEngine()
        req = _make_request("proj-test-three", CORE_THREE_CONSULTANTS)
        for c in CORE_THREE_CONSULTANTS:
            req.responses[c] = _high_response(c)

        assert engine.check_unanimous_risk(req) is True

    def test_one_non_high_breaks_unanimity(self):
        """If even one consultant does not flag high, unanimous is False."""
        engine = ConsultationEngine()
        req = _make_request("proj-test-partial", ALL_CONSULTANTS)
        for c in ALL_CONSULTANTS[:-1]:
            req.responses[c] = _high_response(c)
        req.responses[ALL_CONSULTANTS[-1]] = _low_response(ALL_CONSULTANTS[-1])

        assert engine.check_unanimous_risk(req) is False

    def test_empty_responses_not_unanimous(self):
        """No responses → not unanimous (cannot escalate without evidence)."""
        engine = ConsultationEngine()
        req = _make_request("proj-test-empty", ALL_CONSULTANTS)

        assert engine.check_unanimous_risk(req) is False

    def test_synthesize_sets_human_escalation_when_unanimous(self):
        """synthesize() must set human_escalation_required=True on unanimous high risk."""
        engine = ConsultationEngine()
        req = _make_request("proj-test-synth", ALL_CONSULTANTS)
        for c in ALL_CONSULTANTS:
            req.responses[c] = _high_response(c)

        synthesis = engine.synthesize(req, "escalate", "unanimous high risk", "none")

        assert synthesis.unanimous_high_risk is True
        assert synthesis.human_escalation_required is True

    def test_synthesize_no_escalation_when_not_unanimous(self):
        """synthesize() must NOT set human_escalation when risk is not unanimous."""
        engine = ConsultationEngine()
        req = _make_request("proj-test-no-esc", ALL_CONSULTANTS)
        for c in ALL_CONSULTANTS[:-1]:
            req.responses[c] = _high_response(c)
        req.responses[ALL_CONSULTANTS[-1]] = _low_response(ALL_CONSULTANTS[-1])

        synthesis = engine.synthesize(req, "proceed", "majority agrees", "minor risks noted")

        assert synthesis.unanimous_high_risk is False
        assert synthesis.human_escalation_required is False

    def test_synthesis_dataclass_exposes_human_escalation_flag(self):
        """ConsultationSynthesis dataclass must expose human_escalation_required."""
        engine = ConsultationEngine()
        req = _make_request("proj-test-dict", ALL_CONSULTANTS)
        for c in ALL_CONSULTANTS:
            req.responses[c] = _high_response(c)

        synthesis = engine.synthesize(req, "escalate", "unanimous high risk", "none")

        assert synthesis.human_escalation_required is True
        assert synthesis.unanimous_high_risk is True
