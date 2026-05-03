"""Tests for scripts/validate_skills.py."""

from __future__ import annotations

import importlib.util
import textwrap
from pathlib import Path

import pytest
import yaml


def _load_module(repo_root: Path | None = None):
    if repo_root is None:
        repo_root = Path(__file__).resolve().parents[3]
    script = repo_root / "scripts" / "validate_skills.py"
    spec = importlib.util.spec_from_file_location("validate_skills", script)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _skill_md(name: str, description: str = "A skill.") -> str:
    return textwrap.dedent(f"""\
        ---
        name: {name}
        description: {description}
        ---
        # {name}
        Skill body.
    """)


def _make_registry_index(skills: list[dict]) -> dict:
    return {"skills": skills, "counts": {"active_skills": len(skills)}}


def _make_registry_canonical(agents: list[str]) -> dict:
    return {"agents": {a: {"file": f"agents/{a}.md"} for a in agents}}


# ---------------------------------------------------------------------------
# Check 1: SKILL.md existence and valid frontmatter
# ---------------------------------------------------------------------------

def test_passes_on_clean_repo(monkeypatch):
    """validate_skills exits 0 on the actual current repo."""
    import sys
    repo_root = Path(__file__).resolve().parents[3]
    monkeypatch.setattr(sys, "argv", ["validate_skills.py", "--repo-root", str(repo_root)])
    mod = _load_module()
    result = mod.main()
    assert result == 0


