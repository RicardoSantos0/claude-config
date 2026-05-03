"""Tests for MAS skill trigger policy evaluation."""

from __future__ import annotations

from pathlib import Path

from core.engine.skill_trigger import SkillTriggerPolicy


def _state(phase="planning", status="active"):
    return {
        "core_identity": {
            "project_id": "proj-skill-test",
            "current_phase": phase,
            "status": status,
        },
        "decisions": {"open_questions": []},
    }


def test_resume_recommends_mas_review(tmp_path: Path):
    policy = SkillTriggerPolicy()
    recs = policy.recommendations_for(
        state=_state(phase="execution"),
        project_dir=tmp_path,
        event="project_resume",
    )

    assert any(r.skill == "mas-review" and r.required for r in recs)


def test_planning_without_execution_plan_recommends_mas_plan(tmp_path: Path):
    policy = SkillTriggerPolicy()
    (tmp_path / "planning").mkdir()
    (tmp_path / "planning" / "product_plan.yaml").write_text("ok", encoding="utf-8")

    recs = policy.recommendations_for(
        state=_state(phase="planning"),
        project_dir=tmp_path,
    )

    assert any(r.skill == "mas-plan" and r.rule_id == "skill-plan-before-execution" for r in recs)


def test_planning_with_execution_plan_does_not_recommend_mas_plan(tmp_path: Path):
    policy = SkillTriggerPolicy()
    (tmp_path / "planning").mkdir()
    (tmp_path / "planning" / "execution_plan.yaml").write_text("ok", encoding="utf-8")

    recs = policy.recommendations_for(
        state=_state(phase="planning"),
        project_dir=tmp_path,
    )

    assert not any(r.skill == "mas-plan" for r in recs)


def test_open_questions_recommend_mas_clarify(tmp_path: Path):
    policy = SkillTriggerPolicy()
    state = _state(phase="specification")
    state["decisions"]["open_questions"] = [{"q": "Which scope?"}]

    recs = policy.recommendations_for(state=state, project_dir=tmp_path)

    assert any(r.skill == "mas-clarify" for r in recs)


def test_core_path_change_recommends_mas_examine(tmp_path: Path):
    policy = SkillTriggerPolicy()

    recs = policy.recommendations_for(
        state=_state(phase="execution"),
        project_dir=tmp_path,
        changed_paths=["mas/core/engine/orchestration_loop.py"],
    )

    assert any(r.skill == "mas-examine" for r in recs)
