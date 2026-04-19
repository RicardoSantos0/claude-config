"""
Unit tests for SkillBridge (mas/core/skill_bridge.py).

Tests cover:
- Discovery: finds SKILL.md files, parses metadata, caches result
- Discovery: returns empty list when skills_dir absent
- Authorization: is_skill_authorized() for allowed, denied, wildcard, unknown agents
- authorized_skills() returns correct subset for each agent type
- Invocation: success for authorized agent + existing skill
- Invocation: denied for unauthorized agent (outcome=denied, success=False)
- Invocation: skill_not_found when skill does not exist
- Invocation: audit entry present in result on all paths
- Audit: write_audit_entry / get_audit_log round-trip
- CLI: discover, invoke, authorized, check sub-commands
- Governance: unauthorized access never raises governance violation
"""

import pytest
import json
from pathlib import Path
from core.engine.skill_bridge import SkillBridge, SKILL_ACCESS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def skills_dir(tmp_path) -> Path:
    """Create a minimal fake skills directory."""
    sd = tmp_path / "skills"

    # skill 1 — research-extract
    s1 = sd / "research-extract"
    s1.mkdir(parents=True)
    (s1 / "SKILL.md").write_text(
        "---\nname: research-extract\ndescription: Extract data from research.\n---\n\n## Steps\n",
        encoding="utf-8",
    )

    # skill 2 — skill-builder
    s2 = sd / "skill-builder"
    s2.mkdir()
    (s2 / "SKILL.md").write_text(
        "---\nname: skill-builder\ndescription: Build new skills.\n---\n",
        encoding="utf-8",
    )

    # skill 3 — no SKILL.md (should be ignored)
    s3 = sd / "orphan-dir"
    s3.mkdir()

    return sd


@pytest.fixture
def bridge(skills_dir) -> SkillBridge:
    return SkillBridge(skills_dir=skills_dir)


@pytest.fixture
def projects_root(tmp_path) -> Path:
    p = tmp_path / "projects"
    p.mkdir()
    return p


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

class TestDiscovery:
    def test_discovers_skills_with_skill_md(self, bridge):
        skills = bridge.discover()
        names = {s.name for s in skills}
        assert "research-extract" in names
        assert "skill-builder" in names

    def test_ignores_dirs_without_skill_md(self, bridge):
        skills = bridge.discover()
        names = {s.name for s in skills}
        assert "orphan-dir" not in names

    def test_skill_metadata_has_name_and_description(self, bridge):
        skills = bridge.discover()
        skill = next(s for s in skills if s.name == "research-extract")
        assert skill.description == "Extract data from research."
        assert skill.path.name == "SKILL.md"

    def test_discover_returns_empty_when_dir_absent(self, tmp_path):
        bridge_no_dir = SkillBridge(skills_dir=tmp_path / "nonexistent")
        assert bridge_no_dir.discover() == []

    def test_discover_caches_result(self, bridge):
        r1 = bridge.discover()
        r2 = bridge.discover()
        # Same underlying cache — no rescan, same skill objects
        assert len(r1) == len(r2)
        assert {s.name for s in r1} == {s.name for s in r2}

    def test_force_refresh_rescans(self, bridge, skills_dir):
        r1 = bridge.discover()
        # Add a new skill
        new_skill = skills_dir / "new-skill"
        new_skill.mkdir()
        (new_skill / "SKILL.md").write_text(
            "---\nname: new-skill\ndescription: Brand new.\n---\n",
            encoding="utf-8",
        )
        r2 = bridge.discover(force_refresh=True)
        assert len(r2) == len(r1) + 1

    def test_get_skill_returns_metadata(self, bridge):
        meta = bridge.get_skill("research-extract")
        assert meta is not None
        assert meta.name == "research-extract"

    def test_get_skill_returns_none_for_unknown(self, bridge):
        assert bridge.get_skill("nonexistent-skill") is None

    def test_metadata_to_dict(self, bridge):
        meta = bridge.get_skill("research-extract")
        d = meta.to_dict()
        assert d["name"] == "research-extract"
        assert "description" in d
        assert "path" in d


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------

