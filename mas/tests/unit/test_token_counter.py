"""
Unit tests for TokenCounter (mas/core/token_counter.py).

Tests cover:
- Heuristic backend: basic counting, edge cases, consistency
- count_messages(): per-message overhead
- count_dict(): JSON serialization path
- Module-level convenience functions
- Tiktoken optional: import failure gracefully falls back to heuristic
- CLI integration test
"""

import math
import pytest

from core.utils.token_counter import TokenCounter, count, count_messages, count_dict


# ---------------------------------------------------------------------------
# Heuristic backend
# ---------------------------------------------------------------------------

class TestHeuristicBackend:
    def test_empty_string_returns_zero(self):
        tc = TokenCounter()
        assert tc.count("") == 0

    def test_short_string_positive(self):
        tc = TokenCounter()
        assert tc.count("hello") > 0

    def test_count_is_ceil_char_over_3_8(self):
        tc = TokenCounter()
        text = "a" * 38  # 38 / 3.8 = 10.0 exactly
        assert tc.count(text) == 10

    def test_count_rounds_up(self):
        tc = TokenCounter()
        text = "a" * 5   # 5 / 3.8 = 1.315... → ceil = 2
        assert tc.count(text) == 2

    def test_longer_text_more_tokens(self):
        tc = TokenCounter()
        short = tc.count("hello")
        long_ = tc.count("hello " * 100)
        assert long_ > short

    def test_unicode_counted_by_chars(self):
        tc = TokenCounter()
        # Unicode chars still counted as characters
        n = tc.count("こんにちは")  # 5 chars
        assert n >= 1

    def test_none_equivalent_empty(self):
        tc = TokenCounter()
        # count() takes str; empty string → 0
        assert tc.count("") == 0

    def test_backend_name_heuristic(self):
        tc = TokenCounter()
        assert tc.backend_name == "heuristic"


# ---------------------------------------------------------------------------
# count_messages()
# ---------------------------------------------------------------------------

class TestCountMessages:
    def test_empty_list_returns_base_overhead(self):
        tc = TokenCounter()
        # Empty list: just the reply priming (3 tokens)
        assert tc.count_messages([]) == 3

    def test_single_message_includes_overhead(self):
        tc = TokenCounter()
        msg = [{"role": "user", "content": "hello"}]
        n = tc.count_messages(msg)
        # Must be at least overhead (4) + content tokens + reply priming (3)
        assert n > tc.count("hello")

    def test_more_messages_more_tokens(self):
        tc = TokenCounter()
        one = tc.count_messages([{"role": "user", "content": "hello"}])
        two = tc.count_messages([
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there, how can I help?"},
        ])
        assert two > one

    def test_empty_content_message(self):
        tc = TokenCounter()
        msg = [{"role": "user", "content": ""}]
        n = tc.count_messages(msg)
        assert n > 0  # at least overhead

    def test_missing_content_key(self):
        tc = TokenCounter()
        # Should not raise — missing content treated as ""
        msg = [{"role": "user"}]
        n = tc.count_messages(msg)
        assert n > 0


# ---------------------------------------------------------------------------
# count_dict()
# ---------------------------------------------------------------------------

class TestCountDict:
    def test_empty_dict(self):
        tc = TokenCounter()
        n = tc.count_dict({})
        assert n >= 1  # "{}" is 2 chars

    def test_dict_with_content(self):
        tc = TokenCounter()
        d = {"summary": "This is a test payload with some content"}
        n = tc.count_dict(d)
        assert n > 5

    def test_list_input(self):
        tc = TokenCounter()
        n = tc.count_dict(["a", "b", "c"])
        assert n > 0

    def test_nested_dict(self):
        tc = TokenCounter()
        small = tc.count_dict({"a": 1})
        large = tc.count_dict({"a": 1, "b": {"c": [1, 2, 3, 4, 5], "d": "lots of text here"}})
        assert large > small


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------

class TestConvenienceFunctions:
    def test_count_function(self):
        n = count("hello world")
        assert n > 0

    def test_count_messages_function(self):
        n = count_messages([{"role": "user", "content": "test"}])
        assert n > 0

    def test_count_dict_function(self):
        n = count_dict({"key": "value"})
        assert n > 0

    def test_count_empty(self):
        assert count("") == 0


# ---------------------------------------------------------------------------
# Tiktoken optional: falls back gracefully
# ---------------------------------------------------------------------------

class TestTiktokenOptional:
    def test_tiktoken_unavailable_falls_back(self, monkeypatch):
        """If tiktoken not installed, backend falls back to heuristic."""
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "tiktoken":
                raise ImportError("tiktoken not installed")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)

        tc = TokenCounter(backend="tiktoken")
        assert tc.backend_name == "heuristic"
        # Should still count correctly
        assert tc.count("hello") > 0

    def test_heuristic_is_default(self):
        tc = TokenCounter()
        assert tc.backend_name == "heuristic"


# ---------------------------------------------------------------------------
# Consistency and scaling
# ---------------------------------------------------------------------------

class TestConsistency:
    def test_same_text_same_count(self):
        tc = TokenCounter()
        t = "The quick brown fox jumps over the lazy dog."
        assert tc.count(t) == tc.count(t)

    def test_count_scales_linearly(self):
        tc = TokenCounter()
        base = tc.count("hello ")
        ten_x = tc.count("hello " * 10)
        # Should be approximately 10x (within 20%)
        assert abs(ten_x - base * 10) <= base * 2

    def test_whitespace_counted(self):
        tc = TokenCounter()
        assert tc.count("    ") > 0  # 4 spaces = at least 1 token


# ---------------------------------------------------------------------------
# CLI integration test
# ---------------------------------------------------------------------------

class TestCLI:
    def test_cli_basic(self):
        import subprocess, sys
        result = subprocess.run(
            [sys.executable, "-m", "core.utils.token_counter", "hello world"],
            capture_output=True, text=True,
            cwd=str(__import__("pathlib").Path(__file__).parent.parent.parent)
        )
        assert result.returncode == 0
        assert "tokens" in result.stdout
