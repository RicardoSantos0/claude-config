"""Compatibility wrapper: checkpoint_writer moved to core.engine.checkpoint_writer"""

from core.engine.checkpoint_writer import *

if __name__ == "__main__":
    import sys

    sys.exit(main())
