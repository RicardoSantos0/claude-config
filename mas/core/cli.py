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

# Load .env at repo root so ANTHROPIC_API_KEY is available to agent_runner
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(ROOT / ".env")
except Exception:
    pass

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
    from core.engine.shared_state_manager import SharedStateManager
    sm = SharedStateManager(project_id)
    return sm.load()


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------

@click.group()
@click.version_option("0.2.0", prog_name="mas")
def main():
    """Governed Multi-Agent Delivery System."""


# ---------------------------------------------------------------------------
# mas db (subgroup)
# ---------------------------------------------------------------------------

@main.group()
def db():
    """Database maintenance commands."""


# ---------------------------------------------------------------------------
# mas init
# ---------------------------------------------------------------------------

@main.command()
@click.argument("name_or_id")
@click.option("--request-id", default=None,
              help="Optional request ID (auto-generated if omitted)")
@click.option("--mode", default="standard",
              type=click.Choice(["standard", "lite"], case_sensitive=False),
              help="Project mode: 'standard' (9-phase, full governance) or "
                   "'lite' (3-phase: intake → execution → closed, no consultation).")
def init(name_or_id: str, request_id: str, mode: str):
    """Initialize a new project and its shared state.

    NAME_OR_ID can be either a human-readable slug (e.g. 'website-redesign')
    or a full project ID (e.g. 'proj-20260410-001-website-redesign').

    If a slug is provided, the system generates the full project ID
    with today's date and next available sequence number.

    Examples:
        mas init session-scheduler
        mas init --mode=lite quick-fix
        mas init proj-20260410-001-session-scheduler
    """
    from core.engine.shared_state_manager import SharedStateManager

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

    sm.initialize(request_id=request_id, mode=mode)
    mode_tag = f" [{mode}]" if mode == "lite" else ""
    click.echo(f"[ok] Project initialized{mode_tag}: {sm.project_dir}")
    click.echo(f"     Project ID  : {project_id}")
    click.echo(f"     State file  : {sm.state_path}")
    click.echo(f"     Request ID  : {request_id}")
    click.echo(f"     Mode        : {mode}")


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
    proj_mode = wf.get("mode", "standard")

    pending_handoffs = [
        h for h in wf.get("handoff_history", [])
        if h.get("status") == "pending"
    ]
    completed_phases = wf.get("completed_phases", [])
    violations = state.get("_meta", {}).get("governance_violations", [])

    mode_tag = " [lite]" if proj_mode == "lite" else ""
    # Token usage summary (D1/D3)
    from core.db import query_token_usage
    usage = query_token_usage(project_id)
    live_calls = usage.get("live_calls", 0)
    dry_calls  = usage.get("dry_calls", 0)
    total_tok  = usage.get("total", 0)

    click.echo(f"\nProject  : {project_id}")
    click.echo(f"Status   : {proj_status}")
    click.echo(f"Phase    : {phase}{mode_tag}")
    click.echo(f"Mode     : {proj_mode}")
    click.echo(f"Owner    : {owner}")
    click.echo(f"Updated  : {updated}")
    click.echo(f"Completed phases : {', '.join(completed_phases) or 'none'}")
    click.echo(f"Pending handoffs : {len(pending_handoffs)}")
    click.echo(f"Violations       : {len(violations)}")

    # Dry/live accounting
    total_calls = live_calls + dry_calls
    if total_calls > 0:
        dry_pct = dry_calls / total_calls * 100
        click.echo(f"Agent calls      : {total_calls}  (live: {live_calls}, dry: {dry_calls}, dry%: {dry_pct:.1f}%)")
    click.echo(f"Tokens (total)   : {total_tok:,}")

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
    from core.engine.shared_state_manager import SharedStateManager

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
    from core.engine.handoff_engine import HandoffEngine
    from core.engine.shared_state_manager import SharedStateManager

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
    from core.engine.shared_state_manager import SharedStateManager

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
# mas tokens
# ---------------------------------------------------------------------------

@main.command()
@click.argument("project_id")
def tokens(project_id: str):
    """Show token usage summary for a project.

    Example: mas tokens proj-20260415-001
    """
    _require_project(project_id)
    from core.db import query_token_usage

    usage = query_token_usage(project_id)
    total        = usage.get("total", 0)
    prompt       = usage.get("total_prompt", 0)
    completion   = usage.get("total_completion", 0)
    calls        = usage.get("calls", 0)
    dry_calls    = usage.get("dry_calls", 0)
    live_calls   = usage.get("live_calls", 0)

    click.echo(f"\nToken usage — {project_id}")
    click.echo(f"  Total calls      : {calls}  (live: {live_calls}, dry: {dry_calls})")
    click.echo(f"  Prompt tokens    : {prompt:,}")
    click.echo(f"  Completion tokens: {completion:,}")
    click.echo(f"  Total tokens     : {total:,}")

    if live_calls + dry_calls > 0:
        dry_pct = dry_calls / (live_calls + dry_calls) * 100
        click.echo(f"  Dry-run ratio    : {dry_pct:.1f}%")


# ---------------------------------------------------------------------------
# mas db rebuild-fts
# ---------------------------------------------------------------------------

@db.command("rebuild-fts")
def rebuild_fts():
    """Rebuild the FTS5 index from agent_events (safe to run at any time).

    Example: mas db rebuild-fts
    """
    from core.utils.log_helpers import _get_connection, DB_PATH

    conn = _get_connection(DB_PATH)
    try:
        conn.execute("INSERT INTO agent_events_fts(agent_events_fts) VALUES ('rebuild')")
        conn.commit()
        count = conn.execute("SELECT COUNT(*) FROM agent_events").fetchone()[0]
        click.echo(f"[ok] FTS5 index rebuilt — {count} rows indexed.")
    except Exception as exc:
        click.echo(f"[error] rebuild-fts failed: {exc}", err=True)
        sys.exit(1)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# mas db migrate-graph
