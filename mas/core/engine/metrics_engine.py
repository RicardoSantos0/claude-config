"""
Metrics Engine
Pure scoring functions for project and agent evaluation.
All functions take structured data (dicts/lists from shared state or
task board) and return numeric scores or structured results.

Minimum metrics for v1 (from expert answers):
  - goal_achievement              (0-100)
  - acceptance_criteria_pass_rate (0-100)
  - handoff_acceptance_rate       (0-100)
  - documentation_completeness    (0-100)
  - boundary_violation_count      (integer)

Additional v1 metrics:
  - scope_adherence               (0-100)
  - task_completion_rate          (0-100)
  - decision_quality              (0-100)
  - phase_efficiency              (dict of phase→ratio)

Usage as library:
    from core.metrics_engine import MetricsEngine
    engine = MetricsEngine()
    score = engine.score_goal_achievement(success_criteria, task_outcomes)

Usage as CLI:
    uv run python core/metrics_engine.py score-project --project-id proj-001
    uv run python core/metrics_engine.py score-agent  --project-id proj-001 --agent-id hr_agent
    uv run python core/metrics_engine.py report       --project-id proj-001 [--save]
"""

import sys
import json
import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from core.utils.token_counter import TokenCounter

_token_counter = TokenCounter()

ROOT = Path(__file__).parent.parent

EXEMPLARY_THRESHOLD = 90.0    # Agent score above this → flagged exemplary
PROBATION_THRESHOLD = 60.0    # Agent score below this → recommend probation


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class MetricResult:
    metric: str
    score: float              # 0-100
    evidence: str
    findings: str
    exemplary: bool = False   # True if score > EXEMPLARY_THRESHOLD
    breakdown: dict = field(default_factory=dict)  # optional detailed data


@dataclass
class AgentEvaluation:
    agent_id: str
    metrics: list             # list[MetricResult]
    overall_score: float
    strengths: list
    issues: list
    recommendations: list
    exemplary: bool = False   # True if overall_score > EXEMPLARY_THRESHOLD
    recommend_probation: bool = False

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "metrics": [
                {
                    "metric": m.metric,
                    "score": round(m.score, 2),
                    "evidence": m.evidence,
                    "findings": m.findings,
                    "exemplary": m.exemplary,
                }
                for m in self.metrics
            ],
            "overall_score": round(self.overall_score, 2),
            "strengths": self.strengths,
            "issues": self.issues,
            "recommendations": self.recommendations,
            "exemplary": self.exemplary,
            "recommend_probation": self.recommend_probation,
        }


@dataclass
class EvaluationReport:
    report_id: str
    project_id: str
    timestamp: str
    evaluator: str
    project_metrics: list         # list[MetricResult]
    agent_evaluations: list       # list[AgentEvaluation]
    systemic_findings: dict
    recommendations: dict
    overall_project_score: float

    def to_dict(self) -> dict:
        return {
            "report_id": self.report_id,
            "project_id": self.project_id,
            "timestamp": self.timestamp,
            "evaluator": self.evaluator,
            "overall_project_score": round(self.overall_project_score, 2),
            "project_metrics": [
                {
                    "metric": m.metric,
                    "score": round(m.score, 2),
                    "evidence": m.evidence,
                    "findings": m.findings,
                    "exemplary": m.exemplary,
                }
                for m in self.project_metrics
            ],
            "agent_evaluations": [a.to_dict() for a in self.agent_evaluations],
            "systemic_findings": self.systemic_findings,
            "recommendations": self.recommendations,
        }


# ---------------------------------------------------------------------------
# MetricsEngine
# ---------------------------------------------------------------------------