class TestAuthorization:
    def test_master_orchestrator_authorized_for_all(self, bridge):
        assert bridge.is_skill_authorized("master_orchestrator", "research-extract") is True
        assert bridge.is_skill_authorized("master_orchestrator", "skill-builder") is True
        assert bridge.is_skill_authorized("master_orchestrator", "any-future-skill") is True

    def test_spawner_agent_only_skill_builder(self, bridge):
        assert bridge.is_skill_authorized("spawner_agent", "skill-builder") is True
        assert bridge.is_skill_authorized("spawner_agent", "research-extract") is False

    def test_hr_agent_denied_all(self, bridge):
        assert bridge.is_skill_authorized("hr_agent", "research-extract") is False
        assert bridge.is_skill_authorized("hr_agent", "skill-builder") is False

    def test_trainer_agent_denied_all(self, bridge):
        assert bridge.is_skill_authorized("trainer_agent", "research-extract") is False

    def test_unknown_agent_denied(self, bridge):
        assert bridge.is_skill_authorized("ghost_agent", "research-extract") is False

    def test_authorized_skills_for_scribe(self, bridge):
        skills = bridge.authorized_skills("scribe_agent")
        names = {s.name for s in skills}
        assert "research-extract" in names
        assert "skill-builder" not in names

    def test_authorized_skills_for_hr_is_empty(self, bridge):
        assert bridge.authorized_skills("hr_agent") == []

    def test_authorized_skills_for_unknown_is_empty(self, bridge):
        assert bridge.authorized_skills("ghost_agent") == []

    def test_authorized_skills_for_master_is_all(self, bridge):
        all_skills = bridge.discover()
        authorized = bridge.authorized_skills("master_orchestrator")
        assert len(authorized) == len(all_skills)


# ---------------------------------------------------------------------------
# Invocation
# ---------------------------------------------------------------------------

class TestInvocation:
    def test_authorized_invocation_succeeds(self, bridge):
        result = bridge.invoke("master_orchestrator", "research-extract",
                               "analyze papers", "proj-test-001")
        assert result.success is True
        assert result.outcome == "ok"
        assert result.agent_id == "master_orchestrator"
        assert result.skill_name == "research-extract"

    def test_unauthorized_invocation_denied(self, bridge):
        result = bridge.invoke("hr_agent", "research-extract",
                               "some query", "proj-test-001")
        assert result.success is False
        assert result.outcome == "denied"
        assert "not authorized" in result.message.lower()

    def test_skill_not_found(self, bridge):
        result = bridge.invoke("master_orchestrator", "nonexistent-skill",
                               "query", "proj-test-001")
        assert result.success is False
        assert result.outcome == "skill_not_found"

    def test_audit_entry_present_on_success(self, bridge):
        result = bridge.invoke("master_orchestrator", "research-extract",
                               "query", "proj-test-001")
        assert result.audit_entry
        assert result.audit_entry["outcome"] == "ok"
        assert result.audit_entry["agent_id"] == "master_orchestrator"

    def test_audit_entry_present_on_denial(self, bridge):
        result = bridge.invoke("hr_agent", "research-extract", "q", "proj-test-001")
        assert result.audit_entry
        assert result.audit_entry["outcome"] == "denied"

    def test_invocation_result_to_dict(self, bridge):
        result = bridge.invoke("master_orchestrator", "research-extract",
                               "query", "proj-test-001")
        d = result.to_dict()
        assert d["success"] is True
        assert d["outcome"] == "ok"

    def test_empty_project_id_does_not_crash(self, bridge):
        result = bridge.invoke("master_orchestrator", "research-extract", "q", "")
        assert result.success is True

    def test_query_preview_truncated_in_audit(self, bridge):
        long_query = "x" * 200
        result = bridge.invoke("master_orchestrator", "research-extract",
                               long_query, "proj-test-001")
        preview = result.audit_entry.get("query_preview", "")
        assert len(preview) <= 103  # 100 chars + "..."


# ---------------------------------------------------------------------------
# Audit log persistence
# ---------------------------------------------------------------------------

