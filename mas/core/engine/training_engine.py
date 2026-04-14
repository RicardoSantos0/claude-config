"""
Training Engine
Analyzes evaluation reports and produces improvement proposals.

Authority: L0 advisory only — proposes changes, never applies them.

Proposal lifecycle:
  pending → approved → applied
           → rejected (can be resubmitted with new evidence)

Backlog: roster/training_backlog.yaml
Training brief (per project): projects/{pid}/training/training_brief.yaml

CLI usage:
  uv run python core/training_engine.py analyze --project-id {pid}
  uv run python core/training_engine.py backlog
  uv run python core/training_engine.py approve --proposal-id {id} --authorized-by master_orchestrator
  uv run python core/training_engine.py reject --proposal-id {id} --reason "{reason}" --authorized-by master_orchestrator
"""

from __future__ import annotations

import sys
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

try:
    from .metrics_engine import MetricsEngine
except ImportError:
    MetricsEngine = None  # type: ignore

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BACKLOG_FILE = Path("roster") / "training_backlog.yaml"

# Priority scores (higher = more urgent)
PRIORITY_SCORES: dict[str, int] = {
    "boundary_violation": 5,
    "governance_failure": 4,
    "repeated_quality_issue": 3,
    "communication_waste": 2,
    "context_bloat": 2,
    "efficiency_improvement": 2,
    "prompt_refinement": 1,
}

# Project metrics that, if low, trigger proposals
LOW_THRESHOLD = 70.0
SYSTEMIC_MIN_REPORTS = 2   # need this many reports showing same issue

PROPOSAL_STATUSES = {"pending", "approved", "rejected", "applied", "deferred"}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class TrainingProposal:
    proposal_id: str
    proposal_type: str              # boundary_violation | governance_failure | repeated_quality_issue | efficiency_improvement | prompt_refinement
    priority: int                   # 1-5 (5 = highest)
    target_agent: str               # agent_id or "system"
    target_artifact: str            # e.g. "agents/evaluator_agent.md" or "policies/evaluation_policy.yaml"
    description: str                # what was observed
    recommended_change: str         # what to change
    evidence: list[str]             # report_ids or finding_ids
    tradeoffs: str                  # potential downsides of the change
    minimum_evidence_met: bool      # True if evidence threshold satisfied
    systemic: bool                  # True if pattern seen in 2+ reports
    status: str = "pending"         # pending | approved | rejected | applied
    rejection_reason: str = ""
    original_proposal_id: str = ""  # if resubmission
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    project_ids: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# TrainingEngine
# ---------------------------------------------------------------------------

