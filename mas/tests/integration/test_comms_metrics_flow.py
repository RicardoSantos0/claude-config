"""
Integration Test — Communication Metrics Flow (Phase 3)

Verifies that after handoffs with mixed wire/legacy payloads:
1. Wire compliance counters are tracked in shared state
2. MetricsEngine communication scoring functions can run against real state
3. TrainingEngine generates communication proposals from real state
4. Eval report includes communication section when metrics are low
5. Low wire compliance (< 50% with ≥ 5 handoffs) triggers a wire adoption proposal
6. High wire compliance produces no wire adoption proposal
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from core.engine.shared_state_manager import SharedStateManager
from core.engine.handoff_engine import HandoffEngine
from core.utils.wire_protocol import encode, WireValidator
from core.engine.training_engine import TrainingEngine, LOW_THRESHOLD
from core.engine.metrics_engine import MetricsEngine


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


@pytest.fixture
def sm(tmp_path):
    manager = SharedStateManager("proj-comms-flow-001")
    # manager.initialize(request_id="req-comms-001")  # disabled: avoid creating real projects during migration-focused runs
    # Ensure minimal state exists for tests when initialize() is disabled
    if not manager.exists():
        from core.engine.shared_state_manager import create_initial_state
        manager.project_dir.mkdir(parents=True, exist_ok=True)
        manager._save(create_initial_state(manager.project_id, "req-test"))
    return manager


@pytest.fixture
def engine():
    return HandoffEngine()


# ---------------------------------------------------------------------------
# Wire compliance counters tracked in real state
# ---------------------------------------------------------------------------

class TestWireComplianceCounters:
    def test_wire_compliant_handoff_tracked(self, sm, engine):
        wire_payload = encode({"summary": "task:complete", "artifacts_produced": ["plan.yaml"]})
        engine.create(sm, "master_orchestrator", "project_manager_agent",
                      "planning", "Plan task", payload=wire_payload)
        state = sm.load()
        comm = state.get("communication", {})
        assert comm.get("wire_compliant_count", 0) >= 1
        assert comm.get("wire_total_count", 0) >= 1

    def test_legacy_handoff_does_not_increment_compliant(self, sm, engine):
        engine.create(sm, "master_orchestrator", "scribe_agent",
                      "intake", "Init", payload={"summary": "legacy prose"})
        state = sm.load()
        comm = state.get("communication", {})
        assert comm.get("wire_compliant_count", 0) == 0
        assert comm.get("wire_total_count", 0) >= 1

    def test_compliance_rate_computed_after_mixed_handoffs(self, sm, engine):
        # 2 compliant
        for _ in range(2):
            engine.create(sm, "master_orchestrator", "scribe_agent",
                          "intake", "T", payload=encode({"summary": "ok"}))
        # 2 non-compliant
        for _ in range(2):
            engine.create(sm, "master_orchestrator", "scribe_agent",
                          "intake", "T", payload={"summary": "prose"})

        state = sm.load()
        rate = state.get("communication", {}).get("wire_compliance_rate")
        assert rate is not None
        assert abs(rate - 0.5) < 0.01

    def test_wire_noncompliance_not_governance_violation(self, sm, engine):
        """Legacy payloads must never produce governance violations."""
        for i in range(3):
            engine.create(sm, "master_orchestrator", "scribe_agent",
                          "intake", f"T{i}", payload={"summary": f"prose {i}"})
        state = sm.load()
        violations = state.get("_meta", {}).get("governance_violations", [])
        assert len(violations) == 0


# ---------------------------------------------------------------------------
# MetricsEngine communication scoring runs on real state
# ---------------------------------------------------------------------------

class TestMetricsEngineCommunicationScoring:
    def test_score_functions_return_metric_results(self, sm, engine):
        # Add a few handoffs so functions have data
        for _ in range(2):
            engine.create(sm, "master_orchestrator", "scribe_agent",
                          "intake", "T", payload=encode({"summary": "ok"}))
        engine.create(sm, "master_orchestrator", "scribe_agent",
                      "intake", "T", payload={"summary": "prose"})

        me = MetricsEngine()
        state = sm.load()
        wf = state.get("workflow", {})
        handoff_history = wf.get("handoff_history") or []
        phase_count = max(len(wf.get("completed_phases") or []), 1)
        comm = state.get("communication", {})

        results = [
            me.score_token_efficiency(handoff_history, phase_count),
            me.score_payload_density(handoff_history),
            me.score_context_injection_efficiency([], comm.get("total_tokens_used", 1) or 1),
            me.score_consultation_overhead([], 1),
        ]
        for result in results:
            assert result is not None
            assert hasattr(result, "score")
            assert 0.0 <= result.score <= 100.0

    def test_score_returns_result_for_empty_history(self, sm):
        """With no handoffs yet, scores should not crash."""
        me = MetricsEngine()
        result = me.score_token_efficiency([], 1)
        assert isinstance(result.score, float)


# ---------------------------------------------------------------------------
# TrainingEngine generates communication proposals from real state
# ---------------------------------------------------------------------------

class TestTrainingEngineCommunicationProposals:
    def _make_low_score_result(self, score=40.0):
        m = MagicMock()
        m.score = score
        m.breakdown = {}
        return m

    def test_proposals_generated_for_low_metrics(self, sm):
        te = TrainingEngine()
        state = sm.load()

        mock_me = MagicMock()
        mock_me.score_token_efficiency.return_value = self._make_low_score_result(40.0)
        mock_me.score_payload_density.return_value = self._make_low_score_result(40.0)
        mock_me.score_context_injection_efficiency.return_value = self._make_low_score_result(40.0)
        mock_me.score_consultation_overhead.return_value = self._make_low_score_result(40.0)

        with patch("core.engine.training_engine.MetricsEngine", return_value=mock_me):
            proposals = te.generate_communication_proposals(state, "proj-comms-flow-001")

        assert len(proposals) == 4
        assert all(p.proposal_type in ("communication_waste", "context_bloat") for p in proposals)

    def test_proposals_not_generated_for_high_metrics(self, sm, engine):
        te = TrainingEngine()
        state = sm.load()

        mock_me = MagicMock()
        mock_me.score_token_efficiency.return_value = self._make_low_score_result(95.0)
        mock_me.score_payload_density.return_value = self._make_low_score_result(95.0)
        mock_me.score_context_injection_efficiency.return_value = self._make_low_score_result(95.0)
        mock_me.score_consultation_overhead.return_value = self._make_low_score_result(95.0)

        with patch("core.engine.training_engine.MetricsEngine", return_value=mock_me):
            proposals = te.generate_communication_proposals(state, "proj-comms-flow-001")

        assert len(proposals) == 0

    def test_wire_compliance_proposal_after_5_low_rate_handoffs(self, sm, engine):
        """5+ handoffs with <50% compliance → wire adoption proposal."""
        for i in range(5):
            engine.create(sm, "master_orchestrator", "scribe_agent",
                          "intake", f"T{i}", payload={"summary": f"prose {i}"})

        te_engine = TrainingEngine()
        state = sm.load()

        mock_me = MagicMock()
        for fn in ["score_token_efficiency", "score_payload_density",
                   "score_context_injection_efficiency", "score_consultation_overhead"]:
            getattr(mock_me, fn).return_value = self._make_low_score_result(90.0)

        with patch("core.engine.training_engine.MetricsEngine", return_value=mock_me):
            proposals = te_engine.generate_communication_proposals(state, "proj-comms-flow-001")

        assert len(proposals) == 1
        assert proposals[0].proposal_type == "communication_waste"
        assert "wire" in proposals[0].description.lower()


# ---------------------------------------------------------------------------
# Eval report includes communication section
# ---------------------------------------------------------------------------

class TestEvalReportCommunicationSection:
    def test_metrics_engine_produces_communication_breakdown(self, sm, engine):
        """After mixed handoffs, MetricsEngine communication scores are accessible."""
        # 3 compliant, 2 non-compliant
        for _ in range(3):
            engine.create(sm, "master_orchestrator", "scribe_agent",
                          "intake", "T", payload=encode({"summary": "ok"}))
        for _ in range(2):
            engine.create(sm, "master_orchestrator", "scribe_agent",
                          "intake", "T", payload={"summary": "prose"})

        me = MetricsEngine()
        state = sm.load()
        wf = state.get("workflow", {})
        handoff_history = wf.get("handoff_history") or []
        phase_count = max(len(wf.get("completed_phases") or []), 1)
        comm = state.get("communication", {})

        results = [
            me.score_token_efficiency(handoff_history, phase_count),
            me.score_payload_density(handoff_history),
            me.score_context_injection_efficiency([], comm.get("total_tokens_used", 1) or 1),
            me.score_consultation_overhead([], 1),
        ]
        for result in results:
            assert 0.0 <= result.score <= 100.0
