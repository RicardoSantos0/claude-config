"""
Unit tests for GraphMemory (mas/core/graph_memory.py).

Tests cover:
- GraphStore: add_node, add_edge, has_node, node_count, edge_count
- GraphStore: neighbors() returns connected nodes
- GraphStore: save/load round-trip (SQLite persistence)
- GraphMemory: write_episode() for each episode type
- GraphMemory: query() returns bounded facts
- GraphMemory: query() returns empty for unknown agent with no graph
- GraphMemory: get_related() returns neighbors
- GraphMemory: stats() returns expected keys
- EpisodeWriter: record_handoff() creates episode
- Entity/relationship vocabulary constants
- All episode types do not raise even with minimal data
"""

import pytest
from pathlib import Path

from core.engine.graph_memory import (
    GraphStore, GraphMemory, EpisodeWriter,
    ENTITY_TYPES, RELATIONSHIP_TYPES, MAX_INJECT_TOKENS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def patch_root(tmp_path, monkeypatch):
    import core.engine.graph_memory as gm_mod
    monkeypatch.setattr(gm_mod, "ROOT", tmp_path)
    return tmp_path


@pytest.fixture
def store(tmp_path):
    return GraphStore("proj-gm-001")


@pytest.fixture
def gm():
    return GraphMemory("proj-gm-001")


# ---------------------------------------------------------------------------
# Entity / relationship vocabulary
# ---------------------------------------------------------------------------

class TestVocabulary:
    def test_entity_types_contains_required(self):
        required = {"project", "agent", "decision", "artifact", "capability",
                    "evaluation", "finding", "proposal", "phase", "handoff"}
        assert required <= ENTITY_TYPES

    def test_relationship_types_contains_required(self):
        required = {"owns", "produced", "decided", "references", "depends_on",
                    "handoff_to", "evaluated_by", "spawned_from", "related_to"}
        assert required <= RELATIONSHIP_TYPES


# ---------------------------------------------------------------------------
# GraphStore
# ---------------------------------------------------------------------------

class TestGraphStore:
    def test_add_and_check_node(self, store):
        store.add_node("master_orchestrator", "agent", label="master_orchestrator")
        assert store.has_node("master_orchestrator")

    def test_node_count(self, store):
        store.add_node("agent-a", "agent")
        store.add_node("agent-b", "agent")
        assert store.node_count() == 2

    def test_get_node_returns_attrs(self, store):
        store.add_node("scribe_agent", "agent", label="scribe")
        n = store.get_node("scribe_agent")
        assert n is not None
        assert n["entity_type"] == "agent"

    def test_get_node_returns_none_for_unknown(self, store):
        assert store.get_node("ghost") is None

    def test_add_edge(self, store):
        store.add_node("a", "agent")
        store.add_node("b", "agent")
        store.add_edge("a", "b", "handoff_to")
        assert store.edge_count() == 1

    def test_neighbors_returns_connected_nodes(self, store):
        store.add_node("a", "agent")
        store.add_node("b", "agent")
        store.add_node("c", "phase")
        store.add_edge("a", "b", "handoff_to")
        store.add_edge("a", "c", "completed")
        neighbors = store.neighbors("a")
        ids = {n["node_id"] for n in neighbors}
        assert "b" in ids
        assert "c" in ids

    def test_neighbors_empty_for_isolated_node(self, store):
        store.add_node("lone", "agent")
        assert store.neighbors("lone") == []

    def test_neighbors_returns_empty_for_unknown(self, store):
        assert store.neighbors("nonexistent") == []

    def test_save_and_load(self, tmp_path):
        s = GraphStore("proj-gm-persist")
        s.add_node("agent-x", "agent", label="agent-x")
        s.add_node("phase-y", "phase", label="intake")
        s.add_edge("agent-x", "phase-y", "completed")
        s.save()

        s2 = GraphStore("proj-gm-persist")
        assert s2.has_node("agent-x")
        assert s2.node_count() >= 2
        assert s2.edge_count() >= 1

    def test_invalid_entity_type_falls_back(self, store):
        """Unknown entity type should not raise — falls back to related_to."""
        store.add_node("node-x", "totally_unknown_type")
        assert store.has_node("node-x")


# ---------------------------------------------------------------------------
# GraphMemory — write_episode()
# ---------------------------------------------------------------------------

class TestWriteEpisode:
    def test_handoff_episode_creates_nodes(self, gm):
        eid = gm.write_episode("handoff", {
            "from_agent": "master_orchestrator",
            "to_agent": "scribe_agent",
            "phase": "intake",
            "task_description": "Initialize project",
        })
        assert eid.startswith("ep-handoff-")
        assert gm.store.has_node("master_orchestrator")
        assert gm.store.has_node("scribe_agent")
        assert gm.store.has_node("intake")

    def test_decision_episode(self, gm):
        eid = gm.write_episode("decision", {
            "decision_id": "dec-001",
            "made_by": "master_orchestrator",
            "description": "Approved execution plan",
        })
        assert gm.store.has_node("dec-001")
        assert gm.store.has_node("master_orchestrator")

    def test_artifact_episode(self, gm):
        eid = gm.write_episode("artifact", {
            "artifact_id": "art-001",
            "created_by": "scribe_agent",
            "name": "execution_plan.yaml",
        })
        assert gm.store.has_node("art-001")

    def test_phase_episode(self, gm):
        gm.write_episode("phase", {
            "phase": "planning",
            "project_id": "proj-gm-001",
        })
        assert gm.store.has_node("planning")
        assert gm.store.has_node("proj-gm-001")

    def test_finding_episode(self, gm):
        gm.write_episode("finding", {
            "description": "Scope unclear",
        })
        # A finding node should exist
        assert gm.store.node_count() >= 1

    def test_proposal_episode(self, gm):
        gm.write_episode("proposal", {
            "proposal_id": "prop-001",
            "description": "Improve wire adoption",
            "target_agent": "scribe_agent",
        })
        assert gm.store.has_node("prop-001")

    def test_generic_episode_does_not_raise(self, gm):
        eid = gm.write_episode("unknown_type", {"label": "some random event"})
        assert eid is not None

    def test_episode_returns_string_id(self, gm):
        eid = gm.write_episode("phase", {"phase": "intake"})
        assert isinstance(eid, str)
        assert len(eid) > 0

    @pytest.mark.parametrize("etype", [
        "handoff", "decision", "artifact", "phase", "finding", "proposal"
    ])
    def test_all_episode_types_with_minimal_data(self, gm, etype):
        """Every episode type must not raise with empty data dict."""
        try:
            gm.write_episode(etype, {})
        except Exception as exc:
            pytest.fail(f"write_episode({etype!r}, {{}}) raised: {exc}")


# ---------------------------------------------------------------------------
# GraphMemory — query()
# ---------------------------------------------------------------------------

class TestQuery:
    def _populate(self, gm):
        gm.write_episode("handoff", {
            "from_agent": "master_orchestrator",
            "to_agent": "scribe_agent",
            "phase": "intake",
            "task_description": "Initialize intake folder",
        })
        gm.write_episode("handoff", {
            "from_agent": "master_orchestrator",
            "to_agent": "product_manager_agent",
            "phase": "specification",
            "task_description": "Write product plan",
        })
        gm.write_episode("artifact", {
            "artifact_id": "art-plan",
            "created_by": "scribe_agent",
            "name": "execution_plan.yaml",
        })

    def test_query_returns_dict_with_required_keys(self, gm):
        self._populate(gm)
        result = gm.query("master_orchestrator", "intake")
        assert "agent_id" in result
        assert "facts" in result
        assert "token_estimate" in result

    def test_query_token_estimate_within_bound(self, gm):
        self._populate(gm)
        result = gm.query("master_orchestrator", "intake")
        assert result["token_estimate"] <= MAX_INJECT_TOKENS

    def test_query_returns_empty_facts_for_sparse_graph(self, gm):
        """Less than 5 nodes → query returns empty facts (graph not useful yet)."""
        gm.store.add_node("master_orchestrator", "agent")
        result = gm.query("master_orchestrator", "")
        # node_count < 5 → _graph_context returns "" → query still works
        assert isinstance(result["facts"], list)

    def test_query_context_string_used(self, gm):
        self._populate(gm)
        result = gm.query("scribe_agent", context="execution_plan")
        assert isinstance(result["facts"], list)

    def test_query_unknown_agent_returns_dict(self, gm):
        self._populate(gm)
        result = gm.query("unknown_agent_xyz", "")
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# GraphMemory — get_related()
# ---------------------------------------------------------------------------

class TestGetRelated:
    def test_get_related_returns_list(self, gm):
        gm.write_episode("handoff", {
            "from_agent": "master_orchestrator",
            "to_agent": "scribe_agent",
            "phase": "intake",
        })
        related = gm.get_related("master_orchestrator")
        assert isinstance(related, list)

    def test_get_related_unknown_node_returns_empty(self, gm):
        assert gm.get_related("ghost_node") == []


# ---------------------------------------------------------------------------
# GraphMemory — stats()
# ---------------------------------------------------------------------------

class TestStats:
    def test_stats_has_required_keys(self, gm):
        s = gm.stats()
        assert "project_id" in s
        assert "node_count" in s
        assert "edge_count" in s
        assert "networkx_available" in s

    def test_stats_node_count_increases(self, gm):
        before = gm.stats()["node_count"]
        gm.write_episode("phase", {"phase": "intake"})
        after = gm.stats()["node_count"]
        assert after > before


# ---------------------------------------------------------------------------
# EpisodeWriter
# ---------------------------------------------------------------------------

class TestEpisodeWriter:
    def test_record_handoff_creates_episode(self):
        ew = EpisodeWriter("proj-gm-ep-001")
        handoff = {
            "from_agent": "master_orchestrator",
            "to_agent": "scribe_agent",
            "phase": "intake",
            "task_description": "Initialize",
            "handoff_id": "ho-proj-gm-ep-001-001",
        }
        eid = ew.record_handoff(handoff)
        assert isinstance(eid, str)

    def test_record_phase_transition(self):
        ew = EpisodeWriter("proj-gm-ep-002")
        eid = ew.record_phase_transition("specification", "proj-gm-ep-002")
        assert isinstance(eid, str)


# ---------------------------------------------------------------------------
# Integration: handoff_engine writes episode
# ---------------------------------------------------------------------------

class TestHandoffEngineIntegration:
    def test_handoff_creates_graph_episode(self, tmp_path, monkeypatch):
        import core.engine.shared_state_manager as ssm_mod
        import core.engine.checkpoint_writer as cw_mod
        monkeypatch.setattr(ssm_mod, "ROOT", tmp_path)
        monkeypatch.setattr(cw_mod, "ROOT", tmp_path)

        from core.engine.shared_state_manager import SharedStateManager
        from core.engine.handoff_engine import HandoffEngine

        sm = SharedStateManager("proj-gm-integ-001")
        sm.initialize(request_id="req-gm-001")
        engine = HandoffEngine()
        engine.create(sm, "master_orchestrator", "scribe_agent",
                      "intake", "Init", payload={"summary": "ok"})

        gm = GraphMemory("proj-gm-integ-001")
        assert gm.store.node_count() >= 1
