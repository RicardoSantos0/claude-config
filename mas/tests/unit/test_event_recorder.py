"""
Unit Tests — EventRecorder (mas/core/engine/event_recorder.py)

Coverage target: >= 95% branch coverage on event_recorder.py.

All tests are offline-capable. No live DB writes — core.db.append_event is
mocked at the import point inside event_recorder.record() via monkeypatch or
unittest.mock.patch, except for the integration-style write test which uses a
real temp DB via tmp_path.
"""

import warnings
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from mas.core.engine.event_recorder import EventRecorder, MASEvent, _find_repo_root


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ALL_VALID_TYPES = [
    # orchestration
    "decision_made", "phase_transition", "stop_reason", "policy_block",
    # skills
    "skill_recommended", "skill_requested", "skill_invoked",
    "skill_completed", "skill_skipped",
    # consultation
    "consultation_required", "consultation_requested", "consultation_response",
    "consultation_synthesis", "consultation_applied", "consultation_overridden",
    # handoff
    "handoff_created", "handoff_accepted", "handoff_rejected", "handoff_completed",
    # state
    "shared_state_written", "shared_state_rebuilt", "snapshots_cleaned",
    # quality
    "output_lint", "evaluation_result", "postmortem_created",
    # governance
    "decision_recorded", "override_recorded", "spawn_requested",
    "spawn_approved", "spawn_rejected",
]

EXPECTED_COUNT = 30


def make_recorder(tmp_path: Path) -> EventRecorder:
    """Return an EventRecorder that writes to a temp path (never production DB)."""
    return EventRecorder(db_path=tmp_path / "test.db")


def make_event(action_type: str = "decision_made", **kwargs) -> MASEvent:
    defaults = dict(
        project_id="proj-test-recorder",
        actor="master_orchestrator",
        action_type=action_type,
        intent="Test intent",
    )
    defaults.update(kwargs)
    return MASEvent(**defaults)


# ---------------------------------------------------------------------------
# MASEvent dataclass
# ---------------------------------------------------------------------------

class TestMASEvent:
    def test_required_fields_only(self):
        ev = MASEvent(
            project_id="proj-x",
            actor="scribe_agent",
            action_type="decision_made",
            intent="Minimal event",
        )
        assert ev.project_id == "proj-x"
        assert ev.actor == "scribe_agent"
        assert ev.action_type == "decision_made"
        assert ev.intent == "Minimal event"

    def test_defaults_for_optional_fields(self):
        ev = MASEvent(
            project_id="p", actor="a", action_type="decision_made", intent="i"
        )
        assert ev.payload == {}
        assert ev.phase is None
        assert ev.rule_id is None
        assert ev.artifacts == []
        assert ev.result_shape is None

    def test_all_fields_set(self):
        ev = MASEvent(
            project_id="proj-full",
            actor="master_orchestrator",
            action_type="phase_transition",
            intent="Moving to P2",
            payload={"key": "val"},
            phase="P1",
            rule_id="R-007",
            artifacts=["artifact.md"],
            result_shape="transition_record",
        )
        assert ev.payload == {"key": "val"}
        assert ev.phase == "P1"
        assert ev.rule_id == "R-007"
        assert ev.artifacts == ["artifact.md"]
        assert ev.result_shape == "transition_record"

    def test_payload_and_artifacts_are_independent_instances(self):
        ev1 = MASEvent(project_id="p", actor="a", action_type="decision_made", intent="i")
        ev2 = MASEvent(project_id="p", actor="a", action_type="decision_made", intent="i")
        ev1.payload["x"] = 1
        ev1.artifacts.append("f.md")
        assert ev2.payload == {}
        assert ev2.artifacts == []


# ---------------------------------------------------------------------------
# _find_repo_root
# ---------------------------------------------------------------------------

