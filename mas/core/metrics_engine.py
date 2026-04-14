"""Compatibility wrapper: metrics_engine moved to core.engine.metrics_engine"""

from core.engine.metrics_engine import *  # noqa: F401,F403


if __name__ == "__main__":
    import sys

    sys.exit(main_cli())
