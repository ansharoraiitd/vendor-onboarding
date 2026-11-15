"""
tests/test_llpin.py — Tests for LLPIN format check (L1).
"""
from __future__ import annotations

import pytest
from app.validators.llpin import run_llpin_format


class TestLlpinFormat:
    @pytest.mark.parametrize("llpin", [
        "AAA-1234",
        "ZZZ-9999",
        "MNO-0001",
        "ABC-5678",
    ])
    def test_valid_llpin(self, llpin):
        result = run_llpin_format(llpin)
        assert result.status == "pass"
        assert result.severity == "hard"
        assert result.check_name == "llpin_format"

    def test_invalid_too_short(self):
        result = run_llpin_format("AA-1234")
        assert result.status == "fail"

    def test_invalid_too_long(self):
        result = run_llpin_format("ABCD-1234")
        assert result.status == "fail"

    def test_invalid_no_dash(self):
        result = run_llpin_format("AAA1234")
        assert result.status == "fail"

    def test_invalid_letters_after_dash(self):
        result = run_llpin_format("AAA-ABCD")
        assert result.status == "fail"

    def test_invalid_digits_before_dash(self):
        result = run_llpin_format("123-1234")
        assert result.status == "fail"

    def test_empty(self):
        result = run_llpin_format("")
        assert result.status == "fail"

    def test_none(self):
        result = run_llpin_format(None)
        assert result.status == "fail"

    def test_lowercase_normalised(self):
        result = run_llpin_format("aaa-1234")
        assert result.status == "pass"
