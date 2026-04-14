"""Compatibility wrapper: spawn_policy moved to core.engine.spawn_policy"""

from core.engine.spawn_policy import *  # noqa: F401,F403
from core.engine.spawn_policy import _load_history  # noqa: F401

if __name__ == "__main__":
    import sys
    from core.engine.spawn_policy import main
    sys.exit(main())