class MetricsEngine:
    """
    Computes evaluation metrics from project and agent data.
    All methods are pure (no I/O) — they take data, return scores.
    """

    # ------------------------------------------------------------------
    # Project-level metrics
    # ------------------------------------------------------------------

    def score_goal_achievement(
        self,
        success_criteria: list,
        completed_task_descriptions: list,
    ) -> MetricResult:
        """
        Score 0-100 based on how many success criteria are evidenced
        in completed tasks.

        Heuristic: for each success criterion, check if any completed
        task description mentions keywords from that criterion.
        Score = matched / total * 100.
        If no success criteria defined: score = 50 (unknown).
        """
        if not success_criteria:
            return MetricResult(
                metric="goal_achievement",
                score=50.0,
                evidence="No success criteria defined in specification",
                findings="Cannot assess goal achievement without success criteria",
            )

        matched = 0
        evidence_parts = []

        for criterion in success_criteria:
            criterion_lower = criterion.lower()
            keywords = [w for w in criterion_lower.split() if len(w) > 4]
            if not keywords:
                keywords = [criterion_lower]

            # Check if any completed task covers this criterion
            covered = any(
                any(kw in desc.lower() for kw in keywords)
                for desc in completed_task_descriptions
            )
            if covered:
                matched += 1
                evidence_parts.append(f"✓ '{criterion[:60]}'")
            else:
                evidence_parts.append(f"✗ '{criterion[:60]}' — no matching task")

        score = matched / len(success_criteria) * 100.0

        return MetricResult(
            metric="goal_achievement",
            score=score,
            evidence=f"{matched}/{len(success_criteria)} criteria evidenced in completed tasks",
            findings="; ".join(evidence_parts),
            exemplary=score > EXEMPLARY_THRESHOLD,
        )

    def score_acceptance_criteria_pass_rate(
        self,
        total_criteria: int,
        passed_criteria: int,
    ) -> MetricResult:
        if total_criteria == 0:
            return MetricResult(
                metric="acceptance_criteria_pass_rate",
                score=50.0,
                evidence="No acceptance criteria defined",
                findings="Cannot assess pass rate without acceptance criteria",
            )

        score = passed_criteria / total_criteria * 100.0
        return MetricResult(
            metric="acceptance_criteria_pass_rate",
            score=score,
            evidence=f"{passed_criteria}/{total_criteria} acceptance criteria passed",
            findings=(
                f"Pass rate: {score:.1f}%. "
                + ("All criteria met." if score == 100.0
                   else f"{total_criteria - passed_criteria} criteria not met.")
            ),
            exemplary=score > EXEMPLARY_THRESHOLD,
        )

    def score_scope_adherence(
        self,
        planned_task_count: int,
        completed_task_count: int,
        blocked_task_count: int,
        failed_task_count: int,
        over_effort_task_count: int,
    ) -> MetricResult:
        if planned_task_count == 0:
            return MetricResult(
                metric="scope_adherence",
                score=50.0,
                evidence="No tasks planned",
                findings="Cannot assess scope adherence without tasks",
            )

        completion_rate = completed_task_count / planned_task_count * 100.0
        deductions = (blocked_task_count + failed_task_count) * 10
        deductions += over_effort_task_count * 5
        score = max(0.0, completion_rate - deductions)

        findings_parts = [f"Task completion rate: {completion_rate:.1f}%"]
        if blocked_task_count:
            findings_parts.append(f"{blocked_task_count} blocked (−{blocked_task_count * 10}pts)")
        if failed_task_count:
            findings_parts.append(f"{failed_task_count} failed (−{failed_task_count * 10}pts)")
        if over_effort_task_count:
            findings_parts.append(f"{over_effort_task_count} over-effort (−{over_effort_task_count * 5}pts)")

        return MetricResult(
            metric="scope_adherence",
            score=score,
            evidence=f"{completed_task_count}/{planned_task_count} tasks completed",
            findings="; ".join(findings_parts),
            exemplary=score > EXEMPLARY_THRESHOLD,
        )

    def score_documentation_completeness(self, project_dir: Path) -> MetricResult:
        required = [
            ("intake/clarified_spec.yaml", "Clarified specification"),
            ("planning/product_plan.yaml", "Product plan"),
            ("execution/execution_plan.yaml", "Execution plan"),
        ]
        recommended = [("evaluation/evaluation_report.yaml", "Evaluation report"),]

        required_present = 0
        recommended_present = 0
        evidence_parts = []

        for rel_path, label in required:
            exists = (project_dir / rel_path).exists()
            if exists:
                required_present += 1
                evidence_parts.append(f"✓ {label}")
            else:
                evidence_parts.append(f"✗ {label} (required)")

        for rel_path, label in recommended:
            exists = (project_dir / rel_path).exists()
            if exists:
                recommended_present += 1
                evidence_parts.append(f"✓ {label} (recommended)")

        req_score = required_present / len(required) * 80.0 if required else 80.0
        rec_score = recommended_present / len(recommended) * 20.0 if recommended else 20.0
        score = req_score + rec_score

        return MetricResult(
            metric="documentation_completeness",
            score=score,
            evidence=f"{required_present}/{len(required)} required docs present",
            findings="; ".join(evidence_parts),
            exemplary=score > EXEMPLARY_THRESHOLD,
        )

    # (Other metric methods identical to the original implementation)

    def score_global_graph_contribution(self, project_id: str) -> MetricResult:
        try:
            from .graph_memory import GraphStore, GLOBAL_PROJECT_ID
            global_store = GraphStore(GLOBAL_PROJECT_ID)

            contributed = 0
            if global_store._g is not None:
                for _nid, attrs in global_store._g.nodes(data=True):
                    if attrs.get("project") == project_id or project_id in str(attrs.get("projects", "")):
                        contributed += 1
                edge_contributed = sum(
                    1 for _u, _v, edata in global_store._g.edges(data=True)
                    if edata.get("project") == project_id
                )
                contributed += edge_contributed // 2
            else:
                for _nid, attrs in getattr(global_store, "_nodes", {}).items():
                    if attrs.get("project") == project_id or project_id in str(attrs.get("projects", "")):
                        contributed += 1

            if global_store.has_node(project_id):
                contributed += 1

        except Exception:
            contributed = 0

        score = min(100.0, contributed * 5.0)

        if contributed == 0:
            findings = "Project has not yet contributed to the global graph. Run replay to back-populate."
        elif contributed < 5:
            findings = f"Minimal global graph presence ({contributed} nodes/edges). Consider richer episode recording."
        else:
            findings = f"Project contributed {contributed} nodes/edges to the global graph."

        return MetricResult(
            metric="global_graph_contribution",
            score=round(score, 1),
            evidence=f"contributed_entries={contributed}",
            findings=findings,
            exemplary=contributed >= 20,
            breakdown={"contributed_entries": contributed},
        )


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="metrics_engine",
        description="Metrics Engine CLI — score projects and agents",
    )
    sub = p.add_subparsers(dest="command", required=True)

    sp = sub.add_parser("score-project", help="Score project-level metrics")
    sp.add_argument("--project-id", required=True)

    sa = sub.add_parser("score-agent", help="Score a single agent")
    sa.add_argument("--project-id", required=True)
    sa.add_argument("--agent-id", required=True)

    sr = sub.add_parser("report", help="Produce a full evaluation report")
    sr.add_argument("--project-id", required=True)
    sr.add_argument("--agents", default=None,
                    help="Comma-separated agent IDs (default: all active)")
    sr.add_argument("--save", action="store_true",
                    help="Write report to disk")

    return p


