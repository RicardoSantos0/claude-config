"""
Consultation Engine
Manages the consultation lifecycle for the Consultant Panel.

Rules (from policies/spawn_policy.yaml and consultant_panel_answers.yaml):
  - Mandatory consultations: all 5 consultants must respond
  - Recommended: Master can invoke 2-3 relevant consultants
  - Max 500 words per response
  - 1 follow-up round allowed
  - Unanimous high-risk → Master MUST escalate to human (hard governance rule)
  - Consultants receive only the context Master provides — no direct state access

Mandatory decision types: spawn, scope_change, governance, escalation, architecture
Recommended (optional): resource, priority, approach

CLI usage:
  uv run python core/consultation_engine.py create \\
    --project-id {pid} --question "..." --decision-type spawn
  uv run python core/consultation_engine.py show --project-id {pid} --request-id {id}
  uv run python core/consultation_engine.py check-risk --project-id {pid} --request-id {id}
"""

from __future__ import annotations

import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_RESPONSE_WORDS: int = 500
MAX_REASONING_WORDS: int = 100   # wire protocol: optional rsn field cap
FOLLOW_UP_ROUNDS_MAX: int = 1

ALL_CONSULTANTS: list[str] = [
    "risk_advisor",
    "quality_advisor",
    "devils_advocate",
    "domain_expert",
    "efficiency_advisor",
]

# Decision types requiring ALL 5 consultants
MANDATORY_DECISION_TYPES: frozenset[str] = frozenset({
    "spawn",
    "scope_change",
    "governance",
    "escalation",
    "architecture",
})

# Risk levels
RISK_LEVELS = ("none", "low", "medium", "high")

DOMAINS_DIR = Path(__file__).parent.parent / "domains"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ConsultationResponse:
    consultant_id: str
    response_text: str
    word_count: int
    risk_level: str          # none | low | medium | high
    key_concerns: list[str]
    recommendation: str
    responded_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    truncated: bool = False  # True if response was trimmed to 500 words


@dataclass
class ConsultationRequest:
    request_id: str
    project_id: str
    timestamp: str
    requested_by: str
    question: str
    context: dict
    decision_type: str
    mandatory: bool
    consultants_selected: list[str]
    domain_context: str = ""          # injected for domain_expert
    responses: dict = field(default_factory=dict)  # consultant_id → ConsultationResponse dict
    follow_up_round: int = 0
    follow_up_question: Optional[str] = None
    status: str = "open"              # open | responded | synthesized


@dataclass
class ConsultationSynthesis:
    synthesis_id: str
    request_id: str
    project_id: str
    produced_by: str
    produced_at: str
    summary: str
    perspectives_acknowledged: list[str]
    decision_reached: str
    rationale: str
    risks_addressed: str
    unanimous_high_risk: bool
    human_escalation_required: bool
    follow_up_round: bool = False
    follow_up_question: Optional[str] = None


# ---------------------------------------------------------------------------
# ConsultationEngine
# ---------------------------------------------------------------------------

