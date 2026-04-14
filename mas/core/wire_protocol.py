"""Wire Protocol - top-level wrapper

Re-exports the implementation from core.utils.wire_protocol.
"""

from core.utils.wire_protocol import *  # noqa: F401,F403

if __name__ == "__main__":
    import sys
    sys.exit(main())  # noqa: F821 — main is imported via *