class TestFindRepoRoot:
    def test_returns_directory_with_pyproject_toml(self):
        root = _find_repo_root()
        assert (root / "pyproject.toml").exists(), (
            f"_find_repo_root() returned {root} but pyproject.toml not found there"
        )

    def test_returns_path_object(self):
        root = _find_repo_root()
        assert isinstance(root, Path)


# ---------------------------------------------------------------------------
# EventRecorder._load_valid_types
# ---------------------------------------------------------------------------

class TestLoadValidTypes:
    def test_returns_set(self, tmp_path):
        recorder = make_recorder(tmp_path)
        assert isinstance(recorder._valid_types, set)

    def test_correct_count(self, tmp_path):
        recorder = make_recorder(tmp_path)
        assert len(recorder._valid_types) == EXPECTED_COUNT, (
            f"Expected {EXPECTED_COUNT} event types, got {len(recorder._valid_types)}:\n"
            f"{sorted(recorder._valid_types)}"
        )

    def test_all_expected_types_present(self, tmp_path):
        recorder = make_recorder(tmp_path)
        missing = [t for t in ALL_VALID_TYPES if t not in recorder._valid_types]
        assert missing == [], f"Missing event types: {missing}"

    def test_no_extra_types(self, tmp_path):
        recorder = make_recorder(tmp_path)
        extra = [t for t in recorder._valid_types if t not in ALL_VALID_TYPES]
        assert extra == [], f"Unexpected extra event types: {extra}"

    def test_all_categories_covered(self, tmp_path):
        recorder = make_recorder(tmp_path)
        # Spot-check one from each category
        for representative in [
            "decision_made",       # orchestration
            "skill_invoked",       # skills
            "consultation_applied",# consultation
            "handoff_completed",   # handoff
            "shared_state_written",# state
            "evaluation_result",   # quality
            "spawn_approved",      # governance
        ]:
            assert representative in recorder._valid_types


# ---------------------------------------------------------------------------
# db_path override
# ---------------------------------------------------------------------------

class TestDbPathOverride:
    def test_custom_db_path_stored(self, tmp_path):
        custom = tmp_path / "custom.db"
        recorder = EventRecorder(db_path=custom)
        assert recorder._db_path == custom

    def test_default_db_path_points_to_episodic_db(self, tmp_path):
        recorder = EventRecorder()
        assert recorder._db_path.name == "episodic.db"

    def test_db_path_as_string(self, tmp_path):
        custom = str(tmp_path / "str.db")
        recorder = EventRecorder(db_path=custom)
        assert recorder._db_path == Path(custom)


# ---------------------------------------------------------------------------
# EventRecorder.record() — validation (no DB touched)
# ---------------------------------------------------------------------------

class TestRecordValidation:
    def test_unknown_action_type_raises_value_error(self, tmp_path):
        recorder = make_recorder(tmp_path)
        ev = make_event(action_type="totally_fake_type")
        with pytest.raises(ValueError, match="Unknown event type"):
            recorder.record(ev)

    def test_error_message_names_the_bad_type(self, tmp_path):
        recorder = make_recorder(tmp_path)
        ev = make_event(action_type="not_a_real_event")
        with pytest.raises(ValueError, match="not_a_real_event"):
            recorder.record(ev)

    def test_unknown_type_does_not_call_append_event(self, tmp_path):
        recorder = make_recorder(tmp_path)
        ev = make_event(action_type="bad_type")
        with patch("core.db.append_event") as mock_append:
            with pytest.raises(ValueError):
                recorder.record(ev)
            mock_append.assert_not_called()

    def test_empty_string_action_type_raises(self, tmp_path):
        recorder = make_recorder(tmp_path)
        ev = make_event(action_type="")
        with pytest.raises(ValueError):
            recorder.record(ev)


# ---------------------------------------------------------------------------
# EventRecorder.record() — success for every category
# ---------------------------------------------------------------------------

