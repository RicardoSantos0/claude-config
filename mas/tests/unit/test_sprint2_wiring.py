"""Sprint 2 wiring tests — EventRecorder, OutputLinter, SkillBridge."""
from __future__ import annotations

import warnings
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sm(tmp_path: Path, project_id: str = "proj-test-sprint2") -> "SharedStateManager":  # noqa: F821
    from mas.core.engine.shared_state_manager import SharedStateManager
    project_dir = tmp_path / project_id
    project_dir.mkdir(parents=True, exist_ok=True)
    state = {
        "core_identity": {"project_id": project_id, "status": "active",
                          "current_phase": "execution"},
        "workflow": {"handoff_history": [], "completed_phases": []},
        "decisions": {},
        "_meta": {"governance_violations": []},
    }
    state_path = project_dir / "shared_state.yaml"
    with open(state_path, "w") as f:
        yaml.dump(state, f)

    with patch("mas.core.engine.shared_state_manager.get_logger", return_value=MagicMock()):
        sm = SharedStateManager(project_id, projects_root=tmp_path)
    return sm


# ---------------------------------------------------------------------------
# EventRecorder wired into HandoffEngine
# ---------------------------------------------------------------------------

class TestHandoffEngineUsesEventRecorder:
    """AC-01: HandoffEngine create/accept/reject go through EventRecorder."""

    def test_create_calls_event_recorder(self, tmp_path):
        from mas.core.engine.handoff_engine import HandoffEngine
        sm = _make_sm(tmp_path)
        engine = HandoffEngine(audit_logger=MagicMock())

        recorded = []

        def fake_record_simple(project_id, actor, action_type, intent, **kwargs):
            recorded.append(action_type)
            return "fake-action-id"

        with patch("core.engine.event_recorder.EventRecorder.record_simple",
                   side_effect=fake_record_simple):
            engine.create(
                sm,
                from_agent="master_orchestrator",
                to_agent="scribe_agent",
                phase="execution",
                task_description="Test task",
                payload={
                    "summary": "test",
                    "artifacts_produced": [],
                    "decisions_made": [],
                    "open_questions": [],
                    "constraints_for_next": [],
                    "shared_state_fields_modified": [],
                },
            )

        assert "handoff_created" in recorded

    def test_accept_calls_event_recorder(self, tmp_path):
        from mas.core.engine.handoff_engine import HandoffEngine
        sm = _make_sm(tmp_path)
        engine = HandoffEngine(audit_logger=MagicMock())

        with patch("core.engine.event_recorder.EventRecorder.record_simple",
                   return_value="id") as mock_record:
            with patch("mas.core.engine.handoff_engine.CheckpointWriter"):
                # Put a handoff into state first
                state = sm.load()
                state["workflow"]["handoff_history"] = [{
                    "handoff_id": "ho-proj-test-sprint2-001",
                    "acceptance": {"status": "pending",
                                   "rejection_reason": None,
                                   "follow_up_questions": None,
                                   "accepted_at": None},
                }]
                with open(sm.state_path, "w") as f:
                    yaml.dump(state, f)

                engine.accept(sm, "ho-proj-test-sprint2-001")

        calls = [c.kwargs.get("action_type") or c.args[2]
                 for c in mock_record.call_args_list]
        assert "handoff_accepted" in calls

    def test_create_is_nonfatal_when_recorder_raises(self, tmp_path):
        from mas.core.engine.handoff_engine import HandoffEngine
        sm = _make_sm(tmp_path)
        engine = HandoffEngine(audit_logger=MagicMock())

        with patch("core.engine.event_recorder.EventRecorder.record_simple",
                   side_effect=RuntimeError("DB gone")):
            # Should not raise
            handoff = engine.create(
                sm,
                from_agent="master_orchestrator",
                to_agent="scribe_agent",
                phase="execution",
                task_description="Test task",
                payload={
                    "summary": "test",
                    "artifacts_produced": [],
                    "decisions_made": [],
                    "open_questions": [],
                    "constraints_for_next": [],
                    "shared_state_fields_modified": [],
                },
            )
        assert handoff["handoff_id"].startswith("ho-")


