"""
Response Parser
Extracts structured wire protocol data from raw LLM agent response text.

Every agent is instructed to emit a JSON wire block at the end of its response,
delimited by ```json ... ```. This parser extracts that block, decodes it via
WireDecoder, and falls back to heuristics for non-compliant responses.

Also detects KNOWLEDGE_REQUEST blocks for NotebookLM broker pattern.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Output dataclass
# ---------------------------------------------------------------------------

@dataclass
class ParsedResponse:
    """Structured output of ResponseParser.parse()."""
    status: str                          # s field (e.g. "task:complete")
    decisions: list[dict]                # dec items
    artifacts: list[str]                 # art paths
    reasoning: str                       # rsn field
    next_action: str                     # "delegate" | "advance_phase" | "consult" | "escalate" | "wait"
    next_agent: str | None               # who to delegate to (single, when next_action == "delegate")
    parallel_agents: list[str]           # next_agents list for concurrent dispatch
    consultation_trigger: dict | None    # {decision_type, question, context, consultants}
    knowledge_request: dict | None       # KNOWLEDGE_REQUEST block
    deployment_plan: list[dict]          # deploy array from HR capability assessment
    raw_wire: dict                       # full decoded wire dict (pass-through unknown keys)
    parse_errors: list[str] = field(default_factory=list)

    @property
    def next_agents_label(self) -> str:
        """Short display label for parallel agents list."""
        return "[" + ", ".join(self.parallel_agents) + "]"


# ---------------------------------------------------------------------------
# Status → next_action mapping
# ---------------------------------------------------------------------------

_STATUS_TO_ACTION: dict[str, str] = {
    # Completion / advancement
    "task:complete":        "advance_phase",
    "spec:ready":           "advance_phase",
    "product_plan:ready":   "advance_phase",
    "exec_plan:ready":      "advance_phase",
    "eval:pass":            "advance_phase",
    "eval:fail":            "advance_phase",
    "scribe:recorded":      "advance_phase",
    "ok":                   "advance_phase",
    # Delegation
    "task:delegated":       "delegate",
    # Consultation
    "consult:approve":      "advance_phase",
    "consult:deny":         "wait",
    "consult:flag":         "consult",
    # Escalation
    "escalate":             "escalate",
    "human_required":       "escalate",
}


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

class ResponseParser:
    """
    Parses raw LLM response text into a ParsedResponse.

    Never raises — non-fatal issues accumulate in parse_errors.
    """

    _JSON_BLOCK_RE = re.compile(
        r"```(?:json)?\s*(\{.*?\})\s*```",
        re.DOTALL | re.IGNORECASE,
    )
    _KR_BLOCK_RE = re.compile(
        r"KNOWLEDGE_REQUEST\s*[:\-]?\s*(\{[^`]+?\})",
        re.DOTALL | re.IGNORECASE,
    )
    _RSN_WORD_LIMIT = 100

    def parse(self, raw_text: str) -> ParsedResponse:
        errors: list[str] = []

        wire = self._extract_wire_block(raw_text, errors)
        decoded = self._decode(wire, errors)

        status    = wire.get("s", decoded.get("status", ""))
        decisions = self._extract_decisions(wire, decoded)
        artifacts = self._extract_artifacts(wire, decoded)
        reasoning = wire.get("rsn", decoded.get("reasoning", ""))

        if reasoning and len(reasoning.split()) > self._RSN_WORD_LIMIT:
            errors.append(f"rsn_exceeds_{self._RSN_WORD_LIMIT}_words")

        next_action       = self._resolve_next_action(wire, status, raw_text)
        next_agent        = wire.get("next_agent")
        parallel_agents   = self._extract_parallel_agents(wire)
        consult_trigger   = wire.get("consultation_trigger")
        knowledge_request = self._extract_knowledge_request(raw_text)
        deployment_plan   = self._extract_deployment_plan(wire)

        return ParsedResponse(
            status=status,
            decisions=decisions,
            artifacts=artifacts,
            reasoning=reasoning,
            next_action=next_action,
            next_agent=next_agent,
            parallel_agents=parallel_agents,
            consultation_trigger=consult_trigger,
            knowledge_request=knowledge_request,
            deployment_plan=deployment_plan,
            raw_wire=wire,
            parse_errors=errors,
        )

    # ------------------------------------------------------------------
    # Wire block extraction
    # ------------------------------------------------------------------

    def _extract_wire_block(self, text: str, errors: list[str]) -> dict:
        # Try last JSON fence first (agents put wire block at end)
        matches = list(self._JSON_BLOCK_RE.finditer(text))
        for m in reversed(matches):
            try:
                parsed = json.loads(m.group(1))
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                continue

        if not matches:
            errors.append("no_wire_block_found")
        else:
            errors.append("wire_block_parse_error")
        return {}

    def _decode(self, wire: dict, errors: list[str]) -> dict:
        if not wire:
            return {}
        try:
            from core.utils.wire_protocol import WireDecoder
            return WireDecoder().decode(wire)
        except Exception as e:
            errors.append(f"wire_decode_error: {e}")
            return {}

    # ------------------------------------------------------------------
    # Field extraction
    # ------------------------------------------------------------------

    def _extract_decisions(self, wire: dict, decoded: dict) -> list[dict]:
        raw = wire.get("dec", decoded.get("decisions_made", []))
        if isinstance(raw, list):
            return [d for d in raw if isinstance(d, dict)]
        return []

    def _extract_artifacts(self, wire: dict, decoded: dict) -> list[str]:
        raw = wire.get("art", decoded.get("artifacts_produced", []))
        if isinstance(raw, list):
            return [str(a) for a in raw if a]
        return []

    def _resolve_next_action(self, wire: dict, status: str, text: str) -> str:
        # Explicit in wire block wins
        if "next_action" in wire:
            return str(wire["next_action"])
        # Status map
        if status in _STATUS_TO_ACTION:
            return _STATUS_TO_ACTION[status]
        # Heuristics on text
        upper = text.upper()
        if "KNOWLEDGE_REQUEST" in upper:
            return "wait"   # wait for knowledge injection before proceeding
        if "CONSULT" in upper and "consultation_trigger" in wire:
            return "consult"
        if status.startswith("task:") or status.startswith("eval:") or status.startswith("scribe:"):
            return "advance_phase"
        return "wait"

    def _extract_knowledge_request(self, text: str) -> dict | None:
        m = self._KR_BLOCK_RE.search(text)
        if not m:
            return None
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            return None

    def _extract_parallel_agents(self, wire: dict) -> list[str]:
        """Extract next_agents list for concurrent parallel dispatch."""
        raw = wire.get("next_agents", [])
        if not isinstance(raw, list):
            return []
        return [str(a) for a in raw if a]

    def _extract_deployment_plan(self, wire: dict) -> list[dict]:
        """Extract the HR deploy array from the wire block."""
        raw = wire.get("deploy", [])
        if not isinstance(raw, list):
            return []
        return [entry for entry in raw if isinstance(entry, dict)]
