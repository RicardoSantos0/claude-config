"""Tests for ResponseParser — proj-20260415-005-mas-run-orchestration-loop."""

import json
import pytest
from mas.core.engine.response_parser import ResponseParser, ParsedResponse


def _make_wire(**kwargs) -> str:
    wire = {"_v": "1.0", **kwargs}
    return f"Some agent reasoning here.\n\n```json\n{json.dumps(wire)}\n```"


class TestWireBlockExtraction:

    def test_parses_clean_wire_block(self):
        text = _make_wire(s="task:complete", rsn="all done")
        p = ResponseParser().parse(text)
        assert p.status == "task:complete"
        assert p.reasoning == "all done"
        assert not p.parse_errors

    def test_picks_last_json_fence(self):
        """When multiple fences exist, last one wins (wire block is at end)."""
        text = "```json\n{\"not\": \"wire\"}\n```\n\n" + _make_wire(s="eval:pass")
        p = ResponseParser().parse(text)
        assert p.status == "eval:pass"

    def test_no_wire_block_accumulates_error(self):
        p = ResponseParser().parse("Plain text response with no wire block.")
        assert "no_wire_block_found" in p.parse_errors
        assert p.status == ""

    def test_malformed_json_accumulates_error(self):
        text = "```json\n{broken json\n```"
        p = ResponseParser().parse(text)
        assert any("parse_error" in e or "no_wire_block" in e for e in p.parse_errors)

    def test_json_fence_without_language_tag(self):
        wire = {"_v": "1.0", "s": "task:complete"}
        text = f"response\n\n```\n{json.dumps(wire)}\n```"
        p = ResponseParser().parse(text)
        assert p.status == "task:complete"


class TestDecisionsAndArtifacts:

    def test_dec_list_populates_decisions(self):
        text = _make_wire(s="task:complete",
                          dec=[{"id": "d-001", "v": "use sqlite"},
                               {"id": "d-002", "v": "no spawn"}])
        p = ResponseParser().parse(text)
        assert len(p.decisions) == 2
        assert p.decisions[0]["id"] == "d-001"
        assert p.decisions[1]["v"] == "no spawn"

    def test_art_list_populates_artifacts(self):
        text = _make_wire(s="task:complete",
                          art=["path/to/a.yaml", "path/to/b.md"])
        p = ResponseParser().parse(text)
        assert p.artifacts == ["path/to/a.yaml", "path/to/b.md"]

    def test_empty_dec_returns_empty_list(self):
        text = _make_wire(s="task:complete")
        p = ResponseParser().parse(text)
        assert p.decisions == []

    def test_non_list_dec_returns_empty(self):
        text = _make_wire(s="task:complete", dec="not a list")
        p = ResponseParser().parse(text)
        assert p.decisions == []


class TestNextActionResolution:

    def test_explicit_next_action_wins(self):
        text = _make_wire(s="task:complete", next_action="delegate", next_agent="scribe_agent")
        p = ResponseParser().parse(text)
        assert p.next_action == "delegate"
        assert p.next_agent == "scribe_agent"

    def test_task_complete_maps_to_advance_phase(self):
        text = _make_wire(s="task:complete")
        p = ResponseParser().parse(text)
        assert p.next_action == "advance_phase"

    def test_spec_ready_maps_to_advance_phase(self):
        text = _make_wire(s="spec:ready")
        p = ResponseParser().parse(text)
        assert p.next_action == "advance_phase"

    def test_escalate_status_maps_to_escalate(self):
        text = _make_wire(s="escalate")
        p = ResponseParser().parse(text)
        assert p.next_action == "escalate"

    def test_unknown_status_maps_to_wait(self):
        text = _make_wire(s="unknown:status")
        p = ResponseParser().parse(text)
        assert p.next_action == "wait"

    def test_no_wire_block_maps_to_wait(self):
        p = ResponseParser().parse("plain text")
        assert p.next_action == "wait"


class TestConsultationTrigger:

    def test_consultation_trigger_parsed(self):
        trigger = {
            "decision_type": "spawn",
            "question": "Should we spawn a specialist?",
            "context": {"gap": "no agent covers X"},
        }
        text = _make_wire(s="task:complete", consultation_trigger=trigger)
        p = ResponseParser().parse(text)
        assert p.consultation_trigger is not None
        assert p.consultation_trigger["decision_type"] == "spawn"
        assert p.consultation_trigger["question"] == "Should we spawn a specialist?"

    def test_no_consultation_trigger_is_none(self):
        text = _make_wire(s="task:complete")
        p = ResponseParser().parse(text)
        assert p.consultation_trigger is None


class TestKnowledgeRequest:

    def test_knowledge_request_extracted(self):
        text = (
            "I need some context.\n\n"
            'KNOWLEDGE_REQUEST: {"question": "What are best practices?", '
            '"notebook_id": "ai-agents"}\n\n'
            + _make_wire(s="wait")
        )
        p = ResponseParser().parse(text)
        assert p.knowledge_request is not None
        assert p.knowledge_request["question"] == "What are best practices?"
        assert p.knowledge_request["notebook_id"] == "ai-agents"

    def test_no_knowledge_request_is_none(self):
        text = _make_wire(s="task:complete")
        p = ResponseParser().parse(text)
        assert p.knowledge_request is None

    def test_knowledge_request_present_maps_to_wait(self):
        """When KNOWLEDGE_REQUEST is present without explicit next_action, wait."""
        text = (
            'KNOWLEDGE_REQUEST: {"question": "What is X?"}\n\n'
            + _make_wire(s="wait")
        )
        p = ResponseParser().parse(text)
        assert p.next_action == "wait"


class TestReasoningWordLimit:

    def test_long_rsn_accumulates_warning(self):
        long_rsn = " ".join(["word"] * 110)
        text = _make_wire(s="task:complete", rsn=long_rsn)
        p = ResponseParser().parse(text)
        assert any("rsn_exceeds" in e for e in p.parse_errors)

    def test_short_rsn_no_warning(self):
        text = _make_wire(s="task:complete", rsn="short reasoning")
        p = ResponseParser().parse(text)
        assert not any("rsn_exceeds" in e for e in p.parse_errors)
