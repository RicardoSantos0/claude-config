"""
Unit tests for TrainingEngine communication proposal generation (Phase 3).

Tests cover:
- generate_communication_proposals() returns proposals for low-scoring metrics
- Proposal types map correctly (communication_waste / context_bloat)
- Wire compliance proposal triggered at low rate with sufficient handoffs
- Wire compliance proposal NOT triggered with too few handoffs
- No proposals when all metrics score above threshold
- PRIORITY_SCORES includes communication_waste and context_bloat
- _metric_to_proposal_type routes communication metrics correctly
- _metric_to_artifact returns correct files for communication metrics
- _recommend_for_metric returns non-empty strings for communication metrics
- _tradeoffs_for_metric returns non-empty strings for communication metrics
"""

import pytest
from unittest.mock import MagicMock, patch
from dataclasses import dataclass

from core.training_engine import (
    TrainingEngine,
    PRIORITY_SCORES,
    LOW_THRESHOLD,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def engine():
    return TrainingEngine()


def _make_state(
    wire_compliant: int = 0,
    wire_total: int = 0,
    compliance_rate: float | None = None,
    total_tokens: int = 0,
    handoff_history: list | None = None,
) -> dict:
    """Build a minimal shared state dict for communication proposals."""
    return {
        "core_identity": {"project_id": "proj-test-comms-001", "current_phase": "evaluation"},
        "communication": {
            "wire_compliant_count": wire_compliant,
            "wire_total_count": wire_total,
            "wire_compliance_rate": compliance_rate,
            "total_tokens_used": total_tokens,
            "tokens_by_agent": {},
            "tokens_by_phase": {},
        },
        "workflow": {
            "handoff_history": handoff_history or [],
            "completed_phases": [],
        },
        "consultation": {"consultation_requests": [], "consultation_responses": []},
    }


def _mock_metric_result(score: float) -> MagicMock:
    m = MagicMock()
    m.score = score
    m.breakdown = {}
    return m


# ---------------------------------------------------------------------------
# PRIORITY_SCORES includes new types
# ---------------------------------------------------------------------------

class TestPriorityScores:
    def test_communication_waste_in_priority_scores(self):
        assert "communication_waste" in PRIORITY_SCORES
        assert PRIORITY_SCORES["communication_waste"] == 2

    def test_context_bloat_in_priority_scores(self):
        assert "context_bloat" in PRIORITY_SCORES
        assert PRIORITY_SCORES["context_bloat"] == 2


# ---------------------------------------------------------------------------
# _metric_to_proposal_type routing
# ---------------------------------------------------------------------------

class TestMetricToProposalType:
    def test_token_efficiency_maps_to_communication_waste(self, engine):
        ptype = engine._metric_to_proposal_type("token_efficiency", 40.0)
        assert ptype == "communication_waste"

    def test_payload_density_maps_to_communication_waste(self, engine):
        ptype = engine._metric_to_proposal_type("payload_density", 40.0)
        assert ptype == "communication_waste"

    def test_context_injection_efficiency_maps_to_context_bloat(self, engine):
        ptype = engine._metric_to_proposal_type("context_injection_efficiency", 40.0)
        assert ptype == "context_bloat"

    def test_consultation_overhead_maps_to_context_bloat(self, engine):
        ptype = engine._metric_to_proposal_type("consultation_overhead", 40.0)
        assert ptype == "context_bloat"

    def test_existing_boundary_adherence_unchanged(self, engine):
        ptype = engine._metric_to_proposal_type("boundary_adherence", 40.0)
        assert ptype == "boundary_violation"


# ---------------------------------------------------------------------------
# _metric_to_artifact routing
# ---------------------------------------------------------------------------

class TestMetricToArtifact:
    def test_token_efficiency_artifact(self, engine):
        assert engine._metric_to_artifact("token_efficiency") == "core/wire_protocol.py"

    def test_payload_density_artifact(self, engine):
        assert engine._metric_to_artifact("payload_density") == "core/wire_protocol.py"

    def test_context_injection_artifact(self, engine):
        assert engine._metric_to_artifact("context_injection_efficiency") == "core/prompt_assembler.py"

    def test_consultation_overhead_artifact(self, engine):
        assert engine._metric_to_artifact("consultation_overhead") == "core/consultation_engine.py"


# ---------------------------------------------------------------------------
# _recommend_for_metric
# ---------------------------------------------------------------------------

class TestRecommendForMetric:
    @pytest.mark.parametrize("metric", [
        "token_efficiency",
        "payload_density",
        "context_injection_efficiency",
        "consultation_overhead",
    ])
    def test_recommendation_non_empty(self, engine, metric):
        rec = engine._recommend_for_metric(metric, 40.0, {})
        assert isinstance(rec, str)
        assert len(rec) > 20

    def test_token_efficiency_mentions_wire(self, engine):
        rec = engine._recommend_for_metric("token_efficiency", 40.0, {})
        assert "wire" in rec.lower()

    def test_context_injection_mentions_projections(self, engine):
        rec = engine._recommend_for_metric("context_injection_efficiency", 40.0, {})
        assert "projection" in rec.lower() or "STATE_PROJECTIONS" in rec


# ---------------------------------------------------------------------------
# _tradeoffs_for_metric
# ---------------------------------------------------------------------------

class TestTradeoffsForMetric:
    @pytest.mark.parametrize("metric", [
        "token_efficiency",
        "payload_density",
        "context_injection_efficiency",
        "consultation_overhead",
    ])
    def test_tradeoff_non_empty(self, engine, metric):
        tradeoff = engine._tradeoffs_for_metric(metric)
        assert isinstance(tradeoff, str)
        assert len(tradeoff) > 10


# ---------------------------------------------------------------------------
# generate_communication_proposals — metric scoring
# ---------------------------------------------------------------------------

class TestGenerateCommunicationProposals:
    def _mock_me_all_low(self):
        """MetricsEngine where all 4 comms scores return low (below threshold)."""
        me = MagicMock()
        me.score_token_efficiency.return_value = _mock_metric_result(40.0)
        me.score_payload_density.return_value = _mock_metric_result(40.0)
        me.score_context_injection_efficiency.return_value = _mock_metric_result(40.0)
        me.score_consultation_overhead.return_value = _mock_metric_result(40.0)
        return me

    def _mock_me_all_high(self):
        """MetricsEngine where all 4 comms scores return above threshold."""
        me = MagicMock()
        me.score_token_efficiency.return_value = _mock_metric_result(90.0)
        me.score_payload_density.return_value = _mock_metric_result(90.0)
        me.score_context_injection_efficiency.return_value = _mock_metric_result(90.0)
        me.score_consultation_overhead.return_value = _mock_metric_result(90.0)
        return me

    def test_low_scores_produce_proposals(self, engine):
        state = _make_state()
        mock_me = self._mock_me_all_low()
        with patch("core.training_engine.MetricsEngine", return_value=mock_me):
            proposals = engine.generate_communication_proposals(state, "proj-test-001")
        assert len(proposals) == 4  # one per metric

    def test_high_scores_produce_no_metric_proposals(self, engine):
        state = _make_state()
        mock_me = self._mock_me_all_high()
        with patch("core.training_engine.MetricsEngine", return_value=mock_me):
            proposals = engine.generate_communication_proposals(state, "proj-test-001")
        # No metric proposals; wire compliance proposal depends on counts
        assert all(p.proposal_type in ("communication_waste", "context_bloat") for p in proposals)
        assert len(proposals) == 0

    def test_proposal_ids_are_unique(self, engine):
        state = _make_state()
        mock_me = self._mock_me_all_low()
        with patch("core.training_engine.MetricsEngine", return_value=mock_me):
            proposals = engine.generate_communication_proposals(state, "proj-test-001")
        ids = [p.proposal_id for p in proposals]
        assert len(ids) == len(set(ids))

    def test_proposal_types_correct(self, engine):
        state = _make_state()
        mock_me = self._mock_me_all_low()
        with patch("core.training_engine.MetricsEngine", return_value=mock_me):
            proposals = engine.generate_communication_proposals(state, "proj-test-001")
        types = {p.proposal_type for p in proposals}
        assert "communication_waste" in types
        assert "context_bloat" in types

    def test_project_id_in_evidence(self, engine):
        state = _make_state()
        mock_me = self._mock_me_all_low()
        with patch("core.training_engine.MetricsEngine", return_value=mock_me):
            proposals = engine.generate_communication_proposals(state, "proj-test-abc")
        for p in proposals:
            assert "proj-test-abc" in p.project_ids

    def test_metric_exception_skipped(self, engine):
        """A scoring function that raises must not crash proposal generation."""
        state = _make_state()
        me = MagicMock()
        me.score_token_efficiency.side_effect = RuntimeError("bad")
        me.score_payload_density.return_value = _mock_metric_result(40.0)
        me.score_context_injection_efficiency.return_value = _mock_metric_result(90.0)
        me.score_consultation_overhead.return_value = _mock_metric_result(90.0)
        with patch("core.training_engine.MetricsEngine", return_value=me):
            proposals = engine.generate_communication_proposals(state, "proj-test-001")
        # Only payload_density is low and did not raise
        assert len(proposals) == 1
        assert proposals[0].proposal_type == "communication_waste"


# ---------------------------------------------------------------------------
# generate_communication_proposals — wire compliance
# ---------------------------------------------------------------------------

class TestWireComplianceProposal:
    def _mock_me_all_high(self):
        me = MagicMock()
        me.score_token_efficiency.return_value = _mock_metric_result(90.0)
        me.score_payload_density.return_value = _mock_metric_result(90.0)
        me.score_context_injection_efficiency.return_value = _mock_metric_result(90.0)
        me.score_consultation_overhead.return_value = _mock_metric_result(90.0)
        return me

    def test_wire_proposal_triggered_at_low_rate(self, engine):
        """Compliance rate < 0.5 with ≥ 5 handoffs → wire adoption proposal."""
        state = _make_state(wire_compliant=1, wire_total=5, compliance_rate=0.2)
        with patch("core.training_engine.MetricsEngine", return_value=self._mock_me_all_high()):
            proposals = engine.generate_communication_proposals(state, "proj-test-001")
        assert len(proposals) == 1
        assert proposals[0].proposal_type == "communication_waste"
        assert "wire" in proposals[0].description.lower()

    def test_wire_proposal_not_triggered_below_5_handoffs(self, engine):
        """Fewer than 5 handoffs → not enough evidence, no wire proposal."""
        state = _make_state(wire_compliant=0, wire_total=3, compliance_rate=0.0)
        with patch("core.training_engine.MetricsEngine", return_value=self._mock_me_all_high()):
            proposals = engine.generate_communication_proposals(state, "proj-test-001")
        assert len(proposals) == 0

    def test_wire_proposal_not_triggered_at_high_rate(self, engine):
        """Compliance rate ≥ 0.5 → no wire adoption proposal."""
        state = _make_state(wire_compliant=8, wire_total=10, compliance_rate=0.8)
        with patch("core.training_engine.MetricsEngine", return_value=self._mock_me_all_high()):
            proposals = engine.generate_communication_proposals(state, "proj-test-001")
        assert len(proposals) == 0

    def test_wire_proposal_minimum_evidence_met_at_10(self, engine):
        """minimum_evidence_met is True when wire_total >= 10."""
        state = _make_state(wire_compliant=2, wire_total=10, compliance_rate=0.2)
        with patch("core.training_engine.MetricsEngine", return_value=self._mock_me_all_high()):
            proposals = engine.generate_communication_proposals(state, "proj-test-001")
        assert len(proposals) == 1
        assert proposals[0].minimum_evidence_met is True

    def test_wire_proposal_minimum_evidence_not_met_below_10(self, engine):
        """minimum_evidence_met is False when wire_total is 5-9."""
        state = _make_state(wire_compliant=1, wire_total=7, compliance_rate=0.14)
        with patch("core.training_engine.MetricsEngine", return_value=self._mock_me_all_high()):
            proposals = engine.generate_communication_proposals(state, "proj-test-001")
        assert len(proposals) == 1
        assert proposals[0].minimum_evidence_met is False