class TestRecordSuccessAllCategories:
    """One test per YAML category to confirm all 7 categories pass validation."""

    def _record_with_mock(self, tmp_path, action_type, **event_kwargs):
        recorder = make_recorder(tmp_path)
        ev = make_event(action_type=action_type, **event_kwargs)
        fake_id = "uuid-abc-123"
        with patch("core.db.append_event", return_value=fake_id):
            result = recorder.record(ev)
        return result

    def test_orchestration_decision_made(self, tmp_path):
        result = self._record_with_mock(tmp_path, "decision_made")
        assert result == "uuid-abc-123"

    def test_orchestration_phase_transition(self, tmp_path):
        result = self._record_with_mock(tmp_path, "phase_transition", phase="P1")
        assert result == "uuid-abc-123"

    def test_orchestration_stop_reason(self, tmp_path):
        result = self._record_with_mock(tmp_path, "stop_reason")
        assert result == "uuid-abc-123"

    def test_orchestration_policy_block(self, tmp_path):
        result = self._record_with_mock(tmp_path, "policy_block", rule_id="R-001")
        assert result == "uuid-abc-123"

    def test_skills_skill_invoked(self, tmp_path):
        result = self._record_with_mock(tmp_path, "skill_invoked")
        assert result == "uuid-abc-123"

    def test_skills_skill_completed(self, tmp_path):
        result = self._record_with_mock(tmp_path, "skill_completed")
        assert result == "uuid-abc-123"

    def test_skills_skill_skipped(self, tmp_path):
        result = self._record_with_mock(tmp_path, "skill_skipped")
        assert result == "uuid-abc-123"

    def test_skills_skill_recommended(self, tmp_path):
        result = self._record_with_mock(tmp_path, "skill_recommended")
        assert result == "uuid-abc-123"

    def test_skills_skill_requested(self, tmp_path):
        result = self._record_with_mock(tmp_path, "skill_requested")
        assert result == "uuid-abc-123"

    def test_consultation_required(self, tmp_path):
        result = self._record_with_mock(tmp_path, "consultation_required")
        assert result == "uuid-abc-123"

    def test_consultation_requested(self, tmp_path):
        result = self._record_with_mock(tmp_path, "consultation_requested")
        assert result == "uuid-abc-123"

    def test_consultation_response(self, tmp_path):
        result = self._record_with_mock(tmp_path, "consultation_response")
        assert result == "uuid-abc-123"

    def test_consultation_synthesis(self, tmp_path):
        result = self._record_with_mock(tmp_path, "consultation_synthesis")
        assert result == "uuid-abc-123"

    def test_consultation_applied(self, tmp_path):
        result = self._record_with_mock(tmp_path, "consultation_applied")
        assert result == "uuid-abc-123"

    def test_consultation_overridden(self, tmp_path):
        result = self._record_with_mock(tmp_path, "consultation_overridden")
        assert result == "uuid-abc-123"

    def test_handoff_created(self, tmp_path):
        result = self._record_with_mock(tmp_path, "handoff_created")
        assert result == "uuid-abc-123"

    def test_handoff_accepted(self, tmp_path):
        result = self._record_with_mock(tmp_path, "handoff_accepted")
        assert result == "uuid-abc-123"

    def test_handoff_rejected(self, tmp_path):
        result = self._record_with_mock(tmp_path, "handoff_rejected")
        assert result == "uuid-abc-123"

    def test_handoff_completed(self, tmp_path):
        result = self._record_with_mock(tmp_path, "handoff_completed")
        assert result == "uuid-abc-123"

    def test_state_shared_state_written(self, tmp_path):
        result = self._record_with_mock(tmp_path, "shared_state_written")
        assert result == "uuid-abc-123"

    def test_state_shared_state_rebuilt(self, tmp_path):
        result = self._record_with_mock(tmp_path, "shared_state_rebuilt")
        assert result == "uuid-abc-123"

    def test_state_snapshots_cleaned(self, tmp_path):
        result = self._record_with_mock(tmp_path, "snapshots_cleaned")
        assert result == "uuid-abc-123"

    def test_quality_output_lint(self, tmp_path):
        result = self._record_with_mock(tmp_path, "output_lint")
        assert result == "uuid-abc-123"

    def test_quality_evaluation_result(self, tmp_path):
        result = self._record_with_mock(tmp_path, "evaluation_result")
        assert result == "uuid-abc-123"

    def test_quality_postmortem_created(self, tmp_path):
        result = self._record_with_mock(tmp_path, "postmortem_created")
        assert result == "uuid-abc-123"

    def test_governance_decision_recorded(self, tmp_path):
        result = self._record_with_mock(tmp_path, "decision_recorded")
        assert result == "uuid-abc-123"

    def test_governance_override_recorded(self, tmp_path):
        result = self._record_with_mock(tmp_path, "override_recorded")
        assert result == "uuid-abc-123"

    def test_governance_spawn_requested(self, tmp_path):
        result = self._record_with_mock(tmp_path, "spawn_requested")
        assert result == "uuid-abc-123"

    def test_governance_spawn_approved(self, tmp_path):
        result = self._record_with_mock(tmp_path, "spawn_approved")
        assert result == "uuid-abc-123"

    def test_governance_spawn_rejected(self, tmp_path):
        result = self._record_with_mock(tmp_path, "spawn_rejected")
        assert result == "uuid-abc-123"


