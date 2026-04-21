"""
Generic capability-gap seeder.

Usage:
    python mas/tools/seed_capability.py <path/to/specs/gaps.yaml>

Reads a project-neutral gaps spec, generates capability gap certificates via
CapabilityRegistry (roster search + cert schema), saves them to disk, then
writes the HR deployment plan to shared state and advances the workflow phase.

Spec field notes:
  tags[]            — capability tags used by CapabilityRegistry for roster search
  proposed_agent_id — stored in deployment plan only; not part of the cert schema
  trust_tier        — stored in deployment plan only; spawner decision post-cert

# --- FUTURE INTENT (Option B) ---
# This script is a manual shim. The correct long-term solution is to have
# hr_agent produce gap certificates and the deployment plan autonomously
# during the capability_discovery phase, driven by the project brief and
# roster scan — making this file unnecessary. Once the orchestration loop
# invokes hr_agent and persists its outputs automatically, delete this tool.
# --------------------------------
"""
import sys
import argparse
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))
from core.engine.capability_registry import CapabilityRegistry
from core.engine.shared_state_manager import SharedStateManager


def load_spec(spec_path: Path) -> dict:
    with spec_path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def seed(spec_path: Path) -> None:
    spec = load_spec(spec_path)

    pid = spec["project_id"]
    next_phase = spec["next_phase"]
    gaps = spec["gaps"]
    available_agents = spec.get("available_agents", [])

    registry = CapabilityRegistry()
    sm = SharedStateManager(pid)

    deployment_plan = []
    cert_summaries = []

    for gap in gaps:
        cert = registry.produce_gap_certificate(
            need_description=gap["description"],
            required_capabilities=gap["tags"],
            project_id=pid,
            requested_by="hr_agent",
        )
        cert_path = registry.save_gap_certificate(cert, pid)
        rel_path = str(cert_path.relative_to(Path(__file__).parent.parent))

        deployment_plan.append({
            "need": gap["capability_needed"],
            "status": "gap_certified",
            "cert_id": cert.certificate_id,
            "cert_path": rel_path,
            "proposed_agent": gap["proposed_agent_id"],
            "sprint": gap["sprint"],
            "parallel_group": gap["parallel_group"],
            "trust_tier": gap["trust_tier"],
            "rationale": gap["rationale"],
            "spawn_recommendation": (
                f"Spawn {gap['proposed_agent_id']} as {gap['trust_tier']} "
                f"for Sprint {gap['sprint']}."
            ),
        })
        cert_summaries.append({
            "cert_id": cert.certificate_id,
            "proposed_agent": gap["proposed_agent_id"],
            "sprint": gap["sprint"],
            "status": "open",
        })
        print(f"  [seed_capability] cert: {cert.certificate_id} -> {gap['proposed_agent_id']}")

    sm.write("hr_agent", "capability", "deployment_plan", deployment_plan)
    sm.write("hr_agent", "capability", "capability_gap_certificates", cert_summaries)
    sm.write("hr_agent", "capability", "available_skills_snapshot", available_agents)

    sm.snapshot("capability_discovery")
    sm.write("master_orchestrator", "core_identity", "current_phase", next_phase)
    sm.system_append("workflow", "completed_phases", "capability_discovery")

    print(f"[seed_capability] {pid}: {len(gaps)} gaps certified -> {next_phase}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed capability gaps from a YAML spec.")
    parser.add_argument("spec", type=Path, help="Path to gaps.yaml spec file")
    args = parser.parse_args()

    if not args.spec.exists():
        print(f"ERROR: spec not found: {args.spec}", file=sys.stderr)
        sys.exit(1)

    seed(args.spec)


if __name__ == "__main__":
    main()
