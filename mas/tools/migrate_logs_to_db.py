"""
MAS Legacy Log/State Migration Script (Outline)

This script migrates legacy MAS logs and shared state files to the new SQLite episodic.db system, preserving all original files.

- Reads YAML/text logs from mas/projects/* and mas/global_graph.yaml
- Parses entries, maps to JSON-RPC 2.0 envelopes
- Compresses context/state if required
- Inserts into mas/data/episodic.db with migration status
- Marks migrated entries with a migration_status field
- Does NOT delete or modify legacy files
"""

import os
import glob
import yaml
import sqlite3
import json
from datetime import datetime

# --- CONFIG ---
LEGACY_PATHS = [
    'mas/projects/*/shared_state.yaml',
    'mas/projects/*/graph_memory.yaml',
    'mas/global_graph.yaml',
]
DB_PATH = 'mas/data/episodic.db'

# --- DB SCHEMA (example) ---
CREATE_TABLE_SQL = '''
CREATE TABLE IF NOT EXISTS episodic_events (
    id INTEGER PRIMARY KEY,
    action_id TEXT,
    agent TEXT,
    event_type TEXT,
    timestamp TEXT,
    payload TEXT,
    migration_status TEXT
);
CREATE INDEX IF NOT EXISTS idx_action_id ON episodic_events(action_id);
CREATE INDEX IF NOT EXISTS idx_agent ON episodic_events(agent);
CREATE INDEX IF NOT EXISTS idx_timestamp ON episodic_events(timestamp);
'''

# --- MIGRATION ---
def parse_yaml_file(path):
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def compress_context(context):
    # Placeholder for actual compression logic
    return context

def map_to_jsonrpc(entry, source_file):
    # Map legacy entry to JSON-RPC 2.0 envelope
    return {
        'jsonrpc': '2.0',
        'action_id': entry.get('id') or entry.get('action_id') or f"migrated-{os.path.basename(source_file)}-{datetime.utcnow().isoformat()}",
        'agent': entry.get('agent') or entry.get('owner') or 'unknown',
        'event_type': entry.get('entity_type') or 'event',
        'timestamp': entry.get('timestamp') or datetime.utcnow().isoformat(),
        'payload': compress_context(entry),
        'migration_status': 'migrated_2026-04-12',
    }

def migrate():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    for stmt in CREATE_TABLE_SQL.strip().split(';'):
        if stmt.strip():
            c.execute(stmt)
    conn.commit()

    for pattern in LEGACY_PATHS:
        for file_path in glob.glob(pattern):
            print(f"Migrating {file_path} ...")
            data = parse_yaml_file(file_path)
            if isinstance(data, dict):
                entries = [data]
            elif isinstance(data, list):
                entries = data
            else:
                continue
            for entry in entries:
                jsonrpc_obj = map_to_jsonrpc(entry, file_path)
                c.execute(
                    "INSERT INTO episodic_events (action_id, agent, event_type, timestamp, payload, migration_status) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        jsonrpc_obj['action_id'],
                        jsonrpc_obj['agent'],
                        jsonrpc_obj['event_type'],
                        jsonrpc_obj['timestamp'],
                        json.dumps(jsonrpc_obj['payload']),
                        jsonrpc_obj['migration_status'],
                    )
                )
    conn.commit()
    conn.close()
    print("Migration complete. All legacy files retained.")

if __name__ == '__main__':
    migrate()
