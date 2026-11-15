"""
tests/test_cross_document.py — Unit and integration tests for cross-document consistency checks CD1–CD7 (§3.13 of SPEC).
"""
from __future__ import annotations

import pytest

from app.validators.cross_document import (
    run_cd1_pan_card_number_match,
    run_cd2_pan_card_name_match,
    run_cd3_gst_cert_gstin_match,
    run_cd4_gst_cert_name_match,
    run_cd5a_coi_cin_match,
    run_cd5b_coi_name_match,
    run_cd6_cheque_ifsc_account_match,
    run_cd7_gst_cert_address_vs_proof,
)


# ---------------------------------------------------------------------------
# CD1: pan_card_number_match
# ---------------------------------------------------------------------------
class TestCD1PanNumberMatch:
    def test_raw_text_verbatim_search_passes(self):
        res = run_cd1_pan_card_number_match(
            submitted_pan="AABCU9603R",
            raw_text="GOVT OF INDIA\nINCOME TAX DEPT\nPAN: AABCU9603R\nNAME: ACME",
            extracted_pan="DIFFERENT",  # Ignored because found in raw text
        )
        assert res.status == "pass"
        assert res.severity == "hard"
        assert res.evidence["matched_via"] == "raw_text_search"

    def test_extracted_pan_exact_match_passes(self):
        res = run_cd1_pan_card_number_match(
            submitted_pan="AABCU9603R",
            raw_text="No plain PAN in text",
            extracted_pan="AABCU9603R",
            confidence=0.98,
        )
        assert res.status == "pass"
        assert res.severity == "hard"

    def test_edit_distance_one_is_fixable_ocr_error(self):
        # AABCU9603R vs AABCU9603K (dist = 1)
        res = run_cd1_pan_card_number_match(
            submitted_pan="AABCU9603R",
            raw_text="",
            extracted_pan="AABCU9603K",
            confidence=0.95,
        )
        assert res.status == "fail"
        assert res.severity == "fixable"
        assert "probable OCR error" in res.explanation

    def test_edit_distance_two_is_fixable_ocr_error(self):
        # AABCU9603R vs AABCU9608K (dist = 2)
        res = run_cd1_pan_card_number_match(
            submitted_pan="AABCU9603R",
            raw_text="",
            extracted_pan="AABCU9608K",
            confidence=0.95,
        )
        assert res.status == "fail"
        assert res.severity == "fixable"
        assert res.evidence["edit_distance"] == 2

    def test_confidently_different_is_hard_fail(self):
        # AABCU9603R vs ZZXYA1111Z (dist = 10, conf >= 0.80)
        res = run_cd1_pan_card_number_match(
            submitted_pan="AABCU9603R",
            raw_text="",
            extracted_pan="ZZXYA1111Z",
            confidence=0.95,
            min_confidence=0.80,
        )
        assert res.status == "fail"
        assert res.severity == "hard"

    def test_different_with_low_confidence_is_fixable_gate(self):
        # Confidence < 0.80 -> downgraded to fixable
        res = run_cd1_pan_card_number_match(
            submitted_pan="AABCU9603R",
            raw_text="",
            extracted_pan="ZZXYA1111Z",
            confidence=0.50,
            min_confidence=0.80,
        )
        assert res.status == "fail"
        assert res.severity == "fixable"
        assert "Document unreadable" in res.explanation

    def test_missing_extracted_pan_is_fixable(self):
        res = run_cd1_pan_card_number_match(
            submitted_pan="AABCU9603R",
            raw_text="",
            extracted_pan=None,
        )
        assert res.status == "fail"
        assert res.severity == "fixable"
        assert "Couldn't read PAN" in res.explanation