class ConsultationEngine:

    # ------------------------------------------------------------------
    # Request creation
    # ------------------------------------------------------------------

    def create_request(
        self,
        project_id: str,
        question: str,
        context: dict,
        decision_type: str,
        consultants: Optional[list[str]] = None,
        domain_context: str = "",
    ) -> ConsultationRequest:
        """
        Build a ConsultationRequest.
        If decision_type is mandatory, all 5 consultants are selected
        regardless of the `consultants` argument.
        """
        mandatory = decision_type in MANDATORY_DECISION_TYPES

        if mandatory or consultants is None:
            selected = list(ALL_CONSULTANTS)
        else:
            # Enforce minimum of 2
            selected = consultants if len(consultants) >= 2 else list(ALL_CONSULTANTS)

        return ConsultationRequest(
            request_id=f"consult-{project_id}-{uuid.uuid4().hex[:8]}",
            project_id=project_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            requested_by="master_orchestrator",
            question=question,
            context=context,
            decision_type=decision_type,
            mandatory=mandatory,
            consultants_selected=selected,
            domain_context=domain_context,
        )

    # ------------------------------------------------------------------
    # Response recording
    # ------------------------------------------------------------------

    def record_response(
        self,
        request: ConsultationRequest,
        consultant_id: str,
        response_text: str,
        risk_level: str = "low",
        key_concerns: Optional[list[str]] = None,
        recommendation: str = "",
        reasoning: str = "",
    ) -> ConsultationResponse:
        """
        Record a consultant's response.
        Enforces 500-word cap on response_text; 100-word cap on reasoning.
        Returns the ConsultationResponse and mutates request.responses.
        """
        if consultant_id not in request.consultants_selected:
            raise ValueError(
                f"Consultant '{consultant_id}' was not selected for request '{request.request_id}'"
            )

        if risk_level not in RISK_LEVELS:
            risk_level = "low"

        words = response_text.split()
        truncated = len(words) > MAX_RESPONSE_WORDS
        if truncated:
            response_text = " ".join(words[:MAX_RESPONSE_WORDS]) + " [truncated]"
            word_count = MAX_RESPONSE_WORDS
        else:
            word_count = len(words)

        # Enforce reasoning word cap (wire protocol: max 100 words)
        if reasoning:
            rsn_words = reasoning.split()
            if len(rsn_words) > MAX_REASONING_WORDS:
                reasoning = " ".join(rsn_words[:MAX_REASONING_WORDS]) + " [truncated]"

        resp = ConsultationResponse(
            consultant_id=consultant_id,
            response_text=response_text,
            word_count=word_count,
            risk_level=risk_level,
            key_concerns=key_concerns or [],
            recommendation=recommendation,
            truncated=truncated,
        )

        response_dict = {
            "response_text": resp.response_text,
            "word_count": resp.word_count,
            "risk_level": resp.risk_level,
            "key_concerns": resp.key_concerns,
            "recommendation": resp.recommendation,
            "responded_at": resp.responded_at,
            "truncated": resp.truncated,
        }
        if reasoning:
            response_dict["reasoning"] = reasoning
        request.responses[consultant_id] = response_dict

        # Update status once all selected have responded
        if set(request.consultants_selected) == set(request.responses.keys()):
            request.status = "responded"

        return resp

    # ------------------------------------------------------------------
    # Risk checks
    # ------------------------------------------------------------------

    def check_unanimous_risk(self, request: ConsultationRequest) -> bool:
        """
        Returns True if ALL responding consultants flagged 'high' risk.
        Triggers mandatory human escalation.
        """
        if not request.responses:
            return False
        return all(
            r.get("risk_level") == "high"
            for r in request.responses.values()
        )

    def check_majority_risk(self, request: ConsultationRequest) -> bool:
        """Returns True if >50% of respondents flagged 'high' risk."""
        if not request.responses:
            return False
        high_count = sum(1 for r in request.responses.values() if r.get("risk_level") == "high")
        return high_count > len(request.responses) / 2

    def get_highest_risk_level(self, request: ConsultationRequest) -> str:
        """Returns the highest risk level among all responses."""
        if not request.responses:
            return "none"
        order = {"none": 0, "low": 1, "medium": 2, "high": 3}
        return max(
            (r.get("risk_level", "none") for r in request.responses.values()),
            key=lambda r: order.get(r, 0),
        )

    # ------------------------------------------------------------------
    # Synthesis
    # ------------------------------------------------------------------

    def synthesize(
        self,
        request: ConsultationRequest,
        decision_reached: str,
        rationale: str,
        risks_addressed: str,
        follow_up_question: Optional[str] = None,
    ) -> ConsultationSynthesis:
        """Produce a synthesis of all consultant responses."""
        unanimous_high = self.check_unanimous_risk(request)
        human_escalation = unanimous_high

        perspectives = list(request.responses.keys())
        summary_parts = []
        for cid, resp in request.responses.items():
            concerns = "; ".join(resp.get("key_concerns", []))
            summary_parts.append(
                f"{cid}: [{resp.get('risk_level', 'low')}] {resp.get('recommendation', '')}. "
                f"Concerns: {concerns or 'none stated'}"
            )

        synthesis = ConsultationSynthesis(
            synthesis_id=f"synth-{request.request_id}",
            request_id=request.request_id,
            project_id=request.project_id,
            produced_by="master_orchestrator",
            produced_at=datetime.now(timezone.utc).isoformat(),
            summary="\n".join(summary_parts),
            perspectives_acknowledged=perspectives,
            decision_reached=decision_reached,
            rationale=rationale,
            risks_addressed=risks_addressed,
            unanimous_high_risk=unanimous_high,
            human_escalation_required=human_escalation,
            follow_up_round=follow_up_question is not None,
            follow_up_question=follow_up_question,
        )

        request.status = "synthesized"
        return synthesis

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_request(
        self,
        request: ConsultationRequest,
        project_dir: Path,
    ) -> Path:
        """Write consultation request to projects/{pid}/consultation/."""
        d = project_dir / "consultation"
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{request.request_id}.yaml"
        data = {
            "request_id": request.request_id,
            "project_id": request.project_id,
            "timestamp": request.timestamp,
            "requested_by": request.requested_by,
            "question": request.question,
            "context": request.context,
            "decision_type": request.decision_type,
            "mandatory": request.mandatory,
            "consultants_selected": request.consultants_selected,
            "domain_context": request.domain_context,
            "responses": request.responses,
            "follow_up_round": request.follow_up_round,
            "follow_up_question": request.follow_up_question,
            "status": request.status,
        }
        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
        return path

    def save_synthesis(
        self,
        synthesis: ConsultationSynthesis,
        project_dir: Path,
    ) -> Path:
        """Write synthesis to projects/{pid}/consultation/."""
        d = project_dir / "consultation"
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{synthesis.synthesis_id}.yaml"
        data = {
            "synthesis_id": synthesis.synthesis_id,
            "request_id": synthesis.request_id,
            "project_id": synthesis.project_id,
            "produced_by": synthesis.produced_by,
            "produced_at": synthesis.produced_at,
            "summary": synthesis.summary,
            "perspectives_acknowledged": synthesis.perspectives_acknowledged,
            "decision_reached": synthesis.decision_reached,
            "rationale": synthesis.rationale,
            "risks_addressed": synthesis.risks_addressed,
            "unanimous_high_risk": synthesis.unanimous_high_risk,
            "human_escalation_required": synthesis.human_escalation_required,
            "follow_up_round": synthesis.follow_up_round,
            "follow_up_question": synthesis.follow_up_question,
        }
        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
        return path

    def load_request(self, project_dir: Path, request_id: str) -> dict:
        path = project_dir / "consultation" / f"{request_id}.yaml"
        if not path.exists():
            return {}
        with open(path) as f:
            return yaml.safe_load(f) or {}

    # ------------------------------------------------------------------
    # Domain context injection
    # ------------------------------------------------------------------

    def load_domain_context(self, domain: str) -> str:
        """Load domain context file for domain_expert injection."""
        path = DOMAINS_DIR / f"{domain}.md"
        if path.exists():
            return path.read_text(encoding="utf-8")
        return f"[No domain context found for '{domain}'. Apply general best practices.]"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def is_mandatory(decision_type: str) -> bool:
        return decision_type in MANDATORY_DECISION_TYPES

    @staticmethod
    def get_all_consultants() -> list[str]:
        return list(ALL_CONSULTANTS)
