"""
Tests for PromptAssembler (mas/core/prompt_assembler.py).

Tests cover:
- Wire instruction injected for all agents EXCEPT inquirer_agent
- inquirer_agent prompt contains NO wire instruction
- State projection filters fields per agent
- Compact projection strips _meta, trims handoff history to 2
- Placeholder filling: {injected_project_id}, {injected_current_phase}, etc.
- Graph context injection: returns "" for sparse graph (< 5 nodes)
- Graph context injection: injects facts when graph has enough data
- last_token_count set after assemble()
- Unfilled placeholders left in-place (not replaced with "None")
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.prompt_assembler import (
    PromptAssembler, _project_state, _compact_projection, STATE_PROJECTIONS
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def agents_dir(tmp_path) -> Path:
    """Minimal agents directory with stub templates for key agents."""
    d = tmp_path / "agents"
    d.mkdir()

    # Master orchestrator — uses all injected keys
    (d / "master_orchestrator.md").write_text(
        "---\nname: master_orchestrator\n---\n"
        "Project: {injected_project_id}\n"
        "Phase: {injected_current_phase}\n"
        "State:\n{injected_shared_state}\n"
        "{injected_wire_instruction}\n"
        "{injected_graph_context}\n",
        encoding="utf-8",
    )

    # Inquirer — must NOT receive wire instruction
    (d / "inquirer_agent.md").write_text(
        "---\nname: inquirer_agent\n---\n"
        "Project: {injected_project_id}\n"
        "Ask clarifying questions.\n"
        "{injected_wire_instruction}\n",
        encoding="utf-8",
    )

    # Scribe — agent that checks handoff history injection
    (d / "scribe_agent.md").write_text(
        "---\nname: scribe_agent\n---\n"
        "Recent handoffs:\n{injected_recent_handoffs}\n"
        "{injected_wire_instruction}\n",
        encoding="utf-8",
    )

    return d


@pytest.fixture
def assembler(agents_dir) -> PromptAssembler:
    return PromptAssembler(agents_dir=agents_dir)


def _make_state(project_id="proj-test-001", phase="intake", n_handoffs=0) -> dict:
    handoffs = [
        {
            "handoff_id": f"ho-{i}",
            "from_agent": "master_orchestrator",
            "to_agent": "scribe_agent",
            "phase": phase,
            "task_description": f"Task {i}",
            "payload": {"summary": f"task {i}"},
            "acceptance": {"status": "accepted"},
        }
        for i in range(n_handoffs)
    ]
    return {
        "core_identity": {
            "project_id": project_id,
            "current_phase": phase,
            "status": "active",
        },
        "workflow": {
            "handoff_history": handoffs,
            "completed_phases": [],
            "current_owner": "master_orchestrator",
            "pending_assignments": [],
        },
        "project_definition": {
            "original_brief": "Build something",
            "clarified_specification": None,
        },
        "decisions": {"decision_log": []},
        "artifacts": {},
        "evaluation": {},
        "capability": {},
        "consultation": {"consultation_requests": [], "consultation_responses": []},
        "_meta": {
            "created_at": "2026-04-10T00:00:00Z",
            "updated_at": "2026-04-10T00:01:00Z",
            "governance_violations": [],
        },
    }


# ---------------------------------------------------------------------------
# Wire instruction: all agents except inquirer_agent
# ---------------------------------------------------------------------------

class TestWireInstruction:
    def test_master_orchestrator_gets_wire_instruction(self, assembler):
        state = _make_state()
        prompt = assembler.assemble("master_orchestrator", state)
        assert "_v" in prompt
        assert "wire protocol" in prompt.lower()

    def test_scribe_agent_gets_wire_instruction(self, assembler):
        state = _make_state()
        prompt = assembler.assemble("scribe_agent", state)
        assert "wire protocol" in prompt.lower() or "_v" in prompt

    def test_inquirer_agent_has_no_wire_instruction(self, assembler):
        state = _make_state()
        prompt = assembler.assemble("inquirer_agent", state)
        # Wire instruction block must be absent
        assert "_v" not in prompt
        assert "wire protocol" not in prompt.lower()
        assert "task:complete" not in prompt

    def test_inquirer_wire_instruction_placeholder_replaced_with_empty(self, assembler):
        """The {injected_wire_instruction} placeholder must be replaced with ""
        for inquirer — not left as the literal placeholder text."""
        state = _make_state()
        prompt = assembler.assemble("inquirer_agent", state)
        assert "{injected_wire_instruction}" not in prompt

    def test_wire_instruction_contains_version(self, assembler):
        state = _make_state()
        prompt = assembler.assemble("master_orchestrator", state)
        assert "1.0" in prompt

    def test_wire_instruction_mentions_rsn_cap(self, assembler):
        """The wire instruction must mention the 100-word reasoning cap."""
        state = _make_state()
        prompt = assembler.assemble("master_orchestrator", state)
        assert "100 words" in prompt


# ---------------------------------------------------------------------------
# State projection
# ---------------------------------------------------------------------------

class TestStateProjection:
    def test_inquirer_only_gets_core_identity_and_brief(self):
        state = _make_state()
        projected = _project_state(state, "inquirer_agent")
        assert "core_identity" in projected
        assert "project_definition" in projected
        # inquirer should NOT see workflow decisions
        assert "decisions" not in projected
        assert "evaluation" not in projected

    def test_master_orchestrator_gets_all_sections(self):
        state = _make_state()
        projected = _project_state(state, "master_orchestrator")
        for section in ["core_identity", "project_definition", "workflow",
                        "decisions", "capability", "consultation", "evaluation"]:
            assert section in projected

    def test_unknown_agent_gets_empty_projection(self):
        state = _make_state()
        projected = _project_state(state, "unknown_agent_xyz")
        assert projected == {}

    def test_scribe_agent_sees_handoff_history(self):
        state = _make_state(n_handoffs=3)
        projected = _project_state(state, "scribe_agent")
        assert "workflow" in projected
        assert "handoff_history" in projected["workflow"]


# ---------------------------------------------------------------------------
# Compact projection
# ---------------------------------------------------------------------------

class TestCompactProjection:
    def test_meta_stripped(self):
        state = _make_state()
        projected = _project_state(state, "master_orchestrator")
        compact = _compact_projection(projected)
        assert "_meta" not in compact

    def test_handoff_history_trimmed_to_2(self):
        state = _make_state(n_handoffs=5)
        projected = _project_state(state, "master_orchestrator")
        compact = _compact_projection(projected)
        history = compact.get("workflow", {}).get("handoff_history", [])
        assert len(history) <= 2

    def test_handoff_history_not_trimmed_when_short(self):
        state = _make_state(n_handoffs=1)
        projected = _project_state(state, "master_orchestrator")
        compact = _compact_projection(projected)
        history = compact.get("workflow", {}).get("handoff_history", [])
        assert len(history) == 1

    def test_empty_fields_stripped(self):
        state = _make_state()
        state["workflow"]["pending_assignments"] = []
        projected = _project_state(state, "master_orchestrator")
        compact = _compact_projection(projected)
        wf = compact.get("workflow", {})
        # pending_assignments is empty → stripped
        assert "pending_assignments" not in wf


# ---------------------------------------------------------------------------
# Placeholder filling
# ---------------------------------------------------------------------------

class TestPlaceholderFilling:
    def test_project_id_injected(self, assembler):
        state = _make_state(project_id="proj-placeholder-001")
        prompt = assembler.assemble("master_orchestrator", state)
        assert "proj-placeholder-001" in prompt

    def test_current_phase_injected(self, assembler):
        state = _make_state(phase="specification")
        prompt = assembler.assemble("master_orchestrator", state)
        assert "specification" in prompt

    def test_unfilled_placeholder_left_in_place(self, agents_dir):
        """A placeholder with no matching context key must stay as-is."""
        (agents_dir / "custom_agent.md").write_text(
            "---\nname: custom_agent\n---\nCustom: {injected_unknown_key}\n",
            encoding="utf-8",
        )
        assembler = PromptAssembler(agents_dir=agents_dir)
        state = _make_state()
        prompt = assembler.assemble("custom_agent", state)
        assert "{injected_unknown_key}" in prompt


# ---------------------------------------------------------------------------
# Token count
# ---------------------------------------------------------------------------

class TestTokenCount:
    def test_last_token_count_set_after_assemble(self, assembler):
        state = _make_state()
        assembler.assemble("master_orchestrator", state)
        assert hasattr(assembler, "last_token_count")
        assert isinstance(assembler.last_token_count, int)
        assert assembler.last_token_count > 0

    def test_longer_state_has_higher_token_count(self, assembler):
        short_state = _make_state()
        assembler.assemble("master_orchestrator", short_state)
        short_count = assembler.last_token_count

        long_state = _make_state(n_handoffs=10)
        assembler.assemble("master_orchestrator", long_state)
        long_count = assembler.last_token_count

        assert long_count >= short_count


# ---------------------------------------------------------------------------
# Graph context injection
# ---------------------------------------------------------------------------

class TestGraphContext:
    def test_graph_context_empty_for_sparse_graph(self, assembler, tmp_path, monkeypatch):
        """Graph with < 5 nodes → no graph context injected into prompt."""
        import core.graph_memory as gm_mod
        monkeypatch.setattr(gm_mod, "ROOT", tmp_path)

        state = _make_state(project_id="proj-gc-sparse-001")
        prompt = assembler.assemble("master_orchestrator", state)
        # Sparse graph → {injected_graph_context} replaced with ""
        assert "## Relevant Context (from graph memory)" not in prompt

    def test_graph_context_injected_when_dense(self, assembler, tmp_path, monkeypatch):
        """Graph with ≥ 5 nodes → facts injected into prompt."""
        import core.graph_memory as gm_mod
        monkeypatch.setattr(gm_mod, "ROOT", tmp_path)

        from core.graph_memory import GraphMemory
        gm = GraphMemory("proj-gc-dense-001")
        # Add 6 handoff episodes to populate graph
        for i in range(6):
            gm.write_episode("handoff", {
                "from_agent": "master_orchestrator",
                "to_agent": f"agent_{i}",
                "phase": "intake",
                "task_description": f"Task {i}",
            })

        state = _make_state(project_id="proj-gc-dense-001")
        prompt = assembler.assemble("master_orchestrator", state)
        assert "## Relevant Context (from graph memory)" in prompt

    def test_graph_context_never_raises(self, assembler, tmp_path, monkeypatch):
        """Even if GraphMemory raises internally, _graph_context returns '' silently."""
        import core.graph_memory as gm_mod
        monkeypatch.setattr(gm_mod, "ROOT", tmp_path)

        # Populate graph so node_count >= 5
        from core.graph_memory import GraphMemory
        gm = GraphMemory("proj-gc-raise-001")
        for i in range(6):
            gm.write_episode("handoff", {
                "from_agent": "master_orchestrator",
                "to_agent": f"agent_{i}",
                "phase": "intake",
            })

        # Now patch query to raise
        def bad_query(self, agent_id, context="", max_tokens=300):
            raise RuntimeError("graph unavailable")
        monkeypatch.setattr(GraphMemory, "query", bad_query)

        state = _make_state(project_id="proj-gc-raise-001")
        result = assembler._graph_context("master_orchestrator", state)
        assert result == ""


# ---------------------------------------------------------------------------
# State projection coverage
# ---------------------------------------------------------------------------

class TestProjectionCoverage:
    def test_all_agents_have_projection_defined(self):
        """Every agent in the roster must have a STATE_PROJECTIONS entry."""
        roster = [
            "master_orchestrator", "scribe_agent", "inquirer_agent",
            "product_manager_agent", "project_manager_agent", "hr_agent",
            "evaluator_agent", "trainer_agent", "spawner_agent",
            "risk_advisor", "quality_advisor", "devils_advocate",
            "domain_expert", "efficiency_advisor",
        ]
        for agent in roster:
            assert agent in STATE_PROJECTIONS, (
                f"No STATE_PROJECTIONS entry for '{agent}'"
            )
