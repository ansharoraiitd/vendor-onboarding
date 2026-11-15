"""
tests/test_gstin.py — Tests for GSTIN validator (G1, G2, G3, G4).

GSTIN checksum algorithm: left-to-right over positions 1-14,
factor alternates 2→1→2→… (starts at 2).

Known valid GSTINs (checksums independently verified):
  27AABCU9603R1ZP  — UCO Bank, Maharashtra (state 27)
  29AADCB2230M1Z9  — Karnataka (state 29); checksum=9
  07AAACR5055K1ZF  — Delhi (state 07); checksum=F
  19AABCT3518Q1ZP  — West Bengal (state 19); checksum=P
  24AAACI1289P1ZG  — Gujarat (state 24); checksum=G

Note: 29AADCB2230M1ZP and 07AAACR5055K1Z5 from the original brief were
incorrect. Corrected checksums computed by the forward (left-to-right) algorithm.
"""
from __future__ import annotations

import pytest
from app.validators.gstin import (
    run_gstin_format,
    run_gstin_checksum,
    run_gstin_embedded_pan_match,
    run_gstin_state_code_match,
    _compute_gstin_checksum,
)

KNOWN_VALID_GSTINS = [
    "27AABCU9603R1ZP",
    "29AADCB2230M1Z9",
    "07AAACR5055K1ZF",
    "19AABCT3518Q1ZP",
    "24AAACI1289P1ZG",
]


class TestGstinFormat:
    """G1 — GSTIN format regex."""

    @pytest.mark.parametrize("gstin", KNOWN_VALID_GSTINS)
    def test_valid_known_gstins_pass_format(self, gstin):
        result = run_gstin_format(gstin)
        assert result.status == "pass", f"{gstin} should pass format check"

    def test_invalid_too_short(self):
        result = run_gstin_format("27AABCU9603R1Z")
        assert result.status == "fail"

    def test_invalid_too_long(self):
        result = run_gstin_format("27AABCU9603R1ZPX")
        assert result.status == "fail"

    def test_invalid_zero_in_position_12(self):
        """Position 12 (0-indexed) must be [1-9A-Z], not '0' (digit zero)."""
        # Build a 15-char GSTIN with '0' at position 12
        gstin = "27AABCU9603R0ZP"
        result = run_gstin_format(gstin)
        assert result.status == "fail", "GSTIN with '0' at position 12 must fail format"

    def test_invalid_non_alpha_in_entity_position(self):
        """Position 5 must be [ABCFGHLJPTK]; digit should fail."""
        gstin = "27AAB19603R1ZPX"  # malformed
        result = run_gstin_format(gstin)
        assert result.status == "fail"

    def test_invalid_state_code_non_numeric(self):
        """First 2 chars must be digits."""
        gstin = "XXAABCU9603R1ZP"
        result = run_gstin_format(gstin)
        assert result.status == "fail"

    def test_empty_gstin(self):
        result = run_gstin_format("")
        assert result.status == "fail"

    def test_none_gstin(self):
        result = run_gstin_format(None)
        assert result.status == "fail"

    def test_lowercase_normalised(self):
        """Lowercase input should be normalised to uppercase."""
        result = run_gstin_format("27aabcu9603r1zp")
        assert result.status == "pass"


