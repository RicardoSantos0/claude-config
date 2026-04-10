"""
MAS CLI — Governed Multi-Agent Delivery System
Entry point: uv run mas <command>

Commands
--------
  init      Create and initialize a new project
  status    Show project status and workflow state
  state     Read a value from shared state
  pending   List pending handoffs
  snapshot  Save a timestamped snapshot of shared state
  roster    Show the capability registry summary
"""

import re
import sys
from pathlib import Path
from datetime import datetime, timezone

import click
import yaml

ROOT = Path(__file__).parent.parent

# Max slug length (lowercase alphanum + hyphens)
_MAX_SLUG_LEN = 40
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$")
_FULL_ID_RE = re.compile(r"^proj-\d{8}-\d{3}-.+$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_projects_dir() -> Path:
    from core.config import get_projects_dir
    return get_projects_dir()


def _slugify(text: str) -> str:
    """Turn free-form text into a URL-safe slug (max _MAX_SLUG_LEN chars)."""
    s = text.lower().strip()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = s.strip("-")
    return s[:_MAX_SLUG_LEN]


def _next_sequence(projects_dir: Path, date_str: str) -> int:
    """Scan existing project dirs for today's date prefix and return max+1."""
    prefix = f"proj-{date_str}-"
    max_seq = 0
    if projects_dir.exists():
        for d in projects_dir.iterdir():
            if d.is_dir() and d.name.startswith(prefix):
                # Extract sequence: proj-YYYYMMDD-NNN-slug → NNN
                parts = d.name.split("-", 3)  # ['proj', 'YYYYMMDD', 'NNN', 'slug...']
                if len(parts) >= 3:
                    try:
                        max_seq = max(max_seq, int(parts[2]))
                    except ValueError:
                        pass
    return max_seq + 1


def _generate_project_id(slug: str) -> str:
    """Generate proj-YYYYMMDD-NNN-slug from a slug."""
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    seq = _next_sequence(_get_projects_dir(), date_str)
    return f"proj-{date_str}-{seq:03d}-{slug}"


def _require_project(project_id: str) -> Path:
    """Return project dir or exit with a clear error."""
    p = _get_projects_dir() / project_id
    if not p.exists():
        click.echo(f"[error] Project '{project_id}' not found in {_get_projects_dir()}", err=True)
        sys.exit(1)
    return p


def _load_state(project_id: str) -> dict:
    from core.shared_state_manager import SharedStateManager
    sm = SharedStateManager(project_id)
    return sm.load()


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------

@click.group()
@click.version_option("0.1.0", prog_name="mas")
def main():
    """Governed Multi-Agent Delivery System."""


# ---------------------------------------------------------------------------
# mas init
# ---------------------------------------------------------------------------

@main.command()
@click.argument("name_or_id")
@click.option("--request-id", default=None,
              help="Optional request ID (auto-generated if omitted)")
def init(name_or_id: str, request_id: str):
    """Initialize a new project and its shared state.

    NAME_OR_ID can be either a human-readable slug (e.g. 'website-redesign')
    or a full project ID (e.g. 'proj-20260410-001-website-redesign').

    If a slug is provided, the system generates the full project ID
    with today's date and next available sequence number.

    Examples:
        mas init session-scheduler
        mas init proj-20260410-001-session-scheduler
    """
    from core.shared_state_manager import SharedStateManager

    # Determine project_id: if it looks like a full ID, use as-is; else generate
    if _FULL_ID_RE.match(name_or_id):
        project_id = name_or_id
    else:
        slug = _slugify(name_or_id)
        if not slug:
            click.echo("[error] Invalid slug — must contain at least one alphanumeric character.", err=True)
            sys.exit(1)
        project_id = _generate_project_id(slug)

    if request_id is None:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        request_id = f"req-{ts}"

    sm = SharedStateManager(project_id)
    if sm.project_dir.exists():
        click.echo(f"[warn] Project '{project_id}' already exists — skipping init.", err=True)
        sys.exit(0)

    sm.initialize(request_id=request_id)
    click.echo(f"[ok] Project initialized: {sm.project_dir}")
    click.echo(f"     Project ID  : {project_id}")
    click.echo(f"     State file  : {sm.state_path}")
    click.echo(f"     Request ID  : {request_id}")


# ---------------------------------------------------------------------------
# mas status
# ---------------------------------------------------------------------------

@main.command()
@click.argument("project_id")
def status(project_id: str):
    """Show the current status and phase of a project.

    Example: mas status proj-20260409-001
    """
    _require_project(project_id)
    state = _load_state(project_id)

    ci = state.get("core_identity", {})
    wf = state.get("workflow", {})
    meta = state.get("_meta", {})

    phase = ci.get("current_phase", "—")
    owner = wf.get("current_owner", "—")
    proj_status = ci.get("status", "—")
    updated = meta.get("updated_at", "—")

    pending_handoffs = [
        h for h in wf.get("handoff_history", [])
        if h.get("status") == "pending"
    ]
    completed_phases = wf.get("completed_phases", [])
    violations = state.get("_meta", {}).get("governance_violations", [])

    click.echo(f"\nProject  : {project_id}")
    click.echo(f"Status   : {proj_status}")
    click.echo(f"Phase    : {phase}")
    click.echo(f"Owner    : {owner}")
    click.echo(f"Updated  : {updated}")
    click.echo(f"Completed phases : {', '.join(completed_phases) or 'none'}")
    click.echo(f"Pending handoffs : {len(pending_handoffs)}")
    click.echo(f"Violations       : {len(violations)}")

    if pending_handoffs:
        click.echo("\nPending handoffs:")
        for h in pending_handoffs:
            click.echo(
                f"  [{h['handoff_id']}] "
                f"{h['from_agent']} → {h['to_agent']} "
                f"({h.get('task_description', '')})"
            )


# ---------------------------------------------------------------------------
# mas state
# ---------------------------------------------------------------------------

@main.command()
@click.argument("project_id")
@click.argument("path")
def state(project_id: str, path: str):
    """Read a value from shared state using dot-notation path.

    Example: mas state proj-20260409-001 project_definition.project_goal
    """
    _require_project(project_id)
    from core.shared_state_manager import SharedStateManager

    sm = SharedStateManager(project_id)
    value = sm.read(path)

    if value is None:
        click.echo(f"[none] {path} not set")
    else:
        click.echo(yaml.dump({path: value}, default_flow_style=False,
                              allow_unicode=True).strip())


# ---------------------------------------------------------------------------
# mas pending
# ---------------------------------------------------------------------------

@main.command()
@click.argument("project_id")
def pending(project_id: str):
    """List all pending handoffs for a project.

    Example: mas pending proj-20260409-001
    """
    _require_project(project_id)
    from core.handoff_engine import HandoffEngine
    from core.shared_state_manager import SharedStateManager

    sm = SharedStateManager(project_id)
    engine = HandoffEngine()
    pending_list = engine.get_pending(sm)

    if not pending_list:
        click.echo("[ok] No pending handoffs.")
        return

    click.echo(f"\n{len(pending_list)} pending handoff(s):")
    for h in pending_list:
        click.echo(
            f"\n  ID      : {h['handoff_id']}"
            f"\n  From    : {h['from_agent']}"
            f"\n  To      : {h['to_agent']}"
            f"\n  Phase   : {h.get('phase', '—')}"
            f"\n  Task    : {h.get('task_description', '—')}"
            f"\n  Created : {h.get('created_at', '—')}"
        )


# ---------------------------------------------------------------------------
# mas snapshot
# ---------------------------------------------------------------------------

@main.command()
@click.argument("project_id")
@click.option("--phase", default="manual",
              help="Phase label for the snapshot filename (default: manual)")
def snapshot(project_id: str, phase: str):
    """Save a timestamped snapshot of shared state.

    Example: mas snapshot proj-20260409-001 --phase pre-planning
    """
    _require_project(project_id)
    from core.shared_state_manager import SharedStateManager

    sm = SharedStateManager(project_id)
    snap_path = sm.snapshot(phase=phase)
    click.echo(f"[ok] Snapshot saved: {snap_path}")


# ---------------------------------------------------------------------------
# mas roster
# ---------------------------------------------------------------------------

@main.command()
@click.option("--status", "filter_status", default=None,
              help="Filter by status: active | probation | retired")
def roster(filter_status: str):
    """Show the capability registry summary.

    Example: mas roster
             mas roster --status active
    """
    registry_path = ROOT / "roster" / "registry_index.yaml"
    if not registry_path.exists():
        click.echo("[error] registry_index.yaml not found", err=True)
        sys.exit(1)

    with open(registry_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    reg = data.get("registry", {})
    counts = data.get("counts", {})

    click.echo(f"\nRoster Registry  v{reg.get('version', '?')}")
    click.echo(f"Last updated     : {reg.get('last_updated') or '—'}")
    click.echo(f"Active agents    : {counts.get('active_agents', 0)}")
    click.echo(f"Active skills    : {counts.get('active_skills', 0)}")
    click.echo(f"Retired agents   : {counts.get('retired_agents', 0)}")
    click.echo(f"Spawned total    : {counts.get('spawned_total', 0)}")

    agents = reg.get("agents", [])
    if filter_status:
        agents = [a for a in agents if a.get("status") == filter_status]

    if agents:
        click.echo(f"\nAgents ({len(agents)}):")
        for a in agents:
            perf = a.get("performance_score")
            perf_str = f"  score={perf:.1f}" if perf is not None else ""
            click.echo(
                f"  [{a.get('status', '?'):10}] {a['agent_id']}  "
                f"{a.get('trust_tier', '?')}{perf_str}"
            )
    else:
        click.echo("\nNo agents registered yet.")


# ---------------------------------------------------------------------------
# Entry point guard (for `uv run python core/cli.py`)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    main()