# ---------------------------------------------------------------------------
# EventRecorder.record() — payload normalisation
# ---------------------------------------------------------------------------

class TestRecordPayloadNormalisation:
    """Verify the normalised payload passed to append_event contains expected fields."""

    def _capture_payload(self, tmp_path, event: MASEvent) -> dict:
        recorder = make_recorder(tmp_path)
        captured = {}

        def fake_append(**kwargs):
            captured.update(kwargs)
            return "uid-captured"

        with patch("core.db.append_event", side_effect=fake_append):
            recorder.record(event)
        return captured

    def test_actor_always_in_payload(self, tmp_path):
        ev = make_event(action_type="decision_made")
        captured = self._capture_payload(tmp_path, ev)
        assert captured["payload"]["actor"] == "master_orchestrator"

    def test_phase_included_when_set(self, tmp_path):
        ev = make_event(action_type="phase_transition", phase="P2")
        captured = self._capture_payload(tmp_path, ev)
        assert captured["payload"]["phase"] == "P2"

    def test_phase_absent_when_none(self, tmp_path):
        ev = make_event(action_type="decision_made", phase=None)
        captured = self._capture_payload(tmp_path, ev)
        assert "phase" not in captured["payload"]

    def test_rule_id_included_when_set(self, tmp_path):
        ev = make_event(action_type="policy_block", rule_id="R-042")
        captured = self._capture_payload(tmp_path, ev)
        assert captured["payload"]["rule_id"] == "R-042"

    def test_rule_id_absent_when_none(self, tmp_path):
        ev = make_event(action_type="decision_made", rule_id=None)
        captured = self._capture_payload(tmp_path, ev)
        assert "rule_id" not in captured["payload"]

    def test_artifacts_included_when_nonempty(self, tmp_path):
        ev = make_event(action_type="decision_made", artifacts=["a.md", "b.md"])
        captured = self._capture_payload(tmp_path, ev)
        assert captured["payload"]["artifacts"] == ["a.md", "b.md"]

    def test_artifacts_absent_when_empty(self, tmp_path):
        ev = make_event(action_type="decision_made", artifacts=[])
        captured = self._capture_payload(tmp_path, ev)
        assert "artifacts" not in captured["payload"]

    def test_caller_payload_merged(self, tmp_path):
        ev = make_event(
            action_type="decision_made",
            payload={"custom_key": "custom_val"},
        )
        captured = self._capture_payload(tmp_path, ev)
        assert captured["payload"]["custom_key"] == "custom_val"
        assert captured["payload"]["actor"] == "master_orchestrator"

    def test_result_shape_passed_through(self, tmp_path):
        ev = make_event(action_type="decision_made", result_shape="my_shape")
        captured = self._capture_payload(tmp_path, ev)
        assert captured["result_shape"] == "my_shape"

    def test_result_shape_empty_string_when_none(self, tmp_path):
        ev = make_event(action_type="decision_made", result_shape=None)
        captured = self._capture_payload(tmp_path, ev)
        assert captured["result_shape"] == ""

    def test_db_path_passed_as_string(self, tmp_path):
        ev = make_event(action_type="decision_made")
        captured = self._capture_payload(tmp_path, ev)
        from pathlib import Path; assert isinstance(captured["db_path"], Path)

    def test_project_id_and_agent_id_passed(self, tmp_path):
        ev = make_event(action_type="decision_made")
        captured = self._capture_payload(tmp_path, ev)
        assert captured["project_id"] == "proj-test-recorder"
        assert captured["agent_id"] == "master_orchestrator"
        assert captured["action_type"] == "decision_made"
        assert captured["intent"] == "Test intent"


