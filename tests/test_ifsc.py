"""
tests/test_ifsc.py — Tests for IFSC format check (B1).
"""
from __future__ import annotations

import pytest
from app.validators.ifsc import run_ifsc_format


class TestIfscFormat:
    @pytest.mark.parametrize("ifsc", [
        "HDFC0001234",
        "SBIN0001234",
        "ICIC0001234",
        "UTIB0000123",
        "KKBK0ABCDEF",   # alphanumeric branch code
    ])
    def test_valid_ifsc(self, ifsc):
        result = run_ifsc_format(ifsc)
        assert result.status == "pass"
        assert result.severity == "hard"
        assert result.check_name == "ifsc_format"

    def test_invalid_fifth_char_not_zero(self):
        """5th character must be '0'."""
        result = run_ifsc_format("HDFC1001234")
        assert result.status == "fail"

    def test_invalid_too_short(self):
        result = run_ifsc_format("HDFC000123")
        assert result.status == "fail"

    def test_invalid_too_long(self):
        result = run_ifsc_format("HDFC00012345")
        assert result.status == "fail"

    def test_invalid_numeric_bank_code(self):
        """First 4 must be letters."""
        result = run_ifsc_format("1234001234A")
        assert result.status == "fail"

    def test_empty(self):
        result = run_ifsc_format("")
        assert result.status == "fail"

    def test_none(self):
        result = run_ifsc_format(None)
        assert result.status == "fail"

    def test_lowercase_normalised(self):
        result = run_ifsc_format("hdfc0001234")
        assert result.status == "pass"
