"""Compatibility wrapper for the graph memory module.

This module was moved to `core.engine.graph_memory`. This thin wrapper
preserves the original import path for backwards compatibility.
"""

from core.engine.graph_memory import *


if __name__ == "__main__":
    import sys

    sys.exit(main())
