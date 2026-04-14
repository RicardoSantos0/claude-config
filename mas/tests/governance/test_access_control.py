"""
Governance Tests — Access Control
Every agent must be blocked from writing fields it does not own.
This is the most critical test suite in the system.
"""
import pytest
from core.engine.shared_state_manager import SharedStateManager
from core.engine.access_control import ACCESS_CONTROL, CONSULTANT_AGENTS


# All defined agents in the system
ALL_AGENTS = [
    "master_orchestrator",
    "inquirer_agent",
    "product_manager_agent",
    "project_manager_agent",
    "hr_agent",
    "scribe_agent",
    "evaluator_agent",
    "trainer_agent",
    "spawner_agent",
    "risk_advisor",
    "quality_advisor",
    "devils_advocate",
    "domain_expert",
    "efficiency_advisor",
    "rogue_agent",      # Completely unauthorized agent
]

# Fields where writes should be DENIED for agents that don't own them
DENY_CASES = [
    # (agent_id, section, field) — agent must NOT be allowed to write this
    ("inquirer_agent",     "core_identity",     "current_phase"),
    ("inquirer_agent",     "workflow",          "active_agents"),
    ("product_manager_agent", "decisions",      "decision_log"),
    ("project_manager_agent", "artifacts",      "documents"),
    ("hr_agent",           "core_identity",     "status"),
    ("scribe_agent",       "capability",        "spawn_requests"),
    ("scribe_agent",       "workflow",          "active_agents"),
    ("evaluator_agent",    "workflow",          "current_owner"),
    ("trainer_agent",      "evaluation",        "performance_metrics"),
    ("spawner_agent",      "consultation",      "consultation_requests"),
    ("risk_advisor",       "workflow",          "active_agents"),
    ("rogue_agent",        "core_identity",     "project_id"),
    ("rogue_agent",        "workflow",          "handoff_history"),
    ("rogue_agent",        "decisions",         "decision_log"),
]

# Fields where writes should be ALLOWED for their authorized agents
ALLOW_CASES = [
    # (agent_id, section, field, value)
    ("master_orchestrator",   "core_identity",    "current_phase",  "planning"),
    ("master_orchestrator",   "core_identity",    "status",         "paused"),
    ("master_orchestrator",   "workflow",         "current_owner",  "scribe_agent"),
    ("inquirer_agent",        "project_definition", "original_brief", "Test brief"),
    ("product_manager_agent", "project_definition", "project_goal", "Build X"),
    ("hr_agent",              "capability",       "available_skills_snapshot", []),
    ("scribe_agent",          "decisions",        "decision_log",   []),  # append-only → write denied
    ("evaluator_agent",       "evaluation",       "performance_metrics", []),
    ("trainer_agent",         "evaluation",       "improvement_proposals", []),
]


@pytest.fixture
def sm(tmp_path):
    manager = SharedStateManager("proj-gov-001", projects_root=tmp_path)
    manager.initialize(request_id="req-gov-001")
    return manager


@pytest.mark.parametrize("agent_id,section,field", DENY_CASES)
def test_unauthorized_write_is_blocked(sm, agent_id, section, field):
    """Any agent attempting to write a field it doesn't own must be denied."""
    result = sm.write(agent_id, section, field, "unauthorized_value")
    assert not result.success, (
        f"{agent_id} should NOT be able to write {section}.{field}"
    )
    assert result.reason == "unauthorized_write"


@pytest.mark.parametrize("agent_id,section,field,value", ALLOW_CASES)
def test_authorized_write_is_permitted_or_append_only(sm, agent_id, section, field, value):
    """
    Authorized agents must succeed on write, UNLESS the field is append-only
    (in which case write is denied and append must be used instead).
    """
    from core.engine.access_control import requires_append_only
    field_path = f"{section}.{field}"
    if requires_append_only(field_path):
        # append-only fields must reject write() but accept append()
        result = sm.write(agent_id, section, field, value)
        assert not result.success
        assert result.reason == "field_is_append_only"
    else:
        result = sm.write(agent_id, section, field, value)
        assert result.success, (
            f"{agent_id} SHOULD be able to write {section}.{field}: {result.reason}"
        )


def test_governance_violation_is_recorded(sm):
    """Violations must be recorded in _meta.governance_violations."""
    sm.write("rogue_agent", "core_identity", "project_id", "hacked")
    count = sm.get_violation_count("rogue_agent")
    assert count >= 1


def test_every_field_path_is_in_access_control():
    """All sections in the schema must have access control entries."""
    sections_with_entries = set(k.split(".")[0] for k in ACCESS_CONTROL.keys())
    expected_sections = {
        "core_identity", "project_definition", "workflow", "decisions",
        "capability", "artifacts", "evaluation", "consultation",
    }
    for section in expected_sections:
        assert section in sections_with_entries, (
            f"Section '{section}' has no access control entries"
        )


def test_consultant_agents_can_write_consultation_responses(sm):
    """All consultant agents must be able to append consultation responses."""
    for consultant in CONSULTANT_AGENTS:
        response = {"consultant_id": consultant, "response": "Test response",
                    "word_count": 3, "responded_at": "2026-04-09T00:00:00Z"}
        result = sm.append(consultant, "consultation", "consultation_responses", response)
        assert result.success, (
            f"{consultant} should be able to write consultation.consultation_responses"
        )


def test_non_consultant_cannot_write_consultation_responses(sm):
    """Non-consultant agents must not write consultation responses."""
    result = sm.write("project_manager_agent", "consultation",
                      "consultation_responses", [])
    assert not result.success
