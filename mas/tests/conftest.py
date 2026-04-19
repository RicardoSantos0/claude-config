"""
Pytest collection hooks for MAS test-suite hygiene.

Graph-memory is currently deprecated in favor of SQL-backed retrieval.
The dedicated graph-memory tests are quarantined so the default suite reflects
the actively supported runtime surface.
"""

from __future__ import annotations

from pathlib import Path

import pytest


_DEPRECATED_GRAPH_FILES = {
    "test_graph_memory.py",
    "test_graph_memory_cli.py",
}
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    reason = (
        "graph memory is deprecated in this repo; the supported direction is "
        "SQL-backed retrieval, so the legacy graph-memory suite is quarantined"
    )
    for item in items:
        path_name = Path(str(item.fspath)).name
        if path_name in _DEPRECATED_GRAPH_FILES:
            item.add_marker(pytest.mark.skip(reason=reason))
