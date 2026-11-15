"""
Unit tests for app/pipeline/rule_engine.py.
Ensures every validator is wired correctly without signature/argument mismatch.
"""
from __future__ import annotations

import pytest

from app.adapters.mock import MockAdapter
from app.config import Config, load_config
from app.demo_scenarios import make_gstin
from app.pipeline.rule_engine import run_all_checks
from app.validators import CheckResult


@pytest.fixture
def config() -> Config:
    return load_config("policy.yaml")


def test_rule_engine_clean_pvt_ltd(config):
    pan = "AABCA1234C"
    gstin = make_gstin("27", pan)
    submission = {
        "entity_type": "pvt_ltd",
        "legal_name": "Acme Industrial Systems Private Limited",
        "pan": pan,
        "gstin": gstin,
        "cin": "U12345MH2018PTC123456",
        "ifsc": "SBIN0000300",
        "address_state_code": "27",
        "udyam_number": "UDYAM-MH-00-0012345",
        "udyam_category": "micro",
        "udyam_activity_type": "manufacturing",
        "agreed_payment_days": 30,
        "bank_account_number": "hmac_digest_123",
    }
    extracted_fields = {
        "pan_card": {
            "pan_number": pan,
            "name_on_pan": "Acme Industrial Systems Private Limited",
            "_doc_type_detected": "pan_card",
        },
        "cancelled_cheque": {
            "account_holder_name": "Acme Industrial Systems Private Limited",
            "ifsc_on_cheque": "SBIN0000300",
            "account_last4_on_cheque": "1234",
            "_doc_type_detected": "cancelled_cheque",
        },
        "gst_certificate": {
            "gstin_on_cert": gstin,
            "legal_name_on_cert": "Acme Industrial Systems Private Limited",
            "principal_place_state_code": "27",
            "_doc_type_detected": "gst_certificate",
        },
        "coi": {
            "cin_on_coi": "U12345MH2018PTC123456",
            "company_name_on_coi": "Acme Industrial Systems Private Limited",
            "incorporation_date": "2018-05-10",
            "_doc_type_detected": "coi",
        },
        "udyam_cert": {
            "udyam_category": "micro",
            "udyam_activity_type": "manufacturing",
            "_doc_type_detected": "udyam_cert",
        },
    }
    confidences = {
        "pan_card": {"pan_number": 0.98, "name_on_pan": 0.95},
        "cancelled_cheque": {"account_holder_name": 0.95, "ifsc_on_cheque": 0.98, "account_last4_on_cheque": 0.95},
        "gst_certificate": {"gstin_on_cert": 0.98, "legal_name_on_cert": 0.96, "principal_place_state_code": 0.95},
        "coi": {"cin_on_coi": 0.98, "company_name_on_coi": 0.95, "incorporation_date": 0.95},
        "udyam_cert": {"udyam_category": 0.95, "udyam_activity_type": 0.95},
    }
    uploaded_docs = ["pan_card", "gst_certificate", "cancelled_cheque", "coi"]

    results = run_all_checks(
        submission=submission,
        extracted_fields_by_doc=extracted_fields,
        confidences_by_doc=confidences,
        raw_text_by_doc={},
        config=config,
        uploaded_doc_types=uploaded_docs,
    )

    failing = [r for r in results if r.status in ("fail", "missing")]
    assert not failing, f"Expected no failing checks, got: {[r.check_name for r in failing]}"

    # Verify payment term cap calculation
    cap_result = next((r for r in results if r.check_name == "payment_term_cap"), None)
    assert cap_result is not None
    assert cap_result.evidence["payment_term_cap_days"] == 30


