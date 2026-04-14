"""
Prompt Assembler
Loads agent .md templates and injects scoped shared state.
Each agent receives ONLY the shared state fields it is authorized to read.
This prevents attention pollution and enforces information boundaries.
"""

import re
from pathlib import Path
from typing import Any

import yaml

from core.utils.token_counter import TokenCounter

_token_counter = TokenCounter()

ROOT = Path(__file__).parent.parent.parent
AGENTS_DIR = ROOT / "agents"

# Maps agent_id → list of state paths the agent may read
# Each path is "section.field" or "section" (all fields in section)
STATE_PROJECTIONS: dict[str, list[str]] = {
    "master_orchestrator": [
        "core_identity",
        "project_definition",
        "workflow",
        "decisions",
        "capability",
        "consultation",
        "evaluation",
        "_meta",
    ],
    "scribe_agent": [
        "core_identity",
        "workflow.current_owner",
        "workflow.handoff_history",
        "workflow.completed_phases",
        "decisions",
        "artifacts",
    ],
    "inquirer_agent": [
        "core_identity",
        "project_definition.original_brief",
        "project_definition.clarified_specification",
    ],
    "product_manager_agent": [
        "core_identity",
        "project_definition",
        "workflow.current_owner",
        "workflow.resource_requests",
    ],
    "project_manager_agent": [
        "core_identity",
        "project_definition",
        "workflow",
        "execution",
        "capability.reuse_candidates",
        "capability.capability_gap_certificates",
    ],
    "hr_agent": [
        "core_identity",
        "workflow.resource_requests",
        "workflow.resource_allocations",
        "capability",
    ],
    "evaluator_agent": [
        "core_identity",
        "project_definition",
        "workflow",
        "decisions",
        "artifacts",
        "evaluation",
        "capability.spawned_agents",
    ],
    "trainer_agent": [
        "core_identity",
        "evaluation",
        "workflow.completed_phases",
    ],
    "spawner_agent": [
        "core_identity",
        "capability.spawn_requests",
        "capability.spawned_agents",
        "capability.capability_gap_certificates",
    ],
}

# Consultant projections — only the consultation context the Master provides
CONSULTANT_PROJECTION = ["core_identity.project_id"]
for _c in ("risk_advisor", "quality_advisor", "devils_advocate",
           "domain_expert", "efficiency_advisor"):
    STATE_PROJECTIONS[_c] = CONSULTANT_PROJECTION


def _get_nested(data: dict, path: str) -> Any:
    """Get a value from nested dict by dot-notation path."""
    parts = path.split(".")
    node = data
    for part in parts:
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _project_state(state: dict, agent_id: str) -> dict:
    """
    Return a filtered view of state containing only fields
    the agent is authorized to read.
    """
    projection_paths = STATE_PROJECTIONS.get(agent_id, [])
    projected = {}

    for path in projection_paths:
        parts = path.split(".")
        if len(parts) == 1:
            # Full section
            section = parts[0]
            if section in state:
                projected[section] = state[section]
        elif len(parts) == 2:
            # Single field within section
            section, field = parts
            if section in state and field in state[section]:
                projected.setdefault(section, {})[field] = state[section][field]

    return projected


def _strip_empty(obj: Any) -> Any:
    """Recursively remove None values, empty strings, empty lists, and empty dicts."""
    if isinstance(obj, dict):
        cleaned = {}
        for k, v in obj.items():
            v2 = _strip_empty(v)
            if v2 is not None and v2 != "" and v2 != [] and v2 != {}:
                cleaned[k] = v2
        return cleaned or None
    if isinstance(obj, list):
        cleaned = [_strip_empty(i) for i in obj if _strip_empty(i) is not None]
        return cleaned or None
    return obj


def _compact_projection(projected: dict) -> dict:
    """
    Produce a lean version of the projected state for token efficiency.
    - Removes _meta section entirely (timestamps not useful in prompts)
    - Strips None/empty values recursively
    - Trims handoff_history to last 2 entries
    - Trims consultation_requests to last active entry
    """
    compact = dict(projected)

    # Drop _meta — agents don't need timestamps in prompts
    compact.pop("_meta", None)

    # Trim handoff history to most recent 2
    if "workflow" in compact and isinstance(compact["workflow"], dict):
        history = compact["workflow"].get("handoff_history")
        if isinstance(history, list) and len(history) > 2:
            compact["workflow"] = dict(compact["workflow"])
            compact["workflow"]["handoff_history"] = history[-2:]

    # Trim consultation requests to last 1
    if "consultation" in compact and isinstance(compact["consultation"], dict):
        reqs = compact["consultation"].get("consultation_requests")
        if isinstance(reqs, list) and len(reqs) > 1:
            compact["consultation"] = dict(compact["consultation"])
            compact["consultation"]["consultation_requests"] = reqs[-1:]

    return _strip_empty(compact) or {}