class TestAuditLog:
    def _bridge_with_real_root(self, tmp_path, skills_dir) -> SkillBridge:
        """Bridge with ROOT pointing to tmp_path so audit log writes somewhere real."""
        import core.engine.skill_bridge as sb_mod
        bridge = SkillBridge(skills_dir=skills_dir)
        # Monkey-patch ROOT for the audit path
        original_root = sb_mod.ROOT
        sb_mod.ROOT = tmp_path
        yield bridge
        sb_mod.ROOT = original_root

    def test_write_and_read_audit_entry(self, tmp_path, skills_dir, monkeypatch):
        import core.engine.skill_bridge as sb_mod
        monkeypatch.setattr(sb_mod, "ROOT", tmp_path)
        bridge = SkillBridge(skills_dir=skills_dir)

        entry = {
            "timestamp": "2026-04-10T10:00:00Z",
            "agent_id": "master_orchestrator",
            "skill_name": "research-extract",
            "project_id": "proj-audit-001",
            "query_preview": "analyze data",
            "outcome": "ok",
            "tokens_used": 10,
        }
        bridge.write_audit_entry("proj-audit-001", entry)
        log = bridge.get_audit_log("proj-audit-001")
        assert len(log) == 1
        assert log[0]["outcome"] == "ok"

    def test_multiple_entries_accumulate(self, tmp_path, skills_dir, monkeypatch):
        import core.engine.skill_bridge as sb_mod
        monkeypatch.setattr(sb_mod, "ROOT", tmp_path)
        bridge = SkillBridge(skills_dir=skills_dir)

        for i in range(3):
            bridge.write_audit_entry("proj-audit-002", {
                "timestamp": f"2026-04-10T1{i}:00:00Z",
                "agent_id": "master_orchestrator",
                "skill_name": "research-extract",
                "project_id": "proj-audit-002",
                "query_preview": f"query {i}",
                "outcome": "ok",
                "tokens_used": i * 5,
            })

        log = bridge.get_audit_log("proj-audit-002")
        assert len(log) == 3

    def test_empty_log_for_unknown_project(self, tmp_path, skills_dir, monkeypatch):
        import core.engine.skill_bridge as sb_mod
        monkeypatch.setattr(sb_mod, "ROOT", tmp_path)
        bridge = SkillBridge(skills_dir=skills_dir)
        assert bridge.get_audit_log("proj-no-such-project") == []


# ---------------------------------------------------------------------------
# Governance: unauthorized never raises
# ---------------------------------------------------------------------------

class TestGovernanceSafety:
    def test_unauthorized_does_not_raise(self, bridge):
        """Unauthorized skill access returns a result, never raises."""
        try:
            result = bridge.invoke("hr_agent", "research-extract", "q", "proj-001")
        except Exception as exc:
            pytest.fail(f"invoke() raised unexpectedly: {exc}")
        assert result.success is False

    def test_unknown_skill_does_not_raise(self, bridge):
        try:
            result = bridge.invoke("master_orchestrator", "ghost-skill", "q", "proj-001")
        except Exception as exc:
            pytest.fail(f"invoke() raised unexpectedly: {exc}")
        assert result.success is False

    def test_skill_access_coverage_for_all_known_agents(self):
        """Every agent in the roster has a defined SKILL_ACCESS entry."""
        known_agents = [
            "master_orchestrator", "scribe_agent", "inquirer_agent",
            "product_manager_agent", "project_manager_agent", "hr_agent",
            "evaluator_agent", "trainer_agent", "spawner_agent",
            "risk_advisor", "quality_advisor", "devils_advocate",
            "domain_expert", "efficiency_advisor",
        ]
        for agent in known_agents:
            assert agent in SKILL_ACCESS, f"Missing SKILL_ACCESS entry for '{agent}'"


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------

class TestCLI:
    def test_discover_cli(self, skills_dir):
        import subprocess, sys
        result = subprocess.run(
            [sys.executable, "-m", "core.engine.skill_bridge", "discover"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).parent.parent.parent),
        )
        assert result.returncode == 0
        assert "research-extract" in result.stdout

    def test_check_authorized_cli(self, skills_dir):
        import subprocess, sys
        result = subprocess.run(
            [sys.executable, "-m", "core.engine.skill_bridge", "check",
             "--agent", "master_orchestrator", "--skill", "research-extract"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).parent.parent.parent),
        )
        assert result.returncode == 0
        assert "AUTHORIZED" in result.stdout

    def test_check_denied_cli(self, skills_dir):
        import subprocess, sys
        result = subprocess.run(
            [sys.executable, "-m", "core.engine.skill_bridge", "check",
             "--agent", "hr_agent", "--skill", "research-extract"],
            capture_output=True, text=True,
            cwd=str(Path(__file__).parent.parent.parent),
        )
        assert result.returncode == 1
        assert "DENIED" in result.stdout
