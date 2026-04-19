"""
Unit tests for WireProtocol (mas/core/wire_protocol.py).

Tests cover:
- WireEncoder: encode() compresses keys, adds _v, strips empties
- WireDecoder: decode() expands keys, handles all known fields
- Roundtrip: encode → decode preserves data
- Findings nested encoding/decoding
- WireValidator: compliant vs non-compliant detection
- Status code validation
- Reasoning word cap enforcement
- Version field handling
- Module-level convenience functions
- CLI integration tests
"""

import pytest
from core.utils.wire_protocol import (
    WireEncoder, WireDecoder, WireValidator,
    encode, decode, validate, is_wire_format, encode_decode_roundtrip,
    STATUS_CODES, WIRE_VERSION,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def encoder():
    return WireEncoder()

@pytest.fixture
def decoder():
    return WireDecoder()

@pytest.fixture
def validator():
    return WireValidator()


# ---------------------------------------------------------------------------
# WireEncoder
# ---------------------------------------------------------------------------

class TestWireEncoder:
    def test_adds_version_field(self, encoder):
        wire = encoder.encode({"summary": "ok"})
        assert wire["_v"] == WIRE_VERSION

    def test_compresses_summary_to_s(self, encoder):
        wire = encoder.encode({"summary": "task:complete"})
        assert "s" in wire
        assert "summary" not in wire
        assert wire["s"] == "task:complete"

    def test_compresses_artifacts_produced(self, encoder):
        wire = encoder.encode({"artifacts_produced": ["plan.yaml"]})
        assert "art" in wire
        assert wire["art"] == ["plan.yaml"]

    def test_compresses_all_standard_fields(self, encoder):
        payload = {
            "summary": "eval:pass",
            "artifacts_produced": ["report.yaml"],
            "decisions_made": [{"id": "d-1", "v": "approve"}],
            "open_questions": ["what is scope?"],
            "constraints_for_next": ["must use wire format"],
            "shared_state_fields_modified": ["execution.plan"],
        }
        wire = encoder.encode(payload)
        assert "s" in wire
        assert "art" in wire
        assert "dec" in wire
        assert "oq" in wire
        assert "con" in wire
        assert "mod" in wire

    def test_strips_empty_lists(self, encoder):
        wire = encoder.encode({"summary": "ok", "artifacts_produced": []})
        assert "art" not in wire

    def test_strips_none_values(self, encoder):
        wire = encoder.encode({"summary": "ok", "decisions_made": None})
        assert "dec" not in wire

    def test_strips_empty_string(self, encoder):
        wire = encoder.encode({"summary": "", "recommendations": "something"})
        assert "s" not in wire

    def test_passthrough_unknown_keys(self, encoder):
        wire = encoder.encode({"summary": "ok", "custom_field": "custom_value"})
        assert wire.get("custom_field") == "custom_value"

    def test_encodes_findings_list(self, encoder):
        payload = {
            "summary": "spec_analysis:incomplete",
            "findings": [
                {"path": "scope.exclusions", "status": "missing", "action": "ask"},
                {"path": "timeline", "status": "ambiguous", "action": "clarify"},
            ]
        }
        wire = encoder.encode(payload)
        assert "f" in wire
        assert len(wire["f"]) == 2
        assert wire["f"][0] == {"path": "scope.exclusions", "st": "missing", "act": "ask"}
        assert wire["f"][1] == {"path": "timeline", "st": "ambiguous", "act": "clarify"}


# ---------------------------------------------------------------------------
# WireDecoder
# ---------------------------------------------------------------------------

class TestWireDecoder:
    def test_expands_s_to_summary(self, decoder):
        expanded = decoder.decode({"_v": "1.0", "s": "task:complete"})
        assert "summary" in expanded
        assert expanded["summary"] == "task:complete"

    def test_expands_art_to_artifacts_produced(self, decoder):
        expanded = decoder.decode({"_v": "1.0", "art": ["plan.yaml"]})
        assert "artifacts_produced" in expanded

    def test_strips_version_field(self, decoder):
        expanded = decoder.decode({"_v": "1.0", "s": "ok"})
        assert "_v" not in expanded

    def test_expands_all_compact_fields(self, decoder):
        wire = {
            "_v": "1.0",
            "s": "eval:pass",
            "art": ["r.yaml"],
            "dec": [{"id": "d-1"}],
            "oq": [],
            "con": ["must test"],
            "mod": ["eval.metrics"],
            "rl": "low",
            "rec": "consult:approve",
            "kc": ["minor scope risk"],
        }
        expanded = decoder.decode(wire)
        assert expanded.get("summary") == "eval:pass"
        assert expanded.get("artifacts_produced") == ["r.yaml"]
        assert expanded.get("risk_level") == "low"
        assert expanded.get("recommendation") == "consult:approve"
        assert expanded.get("key_concerns") == ["minor scope risk"]

    def test_passthrough_unknown_compact_keys(self, decoder):
        expanded = decoder.decode({"_v": "1.0", "xyz": "unknown"})
        assert expanded.get("xyz") == "unknown"

    def test_decodes_findings_list(self, decoder):
        wire = {"_v": "1.0", "f": [{"path": "scope", "st": "missing", "act": "ask"}]}
        expanded = decoder.decode(wire)
        assert "findings" in expanded
        assert expanded["findings"][0] == {"path": "scope", "status": "missing", "action": "ask"}


# ---------------------------------------------------------------------------
# Roundtrip
# ---------------------------------------------------------------------------

class TestRoundtrip:
    def test_simple_roundtrip(self):
        payload = {
            "summary": "task:complete",
            "artifacts_produced": ["plan.yaml"],
        }
        result = encode_decode_roundtrip(payload)
        assert result["summary"] == "task:complete"
        assert result["artifacts_produced"] == ["plan.yaml"]

    def test_findings_roundtrip(self):
        payload = {
            "summary": "spec_analysis:incomplete",
            "findings": [
                {"path": "scope", "status": "missing", "action": "ask"},
            ],
        }
        result = encode_decode_roundtrip(payload)
        assert result["summary"] == "spec_analysis:incomplete"
        assert result["findings"][0]["path"] == "scope"
        assert result["findings"][0]["status"] == "missing"

    def test_empty_fields_not_in_roundtrip(self):
        payload = {
            "summary": "ok",
            "artifacts_produced": [],
            "decisions_made": None,
        }
        result = encode_decode_roundtrip(payload)
        assert "artifacts_produced" not in result
        assert "decisions_made" not in result

    def test_full_payload_roundtrip(self):
        payload = {
            "summary": "eval:report_ready",
            "artifacts_produced": ["eval_report.yaml"],
            "decisions_made": [{"id": "d-1", "v": "pass"}],
            "constraints_for_next": ["archive artifacts"],
            "risk_level": "low",
            "recommendation": "consult:approve",
            "key_concerns": ["minor timeline slip"],
            "reasoning": "The project met all success criteria within acceptable bounds.",
        }
        result = encode_decode_roundtrip(payload)
        for key in payload:
            assert result.get(key) == payload[key], f"Mismatch for {key!r}"


# ---------------------------------------------------------------------------
# WireValidator
# ---------------------------------------------------------------------------

class TestWireValidator:
    def test_valid_wire_format(self, validator):
        ok, warnings = validator.validate({"_v": "1.0", "s": "task:complete"})
        assert ok is True
        assert warnings == []

    def test_missing_version_is_noncompliant(self, validator):
        ok, warnings = validator.validate({"summary": "task:complete"})
        assert ok is False
        assert any("_v" in w for w in warnings)

    def test_unknown_version_warns(self, validator):
        ok, warnings = validator.validate({"_v": "99.0", "s": "ok"})
        assert ok is False
        assert any("99.0" in w for w in warnings)

    def test_unknown_status_code_warns(self, validator):
        ok, warnings = validator.validate({"_v": "1.0", "s": "totally_made_up"})
        assert ok is False
        assert any("totally_made_up" in w for w in warnings)

    def test_known_status_code_passes(self, validator):
        for code in ["task:complete", "eval:pass", "consult:approve", "ok"]:
            ok, _ = validator.validate({"_v": "1.0", "s": code})
            assert ok is True, f"Expected {code!r} to be valid"

    def test_custom_section_code_passes(self, validator):
        # "section:anything" format is valid
        ok, warnings = validator.validate({"_v": "1.0", "s": "custom:status"})
        assert ok is True

    def test_reasoning_over_100_words_warns(self, validator):
        long_reasoning = " ".join(["word"] * 101)
        ok, warnings = validator.validate({"_v": "1.0", "s": "ok", "rsn": long_reasoning})
        assert ok is False
        assert any("100 words" in w for w in warnings)

    def test_reasoning_under_100_words_ok(self, validator):
        short_reasoning = " ".join(["word"] * 50)
        ok, warnings = validator.validate({"_v": "1.0", "s": "ok", "rsn": short_reasoning})
        assert ok is True

    def test_is_wire_format_true(self, validator):
        assert validator.is_wire_format({"_v": "1.0", "s": "ok"}) is True

    def test_is_wire_format_false_no_version(self, validator):
        assert validator.is_wire_format({"summary": "ok"}) is False

    def test_is_wire_format_false_non_dict(self, validator):
        assert validator.is_wire_format("string") is False  # type: ignore


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------

class TestConvenienceFunctions:
    def test_encode_function(self):
        wire = encode({"summary": "ok"})
        assert "_v" in wire
        assert "s" in wire

    def test_decode_function(self):
        expanded = decode({"_v": "1.0", "s": "ok"})
        assert "summary" in expanded

    def test_validate_function(self):
        ok, _ = validate({"_v": "1.0", "s": "ok"})
        assert ok is True

    def test_is_wire_format_function(self):
        assert is_wire_format({"_v": "1.0"}) is True
        assert is_wire_format({"summary": "prose"}) is False


# ---------------------------------------------------------------------------
# Status code vocabulary
# ---------------------------------------------------------------------------

class TestStatusCodes:
    def test_all_standard_codes_present(self):
        expected = [
            "task:complete", "eval:pass", "consult:approve", "consult:caution",
            "consult:oppose", "capability:match", "capability:gap", "ok", "error",
            "spec_analysis:ok", "product_plan:ready",
        ]
        for code in expected:
            assert code in STATUS_CODES, f"{code!r} missing from STATUS_CODES"

    def test_no_duplicate_codes(self):
        codes = list(STATUS_CODES.keys())
        assert len(codes) == len(set(codes))


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------

class TestCLI:
    def test_encode_cli(self):
        import subprocess, sys, json
        payload = json.dumps({"summary": "task:complete"})
        result = subprocess.run(
            [sys.executable, "-m", "core.utils.wire_protocol", "encode", payload],
            capture_output=True, text=True,
            cwd=str(__import__("pathlib").Path(__file__).parent.parent.parent)
        )
        assert result.returncode == 0
        wire = json.loads(result.stdout)
        assert wire.get("_v") == "1.0"
        assert wire.get("s") == "task:complete"

    def test_decode_cli(self):
        import subprocess, sys, json
        wire = json.dumps({"_v": "1.0", "s": "task:complete"})
        result = subprocess.run(
            [sys.executable, "-m", "core.utils.wire_protocol", "decode", wire],
            capture_output=True, text=True,
            cwd=str(__import__("pathlib").Path(__file__).parent.parent.parent)
        )
        assert result.returncode == 0
        expanded = json.loads(result.stdout)
        assert expanded.get("summary") == "task:complete"

    def test_validate_compliant_cli(self):
        import subprocess, sys, json
        wire = json.dumps({"_v": "1.0", "s": "ok"})
        result = subprocess.run(
            [sys.executable, "-m", "core.utils.wire_protocol", "validate", wire],
            capture_output=True, text=True,
            cwd=str(__import__("pathlib").Path(__file__).parent.parent.parent)
        )
        assert result.returncode == 0
        assert "COMPLIANT" in result.stdout

    def test_validate_noncompliant_cli(self):
        import subprocess, sys, json
        legacy = json.dumps({"summary": "prose text here"})
        result = subprocess.run(
            [sys.executable, "-m", "core.utils.wire_protocol", "validate", legacy],
            capture_output=True, text=True,
            cwd=str(__import__("pathlib").Path(__file__).parent.parent.parent)
        )
        assert result.returncode == 1
        assert "NON-COMPLIANT" in result.stdout

    def test_codes_cli(self):
        import subprocess, sys
        result = subprocess.run(
            [sys.executable, "-m", "core.utils.wire_protocol", "codes"],
            capture_output=True, text=True,
            cwd=str(__import__("pathlib").Path(__file__).parent.parent.parent)
        )
        assert result.returncode == 0
        assert "task:complete" in result.stdout
