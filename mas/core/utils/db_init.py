"""
MAS DB Init (utils copy)

Copied into `core.utils` and updated imports to use the local utils package.
"""

import json
import sys
from pathlib import Path

from .log_helpers import init_db, DB_PATH

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