def _load_project_data(project_id: str):
    """Load shared state and task board data for a project."""
    from .shared_state_manager import SharedStateManager
    from core.config import get_projects_dir

    sm = SharedStateManager(project_id)
    state = sm.load()
    project_dir = get_projects_dir() / project_id

    board_path = project_dir / "execution" / "task_board.yaml"
    if board_path.exists():
        with open(board_path, encoding="utf-8") as f:
            board_data = yaml.safe_load(f) or {}
    else:
        board_data = {"tasks": [], "milestones": []}

    return state, project_dir, board_data


def main_cli(args=None) -> int:
    p = _build_parser()
    ns = p.parse_args(args)
    engine = MetricsEngine()

    if ns.command == "score-project":
        state, project_dir, board_data = _load_project_data(ns.project_id)
        metrics = engine.evaluate_project(
            ns.project_id, state, project_dir, board_data
        )
        print(f"\nProject metrics for {ns.project_id}:")
        for m in metrics:
            star = " *" if m.exemplary else ""
            print(f"  {m.metric:40} {m.score:6.1f}{star}")
            print(f"    {m.findings}")
        avg = engine.aggregate_project_score(metrics)
        print(f"\n  Overall project score: {avg:.1f}")
        return 0

    if ns.command == "score-agent":
        state, _, board_data = _load_project_data(ns.project_id)
        result = engine.evaluate_agent(ns.agent_id, state, board_data)
        print(f"\nAgent evaluation: {ns.agent_id}")
        for m in result.metrics:
            star = " *" if m.exemplary else ""
            print(f"  {m.metric:40} {m.score:6.1f}{star}")
        print(f"\n  Overall score   : {result.overall_score:.1f}")
        print(f"  Strengths       : {', '.join(result.strengths) or 'none'}")
        print(f"  Issues          : {', '.join(result.issues) or 'none'}")
        print(f"  Exemplary       : {result.exemplary}")
        print(f"  Probation risk  : {result.recommend_probation}")
        return 0

    if ns.command == "report":
        state, project_dir, board_data = _load_project_data(ns.project_id)

        if ns.agents:
            agents = [a.strip() for a in ns.agents.split(",")]
        else:
            wf = state.get("workflow", {})
            agents = list({
                h.get("from_agent") for h in wf.get("handoff_history", [])
                if h.get("from_agent") != "system"
            })

        report = engine.produce_report(
            ns.project_id, state, project_dir, board_data, agents
        )

        print(f"\nEvaluation Report: {report.report_id}")
        print(f"Overall project score: {report.overall_project_score:.1f}")
        print("\nProject metrics:")
        for m in report.project_metrics:
            star = " *" if m.exemplary else ""
            print(f"  {m.metric:40} {m.score:6.1f}{star}")
        print("\nAgent evaluations:")
        for ae in report.agent_evaluations:
            flag = " [EXEMPLARY]" if ae.exemplary else ""
            flag += " [PROBATION RISK]" if ae.recommend_probation else ""
            print(f"  {ae.agent_id:30} {ae.overall_score:6.1f}{flag}")

        if ns.save:
            path = engine.save_report(report, project_dir)
            print(f"\n[ok] Report saved: {path}")
        return 0

    p.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main_cli())
