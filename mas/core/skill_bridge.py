"""Compatibility wrapper: skill_bridge moved to core.engine.skill_bridge"""

from core.engine.skill_bridge import *  # noqa: F401,F403

if __name__ == "__main__":
    import sys
    from core.engine.skill_bridge import main
    sys.exit(main())