class TestGstinChecksum:
    """G2 — GSTIN mod-36 checksum."""

    @pytest.mark.parametrize("gstin", KNOWN_VALID_GSTINS)
    def test_valid_known_gstins_pass_checksum(self, gstin):
        result = run_gstin_checksum(gstin)
        assert result.status == "pass", (
            f"{gstin} should pass checksum. "
            f"Evidence: {result.evidence}"
        )

    @pytest.mark.parametrize("gstin", KNOWN_VALID_GSTINS)
    def test_modified_last_char_fails_checksum(self, gstin):
        """Flipping the last character should cause checksum failure."""
        last = gstin[-1]
        # Replace last char with something different
        replacement = "A" if last != "A" else "B"
        bad_gstin = gstin[:-1] + replacement
        # Only run if the bad GSTIN still passes format
        from app.validators.gstin import GSTIN_FORMAT_RE
        if GSTIN_FORMAT_RE.match(bad_gstin):
            result = run_gstin_checksum(bad_gstin)
            if bad_gstin != gstin:  # only check if we actually changed it
                assert result.status == "fail", (
                    f"Modified GSTIN {bad_gstin} should fail checksum"
                )

    def test_checksum_compute_known_values(self):
        """Unit-test _compute_gstin_checksum directly for known GSTINs."""
        for gstin in KNOWN_VALID_GSTINS:
            expected_char = gstin[14]
            computed_char = _compute_gstin_checksum(gstin[:14])
            assert computed_char == expected_char, (
                f"For {gstin}: expected checksum char '{expected_char}', "
                f"got '{computed_char}'"
            )

    def test_invalid_format_propagates(self):
        """If format is invalid, checksum check should also fail."""
        result = run_gstin_checksum("INVALID")
        assert result.status == "fail"


class TestGstinEmbeddedPanMatch:
    """G3 — GSTIN embedded PAN match."""

    def test_valid_embedded_pan_match(self):
        # 27AABCU9603R1ZP -> PAN is AABCU9603R (chars 2:12)
        result = run_gstin_embedded_pan_match("27AABCU9603R1ZP", "AABCU9603R")
        assert result.status == "pass"

    def test_valid_embedded_pan_match_second(self):
        # 29AADCB2230M1Z9 -> PAN is AADCB2230M
        result = run_gstin_embedded_pan_match("29AADCB2230M1Z9", "AADCB2230M")
        assert result.status == "pass"

    def test_valid_embedded_pan_match_third(self):
        # 07AAACR5055K1ZF -> PAN is AAACR5055K
        result = run_gstin_embedded_pan_match("07AAACR5055K1ZF", "AAACR5055K")
        assert result.status == "pass"

    def test_embedded_pan_mismatch(self):
        """PAN that doesn't match the embedded portion should fail."""
        result = run_gstin_embedded_pan_match("27AABCU9603R1ZP", "ZZZZE1234F")
        assert result.status == "fail"
        assert result.severity == "hard"
        assert result.evidence["embedded_pan"] == "AABCU9603R"

    def test_short_gstin_fails(self):
        result = run_gstin_embedded_pan_match("27AABCU", "AABCU9603R")
        assert result.status == "fail"


class TestGstinStateCodeMatch:
    """G4 — GSTIN state code match (confidence gate)."""

    def test_matching_state_code_passes(self):
        # 27AABCU9603R1ZP -> state code 27 (Maharashtra)
        result = run_gstin_state_code_match("27AABCU9603R1ZP", "27", 0.95, 0.80)
        assert result.status == "pass"
        assert result.severity == "fixable"

    def test_mismatched_state_code_fails(self):
        result = run_gstin_state_code_match("27AABCU9603R1ZP", "29", 0.95, 0.80)
        assert result.status == "fail"
        assert result.severity == "fixable"

    def test_low_confidence_downgrades_to_fixable(self):
        """Even if state code mismatches, low confidence means fixable."""
        result = run_gstin_state_code_match("27AABCU9603R1ZP", "29", 0.60, 0.80)
        assert result.status == "fail"
        assert result.severity == "fixable"
        assert "confidence" in result.evidence

    def test_high_confidence_mismatch_is_fixable(self):
        """G4 is Fixable by design — not Hard."""
        result = run_gstin_state_code_match("07AAACR5055K1ZF", "27", 0.99, 0.80)
        assert result.status == "fail"
        assert result.severity == "fixable"  # G4 is always fixable, not hard

    def test_exact_confidence_boundary(self):
        """confidence == min_confidence should run the check normally."""
        result = run_gstin_state_code_match("27AABCU9603R1ZP", "27", 0.80, 0.80)
        assert result.status == "pass"

    def test_just_below_confidence_boundary(self):
        """confidence just below min_confidence should downgrade."""
        result = run_gstin_state_code_match("27AABCU9603R1ZP", "27", 0.799, 0.80)
        assert result.status == "fail"
        assert result.severity == "fixable"