# ---------------------------------------------------------------------------
# CD2: pan_card_name_match
# ---------------------------------------------------------------------------
class TestCD2PanNameMatch:
    def test_name_match_above_threshold_passes(self):
        res = run_cd2_pan_card_name_match(
            submitted_legal_name="Acme Manufacturing Private Limited",
            extracted_name="Acme Manufacturing Pvt Ltd",
            threshold=85.0,
        )
        assert res.status == "pass"

    def test_name_mismatch_first_failure_is_fixable(self):
        res = run_cd2_pan_card_name_match(
            submitted_legal_name="Acme Manufacturing Private Limited",
            extracted_name="Global Trade Corporation",
            failed_in_previous_run=False,
            threshold=85.0,
        )
        assert res.status == "fail"
        assert res.severity == "fixable"

    def test_name_mismatch_repeat_failure_is_hard(self):
        res = run_cd2_pan_card_name_match(
            submitted_legal_name="Acme Manufacturing Private Limited",
            extracted_name="Global Trade Corporation",
            failed_in_previous_run=True,
            confidence=0.90,
            min_confidence=0.80,
            threshold=85.0,
        )
        assert res.status == "fail"
        assert res.severity == "hard"
        assert "repeat failure" in res.explanation

    def test_missing_extracted_name_is_fixable(self):
        res = run_cd2_pan_card_name_match(
            submitted_legal_name="Acme Manufacturing Private Limited",
            extracted_name="",
        )
        assert res.status == "fail"
        assert res.severity == "fixable"
        assert "Couldn't read name" in res.explanation


# ---------------------------------------------------------------------------
# CD3: gst_cert_gstin_match
# ---------------------------------------------------------------------------
class TestCD3GstCertGstinMatch:
    def test_raw_text_search_passes(self):
        gstin = "27AABCU9603R1ZM"
        res = run_cd3_gst_cert_gstin_match(
            submitted_gstin=gstin,
            raw_text=f"REGISTRATION CERTIFICATE\nGSTIN: {gstin}\nMAHARASHTRA",
            extracted_gstin="",
        )
        assert res.status == "pass"
        assert res.evidence["matched_via"] == "raw_text_search"

    def test_edit_distance_two_is_fixable(self):
        # 27AABCU9603R1ZM vs 27AABCU9603R1ZA (dist = 1)
        res = run_cd3_gst_cert_gstin_match(
            submitted_gstin="27AABCU9603R1ZM",
            raw_text="",
            extracted_gstin="27AABCU9603R1ZA",
            confidence=0.95,
        )
        assert res.status == "fail"
        assert res.severity == "fixable"

    def test_confidently_different_is_hard(self):
        res = run_cd3_gst_cert_gstin_match(
            submitted_gstin="27AABCU9603R1ZM",
            raw_text="",
            extracted_gstin="07AAAAA0000A1Z5",
            confidence=0.95,
            min_confidence=0.80,
        )
        assert res.status == "fail"
        assert res.severity == "hard"


# ---------------------------------------------------------------------------
# CD4: gst_cert_name_match
# ---------------------------------------------------------------------------
class TestCD4GstCertNameMatch:
    def test_matches_via_legal_name(self):
        res = run_cd4_gst_cert_name_match(
            submitted_legal_name="Delta Commodities Private Limited",
            extracted_legal_name="Delta Commodities Pvt Ltd",
            extracted_trade_name="",
        )
        assert res.status == "pass"

    def test_matches_via_trade_name(self):
        res = run_cd4_gst_cert_name_match(
            submitted_legal_name="Delta Commodities Private Limited",
            extracted_legal_name="XYZ Holding Corp",
            extracted_trade_name="Delta Commodities",
        )
        assert res.status == "pass"

    def test_mismatch_first_run_is_fixable(self):
        res = run_cd4_gst_cert_name_match(
            submitted_legal_name="Delta Commodities Private Limited",
            extracted_legal_name="Completely Wrong Name Ltd",
            failed_in_previous_run=False,
        )
        assert res.status == "fail"
        assert res.severity == "fixable"

    def test_mismatch_repeat_run_is_hard(self):
        res = run_cd4_gst_cert_name_match(
            submitted_legal_name="Delta Commodities Private Limited",
            extracted_legal_name="Completely Wrong Name Ltd",
            failed_in_previous_run=True,
            confidence=0.92,
        )
        assert res.status == "fail"
        assert res.severity == "hard"