# ---------------------------------------------------------------------------
# OutputLinter wired into HandoffEngine
# ---------------------------------------------------------------------------

class TestHandoffEngineLintsOutput:
    """AC-12: OutputLinter runs on handoff summary; findings are output_lint events."""

    def test_verbose_summary_triggers_lint_event(self, tmp_path):
        from mas.core.engine.handoff_engine import HandoffEngine
        sm = _make_sm(tmp_path)
        engine = HandoffEngine(audit_logger=MagicMock())

        lint_events = []

        def capture_record(project_id, actor, action_type, intent, **kwargs):
            lint_events.append(action_type)
            return "id"

        verbose_summary = " ".join(["word"] * 900)  # 900 words > 800 threshold
        with patch("core.engine.event_recorder.EventRecorder.record_simple",
                   side_effect=capture_record):
            engine.create(
                sm,
                from_agent="master_orchestrator",
                to_agent="scribe_agent",
                phase="execution",
                task_description="Test",
                payload={
                    "summary": verbose_summary,
                    "artifacts_produced": [],
                    "decisions_made": [],
                    "open_questions": [],
                    "constraints_for_next": [],
                    "shared_state_fields_modified": [],
                },
            )

        assert "output_lint" in lint_events

    def test_clean_summary_no_lint_event(self, tmp_path):
        from mas.core.engine.handoff_engine import HandoffEngine
        sm = _make_sm(tmp_path)
        engine = HandoffEngine(audit_logger=MagicMock())

        lint_events = []

        def capture_record(project_id, actor, action_type, intent, **kwargs):
            lint_events.append(action_type)
            return "id"

        clean_summary = '"s": "task:complete" "_v": "1.0" short summary'
        with patch("core.engine.event_recorder.EventRecorder.record_simple",
                   side_effect=capture_record):
            engine.create(
                sm,
                from_agent="master_orchestrator",
                to_agent="scribe_agent",
                phase="execution",
                task_description="Test",
                payload={
                    "summary": clean_summary,
                    "artifacts_produced": [],
                    "decisions_made": [],
                    "open_questions": [],
                    "constraints_for_next": [],
                    "shared_state_fields_modified": [],
                },
            )

        assert "output_lint" not in lint_events


# ---------------------------------------------------------------------------
# SkillBridge.render_skill_prompt
# ---------------------------------------------------------------------------

class TestSkillBridgeRenderPrompt:
    """AC-03: render_skill_prompt() returns usable markdown blocks."""

    def _bridge_with_mock_skill(self, tmp_path: Path) -> "SkillBridge":  # noqa: F821
        from mas.core.engine.skill_bridge import SkillBridge, SkillMetadata
        bridge = SkillBridge(skills_dir=tmp_path)
        bridge._cache = {
            "research-extract": SkillMetadata(
                name="research-extract",
                description="Extract research from sources",
                path=tmp_path / "research-extract" / "SKILL.md",
            )
        }
        return bridge

    def test_authorized_agent_gets_prompt(self, tmp_path):
        from mas.core.engine.skill_bridge import SkillBridge
        bridge = self._bridge_with_mock_skill(tmp_path)
        result = bridge.render_skill_prompt(
            "master_orchestrator", "research-extract", "query text"
        )
        assert "You are executing the following Claude Code skill" in result
        assert "# research-extract" in result
        assert "query text" in result

    def test_unauthorized_agent_gets_denied_message(self, tmp_path):
        from mas.core.engine.skill_bridge import SkillBridge
        bridge = self._bridge_with_mock_skill(tmp_path)
        result = bridge.render_skill_prompt("hr_agent", "research-extract", "query")
        assert "denied" in result

    def test_unknown_skill_gets_not_found_message(self, tmp_path):
        from mas.core.engine.skill_bridge import SkillBridge
        bridge = self._bridge_with_mock_skill(tmp_path)
        result = bridge.render_skill_prompt(
            "master_orchestrator", "nonexistent-skill", "query"
        )
        assert "not found" in result
