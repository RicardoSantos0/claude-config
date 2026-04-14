"""Compatibility wrapper: training_engine moved to core.engine.training_engine"""

from core.engine.training_engine import *  # noqa: F401,F403


def _cli_analyze(args: list[str]) -> None:
    import argparse
    from pathlib import Path
    import yaml
    import sys

    p = argparse.ArgumentParser(prog="training_engine analyze")
    p.add_argument("--project-id", required=True)
    p.add_argument("--projects-root", default="projects")
    ns = p.parse_args(args)

    project_dir = Path(ns.projects_root) / ns.project_id
    report_path = project_dir / "evaluation" / "evaluation_report.yaml"

    if not report_path.exists():
        print(f"No evaluation report found at {report_path}")
        sys.exit(1)

    with open(report_path) as f:
        report_data = yaml.safe_load(f)

    engine = TrainingEngine()
    proposals = engine.analyze_evaluation_report(report_data, project_id=ns.project_id)
    brief_path = engine.produce_training_brief(ns.project_id, proposals, project_dir)
    added = engine.update_backlog(proposals)

    print(f"Analysis complete: {len(proposals)} proposal(s) produced.")
    print(f"Training brief: {brief_path}")
    print(f"Backlog: {added} new proposal(s) added.")
    for p in engine.prioritize(proposals):
        prefix = "[SYSTEMIC]" if p.systemic else ""
        print(f"  P{p.priority} {prefix} [{p.proposal_type}] {p.description[:80]}...")


def _cli_backlog(args: list[str]) -> None:
    import argparse
    import sys

    p = argparse.ArgumentParser(prog="training_engine backlog")
    p.add_argument("--status", default=None, choices=list(PROPOSAL_STATUSES))
    ns = p.parse_args(args)

    engine = TrainingEngine()
    backlog = engine.load_backlog()
    proposals = backlog.get("proposals", [])

    if ns.status:
        proposals = [p for p in proposals if p["status"] == ns.status]

    if not proposals:
        print("No proposals in backlog" + (f" with status '{ns.status}'" if ns.status else "") + ".")
        return

    print(f"Training backlog ({len(proposals)} proposal(s)):\n")
    for p in proposals:
        prefix = "[SYSTEMIC]" if p.get("systemic") else ""
        print(
            f"  [{p['proposal_id']}] P{p['priority']} {prefix} "
            f"[{p['proposal_type']}] [{p['status']}] "
            f"{p['description'][:70]}..."
        )


def _cli_approve(args: list[str]) -> None:
    import argparse
    import sys

    p = argparse.ArgumentParser(prog="training_engine approve")
    p.add_argument("--proposal-id", required=True)
    p.add_argument("--authorized-by", required=True)
    ns = p.parse_args(args)

    engine = TrainingEngine()
    ok = engine.approve_proposal(ns.proposal_id, ns.authorized_by)
    if ok:
        print(f"[ok] Proposal '{ns.proposal_id}' approved by {ns.authorized_by}.")
    else:
        print(f"[fail] Could not approve '{ns.proposal_id}'. Check proposal_id, status, and authorization.")
        sys.exit(1)


def _cli_reject(args: list[str]) -> None:
    import argparse
    import sys

    p = argparse.ArgumentParser(prog="training_engine reject")
    p.add_argument("--proposal-id", required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--authorized-by", required=True)
    ns = p.parse_args(args)

    engine = TrainingEngine()
    ok = engine.reject_proposal(ns.proposal_id, ns.reason, ns.authorized_by)
    if ok:
        print(f"[ok] Proposal '{ns.proposal_id}' rejected: {ns.reason}")
    else:
        print(f"[fail] Could not reject '{ns.proposal_id}'. Check proposal_id, status, and authorization.")
        sys.exit(1)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python core/training_engine.py <analyze|backlog|approve|reject> [options]")
        sys.exit(1)

    cmd = sys.argv[1]
    rest = sys.argv[2:]

    dispatch = {
        "analyze": _cli_analyze,
        "backlog": _cli_backlog,
        "approve": _cli_approve,
        "reject": _cli_reject,
    }

    if cmd not in dispatch:
        print(f"Unknown command: {cmd}")
        sys.exit(1)

    dispatch[cmd](rest)