# ---------------------------------------------------------------------------
# CD5a & CD5b: coi_cin_match & coi_name_match
# ---------------------------------------------------------------------------
class TestCD5CoiMatches:
    def test_cd5a_raw_text_cin_match_passes(self):
        cin = "U12345MH2018PTC123456"
        res = run_cd5a_coi_cin_match(
            submitted_cin=cin,
            raw_text=f"CERTIFICATE OF INCORPORATION\nCIN: {cin}",
            extracted_cin="",
        )
        assert res.status == "pass"

    def test_cd5a_edit_distance_is_fixable(self):
        cin = "U12345MH2018PTC123456"
        cin_ocr = "U12345MH2018PTC123458"  # dist 1
        res = run_cd5a_coi_cin_match(
            submitted_cin=cin,
            raw_text="",
            extracted_cin=cin_ocr,
        )
        assert res.status == "fail"
        assert res.severity == "fixable"

    def test_cd5b_company_name_match_passes(self):
        res = run_cd5b_coi_name_match(
            submitted_legal_name="Acme Industrial Solutions Private Limited",
            extracted_company_name="Acme Industrial Solutions Pvt Ltd",
        )
        assert res.status == "pass"

    def test_cd5b_mismatch_repeat_run_is_hard(self):
        res = run_cd5b_coi_name_match(
            submitted_legal_name="Acme Industrial Solutions Private Limited",
            extracted_company_name="Totally Unrelated Corp Ltd",
            failed_in_previous_run=True,
        )
        assert res.status == "fail"
        assert res.severity == "hard"


# ---------------------------------------------------------------------------
# CD6: cheque_ifsc_account_match
# ---------------------------------------------------------------------------
class TestCD6ChequeMatch:
    def test_raw_text_search_passes(self):
        res = run_cd6_cheque_ifsc_account_match(
            submitted_ifsc="SBIN0000300",
            submitted_last4="1234",
            raw_text="CANCELLED CHEQUE\nIFSC: SBIN0000300\nA/C: XXXX XXXX 1234",
            extracted_ifsc="",
            extracted_last4="",
        )
        assert res.status == "pass"

    def test_edit_distance_is_fixable(self):
        res = run_cd6_cheque_ifsc_account_match(
            submitted_ifsc="SBIN0000300",
            submitted_last4="1234",
            raw_text="",
            extracted_ifsc="SBIN000030O",  # O vs 0 (dist 1)
            extracted_last4="1234",
        )
        assert res.status == "fail"
        assert res.severity == "fixable"

    def test_confidently_different_is_hard(self):
        res = run_cd6_cheque_ifsc_account_match(
            submitted_ifsc="SBIN0000300",
            submitted_last4="1234",
            raw_text="",
            extracted_ifsc="HDFC0001234",
            extracted_last4="9999",
            ifsc_conf=0.95,
            last4_conf=0.95,
        )
        assert res.status == "fail"
        assert res.severity == "hard"


# ---------------------------------------------------------------------------
# CD7: gst_cert_address_vs_proof
# ---------------------------------------------------------------------------
class TestCD7AddressVsProof:
    def test_matching_state_passes(self):
        res = run_cd7_gst_cert_address_vs_proof(
            gst_state_code="27",
            proof_state_code="27",
        )
        assert res is not None
        assert res.status == "pass"
        assert res.severity == "soft"
        assert res.score_contribution == 0.0

    def test_mismatched_state_warns_with_eight_points(self):
        res = run_cd7_gst_cert_address_vs_proof(
            gst_state_code="27",
            proof_state_code="24",  # Gujarat vs Maharashtra
        )
        assert res is not None
        assert res.status == "warn"
        assert res.severity == "soft"
        assert res.score_contribution == 8.0

    def test_low_confidence_skips(self):
        res = run_cd7_gst_cert_address_vs_proof(
            gst_state_code="27",
            proof_state_code="24",
            confidence=0.50,
            min_confidence=0.80,
        )
        assert res is None  # Skipped as per SPEC §3.13
