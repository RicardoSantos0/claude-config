"""AC-04: response_parser exposes skill_request and skills_used fields."""
from __future__ import annotations

from mas.core.engine.response_parser import ResponseParser


class TestSkillFields:
    def _parse(self, wire_extra: str = "") -> object:
        text = f'```json\n{{"s": "task:complete", "_v": "1.0"{wire_extra}}}\n```'
        return ResponseParser().parse(text)

    def test_skill_request_extracted(self):
        pr = self._parse(', "sk_req": {"skill": "research-extract", "query": "papers on LLM"}')
        assert pr.skill_request == {"skill": "research-extract", "query": "papers on LLM"}

    def test_skill_request_none_when_absent(self):
        pr = self._parse()
        assert pr.skill_request is None

    def test_skills_used_extracted(self):
        pr = self._parse(', "sk_used": ["research-extract", "notebooklm"]')
        assert pr.skills_used == ["research-extract", "notebooklm"]

    def test_skills_used_empty_when_absent(self):
        pr = self._parse()
        assert pr.skills_used == []

    def test_skills_used_non_list_coerced_to_empty(self):
        pr = self._parse(', "sk_used": "research-extract"')
        assert pr.skills_used == []

    def test_both_fields_together(self):
        pr = self._parse(
            ', "sk_req": {"skill": "mas-examine"}, "sk_used": ["mas-review"]'
        )
        assert pr.skill_request == {"skill": "mas-examine"}
        assert pr.skills_used == ["mas-review"]
