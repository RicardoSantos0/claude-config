"""Token Counter - top-level wrapper

This wrapper re-exports the implementation from core.utils.token_counter
to allow incremental migration while preserving backwards compatibility.
"""

from core.utils.token_counter import *  # noqa: F401,F403

if __name__ == "__main__":
    import sys
    sys.exit(main())