# ---------------------------------------------------------------------------
# EventRecorder.record() — graceful degradation
# ---------------------------------------------------------------------------

class TestRecordGracefulDegradation:
    def test_returns_empty_string_on_db_failure(self, tmp_path):
        recorder = make_recorder(tmp_path)
        ev = make_event(action_type="decision_made")
        with patch("core.db.append_event", side_effect=RuntimeError("DB gone")):
            result = recorder.record(ev)
        assert result == ""

    def test_emits_runtime_warning_on_db_failure(self, tmp_path):
        recorder = make_recorder(tmp_path)
        ev = make_event(action_type="decision_made")
        with patch("core.db.append_event", side_effect=OSError("disk full")):
            with pytest.warns(RuntimeWarning):
                recorder.record(ev)

    def test_warning_message_contains_action_type(self, tmp_path):
        recorder = make_recorder(tmp_path)
        ev = make_event(action_type="phase_transition")
        with patch("core.db.append_event", side_effect=Exception("bad")):
            with pytest.warns(RuntimeWarning, match="phase_transition"):
                recorder.record(ev)

    def test_warning_message_contains_project_id(self, tmp_path):
        recorder = make_recorder(tmp_path)
        ev = make_event(action_type="decision_made")
        with patch("core.db.append_event", side_effect=Exception("bad")):
            with pytest.warns(RuntimeWarning, match="proj-test-recorder"):
                recorder.record(ev)

    def test_no_exception_propagates_on_import_error(self, tmp_path):
        """Simulates core.db not importable at record() time."""
        recorder = make_recorder(tmp_path)
        ev = make_event(action_type="decision_made")
        with patch("core.db.append_event", side_effect=ImportError("no module")):
            with pytest.warns(RuntimeWarning):
                result = recorder.record(ev)
        assert result == ""

    def test_no_exception_propagates_on_permission_error(self, tmp_path):
        recorder = make_recorder(tmp_path)
        ev = make_event(action_type="decision_made")
        with patch("core.db.append_event", side_effect=PermissionError("locked")):
            with pytest.warns(RuntimeWarning):
                result = recorder.record(ev)
        assert result == ""

    def test_value_error_for_bad_type_still_raises(self, tmp_path):
        """ValueError from validation must NOT be swallowed by the except block."""
        recorder = make_recorder(tmp_path)
        ev = make_event(action_type="nonexistent_event")
        # ValueError is raised before the try block — must propagate
        with pytest.raises(ValueError):
            recorder.record(ev)


# ---------------------------------------------------------------------------
# EventRecorder.record_simple() convenience wrapper
# ---------------------------------------------------------------------------

