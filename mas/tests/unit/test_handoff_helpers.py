"""Tests for mas/core/handoff_helpers.py"""

import pytest

from core.engine.handoff_helpers import (
    build_reanchor_payload,
    extract_delta,
    summarise_handoff_history,
    payload_token_estimate,
)


# --- build_reanchor_payload ---

def test_build_reanchor_payload_required_fields():
    payload = build_reanchor_payload(
        project_id="proj-001",
        phase="execution",
        current_owner="master_orchestrator",
        next_agent="scribe_agent",
        next_action="write checkpoint",
    )
    assert payload["re_anchor"] is True
    assert payload["project_id"] == "proj-001"
    assert payload["phase"] == "execution"
    assert payload["from_agent"] == "master_orchestrator"
    assert payload["to_agent"] == "scribe_agent"
    assert payload["next_action"] == "write checkpoint"
    assert "as_of" in payload


def test_build_reanchor_payload_defaults_empty_lists():
    payload = build_reanchor_payload("proj-001", "planning",
                                     "master_orchestrator", "pm_agent", "plan")
    assert payload["tried"] == []
    assert payload["worked"] == []
    assert payload["failed"] == []
    assert payload["do_not_retry"] == []
    assert payload["open_questions"] == []
    assert payload["artifacts_produced"] == []
    assert payload["decisions_made"] == []


def test_build_reanchor_payload_with_history():
    payload = build_reanchor_payload(
        "proj-001", "execution", "master_orchestrator", "evaluator_agent",
        "evaluate M1",
        tried=["M1 tasks"],
        worked=["T-M1-001", "T-M1-002"],
        failed=["T-M1-003 — timeout"],
        do_not_retry=["T-M1-003 without timeout increase"],
    )
    assert "M1 tasks" in payload["tried"]
    assert "T-M1-001" in payload["worked"]
    assert len(payload["failed"]) == 1
    assert len(payload["do_not_retry"]) == 1


# --- extract_delta ---

def test_extract_delta_detects_changed_fields():
    prev = {"phase": "planning", "status": "active", "owner": "master"}
    curr = {"phase": "execution", "status": "active", "owner": "evaluator"}
    delta = extract_delta(prev, curr)
    assert "phase" in delta
    assert "owner" in delta
    assert "status" not in delta


def test_extract_delta_no_changes():
    state = {"phase": "planning", "status": "active"}
    delta = extract_delta(state, state)
    assert delta == {}


def test_extract_delta_new_field():
    prev = {"phase": "planning"}
    curr = {"phase": "planning", "new_field": "new_value"}
    delta = extract_delta(prev, curr)
    assert "new_field" in delta


def test_extract_delta_watched_fields():
    prev = {"a": 1, "b": 2, "c": 3}
    curr = {"a": 99, "b": 2, "c": 99}
    delta = extract_delta(prev, curr, watched_fields=["a"])
    assert "a" in delta
    assert "c" not in delta


# --- summarise_handoff_history ---

SAMPLE_HISTORY = [
    {
        "handoff_id": f"ho-{i:03d}",
        "from_agent": "master_orchestrator",
        "to_agent": "scribe_agent",
        "phase": "intake",
        "timestamp": f"2026-04-11T{i:02d}:00:00Z",
        "payload": {"summary": f"step {i}", "large_data": "x" * 1000},
        "acceptance": {"status": "accepted"},
    }
    for i in range(10)
]


def test_summarise_handoff_history_last_n():
    summaries = summarise_handoff_history(SAMPLE_HISTORY, last_n=3)
    assert len(summaries) == 3
    assert summaries[-1]["handoff_id"] == "ho-009"


def test_summarise_handoff_history_strips_large_payload():
    summaries = summarise_handoff_history(SAMPLE_HISTORY, last_n=1)
    assert "large_data" not in summaries[0]
    assert summaries[0]["summary"] == "step 9"


def test_summarise_handoff_history_empty():
    assert summarise_handoff_history([]) == []


def test_summarise_handoff_history_fewer_than_n():
    summaries = summarise_handoff_history(SAMPLE_HISTORY[:2], last_n=5)
    assert len(summaries) == 2


# --- payload_token_estimate ---

def test_payload_token_estimate_non_zero():
    payload = {"key": "value" * 100}
    estimate = payload_token_estimate(payload)
    assert estimate > 0


def test_payload_token_estimate_larger_payload_more_tokens():
    small = {"a": "x" * 10}
    large = {"a": "x" * 1000}
    assert payload_token_estimate(large) > payload_token_estimate(small)
