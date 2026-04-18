"""
Tests for `mas tokens <project_id>` CLI subcommand (D1).
AC1: tokens command outputs project token summary.
AC2: dry/live call breakdown is included.
"""

import json
import tempfile
from pathlib import Path

import pytest
from click.testing import CliRunner

from core.cli import main
from core.utils.log_helpers import init_db, append_event


@pytest.fixture()
def tmp_db(tmp_path):
    db = tmp_path / "test.db"
    init_db(db)
    return db


@pytest.fixture()
def runner():
    return CliRunner()


def _write_call(db, project_id, dry=False, prompt=100, completion=50):
    append_event(
        project_id=project_id,
        agent_id="test_agent",
        action_type="agent_call",
        intent="test prompt",
        result_shape=f"tokens={prompt + completion}",
        payload={
            "model": "test-model",
            "tokens_prompt": prompt,
            "tokens_completion": completion,
            "tokens_total": prompt + completion,
            "dry_run": dry,
        },
        db_path=db,
    )


class TestQueryTokenUsage:
    """Unit tests for db.query_token_usage() with dry_run field."""

    def test_returns_zero_on_empty(self, tmp_db):
        from core.db import query_token_usage
        result = query_token_usage("proj-no-calls", db_path=tmp_db)
        assert result["total"] == 0
        assert result["calls"] == 0
        assert result["dry_calls"] == 0
        assert result["live_calls"] == 0

    def test_counts_live_call(self, tmp_db):
        from core.db import query_token_usage
        _write_call(tmp_db, "proj-live", dry=False, prompt=100, completion=50)
        result = query_token_usage("proj-live", db_path=tmp_db)
        assert result["total"] == 150
        assert result["calls"] == 1
        assert result["live_calls"] == 1
        assert result["dry_calls"] == 0

    def test_counts_dry_call(self, tmp_db):
        from core.db import query_token_usage
        _write_call(tmp_db, "proj-dry", dry=True, prompt=0, completion=0)
        result = query_token_usage("proj-dry", db_path=tmp_db)
        assert result["total"] == 0
        assert result["calls"] == 1
        assert result["dry_calls"] == 1
        assert result["live_calls"] == 0

    def test_mixed_calls(self, tmp_db):
        from core.db import query_token_usage
        _write_call(tmp_db, "proj-mix", dry=False, prompt=200, completion=100)
        _write_call(tmp_db, "proj-mix", dry=True, prompt=0, completion=0)
        _write_call(tmp_db, "proj-mix", dry=False, prompt=300, completion=150)
        result = query_token_usage("proj-mix", db_path=tmp_db)
        assert result["calls"] == 3
        assert result["live_calls"] == 2
        assert result["dry_calls"] == 1
        assert result["total"] == 750

    def test_scoped_by_project(self, tmp_db):
        from core.db import query_token_usage
        _write_call(tmp_db, "proj-A", dry=False, prompt=100, completion=50)
        _write_call(tmp_db, "proj-B", dry=False, prompt=999, completion=999)
        result = query_token_usage("proj-A", db_path=tmp_db)
        assert result["total"] == 150
        assert result["calls"] == 1


class TestCliTokens:
    """Integration tests for `mas tokens` CLI command."""

    def test_tokens_requires_project(self, runner, tmp_path):
        result = runner.invoke(main, ["tokens", "proj-nonexistent-999"])
        assert result.exit_code != 0

    def test_tokens_output_format(self, runner, tmp_path, monkeypatch):
        # Patch projects dir and db path
        from core.engine.shared_state_manager import SharedStateManager
        sm = SharedStateManager.__new__(SharedStateManager)
        sm.project_id = "proj-tok-test"
        sm.project_dir = tmp_path / "projects" / "proj-tok-test"
        sm.project_dir.mkdir(parents=True)
        (sm.project_dir / "state.yaml").write_text("core_identity:\n  project_id: proj-tok-test\n")

        import core.cli as cli_mod
        monkeypatch.setattr(cli_mod, "_get_projects_dir", lambda: tmp_path / "projects")

        import core.db as db_mod
        tmp_db = tmp_path / "test.db"
        init_db(tmp_db)
        _write_call(tmp_db, "proj-tok-test", dry=False, prompt=100, completion=50)
        _write_call(tmp_db, "proj-tok-test", dry=True)
        orig = db_mod.query_token_usage

        def patched(project_id, db_path=None):
            return orig(project_id, db_path=tmp_db)

        monkeypatch.setattr(db_mod, "query_token_usage", patched)

        result = runner.invoke(main, ["tokens", "proj-tok-test"])
        assert result.exit_code == 0
        assert "proj-tok-test" in result.output
        assert "Total calls" in result.output
        assert "live:" in result.output
        assert "dry:" in result.output