def test_skill_dir_missing_skill_md(tmp_path):
    """Skill directory without SKILL.md is an error."""
    mod = _load_module()
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    (skills_dir / "my-skill").mkdir()  # no SKILL.md

    registry_idx = tmp_path / "mas" / "roster" / "registry_index.yaml"
    registry_idx.parent.mkdir(parents=True)
    registry_idx.write_text(yaml.dump(_make_registry_index([])), encoding="utf-8")

    canonical = tmp_path / "mas" / "roster" / "registry_canonical.yaml"
    canonical.write_text(yaml.dump(_make_registry_canonical([])), encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")

    errors = _collect_errors(mod, tmp_path)
    assert any("SKILL.MD_MISSING" in e for e in errors)


def test_skill_md_missing_frontmatter(tmp_path):
    """SKILL.md without frontmatter delimiter is flagged."""
    mod = _load_module()
    skills_dir = tmp_path / "skills" / "bad-skill"
    skills_dir.mkdir(parents=True)
    (skills_dir / "SKILL.md").write_text("No frontmatter here.\n", encoding="utf-8")

    _write_empty_registries(tmp_path)
    errors = _collect_errors(mod, tmp_path)
    assert any("FRONTMATTER_INVALID" in e for e in errors)


# ---------------------------------------------------------------------------
# Check 2: Active registry skill exists on disk
# ---------------------------------------------------------------------------

def test_registry_skill_missing_on_disk(tmp_path):
    """Active registry skill with no SKILL.md on disk is flagged."""
    mod = _load_module()
    (tmp_path / "skills").mkdir()
    skills = [{"skill_id": "ghost-skill", "status": "active", "category": "workflow",
               "trigger_phases": ["intake"], "recommended_for": []}]
    _write_registries(tmp_path, skills, [])
    errors = _collect_errors(mod, tmp_path)
    assert any("REGISTRY_SKILL_MISSING_ON_DISK" in e and "ghost-skill" in e for e in errors)


def test_inactive_registry_skill_not_checked(tmp_path):
    """Inactive registry skill does not trigger disk check."""
    mod = _load_module()
    (tmp_path / "skills").mkdir()
    skills = [{"skill_id": "old-skill", "status": "inactive", "category": "workflow",
               "trigger_phases": ["intake"], "recommended_for": []}]
    _write_registries(tmp_path, skills, [])
    errors = _collect_errors(mod, tmp_path)
    assert not any("REGISTRY_SKILL_MISSING_ON_DISK" in e for e in errors)


# ---------------------------------------------------------------------------
# Check 3: Workflow skills have trigger_phases
# ---------------------------------------------------------------------------

def test_workflow_skill_no_trigger_phases(tmp_path):
    """Workflow skill without trigger_phases is flagged."""
    mod = _load_module()
    skills_dir = tmp_path / "skills" / "wf-skill"
    skills_dir.mkdir(parents=True)
    (skills_dir / "SKILL.md").write_text(_skill_md("wf-skill"), encoding="utf-8")
    skills = [{"skill_id": "wf-skill", "status": "active", "category": "workflow",
               "recommended_for": []}]
    _write_registries(tmp_path, skills, [])
    errors = _collect_errors(mod, tmp_path)
    assert any("WORKFLOW_SKILL_NO_TRIGGER_PHASES" in e for e in errors)


def test_non_workflow_skill_no_trigger_phases_ok(tmp_path):
    """Non-workflow skill without trigger_phases is not flagged."""
    mod = _load_module()
    skills_dir = tmp_path / "skills" / "tool-skill"
    skills_dir.mkdir(parents=True)
    (skills_dir / "SKILL.md").write_text(_skill_md("tool-skill"), encoding="utf-8")
    skills = [{"skill_id": "tool-skill", "status": "active", "category": "tool",
               "recommended_for": []}]
    _write_registries(tmp_path, skills, [])
    errors = _collect_errors(mod, tmp_path)
    assert not any("WORKFLOW_SKILL_NO_TRIGGER_PHASES" in e for e in errors)


# ---------------------------------------------------------------------------
# Check 4: recommended_for agents exist in canonical registry
# ---------------------------------------------------------------------------

def test_recommended_for_unknown_agent(tmp_path):
    """Skill recommended_for a non-existent agent is flagged."""
    mod = _load_module()
    skills_dir = tmp_path / "skills" / "my-skill"
    skills_dir.mkdir(parents=True)
    (skills_dir / "SKILL.md").write_text(_skill_md("my-skill"), encoding="utf-8")
    skills = [{"skill_id": "my-skill", "status": "active", "category": "workflow",
               "trigger_phases": ["intake"], "recommended_for": ["ghost_agent"]}]
    _write_registries(tmp_path, skills, agents=[])
    errors = _collect_errors(mod, tmp_path)
    assert any("RECOMMENDED_FOR_UNKNOWN_AGENT" in e and "ghost_agent" in e for e in errors)


def test_recommended_for_known_agent_ok(tmp_path):
    """Skill recommended_for a known agent passes."""
    mod = _load_module()
    skills_dir = tmp_path / "skills" / "my-skill"
    skills_dir.mkdir(parents=True)
    (skills_dir / "SKILL.md").write_text(_skill_md("my-skill"), encoding="utf-8")
    skills = [{"skill_id": "my-skill", "status": "active", "category": "workflow",
               "trigger_phases": ["intake"], "recommended_for": ["master_orchestrator"]}]
    _write_registries(tmp_path, skills, agents=["master_orchestrator"])
    errors = _collect_errors(mod, tmp_path)
    assert not any("RECOMMENDED_FOR_UNKNOWN_AGENT" in e for e in errors)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _collect_errors(mod, tmp_path: Path) -> list[str]:
    """Run main with argv pointing to tmp_path; return printed lines."""
    import sys
    from io import StringIO
    old_argv = sys.argv
    old_stdout = sys.stdout
    sys.argv = ["validate_skills.py", "--repo-root", str(tmp_path)]
    sys.stdout = buf = StringIO()
    try:
        mod.main()
    except SystemExit:
        pass
    finally:
        sys.argv = old_argv
        sys.stdout = old_stdout
    return buf.getvalue().splitlines()


def _write_empty_registries(tmp_path: Path) -> None:
    _write_registries(tmp_path, [], [])


def _write_registries(tmp_path: Path, skills: list[dict], agents: list[str]) -> None:
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")
    roster = tmp_path / "mas" / "roster"
    roster.mkdir(parents=True, exist_ok=True)
    (roster / "registry_index.yaml").write_text(
        yaml.dump(_make_registry_index(skills)), encoding="utf-8"
    )
    (roster / "registry_canonical.yaml").write_text(
        yaml.dump(_make_registry_canonical(agents)), encoding="utf-8"
    )
