"""
Governance tests for wire protocol compliance tracking.

Key governance rule:
  Non-compliant wire payload → metric warning logged, project CONTINUES.
  Non-compliance is NEVER a governance violation.
  Compliant payload → compliance counter incremented.

Tests verify:
- Non-compliant handoff succeeds (not blocked)
- Compliance counters updated on each handoff
- wire_compliance_rate computed correctly
- Governance violation count unchanged after non-compliant handoff
- Compliant handoff increments wire_compliant_count
- wire_validator.validate() returns False for legacy format without raising
"""

import pytest
from core.engine.shared_state_manager import SharedStateManager
from core.engine.handoff_engine import HandoffEngine
from core.utils.wire_protocol import validate, is_wire_format, encode


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def patch_roots(tmp_path, monkeypatch):
    import core.engine.shared_state_manager as ssm_mod
    import core.engine.checkpoint_writer as cw_mod
    monkeypatch.setattr(ssm_mod, "ROOT", tmp_path)
    monkeypatch.setattr(cw_mod, "ROOT", tmp_path)
    return tmp_path


def _make_project(tmp_path, project_id="proj-wire-gov-001"):
    sm = SharedStateManager(project_id)
    sm.initialize(request_id="req-wire-001")
    return sm


# ---------------------------------------------------------------------------
# Non-compliance is not a governance violation
# ---------------------------------------------------------------------------

class TestNonComplianceNotViolation:
    def test_legacy_payload_handoff_succeeds(self, tmp_path):
        """Handoff with legacy (non-wire) payload must not be blocked."""
        sm = _make_project(tmp_path)
        engine = HandoffEngine()

        # Legacy format: no _v field, prose summary
        handoff = engine.create(
            sm, "master_orchestrator", "scribe_agent",
            "intake", "Initialize folder",
            payload={"summary": "Starting the project now with full prose description."},
        )
        assert handoff["handoff_id"] is not None

        # No governance violation recorded
        state = sm.load()
        violations = state.get("_meta", {}).get("governance_violations", [])
        assert len(violations) == 0

    def test_noncompliant_payload_does_not_increment_violation_count(self, tmp_path):
        """Wire non-compliance must not add to governance_violations."""
        sm = _make_project(tmp_path)
        engine = HandoffEngine()

        # 3 non-compliant handoffs
        for i in range(3):
            engine.create(
                sm, "master_orchestrator", "scribe_agent",
                "intake", f"Task {i}",
                payload={"summary": f"Prose summary number {i}"},
            )

        state = sm.load()
        violations = state.get("_meta", {}).get("governance_violations", [])
        assert len(violations) == 0

    def test_governance_violations_only_for_access_control(self, tmp_path):
        """Only access control breaches create governance violations."""
        sm = _make_project(tmp_path)

        # Attempt unauthorized write → violation
        result = sm.write("scribe_agent", "core_identity", "current_phase", "specification")
        assert not result.success

        state = sm.load()
        violations = state.get("_meta", {}).get("governance_violations", [])
        assert len(violations) >= 1
        assert violations[0]["reason"] == "unauthorized_write"


# ---------------------------------------------------------------------------
# Compliance counters updated correctly
# ---------------------------------------------------------------------------

