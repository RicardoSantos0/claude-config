"""AC-08: access_control rejects writes to unknown field paths."""
from __future__ import annotations

from mas.core.engine.access_control import is_authorized, ACCESS_CONTROL


class TestUnknownPathRejection:
    def test_unknown_path_is_denied(self):
        assert is_authorized("master_orchestrator", "unknown_section.unknown_field") is False

    def test_unknown_section_is_denied(self):
        assert is_authorized("master_orchestrator", "nonexistent.field") is False

    def test_known_path_owner_is_authorized(self):
        assert is_authorized("master_orchestrator", "core_identity.current_phase") is True

    def test_known_path_non_owner_is_denied(self):
        assert is_authorized("scribe_agent", "core_identity.current_phase") is False

    def test_any_agent_path_is_authorized_for_all(self):
        assert is_authorized("scribe_agent", "decisions.assumptions") is True
        assert is_authorized("inquirer_agent", "decisions.assumptions") is True
        assert is_authorized("risk_advisor", "decisions.assumptions") is True

    def test_system_sentinel_authorized_for_system_fields(self):
        assert is_authorized("system", "workflow.handoff_history") is True

    def test_empty_path_is_denied(self):
        assert is_authorized("master_orchestrator", "") is False

    def test_partial_path_is_denied(self):
        # "core_identity" without field — not in matrix
        assert is_authorized("master_orchestrator", "core_identity") is False

    def test_all_matrix_paths_have_write_key(self):
        for path, rule in ACCESS_CONTROL.items():
            assert "write" in rule, f"Missing 'write' key in ACCESS_CONTROL['{path}']"
            assert isinstance(rule["write"], list), f"'write' must be a list in '{path}'"
