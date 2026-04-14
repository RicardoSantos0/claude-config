"""
Governance Tests — Append-Only Field Enforcement
Append-only fields must reject overwrite operations.
"""
import pytest
from core.engine.shared_state_manager import SharedStateManager


@pytest.fixture
def sm(tmp_path):
    manager = SharedStateManager("proj-ao-001", projects_root=tmp_path)
    manager.initialize(request_id="req-ao-001")
    return manager


APPEND_ONLY_FIELDS = [
    # (agent_id, section, field)
    ("master_orchestrator", "workflow",    "completed_phases"),
    ("hr_agent",            "workflow",    "resource_allocations"),
    ("scribe_agent",        "decisions",   "decision_log"),
    ("master_orchestrator", "decisions",   "approvals"),
    ("hr_agent",            "capability",  "capability_gap_certificates"),
    ("hr_agent",            "capability",  "spawn_requests"),
    ("spawner_agent",       "capability",  "spawned_agents"),
    ("evaluator_agent",     "capability",  "verification_results"),
    ("scribe_agent",        "artifacts",   "documents"),
    ("scribe_agent",        "artifacts",   "deliverables"),
    ("scribe_agent",        "artifacts",   "change_log"),
    ("evaluator_agent",     "evaluation",  "performance_metrics"),
    ("evaluator_agent",     "evaluation",  "quality_findings"),
    ("trainer_agent",       "evaluation",  "improvement_proposals"),
    ("master_orchestrator", "evaluation",  "approved_updates"),
    ("master_orchestrator", "consultation","consultation_requests"),
    ("master_orchestrator", "consultation","synthesis"),
]


@pytest.mark.parametrize("agent_id,section,field", APPEND_ONLY_FIELDS)
def test_write_to_append_only_field_is_blocked(sm, agent_id, section, field):
    """write() on an append-only field must return field_is_append_only."""
    result = sm.write(agent_id, section, field, [{"test": "value"}])
    assert not result.success, (
        f"write() should be blocked for append-only field {section}.{field}"
    )
    assert result.reason == "field_is_append_only"


@pytest.mark.parametrize("agent_id,section,field", APPEND_ONLY_FIELDS)
def test_append_to_append_only_field_succeeds(sm, agent_id, section, field):
    """append() on an append-only field must succeed for authorized agents."""
    item = {"test_id": "t-001", "value": "test"}
    result = sm.append(agent_id, section, field, item)
    assert result.success, (
        f"append() should succeed for {agent_id} on {section}.{field}: {result.reason}"
    )


def test_append_accumulates_without_overwriting(sm):
    """Multiple appends must accumulate — not reset the list."""
    for i in range(5):
        sm.append("master_orchestrator", "decisions", "approvals",
                  {"approval_id": f"ap-{i:03d}", "approved_by": "master_orchestrator"})

    val = sm.read("decisions.approvals")
    assert len(val) == 5


def test_handoff_history_is_append_only_via_system(sm):
    """workflow.handoff_history is system-owned append-only."""
    # write() must be blocked even by master
    result = sm.write("master_orchestrator", "workflow", "handoff_history", [])
    assert not result.success
    # system_append() must work
    result2 = sm.system_append("workflow", "handoff_history",
                               {"handoff_id": "ho-001"})
    assert result2.success


def test_any_agent_can_append_to_assumptions(sm):
    """decisions.assumptions allows any_agent to append."""
    for agent_id in ["master_orchestrator", "product_manager_agent",
                     "project_manager_agent", "evaluator_agent"]:
        result = sm.append(agent_id, "decisions", "assumptions",
                           {"assumption_id": f"a-{agent_id}", "stated_by": agent_id,
                            "description": "Test", "validated": False})
        assert result.success, f"{agent_id} should be able to append to decisions.assumptions"


def test_unauthorized_agent_cannot_append_to_restricted_field(sm):
    """Even for append, unauthorized agents are blocked."""
    result = sm.append("rogue_agent", "artifacts", "documents",
                       {"artifact_id": "hacked"})
    assert not result.success
    assert result.reason == "unauthorized_write"
