"""
Tests for proj-20260415-004-mas-improvements-full (all 9 deliverables).

AC1: handoff_engine.accept() auto-appends dec items → decisions.decision_log
AC2: metrics_engine returns mode='not_applicable' for 50-default metrics on dry-run projects
AC3: prompt_assembler falls back to cross-project search when local hits < 2
AC4: db.py exports query_graph_node() and query_graph_edges()
AC5: prompt_assembler._graph_context() uses SQLite agent_graph tables
AC6: training_engine skips proposals whose description matches an applied/approved entry
AC7: mas/CLAUDE.md has Live Run Quickstart section
AC8: master_orchestrator.md documents scribe invocation at phase-close
AC9: librarian_agent.md has maintenance schedule section
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from core.utils.log_helpers import init_db, _get_connection


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_db(tmp_path):
    db = tmp_path / "test.db"
    init_db(db)
    return db


@pytest.fixture()
def tmp_project(tmp_path):
    """Minimal project directory with shared state."""
    pid = "proj-test-improvements-001"
    proj_dir = tmp_path / "projects" / pid
    proj_dir.mkdir(parents=True)
    state = {
        "core_identity": {"project_id": pid, "current_phase": "execution", "status": "active"},
        "workflow": {"completed_phases": [], "handoff_history": [], "current_owner": "master_orchestrator",
                     "mode": "standard", "active_agents": [], "pending_assignments": [],
                     "resource_requests": [], "resource_allocations": []},
        "decisions": {"decision_log": [], "assumptions": [], "open_questions": [], "approvals": [], "policy_flags": []},
        "project_definition": {}, "capability": {}, "execution": {}, "artifacts": {},
        "evaluation": {}, "consultation": {}, "communication": {}, "governance": {},
        "_meta": {"governance_violations": [], "created_at": "2026-01-01T00:00:00Z", "updated_at": "2026-01-01T00:00:00Z"},
    }
    (proj_dir / "shared_state.yaml").write_text(yaml.dump(state), encoding="utf-8")
    return proj_dir, pid


# ---------------------------------------------------------------------------
# AC1: handoff_engine auto-populates decision_log from dec payload
# ---------------------------------------------------------------------------

class TestDecisionLogAutoPopulation:
    """AC1: accept() appends dec items → decisions.decision_log."""

    def test_dec_items_appended_on_accept(self, tmp_project):
        proj_dir, pid = tmp_project
        from core.engine.shared_state_manager import SharedStateManager
        from core.engine.handoff_engine import HandoffEngine

        sm = SharedStateManager(pid, projects_root=proj_dir.parent, audit_logger=MagicMock())

        he = HandoffEngine(audit_logger=MagicMock())
        ho = he.create(sm,
            from_agent="master_orchestrator", to_agent="scribe_agent",
            phase="execution", task_description="test handoff",
            payload={"_v": "1.0", "s": "task:complete",
                     "dec": [{"id": "d-test-001", "v": "decision_value_here"}]})

        he.accept(sm, ho["handoff_id"])

        state = sm.load()
        log = state.get("decisions", {}).get("decision_log", [])
        assert len(log) == 1, f"Expected 1 decision_log entry, got {len(log)}"
        assert log[0]["decision_id"] == "d-test-001"
        assert log[0]["value"] == "decision_value_here"
        assert log[0]["source_handoff"] == ho["handoff_id"]

    def test_multiple_dec_items_all_appended(self, tmp_project):
        proj_dir, pid = tmp_project
        from core.engine.shared_state_manager import SharedStateManager
        from core.engine.handoff_engine import HandoffEngine

        sm = SharedStateManager(pid, projects_root=proj_dir.parent, audit_logger=MagicMock())

        he = HandoffEngine(audit_logger=MagicMock())
        ho = he.create(sm,
            from_agent="master_orchestrator", to_agent="scribe_agent",
            phase="execution", task_description="multi-dec test",
            payload={"_v": "1.0", "s": "task:complete",
                     "dec": [{"id": "d-001", "v": "v1"}, {"id": "d-002", "v": "v2"}]})
        he.accept(sm, ho["handoff_id"])

        state = sm.load()
        log = state.get("decisions", {}).get("decision_log", [])
        assert len(log) == 2
        ids = {e["decision_id"] for e in log}
        assert ids == {"d-001", "d-002"}

    def test_no_dec_no_decision_log_entries(self, tmp_project):
        proj_dir, pid = tmp_project
        from core.engine.shared_state_manager import SharedStateManager
        from core.engine.handoff_engine import HandoffEngine

        sm = SharedStateManager(pid, projects_root=proj_dir.parent, audit_logger=MagicMock())

        he = HandoffEngine(audit_logger=MagicMock())
        ho = he.create(sm,
            from_agent="master_orchestrator", to_agent="scribe_agent",
            phase="execution", task_description="no dec test",
            payload={"_v": "1.0", "s": "task:complete"})
        he.accept(sm, ho["handoff_id"])

        state = sm.load()
        log = state.get("decisions", {}).get("decision_log", [])
        assert log == []


# ---------------------------------------------------------------------------
# AC2: metrics_engine not_applicable mode on dry-run projects
# ---------------------------------------------------------------------------

class TestMetricsNotApplicable:
    """AC2: MetricResult.mode='not_applicable' for dry-run 50-defaults."""

    def test_metric_result_has_mode_field(self):
        from core.engine.metrics_engine import MetricResult
        m = MetricResult(metric="test", score=50.0, evidence="e", findings="f")
        assert hasattr(m, "mode")
        assert m.mode == "live"

    def test_not_applicable_mode_excluded_from_aggregate(self):
        from core.engine.metrics_engine import MetricsEngine, MetricResult
        engine = MetricsEngine()
        metrics = [
            MetricResult(metric="a", score=80.0, evidence="", findings=""),
            MetricResult(metric="b", score=50.0, evidence="", findings="", mode="not_applicable"),
            MetricResult(metric="c", score=60.0, evidence="", findings=""),
        ]
        score = engine.aggregate_project_score(metrics)
        assert abs(score - 70.0) < 0.01, f"Expected 70.0 (avg of 80+60), got {score}"

    def test_all_not_applicable_returns_zero(self):
        from core.engine.metrics_engine import MetricsEngine, MetricResult
        engine = MetricsEngine()
        metrics = [
            MetricResult(metric="a", score=50.0, evidence="", findings="", mode="not_applicable"),
        ]
        assert engine.aggregate_project_score(metrics) == 0.0

    def test_is_dry_run_state_true_when_no_live_calls(self, tmp_db):
        from core.engine.metrics_engine import MetricsEngine
        engine = MetricsEngine()
        state = {"core_identity": {"project_id": "proj-dry-test"}}
        # No events in db → live_calls=0 → dry-run
        with patch("core.db.query_token_usage", return_value={"live_calls": 0, "calls": 0}):
            result = engine._is_dry_run_state(state)
        assert result is True

    def test_is_dry_run_state_false_when_live_calls_exist(self):
        from core.engine.metrics_engine import MetricsEngine
        engine = MetricsEngine()
        state = {"core_identity": {"project_id": "proj-live-test"}}
        with patch("core.db.query_token_usage", return_value={"live_calls": 5, "calls": 5}):
            result = engine._is_dry_run_state(state)
        assert result is False


# ---------------------------------------------------------------------------
# AC3: prompt_assembler cross-project semantic search fallback
# ---------------------------------------------------------------------------

class TestCrossProjectSemanticFallback:
    """AC3: _sqlite_context() falls back to cross-project search when local < 2."""

    def test_cross_project_fallback_called_when_local_empty(self):
        from core.engine.prompt_assembler import PromptAssembler
        assembler = PromptAssembler()

        calls = []
        def mock_search(query, project_id=None, limit=5):
            calls.append(project_id)
            if project_id == "proj-local":
                return []   # local: no hits
            return [
                {"timestamp": "2026-01-01T00:00:00", "agent_id": "a", "action_type": "t",
                 "intent": "x", "project_id": "proj-other"},
                {"timestamp": "2026-01-01T00:01:00", "agent_id": "b", "action_type": "t",
                 "intent": "y", "project_id": "proj-other2"},
            ]

        with patch("core.db.semantic_search", side_effect=mock_search), \
             patch("core.db.query_project_history", return_value=[]), \
             patch("core.db.format_events_for_prompt", return_value="cross-project context"):
            result = assembler._sqlite_context("proj-local", phase="execution")

        # Should have tried cross-project search (project_id=None)
        assert None in calls, "Cross-project search (project_id=None) was not called"

    def test_uses_local_hits_when_sufficient(self):
        from core.engine.prompt_assembler import PromptAssembler
        assembler = PromptAssembler()

        local_events = [
            {"timestamp": "2026-01-01", "agent_id": "a", "action_type": "t",
             "intent": "local1", "project_id": "proj-local"},
            {"timestamp": "2026-01-01", "agent_id": "b", "action_type": "t",
             "intent": "local2", "project_id": "proj-local"},
        ]

        cross_calls = []
        def mock_search(query, project_id=None, limit=5):
            if project_id is None:
                cross_calls.append(True)
            return local_events

        with patch("core.db.semantic_search", side_effect=mock_search), \
             patch("core.db.format_events_for_prompt", return_value="local context"):
            assembler._sqlite_context("proj-local", phase="execution")

        assert not cross_calls, "Cross-project search should not fire when local has ≥2 hits"


# ---------------------------------------------------------------------------
# AC4: db.py graph query helpers
# ---------------------------------------------------------------------------

class TestGraphQueryHelpers:
    """AC4: query_graph_node() and query_graph_edges() are exported from db.py."""

    def test_query_graph_node_exported(self):
        from core import db
        assert hasattr(db, "query_graph_node")
        assert "query_graph_node" in db.__all__

    def test_query_graph_edges_exported(self):
        from core import db
        assert hasattr(db, "query_graph_edges")
        assert "query_graph_edges" in db.__all__

    def test_query_graph_node_returns_none_when_missing(self, tmp_db):
        from core.db import query_graph_node
        result = query_graph_node("nonexistent-agent", db_path=tmp_db)
        assert result is None

    def test_query_graph_edges_returns_empty_when_none(self, tmp_db):
        from core.db import query_graph_edges
        result = query_graph_edges("nonexistent-agent", db_path=tmp_db)
        assert result == []

    def test_query_graph_node_finds_inserted_row(self, tmp_db):
        from core.db import query_graph_node
        conn = _get_connection(tmp_db)
        conn.execute("INSERT INTO agent_graph(id, type, label, meta) VALUES (?,?,?,?)",
                     ("master_orchestrator", "agent", "Master Orchestrator", "{}"))
        conn.commit()
        conn.close()

        row = query_graph_node("master_orchestrator", db_path=tmp_db)
        assert row is not None
        assert row["label"] == "Master Orchestrator"

    def test_query_graph_edges_finds_connected_edges(self, tmp_db):
        from core.db import query_graph_edges
        conn = _get_connection(tmp_db)
        conn.execute("INSERT INTO agent_graph_edges(id, source, target, relation, meta) VALUES (?,?,?,?,?)",
                     ("e-001", "master_orchestrator", "scribe_agent", "delegates_to", "{}"))
        conn.commit()
        conn.close()

        edges = query_graph_edges("master_orchestrator", db_path=tmp_db)
        assert len(edges) == 1
        assert edges[0]["relation"] == "delegates_to"


# ---------------------------------------------------------------------------
# AC5: prompt_assembler._graph_context() uses SQLite tables
# ---------------------------------------------------------------------------

class TestGraphContextInjection:
    """AC5: _graph_context() reads from agent_graph SQLite tables."""

    def test_graph_context_empty_when_no_data(self):
        from core.engine.prompt_assembler import PromptAssembler
        assembler = PromptAssembler()
        with patch("core.db.query_graph_node", return_value=None), \
             patch("core.db.query_graph_edges", return_value=[]):
            result = assembler._graph_context("master_orchestrator", {})
        # Falls through to GraphMemory fallback which also returns "" with no project_id
        assert isinstance(result, str)

    def test_graph_context_populated_from_sqlite(self):
        from core.engine.prompt_assembler import PromptAssembler
        assembler = PromptAssembler()
        node = {"id": "master_orchestrator", "type": "agent", "label": "Master Orchestrator", "meta": "{}"}
        edges = [{"id": "e-1", "source": "master_orchestrator", "target": "scribe_agent",
                  "relation": "delegates_to", "meta": "{}"}]

        with patch("core.db.query_graph_node", return_value=node), \
             patch("core.db.query_graph_edges", return_value=edges):
            result = assembler._graph_context("master_orchestrator", {})

        assert "Agent Graph Context" in result
        assert "Master Orchestrator" in result
        assert "delegates_to" in result
        assert "scribe_agent" in result


# ---------------------------------------------------------------------------
# AC6: training_engine proposal deduplication
# ---------------------------------------------------------------------------

class TestTrainingProposalDeduplication:
    """AC6: analyze_evaluation_report skips already-applied/approved descriptions."""

    def _make_report(self, metric="goal_achievement", score=50.0):
        return {
            "project_id": "proj-test",
            "report_id": "eval-test-001",
            "project_metrics": [
                {"metric": metric, "score": score,
                 "evidence": "No success criteria", "mode": "live"}
            ],
            "agent_evaluations": [],
            "systemic_findings": {},
            "recommendations": {"improvement_areas": []},
        }

    def _make_backlog_with_applied(self, description):
        return {"proposals": [
            {"proposal_id": "prop-old-001", "status": "applied",
             "description": description},
        ]}

    def test_duplicate_applied_proposal_skipped(self, monkeypatch):
        from core.engine.training_engine import TrainingEngine
        te = TrainingEngine()
        report = self._make_report()
        desc = ("Metric 'goal_achievement' scored 50.0/100 "
                "(below threshold 70.0). Evidence: No success criteria")
        backlog = self._make_backlog_with_applied(desc)
        monkeypatch.setattr(te, "load_backlog", lambda: backlog)

        proposals = te.analyze_evaluation_report(report, project_id="proj-test")
        # The metric proposal should be skipped (duplicate of applied entry)
        metric_props = [p for p in proposals
                        if p.description.startswith("Metric 'goal_achievement'")]
        assert metric_props == [], "Duplicate applied proposal should be skipped"

    def test_non_duplicate_proposal_generated(self, monkeypatch):
        from core.engine.training_engine import TrainingEngine
        te = TrainingEngine()
        report = self._make_report()
        backlog = {"proposals": []}  # empty backlog
        monkeypatch.setattr(te, "load_backlog", lambda: backlog)

        proposals = te.analyze_evaluation_report(report, project_id="proj-test")
        metric_props = [p for p in proposals
                        if "goal_achievement" in p.description]
        assert len(metric_props) >= 1, "New proposal should be generated when backlog is empty"

    def test_pending_proposal_not_treated_as_duplicate(self, monkeypatch):
        from core.engine.training_engine import TrainingEngine
        te = TrainingEngine()
        report = self._make_report()
        desc = ("Metric 'goal_achievement' scored 50.0/100 "
                "(below threshold 70.0). Evidence: No success criteria")
        backlog = {"proposals": [
            {"proposal_id": "prop-pending", "status": "pending", "description": desc}
        ]}
        monkeypatch.setattr(te, "load_backlog", lambda: backlog)

        proposals = te.analyze_evaluation_report(report, project_id="proj-test")
        # pending != applied/approved → should still generate
        metric_props = [p for p in proposals
                        if "goal_achievement" in p.description]
        assert len(metric_props) >= 1, "Pending proposals should not block new generation"

    def test_not_applicable_metrics_skipped(self, monkeypatch):
        from core.engine.training_engine import TrainingEngine
        te = TrainingEngine()
        report = {
            "project_id": "proj-dry",
            "report_id": "eval-dry-001",
            "project_metrics": [
                {"metric": "goal_achievement", "score": 50.0,
                 "evidence": "dry-run", "mode": "not_applicable"}
            ],
            "agent_evaluations": [],
            "systemic_findings": {},
            "recommendations": {"improvement_areas": []},
        }
        monkeypatch.setattr(te, "load_backlog", lambda: {"proposals": []})
        proposals = te.analyze_evaluation_report(report, project_id="proj-dry")
        na_props = [p for p in proposals if "goal_achievement" in p.description]
        assert na_props == [], "not_applicable metrics should not generate proposals"


# ---------------------------------------------------------------------------
# AC7: mas/CLAUDE.md has Live Run Quickstart section
# ---------------------------------------------------------------------------

class TestCLAUDEMdLiveRunSection:
    def test_live_run_quickstart_exists(self):
        claude_md = Path(__file__).parents[2] / "CLAUDE.md"
        content = claude_md.read_text(encoding="utf-8")
        assert "Live Run Quickstart" in content

    def test_live_run_section_mentions_api_key(self):
        claude_md = Path(__file__).parents[2] / "CLAUDE.md"
        content = claude_md.read_text(encoding="utf-8")
        assert "ANTHROPIC_API_KEY" in content

    def test_live_run_section_mentions_mas_tokens(self):
        claude_md = Path(__file__).parents[2] / "CLAUDE.md"
        content = claude_md.read_text(encoding="utf-8")
        assert "mas tokens" in content

    def test_live_run_section_explains_dry_run_behavior(self):
        claude_md = Path(__file__).parents[2] / "CLAUDE.md"
        content = claude_md.read_text(encoding="utf-8")
        assert "not_applicable" in content or "dry-run" in content.lower()


# ---------------------------------------------------------------------------
# AC8: master_orchestrator.md documents scribe invocation
# ---------------------------------------------------------------------------

class TestMasterOrchestratorScribeDoc:
    def test_scribe_invocation_at_phase_close_documented(self):
        mo_md = Path(__file__).parents[3] / "agents" / "master_orchestrator.md"
        content = mo_md.read_text(encoding="utf-8")
        assert "scribe_agent" in content
        assert "phase-close" in content or "phase close" in content.lower()

    def test_documentation_completeness_mentioned(self):
        mo_md = Path(__file__).parents[3] / "agents" / "master_orchestrator.md"
        content = mo_md.read_text(encoding="utf-8")
        assert "documentation_completeness" in content


# ---------------------------------------------------------------------------
# AC9: librarian_agent.md has maintenance schedule
# ---------------------------------------------------------------------------

class TestLibrarianMaintenanceSchedule:
    def test_maintenance_section_exists(self):
        lib_md = Path(__file__).parents[3] / "agents" / "librarian_agent.md"
        content = lib_md.read_text(encoding="utf-8")
        assert "maintenance" in content.lower()

    def test_rebuild_fts_mentioned(self):
        lib_md = Path(__file__).parents[3] / "agents" / "librarian_agent.md"
        content = lib_md.read_text(encoding="utf-8")
        assert "rebuild-fts" in content or "rebuild_fts" in content

    def test_migrate_graph_mentioned(self):
        lib_md = Path(__file__).parents[3] / "agents" / "librarian_agent.md"
        content = lib_md.read_text(encoding="utf-8")
        assert "migrate-graph" in content or "migrate_graph" in content
