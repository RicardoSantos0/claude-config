"""
MAS DB Init — T-M3-003
Idempotent script to initialise mas/data/episodic.db and semantic_stub.json.
Safe to re-run.
"""

import json
import sys
from pathlib import Path

# Add parent to path for log_helpers import
sys.path.insert(0, str(Path(__file__).parent))
from log_helpers import init_db, DB_PATH

SEMANTIC_STUB_PATH = DB_PATH.parent / "semantic_stub.json"


def init_semantic_stub(path: Path = SEMANTIC_STUB_PATH) -> None:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        stub = {
            "version": "stub-1.0",
            "note": (
                "Semantic vector search not implemented. "
                "Upgrade path: replace with ChromaDB or pgvector."
            ),
            "entries": [],
        }
        path.write_text(json.dumps(stub, indent=2))
        print(f"[ok] Created semantic stub: {path}")
    else:
        print(f"[ok] Semantic stub already exists: {path}")


def main() -> None:
    print(f"Initialising episodic DB at: {DB_PATH}")
    init_db()
    print(f"[ok] episodic.db ready (WAL mode, schema applied)")
    init_semantic_stub()
    print("DB init complete.")


if __name__ == "__main__":
    main()
