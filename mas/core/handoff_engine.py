"""Re-exports the implementation from core.engine.handoff_engine."""

from core.engine.handoff_engine import *  # noqa: F401,F403


if __name__ == "__main__":
    import sys

    from core.engine.handoff_engine import main_cli

    sys.exit(main_cli())
