"""
Phase 0 Tests — Directory Structure Verification
Verifies that all required directories and files exist.
"""
import pytest
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent


def test_required_directories_exist():
    required_dirs = [
        "roster",
        "roster/agents",
        "roster/skills",
        "roster/tools",
        "roster/trust_tiers",
        "policies",
        "templates",
        "projects",
        "foundation",
        "agents",
        "core",
        "tests",
        "tests/unit",
        "tests/governance",
        "tests/integration",
        "tests/prompts",
        "domains",
    ]
    for d in required_dirs:
        assert (ROOT / d).is_dir(), f"Missing directory: {d}"


def test_required_foundation_files_exist():
    required = [
        "foundation/memory_types.yaml",
        "foundation/shared_state_schema.yaml",
        "foundation/handoff_protocol.yaml",
        "foundation/folder_structure.yaml",
    ]
    for f in required:
        assert (ROOT / f).is_file(), f"Missing foundation file: {f}"


def test_required_policy_files_exist():
    required = [
        "policies/spawn_policy.yaml",
        "policies/governance_policy.yaml",
        "policies/trust_tier_policy.yaml",
        "policies/evaluation_policy.yaml",
        "policies/training_policy.yaml",
        "policies/handoff_protocol.yaml",
    ]
    for f in required:
        assert (ROOT / f).is_file(), f"Missing policy file: {f}"


def test_required_template_files_exist():
    required = [
        "templates/project_spec_template.yaml",
        "templates/capability_gap_certificate_template.yaml",
        "templates/spawn_request_template.yaml",
        "templates/evaluation_report_template.yaml",
        "templates/handoff_template.yaml",
        "templates/consultation_request_template.yaml",
    ]
    for f in required:
        assert (ROOT / f).is_file(), f"Missing template file: {f}"


def test_system_config_exists():
    assert (ROOT / "system_config.yaml").is_file()


def test_pyproject_toml_exists():
    assert (ROOT / "pyproject.toml").is_file()


def test_roster_files_exist():
    required = [
        "roster/registry_index.yaml",
        "roster/version_history.yaml",
        "roster/trust_tiers/tier_definitions.yaml",
    ]
    for f in required:
        assert (ROOT / f).is_file(), f"Missing roster file: {f}"


def test_env_example_exists():
    assert (ROOT / ".env.example").is_file()


def test_gitignore_covers_env():
    gitignore = (ROOT / ".gitignore").read_text()
    assert ".env" in gitignore


def test_gitignore_covers_projects():
    gitignore = (ROOT / ".gitignore").read_text()
    assert "projects/" in gitignore
