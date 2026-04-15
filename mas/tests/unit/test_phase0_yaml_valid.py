"""
Phase 0 Tests — YAML Validation
Verifies that all YAML files parse without errors and have required fields.
"""
import pytest
import yaml
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent


def load_yaml(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def all_yaml_files():
    """Collect all YAML files in foundation, policies, templates, roster, root."""
    paths = []
    for directory in ["foundation", "policies", "templates", "roster"]:
        paths.extend((ROOT / directory).rglob("*.yaml"))
    paths.append(ROOT / "system_config.yaml")
    return paths


@pytest.mark.parametrize("yaml_path", all_yaml_files(), ids=lambda p: str(p.relative_to(ROOT)))
def test_yaml_parses_without_error(yaml_path):
    """Every YAML file must parse cleanly."""
    data = load_yaml(yaml_path)
    assert data is not None, f"{yaml_path} parsed as empty/null"


def test_system_config_required_fields():
    config = load_yaml(ROOT / "system_config.yaml")
    assert "system" in config
    assert "paths" in config
    assert "defaults" in config
    assert "llm" in config
    assert "trust_tiers" in config
    assert "audit" in config


def test_system_config_models():
    config = load_yaml(ROOT / "system_config.yaml")
    llm = config["llm"]
    assert "master_model" in llm, "master_model must be defined"
    assert "default_model" in llm, "default_model must be defined"
    assert llm["master_model"] == "claude-opus-4-6"
    assert llm["default_model"] == "claude-sonnet-4-6"


def test_system_config_paths():
    config = load_yaml(ROOT / "system_config.yaml")
    required_paths = ["root", "roster", "policies", "templates", "projects",
                      "foundation", "agents", "core", "tests", "audit_log", "domains"]
    for p in required_paths:
        assert p in config["paths"], f"Missing path config: {p}"


def test_handoff_protocol_has_required_fields():
    data = load_yaml(ROOT / "policies/handoff_protocol.yaml")
    assert "handoff_protocol" in data
    protocol = data["handoff_protocol"]
    assert "handoff_record" in protocol
    assert "rules" in protocol


def test_memory_types_has_three_types():
    data = load_yaml(ROOT / "foundation/memory_types.yaml")
    assert "memory_types" in data
    types = data["memory_types"]
    assert "working_state" in types
    assert "project_memory" in types
    assert "roster_memory" in types


def test_shared_state_schema_has_sections():
    data = load_yaml(ROOT / "foundation/shared_state_schema.yaml")
    assert "shared_state" in data
    state = data["shared_state"]
    required_sections = [
        "core_identity", "project_definition", "workflow",
        "decisions", "capability", "artifacts", "evaluation", "consultation"
    ]
    for section in required_sections:
        assert section in state, f"Missing shared_state section: {section}"


def test_spawn_policy_has_limits():
    data = load_yaml(ROOT / "policies/spawn_policy.yaml")
    assert "spawn_policy" in data
    policy = data["spawn_policy"]
    assert "limits" in policy
    limits = policy["limits"]
    assert limits["max_spawns_per_project"] == 3
    assert limits["recursive_spawn_allowed"] is False


def test_trust_tier_policy_has_all_tiers():
    data = load_yaml(ROOT / "policies/trust_tier_policy.yaml")
    assert "trust_tier_policy" in data
    tiers = data["trust_tier_policy"]["tiers"]
    assert "T0_core" in tiers
    assert "T1_established" in tiers
    assert "T2_supervised" in tiers
    assert "T3_provisional" in tiers


def test_handoff_template_has_acceptance():
    data = load_yaml(ROOT / "templates/handoff_template.yaml")
    assert "handoff" in data
    h = data["handoff"]
    assert "payload" in h
    assert "acceptance" in h
    assert h["acceptance"]["status"] == "pending"


def test_registry_index_has_agents_and_skills():
    data = load_yaml(ROOT / "roster/registry_index.yaml")
    assert "registry" in data
    assert "agents" in data["registry"]
    assert "skills" in data["registry"]


def test_tier_definitions_has_core_agents():
    data = load_yaml(ROOT / "roster/trust_tiers/tier_definitions.yaml")
    assert "tier_assignments" in data
    t0 = data["tier_assignments"]["T0_core"]
    assert "master_orchestrator" in t0
    assert "hr_agent" in t0
    assert "scribe_agent" in t0
