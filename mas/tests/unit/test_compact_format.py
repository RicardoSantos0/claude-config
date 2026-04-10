"""
Unit Tests — Compact Wire Format
Tests round-trip compact↔expand for HandoffEngine and ConsultationEngine,
and _strip_empty / _compact_projection helpers in PromptAssembler.
"""
import pytest

from core.handoff_engine import HandoffEngine
from core.consultation_engine import ConsultationEngine
from core.prompt_assembler import _strip_empty, _compact_projection


# ---------------------------------------------------------------------------
# HandoffEngine compact ↔ expand
# ---------------------------------------------------------------------------

@pytest.fixture
def full_handoff():
    return {
        "handoff_id": "ho-proj-001-001",
        "project_id": "proj-001",
        "timestamp": "2025-06-01T12:00:00Z",
        "from_agent": "master_orchestrator",
        "to_agent": "scribe_agent",
        "authorized_by": "master_orchestrator",
        "phase": "intake",
        "task_description": "Initialize project folder",
        "payload": {
            "summary": "Project initialized",
            "artifacts_produced": ["spec.yaml"],
            "decisions_made": [],
            "open_questions": ["What is the deadline?"],
            "constraints_for_next": [],
            "shared_state_fields_modified": ["core_identity.status"],
        },
        "token_usage": {
            "prompt_tokens": 500,
            "completion_tokens": 200,
            "total_tokens": 700,
        },
        "acceptance": {
            "status": "pending",
            "rejection_reason": None,
            "follow_up_questions": None,
            "accepted_at": None,
        },
    }


class TestHandoffCompact:
    def test_compact_uses_short_keys(self, full_handoff):
        c = HandoffEngine.compact(full_handoff)
        assert "id" in c
        assert "pid" in c
        assert "handoff_id" not in c
        assert "project_id" not in c

    def test_compact_omits_empty_lists(self, full_handoff):
        c = HandoffEngine.compact(full_handoff)
        p = c["p"]
        assert "dec" not in p  # decisions_made was []
        assert "con" not in p  # constraints_for_next was []
        assert "s" in p  # summary present
        assert "oq" in p  # open_questions had content

    def test_compact_token_usage(self, full_handoff):
        c = HandoffEngine.compact(full_handoff)
        assert c["tok"] == [500, 200, 700]

    def test_compact_omits_zero_tokens(self, full_handoff):
        full_handoff["token_usage"] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        c = HandoffEngine.compact(full_handoff)
        assert "tok" not in c

    def test_round_trip_preserves_data(self, full_handoff):
        c = HandoffEngine.compact(full_handoff)
        expanded = HandoffEngine.expand(c)
        # Key fields preserved
        assert expanded["handoff_id"] == full_handoff["handoff_id"]
        assert expanded["project_id"] == full_handoff["project_id"]
        assert expanded["from_agent"] == full_handoff["from_agent"]
        assert expanded["payload"]["summary"] == full_handoff["payload"]["summary"]
        assert expanded["payload"]["open_questions"] == full_handoff["payload"]["open_questions"]
        assert expanded["token_usage"] == full_handoff["token_usage"]

    def test_expand_passthrough_already_expanded(self, full_handoff):
        result = HandoffEngine.expand(full_handoff)
        assert result is full_handoff

    def test_compact_acceptance_status(self, full_handoff):
        full_handoff["acceptance"]["status"] = "accepted"
        full_handoff["acceptance"]["accepted_at"] = "2025-06-01T12:05:00Z"
        c = HandoffEngine.compact(full_handoff)
        assert c["acc"] == "accepted"
        assert c["aat"] == "2025-06-01T12:05:00Z"

    def test_compact_rejection(self, full_handoff):
        full_handoff["acceptance"]["status"] = "rejected"
        full_handoff["acceptance"]["rejection_reason"] = "Incomplete payload"
        c = HandoffEngine.compact(full_handoff)
        assert c["acc"] == "rejected"
        assert c["rej"] == "Incomplete payload"

    def test_compact_preserves_extra_payload_keys(self, full_handoff):
        full_handoff["payload"]["custom_field"] = "custom_value"
        c = HandoffEngine.compact(full_handoff)
        assert c["p"]["custom_field"] == "custom_value"


# ---------------------------------------------------------------------------
# ConsultationEngine compact ↔ expand
# ---------------------------------------------------------------------------

@pytest.fixture
def full_response():
    return {
        "response_text": "I recommend proceeding with caution.",
        "word_count": 7,
        "risk_level": "medium",
        "key_concerns": ["Budget overrun", "Timeline risk"],
        "recommendation": "Proceed with mitigation plan",
        "responded_at": "2025-06-01T12:00:00Z",
        "truncated": False,
    }


@pytest.fixture
def full_request():
    return {
        "request_id": "cr-proj-001-001",
        "project_id": "proj-001",
        "timestamp": "2025-06-01T12:00:00Z",
        "requested_by": "master_orchestrator",
        "question": "Should we spawn a reporting agent?",
        "context": {"current_agents": 3},
        "decision_type": "spawn",
        "mandatory": True,
        "consultants_selected": ["risk_advisor", "quality_advisor"],
        "domain_context": "",
        "follow_up_round": 0,
        "follow_up_question": "",
        "status": "pending",
        "responses": {
            "risk_advisor": {
                "response_text": "High risk due to budget.",
                "word_count": 6,
                "risk_level": "high",
                "key_concerns": ["Budget"],
                "recommendation": "Do not spawn",
                "responded_at": "2025-06-01T12:01:00Z",
                "truncated": False,
            }
        },
    }


