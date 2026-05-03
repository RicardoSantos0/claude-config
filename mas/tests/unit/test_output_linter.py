"""Tests for mas.core.engine.output_linter."""
from __future__ import annotations

from mas.core.engine.output_linter import (
    LINT_MISSING_WIRE,
    LINT_REPEATS_POLICY,
    LINT_RSN_TOO_LONG,
    LINT_TOO_MANY_SECTIONS,
    LINT_VERBOSE,
    LintResult,
    OutputLinter,
)

VALID_WIRE_OUTPUT = '{"_v": "1.0", "s": "task:complete", "rsn": "done", "next_action": "close"}'


def make_linter(**kwargs):
    return OutputLinter(**kwargs)


# ---------------------------------------------------------------------------
# Passing output
# ---------------------------------------------------------------------------

def test_clean_compact_output_passes():
    linter = make_linter()
    result = linter.lint(VALID_WIRE_OUTPUT, agent_id="test_agent")
    assert result.passed
    assert not result.findings
    assert not result.has_warnings


# ---------------------------------------------------------------------------
# LINT_VERBOSE
# ---------------------------------------------------------------------------

def test_verbose_output_flagged():
    linter = make_linter()
    long_output = VALID_WIRE_OUTPUT + " word" * 850
    result = linter.lint(long_output)
    codes = [f["code"] for f in result.findings]
    assert LINT_VERBOSE in codes


def test_output_under_threshold_not_flagged():
    linter = make_linter()
    output = VALID_WIRE_OUTPUT + " word" * 10
    result = linter.lint(output)
    codes = [f["code"] for f in result.findings]
    assert LINT_VERBOSE not in codes


# ---------------------------------------------------------------------------
# LINT_MISSING_WIRE
# ---------------------------------------------------------------------------

def test_no_wire_markers_flagged():
    linter = make_linter()
    result = linter.lint("This is a plain text response with no wire markers.")
    codes = [f["code"] for f in result.findings]
    assert LINT_MISSING_WIRE in codes


def test_wire_marker_present_not_flagged():
    linter = make_linter()
    result = linter.lint(VALID_WIRE_OUTPUT)
    codes = [f["code"] for f in result.findings]
    assert LINT_MISSING_WIRE not in codes


# ---------------------------------------------------------------------------
# LINT_TOO_MANY_SECTIONS
# ---------------------------------------------------------------------------

def test_too_many_sections_flagged():
    linter = make_linter(max_sections=3)
    output = VALID_WIRE_OUTPUT + "\n# S1\n# S2\n# S3\n# S4\n"
    result = linter.lint(output)
    codes = [f["code"] for f in result.findings]
    assert LINT_TOO_MANY_SECTIONS in codes


def test_sections_within_limit_not_flagged():
    linter = make_linter(max_sections=7)
    output = VALID_WIRE_OUTPUT + "\n# S1\n# S2\n"
    result = linter.lint(output)
    codes = [f["code"] for f in result.findings]
    assert LINT_TOO_MANY_SECTIONS not in codes


# ---------------------------------------------------------------------------
# LINT_REPEATS_POLICY
# ---------------------------------------------------------------------------

def test_repeated_policy_phrases_flagged():
    linter = make_linter()
    output = (VALID_WIRE_OUTPUT +
              " wire protocol rules apply. Use handoff_engine.py to delegate.")
    result = linter.lint(output)
    codes = [f["code"] for f in result.findings]
    assert LINT_REPEATS_POLICY in codes


def test_single_policy_phrase_not_flagged():
    linter = make_linter()
    output = VALID_WIRE_OUTPUT + " Use the wire protocol."
    result = linter.lint(output)
    codes = [f["code"] for f in result.findings]
    assert LINT_REPEATS_POLICY not in codes


# ---------------------------------------------------------------------------
# LINT_RSN_TOO_LONG
# ---------------------------------------------------------------------------

def test_long_rsn_flagged():
    linter = make_linter(max_rsn_words=5)
    rsn = " ".join(["word"] * 10)
    output = f'{{"_v": "1.0", "s": "task:complete", "rsn": "{rsn}", "next_action": "x"}}'
    result = linter.lint(output)
    codes = [f["code"] for f in result.findings]
    assert LINT_RSN_TOO_LONG in codes


def test_short_rsn_not_flagged():
    linter = make_linter()
    result = linter.lint(VALID_WIRE_OUTPUT)
    codes = [f["code"] for f in result.findings]
    assert LINT_RSN_TOO_LONG not in codes


def test_no_rsn_field_not_flagged():
    linter = make_linter()
    output = '{"_v": "1.0", "s": "task:complete", "next_action": "x"}'
    result = linter.lint(output)
    codes = [f["code"] for f in result.findings]
    assert LINT_RSN_TOO_LONG not in codes


# ---------------------------------------------------------------------------
# LintResult properties
# ---------------------------------------------------------------------------

def test_lint_result_has_warnings_true_when_findings():
    r = LintResult(passed=False, findings=[{"code": LINT_VERBOSE}])
    assert r.has_warnings


def test_lint_result_has_warnings_false_when_empty():
    r = LintResult(passed=True)
    assert not r.has_warnings


# ---------------------------------------------------------------------------
# agent_id captured in findings
# ---------------------------------------------------------------------------

def test_agent_id_in_finding():
    linter = make_linter()
    result = linter.lint("plain text no wire", agent_id="quality_advisor")
    assert any(f.get("agent") == "quality_advisor" for f in result.findings)