def _fill_placeholders(template: str, context: dict) -> str:
    """Replace {placeholder} markers with values from context."""
    def replacer(match):
        key = match.group(1).strip()
        val = context.get(key)
        if val is None:
            return match.group(0)  # Leave unfilled placeholders as-is
        if isinstance(val, (dict, list)):
            return yaml.dump(val, default_flow_style=False,
                             allow_unicode=True).strip()
        return str(val)

    return re.sub(r"\{([^}]+)\}", replacer, template)


class PromptAssembler:
    """
    Assembles agent system prompts by injecting scoped state context
    into .md templates.
    """

    def __init__(self, agents_dir: Path = AGENTS_DIR):
        self.agents_dir = agents_dir

    def get_template_path(self, agent_id: str) -> Path:
        return self.agents_dir / f"{agent_id}.md"

    def load_template(self, agent_id: str) -> str:
        """Load the raw .md template for an agent (strips YAML frontmatter)."""
        path = self.get_template_path(agent_id)
        if not path.exists():
            raise FileNotFoundError(f"Agent template not found: {path}")
        content = path.read_text(encoding="utf-8")
        # Strip YAML frontmatter (--- ... ---)
        if content.startswith("---"):
            end = content.find("---", 3)
            if end != -1:
                content = content[end + 3:].lstrip()
        return content

    def assemble(self, agent_id: str, state: dict,
                 extra_context: dict | None = None) -> str:
        """
        Assemble a complete prompt for an agent.
        Injects scoped state and any extra context.

        After assembly, self.last_token_count holds the estimated
        token count of the assembled prompt.
        """
        template = self.load_template(agent_id)
        projected = _project_state(state, agent_id)
        compact = _compact_projection(projected)

        # Wire protocol instruction (agent-to-agent outputs only; never for human-facing)
        # Inquirer is excluded — its output is natural language for humans.
        _WIRE_INSTRUCTION = (
            "\n\n## Output Format\n"
            "For all agent-to-agent outputs (handoff payloads, consultation responses), "
            "use MAS wire protocol v1.0:\n"
            "- Status: compact code, e.g. `\"s\": \"task:complete\"`\n"
            "- Version: `\"_v\": \"1.0\"` in every payload\n"
            "- Omit empty lists and null fields\n"
            "- Optional reasoning (`rsn`): max 100 words\n"
            "- Human-facing text (CHECKPOINT.md, reports) uses expand() — stay structured here.\n"
        ) if agent_id != "inquirer_agent" else ""

        context = {
            "injected_project_id": state.get("core_identity", {}).get("project_id", ""),
            "injected_current_phase": state.get("core_identity", {}).get("current_phase", ""),
            "injected_shared_state": yaml.dump(compact, default_flow_style=False,
                                               allow_unicode=True, sort_keys=False),
            "injected_wire_instruction": _WIRE_INSTRUCTION,
        }

        # Add section-specific convenience keys
        if "workflow" in compact:
            context["injected_pending_items"] = yaml.dump(
                compact["workflow"].get("pending_assignments", []),
                default_flow_style=False, allow_unicode=True,
            )
            context["injected_recent_handoffs"] = yaml.dump(
                compact["workflow"].get("handoff_history", [])[-2:],
                default_flow_style=False, allow_unicode=True,
            )

        if "consultation" in compact:
            context["injected_active_consultation"] = yaml.dump(
                compact["consultation"].get("consultation_requests", [])[-1:],
                default_flow_style=False, allow_unicode=True,
            )

        if "project_definition" in compact:
            spec = compact["project_definition"].get("clarified_specification")
            context["injected_clarified_specification"] = (
                yaml.dump(spec, default_flow_style=False, allow_unicode=True)
                if spec else "(not yet available)"
            )
            context["injected_original_brief"] = (
                compact["project_definition"].get("original_brief") or "(not yet available)"
            )

        # Graph memory context injection (replaces part of state dump when available)
        # Only used when graph has ≥ 5 nodes — not enough data otherwise.
        graph_context = self._graph_context(agent_id, state)
        if graph_context:
            context["injected_graph_context"] = graph_context

        if extra_context:
            context.update(extra_context)

        prompt = _fill_placeholders(template, context)
        self.last_token_count: int = _token_counter.count(prompt)
        return prompt

    def _graph_context(self, agent_id: str, state: dict) -> str:
        """
        Query graph memory for agent-relevant facts.
        Returns a compact string for prompt injection, or "" if unavailable.
        Requires graph to have ≥ 5 nodes to be useful.
        """
        try:
            from core.graph_memory import GraphMemory
            project_id = state.get("core_identity", {}).get("project_id", "")
            if not project_id:
                return ""
            gm = GraphMemory(project_id)
            if gm.store.node_count() < 5:
                return ""
            phase = state.get("core_identity", {}).get("current_phase", "")
            result = gm.query(agent_id, context=phase)
            facts = result.get("facts", [])
            if not facts:
                return ""
            lines = [f"[{f['type']}] {f['summary']}" for f in facts]
            return "## Relevant Context (from graph memory)\n" + "\n".join(lines)
        except Exception:
            return ""

    def get_state_projection(self, agent_id: str) -> list[str]:
        """Return the list of state paths this agent is authorized to read."""
        return STATE_PROJECTIONS.get(agent_id, [])
