"""
MAS Database — Central SQLite access layer.

Single import point for all database operations. Every module that needs
to read or write the event log imports from here, not from log_helpers directly.

Database: mas/data/episodic.db

Tables:
  agent_events    — every handoff, agent call, phase transition, consultation
  episodic_events — migrated history (read-only, commsopt migration)

Public API:
  append_event(project_id, agent_id, action_type, intent, ...)  → action_id
  query_events(project_id, agent_id, action_type, limit) → list[dict]
  query_project_history(project_id, limit)  → list[dict]  (chronological)
  query_agent_context(project_id, agent_id, limit) → list[dict]
  format_events_for_prompt(events) → str
"""

from pathlib import Path
from typing import Optional

from core.utils.log_helpers import (
    DB_PATH,
    init_db,
    append_event,
    query_events,
    query_by_action_id,
)

__all__ = [
    "DB_PATH",
    "init_db",
    "append_event",
    "query_events",
    "query_by_action_id",
    "query_project_history",
    "query_agent_context",
    "format_events_for_prompt",
]


def query_project_history(
    project_id: str,
    limit: int = 20,
    db_path: Path = DB_PATH,
) -> list[dict]:
    """
    Return the most recent N events for a project, in chronological order.
    Use this in agent context injection — agents see what happened before them.
    """
    rows = query_events(project_id=project_id, limit=limit, db_path=db_path)
    return list(reversed(rows))  # query_events returns newest-first; reverse for agents


def query_agent_context(
    project_id: str,
    agent_id: str,
    limit: int = 10,
    db_path: Path = DB_PATH,
) -> list[dict]:
    """
    Return the most recent N events for a specific agent on a project.
    Use to give an agent its own recent history.
    """
    rows = query_events(project_id=project_id, agent_id=agent_id,
                        limit=limit, db_path=db_path)
    return list(reversed(rows))


def format_events_for_prompt(events: list[dict]) -> str:
    """
    Format a list of DB event rows as a compact string for prompt injection.
    Returns at most the last 5 events to stay within token budget.
    """
    if not events:
        return "(no prior events recorded)"
    lines = []
    for e in events[-5:]:
        ts = (e.get("timestamp") or "")[:16]       # YYYY-MM-DDTHH:MM
        agent = e.get("agent_id") or "?"
        action = e.get("action_type") or "?"
        intent = (e.get("intent") or "")[:80]      # cap to keep prompts short
        lines.append(f"[{ts}] {agent} / {action}: {intent}")
    return "\n".join(lines)