class TrainingEngine:

    # ------------------------------------------------------------------
    # Analysis: single report
    # ------------------------------------------------------------------

    def analyze_evaluation_report(
        self,
        report_data: dict,
        project_id: str = "",
    ) -> list[TrainingProposal]:
        """
        Produce proposals from a single evaluation report.
        Returns proposals for: low metrics, probation-risk agents, systemic findings.
        """
        proposals: list[TrainingProposal] = []
        report_id = report_data.get("report_id", "unknown")
        pid = project_id or report_data.get("project_id", "unknown")

        # --- 1. Project metrics below threshold ---
        for m in report_data.get("project_metrics", []):
            score = float(m.get("score", 100))
            metric = m.get("metric", "unknown")
            if score < LOW_THRESHOLD:
                ptype = self._metric_to_proposal_type(metric, score)
                proposals.append(TrainingProposal(
                    proposal_id=f"prop-{uuid.uuid4().hex[:8]}",
                    proposal_type=ptype,
                    priority=PRIORITY_SCORES[ptype],
                    target_agent="system",
                    target_artifact=self._metric_to_artifact(metric),
                    description=(
                        f"Metric '{metric}' scored {score:.1f}/100 "
                        f"(below threshold {LOW_THRESHOLD}). "
                        f"Evidence: {m.get('evidence', 'none')}"
                    ),
                    recommended_change=self._recommend_for_metric(metric, score, m),
                    evidence=[report_id],
                    tradeoffs=self._tradeoffs_for_metric(metric),
                    minimum_evidence_met=True,   # 1 report = sufficient for single finding
                    systemic=False,
                    project_ids=[pid],
                ))

        # --- 2. Agents recommended for probation ---
        for agent_eval in report_data.get("agent_evaluations", []):
            if agent_eval.get("recommend_probation"):
                agent_id = agent_eval.get("agent_id", "unknown")
                overall = float(agent_eval.get("overall_score", 0))
                proposals.append(TrainingProposal(
                    proposal_id=f"prop-{uuid.uuid4().hex[:8]}",
                    proposal_type="boundary_violation",
                    priority=PRIORITY_SCORES["boundary_violation"],
                    target_agent=agent_id,
                    target_artifact=f"agents/{agent_id}.md",
                    description=(
                        f"Agent '{agent_id}' scored {overall:.1f}/100 — "
                        f"flagged for probation review. "
                        f"Issues: {'; '.join(agent_eval.get('issues', []))}"
                    ),
                    recommended_change=(
                        f"Review agent definition and governance boundaries for '{agent_id}'. "
                        "Consider restricting tool set or adding explicit escalation triggers."
                    ),
                    evidence=[report_id],
                    tradeoffs="Restricting the agent may reduce its effectiveness on tasks.",
                    minimum_evidence_met=True,
                    systemic=False,
                    project_ids=[pid],
                ))

        # --- 3. Systemic findings from report ---
        for finding in report_data.get("systemic_findings", []):
            finding_text = str(finding)
            proposals.append(TrainingProposal(
                proposal_id=f"prop-{uuid.uuid4().hex[:8]}",
                proposal_type="governance_failure",
                priority=PRIORITY_SCORES["governance_failure"],
                target_agent="system",
                target_artifact="policies/governance_policy.yaml",
                description=f"Systemic finding: {finding_text}",
                recommended_change=(
                    "Review governance policy and update to address systemic pattern."
                ),
                evidence=[report_id],
                tradeoffs="Policy changes may slow workflow if overly restrictive.",
                minimum_evidence_met=True,
                systemic=True,
                project_ids=[pid],
            ))

        # --- 4. Improvement areas from recommendations ---
        recs = report_data.get("recommendations", {}) or {}
        for area in recs.get("improvement_areas", []):
            proposals.append(TrainingProposal(
                proposal_id=f"prop-{uuid.uuid4().hex[:8]}",
                proposal_type="efficiency_improvement",
                priority=PRIORITY_SCORES["efficiency_improvement"],
                target_agent="system",
                target_artifact="policies/",
                description=f"Improvement area identified: {area}",
                recommended_change=(
                    f"Investigate and address '{area}' in the relevant agent or policy."
                ),
                evidence=[report_id],
                tradeoffs="Investigation required before recommending specific change.",
                minimum_evidence_met=True,
                systemic=False,
                project_ids=[pid],
            ))

        return proposals

    # ------------------------------------------------------------------
    # Analysis: multiple reports (systemic pattern detection)
    # ------------------------------------------------------------------

    def analyze_multiple_reports(
        self,
        reports: list[dict],
        project_ids: Optional[list[str]] = None,
    ) -> list[TrainingProposal]:
        """
        Analyze N evaluation reports together, surfacing systemic patterns.
        Single-report proposals are also included but flagged accordingly.
        """
        if project_ids is None:
            project_ids = [r.get("project_id", "unknown") for r in reports]

        all_proposals: list[TrainingProposal] = []
        metric_scores: dict[str, list[tuple[float, str, str]]] = defaultdict(list)
            # metric → [(score, report_id, project_id)]

        # Collect per-report proposals + gather metric data
        for i, report in enumerate(reports):
            pid = project_ids[i] if i < len(project_ids) else report.get("project_id", "unknown")
            per_report = self.analyze_evaluation_report(report, project_id=pid)
            all_proposals.extend(per_report)

            for m in report.get("project_metrics", []):
                score = float(m.get("score", 100))
                metric_scores[m.get("metric", "unknown")].append(
                    (score, report.get("report_id", "unknown"), pid)
                )

        # Detect systemic patterns: same metric low in 2+ reports
        systemic_added: set[str] = set()
        for metric, scores in metric_scores.items():
            low_instances = [(s, rid, pid) for s, rid, pid in scores if s < LOW_THRESHOLD]
            if len(low_instances) >= SYSTEMIC_MIN_REPORTS:
                key = f"systemic-{metric}"
                if key in systemic_added:
                    continue
                systemic_added.add(key)
                ptype = self._metric_to_proposal_type(metric, sum(s for s, _, _ in low_instances) / len(low_instances))
                evidence = [rid for _, rid, _ in low_instances]
                pids = [pid for _, _, pid in low_instances]
                all_proposals.append(TrainingProposal(
                    proposal_id=f"prop-systemic-{uuid.uuid4().hex[:8]}",
                    proposal_type=ptype,
                    priority=PRIORITY_SCORES[ptype] + 1,  # bump systemic higher
                    target_agent="system",
                    target_artifact=self._metric_to_artifact(metric),
                    description=(
                        f"SYSTEMIC: Metric '{metric}' scored below {LOW_THRESHOLD} "
                        f"in {len(low_instances)}/{len(reports)} reports. "
                        f"Average score: {sum(s for s, _, _ in low_instances) / len(low_instances):.1f}. "
                        f"Consistent pattern suggests structural issue."
                    ),
                    recommended_change=self._recommend_systemic(metric),
                    evidence=evidence,
                    tradeoffs=self._tradeoffs_for_metric(metric),
                    minimum_evidence_met=True,
                    systemic=True,
                    project_ids=pids,
                ))

        return all_proposals

    # ------------------------------------------------------------------
    # Prioritization
    # ------------------------------------------------------------------

    def prioritize(self, proposals: list[TrainingProposal]) -> list[TrainingProposal]:
        """Sort proposals: higher priority first, systemic before non-systemic, newer evidence."""
        return sorted(
            proposals,
            key=lambda p: (
                -p.priority,
                not p.systemic,              # systemic first within same priority
                not p.minimum_evidence_met,  # evidence-met first
            ),
        )

    # ------------------------------------------------------------------
    # Training brief (per project)
    # ------------------------------------------------------------------

    def produce_training_brief(
        self,
        project_id: str,
        proposals: list[TrainingProposal],
        project_dir: Path,
    ) -> Path:
        """Write training brief to projects/{pid}/training/training_brief.yaml."""
        brief_dir = project_dir / "training"
        brief_dir.mkdir(parents=True, exist_ok=True)

        prioritized = self.prioritize(proposals)
        brief = {
            "project_id": project_id,
            "trainer": "trainer_agent",
            "authority_level": "L0_advisory",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_proposals": len(proposals),
            "proposal_summary": {
                "by_type": _count_by(proposals, "proposal_type"),
                "by_priority": _count_by(proposals, "priority"),
                "systemic_count": sum(1 for p in proposals if p.systemic),
                "minimum_evidence_met_count": sum(1 for p in proposals if p.minimum_evidence_met),
            },
            "proposals": [_proposal_to_dict(p) for p in prioritized],
            "note": (
                "These are advisory proposals only. No changes will be applied "
                "until Master Orchestrator approves each proposal individually."
            ),
        }

        path = brief_dir / "training_brief.yaml"
        with open(path, "w") as f:
            yaml.dump(brief, f, default_flow_style=False, sort_keys=False)

        return path

    # ------------------------------------------------------------------
    # Backlog management
    # ------------------------------------------------------------------

    def load_backlog(self) -> dict:
        if not BACKLOG_FILE.exists():
            return {"proposals": [], "last_updated": None}
        with open(BACKLOG_FILE) as f:
            return yaml.safe_load(f) or {"proposals": [], "last_updated": None}

    def update_backlog(self, proposals: list[TrainingProposal]) -> None:
        """Append new proposals to the backlog. Deduplicates by proposal_id."""
        backlog = self.load_backlog()
        existing_ids = {p["proposal_id"] for p in backlog.get("proposals", [])}
        added = 0
        for p in proposals:
            if p.proposal_id not in existing_ids:
                backlog["proposals"].append(_proposal_to_dict(p))
                existing_ids.add(p.proposal_id)
                added += 1
        backlog["last_updated"] = datetime.now(timezone.utc).isoformat()
        _save_backlog(backlog)
        return added

    def approve_proposal(self, proposal_id: str, authorized_by: str) -> bool:
        """Mark a proposal as approved. Only master_orchestrator may approve."""
        if authorized_by != "master_orchestrator":
            return False
        backlog = self.load_backlog()
        for p in backlog["proposals"]:
            if p["proposal_id"] == proposal_id:
                if p["status"] in ("pending",):
                    p["status"] = "approved"
                    p["approved_by"] = authorized_by
                    p["approved_at"] = datetime.now(timezone.utc).isoformat()
                    _save_backlog(backlog)
                    return True
        return False

    def reject_proposal(
        self,
        proposal_id: str,
        reason: str,
        authorized_by: str,
    ) -> bool:
        """Mark a proposal as rejected with a reason. Only master_orchestrator may reject."""
        if authorized_by != "master_orchestrator":
            return False
        backlog = self.load_backlog()
        for p in backlog["proposals"]:
            if p["proposal_id"] == proposal_id:
                if p["status"] in ("pending",):
                    p["status"] = "rejected"
                    p["rejection_reason"] = reason
                    p["rejected_by"] = authorized_by
                    p["rejected_at"] = datetime.now(timezone.utc).isoformat()
                    _save_backlog(backlog)
                    return True
        return False

    def mark_applied(self, proposal_id: str, authorized_by: str) -> bool:
        """Mark an approved proposal as applied."""
        if authorized_by != "master_orchestrator":
            return False
        backlog = self.load_backlog()
        for p in backlog["proposals"]:
            if p["proposal_id"] == proposal_id and p["status"] == "approved":
                p["status"] = "applied"
                p["applied_at"] = datetime.now(timezone.utc).isoformat()
                _save_backlog(backlog)
                return True
        return False

    def get_pending(self) -> list[dict]:
        backlog = self.load_backlog()
        return [p for p in backlog.get("proposals", []) if p["status"] == "pending"]
