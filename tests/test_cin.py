"""
tests/test_cin.py — Tests for CIN validator (C1–C5).
"""
from __future__ import annotations

import pytest
from app.validators.cin import (
    run_cin_format,
    run_cin_listing_status,
    run_cin_state_match,
    run_cin_year_match,
    run_cin_entity_type_match,
)

# Valid CIN examples:
# U74999MH2010PTC123456  — Unlisted, MH state, 2010, Private (PTC)
# L65191KA1994PLC016171  — Listed, KA state, 1994, Public (PLC)
VALID_CIN_PVT = "U74999MH2010PTC123456"
VALID_CIN_PUB = "L65191KA1994PLC016171"
VALID_CIN_NPL = "U85300DL2001NPL123456"


class TestCinFormat:
    def test_valid_cin_pvt(self):
        result = run_cin_format(VALID_CIN_PVT)
        assert result.status == "pass"
        assert result.severity == "hard"

    def test_valid_cin_pub(self):
        result = run_cin_format(VALID_CIN_PUB)
        assert result.status == "pass"

    def test_valid_cin_npl(self):
        result = run_cin_format(VALID_CIN_NPL)
        assert result.status == "pass"

    def test_invalid_too_short(self):
        result = run_cin_format("U74999MH2010PTC12345")
        assert result.status == "fail"

    def test_invalid_wrong_start_char(self):
        """Must start with U or L."""
        result = run_cin_format("X74999MH2010PTC123456")
        assert result.status == "fail"

    def test_empty(self):
        result = run_cin_format("")
        assert result.status == "fail"

    def test_lowercase_normalised(self):
        result = run_cin_format(VALID_CIN_PVT.lower())
        assert result.status == "pass"


class TestCinListingStatus:
    def test_unlisted_matches_unlisted_claim(self):
        result = run_cin_listing_status(VALID_CIN_PVT, False)
        assert result.status == "pass"

    def test_listed_matches_listed_claim(self):
        result = run_cin_listing_status(VALID_CIN_PUB, True)
        assert result.status == "pass"

    def test_mismatch_unlisted_claimed_listed(self):
        result = run_cin_listing_status(VALID_CIN_PVT, True)
        assert result.status == "fail"
        assert result.severity == "fixable"

    def test_no_claim_passes(self):
        result = run_cin_listing_status(VALID_CIN_PVT, None)
        assert result.status == "pass"


class TestCinStateMatch:
    def test_matching_state(self):
        # VALID_CIN_PVT has state MH at chars 6-7
        result = run_cin_state_match(VALID_CIN_PVT, "MH")
        assert result.status == "pass"
        assert result.severity == "soft"

    def test_mismatched_state(self):
        result = run_cin_state_match(VALID_CIN_PVT, "DL")
        assert result.status == "warn"
        assert result.severity == "soft"
        assert result.score_contribution == 5.0


class TestCinYearMatch:
    def test_matching_year(self):
        result = run_cin_year_match(VALID_CIN_PVT, 2010)
        assert result.status == "pass"
        assert result.severity == "hard"

    def test_mismatched_year(self):
        result = run_cin_year_match(VALID_CIN_PVT, 2015)
        assert result.status == "fail"
        assert result.severity == "hard"

    def test_invalid_cin_fails(self):
        result = run_cin_year_match("INVALID", 2010)
        assert result.status == "fail"


class TestCinEntityTypeMatch:
    def test_ptc_matches_pvt_ltd(self):
        result = run_cin_entity_type_match(VALID_CIN_PVT, "pvt_ltd")
        assert result.status == "pass"

    def test_plc_matches_pub_ltd(self):
        result = run_cin_entity_type_match(VALID_CIN_PUB, "pub_ltd")
        assert result.status == "pass"

    def test_npl_matches_section8(self):
        result = run_cin_entity_type_match(VALID_CIN_NPL, "section8")
        assert result.status == "pass"

    def test_ptc_does_not_match_pub_ltd(self):
        result = run_cin_entity_type_match(VALID_CIN_PVT, "pub_ltd")
        assert result.status == "fail"
        assert result.severity == "hard"

    def test_invalid_cin_fails(self):
        result = run_cin_entity_type_match("INVALID", "pvt_ltd")
        assert result.status == "fail"
