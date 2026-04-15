"""
Tests for FTS5 semantic search — proj-20260415-001-db-semantic-and-acl-fix

AC4  semantic_search("handoff", project_id) returns ≥ 1 result after events are written
AC5  FTS5 trigger fires: append_event → FTS index has a row
AC6  prompt_assembler._sqlite_context uses semantic search when phase is present
"""

import pytest
import tempfile
import sqlite3
from pathlib import Path
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_temp_db() -> Path:
    """Create a fresh isolated DB for each test."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    return Path(tmp.name)


def _init_and_populate(db_path: Path, project_id: str = "proj-test") -> None:
    """Init schema and insert a handoff event into the test DB."""
    from core.utils.log_helpers import init_db, append_event
    init_db(db_path)
    append_event(
        project_id=project_id,
        agent_id="master_orchestrator",
        action_type="handoff_created",
        intent="Delegate handoff to inquirer_agent for intake",
        db_path=db_path,
    )


# ---------------------------------------------------------------------------
# AC4: semantic_search returns results
# ---------------------------------------------------------------------------

class TestSemanticSearchReturnsResults:

    def test_search_finds_existing_event(self):
        """AC4: semantic_search returns ≥ 1 result matching 'handoff'."""
        from core.db import semantic_search
        db_path = _make_temp_db()
        _init_and_populate(db_path)

        results = semantic_search("handoff", db_path=db_path)
        assert len(results) >= 1, "Expected at least one hit for 'handoff'"

    def test_search_keyword_in_intent(self):
        """AC4: keyword present in intent is found."""
        from core.utils.log_helpers import init_db, append_event
        from core.db import semantic_search

        db_path = _make_temp_db()
        init_db(db_path)
        append_event("proj-kw", "scribe_agent", "handoff_accepted",
                     "Scribe accepted the evaluation report task", db_path=db_path)

        results = semantic_search("evaluation", db_path=db_path)
        assert any("evaluation" in (r.get("intent") or "").lower() for r in results)

    def test_project_filter_scopes_results(self):
        """AC4: project_id filter returns only matching project events."""
        from core.utils.log_helpers import init_db, append_event
        from core.db import semantic_search

        db_path = _make_temp_db()
        init_db(db_path)
        append_event("proj-alpha", "master_orchestrator", "handoff_created",
                     "intake handoff for alpha project", db_path=db_path)
        append_event("proj-beta", "master_orchestrator", "handoff_created",
                     "intake handoff for beta project", db_path=db_path)

        alpha_results = semantic_search("intake", project_id="proj-alpha", db_path=db_path)
        beta_results  = semantic_search("intake", project_id="proj-beta",  db_path=db_path)

        assert all(r["project_id"] == "proj-alpha" for r in alpha_results)
        assert all(r["project_id"] == "proj-beta"  for r in beta_results)

    def test_search_graceful_on_empty_db(self):
        """AC4: empty DB returns [] without raising."""
        from core.utils.log_helpers import init_db
        from core.db import semantic_search

        db_path = _make_temp_db()
        init_db(db_path)  # tables created, no rows

        results = semantic_search("anything", db_path=db_path)
        assert results == []

    def test_empty_query_returns_empty(self):
        """AC4 edge case: blank query returns [] immediately."""
        from core.db import semantic_search
        db_path = _make_temp_db()
        assert semantic_search("", db_path=db_path) == []
        assert semantic_search("  ", db_path=db_path) == []


# ---------------------------------------------------------------------------
# AC5: FTS5 trigger fires on append_event
# ---------------------------------------------------------------------------

class TestFTS5TriggerFiresOnAppend:

    def test_trigger_inserts_fts_row(self):
        """AC5: after append_event, agent_events_fts has a matching row."""
        from core.utils.log_helpers import init_db, append_event

        db_path = _make_temp_db()
        init_db(db_path)

        import sqlite3
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        before = conn.execute("SELECT count(*) FROM agent_events_fts").fetchone()[0]
        append_event("proj-fts-test", "evaluator_agent", "handoff_created",
                     "trigger test for FTS5 index", db_path=db_path)
        after = conn.execute("SELECT count(*) FROM agent_events_fts").fetchone()[0]
        conn.close()

        assert after == before + 1, "FTS5 trigger did not fire on append_event"

    def test_trigger_content_is_searchable(self):
        """AC5: content inserted via trigger is immediately searchable."""
        from core.utils.log_helpers import init_db, append_event
        from core.db import semantic_search

        db_path = _make_temp_db()
        init_db(db_path)

        append_event("proj-fts-content", "hr_agent", "handoff_accepted",
                     "capability gap certificate approved for spawner", db_path=db_path)

        results = semantic_search("certificate", db_path=db_path)
        assert len(results) >= 1
        assert "certificate" in (results[0].get("intent") or "").lower()

    def test_multiple_appends_all_indexed(self):
        """AC5: multiple append_event calls all land in FTS index."""
        from core.utils.log_helpers import init_db, append_event

        db_path = _make_temp_db()
        init_db(db_path)

        for i in range(5):
            append_event(f"proj-multi", "master_orchestrator", "handoff_created",
                         f"test handoff event number {i}", db_path=db_path)

        import sqlite3
        conn = sqlite3.connect(str(db_path))
        count = conn.execute("SELECT count(*) FROM agent_events_fts").fetchone()[0]
        conn.close()
        assert count == 5


# ---------------------------------------------------------------------------
# AC6: prompt_assembler uses semantic search when phase is provided
# ---------------------------------------------------------------------------

class TestPromptAssemblerUsesSemanticSearch:

    def test_sqlite_context_calls_semantic_search_when_phase_given(self):
        """AC6: _sqlite_context prefers semantic_search when phase is present."""
        from core.engine.prompt_assembler import PromptAssembler

        pa = PromptAssembler()

        with patch("core.db.semantic_search") as mock_sem, \
             patch("core.db.query_project_history") as mock_hist, \
             patch("core.db.format_events_for_prompt", return_value="[events]"):

            # Simulate ≥ 2 semantic results so fallback is NOT triggered
            mock_sem.return_value = [{"intent": "a"}, {"intent": "b"}]
            mock_hist.return_value = []

            result = pa._sqlite_context("proj-x", phase="execution")

        mock_sem.assert_called_once_with("execution", project_id="proj-x", limit=5)
        assert result == "[events]"

    def test_sqlite_context_falls_back_when_semantic_empty(self):
        """AC6: falls back to query_project_history when semantic returns < 2 results."""
        from core.engine.prompt_assembler import PromptAssembler

        pa = PromptAssembler()

        with patch("core.db.semantic_search", return_value=[]) as mock_sem, \
             patch("core.db.query_project_history", return_value=[{"intent": "recent"}]) as mock_hist, \
             patch("core.db.format_events_for_prompt", return_value="[fallback]"):

            result = pa._sqlite_context("proj-y", phase="review")

        mock_sem.assert_called_once()
        mock_hist.assert_called_once_with("proj-y", limit=5)
        assert result == "[fallback]"

    def test_sqlite_context_no_phase_skips_semantic(self):
        """AC6: when phase is empty, goes straight to query_project_history."""
        from core.engine.prompt_assembler import PromptAssembler

        pa = PromptAssembler()

        with patch("core.db.semantic_search") as mock_sem, \
             patch("core.db.query_project_history", return_value=[]) as mock_hist, \
             patch("core.db.format_events_for_prompt", return_value=""):

            pa._sqlite_context("proj-z", phase="")

        mock_sem.assert_not_called()
        mock_hist.assert_called_once()
