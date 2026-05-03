"""AC-16: Integration tests — HandoffEngine+EventRecorder, close sequence, SkillBridge."""
from __future__ import annotations

import warnings
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sm(tmp_path: Path, project_id: str = "proj-test-integration"):
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
    with open(project_dir / "shared_state.yaml", "w") as f:
        yaml.dump(state, f)
    with patch("mas.core.engine.shared_state_manager.get_logger", return_value=MagicMock()):
        sm = SharedStateManager(project_id, projects_root=tmp_path)
    return sm


# ---------------------------------------------------------------------------
# HandoffEngine + EventRecorder integration
# ---------------------------------------------------------------------------

class TestHandoffEventRecorderIntegration:
    """AC-16: Full create→accept cycle records typed events."""

    def test_create_and_accept_record_typed_events(self, tmp_path):
        from mas.core.engine.handoff_engine import HandoffEngine

        sm = _make_sm(tmp_path)
        engine = HandoffEngine(audit_logger=MagicMock())

        recorded_types = []

        def capture(project_id, actor, action_type, intent, **kwargs):
            recorded_types.append(action_type)
            return "fake-id"

        with patch("core.engine.event_recorder.EventRecorder.record_simple",
                   side_effect=capture):
            with patch("core.engine.handoff_engine.CheckpointWriter"):
                handoff = engine.create(
                    sm,
                    from_agent="master_orchestrator",
                    to_agent="scribe_agent",
                    phase="execution",
                    task_description="Write checkpoint",
                    payload={
                        "summary": '"s": "task:delegated" "_v": "1.0"',
                        "artifacts_produced": [],
                        "decisions_made": [],
                        "open_questions": [],
                        "constraints_for_next": [],
                        "shared_state_fields_modified": [],
                    },
                )
                engine.accept(sm, handoff["handoff_id"])

        assert "handoff_created" in recorded_types
        assert "handoff_accepted" in recorded_types

    def test_reject_records_typed_event(self, tmp_path):
        from mas.core.engine.handoff_engine import HandoffEngine

        sm = _make_sm(tmp_path)
        engine = HandoffEngine(audit_logger=MagicMock())
        recorded_types = []

        def capture(project_id, actor, action_type, intent, **kwargs):
            recorded_types.append(action_type)
            return "fake-id"

        with patch("core.engine.event_recorder.EventRecorder.record_simple",
                   side_effect=capture):
            handoff = engine.create(
                sm,
                from_agent="master_orchestrator",
                to_agent="scribe_agent",
                phase="execution",
                task_description="Task",
                payload={
                    "summary": '"s": "task:delegated"',
                    "artifacts_produced": [], "decisions_made": [],
                    "open_questions": [], "constraints_for_next": [],
                    "shared_state_fields_modified": [],
                },
            )
            engine.reject(sm, handoff["handoff_id"], reason="missing context")

        assert "handoff_rejected" in recorded_types


# ---------------------------------------------------------------------------
# OutputLinter + HandoffEngine integration
# ---------------------------------------------------------------------------

class TestOutputLinterHandoffIntegration:
    """AC-16: Verbose handoff summaries generate output_lint events."""

    def test_verbose_summary_produces_lint_event(self, tmp_path):
        from mas.core.engine.handoff_engine import HandoffEngine

        sm = _make_sm(tmp_path)
        engine = HandoffEngine(audit_logger=MagicMock())
        lint_fired = []

        def capture(project_id, actor, action_type, intent, **kwargs):
            if action_type == "output_lint":
                lint_fired.append(True)
            return "id"

        verbose = " ".join(["word"] * 850)
        with patch("core.engine.event_recorder.EventRecorder.record_simple",
                   side_effect=capture):
            engine.create(
                sm,
                from_agent="master_orchestrator",
                to_agent="scribe_agent",
                phase="execution",
                task_description="task",
                payload={
                    "summary": verbose,
                    "artifacts_produced": [], "decisions_made": [],
                    "open_questions": [], "constraints_for_next": [],
                    "shared_state_fields_modified": [],
                },
            )

        assert lint_fired, "Expected output_lint event for verbose summary"


# ---------------------------------------------------------------------------
# SkillBridge render_skill_prompt integration
# ---------------------------------------------------------------------------

class TestSkillBridgeRenderIntegration:
    """AC-16: render_skill_prompt produces usable prompt blocks."""

    def _bridge(self, tmp_path: Path):
        from mas.core.engine.skill_bridge import SkillBridge, SkillMetadata
        b = SkillBridge(skills_dir=tmp_path)
        b._cache = {
            "mas-examine": SkillMetadata(
                name="mas-examine",
                description="Analyze without modifying state",
                path=tmp_path / "mas-examine" / "SKILL.md",
            )
        }
        return b

    def test_render_includes_skill_name_and_query(self, tmp_path):
        bridge = self._bridge(tmp_path)
        result = bridge.render_skill_prompt("master_orchestrator", "mas-examine", "check policies")
        assert "mas-examine" in result
        assert "check policies" in result

    def test_render_denied_for_unauthorized(self, tmp_path):
        bridge = self._bridge(tmp_path)
        result = bridge.render_skill_prompt("hr_agent", "mas-examine", "query")
        assert "denied" in result


# ---------------------------------------------------------------------------
# Registry skill count
# ---------------------------------------------------------------------------

class TestRegistrySkillCount:
    """AC-16: registry_index.yaml lists all 13 skills."""

    def test_all_skills_registered(self):
        registry_path = Path(__file__).parents[2] / "roster" / "registry_index.yaml"
        with open(registry_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        skills = data.get("skills", [])
        assert len(skills) >= 13, f"Expected >= 13 skills, got {len(skills)}"
        skill_ids = {s["skill_id"] for s in skills}
        for expected in ["mas-review", "mas-plan", "mas-clarify", "mas-examine",
                         "mas-document", "mas-handoff", "mas-logwork", "mas-postmortem",
                         "research-extract", "research-sync", "skill-builder",
                         "notebooklm", "frontend-design"]:
            assert expected in skill_ids, f"Missing skill: {expected}"

    def test_active_skills_count_matches(self):
        registry_path = Path(__file__).parents[2] / "roster" / "registry_index.yaml"
        with open(registry_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        active = [s for s in data.get("skills", []) if s.get("status") == "active"]
        assert data["counts"]["active_skills"] == len(active)
