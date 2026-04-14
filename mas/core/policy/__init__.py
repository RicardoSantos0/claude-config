"""Policy subpackage — migration aliases

Provides aliases for policy-related modules under `core.policy.*`.
"""

from .. import capability_registry as capability_registry
from .. import spawn_policy as spawn_policy

__all__ = ["capability_registry", "spawn_policy"]
