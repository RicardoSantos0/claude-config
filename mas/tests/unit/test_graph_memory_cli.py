"""
CLI smoke tests for graph_memory.py.

Tests cover:
- stats command: returns valid JSON with expected keys
- query command: returns JSON with facts list
- episodes command: lists nodes
- All commands exit 0 on a fresh project
"""

import subprocess
import sys
import json
from pathlib import Path
import pytest


MAS_ROOT = Path(__file__).parent.parent.parent   # mas/


@pytest.fixture(autouse=True)
def patch_root(tmp_path, monkeypatch):
    import core.graph_memory as gm_mod
    monkeypatch.setattr(gm_mod, "ROOT", tmp_path)
    return tmp_path


def _run(args: list[str], cwd=MAS_ROOT) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "core.graph_memory"] + args,
        capture_output=True, text=True, cwd=str(cwd),
    )


class TestGraphMemoryCLI:
    def test_stats_exits_0(self):
        result = _run(["stats", "--project-id", "proj-cli-001"])
        assert result.returncode == 0

    def test_stats_returns_json_with_keys(self):
        result = _run(["stats", "--project-id", "proj-cli-001"])
        data = json.loads(result.stdout)
        assert "node_count" in data
        assert "edge_count" in data
        assert "networkx_available" in data

    def test_query_exits_0(self):
        result = _run(["query", "--project-id", "proj-cli-001",
                       "--agent", "master_orchestrator"])
        assert result.returncode == 0

    def test_query_returns_json(self):
        result = _run(["query", "--project-id", "proj-cli-001",
                       "--agent", "master_orchestrator", "--context", "intake"])
        data = json.loads(result.stdout)
        assert "facts" in data
        assert "agent_id" in data
        assert data["agent_id"] == "master_orchestrator"

    def test_episodes_exits_0(self):
        result = _run(["episodes", "--project-id", "proj-cli-001"])
        assert result.returncode == 0

    def test_no_command_exits_nonzero(self):
        result = _run([])
        assert result.returncode != 0

    def test_stats_node_count_after_write(self):
        """Write a graph YAML directly to the CLI's project dir, verify stats."""
        import shutil, yaml as _yaml

        project_dir = MAS_ROOT / "projects" / "proj-cli-stats-002"
        graph_file = project_dir / "graph_memory.yaml"
        project_dir.mkdir(parents=True, exist_ok=True)

        data = {
            "project_id": "proj-cli-stats-002",
            "nodes": [
                {"id": "master_orchestrator", "entity_type": "agent", "label": "master_orchestrator"},
                {"id": "scribe_agent", "entity_type": "agent", "label": "scribe_agent"},
            ],
            "edges": [
                {"source": "master_orchestrator", "target": "scribe_agent", "rel_type": "handoff_to"},
            ],
        }
        with graph_file.open("w") as f:
            _yaml.dump(data, f)

        try:
            result = _run(["stats", "--project-id", "proj-cli-stats-002"])
            assert result.returncode == 0
            out = json.loads(result.stdout)
            assert out["node_count"] >= 2
        finally:
            shutil.rmtree(str(project_dir), ignore_errors=True)
