"""
Unit Tests — CapabilityRegistry
Tests scoring, search, roster mutations, gap certificates, version history.
"""
import pytest
import yaml
from pathlib import Path
from core.capability_registry import (
    CapabilityRegistry,
    MatchResult,
    GapCertificate,
    STRONG_MATCH_THRESHOLD,
    PARTIAL_MATCH_THRESHOLD,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def registry(tmp_path):
    """A CapabilityRegistry backed by a fresh empty registry in tmp_path."""
    roster_dst = tmp_path / "roster"
    roster_dst.mkdir()

    # Minimal blank registry
    registry_path = roster_dst / "registry_index.yaml"
    registry_path.write_text(
        "registry:\n"
        "  version: '1.0.0'\n"
        "  last_updated: ''\n"
        "  maintained_by: hr_agent\n"
        "  agents: []\n"
        "  skills: []\n"
        "  tools: []\n"
        "counts:\n"
        "  active_agents: 0\n"
        "  active_skills: 0\n"
        "  retired_agents: 0\n"
        "  spawned_total: 0\n",
        encoding="utf-8",
    )

    # Blank version history
    vh_path = roster_dst / "version_history.yaml"
    vh_path.write_text(
        "version_history:\n"
        "  maintained_by: hr_agent\n"
        "  entries: []\n",
        encoding="utf-8",
    )

    return CapabilityRegistry(registry_path=registry_path,
                               version_history_path=vh_path)


@pytest.fixture
def populated_registry(registry):
    """Registry with a mix of active, probation, and retired agents."""
    agents = [
        {
            "agent_id": "reporting_agent",
            "name": "Reporting Agent",
            "version": "1.0.0",
            "trust_tier": "T1_established",
            "status": "active",
            "capabilities": ["reporting", "dashboard", "data-visualization",
                             "salesforce", "charts"],
            "performance_score": 82.0,
            "spawn_origin": None,
            "created_at": "2026-01-01T00:00:00+00:00",
        },
        {
            "agent_id": "etl_agent",
            "name": "ETL Agent",
            "version": "1.0.0",
            "trust_tier": "T1_established",
            "status": "active",
            "capabilities": ["etl", "data-pipeline", "transformation", "reporting"],
            "performance_score": 75.0,
            "spawn_origin": None,
            "created_at": "2026-01-02T00:00:00+00:00",
        },
        {
            "agent_id": "legacy_agent",
            "name": "Legacy Agent",
            "version": "0.9.0",
            "trust_tier": "T2_supervised",
            "status": "probation",
            "capabilities": ["reporting", "legacy-system", "csv-export"],
            "performance_score": 45.0,
            "spawn_origin": None,
            "created_at": "2025-06-01T00:00:00+00:00",
        },
        {
            "agent_id": "old_agent",
            "name": "Old Agent",
            "version": "0.1.0",
            "trust_tier": "T2_supervised",
            "status": "retired",
            "capabilities": ["reporting", "dashboard"],
            "performance_score": 30.0,
            "spawn_origin": None,
            "created_at": "2025-01-01T00:00:00+00:00",
        },
    ]
    for a in agents:
        registry.register_agent(a)
    return registry


# ---------------------------------------------------------------------------
# Scoring tests
# ---------------------------------------------------------------------------

class TestScoring:
    def test_perfect_match_scores_100(self, registry):
        score = registry.score_match(
            ["reporting", "dashboard"],
            ["reporting", "dashboard", "charts"],
        )
        assert score == 100.0

    def test_partial_match(self, registry):
        score = registry.score_match(
            ["reporting", "dashboard", "salesforce"],
            ["reporting", "dashboard"],
        )
        assert score == pytest.approx(100 * 2 / 3)

    def test_no_match_scores_zero(self, registry):
        score = registry.score_match(
            ["ml-training", "gpu-inference"],
            ["reporting", "dashboard"],
        )
        assert score == 0.0

    def test_empty_required_returns_zero(self, registry):
        assert registry.score_match([], ["reporting"]) == 0.0

    def test_case_insensitive_matching(self, registry):
        score = registry.score_match(
            ["Reporting", "DASHBOARD"],
            ["reporting", "dashboard"],
        )
        assert score == 100.0

    def test_strong_threshold_boundary(self, registry):
        # 4/5 = 80% → exactly at strong threshold
        score = registry.score_match(
            ["a", "b", "c", "d", "e"],
            ["a", "b", "c", "d"],
        )
        assert score == 80.0
        assert registry._classify_match(score) == "strong"

    def test_partial_threshold_boundary(self, registry):
        # 3/6 = 50% → exactly at partial threshold
        score = registry.score_match(
            ["a", "b", "c", "d", "e", "f"],
            ["a", "b", "c"],
        )
        assert score == 50.0
        assert registry._classify_match(score) == "partial"

    def test_below_partial_is_none(self, registry):
        # 1/3 = 33% → below partial
        score = registry.score_match(
            ["a", "b", "c"],
            ["a"],
        )
        assert score == pytest.approx(33.33, abs=0.1)
        assert registry._classify_match(score) == "none"


# ---------------------------------------------------------------------------
# Search tests
# ---------------------------------------------------------------------------

class TestSearch:
    def test_strong_match_found(self, populated_registry):
        results = populated_registry.search(
            ["reporting", "dashboard", "salesforce", "data-visualization"]
        )
        assert results[0].agent_id == "reporting_agent"
        assert results[0].match_type == "strong"

    def test_retired_agents_excluded(self, populated_registry):
        results = populated_registry.search(["reporting", "dashboard"])
        ids = [r.agent_id for r in results]
        assert "old_agent" not in ids

    def test_results_sorted_by_score_desc(self, populated_registry):
        results = populated_registry.search(["reporting", "dashboard", "salesforce"])
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_no_matching_tags_returns_zero_scores(self, populated_registry):
        results = populated_registry.search(["ml-training", "gpu-inference"])
        for r in results:
            assert r.score == 0.0

    def test_probation_agent_included_with_flag(self, populated_registry):
        results = populated_registry.search(["reporting", "legacy-system"])
        legacy = next(r for r in results if r.agent_id == "legacy_agent")
        assert legacy.on_probation is True
        assert "probation" in legacy.recommendation.lower()

    def test_get_strong_matches_filter(self, populated_registry):
        strong = populated_registry.get_strong_matches(
            ["reporting", "dashboard", "salesforce", "data-visualization"]
        )
        assert all(r.match_type == "strong" for r in strong)

    def test_get_partial_matches_filter(self, populated_registry):
        partial = populated_registry.get_partial_matches(["reporting", "salesforce", "ml"])
        assert all(r.match_type == "partial" for r in partial)

    def test_search_empty_registry(self, registry):
        results = registry.search(["anything"])
        assert results == []


# ---------------------------------------------------------------------------
# Roster mutation tests
# ---------------------------------------------------------------------------

class TestRosterMutation:
    def test_register_new_agent_adds_to_registry(self, registry):
        entry = {
            "agent_id": "test_agent",
            "name": "Test Agent",
            "version": "1.0.0",
            "trust_tier": "T1_established",
            "status": "active",
            "capabilities": ["testing"],
        }
        result = registry.register_agent(entry)
        assert result is True

        found = registry.get_agent("test_agent")
        assert found is not None
        assert found["agent_id"] == "test_agent"

    def test_register_existing_agent_updates_in_place(self, populated_registry):
        entry = {
            "agent_id": "etl_agent",
            "name": "ETL Agent v2",
            "version": "2.0.0",
            "trust_tier": "T1_established",
            "status": "active",
            "capabilities": ["etl", "data-pipeline", "streaming"],
        }
        populated_registry.register_agent(entry)
        found = populated_registry.get_agent("etl_agent")
        assert found["version"] == "2.0.0"
        assert found["name"] == "ETL Agent v2"

    def test_register_missing_fields_raises(self, registry):
        with pytest.raises(ValueError):
            registry.register_agent({"agent_id": "incomplete"})

    def test_retire_agent_sets_status(self, populated_registry):
        found = populated_registry.retire_agent("etl_agent", "replaced by streaming_agent")
        assert found is True
        agent = populated_registry.get_agent("etl_agent")
        assert agent["status"] == "retired"
        assert agent["retirement_reason"] == "replaced by streaming_agent"
        assert agent["retired_at"] is not None

    def test_retire_nonexistent_agent_returns_false(self, registry):
        result = registry.retire_agent("nonexistent", "test")
        assert result is False

    def test_retire_does_not_delete(self, populated_registry):
        populated_registry.retire_agent("etl_agent", "test")
        # Agent must still be readable
        agent = populated_registry.get_agent("etl_agent")
        assert agent is not None

    def test_counts_updated_after_register(self, registry):
        entry = {
            "agent_id": "new_agent",
            "name": "New Agent",
            "version": "1.0.0",
            "trust_tier": "T1_established",
            "status": "active",
            "capabilities": ["new"],
        }
        registry.register_agent(entry)
        data = registry.load_registry()
        assert data["counts"]["active_agents"] == 1

    def test_counts_updated_after_retire(self, populated_registry):
        populated_registry.retire_agent("reporting_agent", "test")
        data = populated_registry.load_registry()
        assert data["counts"]["retired_agents"] >= 1

    def test_performance_score_update(self, populated_registry):
        result = populated_registry.update_performance_score("reporting_agent", 91.5)
        assert result is True
        agent = populated_registry.get_agent("reporting_agent")
        assert agent["performance_score"] == 91.5

    def test_performance_score_out_of_range_raises(self, populated_registry):
        with pytest.raises(ValueError):
            populated_registry.update_performance_score("reporting_agent", 101.0)

    def test_flag_probation(self, populated_registry):
        result = populated_registry.flag_probation("etl_agent", "score dropped to 45")
        assert result is True
        agent = populated_registry.get_agent("etl_agent")
        assert agent["status"] == "probation"


# ---------------------------------------------------------------------------
# Version history tests
# ---------------------------------------------------------------------------

class TestVersionHistory:
    def test_register_appends_version_history(self, registry):
        entry = {
            "agent_id": "vh_test",
            "name": "VH Test",
            "version": "1.0.0",
            "trust_tier": "T1_established",
            "status": "active",
            "capabilities": ["vh"],
        }
        registry.register_agent(entry)
        vh = registry._load_version_history()
        entries = vh["version_history"]["entries"]
        assert len(entries) >= 1
        assert entries[-1]["change_type"] == "add"
        assert entries[-1]["target_id"] == "vh_test"

    def test_retire_appends_version_history(self, populated_registry):
        populated_registry.retire_agent("etl_agent", "test retire")
        vh = populated_registry._load_version_history()
        entries = vh["version_history"]["entries"]
        retire_entries = [e for e in entries if e["change_type"] == "retire"]
        assert len(retire_entries) >= 1

    def test_version_history_is_append_only(self, registry):
        """Old entries must never be modified."""
        entry = {
            "agent_id": "immutable_test",
            "name": "Immutable Test",
            "version": "1.0.0",
            "trust_tier": "T1_established",
            "status": "active",
            "capabilities": ["test"],
        }
        registry.register_agent(entry)
        vh_before = registry._load_version_history()
        first_entry = dict(vh_before["version_history"]["entries"][0])

        # Do another mutation
        registry.retire_agent("immutable_test", "test")

        vh_after = registry._load_version_history()
        assert vh_after["version_history"]["entries"][0] == first_entry


# ---------------------------------------------------------------------------
# Gap Certificate tests
# ---------------------------------------------------------------------------

class TestGapCertificate:
    def test_gap_cert_produced_when_no_match(self, registry):
        cert = registry.produce_gap_certificate(
            need_description="Need an ML training agent",
            required_capabilities=["ml-training", "gpu-inference", "model-registry"],
            project_id="proj-test-001",
            requested_by="product_manager_agent",
        )
        assert isinstance(cert, GapCertificate)
        assert cert.project_id == "proj-test-001"
        assert cert.exact_matches_found == 0
        assert cert.spawn_recommendation["should_spawn"] is True

    def test_gap_cert_includes_partial_details(self, populated_registry):
        # 2 of 3 required tags match reporting_agent → 66.7% → partial match
        cert = populated_registry.produce_gap_certificate(
            need_description="Need reporting dashboard with ML features",
            required_capabilities=["reporting", "dashboard", "ml-training"],
            project_id="proj-test-002",
            requested_by="product_manager_agent",
        )
        # reporting_agent matches "reporting" and "dashboard" → 66.7% partial
        assert cert.partial_matches_found >= 1

    def test_gap_cert_id_format(self, registry):
        cert = registry.produce_gap_certificate(
            need_description="test",
            required_capabilities=["xyz"],
            project_id="proj-abc-001",
            requested_by="test_agent",
        )
        assert cert.certificate_id.startswith("gap-proj-abc-001-")

    def test_gap_cert_to_dict_has_all_sections(self, registry):
        cert = registry.produce_gap_certificate(
            need_description="Need a thing",
            required_capabilities=["thing"],
            project_id="proj-001",
            requested_by="master_orchestrator",
        )
        d = cert.to_dict()
        cgc = d["capability_gap_certificate"]
        assert "search_performed" in cgc
        assert "why_existing_fails" in cgc
        assert "spawn_recommendation" in cgc
        assert cgc["approved_by_hr"] is False

    def test_gap_cert_saved_to_disk(self, registry, tmp_path):
        cert = registry.produce_gap_certificate(
            need_description="test",
            required_capabilities=["test"],
            project_id="proj-save-001",
            requested_by="master_orchestrator",
        )
        projects_root = tmp_path / "projects"
        projects_root.mkdir()
        path = registry.save_gap_certificate(cert, "proj-save-001",
                                              projects_root=projects_root)
        assert path.exists()
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert "capability_gap_certificate" in data
        assert data["capability_gap_certificate"]["certificate_id"] == cert.certificate_id

    def test_no_gap_when_strong_match_exists(self, populated_registry):
        """If a strong match exists, produce_gap_certificate still works
        but should reflect that strong matches were found."""
        cert = populated_registry.produce_gap_certificate(
            need_description="Need a reporting dashboard",
            required_capabilities=["reporting", "dashboard", "salesforce",
                                    "data-visualization"],
            project_id="proj-test-003",
            requested_by="product_manager_agent",
        )
        # Strong match found — exact_matches_found should be > 0
        assert cert.exact_matches_found >= 1


# ---------------------------------------------------------------------------
# MatchResult recommendation tests
# ---------------------------------------------------------------------------

class TestMatchResultRecommendation:
    def _make_result(self, match_type, on_probation=False, performance_score=None,
                     required=None, matching=None):
        required = required or ["a", "b", "c"]
        matching = matching or required[:]
        return MatchResult(
            agent_id="test",
            name="Test",
            trust_tier="T1",
            status="probation" if on_probation else "active",
            capabilities=matching,
            matching_tags=matching,
            required_tags=required,
            score=100.0 if match_type == "strong" else 60.0 if match_type == "partial" else 0.0,
            match_type=match_type,
            on_probation=on_probation,
            performance_score=performance_score,
        )

    def test_strong_match_recommends_reuse(self):
        r = self._make_result("strong")
        assert r.recommendation == "reuse"

    def test_strong_match_probation_includes_warning(self):
        r = self._make_result("strong", on_probation=True, performance_score=45.0)
        assert "reuse_with_warning" in r.recommendation
        assert "probation" in r.recommendation.lower()

    def test_partial_match_recommends_parameterize(self):
        r = self._make_result("partial", required=["a", "b", "c"], matching=["a", "b"])
        assert "parameterize" in r.recommendation
        assert "c" in r.recommendation

    def test_none_match_recommends_gap_certify(self):
        r = self._make_result("none", required=["x"], matching=[])
        assert r.recommendation == "gap_certify"
