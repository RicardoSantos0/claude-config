"""Compatibility wrapper: consultation_engine moved to core.engine.consultation_engine"""

from core.engine.consultation_engine import *  # noqa: F401,F403


def _cli_create(args: list[str]) -> None:
    import argparse
    from pathlib import Path
    p = argparse.ArgumentParser(prog="consultation_engine create")
    p.add_argument("--project-id", required=True)
    p.add_argument("--question", required=True)
    p.add_argument("--decision-type", required=True)
    p.add_argument("--projects-root", default="projects")
    p.add_argument("--domain", default="software_engineering")
    ns = p.parse_args(args)

    engine = ConsultationEngine()
    request = engine.create_request(
        project_id=ns.project_id,
        question=ns.question,
        context={},
        decision_type=ns.decision_type,
        domain_context=engine.load_domain_context(ns.domain),
    )

    project_dir = Path(ns.projects_root) / ns.project_id
    path = engine.save_request(request, project_dir)

    print(f"[ok] Consultation request created: {request.request_id}")
    print(f"  Decision type: {request.decision_type} ({'mandatory' if request.mandatory else 'recommended'})")
    print(f"  Consultants: {', '.join(request.consultants_selected)}")
    print(f"  Saved to: {path}")


def _cli_show(args: list[str]) -> None:
    import argparse
    import yaml
    import sys
    from pathlib import Path
    p = argparse.ArgumentParser(prog="consultation_engine show")
    p.add_argument("--project-id", required=True)
    p.add_argument("--request-id", required=True)
    p.add_argument("--projects-root", default="projects")
    ns = p.parse_args(args)

    engine = ConsultationEngine()
    project_dir = Path(ns.projects_root) / ns.project_id
    data = engine.load_request(project_dir, ns.request_id)

    if not data:
        print(f"Request '{ns.request_id}' not found.")
        sys.exit(1)

    print(yaml.dump(data, default_flow_style=False, sort_keys=False))


def _cli_check_risk(args: list[str]) -> None:
    import argparse
    import sys
    from pathlib import Path
    p = argparse.ArgumentParser(prog="consultation_engine check-risk")
    p.add_argument("--project-id", required=True)
    p.add_argument("--request-id", required=True)
    p.add_argument("--projects-root", default="projects")
    ns = p.parse_args(args)

    engine = ConsultationEngine()
    project_dir = Path(ns.projects_root) / ns.project_id
    data = engine.load_request(project_dir, ns.request_id)

    if not data:
        print(f"Request '{ns.request_id}' not found.")
        sys.exit(1)

    responses = data.get("responses", {})
    if not responses:
        print("No responses recorded yet.")
        return

    for cid, r in responses.items():
        lvl = r.get("risk_level", "none")
        print(f"  {cid}: {lvl}")

    unanimous = all(r.get("risk_level") == "high" for r in responses.values())
    print(f"\nUnanimous high-risk: {unanimous}")
    if unanimous:
        print("*** HUMAN ESCALATION REQUIRED — Master cannot override unanimous high-risk ***)")


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python core/consultation_engine.py <create|show|check-risk> [options]")
        sys.exit(1)

    cmd = sys.argv[1]
    rest = sys.argv[2:]

    dispatch = {
        "create": _cli_create,
        "show": _cli_show,
        "check-risk": _cli_check_risk,
    }

    if cmd not in dispatch:
        print(f"Unknown command: {cmd}")
        sys.exit(1)

    dispatch[cmd](rest)