def test_rule_engine_gstin_state_code_confidence_gate(config):
    submission = {
        "entity_type": "proprietorship",
        "legal_name": "Test Prop",
        "pan": "AABCP1234A",
        "gstin": "27AABCP1234A1ZP",
        "ifsc": "SBIN0000300",
        "address_state_code": "27",
    }
    # Low confidence on state extraction
    extracted_fields = {
        "gst_certificate": {"principal_place_state_code": "29"},  # Mismatch
    }
    confidences = {
        "gst_certificate": {"principal_place_state_code": 0.50},  # Low confidence (<0.80)
    }

    results = run_all_checks(
        submission=submission,
        extracted_fields_by_doc=extracted_fields,
        confidences_by_doc=confidences,
        raw_text_by_doc={},
        config=config,
        uploaded_doc_types=["pan_card", "gst_certificate", "cancelled_cheque"],
    )

    g4 = next((r for r in results if r.check_name == "gstin_state_code_match"), None)
    assert g4 is not None
    assert g4.severity == "fixable"
    assert "downgraded" in g4.message.lower() or "confidence" in g4.message.lower()


def test_rule_engine_duplicate_bank_account_escalate(config):
    submission = {
        "entity_type": "proprietorship",
        "legal_name": "Test Prop",
        "pan": "AABCP1234A",
        "gstin": "27AABCP1234A1ZP",
        "ifsc": "SBIN0000300",
        "address_state_code": "27",
        "bank_account_number": "collision_hmac_123",
    }
    results = run_all_checks(
        submission=submission,
        extracted_fields_by_doc={},
        confidences_by_doc={},
        raw_text_by_doc={},
        config=config,
        existing_bank_account_hmacs={"collision_hmac_123"},
        uploaded_doc_types=["pan_card", "gst_certificate", "cancelled_cheque"],
    )

    dv2 = next((r for r in results if r.check_name == "duplicate_bank_account"), None)
    assert dv2 is not None
    assert dv2.severity == "escalate"
    assert dv2.status == "fail"


def test_rule_engine_trading_msme_cap_is_none(config):
    submission = {
        "entity_type": "llp",
        "legal_name": "Trading LLP",
        "pan": "AABCF1234A",
        "llpin": "AAA-1234",
        "gstin": "24AABCF1234A1ZP",
        "ifsc": "SBIN0000300",
        "address_state_code": "24",
        "udyam_number": "UDYAM-GJ-00-0098765",
        "udyam_category": "small",
        "udyam_activity_type": "trading",
        "agreed_payment_days": 45,
    }
    results = run_all_checks(
        submission=submission,
        extracted_fields_by_doc={},
        confidences_by_doc={},
        raw_text_by_doc={},
        config=config,
        uploaded_doc_types=["pan_card", "gst_certificate", "cancelled_cheque", "llpin_cert"],
    )

    cap_res = next((r for r in results if r.check_name == "payment_term_cap"), None)
    assert cap_res is not None
    assert cap_res.evidence["payment_term_cap_days"] is None


