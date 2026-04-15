"""
MAS Log Helpers — utils copy

Copied into `core.utils` as part of the incremental refactor. Adjusted
DB_PATH calculation to remain correct when the module lives under
`mas/core/utils/`.
"""

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Ensure DB path resolves to mas/data/episodic.db regardless of module location
DB_PATH = Path(__file__).parents[2] / "data" / "episodic.db"


# ---------------------------------------------------------------------------
# JSON-RPC 2.0 envelope
# ---------------------------------------------------------------------------

def make_log_entry(
    agent_id: str,
    action_type: str,
    intent: str,
    inputs: Optional[dict] = None,
    result_shape: Optional[str] = None,
    artifacts: Optional[list] = None,
    decisions: Optional[list] = None,
    error: Optional[str] = None,
    action_id: Optional[str] = None,
) -> dict:
    """Build a JSON-RPC 2.0 structured log entry."""
    return {
        "_v": "1.0",
        "jsonrpc": "2.0",
        "id": action_id or str(uuid.uuid4()),
        "method": f"{agent_id}.{action_type}",
        "params": {
            "intent": intent,
            "inputs": inputs or {},
        },
        "result": {
            "result_shape": result_shape or "",
            "artifacts": artifacts or [],
            "decisions": decisions or [],
        },
        "error": error,
    }


# ---------------------------------------------------------------------------
# SQLite episodic log
# ---------------------------------------------------------------------------

def _get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path = DB_PATH) -> None:
    """Initialise episodic log DB schema (idempotent)."""
    with _get_connection(db_path) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS agent_events (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id   TEXT    NOT NULL,
                agent_id     TEXT    NOT NULL,
                action_type  TEXT    NOT NULL,
                timestamp    TEXT    NOT NULL,
                intent       TEXT,
                result_shape TEXT,
                payload      TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_project   ON agent_events(project_id);
            CREATE INDEX IF NOT EXISTS idx_agent     ON agent_events(agent_id);
            CREATE INDEX IF NOT EXISTS idx_action    ON agent_events(action_type);
            CREATE INDEX IF NOT EXISTS idx_timestamp ON agent_events(timestamp);

            -- FTS5 virtual table for semantic (full-text) search over intent + payload.
            -- content=agent_events keeps the FTS index in sync with the base table
            -- when rows are inserted via the trigger below.
            CREATE VIRTUAL TABLE IF NOT EXISTS agent_events_fts
                USING fts5(
                    intent,
                    payload,
                    content='agent_events',
                    content_rowid='id'
                );

            -- Trigger: keep FTS index current on every new event.
            CREATE TRIGGER IF NOT EXISTS agent_events_fts_insert
                AFTER INSERT ON agent_events
                BEGIN
                    INSERT INTO agent_events_fts(rowid, intent, payload)
                    VALUES (NEW.id, NEW.intent, NEW.payload);
                END;

            -- Graph tables: nodes and edges migrated from global_graph.yaml
            CREATE TABLE IF NOT EXISTS agent_graph (
                id      TEXT PRIMARY KEY,
                type    TEXT,
                label   TEXT,
                meta    TEXT
            );
            CREATE TABLE IF NOT EXISTS agent_graph_edges (
                id          TEXT PRIMARY KEY,
                source      TEXT,
                target      TEXT,
                relation    TEXT,
                meta        TEXT
            );
        """)


def append_event(
    project_id: str,
    agent_id: str,
    action_type: str,
    intent: str,
    result_shape: str = "",
    payload: Optional[dict] = None,
    db_path: Path = DB_PATH,
) -> str:
    """Append an event to the episodic log. Returns the action_id."""
    action_id = str(uuid.uuid4())
    entry = make_log_entry(
        agent_id=agent_id,
        action_type=action_type,
        intent=intent,
        result_shape=result_shape,
        action_id=action_id,
    )
    if payload:
        entry["params"]["inputs"] = payload

    init_db(db_path)
    ts = datetime.now(timezone.utc).isoformat()
    with _get_connection(db_path) as conn:
        conn.execute(
            """INSERT INTO agent_events
               (project_id, agent_id, action_type, timestamp, intent, result_shape, payload)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (project_id, agent_id, action_type, ts, intent, result_shape,
             json.dumps(entry)),
        )
    return action_id


def query_by_action_id(action_id: str, db_path: Path = DB_PATH) -> Optional[dict]:
    """Retrieve a single event by its action_id — no full-scan."""
    if not db_path.exists():
        return None
    with _get_connection(db_path) as conn:
        cur = conn.execute(
            "SELECT * FROM agent_events WHERE json_extract(payload, '$.id') = ?",
            (action_id,),
        )
        row = cur.fetchone()
        if row:
            return dict(row)
    return None


def query_events(
    project_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    action_type: Optional[str] = None,
    limit: int = 50,
    db_path: Path = DB_PATH,
) -> list[dict]:
    """Query events by project/agent/action with a row limit."""
    if not db_path.exists():
        return []
    clauses, params = [], []
    if project_id:
        clauses.append("project_id = ?")
        params.append(project_id)
    if agent_id:
        clauses.append("agent_id = ?")
        params.append(agent_id)
    if action_type:
        clauses.append("action_type = ?")
        params.append(action_type)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    with _get_connection(db_path) as conn:
        cur = conn.execute(
            f"SELECT * FROM agent_events {where} ORDER BY id DESC LIMIT ?",
            params,
        )
        return [dict(r) for r in cur.fetchall()]
