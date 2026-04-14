"""Compatibility wrapper: capability_registry moved to core.engine.capability_registry"""

from core.engine.capability_registry import *  # noqa: F401,F403

if __name__ == "__main__":
    import sys
    from core.engine.capability_registry import main_cli
    sys.exit(main_cli())
