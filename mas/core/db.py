"""
MAS Database — Central SQLite access layer.

Single import point for all database operations. Every module that needs
to read or write the event log imports from here, not from log_helpers directly.

Database: mas/data/episodic.db

Tables:
  agent_events      — every handoff, agent call, phase transition, consultation
  agent_events_fts  — FTS5 virtual table (intent + payload) for semantic search
  episodic_events   — migrated history (read-only, commsopt migration)

Public API:
  append_event(project_id, agent_id, action_type, intent, ...)  → action_id
  query_events(project_id, agent_id, action_type, limit) → list[dict]
  query_project_history(project_id, limit)  → list[dict]  (chronological)
  query_agent_context(project_id, agent_id, limit) → list[dict]
  semantic_search(query, project_id, limit) → list[dict]  (FTS5 ranked)
  query_token_usage(project_id) → dict  (summed token counts for agent_call events)
  format_events_for_prompt(events) → str
"""

import sqlite3
from pathlib import Path
from typing import Optional

from core.utils.log_helpers import (
    DB_PATH,
    init_db,
    append_event,
    query_events,
    query_by_action_id,
    _get_connection,
)

__all__ = [
    "DB_PATH",
    "init_db",
    "append_event",
    "query_events",
    "query_by_action_id",
    "query_project_history",
    "query_agent_context",
    "semantic_search",
    "query_token_usage",
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


def semantic_search(
    query: str,
    project_id: str | None = None,
    limit: int = 5,
    db_path: Path = DB_PATH,
) -> list[dict]:
    """
    Full-text search over agent_events using the FTS5 index (agent_events_fts).
    Results are ranked by BM25 relevance (best match first).

    Falls back to [] gracefully if:
      - The FTS5 table doesn't exist yet (call init_db() first)
      - The query is empty or causes a syntax error
      - Any SQLite error

    Args:
        query:      Search term(s) — plain text, FTS5 syntax supported.
        project_id: Optional filter to scope results to one project.
        limit:      Maximum results to return.
        db_path:    Path to the SQLite database (default: mas/data/episodic.db).

    Returns:
        List of event dicts (same shape as query_events results), newest-first.
    """
    if not query or not query.strip():
        return []
    try:
        with _get_connection(db_path) as conn:
            if project_id:
                sql = """
                    SELECT ae.id, ae.project_id, ae.agent_id, ae.action_type,
                           ae.timestamp, ae.intent, ae.result_shape, ae.payload
                    FROM agent_events_fts
                    JOIN agent_events ae ON agent_events_fts.rowid = ae.id
                    WHERE agent_events_fts MATCH ?
                      AND ae.project_id = ?
                    ORDER BY rank
                    LIMIT ?
                """
                rows = conn.execute(sql, (query, project_id, limit)).fetchall()
            else:
                sql = """
                    SELECT ae.id, ae.project_id, ae.agent_id, ae.action_type,
                           ae.timestamp, ae.intent, ae.result_shape, ae.payload
                    FROM agent_events_fts
                    JOIN agent_events ae ON agent_events_fts.rowid = ae.id
                    WHERE agent_events_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                """
                rows = conn.execute(sql, (query, limit)).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


def query_token_usage(
    project_id: str,
    db_path: Path = DB_PATH,
) -> dict:
    """
    Sum token usage across all agent_call events for a project.
    Token fields are stored in the JSON payload as:
      {"tokens_prompt": N, "tokens_completion": N, "tokens_total": N}

    Returns:
        {"total_prompt": int, "total_completion": int, "total": int, "calls": int}
    """
    try:
        import json as _json
        with _get_connection(db_path) as conn:
            rows = conn.execute(
                "SELECT payload FROM agent_events WHERE project_id=? AND action_type='agent_call'",
                (project_id,),
            ).fetchall()
        total_prompt = total_completion = total = calls = 0
        for row in rows:
            try:
                data = _json.loads(row["payload"] or "{}")
                params = data.get("params", {}).get("inputs", {})
                total_prompt     += params.get("tokens_prompt", 0)
                total_completion += params.get("tokens_completion", 0)
                total            += params.get("tokens_total", 0)
                calls += 1
            except Exception:
                pass
        return {
            "total_prompt":     total_prompt,
            "total_completion": total_completion,
            "total":            total,
            "calls":            calls,
        }
    except Exception:
        return {"total_prompt": 0, "total_completion": 0, "total": 0, "calls": 0}


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
