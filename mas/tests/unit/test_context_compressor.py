"""Tests for mas/core/context_compressor.py"""

import json
import pytest

from core.engine.context_compressor import (
    compress,
    compression_ratio,
    estimate_tokens,
    build_reanchor,
    SUMMARY_FIELDS,
)

SAMPLE_STATE = {
    "core_identity": {
        "project_id": "proj-001",
        "current_phase": "execution",
        "status": "active",
        "created_at": "2026-04-11T00:00:00Z",
        "updated_at": "2026-04-11T12:00:00Z",
        "request_id": "req-001",
    },
    "project_definition": {
        "project_goal": "Test goal",
        "success_criteria": ["criterion A", "criterion B"],
        "original_brief": "Long original brief text " * 50,
    },
    "workflow": {
        "current_owner": "master_orchestrator",
        "completed_phases": ["intake", "planning"],
        "pending_assignments": [],
        "active_agents": [],
        "handoff_history": [{"handoff_id": f"ho-{i}"} for i in range(10)],
    },
    "decisions": {
        "open_questions": ["Q1"],
        "decision_log": [{"id": "dec-001", "decision": "proceed"}] * 20,
        "assumptions": [],
        "approvals": [],
        "policy_flags": [],
    },
    "artifacts": {"documents": [], "deliverables": [], "change_log": []},
    "execution": {
        "milestones": [{"id": "M1"}] * 5,
        "tasks": [{"id": f"T-{i}"} for i in range(26)],
        "progress_reports": [],
        "blocker_alerts": [],
    },
}


# --- compress summary ---

def test_compress_summary_includes_high_signal_fields():
    result = compress(SAMPLE_STATE, mode="summary")
    assert result["core_identity"]["project_id"] == "proj-001"
    assert result["core_identity"]["current_phase"] == "execution"
    assert result["project_definition"]["project_goal"] == "Test goal"
    assert result["workflow"]["current_owner"] == "master_orchestrator"


def test_compress_summary_excludes_low_signal_fields():
    result = compress(SAMPLE_STATE, mode="summary")
    assert "created_at" not in result.get("core_identity", {})
    assert "handoff_history" not in result.get("workflow", {})
    assert "decision_log" not in result.get("decisions", {})
    assert "execution" not in result
    assert "artifacts" not in result


def test_compress_summary_achieves_30pct_reduction():
    result = compress(SAMPLE_STATE, mode="summary")
    ratio = compression_ratio(SAMPLE_STATE, result)
    assert ratio < 0.70, f"Expected <70% of original size, got {ratio:.2%}"


# --- compress detail ---

def test_compress_detail_includes_more_fields():
    result = compress(SAMPLE_STATE, mode="detail")
    assert "handoff_history" in result.get("workflow", {})
    assert "decision_log" in result.get("decisions", {})


def test_compress_detail_still_smaller_than_full():
    result_detail = compress(SAMPLE_STATE, mode="detail")
    ratio = compression_ratio(SAMPLE_STATE, result_detail)
    # Detail mode should still drop some fields (execution tasks, artifacts)
    assert ratio < 1.0


# --- compress full ---

def test_compress_full_returns_unchanged():
    result = compress(SAMPLE_STATE, mode="full")
    assert result == SAMPLE_STATE


# --- compress reanchor ---

def test_compress_reanchor_minimal_fields():
    result = compress(SAMPLE_STATE, mode="reanchor")
    assert result["project_id"] == "proj-001"
    assert result["phase"] == "execution"
    assert result["current_owner"] == "master_orchestrator"
    # No large lists
    assert "handoff_history" not in result
    assert "decision_log" not in result
    assert "tasks" not in result


def test_compress_reanchor_very_small():
    result = compress(SAMPLE_STATE, mode="reanchor")
    ratio = compression_ratio(SAMPLE_STATE, result)
    assert ratio < 0.05, f"Re-anchor should be tiny, got {ratio:.2%}"


# --- estimate_tokens ---

def test_estimate_tokens_rough():
    text = "a" * 400
    assert estimate_tokens(text) == 100


def test_estimate_tokens_minimum():
    assert estimate_tokens("") >= 1


# --- build_reanchor ---

def test_build_reanchor_structure():
    payload = build_reanchor(
        project_id="proj-001",
        phase="execution",
        current_owner="master_orchestrator",
        tried=["approach A"],
        worked=["step 1"],
        failed=["step 2"],
        do_not_retry=["approach A"],
        next_action="proceed to M2",
    )
    assert payload["project_id"] == "proj-001"
    assert payload["tried"] == ["approach A"]
    assert payload["do_not_retry"] == ["approach A"]
    assert payload["next_action"] == "proceed to M2"


def test_build_reanchor_defaults():
    payload = build_reanchor("proj-001", "planning", "master_orchestrator")
    assert payload["tried"] == []
    assert payload["worked"] == []
    assert payload["open_questions"] == []


# --- compression_ratio ---

def test_compression_ratio_zero_original():
    ratio = compression_ratio({}, {})
    assert ratio == 1.0


def test_compression_ratio_smaller_result():
    original = {"a": "x" * 1000}
    compressed = {"a": "x"}
    ratio = compression_ratio(original, compressed)
    assert ratio < 0.1