# ---------------------------------------------------------------------------

@db.command("migrate-graph")
@click.option("--dry-run", is_flag=True, default=False,
              help="Show what would be migrated without writing to SQLite.")
def migrate_graph(dry_run: bool):
    """Migrate global_graph.yaml nodes/edges into agent_graph SQLite tables.

    Creates agent_graph and agent_graph_edges tables if they do not exist.
    Migration is idempotent (INSERT OR IGNORE).

    Example:
        mas db migrate-graph
        mas db migrate-graph --dry-run
    """
    import yaml as _yaml
    from core.utils.log_helpers import _get_connection, DB_PATH

    graph_path = ROOT / "data" / "global_graph.yaml"
    if not graph_path.exists():
        click.echo(f"[warn] {graph_path} not found — nothing to migrate.")
        return

    with open(graph_path, encoding="utf-8") as f:
        graph_data = _yaml.safe_load(f) or {}

    nodes = graph_data.get("nodes", [])
    edges = graph_data.get("edges", [])

    if dry_run:
        click.echo(f"[dry-run] Would migrate {len(nodes)} nodes, {len(edges)} edges.")
        return

    conn = _get_connection(DB_PATH)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_graph (
                id      TEXT PRIMARY KEY,
                type    TEXT,
                label   TEXT,
                meta    TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_graph_edges (
                id          TEXT PRIMARY KEY,
                source      TEXT,
                target      TEXT,
                relation    TEXT,
                meta        TEXT
            )
        """)

        import json as _json
        node_count = 0
        for node in nodes:
            nid = node.get("id") or node.get("node_id", "")
            if not nid:
                continue
            conn.execute(
                "INSERT OR IGNORE INTO agent_graph(id, type, label, meta) VALUES (?, ?, ?, ?)",
                (nid, node.get("type", ""), node.get("label", nid),
                 _json.dumps({k: v for k, v in node.items() if k not in ("id", "node_id", "type", "label")})),
            )
            node_count += 1

        edge_count = 0
        for edge in edges:
            eid = edge.get("id") or edge.get("edge_id", "")
            if not eid:
                continue
            conn.execute(
                "INSERT OR IGNORE INTO agent_graph_edges(id, source, target, relation, meta) VALUES (?, ?, ?, ?, ?)",
                (eid, edge.get("source", ""), edge.get("target", ""),
                 edge.get("relation", edge.get("type", "")),
                 _json.dumps({k: v for k, v in edge.items()
                              if k not in ("id", "edge_id", "source", "target", "relation", "type")})),
            )
            edge_count += 1

        conn.commit()
        click.echo(f"[ok] Graph migrated — {node_count} nodes, {edge_count} edges written to {DB_PATH}.")
    except Exception as exc:
        click.echo(f"[error] migrate-graph failed: {exc}", err=True)
        sys.exit(1)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# mas run — autonomous orchestration loop
# ---------------------------------------------------------------------------

@main.command()
@click.argument("project_id")
@click.option("--max-steps", default=50, show_default=True,
              help="Hard stop after N agent steps.")
@click.option("--dry-run", is_flag=True, default=False,
              help="Dry-run mode — no real Anthropic API calls.")
@click.option("--auto", is_flag=True, default=False,
              help="Skip human confirmation at phase boundaries.")
@click.option("--phase", "target_phase", default=None, metavar="PHASE",
              help="Stop after this phase completes (e.g. 'specification').")
def run(project_id: str, max_steps: int, dry_run: bool,
        auto: bool, target_phase: str | None):
    """Run the autonomous orchestration loop for a project.

    Drives the project through intake -> specification -> planning phases,
    pausing at each phase boundary for human confirmation (unless --auto).
    Integrates consultation and NotebookLM knowledge requests.

    Examples:

    \b
        mas run proj-20260415-005-my-project
        mas run proj-20260415-005-my-project --dry-run --auto --max-steps 10
        mas run proj-20260415-005-my-project --phase specification
    """
    _require_project(project_id)

    from core.engine.orchestration_loop import OrchestrationLoop, LoopConfig, StopReason

    config = LoopConfig(
        project_id=project_id,
        max_steps=max_steps,
        dry_run=dry_run,
        auto=auto,
        target_phase=target_phase,
    )

    click.echo(f"\n[mas run] {project_id}")
    if dry_run:
        click.echo("  mode: dry-run (no real API calls)")
    if auto:
        click.echo("  mode: auto (phase boundaries skipped)")
    click.echo("")

    loop = OrchestrationLoop(config)
    result = loop.run()

    click.echo(f"\n[mas run] stopped at step {result.stopped_at_step}")
    click.echo(f"  reason : {result.reason.value}")
    click.echo(f"  agent  : {result.last_agent}")
    click.echo(f"  phase  : {result.last_phase}")
    if result.message:
        click.echo(f"  message: {result.message}")

    if result.reason == StopReason.UNANIMOUS_RISK:
        click.echo("\n[GOVERNANCE] Unanimous high-risk — human review required.", err=True)
        sys.exit(2)
    elif result.reason == StopReason.HUMAN_ESCALATION:
        click.echo("\n[GOVERNANCE] Human escalation required.", err=True)
        sys.exit(2)
    elif result.reason == StopReason.ERROR:
        sys.exit(1)


# ---------------------------------------------------------------------------
# Entry point guard (for `uv run python core/cli.py`)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    main()
