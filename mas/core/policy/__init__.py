"""Policy subpackage — re-exports policy/registry modules from core.engine.

Import directly from engine submodules, e.g.:

    from core.engine.capability_registry import CapabilityRegistry
    from core.engine.spawn_policy import SpawnPolicyEngine
"""

from core.engine import capability_registry
from core.engine import spawn_policy

__all__ = ["capability_registry", "spawn_policy"]