class TestComplianceCounters:
    def test_wire_compliant_handoff_increments_counter(self, tmp_path):
        """A wire-format payload increments wire_compliant_count."""
        sm = _make_project(tmp_path)
        engine = HandoffEngine()

        wire_payload = encode({"summary": "task:complete", "artifacts_produced": ["plan.yaml"]})
        engine.create(
            sm, "master_orchestrator", "project_manager_agent",
            "planning", "Compile plan",
            payload=wire_payload,
        )

        state = sm.load()
        comm = state.get("communication", {})
        assert comm.get("wire_compliant_count", 0) >= 1
        assert comm.get("wire_total_count", 0) >= 1

    def test_legacy_handoff_increments_total_not_compliant(self, tmp_path):
        """A legacy payload increments wire_total_count but not wire_compliant_count."""
        sm = _make_project(tmp_path)
        engine = HandoffEngine()

        engine.create(
            sm, "master_orchestrator", "scribe_agent",
            "intake", "Init",
            payload={"summary": "legacy prose payload"},
        )

        state = sm.load()
        comm = state.get("communication", {})
        assert comm.get("wire_total_count", 0) >= 1
        assert comm.get("wire_compliant_count", 0) == 0

    def test_compliance_rate_computed(self, tmp_path):
        """wire_compliance_rate is computed as compliant/total."""
        sm = _make_project(tmp_path)
        engine = HandoffEngine()

        # 1 compliant
        wire_payload = encode({"summary": "ok"})
        engine.create(sm, "master_orchestrator", "scribe_agent", "intake", "T1", payload=wire_payload)
        # 1 non-compliant
        engine.create(sm, "master_orchestrator", "scribe_agent", "intake", "T2",
                      payload={"summary": "legacy"})

        state = sm.load()
        rate = state.get("communication", {}).get("wire_compliance_rate")
        assert rate is not None
        assert 0.0 <= rate <= 1.0
        assert abs(rate - 0.5) < 0.01  # 1/2 = 0.5

    def test_all_compliant_rate_is_1(self, tmp_path):
        """100% compliant → rate = 1.0."""
        sm = _make_project(tmp_path)
        engine = HandoffEngine()

        for i in range(5):
            wire_payload = encode({"summary": "task:complete"})
            engine.create(sm, "master_orchestrator", "scribe_agent", "intake",
                          f"T{i}", payload=wire_payload)

        state = sm.load()
        rate = state.get("communication", {}).get("wire_compliance_rate")
        assert rate == 1.0

    def test_all_noncompliant_rate_is_0(self, tmp_path):
        """0% compliant → rate = 0.0."""
        sm = _make_project(tmp_path)
        engine = HandoffEngine()

        for i in range(3):
            engine.create(sm, "master_orchestrator", "scribe_agent", "intake",
                          f"T{i}", payload={"summary": f"prose {i}"})

        state = sm.load()
        rate = state.get("communication", {}).get("wire_compliance_rate")
        assert rate == 0.0


# ---------------------------------------------------------------------------
# Validator behavior
# ---------------------------------------------------------------------------

class TestValidatorBehavior:
    def test_legacy_format_returns_false_not_raises(self):
        """validate() must return (False, warnings) for legacy — never raise."""
        ok, warnings = validate({"summary": "prose"})
        assert ok is False
        assert isinstance(warnings, list)
        assert len(warnings) > 0

    def test_wire_format_returns_true(self):
        wire = encode({"summary": "ok"})
        ok, warnings = validate(wire)
        assert ok is True
        assert warnings == []

    def test_is_wire_format_detection(self):
        assert is_wire_format(encode({"summary": "ok"})) is True
        assert is_wire_format({"summary": "prose"}) is False
        assert is_wire_format({}) is False


# ---------------------------------------------------------------------------
# Compliance tracking survives checkpoint failure
# ---------------------------------------------------------------------------

class TestComplianceNonFatal:
    def test_compliance_tracking_survives_checkpoint_error(self, tmp_path, monkeypatch):
        """Even if checkpoint writer raises, handoff and compliance tracking succeed."""
        import core.engine.checkpoint_writer as cw_mod

        def bad_write(self):
            raise OSError("disk full")

        monkeypatch.setattr(cw_mod.CheckpointWriter, "write", bad_write)

        sm = _make_project(tmp_path, "proj-wire-nonfatal-001")
        engine = HandoffEngine()

        wire_payload = encode({"summary": "task:complete"})
        handoff = engine.create(
            sm, "master_orchestrator", "scribe_agent",
            "intake", "Init",
            payload=wire_payload,
        )
        assert handoff["handoff_id"] is not None

        state = sm.load()
        assert state.get("communication", {}).get("wire_total_count", 0) >= 1
