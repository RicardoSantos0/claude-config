"""Compatibility wrapper: shared_state_manager moved to core.engine.shared_state_manager"""

from core.engine.shared_state_manager import *  # noqa: F401,F403


if __name__ == "__main__":
    import sys
    from core.engine.shared_state_manager import main_cli

    sys.exit(main_cli())