class TestConsultationCompactResponse:
    def test_compact_uses_short_keys(self, full_response):
        c = ConsultationEngine.compact_response(full_response)
        assert "r" in c
        assert "response_text" not in c

    def test_compact_risk_level_abbreviated(self, full_response):
        c = ConsultationEngine.compact_response(full_response)
        assert c["rl"] == "m"  # medium → m

    def test_compact_omits_false_truncated(self, full_response):
        c = ConsultationEngine.compact_response(full_response)
        assert "tr" not in c

    def test_round_trip_response(self, full_response):
        c = ConsultationEngine.compact_response(full_response)
        expanded = ConsultationEngine.expand_response(c)
        assert expanded["response_text"] == full_response["response_text"]
        assert expanded["risk_level"] == full_response["risk_level"]
        assert expanded["key_concerns"] == full_response["key_concerns"]

    def test_expand_passthrough_already_expanded(self, full_response):
        result = ConsultationEngine.expand_response(full_response)
        assert result is full_response


class TestConsultationCompactRequest:
    def test_compact_uses_short_keys(self, full_request):
        c = ConsultationEngine.compact_request(full_request)
        assert "pid" in c
        assert "project_id" not in c

    def test_compact_omits_empty_strings(self, full_request):
        c = ConsultationEngine.compact_request(full_request)
        assert "dom" not in c  # domain_context was ""
        assert "fuq" not in c  # follow_up_question was ""

    def test_compact_omits_zero_follow_up_round(self, full_request):
        c = ConsultationEngine.compact_request(full_request)
        assert "fur" not in c

    def test_compact_includes_nested_responses(self, full_request):
        c = ConsultationEngine.compact_request(full_request)
        assert "resp" in c
        assert "risk_advisor" in c["resp"]
        assert c["resp"]["risk_advisor"]["rl"] == "h"  # high → h

    def test_round_trip_request(self, full_request):
        c = ConsultationEngine.compact_request(full_request)
        expanded = ConsultationEngine.expand_request(c)
        assert expanded["project_id"] == full_request["project_id"]
        assert expanded["question"] == full_request["question"]
        assert expanded["mandatory"] == full_request["mandatory"]
        assert "risk_advisor" in expanded["responses"]
        assert expanded["responses"]["risk_advisor"]["risk_level"] == "high"

    def test_expand_passthrough_already_expanded(self, full_request):
        result = ConsultationEngine.expand_request(full_request)
        assert result is full_request


# ---------------------------------------------------------------------------
# PromptAssembler helpers
# ---------------------------------------------------------------------------

class TestStripEmpty:
    def test_removes_none(self):
        assert _strip_empty({"a": None, "b": 1}) == {"b": 1}

    def test_removes_empty_list(self):
        assert _strip_empty({"a": [], "b": [1]}) == {"b": [1]}

    def test_removes_empty_dict(self):
        assert _strip_empty({"a": {}, "b": {"x": 1}}) == {"b": {"x": 1}}

    def test_removes_empty_string(self):
        assert _strip_empty({"a": "", "b": "text"}) == {"b": "text"}

    def test_nested_cleanup(self):
        result = _strip_empty({"x": {"a": None, "b": []}, "y": 1})
        assert result == {"y": 1}

    def test_all_empty_returns_none(self):
        assert _strip_empty({"a": None, "b": []}) is None

    def test_preserves_zero(self):
        assert _strip_empty({"a": 0}) == {"a": 0}

    def test_preserves_false(self):
        assert _strip_empty({"a": False}) == {"a": False}


class TestCompactProjection:
    def test_strips_meta(self):
        state = {
            "core_identity": {"project_id": "proj-001"},
            "_meta": {"created_at": "2025-06-01", "version": "1.0"},
        }
        result = _compact_projection(state)
        assert "_meta" not in result
        assert "core_identity" in result

    def test_trims_handoff_history(self):
        state = {
            "workflow": {
                "handoff_history": [
                    {"handoff_id": f"ho-{i}"} for i in range(10)
                ],
                "current_owner": "master_orchestrator",
            }
        }
        result = _compact_projection(state)
        assert len(result["workflow"]["handoff_history"]) == 2
        assert result["workflow"]["handoff_history"][0]["handoff_id"] == "ho-8"

    def test_trims_consultation_requests(self):
        state = {
            "consultation": {
                "consultation_requests": [
                    {"request_id": f"cr-{i}"} for i in range(5)
                ]
            }
        }
        result = _compact_projection(state)
        assert len(result["consultation"]["consultation_requests"]) == 1
        assert result["consultation"]["consultation_requests"][0]["request_id"] == "cr-4"

    def test_strips_empty_after_compaction(self):
        state = {
            "core_identity": {"project_id": "proj-001"},
            "workflow": {"handoff_history": [], "pending_assignments": []},
        }
        result = _compact_projection(state)
        assert "core_identity" in result
        assert "workflow" not in result  # all fields were empty

    def test_returns_empty_dict_for_all_empty(self):
        state = {"_meta": {"ts": "2025-01-01"}}
        result = _compact_projection(state)
        assert result == {}
