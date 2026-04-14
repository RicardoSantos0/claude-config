"""Engine subpackage — migration aliases

This package provides a compatibility layer so code can import
from `core.engine.*` while we perform an incremental physical
reorganization of modules.

Notes:
- This is intentionally an aliasing layer — modules remain at
  `mas/core/*.py` for now. Later we can move files into this
  package and update imports to be relative within `core.engine`.
"""

from .. import handoff_engine as handoff_engine
from .. import shared_state_manager as shared_state_manager
from .. import task_board as task_board
from .. import metrics_engine as metrics_engine
from .. import consultation_engine as consultation_engine
from .. import training_engine as training_engine
from .. import graph_memory as graph_memory
from .. import context_compressor as context_compressor
from .. import skill_bridge as skill_bridge
from .. import message_bus as message_bus
from .. import prompt_assembler as prompt_assembler

__all__ = [
    "handoff_engine", "shared_state_manager", "task_board", "metrics_engine",
    "consultation_engine", "training_engine", "graph_memory", "context_compressor",
    "skill_bridge", "message_bus", "prompt_assembler",
]