def test_no_check_silently_skipped_on_empty_extraction(config):
    """
    Fail-closed assertion: If required documents are uploaded but fields cannot be read,
    no dependent check is silently skipped; each produces a fixable failure.
    """
    pan = "AABCA1234C"
    gstin = make_gstin("27", pan)
    submission = {
        "entity_type": "pvt_ltd",
        "legal_name": "Acme Industrial Systems Private Limited",
        "pan": pan,
        "gstin": gstin,
        "cin": "U12345MH2018PTC123456",
        "ifsc": "SBIN0000300",
        "address_state_code": "27",
        "udyam_number": "UDYAM-MH-00-0012345",
    }
    # Completely empty extracted fields (e.g. unreadable scan or failed OCR)
    extracted_fields = {
        "pan_card": {"_doc_type_detected": "pan_card"},
        "gst_certificate": {"_doc_type_detected": "gst_certificate"},
        "cancelled_cheque": {"_doc_type_detected": "cancelled_cheque"},
        "coi": {"_doc_type_detected": "coi"},
        "udyam_cert": {"_doc_type_detected": "udyam_cert"},
    }
    uploaded_docs = ["pan_card", "gst_certificate", "cancelled_cheque", "coi", "udyam_cert"]

    results = run_all_checks(
        submission=submission,
        extracted_fields_by_doc=extracted_fields,
        confidences_by_doc={},
        raw_text_by_doc={},
        config=config,
        uploaded_doc_types=uploaded_docs,
    )

    check_names = {r.check_name: r for r in results}

    # 1. Bank name match was NOT silently skipped — it produced a fixable failure
    assert "bank_name_fuzzy_match" in check_names
    assert check_names["bank_name_fuzzy_match"].status == "fail"
    assert check_names["bank_name_fuzzy_match"].severity == "fixable"
    assert "Couldn't read account holder name" in check_names["bank_name_fuzzy_match"].message

    # 2. CIN year match was NOT silently skipped — it produced a fixable failure
    assert "cin_year_match" in check_names
    assert check_names["cin_year_match"].status == "fail"
    assert check_names["cin_year_match"].severity == "fixable"
    assert "Couldn't read incorporation date" in check_names["cin_year_match"].message

    # 3. GSTIN state code match was NOT silently skipped — it produced a fixable failure
    assert "gstin_state_code_match" in check_names
    assert check_names["gstin_state_code_match"].status == "fail"
    assert check_names["gstin_state_code_match"].severity == "fixable"
    assert "Couldn't read principal place state code" in check_names["gstin_state_code_match"].message

    # 4. Udyam readable check was NOT silently skipped
    assert "udyam_details_readable" in check_names
    assert check_names["udyam_details_readable"].status == "fail"
    assert check_names["udyam_details_readable"].severity == "fixable"


def test_document_type_verification_mismatch(config):
    """
    Document type verification: Classify each upload and compare to slot.
    Mismatch produces fixable failure.
    """
    submission = {
        "entity_type": "proprietorship",
        "legal_name": "Test Prop",
        "pan": "AABCP1234A",
        "ifsc": "SBIN0000300",
    }
    # GST certificate uploaded into cancelled_cheque slot
    extracted_fields = {
        "cancelled_cheque": {"_doc_type_detected": "gst_certificate"},
    }
    results = run_all_checks(
        submission=submission,
        extracted_fields_by_doc=extracted_fields,
        confidences_by_doc={},
        raw_text_by_doc={},
        config=config,
        uploaded_doc_types=["cancelled_cheque"],
    )

    doc_match = next((r for r in results if r.check_name == "document_type_match_cancelled_cheque"), None)
    assert doc_match is not None
    assert doc_match.status == "fail"
    assert doc_match.severity == "fixable"
    assert "looks like a gst certificate, not a cancelled cheque" in doc_match.message.lower()


def test_gst_state_vs_address_state_soft_check(config):
    """
    Multi-state vendor: GST certificate state (e.g. 29 Karnataka) differs from
    corporate registered address state (e.g. 27 Maharashtra).
    Produces soft check warn (+10 risk weight from policy.yaml).
    """
    submission = {
        "entity_type": "pvt_ltd",
        "legal_name": "Multi State Enterprises Private Limited",
        "pan": "AABCQ1515Q",
        "gstin": "29AABCQ1515Q1Z1",
        "cin": "U72200MH2018PTC151515",
        "ifsc": "SBIN0000300",
        "address_state_code": "27",
    }
    extracted_fields = {
        "gst_certificate": {
            "principal_place_state_code": "29",
            "gstin": "29AABCQ1515Q1Z1",
            "legal_name": "Multi State Enterprises Private Limited",
        }
    }
    results = run_all_checks(
        submission=submission,
        extracted_fields_by_doc=extracted_fields,
        confidences_by_doc={"gst_certificate": {"principal_place_state_code": 0.95}},
        raw_text_by_doc={},
        config=config,
        uploaded_doc_types=["gst_certificate"],
    )

    state_check = next((r for r in results if r.check_name == "gst_state_vs_address_state"), None)
    assert state_check is not None, "gst_state_vs_address_state check must be produced"
    assert state_check.status == "warn"
    assert state_check.severity == "soft"
    assert state_check.score_contribution == 10.0
    assert state_check.evidence["gst_cert_state"] == "29"
    assert state_check.evidence["address_state"] == "27"

