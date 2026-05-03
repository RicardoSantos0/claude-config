"""Tests for mas.core.engine.lifecycle_guard."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from mas.core.engine.lifecycle_guard import LifecycleGuard


@pytest.fixture
def guard():
    return LifecycleGuard()


@pytest.fixture
def project_dir(tmp_path):
    return tmp_path


def _make_artifact(project_dir: Path, rel_path: str) -> Path:
    p = project_dir / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("artifact")
    return p


# ---------------------------------------------------------------------------
# check_phase_artifacts
# ---------------------------------------------------------------------------

def test_intake_passes_with_original_brief(guard, project_dir):
    _make_artifact(project_dir, "intake/original_brief.md")
    result = guard.check_phase_artifacts("intake", project_dir)
    assert result.passed


def test_intake_fails_without_original_brief(guard, project_dir):
    result = guard.check_phase_artifacts("intake", project_dir)
    assert not result.passed
    assert any("original_brief" in v["missing"] for v in result.violations)


def test_planning_requires_both_plans(guard, project_dir):
    _make_artifact(project_dir, "planning/product_plan.yaml")
    result = guard.check_phase_artifacts("planning", project_dir)
    assert not result.passed
    assert any("execution_plan" in v["missing"] for v in result.violations)


def test_planning_passes_with_both_plans(guard, project_dir):
    _make_artifact(project_dir, "planning/product_plan.yaml")
    _make_artifact(project_dir, "planning/execution_plan.yaml")
    result = guard.check_phase_artifacts("planning", project_dir)
    assert result.passed


def test_unknown_phase_passes_with_no_requirements(guard, project_dir):
    result = guard.check_phase_artifacts("nonexistent_phase", project_dir)
    assert result.passed


# ---------------------------------------------------------------------------
# check_close
# ---------------------------------------------------------------------------

def _closed_state(extra_pending=None, open_questions=None):
    state = {
        "core_identity": {"status": "closed"},
        "workflow": {"pending_assignments": extra_pending or []},
        "decisions": {"open_questions": open_questions or []},
    }
    return state


def test_close_blocked_with_pending_handoffs(guard, project_dir):
    state = _closed_state(extra_pending=[{"id": "h-1"}])
    result = guard.check_close(project_dir, state)
    assert result.blocked
    assert any("no-close-with-open-handoffs" in v["invariant"] for v in result.violations)


def test_close_warns_with_open_questions(guard, project_dir):
    _make_artifact(project_dir, "CLOSED.md")
    _make_artifact(project_dir, "final_shared_state.yaml")
    state = _closed_state(open_questions=[{"q": "unanswered"}])
    result = guard.check_close(project_dir, state)
    assert any("no-close-with-open-questions" in w["invariant"] for w in result.warnings)


def test_close_passes_clean_state(guard, project_dir):
    _make_artifact(project_dir, "CLOSED.md")
    _make_artifact(project_dir, "final_shared_state.yaml")
    result = guard.check_close(project_dir, _closed_state())
    assert result.passed


# ---------------------------------------------------------------------------
# check_spawn
# ---------------------------------------------------------------------------

def test_spawn_blocked_without_gap_cert(guard, project_dir):
    result = guard.check_spawn(project_dir)
    assert result.blocked
    assert any("gap_certificate" in v["missing"] for v in result.violations)


def test_spawn_passes_with_gap_cert(guard, project_dir):
    _make_artifact(project_dir, "governance/gap_certificate.yaml")
    result = guard.check_spawn(project_dir)
    assert result.passed


# ---------------------------------------------------------------------------
# GuardResult properties
# ---------------------------------------------------------------------------

def test_guard_result_blocked_is_not_passed():
    from mas.core.engine.lifecycle_guard import GuardResult
    r = GuardResult(passed=False, violations=[{"invariant": "x", "severity": "block"}])
    assert r.blocked
    assert not r.passed


def test_guard_result_passed_is_not_blocked():
    from mas.core.engine.lifecycle_guard import GuardResult
    r = GuardResult(passed=True)
    assert not r.blocked