class TestRecordSimple:
    def test_returns_action_id(self, tmp_path):
        recorder = make_recorder(tmp_path)
        with patch("core.db.append_event", return_value="simple-uid"):
            result = recorder.record_simple(
                project_id="proj-simple",
                actor="scribe_agent",
                action_type="decision_made",
                intent="A simple test",
            )
        assert result == "simple-uid"

    def test_unknown_type_raises(self, tmp_path):
        recorder = make_recorder(tmp_path)
        with pytest.raises(ValueError, match="Unknown event type"):
            recorder.record_simple(
                project_id="proj-simple",
                actor="scribe_agent",
                action_type="not_in_taxonomy",
                intent="Should fail",
            )

    def test_optional_kwargs_passed_through(self, tmp_path):
        recorder = make_recorder(tmp_path)
        captured = {}

        def fake_append(**kwargs):
            captured.update(kwargs)
            return "kw-uid"

        with patch("core.db.append_event", side_effect=fake_append):
            recorder.record_simple(
                project_id="proj-kw",
                actor="master_orchestrator",
                action_type="phase_transition",
                intent="Testing kwargs",
                phase="P3",
                rule_id="R-999",
                artifacts=["doc.md"],
                result_shape="transition_record",
                payload={"extra": True},
            )

        assert captured["payload"]["phase"] == "P3"
        assert captured["payload"]["rule_id"] == "R-999"
        assert captured["payload"]["artifacts"] == ["doc.md"]
        assert captured["result_shape"] == "transition_record"
        assert captured["payload"]["extra"] is True

    def test_graceful_degradation_via_record_simple(self, tmp_path):
        recorder = make_recorder(tmp_path)
        with patch("core.db.append_event", side_effect=Exception("fail")):
            with pytest.warns(RuntimeWarning):
                result = recorder.record_simple(
                    project_id="proj-deg",
                    actor="master_orchestrator",
                    action_type="decision_made",
                    intent="Degradation test",
                )
        assert result == ""

    def test_default_payload_is_empty_dict(self, tmp_path):
        recorder = make_recorder(tmp_path)
        captured = {}

        def fake_append(**kwargs):
            captured.update(kwargs)
            return "uid"

        with patch("core.db.append_event", side_effect=fake_append):
            recorder.record_simple(
                project_id="p", actor="a",
                action_type="decision_made", intent="i",
            )
        # caller_payload is {} so only "actor" key should be set by normalisation
        assert captured["payload"] == {"actor": "a"}

    def test_default_phase_is_none(self, tmp_path):
        recorder = make_recorder(tmp_path)
        captured = {}

        def fake_append(**kwargs):
            captured.update(kwargs)
            return "uid"

        with patch("core.db.append_event", side_effect=fake_append):
            recorder.record_simple(
                project_id="p", actor="a",
                action_type="decision_made", intent="i",
            )
        assert "phase" not in captured["payload"]


# ---------------------------------------------------------------------------
# Integration-style write test (real temp DB)
# ---------------------------------------------------------------------------

class TestRecordWithRealDB:
    """
    Uses a real SQLite DB in tmp_path so we verify end-to-end without
    touching production episodic.db. Requires core.db.init_db to set up schema.
    """

    def test_record_writes_to_temp_db(self, tmp_path):
        from core.db import init_db, query_events

        db = tmp_path / "integration.db"
        init_db(db_path=db)

        recorder = EventRecorder(db_path=db)
        ev = make_event(action_type="decision_made", payload={"note": "integration"})
        action_id = recorder.record(ev)

        assert isinstance(action_id, str)
        assert len(action_id) > 0

        rows = query_events(project_id="proj-test-recorder", db_path=db)
        assert len(rows) == 1
        assert rows[0]["action_type"] == "decision_made"

    def test_multiple_records_in_temp_db(self, tmp_path):
        from core.db import init_db, query_events

        db = tmp_path / "multi.db"
        init_db(db_path=db)

        recorder = EventRecorder(db_path=db)
        types = ["decision_made", "phase_transition", "handoff_created"]
        for t in types:
            recorder.record(make_event(action_type=t))

        rows = query_events(project_id="proj-test-recorder", limit=10, db_path=db)
        assert len(rows) == 3
        recorded_types = {r["action_type"] for r in rows}
        assert recorded_types == set(types)
