"""
MAS Output Linter

Detects verbose, malformed, or non-compliant agent outputs.
Records findings as output_lint events in episodic.db via EventRecorder.
Lint codes are stable identifiers — do not rename once published.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# Stable lint codes
LINT_VERBOSE = "MAS.OUTPUT.VERBOSE"
LINT_MISSING_WIRE = "MAS.OUTPUT.MISSING_WIRE"
LINT_TOO_MANY_SECTIONS = "MAS.OUTPUT.TOO_MANY_SECTIONS"
LINT_REPEATS_POLICY = "MAS.OUTPUT.REPEATS_POLICY"
LINT_RSN_TOO_LONG = "MAS.OUTPUT.RSN_TOO_LONG"

_POLICY_PHRASES = [
    "wire protocol",
    "handoff_engine.py",
    "shared_state_manager.py append",
    "uv run python mas/core",
]

_WIRE_MARKERS = ['"s":', '"_v":', '"next_action":', '"rsn":']


@dataclass
class LintResult:
    passed: bool
    findings: list[dict[str, Any]] = field(default_factory=list)

    @property
    def has_warnings(self) -> bool:
        return bool(self.findings)


class OutputLinter:
    """Checks agent output text for verbosity and compliance issues."""

    def __init__(self, max_rsn_words: int = 50, max_sections: int = 7) -> None:
        self._max_rsn_words = max_rsn_words
        self._max_sections = max_sections

    def lint(self, output: str, agent_id: str = "", project_id: str = "") -> LintResult:
        """Run all lint checks. Returns LintResult with any findings."""
        findings: list[dict[str, Any]] = []

        findings.extend(self._check_verbose(output, agent_id))
        findings.extend(self._check_missing_wire(output, agent_id))
        findings.extend(self._check_too_many_sections(output, agent_id))
        findings.extend(self._check_repeats_policy(output, agent_id))
        findings.extend(self._check_rsn_length(output, agent_id))

        return LintResult(passed=len(findings) == 0, findings=findings)

    def _check_verbose(self, output: str, agent_id: str) -> list[dict]:
        word_count = len(output.split())
        if word_count > 800:
            return [{"code": LINT_VERBOSE, "agent": agent_id,
                     "detail": f"Output is {word_count} words (threshold: 800)"}]
        return []

    def _check_missing_wire(self, output: str, agent_id: str) -> list[dict]:
        has_wire = any(marker in output for marker in _WIRE_MARKERS)
        if not has_wire:
            return [{"code": LINT_MISSING_WIRE, "agent": agent_id,
                     "detail": "No wire protocol markers found in output"}]
        return []

    def _check_too_many_sections(self, output: str, agent_id: str) -> list[dict]:
        sections = re.findall(r"^#{1,3} .+", output, re.MULTILINE)
        if len(sections) > self._max_sections:
            return [{"code": LINT_TOO_MANY_SECTIONS, "agent": agent_id,
                     "detail": f"{len(sections)} sections (threshold: {self._max_sections})"}]
        return []

    def _check_repeats_policy(self, output: str, agent_id: str) -> list[dict]:
        lower = output.lower()
        hits = [p for p in _POLICY_PHRASES if p.lower() in lower]
        if len(hits) >= 2:
            return [{"code": LINT_REPEATS_POLICY, "agent": agent_id,
                     "detail": f"Repeated policy phrases detected: {hits}"}]
        return []

    def _check_rsn_length(self, output: str, agent_id: str) -> list[dict]:
        match = re.search(r'"rsn"\s*:\s*"([^"]*)"', output)
        if match:
            words = len(match.group(1).split())
            if words > self._max_rsn_words:
                return [{"code": LINT_RSN_TOO_LONG, "agent": agent_id,
                         "detail": f"rsn is {words} words (threshold: {self._max_rsn_words})"}]
        return []
