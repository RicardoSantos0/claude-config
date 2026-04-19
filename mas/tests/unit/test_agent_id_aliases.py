"""Unit tests for agent ID alias normalization helpers."""

from core.engine.agent_ids import normalize_agent_id, is_consultant_panel_alias


class TestNormalizeAgentId:
    def test_hr_alias(self):
        assert normalize_agent_id("hr") == "hr_agent"

    def test_hyphenated_alias(self):
        assert normalize_agent_id("domain-expert") == "domain_expert"

    def test_unknown_passthrough(self):
        assert normalize_agent_id("custom_specialist") == "custom_specialist"


class TestConsultantPanelAliases:
    def test_experts_alias(self):
        assert is_consultant_panel_alias("experts") is True

    def test_wxperts_typo_alias(self):
        assert is_consultant_panel_alias("wxperts") is True

    def test_regular_agent_not_panel_alias(self):
        assert is_consultant_panel_alias("hr_agent") is False

