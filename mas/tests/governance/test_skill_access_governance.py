"""
Governance tests for Skill Bridge access control.

Key governance rules:
  - Unauthorized skill access → audit log entry with outcome="denied"
  - Unauthorized skill access is NEVER a governance violation in shared state
  - Skill access denied silently — invoke() returns success=False, never raises
  - Authorized access logs outcome="ok" in audit
  - Unknown agent is always denied

These tests verify the governance boundary behavior, not functional correctness
(that is covered by test_skill_bridge.py).
"""

import pytest
from pathlib import Path
from core.skill_bridge import SkillBridge, SKILL_ACCESS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def skills_dir(tmp_path) -> Path:
    sd = tmp_path / "skills"
    s1 = sd / "research-extract"
    s1.mkdir(parents=True)
    (s1 / "SKILL.md").write_text(
        "---\nname: research-extract\ndescription: Extract research data.\n---\n",
        encoding="utf-8",
    )
    s2 = sd / "skill-builder"
    s2.mkdir()
    (s2 / "SKILL.md").write_text(
        "---\nname: skill-builder\ndescription: Build skills.\n---\n",
        encoding="utf-8",
    )
    return sd


@pytest.fixture
def bridge(skills_dir) -> SkillBridge:
    return SkillBridge(skills_dir=skills_dir)


# ---------------------------------------------------------------------------
# Unauthorized access never raises, always denied
# ---------------------------------------------------------------------------

class TestUnauthorizedAccessNeverRaises:
    def test_hr_denied_silently(self, bridge):
        result = bridge.invoke("hr_agent", "research-extract", "query", "proj-gov-001")
        assert result.success is False
        assert result.outcome == "denied"

    def test_trainer_denied_silently(self, bridge):
        result = bridge.invoke("trainer_agent", "skill-builder", "query", "proj-gov-001")
        assert result.success is False
        assert result.outcome == "denied"

    def test_unknown_agent_denied(self, bridge):
        result = bridge.invoke("unknown_agent", "research-extract", "query", "proj-gov-001")
        assert result.success is False
        assert result.outcome == "denied"

    def test_denied_invoke_does_not_raise(self, bridge):
        try:
            bridge.invoke("hr_agent", "research-extract", "q", "proj-gov-001")
        except Exception as exc:
            pytest.fail(f"invoke() raised unexpectedly on denial: {exc}")

    def test_denied_result_has_audit_entry(self, bridge):
        result = bridge.invoke("hr_agent", "research-extract", "q", "proj-gov-001")
        assert result.audit_entry
        assert result.audit_entry["outcome"] == "denied"
        assert result.audit_entry["agent_id"] == "hr_agent"

    def test_spawner_denied_research_extract(self, bridge):
        """spawner_agent is only authorized for skill-builder, not research-extract."""
        result = bridge.invoke("spawner_agent", "research-extract", "q", "proj-gov-001")
        assert result.success is False
        assert result.outcome == "denied"


# ---------------------------------------------------------------------------
# Unauthorized access is NOT a governance violation in shared state
# ---------------------------------------------------------------------------

class TestUnauthorizedNotGovernanceViolation:
    def test_denial_produces_no_governance_violation(self, tmp_path, skills_dir, monkeypatch):
        """
        Skill access denial must not write to shared_state governance_violations.
        The skill bridge is a tool layer — not a state governance boundary.
        """
        import core.skill_bridge as sb_mod
        monkeypatch.setattr(sb_mod, "ROOT", tmp_path)
        bridge = SkillBridge(skills_dir=skills_dir)

        # Do 3 unauthorized invocations
        for _ in range(3):
            bridge.invoke("hr_agent", "research-extract", "q", "proj-gov-001")

        # No shared state is written at all for unauthorized skill access
        state_path = tmp_path / "projects" / "proj-gov-001" / "shared_state.yaml"
        assert not state_path.exists(), (
            "Skill bridge must not write shared_state for unauthorized access"
        )

    def test_audit_log_written_for_denial(self, tmp_path, skills_dir, monkeypatch):
        """Denied invocations ARE logged in skill_audit_log.yaml, not shared_state."""
        import core.skill_bridge as sb_mod
        monkeypatch.setattr(sb_mod, "ROOT", tmp_path)
        bridge = SkillBridge(skills_dir=skills_dir)

        result = bridge.invoke("hr_agent", "research-extract", "q", "proj-gov-002")
        # Manually write the audit entry (bridge.invoke doesn't auto-write — caller does)
        if result.audit_entry:
            bridge.write_audit_entry("proj-gov-002", result.audit_entry)

        log = bridge.get_audit_log("proj-gov-002")
        assert len(log) >= 1
        assert log[0]["outcome"] == "denied"


# ---------------------------------------------------------------------------
# Authorized access produces ok audit entry
# ---------------------------------------------------------------------------

class TestAuthorizedAccessAudit:
    def test_authorized_invocation_outcome_ok(self, bridge):
        result = bridge.invoke("master_orchestrator", "research-extract",
                               "analyze papers", "proj-gov-003")
        assert result.success is True
        assert result.audit_entry["outcome"] == "ok"

    def test_audit_entry_includes_tokens(self, bridge):
        result = bridge.invoke("master_orchestrator", "research-extract",
                               "analyze papers about AI", "proj-gov-003")
        assert "tokens_used" in result.audit_entry
        assert isinstance(result.audit_entry["tokens_used"], int)

    def test_audit_includes_skill_and_agent(self, bridge):
        result = bridge.invoke("master_orchestrator", "research-extract",
                               "query", "proj-gov-003")
        assert result.audit_entry["skill_name"] == "research-extract"
        assert result.audit_entry["agent_id"] == "master_orchestrator"


# ---------------------------------------------------------------------------
# All agents have defined access rules (coverage completeness)
# ---------------------------------------------------------------------------

class TestAccessRuleCoverage:
    ROSTER = [
        "master_orchestrator", "scribe_agent", "inquirer_agent",
        "product_manager_agent", "project_manager_agent", "hr_agent",
        "evaluator_agent", "trainer_agent", "spawner_agent",
        "risk_advisor", "quality_advisor", "devils_advocate",
        "domain_expert", "efficiency_advisor",
    ]

    def test_all_roster_agents_have_skill_access_rules(self):
        for agent in self.ROSTER:
            assert agent in SKILL_ACCESS, (
                f"Agent '{agent}' missing from SKILL_ACCESS — "
                "add an entry (can be empty list [])"
            )

    def test_no_agent_grants_access_to_nonexistent_skill(self):
        """All explicit skill names in SKILL_ACCESS should match known skill dirs."""
        known_skills = {"research-extract", "research-sync", "notebooklm",
                        "frontend-design", "skill-builder"}  # real skills in repo
        for agent, allowed in SKILL_ACCESS.items():
            for skill in allowed:
                if skill == "*":
                    continue
                assert skill in known_skills, (
                    f"Agent '{agent}' references unknown skill '{skill}' in SKILL_ACCESS"
                )
