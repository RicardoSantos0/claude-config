#!/usr/bin/env python3
"""
check_archive_clean.py — Verify a git archive contains no private/generated paths.

Usage:
    python scripts/check_archive_clean.py <archive.zip>

Exit codes:
    0  — archive contains no blocked private/generated paths
    1  — archive contains one or more blocked paths (error details printed)
    2  — usage error or archive cannot be opened

Blocked path patterns (any archive member matching these is a violation):
    .env
    .env.*
    .claude/settings.local.json
    .venv/
    __pycache__/
    *.pyc
    *.pyo
    mas/data/
    mas/projects/
    mas/logs/
    mas/working_state/
    skills/notebooklm/data/browser_state/
    skills/notebooklm/data/auth_info.json
    *.sqlite
    *.sqlite3
    *.db
    *.log
    secrets/
    logs/
"""

import sys
import zipfile
import fnmatch
from pathlib import Path


BLOCKED_PATTERNS = [
    ".env",
    ".env.*",
    ".claude/settings.local.json",
    ".venv/*",
    "__pycache__/*",
    "*.pyc",
    "*.pyo",
    "mas/data/*",
    "mas/projects/*",
    "mas/logs/*",
    "mas/working_state/*",
    "skills/notebooklm/data/browser_state/*",
    "skills/notebooklm/data/auth_info.json",
    "*.sqlite",
    "*.sqlite3",
    "*.db",
    "*.log",
    "secrets/*",
    "logs/*",
]


def is_blocked(name: str) -> bool:
    """Return True if the archive member name matches any blocked pattern."""
    # Normalise to forward slashes for cross-platform matching
    name = name.replace("\\", "/")
    for pattern in BLOCKED_PATTERNS:
        if fnmatch.fnmatch(name, pattern):
            return True
        # Also match if the name starts with a blocked prefix directory
        prefix = pattern.rstrip("*").rstrip("/")
        if prefix and (name == prefix or name.startswith(prefix + "/")):
            return True
    return False


def check_archive(path: str) -> list[str]:
    """Return list of blocked paths found in the archive."""
    try:
        with zipfile.ZipFile(path, "r") as zf:
            names = zf.namelist()
    except zipfile.BadZipFile as exc:
        print(f"ERROR: cannot open archive: {exc}", file=sys.stderr)
        sys.exit(2)
    return [n for n in names if is_blocked(n)]


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python scripts/check_archive_clean.py <archive.zip>", file=sys.stderr)
        sys.exit(2)

    archive_path = sys.argv[1]
    if not Path(archive_path).exists():
        print(f"ERROR: archive not found: {archive_path}", file=sys.stderr)
        sys.exit(2)

    violations = check_archive(archive_path)

    if violations:
        print("ERROR: archive contains blocked paths:")
        for v in violations:
            print(f"  - {v}")
        sys.exit(1)
    else:
        print("OK: archive contains no blocked private/generated paths.")
        sys.exit(0)


if __name__ == "__main__":
    main()
