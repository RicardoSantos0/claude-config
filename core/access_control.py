"""
Access Control Matrix
Defines which agents can write which shared state fields,
and what mutability rules apply.

Enforced by SharedStateManager on every write attempt.
"""

# --- AGENT GROUPS ---
CONSULTANT_AGENTS = frozenset({
    "risk_advisor", "quality_advisor", "devils_advocate",
    "domain_expert", "efficiency_advisor",
})

ANY_AGENT = "__any__"   # sentinel: all agents may write
SYSTEM    = "system"    # sentinel: internal system writes only


def _any(*agents: str) -> list:
    return list(agents)


# --- ACCESS CONTROL MATRIX ---
# Key format: "section.field"
# Values:
#   write:      list of agent_ids allowed to write (or [ANY_AGENT])
#   mode:       "append_only" | "append_only_with_resolution" | None
#   mutability: "immutable" | "immutable_after_approval" | None
ACCESS_CONTROL: dict[str, dict] = {

    # === CORE IDENTITY ===
    "core_identity.project_id":        {"write": ["master_orchestrator"],          "mutability": "immutable_after_approval"},
    "core_identity.request_id":        {"write": ["inquirer_agent"],                "mutability": "immutable_after_approval"},
    "core_identity.created_at":        {"write": [SYSTEM],                          "mutability": "immutable"},
    "core_identity.updated_at":        {"write": [SYSTEM]},
    "core_identity.current_phase":     {"write": ["master_orchestrator"]},
    "core_identity.status":            {"write": ["master_orchestrator"]},

    # === PROJECT DEFINITION ===
    "project_definition.original_brief":          {"write": ["inquirer_agent"],         "mutability": "immutable_after_approval"},
    "project_definition.clarified_specification": {"write": ["inquirer_agent"],         "mutability": "immutable_after_approval"},
    "project_definition.project_goal":            {"write": ["product_manager_agent"],  "mutability": "immutable_after_approval"},
    "project_definition.problem_statement":       {"write": ["product_manager_agent"],  "mutability": "immutable_after_approval"},
    "project_definition.scope":                   {"write": ["product_manager_agent"],  "mode": "append_only_after_approval"},
    "project_definition.constraints":             {"write": ["product_manager_agent"],  "mode": "append_only_after_approval"},
    "project_definition.success_criteria":        {"write": ["product_manager_agent"],  "mutability": "immutable_after_approval"},
    "project_definition.acceptance_criteria":     {"write": ["product_manager_agent"],  "mutability": "immutable_after_approval"},
    "project_definition.risk_classification":     {"write": ["product_manager_agent", "master_orchestrator"]},
    "project_definition.priority":                {"write": ["product_manager_agent", "master_orchestrator"]},

    # === WORKFLOW ===
    "workflow.active_agents":       {"write": ["master_orchestrator"]},
    "workflow.completed_phases":    {"write": ["master_orchestrator"],                    "mode": "append_only"},
    "workflow.pending_assignments": {"write": ["master_orchestrator"]},
    "workflow.current_owner":       {"write": ["master_orchestrator"]},
    "workflow.handoff_history":     {"write": [SYSTEM],                                   "mode": "append_only"},
    "workflow.resource_requests":   {"write": ["product_manager_agent", "project_manager_agent"], "mode": "append_only"},
    "workflow.resource_allocations":{"write": ["hr_agent"],                               "mode": "append_only"},

    # === DECISIONS ===
    "decisions.decision_log":    {"write": ["scribe_agent"],   "mode": "append_only"},
    "decisions.assumptions":     {"write": [ANY_AGENT],        "mode": "append_only"},
    "decisions.open_questions":  {"write": [ANY_AGENT],        "mode": "append_only_with_resolution"},
    "decisions.approvals":       {"write": ["master_orchestrator"], "mode": "append_only"},
    "decisions.policy_flags":    {"write": [ANY_AGENT],        "mode": "append_only"},

    # === CAPABILITY ===
    "capability.available_skills_snapshot":    {"write": ["hr_agent"]},
    "capability.reuse_candidates":             {"write": ["hr_agent"]},
    "capability.capability_gap_certificates":  {"write": ["hr_agent"],          "mode": "append_only"},
    "capability.spawn_requests":               {"write": ["hr_agent"],          "mode": "append_only"},
    "capability.spawned_agents":               {"write": ["spawner_agent"],     "mode": "append_only"},
    "capability.verification_results":         {"write": ["evaluator_agent"],   "mode": "append_only"},

    # === ARTIFACTS ===
    "artifacts.documents":    {"write": ["scribe_agent"], "mode": "append_only"},
    "artifacts.deliverables": {"write": ["scribe_agent"], "mode": "append_only"},
    "artifacts.change_log":   {"write": ["scribe_agent"], "mode": "append_only"},

    # === EVALUATION ===
    "evaluation.performance_metrics":   {"write": ["evaluator_agent"], "mode": "append_only"},
    "evaluation.quality_findings":      {"write": ["evaluator_agent"], "mode": "append_only"},
    "evaluation.improvement_proposals": {"write": ["trainer_agent"],   "mode": "append_only"},
    "evaluation.approved_updates":      {"write": ["master_orchestrator"], "mode": "append_only"},

    # === CONSULTATION ===
    "consultation.consultation_requests":  {"write": ["master_orchestrator"],   "mode": "append_only"},
    "consultation.consultation_responses": {"write": list(CONSULTANT_AGENTS),   "mode": "append_only"},
    "consultation.synthesis":              {"write": ["master_orchestrator"],   "mode": "append_only"},
}


def is_authorized(agent_id: str, field_path: str) -> bool:
    """Check if agent_id is authorized to write to field_path."""
    rule = ACCESS_CONTROL.get(field_path)
    if rule is None:
        return False  # Unknown fields are denied by default
    writers = rule.get("write", [])
    if ANY_AGENT in writers:
        return True
    if agent_id in writers:
        return True
    # Check consultant group membership
    if agent_id in CONSULTANT_AGENTS and list(CONSULTANT_AGENTS) == writers:
        return True
    # Check if writers list is the consultant group
    if set(writers) == CONSULTANT_AGENTS and agent_id in CONSULTANT_AGENTS:
        return True
    return False


def get_mode(field_path: str) -> str | None:
    """Return the write mode for a field ('append_only', 'append_only_with_resolution', etc.)."""
    rule = ACCESS_CONTROL.get(field_path, {})
    return rule.get("mode")


def get_mutability(field_path: str) -> str | None:
    """Return the mutability constraint for a field."""
    rule = ACCESS_CONTROL.get(field_path, {})
    return rule.get("mutability")


def requires_append_only(field_path: str) -> bool:
    """Return True if this field is strictly append-only (no overwrites allowed)."""
    mode = get_mode(field_path)
    return mode in ("append_only", "append_only_with_resolution")


def is_immutable(field_path: str) -> bool:
    """Return True if this field is always immutable (set once)."""
    return get_mutability(field_path) == "immutable"


def is_immutable_after_approval(field_path: str) -> bool:
    """Return True if this field is immutable once approved."""
    return get_mutability(field_path) == "immutable_after_approval"
