"""
tests/test_pan.py — Tests for PAN validator (P1, P2).
"""
from __future__ import annotations

import pytest
from app.validators.pan import run_pan_format, run_pan_entity_type_match


class TestPanFormat:
    """P1 — PAN format validation."""

    def test_valid_pan_proprietor(self):
        """ABCPE1234F — 4th char P (Proprietor); should pass."""
        result = run_pan_format("ABCPE1234F")
        assert result.status == "pass"
        assert result.severity == "hard"
        assert result.check_name == "pan_format"

    def test_valid_pan_company(self):
        """AABCU9603R — 4th char C (Company); should pass."""
        result = run_pan_format("AABCU9603R")
        assert result.status == "pass"
        assert result.severity == "hard"

    def test_invalid_format_too_short(self):
        result = run_pan_format("ABCP123")
        assert result.status == "fail"
        assert result.severity == "hard"

    def test_invalid_format_too_long(self):
        result = run_pan_format("ABCPE1234FX")
        assert result.status == "fail"
        assert result.severity == "hard"

    def test_invalid_format_digit_in_first_3(self):
        result = run_pan_format("A1CPE1234F")
        assert result.status == "fail"

    def test_invalid_entity_char(self):
        """4th char must be one of ABCFGHLJPTK — 'Z' should fail."""
        result = run_pan_format("ABCZE1234F")
        assert result.status == "fail"

    def test_lowercase_input_normalised_to_pass(self):
        """Validator uppercases input before checking; lowercase PAN should pass format."""
        result = run_pan_format("abcpe1234f")
        # 'abcpe1234f'.upper() -> 'ABCPE1234F' which is a valid PAN format
        assert result.status == "pass"

    def test_empty_pan(self):
        result = run_pan_format("")
        assert result.status == "fail"

    def test_none_pan(self):
        result = run_pan_format(None)
        assert result.status == "fail"

    def test_all_digits_invalid(self):
        result = run_pan_format("1234567890")
        assert result.status == "fail"

    def test_valid_pan_uppercase_normalised(self):
        """Whitespace-padded input should still pass after strip."""
        result = run_pan_format("  AABCU9603R  ")
        assert result.status == "pass"


class TestPanEntityTypeMatch:
    """P2 — PAN entity-type character match."""

    @pytest.mark.parametrize("pan,entity_type", [
        ("ABCPE1234F", "proprietorship"),   # P -> proprietorship
        ("ABCCE1234F", "pvt_ltd"),           # C -> pvt_ltd
        ("ABCCE1234F", "pub_ltd"),           # C -> pub_ltd
        ("ABCCE1234F", "section8"),          # C -> section8
        ("ABCFE1234F", "partnership"),       # F -> partnership
        ("ABCFE1234F", "llp"),               # F -> llp
    ])
    def test_valid_entity_type_match(self, pan, entity_type):
        result = run_pan_entity_type_match(pan, entity_type)
        assert result.status == "pass"
        assert result.severity == "hard"

    def test_entity_type_mismatch_proprietor_given_company(self):
        """PAN char C for a proprietorship should fail."""
        result = run_pan_entity_type_match("ABCCE1234F", "proprietorship")
        assert result.status == "fail"
        assert result.severity == "hard"

    def test_entity_type_mismatch_firm_given_company(self):
        """PAN char F for pvt_ltd should fail."""
        result = run_pan_entity_type_match("ABCFE1234F", "pvt_ltd")
        assert result.status == "fail"
        assert result.severity == "hard"

    def test_invalid_pan_format_propagates(self):
        """Invalid PAN should produce fail (can't decode entity type)."""
        result = run_pan_entity_type_match("INVALID", "pvt_ltd")
        assert result.status == "fail"

    def test_unknown_entity_type(self):
        """Unknown entity_type should return fail."""
        result = run_pan_entity_type_match("AABCU9603R", "trust")
        assert result.status == "fail"

    def test_evidence_contains_pan_char(self):
        result = run_pan_entity_type_match("AABCU9603R", "pvt_ltd")
        assert "pan_char" in result.evidence
        assert result.evidence["pan_char"] == "C"
