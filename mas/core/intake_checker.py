"""Compatibility wrapper: intake_checker moved to core.engine.intake_checker"""

from core.engine.intake_checker import *  # noqa: F401,F403

if __name__ == "__main__":
    import sys
    from core.engine.intake_checker import main_cli
    sys.exit(main_cli())
