"""
Tests for librarian_agent spawn output (D5).
AC8: librarian_agent.md exists with correct frontmatter.
AC9: librarian_agent registered in registry_index.yaml.
"""

import yaml
from pathlib import Path

import pytest

AGENTS_DIR = Path(__file__).parents[3] / "agents"
ROSTER_PATH = Path(__file__).parents[2] / "roster" / "registry_index.yaml"
LIBRARIAN_MD = AGENTS_DIR / "librarian_agent.md"


class TestLibrarianAgentFile:
    """AC8: librarian_agent.md exists with correct structure."""

    def test_file_exists(self):
        assert LIBRARIAN_MD.exists(), "agents/librarian_agent.md must exist"

    def test_frontmatter_name(self):
        content = LIBRARIAN_MD.read_text(encoding="utf-8")
        # Parse YAML frontmatter between first pair of ---
        lines = content.split("\n")
        assert lines[0].strip() == "---"
        end = next(i for i, l in enumerate(lines[1:], 1) if l.strip() == "---")
        fm = yaml.safe_load("\n".join(lines[1:end]))
        assert fm.get("name") == "librarian_agent"

    def test_frontmatter_description_mentions_db(self):
        content = LIBRARIAN_MD.read_text(encoding="utf-8")
        lines = content.split("\n")
        end = next(i for i, l in enumerate(lines[1:], 1) if l.strip() == "---")
        fm = yaml.safe_load("\n".join(lines[1:end]))
        desc = fm.get("description", "").lower()
        assert "db" in desc or "database" in desc

    def test_frontmatter_not_user_invocable(self):
        content = LIBRARIAN_MD.read_text(encoding="utf-8")
        lines = content.split("\n")
        end = next(i for i, l in enumerate(lines[1:], 1) if l.strip() == "---")
        fm = yaml.safe_load("\n".join(lines[1:end]))
        assert fm.get("user-invocable") is False

    def test_body_mentions_trust_tier(self):
        content = LIBRARIAN_MD.read_text(encoding="utf-8")
        assert "T2" in content or "supervised" in content.lower()

    def test_body_mentions_gap_cert(self):
        content = LIBRARIAN_MD.read_text(encoding="utf-8")
        assert "gap-proj-20260415-002-001" in content

    def test_body_mentions_db_operations(self):
        content = LIBRARIAN_MD.read_text(encoding="utf-8")
        assert "db_operations" in content or "db operations" in content.lower()

    def test_body_mentions_mas_db_commands(self):
        content = LIBRARIAN_MD.read_text(encoding="utf-8")
        assert "mas db rebuild-fts" in content or "rebuild-fts" in content

    def test_body_mentions_wire_format(self):
        content = LIBRARIAN_MD.read_text(encoding="utf-8")
        assert "wire" in content.lower() or "_v" in content


class TestLibrarianAgentRegistry:
    """AC9: librarian_agent is registered in registry_index.yaml."""

    def _load_registry(self):
        with open(ROSTER_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f)

    def test_librarian_in_registry(self):
        data = self._load_registry()
        agents = data["registry"]["agents"]
        ids = [a["agent_id"] for a in agents]
        assert "librarian_agent" in ids

    def test_librarian_trust_tier(self):
        data = self._load_registry()
        agents = data["registry"]["agents"]
        lib = next(a for a in agents if a["agent_id"] == "librarian_agent")
        assert lib["trust_tier"] == "T2_supervised"

    def test_librarian_has_gap_cert(self):
        data = self._load_registry()
        agents = data["registry"]["agents"]
        lib = next(a for a in agents if a["agent_id"] == "librarian_agent")
        assert lib.get("gap_cert") == "gap-proj-20260415-002-001"

    def test_librarian_has_db_ops_capability(self):
        data = self._load_registry()
        agents = data["registry"]["agents"]
        lib = next(a for a in agents if a["agent_id"] == "librarian_agent")
        caps = lib.get("capabilities", [])
        assert "db_operations" in caps

    def test_spawned_total_incremented(self):
        data = self._load_registry()
        assert data["counts"]["spawned_total"] >= 1

    def test_active_agents_count_updated(self):
        data = self._load_registry()
        agents = data["registry"]["agents"]
        active = [a for a in agents if a.get("status") == "active"]
        assert data["counts"]["active_agents"] == len(active)
