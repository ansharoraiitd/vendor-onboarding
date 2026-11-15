"""
app/eval_dataset.py — Frozen 38-record evaluation dataset (§11 of SPEC).
Split into 20 tune / 18 holdout records.
15 of 38 records are legitimate vendors (including 6 messy-but-legitimate cases).
5 adversarial test cases.
Ground truth labels written from domain compliance reasoning before rules.
"""
from __future__ import annotations

import dataclasses
from typing import Any, Dict, List, Optional

from app.validators.gstin import _compute_gstin_checksum


def make_gstin(state: str, pan: str, reg_no: str = "1") -> str:
    """Build a syntactically valid GSTIN with correct mod-36 checksum."""
    base14 = f"{state}{pan}{reg_no}Z"
    return base14 + _compute_gstin_checksum(base14)


@dataclasses.dataclass(frozen=True)
class EvalRecord:
    id: str
    split: str                                    # "tune" | "holdout"
    name: str                                     # Vendor legal name
    category: str                                 # "legitimate_clean" | "legitimate_messy" | "adversarial" | "defect"
    notes: str
    expected_outcome: str                         # "approved" | "pending" | "rejected" | "human_review"
    expected_failing_checks: List[str]
    is_legitimate: bool                           # True if legitimate vendor (denominator for false-rejection rate)
    is_adversarial: bool                          # True for adversarial injection cases
    submission: Dict[str, Any]
    docs: Dict[str, Dict[str, Any]]               # doc_type -> extracted fields/confidences/snippets
    pdf_files: Optional[Dict[str, str]] = None    # optional paths to physical PDFs
    needs_vision: bool = False                    # True if document is an image-only scan requiring vision model


# Deterministic valid base identifiers
PAN_LEG01 = "AABCA5678B"
PAN_LEG02 = "AABCB6789C"
PAN_LEG03 = "AABCC7890D"
PAN_LEG04 = "AABCD8901E"
PAN_LEG05 = "AABCE9012F"
PAN_LEG06 = "AABCF0123G"

PAN_ADV01 = "AABCA9991A"
PAN_ADV02 = "AABCB9992B"
PAN_ADV03 = "AABCC9993C"
PAN_ADV04 = "AABCD9994D"
PAN_ADV05 = "AABCE9995E"

PAN_CLN01 = "AAACT1234F"
PAN_CLN02 = "AABCI2345G"
PAN_CLN03 = "AAFFH3456H"   # Firm (4th char F)
PAN_CLN04 = "AAFFS4567I"   # Firm (4th char F)
PAN_CLN05 = "AABPR5678J"   # Proprietor (4th char P)
PAN_CLN06 = "AABCN6789K"   # Section 8 company (4th char C)
PAN_CLN07 = "AAFFV7890L"   # LLP (4th char F)
PAN_CLN08 = "AABPP8901M"   # Proprietor (4th char P)
PAN_CLN09 = "AABCZ9012N"   # Company (4th char C)

PAN_DEF01 = "AABP1234A"    # Invalid (9 chars)
PAN_DEF02 = "AABPP1234A"   # 'P' for pvt_ltd
PAN_DEF03 = "AAFFN0000M"   # Missing in mock ITD
PAN_DEF04 = "AAFCB1234C"   # For bad GSTIN
PAN_DEF05 = "AABCG2345D"   # For bad checksum
PAN_DEF06 = "AABCH3456E"   # Embedded PAN mismatch
PAN_DEF07 = "AABCI4567F"   # State mismatch
PAN_DEF08 = "AABCJ5678G"   # Bad CIN
PAN_DEF09 = "AABCK6789H"   # CIN year mismatch
PAN_DEF10 = "AAFCL7890I"   # Bad LLPIN
PAN_DEF11 = "AAFFM8901J"   # Bad IFSC
PAN_DEF12 = "AABCN9012K"   # Missing IFSC
PAN_DEF13 = "AAFFO0123L"   # Shared account
PAN_DEF14 = "AABCP1234M"   # High soft score
PAN_DEF15 = "AABCQ2345N"   # Missing PAN doc
PAN_DEF16 = "AABCR3456O"   # Missing COI doc
PAN_DEF17 = "AAFFP7890Q"   # PAN collision DV1
PAN_DEF18 = "AABCS4567P"   # Udyam unreadable


EVAL_RECORDS: List[EvalRecord] = [
    # =========================================================================
    # 1. MESSY-BUT-LEGITIMATE CASES (6 records) — MUST APPROVE
    # =========================================================================
    EvalRecord(
        id="LEG01",
        split="tune",
        name="Apex Tech Solutions Private Limited",
        category="legitimate_messy",
        notes="Cheque layout variant: uses 'Beneficiary Name:' header instead of 'Pay to:'. Should approve.",
        expected_outcome="approved",
        expected_failing_checks=[],
        is_legitimate=True,
        is_adversarial=False,
        submission={
            "legal_name": "Apex Tech Solutions Private Limited",
            "entity_type": "pvt_ltd",
            "pan": PAN_LEG01,
            "gstin": make_gstin("27", PAN_LEG01),
            "cin": "U72200MH2016PTC281234",
            "ifsc": "HDFC0001234",
            "bank_account_number": "112233445501",
            "address_state_code": "27",
            "email": "vendor@apextech.example.com",
        },
        docs={
            "pan_card": {
                "detected": "pan_card",
                "fields": {"pan_number": PAN_LEG01, "name_on_pan": "Apex Tech Solutions Private Limited"},
                "confidences": {"pan_number": 0.99, "name_on_pan": 0.98},
            },
            "gst_certificate": {
                "detected": "gst_certificate",
                "fields": {
                    "gstin_on_cert": make_gstin("27", PAN_LEG01),
                    "legal_name_on_cert": "Apex Tech Solutions Private Limited",
                    "principal_place_state_code": "27",
                },
                "confidences": {"gstin_on_cert": 0.99, "legal_name_on_cert": 0.98, "principal_place_state_code": 0.95},
            },
            "cancelled_cheque": {
                "detected": "cancelled_cheque",
                "fields": {
                    "account_holder_name": "Apex Tech Solutions Private Limited",
                    "ifsc_on_cheque": "HDFC0001234",
                    "account_last4_on_cheque": "5501",
                },
                "confidences": {"account_holder_name": 0.98, "ifsc_on_cheque": 0.99, "account_last4_on_cheque": 0.95},
                "raw_text": "CANCELLED CHEQUE\nBeneficiary Name: Apex Tech Solutions Private Limited\nAccount Number: XXXX XXXX 5501\nIFSC: HDFC0001234",
            },
            "coi": {
                "detected": "coi",
                "fields": {
                    "cin_on_coi": "U72200MH2016PTC281234",
                    "company_name_on_coi": "Apex Tech Solutions Private Limited",
                    "incorporation_date": "2016-04-12",
                },
                "confidences": {"cin_on_coi": 0.99, "company_name_on_coi": 0.98, "incorporation_date": 0.95},
            },
        },
    ),
    EvalRecord(
        id="LEG02",
        split="holdout",
        name="Bharat Logistics Private Limited",
        category="legitimate_messy",
        notes="Cheque layout variant: uses 'A/c Holder:' layout with trailing dashes. Should approve.",
        expected_outcome="approved",
        expected_failing_checks=[],
        is_legitimate=True,
        is_adversarial=False,
        submission={
            "legal_name": "Bharat Logistics Private Limited",
            "entity_type": "pvt_ltd",
            "pan": PAN_LEG02,
            "gstin": make_gstin("27", PAN_LEG02),
            "cin": "U60200MH2015PTC271234",
            "ifsc": "ICIC0002456",
            "bank_account_number": "112233445502",
            "address_state_code": "27",
            "email": "vendor@bharatlogistics.example.com",
        },
        docs={
            "pan_card": {
                "detected": "pan_card",
                "fields": {"pan_number": PAN_LEG02, "name_on_pan": "Bharat Logistics Private Limited"},
                "confidences": {"pan_number": 0.99, "name_on_pan": 0.97},
            },
            "gst_certificate": {
                "detected": "gst_certificate",
                "fields": {
                    "gstin_on_cert": make_gstin("27", PAN_LEG02),
                    "legal_name_on_cert": "Bharat Logistics Private Limited",
                    "principal_place_state_code": "27",
                },
                "confidences": {"gstin_on_cert": 0.99, "legal_name_on_cert": 0.98, "principal_place_state_code": 0.95},
            },
            "cancelled_cheque": {
                "detected": "cancelled_cheque",
                "fields": {
                    "account_holder_name": "Bharat Logistics Private Limited",
                    "ifsc_on_cheque": "ICIC0002456",
                    "account_last4_on_cheque": "5502",
                },
                "confidences": {"account_holder_name": 0.97, "ifsc_on_cheque": 0.99, "account_last4_on_cheque": 0.95},
                "raw_text": "CANCELLED CHEQUE\nA/c Holder: Bharat Logistics Private Limited\nAccount: 112233445502\nIFSC: ICIC0002456",
            },
            "coi": {
                "detected": "coi",
                "fields": {
                    "cin_on_coi": "U60200MH2015PTC271234",
                    "company_name_on_coi": "Bharat Logistics Private Limited",
                    "incorporation_date": "2015-08-20",
                },
                "confidences": {"cin_on_coi": 0.99, "company_name_on_coi": 0.98, "incorporation_date": 0.95},
            },
        },
    ),
    EvalRecord(
        id="LEG03",
        split="tune",
        name="Chandra Enterprises Private Limited",
        category="legitimate_messy",
        notes="Name variant: 'Private Limited' in submission vs 'Pvt Ltd' on documents. Levenshtein <= 2. Should approve.",
        expected_outcome="approved",
        expected_failing_checks=[],
        is_legitimate=True,
        is_adversarial=False,
        submission={
            "legal_name": "Chandra Enterprises Private Limited",
            "entity_type": "pvt_ltd",
            "pan": PAN_LEG03,
            "gstin": make_gstin("27", PAN_LEG03),
            "cin": "U51909MH2017PTC291234",
            "ifsc": "SBIN0000300",
            "bank_account_number": "112233445503",
            "address_state_code": "27",
            "email": "vendor@chandraent.example.com",
        },
        docs={
            "pan_card": {
                "detected": "pan_card",
                "fields": {"pan_number": PAN_LEG03, "name_on_pan": "Chandra Enterprises Pvt Ltd"},
                "confidences": {"pan_number": 0.99, "name_on_pan": 0.98},
            },
            "gst_certificate": {
                "detected": "gst_certificate",
                "fields": {
                    "gstin_on_cert": make_gstin("27", PAN_LEG03),
                    "legal_name_on_cert": "Chandra Enterprises Pvt Ltd",
                    "principal_place_state_code": "27",
                },
                "confidences": {"gstin_on_cert": 0.99, "legal_name_on_cert": 0.98, "principal_place_state_code": 0.95},
            },
            "cancelled_cheque": {
                "detected": "cancelled_cheque",
                "fields": {
                    "account_holder_name": "Chandra Enterprises Pvt Ltd",
                    "ifsc_on_cheque": "SBIN0000300",
                    "account_last4_on_cheque": "5503",
                },
                "confidences": {"account_holder_name": 0.98, "ifsc_on_cheque": 0.99, "account_last4_on_cheque": 0.95},
                "raw_text": "CANCELLED CHEQUE\nPay to: Chandra Enterprises Pvt Ltd\nAccount Number: XXXX XXXX 5503\nIFSC: SBIN0000300",
            },
            "coi": {
                "detected": "coi",
                "fields": {
                    "cin_on_coi": "U51909MH2017PTC291234",
                    "company_name_on_coi": "Chandra Enterprises Pvt Ltd",
                    "incorporation_date": "2017-03-10",
                },
                "confidences": {"cin_on_coi": 0.99, "company_name_on_coi": 0.98, "incorporation_date": 0.95},
            },
        },
    ),
    EvalRecord(
        id="LEG04",
        split="holdout",
        name="Dynamic Solutions India Private Limited",
        category="legitimate_messy",
        notes="Name variant: 'Dynamic Solutions (India) Pvt. Ltd.' with punctuation/brackets. Should approve.",
        expected_outcome="approved",
        expected_failing_checks=[],
        is_legitimate=True,
        is_adversarial=False,
        submission={
            "legal_name": "Dynamic Solutions India Private Limited",
            "entity_type": "pvt_ltd",
            "pan": PAN_LEG04,
            "gstin": make_gstin("27", PAN_LEG04),
            "cin": "U74999MH2018PTC301234",
            "ifsc": "HDFC0001234",
            "bank_account_number": "112233445504",
            "address_state_code": "27",
            "email": "vendor@dynamicsolutions.example.com",
        },
        docs={
            "pan_card": {
                "detected": "pan_card",
                "fields": {"pan_number": PAN_LEG04, "name_on_pan": "Dynamic Solutions India Pvt Ltd"},
                "confidences": {"pan_number": 0.99, "name_on_pan": 0.97},
            },
            "gst_certificate": {
                "detected": "gst_certificate",
                "fields": {
                    "gstin_on_cert": make_gstin("27", PAN_LEG04),
                    "legal_name_on_cert": "Dynamic Solutions (India) Pvt. Ltd.",
                    "principal_place_state_code": "27",
                },
                "confidences": {"gstin_on_cert": 0.99, "legal_name_on_cert": 0.98, "principal_place_state_code": 0.95},
            },
            "cancelled_cheque": {
                "detected": "cancelled_cheque",
                "fields": {
                    "account_holder_name": "Dynamic Solutions India Pvt Ltd",
                    "ifsc_on_cheque": "HDFC0001234",
                    "account_last4_on_cheque": "5504",
                },
                "confidences": {"account_holder_name": 0.96, "ifsc_on_cheque": 0.99, "account_last4_on_cheque": 0.95},
                "raw_text": "CANCELLED CHEQUE\nPay to: Dynamic Solutions India Pvt Ltd\nAccount Number: XXXX XXXX 5504\nIFSC: HDFC0001234",
            },
            "coi": {
                "detected": "coi",
                "fields": {
                    "cin_on_coi": "U74999MH2018PTC301234",
                    "company_name_on_coi": "Dynamic Solutions (India) Pvt Ltd",
                    "incorporation_date": "2018-05-18",
                },
                "confidences": {"cin_on_coi": 0.99, "company_name_on_coi": 0.98, "incorporation_date": 0.95},
            },
        },
    ),
    EvalRecord(
        id="LEG05",
        split="tune",
        name="Evergreen Agro Products Private Limited",
        category="legitimate_messy",
        notes="Slightly low-quality scan on GST cert: confidence 0.85; core fields clean. Should approve.",
        expected_outcome="approved",
        expected_failing_checks=[],
        is_legitimate=True,
        is_adversarial=False,
        submission={
            "legal_name": "Evergreen Agro Products Private Limited",
            "entity_type": "pvt_ltd",
            "pan": PAN_LEG05,
            "gstin": make_gstin("27", PAN_LEG05),
            "cin": "U01111MH2019PTC311234",
            "ifsc": "SBIN0000300",
            "bank_account_number": "112233445505",
            "address_state_code": "27",
            "email": "vendor@evergreenagro.example.com",
        },
        docs={
            "pan_card": {
                "detected": "pan_card",
                "fields": {"pan_number": PAN_LEG05, "name_on_pan": "Evergreen Agro Products Private Limited"},
                "confidences": {"pan_number": 0.99, "name_on_pan": 0.98},
            },
            "gst_certificate": {
                "detected": "gst_certificate",
                "fields": {
                    "gstin_on_cert": make_gstin("27", PAN_LEG05),
                    "legal_name_on_cert": "Evergreen Agro Products Private Limited",
                    "principal_place_state_code": "27",
                },
                "confidences": {"gstin_on_cert": 0.98, "legal_name_on_cert": 0.97, "principal_place_state_code": 0.88},
            },
            "cancelled_cheque": {
                "detected": "cancelled_cheque",
                "fields": {
                    "account_holder_name": "Evergreen Agro Products Private Limited",
                    "ifsc_on_cheque": "SBIN0000300",
                    "account_last4_on_cheque": "5505",
                },
                "confidences": {"account_holder_name": 0.97, "ifsc_on_cheque": 0.99, "account_last4_on_cheque": 0.95},
                "raw_text": "CANCELLED CHEQUE\nPay to: Evergreen Agro Products Private Limited\nAccount Number: XXXX XXXX 5505\nIFSC: SBIN0000300",
            },
            "coi": {
                "detected": "coi",
                "fields": {
                    "cin_on_coi": "U01111MH2019PTC311234",
                    "company_name_on_coi": "Evergreen Agro Products Private Limited",
                    "incorporation_date": "2019-09-09",
                },
                "confidences": {"cin_on_coi": 0.99, "company_name_on_coi": 0.98, "incorporation_date": 0.95},
            },
        },
    ),
    EvalRecord(
        id="LEG06",
        split="holdout",
        name="Falcon Engineering Private Limited",
        category="legitimate_messy",
        notes="Bank name near-miss: 'Falcon Engg Pvt Ltd' vs 'Falcon Engineering Private Limited'. Score 75.8 contributes soft risk score 10 < 20. Should approve.",
        expected_outcome="approved",
        expected_failing_checks=[],
        is_legitimate=True,
        is_adversarial=False,
        submission={
            "legal_name": "Falcon Engineering Private Limited",
            "entity_type": "pvt_ltd",
            "pan": PAN_LEG06,
            "gstin": make_gstin("27", PAN_LEG06),
            "cin": "U28920MH2014PTC261234",
            "ifsc": "ICIC0002456",
            "bank_account_number": "112233445506",
            "address_state_code": "27",
            "email": "vendor@falconeng.example.com",
        },
        docs={
            "pan_card": {
                "detected": "pan_card",
                "fields": {"pan_number": PAN_LEG06, "name_on_pan": "Falcon Engineering Private Limited"},
                "confidences": {"pan_number": 0.99, "name_on_pan": 0.98},
            },
            "gst_certificate": {
                "detected": "gst_certificate",
                "fields": {
                    "gstin_on_cert": make_gstin("27", PAN_LEG06),
                    "legal_name_on_cert": "Falcon Engineering Private Limited",
                    "principal_place_state_code": "27",
                },
                "confidences": {"gstin_on_cert": 0.99, "legal_name_on_cert": 0.98, "principal_place_state_code": 0.95},
            },
            "cancelled_cheque": {
                "detected": "cancelled_cheque",
                "fields": {
                    "account_holder_name": "Falcon Engg Pvt Ltd",
                    "ifsc_on_cheque": "ICIC0002456",
                    "account_last4_on_cheque": "5506",
                },
                "confidences": {"account_holder_name": 0.97, "ifsc_on_cheque": 0.99, "account_last4_on_cheque": 0.95},
                "raw_text": "CANCELLED CHEQUE\nPay to: Falcon Engg Pvt Ltd\nAccount Number: XXXX XXXX 5506\nIFSC: ICIC0002456",
            },
            "coi": {
                "detected": "coi",
                "fields": {
                    "cin_on_coi": "U28920MH2014PTC261234",
                    "company_name_on_coi": "Falcon Engineering Private Limited",
                    "incorporation_date": "2014-11-25",
                },
                "confidences": {"cin_on_coi": 0.99, "company_name_on_coi": 0.98, "incorporation_date": 0.95},
            },
        },
    ),

    # =========================================================================
    # 2. ADVERSARIAL CASES (5 records) — MUST NOT APPROVE
    # =========================================================================
    EvalRecord(
        id="ADV01",
        split="tune",
        name="Adversarial Text Cheque Private Limited",
        category="adversarial",
        notes="Adversarial: Text cheque has completely wrong account holder name ('Ramesh Patel'). Must NOT approve.",
        expected_outcome="pending",
        expected_failing_checks=["bank_name_fuzzy_match"],
        is_legitimate=False,
        is_adversarial=True,
        submission={
            "legal_name": "Adversarial Text Cheque Private Limited",
            "entity_type": "pvt_ltd",
            "pan": PAN_ADV01,
            "gstin": make_gstin("27", PAN_ADV01),
            "cin": "U72200MH2018PTC309991",
            "ifsc": "HDFC0001234",
            "bank_account_number": "998877665501",
            "address_state_code": "27",
            "email": "adv1@test.example.com",
        },
        docs={
            "pan_card": {
                "detected": "pan_card",
                "fields": {"pan_number": PAN_ADV01, "name_on_pan": "Adversarial Text Cheque Private Limited"},
                "confidences": {"pan_number": 0.99, "name_on_pan": 0.98},
            },
            "gst_certificate": {
                "detected": "gst_certificate",
                "fields": {"gstin_on_cert": make_gstin("27", PAN_ADV01), "legal_name_on_cert": "Adversarial Text Cheque Private Limited", "principal_place_state_code": "27"},
                "confidences": {"gstin_on_cert": 0.99, "legal_name_on_cert": 0.98, "principal_place_state_code": 0.95},
            },
            "cancelled_cheque": {
                "detected": "cancelled_cheque",
                "fields": {"account_holder_name": "Ramesh Patel", "ifsc_on_cheque": "HDFC0001234", "account_last4_on_cheque": "5501"},
                "confidences": {"account_holder_name": 0.98, "ifsc_on_cheque": 0.99, "account_last4_on_cheque": 0.95},
                "raw_text": "CANCELLED CHEQUE\nPay to: Ramesh Patel\nAccount Number: XXXX XXXX 5501\nIFSC: HDFC0001234",
            },
            "coi": {
                "detected": "coi",
                "fields": {"cin_on_coi": "U72200MH2018PTC309991", "company_name_on_coi": "Adversarial Text Cheque Private Limited", "incorporation_date": "2018-01-01"},
                "confidences": {"cin_on_coi": 0.99, "company_name_on_coi": 0.98},
            },
        },
    ),
    EvalRecord(
        id="ADV02",
        split="holdout",
        name="Adversarial Image Cheque Private Limited",
        category="adversarial",
        notes="Adversarial: Scanned cheque with third-party name ('Vijay Sales Corporation'). Must NOT approve.",
        expected_outcome="pending",
        expected_failing_checks=["bank_name_fuzzy_match"],
        is_legitimate=False,
        is_adversarial=True,
        needs_vision=True,
        submission={
            "legal_name": "Adversarial Image Cheque Private Limited",
            "entity_type": "pvt_ltd",
            "pan": PAN_ADV02,
            "gstin": make_gstin("27", PAN_ADV02),
            "cin": "U72200MH2018PTC309992",
            "ifsc": "SBIN0000300",
            "bank_account_number": "998877665502",
            "address_state_code": "27",
            "email": "adv2@test.example.com",
        },
        docs={
            "pan_card": {
                "detected": "pan_card",
                "fields": {"pan_number": PAN_ADV02, "name_on_pan": "Adversarial Image Cheque Private Limited"},
                "confidences": {"pan_number": 0.99, "name_on_pan": 0.98},
            },
            "gst_certificate": {
                "detected": "gst_certificate",
                "fields": {"gstin_on_cert": make_gstin("27", PAN_ADV02), "legal_name_on_cert": "Adversarial Image Cheque Private Limited", "principal_place_state_code": "27"},
                "confidences": {"gstin_on_cert": 0.99, "legal_name_on_cert": 0.98, "principal_place_state_code": 0.95},
            },
            "cancelled_cheque": {
                "detected": "cancelled_cheque",
                "fields": {"account_holder_name": "Vijay Sales Corporation", "ifsc_on_cheque": "SBIN0000300", "account_last4_on_cheque": "5502"},
                "confidences": {"account_holder_name": 0.96, "ifsc_on_cheque": 0.99, "account_last4_on_cheque": 0.95},
                "raw_text": "STATE BANK OF INDIA\nPayee: Vijay Sales Corporation\nAccount Number: XXXX XXXX 5502\nIFSC: SBIN0000300",
            },
            "coi": {
                "detected": "coi",
                "fields": {"cin_on_coi": "U72200MH2018PTC309992", "company_name_on_coi": "Adversarial Image Cheque Private Limited", "incorporation_date": "2018-01-01"},
                "confidences": {"cin_on_coi": 0.99, "company_name_on_coi": 0.98},
            },
        },
    ),
    EvalRecord(
        id="ADV03",
        split="tune",
        name="Adversarial Layout Cheque Private Limited",
        category="adversarial",
        notes="Adversarial: Cheque with non-standard layout and wrong payee ('Suresh Kumar Gupta'). Must NOT approve.",
        expected_outcome="pending",
        expected_failing_checks=["bank_name_fuzzy_match"],
        is_legitimate=False,
        is_adversarial=True,
        submission={
            "legal_name": "Adversarial Layout Cheque Private Limited",
            "entity_type": "pvt_ltd",
            "pan": PAN_ADV03,
            "gstin": make_gstin("27", PAN_ADV03),
            "cin": "U72200MH2018PTC309993",
            "ifsc": "ICIC0002456",
            "bank_account_number": "998877665503",
            "address_state_code": "27",
            "email": "adv3@test.example.com",
        },
        docs={
            "pan_card": {
                "detected": "pan_card",
                "fields": {"pan_number": PAN_ADV03, "name_on_pan": "Adversarial Layout Cheque Private Limited"},
                "confidences": {"pan_number": 0.99, "name_on_pan": 0.98},
            },
            "gst_certificate": {
                "detected": "gst_certificate",
                "fields": {"gstin_on_cert": make_gstin("27", PAN_ADV03), "legal_name_on_cert": "Adversarial Layout Cheque Private Limited", "principal_place_state_code": "27"},
                "confidences": {"gstin_on_cert": 0.99, "legal_name_on_cert": 0.98, "principal_place_state_code": 0.95},
            },
            "cancelled_cheque": {
                "detected": "cancelled_cheque",
                "fields": {"account_holder_name": "Suresh Kumar Gupta", "ifsc_on_cheque": "ICIC0002456", "account_last4_on_cheque": "5503"},
                "confidences": {"account_holder_name": 0.98, "ifsc_on_cheque": 0.99, "account_last4_on_cheque": 0.95},
                "raw_text": "ICICI BANK\nBeneficiary: Suresh Kumar Gupta\nA/c No: 998877665503\nRTGS/NEFT IFSC: ICIC0002456",
            },
            "coi": {
                "detected": "coi",
                "fields": {"cin_on_coi": "U72200MH2018PTC309993", "company_name_on_coi": "Adversarial Layout Cheque Private Limited", "incorporation_date": "2018-01-01"},
                "confidences": {"cin_on_coi": 0.99, "company_name_on_coi": 0.98},
            },
        },
    ),
    EvalRecord(
        id="ADV04",
        split="holdout",
        name="Adversarial Irrelevant Doc Private Limited",
        category="adversarial",
        notes="Adversarial: Irrelevant essay PDF uploaded into cancelled cheque slot. Fails document type verification. Must NOT approve.",
        expected_outcome="pending",
        expected_failing_checks=["document_type_match_cancelled_cheque"],
        is_legitimate=False,
        is_adversarial=True,
        submission={
            "legal_name": "Adversarial Irrelevant Doc Private Limited",
            "entity_type": "pvt_ltd",
            "pan": PAN_ADV04,
            "gstin": make_gstin("27", PAN_ADV04),
            "cin": "U72200MH2018PTC309994",
            "ifsc": "HDFC0001234",
            "bank_account_number": "998877665504",
            "address_state_code": "27",
            "email": "adv4@test.example.com",
        },
        docs={
            "pan_card": {
                "detected": "pan_card",
                "fields": {"pan_number": PAN_ADV04, "name_on_pan": "Adversarial Irrelevant Doc Private Limited"},
                "confidences": {"pan_number": 0.99, "name_on_pan": 0.98},
            },
            "gst_certificate": {
                "detected": "gst_certificate",
                "fields": {"gstin_on_cert": make_gstin("27", PAN_ADV04), "legal_name_on_cert": "Adversarial Irrelevant Doc Private Limited", "principal_place_state_code": "27"},
                "confidences": {"gstin_on_cert": 0.99, "legal_name_on_cert": 0.98, "principal_place_state_code": 0.95},
            },
            "cancelled_cheque": {
                "detected": "unknown_document",
                "fields": {},
                "confidences": {},
                "raw_text": "The History of Architecture in Ancient Civilizations. Rome was built on seven hills...",
            },
            "coi": {
                "detected": "coi",
                "fields": {"cin_on_coi": "U72200MH2018PTC309994", "company_name_on_coi": "Adversarial Irrelevant Doc Private Limited", "incorporation_date": "2018-01-01"},
                "confidences": {"cin_on_coi": 0.99, "company_name_on_coi": 0.98},
            },
        },
    ),
    EvalRecord(
        id="ADV05",
        split="tune",
        name="Adversarial Slot Swapped Private Limited",
        category="adversarial",
        notes="Adversarial: GST certificate uploaded in PAN card slot. CD1 & slot mismatch. Must NOT approve.",
        expected_outcome="rejected",
        expected_failing_checks=["pan_card_number_match"],
        is_legitimate=False,
        is_adversarial=True,
        submission={
            "legal_name": "Adversarial Slot Swapped Private Limited",
            "entity_type": "pvt_ltd",
            "pan": PAN_ADV05,
            "gstin": make_gstin("27", PAN_ADV05),
            "cin": "U72200MH2018PTC309995",
            "ifsc": "SBIN0000300",
            "bank_account_number": "998877665505",
            "address_state_code": "27",
            "email": "adv5@test.example.com",
        },
        docs={
            "pan_card": {
                "detected": "gst_certificate",
                "fields": {"pan_number": "AAECX9999Z", "gstin_on_cert": make_gstin("27", "AAECX9999Z"), "legal_name_on_cert": "Adversarial Slot Swapped Private Limited"},
                "confidences": {"pan_number": 0.99, "gstin_on_cert": 0.98, "legal_name_on_cert": 0.98},
                "raw_text": f"GOVERNMENT OF INDIA\nGST REGISTRATION CERTIFICATE\nGSTIN: {make_gstin('27', 'AAECX9999Z')}",
            },
            "gst_certificate": {
                "detected": "gst_certificate",
                "fields": {"gstin_on_cert": make_gstin("27", PAN_ADV05), "legal_name_on_cert": "Adversarial Slot Swapped Private Limited", "principal_place_state_code": "27"},
                "confidences": {"gstin_on_cert": 0.99, "legal_name_on_cert": 0.98, "principal_place_state_code": 0.95},
            },
            "cancelled_cheque": {
                "detected": "cancelled_cheque",
                "fields": {"account_holder_name": "Adversarial Slot Swapped Private Limited", "ifsc_on_cheque": "SBIN0000300", "account_last4_on_cheque": "5505"},
                "confidences": {"account_holder_name": 0.98, "ifsc_on_cheque": 0.99, "account_last4_on_cheque": 0.95},
                "raw_text": "CANCELLED CHEQUE\nPay to: Adversarial Slot Swapped Private Limited\nAccount Number: XXXX XXXX 5505\nIFSC: SBIN0000300",
            },
            "coi": {
                "detected": "coi",
                "fields": {"cin_on_coi": "U72200MH2018PTC309995", "company_name_on_coi": "Adversarial Slot Swapped Private Limited", "incorporation_date": "2018-01-01"},
                "confidences": {"cin_on_coi": 0.99, "company_name_on_coi": 0.98},
            },
        },
    ),

    # =========================================================================
    # 3. CLEAN APPROVALS ACROSS ENTITY TYPES (9 records) — MUST APPROVE
    # =========================================================================
    EvalRecord(
        id="CLN01",
        split="tune",
        name="Tata Consultancy Services Limited",
        category="legitimate_clean",
        notes="Clean Public Limited company onboarding. All checks pass.",
        expected_outcome="approved",
        expected_failing_checks=[],
        is_legitimate=True,
        is_adversarial=False,
        submission={
            "legal_name": "Tata Consultancy Services Limited",
            "entity_type": "pub_ltd",
            "pan": PAN_CLN01,
            "gstin": make_gstin("27", PAN_CLN01),
            "cin": "L22210MH1995PLC084781",
            "ifsc": "SBIN0000300",
            "bank_account_number": "223344556601",
            "address_state_code": "27",
            "email": "vendor@tcs.example.com",
        },
        docs={
            "pan_card": {"detected": "pan_card", "fields": {"pan_number": PAN_CLN01, "name_on_pan": "Tata Consultancy Services Limited"}, "confidences": {"pan_number": 0.99, "name_on_pan": 0.98}},
            "gst_certificate": {"detected": "gst_certificate", "fields": {"gstin_on_cert": make_gstin("27", PAN_CLN01), "legal_name_on_cert": "Tata Consultancy Services Limited", "principal_place_state_code": "27"}, "confidences": {"gstin_on_cert": 0.99, "legal_name_on_cert": 0.98, "principal_place_state_code": 0.95}},
            "cancelled_cheque": {"detected": "cancelled_cheque", "fields": {"account_holder_name": "Tata Consultancy Services Limited", "ifsc_on_cheque": "SBIN0000300", "account_last4_on_cheque": "6601"}, "confidences": {"account_holder_name": 0.98, "ifsc_on_cheque": 0.99, "account_last4_on_cheque": 0.95}},
            "coi": {"detected": "coi", "fields": {"cin_on_coi": "L22210MH1995PLC084781", "company_name_on_coi": "Tata Consultancy Services Limited", "incorporation_date": "1995-01-19"}, "confidences": {"cin_on_coi": 0.99, "company_name_on_coi": 0.98}},
        },
    ),
    EvalRecord(
        id="CLN02",
        split="holdout",
        name="Infosys BPM Limited",
        category="legitimate_clean",
        notes="Clean Public Limited company in Karnataka. All checks pass.",
        expected_outcome="approved",
        expected_failing_checks=[],
        is_legitimate=True,
        is_adversarial=False,
        submission={
            "legal_name": "Infosys BPM Limited",
            "entity_type": "pub_ltd",
            "pan": PAN_CLN02,
            "gstin": make_gstin("29", PAN_CLN02),
            "cin": "L72200KA2002PLC030310",
            "ifsc": "HDFC0001234",
            "bank_account_number": "223344556602",
            "address_state_code": "29",
            "email": "vendor@infosysbpm.example.com",
        },
        docs={
            "pan_card": {"detected": "pan_card", "fields": {"pan_number": PAN_CLN02, "name_on_pan": "Infosys BPM Limited"}, "confidences": {"pan_number": 0.99, "name_on_pan": 0.98}},
            "gst_certificate": {"detected": "gst_certificate", "fields": {"gstin_on_cert": make_gstin("29", PAN_CLN02), "legal_name_on_cert": "Infosys BPM Limited", "principal_place_state_code": "29"}, "confidences": {"gstin_on_cert": 0.99, "legal_name_on_cert": 0.98, "principal_place_state_code": 0.95}},
            "cancelled_cheque": {"detected": "cancelled_cheque", "fields": {"account_holder_name": "Infosys BPM Limited", "ifsc_on_cheque": "HDFC0001234", "account_last4_on_cheque": "6602"}, "confidences": {"account_holder_name": 0.98, "ifsc_on_cheque": 0.99, "account_last4_on_cheque": 0.95}},
            "coi": {"detected": "coi", "fields": {"cin_on_coi": "L72200KA2002PLC030310", "company_name_on_coi": "Infosys BPM Limited", "incorporation_date": "2002-04-03"}, "confidences": {"cin_on_coi": 0.99, "company_name_on_coi": 0.98}},
        },
    ),
    EvalRecord(
        id="CLN03",
        split="tune",
        name="Hindustan Logistics LLP",
        category="legitimate_clean",
        notes="Clean LLP with LLPIN certificate. All checks pass.",
        expected_outcome="approved",
        expected_failing_checks=[],
        is_legitimate=True,
        is_adversarial=False,
        submission={
            "legal_name": "Hindustan Logistics LLP",
            "entity_type": "llp",
            "pan": PAN_CLN03,
            "gstin": make_gstin("27", PAN_CLN03),
            "llpin": "AAB-5678",
            "ifsc": "ICIC0002456",
            "bank_account_number": "223344556603",
            "address_state_code": "27",
            "email": "vendor@hindustanlog.example.com",
        },
        docs={
            "pan_card": {"detected": "pan_card", "fields": {"pan_number": PAN_CLN03, "name_on_pan": "Hindustan Logistics LLP"}, "confidences": {"pan_number": 0.99, "name_on_pan": 0.98}},
            "gst_certificate": {"detected": "gst_certificate", "fields": {"gstin_on_cert": make_gstin("27", PAN_CLN03), "legal_name_on_cert": "Hindustan Logistics LLP", "principal_place_state_code": "27"}, "confidences": {"gstin_on_cert": 0.99, "legal_name_on_cert": 0.98, "principal_place_state_code": 0.95}},
            "cancelled_cheque": {"detected": "cancelled_cheque", "fields": {"account_holder_name": "Hindustan Logistics LLP", "ifsc_on_cheque": "ICIC0002456", "account_last4_on_cheque": "6603"}, "confidences": {"account_holder_name": 0.98, "ifsc_on_cheque": 0.99, "account_last4_on_cheque": 0.95}},
            "llpin_cert": {"detected": "llpin_cert", "fields": {"llpin_on_cert": "AAB-5678", "llp_name_on_cert": "Hindustan Logistics LLP"}, "confidences": {"llpin_on_cert": 0.99, "llp_name_on_cert": 0.98}},
        },
    ),
    EvalRecord(
        id="CLN04",
        split="holdout",
        name="Sharma & Sons Partnership Firm",
        category="legitimate_clean",
        notes="Clean Partnership firm with address proof. All checks pass.",
        expected_outcome="approved",
        expected_failing_checks=[],
        is_legitimate=True,
        is_adversarial=False,
        submission={
            "legal_name": "Sharma & Sons Partnership Firm",
            "entity_type": "partnership",
            "pan": PAN_CLN04,
            "gstin": make_gstin("07", PAN_CLN04),
            "ifsc": "SBIN0000300",
            "bank_account_number": "223344556604",
            "address_state_code": "07",
            "email": "vendor@sharmasons.example.com",
        },
        docs={
            "pan_card": {"detected": "pan_card", "fields": {"pan_number": PAN_CLN04, "name_on_pan": "Sharma & Sons Partnership Firm"}, "confidences": {"pan_number": 0.99, "name_on_pan": 0.98}},
            "gst_certificate": {"detected": "gst_certificate", "fields": {"gstin_on_cert": make_gstin("07", PAN_CLN04), "legal_name_on_cert": "Sharma & Sons Partnership Firm", "principal_place_state_code": "07"}, "confidences": {"gstin_on_cert": 0.99, "legal_name_on_cert": 0.98, "principal_place_state_code": 0.95}},
            "cancelled_cheque": {"detected": "cancelled_cheque", "fields": {"account_holder_name": "Sharma & Sons Partnership Firm", "ifsc_on_cheque": "SBIN0000300", "account_last4_on_cheque": "6604"}, "confidences": {"account_holder_name": 0.98, "ifsc_on_cheque": 0.99, "account_last4_on_cheque": 0.95}},
            "address_proof": {"detected": "address_proof", "fields": {"address_text": "Connaught Place, New Delhi 110001"}, "confidences": {"address_text": 0.95}},
        },
    ),
    EvalRecord(
        id="CLN05",
        split="tune",
        name="Rajesh Kumar",
        category="legitimate_clean",
        notes="Clean Proprietorship with PAN 4th char 'P'. All checks pass.",
        expected_outcome="approved",
        expected_failing_checks=[],
        is_legitimate=True,
        is_adversarial=False,
        submission={
            "legal_name": "Rajesh Kumar",
            "trade_name": "Rajesh Auto Spares",
            "entity_type": "proprietorship",
            "pan": PAN_CLN05,
            "gstin": make_gstin("27", PAN_CLN05),
            "ifsc": "HDFC0001234",
            "bank_account_number": "223344556605",
            "address_state_code": "27",
            "email": "vendor@rajeshauto.example.com",
        },
        docs={
            "pan_card": {"detected": "pan_card", "fields": {"pan_number": PAN_CLN05, "name_on_pan": "Rajesh Kumar"}, "confidences": {"pan_number": 0.99, "name_on_pan": 0.98}},
            "gst_certificate": {"detected": "gst_certificate", "fields": {"gstin_on_cert": make_gstin("27", PAN_CLN05), "legal_name_on_cert": "Rajesh Kumar", "principal_place_state_code": "27"}, "confidences": {"gstin_on_cert": 0.99, "legal_name_on_cert": 0.98, "principal_place_state_code": 0.95}},
            "cancelled_cheque": {"detected": "cancelled_cheque", "fields": {"account_holder_name": "Rajesh Kumar", "ifsc_on_cheque": "HDFC0001234", "account_last4_on_cheque": "6605"}, "confidences": {"account_holder_name": 0.98, "ifsc_on_cheque": 0.99, "account_last4_on_cheque": 0.95}},
            "address_proof": {"detected": "address_proof", "fields": {"address_text": "Station Road, Pune 411001"}, "confidences": {"address_text": 0.95}},
        },
    ),
    EvalRecord(
        id="CLN06",
        split="holdout",
        name="Navjeevan Foundation",
        category="legitimate_clean",
        notes="Clean Section 8 non-profit company (PAN 4th char 'C'). All checks pass.",
        expected_outcome="approved",
        expected_failing_checks=[],
        is_legitimate=True,
        is_adversarial=False,
        submission={
            "legal_name": "Navjeevan Foundation",
            "entity_type": "section8",
            "pan": PAN_CLN06,
            "gstin": make_gstin("27", PAN_CLN06),
            "cin": "U85300MH2020NPL341234",
            "ifsc": "SBIN0000300",
            "bank_account_number": "223344556606",
            "address_state_code": "27",
            "email": "vendor@navjeevan.example.com",
        },
        docs={
            "pan_card": {"detected": "pan_card", "fields": {"pan_number": PAN_CLN06, "name_on_pan": "Navjeevan Foundation"}, "confidences": {"pan_number": 0.99, "name_on_pan": 0.98}},
            "gst_certificate": {"detected": "gst_certificate", "fields": {"gstin_on_cert": make_gstin("27", PAN_CLN06), "legal_name_on_cert": "Navjeevan Foundation", "principal_place_state_code": "27"}, "confidences": {"gstin_on_cert": 0.99, "legal_name_on_cert": 0.98, "principal_place_state_code": 0.95}},
            "cancelled_cheque": {"detected": "cancelled_cheque", "fields": {"account_holder_name": "Navjeevan Foundation", "ifsc_on_cheque": "SBIN0000300", "account_last4_on_cheque": "6606"}, "confidences": {"account_holder_name": 0.98, "ifsc_on_cheque": 0.99, "account_last4_on_cheque": 0.95}},
            "coi": {"detected": "coi", "fields": {"cin_on_coi": "U85300MH2020NPL341234", "company_name_on_coi": "Navjeevan Foundation", "incorporation_date": "2020-02-14"}, "confidences": {"cin_on_coi": 0.99, "company_name_on_coi": 0.98}},
        },
    ),
    EvalRecord(
        id="CLN07",
        split="tune",
        name="Vanguard Trading LLP",
        category="legitimate_clean",
        notes="Trading MSME activity: exempt from MSME payment cap (cap = None). Approved.",
        expected_outcome="approved",
        expected_failing_checks=[],
        is_legitimate=True,
        is_adversarial=False,
        submission={
            "legal_name": "Vanguard Trading LLP",
            "entity_type": "llp",
            "pan": PAN_CLN07,
            "gstin": make_gstin("24", PAN_CLN07),
            "llpin": "AAC-9012",
            "ifsc": "ICIC0002456",
            "bank_account_number": "223344556607",
            "udyam_number": "UDYAM-GJ-00-0019283",
            "udyam_category": "small",
            "udyam_activity_type": "trading",
            "address_state_code": "24",
            "email": "vendor@vanguardtrading.example.com",
            "agreed_payment_days": 45,
        },
        docs={
            "pan_card": {"detected": "pan_card", "fields": {"pan_number": PAN_CLN07, "name_on_pan": "Vanguard Trading LLP"}, "confidences": {"pan_number": 0.99, "name_on_pan": 0.98}},
            "gst_certificate": {"detected": "gst_certificate", "fields": {"gstin_on_cert": make_gstin("24", PAN_CLN07), "legal_name_on_cert": "Vanguard Trading LLP", "principal_place_state_code": "24"}, "confidences": {"gstin_on_cert": 0.99, "legal_name_on_cert": 0.98, "principal_place_state_code": 0.95}},
            "cancelled_cheque": {"detected": "cancelled_cheque", "fields": {"account_holder_name": "Vanguard Trading LLP", "ifsc_on_cheque": "ICIC0002456", "account_last4_on_cheque": "6607"}, "confidences": {"account_holder_name": 0.98, "ifsc_on_cheque": 0.99, "account_last4_on_cheque": 0.95}},
            "llpin_cert": {"detected": "llpin_cert", "fields": {"llpin_on_cert": "AAC-9012", "llp_name_on_cert": "Vanguard Trading LLP"}, "confidences": {"llpin_on_cert": 0.99, "llp_name_on_cert": 0.98}},
            "udyam_cert": {"detected": "udyam_cert", "fields": {"udyam_number_on_cert": "UDYAM-GJ-00-0019283", "udyam_category": "small", "udyam_activity_type": "trading"}, "confidences": {"udyam_number_on_cert": 0.99, "udyam_category": 0.98, "udyam_activity_type": 0.98}},
        },
    ),
    EvalRecord(
        id="CLN08",
        split="holdout",
        name="Precision Micro Tools",
        category="legitimate_clean",
        notes="Micro manufacturer without written agreement: capped at 15 days default. Approved.",
        expected_outcome="approved",
        expected_failing_checks=[],
        is_legitimate=True,
        is_adversarial=False,
        submission={
            "legal_name": "Precision Micro Tools",
            "entity_type": "proprietorship",
            "pan": PAN_CLN08,
            "gstin": make_gstin("27", PAN_CLN08),
            "ifsc": "HDFC0001234",
            "bank_account_number": "223344556608",
            "udyam_number": "UDYAM-MH-01-0028374",
            "udyam_category": "micro",
            "udyam_activity_type": "manufacturing",
            "address_state_code": "27",
            "email": "vendor@precisionmicro.example.com",
            "agreed_payment_days": None,
        },
        docs={
            "pan_card": {"detected": "pan_card", "fields": {"pan_number": PAN_CLN08, "name_on_pan": "Precision Micro Tools"}, "confidences": {"pan_number": 0.99, "name_on_pan": 0.98}},
            "gst_certificate": {"detected": "gst_certificate", "fields": {"gstin_on_cert": make_gstin("27", PAN_CLN08), "legal_name_on_cert": "Precision Micro Tools", "principal_place_state_code": "27"}, "confidences": {"gstin_on_cert": 0.99, "legal_name_on_cert": 0.98, "principal_place_state_code": 0.95}},
            "cancelled_cheque": {"detected": "cancelled_cheque", "fields": {"account_holder_name": "Precision Micro Tools", "ifsc_on_cheque": "HDFC0001234", "account_last4_on_cheque": "6608"}, "confidences": {"account_holder_name": 0.98, "ifsc_on_cheque": 0.99, "account_last4_on_cheque": 0.95}},
            "address_proof": {"detected": "address_proof", "fields": {"address_text": "MIDC Bhosari, Pune 411026"}, "confidences": {"address_text": 0.95}},
            "udyam_cert": {"detected": "udyam_cert", "fields": {"udyam_number_on_cert": "UDYAM-MH-01-0028374", "udyam_category": "micro", "udyam_activity_type": "manufacturing"}, "confidences": {"udyam_number_on_cert": 0.99, "udyam_category": 0.98, "udyam_activity_type": 0.98}},
        },
    ),
    EvalRecord(
        id="CLN09",
        split="tune",
        name="Zenith Components Private Limited",
        category="legitimate_clean",
        notes="Small manufacturing enterprise with 30-day written agreement. Capped at 30 days. Approved.",
        expected_outcome="approved",
        expected_failing_checks=[],
        is_legitimate=True,
        is_adversarial=False,
        submission={
            "legal_name": "Zenith Components Private Limited",
            "entity_type": "pvt_ltd",
            "pan": PAN_CLN09,
            "gstin": make_gstin("27", PAN_CLN09),
            "cin": "U29200MH2012PTC231234",
            "ifsc": "SBIN0000300",
            "bank_account_number": "223344556609",
            "udyam_number": "UDYAM-MH-02-0039485",
            "udyam_category": "small",
            "udyam_activity_type": "manufacturing",
            "address_state_code": "27",
            "email": "vendor@zenithcomp.example.com",
            "agreed_payment_days": 30,
        },
        docs={
            "pan_card": {"detected": "pan_card", "fields": {"pan_number": PAN_CLN09, "name_on_pan": "Zenith Components Private Limited"}, "confidences": {"pan_number": 0.99, "name_on_pan": 0.98}},
            "gst_certificate": {"detected": "gst_certificate", "fields": {"gstin_on_cert": make_gstin("27", PAN_CLN09), "legal_name_on_cert": "Zenith Components Private Limited", "principal_place_state_code": "27"}, "confidences": {"gstin_on_cert": 0.99, "legal_name_on_cert": 0.98, "principal_place_state_code": 0.95}},
            "cancelled_cheque": {"detected": "cancelled_cheque", "fields": {"account_holder_name": "Zenith Components Private Limited", "ifsc_on_cheque": "SBIN0000300", "account_last4_on_cheque": "6609"}, "confidences": {"account_holder_name": 0.98, "ifsc_on_cheque": 0.99, "account_last4_on_cheque": 0.95}},
            "coi": {"detected": "coi", "fields": {"cin_on_coi": "U29200MH2012PTC231234", "company_name_on_coi": "Zenith Components Private Limited", "incorporation_date": "2012-07-22"}, "confidences": {"cin_on_coi": 0.99, "company_name_on_coi": 0.98}},
            "udyam_cert": {"detected": "udyam_cert", "fields": {"udyam_number_on_cert": "UDYAM-MH-02-0039485", "udyam_category": "small", "udyam_activity_type": "manufacturing"}, "confidences": {"udyam_number_on_cert": 0.99, "udyam_category": 0.98, "udyam_activity_type": 0.98}},
        },
    ),

    # =========================================================================
    # 4. DEFECT & FAILURE CASES (18 records) — MUST NOT APPROVE
    # =========================================================================
    EvalRecord(
        id="DEF01",
        split="holdout",
        name="Bad PAN Format Enterprises",
        category="defect",
        notes="PAN format invalid (P1 check): 9 characters instead of 10. Rejected.",
        expected_outcome="rejected",
        expected_failing_checks=["pan_format"],
        is_legitimate=False,
        is_adversarial=False,
        submission={
            "legal_name": "Bad PAN Format Enterprises",
            "entity_type": "proprietorship",
            "pan": PAN_DEF01,  # Invalid format (9 chars)
            "gstin": "27AABP1234A1Z1",
            "ifsc": "HDFC0001234",
            "bank_account_number": "334455667701",
            "address_state_code": "27",
            "email": "def1@test.example.com",
        },
        docs={},
    ),
    EvalRecord(
        id="DEF02",
        split="tune",
        name="Wrong Entity PAN Private Limited",
        category="defect",
        notes="PAN 4th character mismatch (P2): Company requires 'C', but submitted PAN has 'P'. Rejected.",
        expected_outcome="rejected",
        expected_failing_checks=["pan_entity_type_match"],
        is_legitimate=False,
        is_adversarial=False,
        submission={
            "legal_name": "Wrong Entity PAN Private Limited",
            "entity_type": "pvt_ltd",
            "pan": PAN_DEF02,  # 'P' instead of 'C'
            "gstin": make_gstin("27", PAN_DEF02),
            "cin": "U72200MH2020PTC331234",
            "ifsc": "SBIN0000300",
            "bank_account_number": "334455667702",
            "address_state_code": "27",
            "email": "def2@test.example.com",
        },
        docs={},
    ),
    EvalRecord(
        id="DEF03",
        split="holdout",
        name="Missing ITD PAN Firm",
        category="defect",
        notes="PAN not found in ITD database (P3 check, mock status='missing'). Pending.",
        expected_outcome="pending",
        expected_failing_checks=["pan_status"],
        is_legitimate=False,
        is_adversarial=False,
        submission={
            "legal_name": "Missing ITD PAN Firm",
            "entity_type": "partnership",
            "pan": PAN_DEF03,  # Mock missing PAN in ITD
            "gstin": make_gstin("27", PAN_DEF03),
            "ifsc": "ICIC0002456",
            "bank_account_number": "334455667703",
            "address_state_code": "27",
            "email": "def3@test.example.com",
        },
        docs={
            "pan_card": {"detected": "pan_card", "fields": {"pan_number": PAN_DEF03, "name_on_pan": "Missing ITD PAN Firm"}, "confidences": {"pan_number": 0.99, "name_on_pan": 0.98}},
            "gst_certificate": {"detected": "gst_certificate", "fields": {"gstin_on_cert": make_gstin("27", PAN_DEF03), "legal_name_on_cert": "Missing ITD PAN Firm", "principal_place_state_code": "27"}, "confidences": {"gstin_on_cert": 0.99, "legal_name_on_cert": 0.98, "principal_place_state_code": 0.95}},
            "cancelled_cheque": {"detected": "cancelled_cheque", "fields": {"account_holder_name": "Missing ITD PAN Firm", "ifsc_on_cheque": "ICIC0002456", "account_last4_on_cheque": "7703"}, "confidences": {"account_holder_name": 0.98, "ifsc_on_cheque": 0.99, "account_last4_on_cheque": 0.95}},
            "address_proof": {"detected": "address_proof", "fields": {"address_text": "Fort, Mumbai 400001"}, "confidences": {"address_text": 0.95}},
        },
    ),
    EvalRecord(
        id="DEF04",
        split="tune",
        name="Bad GSTIN Format LLP",
        category="defect",
        notes="GSTIN format invalid (G1 check): contains lower-case / invalid char count. Rejected.",
        expected_outcome="rejected",
        expected_failing_checks=["gstin_format"],
        is_legitimate=False,
        is_adversarial=False,
        submission={
            "legal_name": "Bad GSTIN Format LLP",
            "entity_type": "llp",
            "pan": PAN_DEF04,
            "gstin": "27AAFCB1234C1Z",  # 14 chars
            "llpin": "AAD-1122",
            "ifsc": "HDFC0001234",
            "bank_account_number": "334455667704",
            "address_state_code": "27",
            "email": "def4@test.example.com",
        },
        docs={},
    ),
    EvalRecord(
        id="DEF05",
        split="holdout",
        name="GSTIN Mod36 Fail Private Limited",
        category="defect",
        notes="GSTIN mod-36 checksum mismatch (G2 check): check digit off-by-one. Rejected.",
        expected_outcome="rejected",
        expected_failing_checks=["gstin_checksum"],
        is_legitimate=False,
        is_adversarial=False,
        submission={
            "legal_name": "GSTIN Mod36 Fail Private Limited",
            "entity_type": "pvt_ltd",
            "pan": PAN_DEF05,
            "gstin": f"27{PAN_DEF05}1Z9",  # Deliberate invalid checksum
            "cin": "U72200MH2019PTC321234",
            "ifsc": "SBIN0000300",
            "bank_account_number": "334455667705",
            "address_state_code": "27",
            "email": "def5@test.example.com",
        },
        docs={},
    ),
    EvalRecord(
        id="DEF06",
        split="tune",
        name="GSTIN Embedded PAN Mismatch Private Limited",
        category="defect",
        notes="GSTIN chars 3-12 do not match submitted PAN (G3 check). Rejected.",
        expected_outcome="rejected",
        expected_failing_checks=["gstin_embedded_pan_match"],
        is_legitimate=False,
        is_adversarial=False,
        submission={
            "legal_name": "GSTIN Embedded PAN Mismatch Private Limited",
            "entity_type": "pvt_ltd",
            "pan": PAN_DEF06,
            "gstin": make_gstin("27", "AABCD3456E"),  # Embedded PAN AABCD3456E != PAN_DEF06
            "cin": "U72200MH2018PTC311234",
            "ifsc": "ICIC0002456",
            "bank_account_number": "334455667706",
            "address_state_code": "27",
            "email": "def6@test.example.com",
        },
        docs={},
    ),
    EvalRecord(
        id="DEF07",
        split="holdout",
        name="GSTIN State Code Mismatch Private Limited",
        category="defect",
        notes="GSTIN starts with 27 (MH), but principal place on cert is Gujarat (24). Fixable -> Pending.",
        expected_outcome="pending",
        expected_failing_checks=["gstin_state_code_match"],
        is_legitimate=False,
        is_adversarial=False,
        submission={
            "legal_name": "GSTIN State Code Mismatch Private Limited",
            "entity_type": "pvt_ltd",
            "pan": PAN_DEF07,
            "gstin": make_gstin("27", PAN_DEF07),
            "cin": "U72200MH2017PTC301234",
            "ifsc": "HDFC0001234",
            "bank_account_number": "334455667707",
            "address_state_code": "27",
            "email": "def7@test.example.com",
        },
        docs={
            "pan_card": {"detected": "pan_card", "fields": {"pan_number": PAN_DEF07, "name_on_pan": "GSTIN State Code Mismatch Private Limited"}, "confidences": {"pan_number": 0.99, "name_on_pan": 0.98}},
            "gst_certificate": {
                "detected": "gst_certificate",
                "fields": {"gstin_on_cert": make_gstin("27", PAN_DEF07), "legal_name_on_cert": "GSTIN State Code Mismatch Private Limited", "principal_place_state_code": "24"},  # 24 != 27
                "confidences": {"gstin_on_cert": 0.99, "legal_name_on_cert": 0.98, "principal_place_state_code": 0.95},
            },
            "cancelled_cheque": {"detected": "cancelled_cheque", "fields": {"account_holder_name": "GSTIN State Code Mismatch Private Limited", "ifsc_on_cheque": "HDFC0001234", "account_last4_on_cheque": "7707"}, "confidences": {"account_holder_name": 0.98, "ifsc_on_cheque": 0.99, "account_last4_on_cheque": 0.95}},
            "coi": {"detected": "coi", "fields": {"cin_on_coi": "U72200MH2017PTC301234", "company_name_on_coi": "GSTIN State Code Mismatch Private Limited", "incorporation_date": "2017-05-12"}, "confidences": {"cin_on_coi": 0.99, "company_name_on_coi": 0.98}},
        },
    ),
    EvalRecord(
        id="DEF08",
        split="tune",
        name="Bad CIN Format Private Limited",
        category="defect",
        notes="CIN format invalid (C1 check): does not conform to 21-character structure. Rejected.",
        expected_outcome="rejected",
        expected_failing_checks=["cin_format"],
        is_legitimate=False,
        is_adversarial=False,
        submission={
            "legal_name": "Bad CIN Format Private Limited",
            "entity_type": "pvt_ltd",
            "pan": PAN_DEF08,
            "gstin": make_gstin("27", PAN_DEF08),
            "cin": "INVALID-CIN-FORMAT",
            "ifsc": "SBIN0000300",
            "bank_account_number": "334455667708",
            "address_state_code": "27",
            "email": "def8@test.example.com",
        },
        docs={},
    ),
    EvalRecord(
        id="DEF09",
        split="holdout",
        name="CIN Year Mismatch Private Limited",
        category="defect",
        notes="CIN year (2018) does not match incorporation date year (2020) on COI. Hard fail -> Rejected.",
        expected_outcome="rejected",
        expected_failing_checks=["cin_year_match"],
        is_legitimate=False,
        is_adversarial=False,
        submission={
            "legal_name": "CIN Year Mismatch Private Limited",
            "entity_type": "pvt_ltd",
            "pan": PAN_DEF09,
            "gstin": make_gstin("27", PAN_DEF09),
            "cin": "U72200MH2018PTC291234",  # 2018 in CIN
            "ifsc": "ICIC0002456",
            "bank_account_number": "334455667709",
            "address_state_code": "27",
            "email": "def9@test.example.com",
        },
        docs={
            "pan_card": {"detected": "pan_card", "fields": {"pan_number": PAN_DEF09, "name_on_pan": "CIN Year Mismatch Private Limited"}, "confidences": {"pan_number": 0.99, "name_on_pan": 0.98}},
            "gst_certificate": {"detected": "gst_certificate", "fields": {"gstin_on_cert": make_gstin("27", PAN_DEF09), "legal_name_on_cert": "CIN Year Mismatch Private Limited", "principal_place_state_code": "27"}, "confidences": {"gstin_on_cert": 0.99, "legal_name_on_cert": 0.98, "principal_place_state_code": 0.95}},
            "cancelled_cheque": {"detected": "cancelled_cheque", "fields": {"account_holder_name": "CIN Year Mismatch Private Limited", "ifsc_on_cheque": "ICIC0002456", "account_last4_on_cheque": "7709"}, "confidences": {"account_holder_name": 0.98, "ifsc_on_cheque": 0.99, "account_last4_on_cheque": 0.95}},
            "coi": {
                "detected": "coi",
                "fields": {"cin_on_coi": "U72200MH2018PTC291234", "company_name_on_coi": "CIN Year Mismatch Private Limited", "incorporation_date": "2020-05-10"},  # 2020 != 2018
                "confidences": {"cin_on_coi": 0.99, "company_name_on_coi": 0.98, "incorporation_date": 0.95},
            },
        },
    ),
    EvalRecord(
        id="DEF10",
        split="tune",
        name="Bad LLPIN Format LLP",
        category="defect",
        notes="LLPIN format invalid (L1 check): does not match [A-Z]{3}-\d{4}. Rejected.",
        expected_outcome="rejected",
        expected_failing_checks=["llpin_format"],
        is_legitimate=False,
        is_adversarial=False,
        submission={
            "legal_name": "Bad LLPIN Format LLP",
            "entity_type": "llp",
            "pan": PAN_DEF10,
            "gstin": make_gstin("27", PAN_DEF10),
            "llpin": "12345",  # Invalid
            "ifsc": "HDFC0001234",
            "bank_account_number": "334455667710",
            "address_state_code": "27",
            "email": "def10@test.example.com",
        },
        docs={},
    ),
    EvalRecord(
        id="DEF11",
        split="holdout",
        name="Bad IFSC Format Firm",
        category="defect",
        notes="IFSC format invalid (B2 check): 5th char not '0' or bad length. Rejected.",
        expected_outcome="rejected",
        expected_failing_checks=["ifsc_format"],
        is_legitimate=False,
        is_adversarial=False,
        submission={
            "legal_name": "Bad IFSC Format Firm",
            "entity_type": "partnership",
            "pan": PAN_DEF11,
            "gstin": make_gstin("27", PAN_DEF11),
            "ifsc": "HDFC1001234",  # 5th char is '1' not '0'
            "bank_account_number": "334455667711",
            "address_state_code": "27",
            "email": "def11@test.example.com",
        },
        docs={},
    ),
    EvalRecord(
        id="DEF12",
        split="tune",
        name="IFSC Not Found Private Limited",
        category="defect",
        notes="IFSC not found in RBI list (mock returns not_found). Fixable -> Pending.",
        expected_outcome="pending",
        expected_failing_checks=["ifsc_lookup"],
        is_legitimate=False,
        is_adversarial=False,
        submission={
            "legal_name": "IFSC Not Found Private Limited",
            "entity_type": "pvt_ltd",
            "pan": PAN_DEF12,
            "gstin": make_gstin("27", PAN_DEF12),
            "cin": "U72200MH2019PTC311234",
            "ifsc": "XXXX0000000",  # Mock missing
            "bank_account_number": "334455667712",
            "address_state_code": "27",
            "email": "def12@test.example.com",
        },
        docs={
            "pan_card": {"detected": "pan_card", "fields": {"pan_number": PAN_DEF12, "name_on_pan": "IFSC Not Found Private Limited"}, "confidences": {"pan_number": 0.99, "name_on_pan": 0.98}},
            "gst_certificate": {"detected": "gst_certificate", "fields": {"gstin_on_cert": make_gstin("27", PAN_DEF12), "legal_name_on_cert": "IFSC Not Found Private Limited", "principal_place_state_code": "27"}, "confidences": {"gstin_on_cert": 0.99, "legal_name_on_cert": 0.98, "principal_place_state_code": 0.95}},
            "cancelled_cheque": {"detected": "cancelled_cheque", "fields": {"account_holder_name": "IFSC Not Found Private Limited", "ifsc_on_cheque": "XXXX0000000", "account_last4_on_cheque": "7712"}, "confidences": {"account_holder_name": 0.98, "ifsc_on_cheque": 0.99, "account_last4_on_cheque": 0.95}},
            "coi": {"detected": "coi", "fields": {"cin_on_coi": "U72200MH2019PTC311234", "company_name_on_coi": "IFSC Not Found Private Limited", "incorporation_date": "2019-01-10"}, "confidences": {"cin_on_coi": 0.99, "company_name_on_coi": 0.98}},
        },
    ),
    EvalRecord(
        id="DEF13",
        split="holdout",
        name="Shared Bank Account Collision Firm",
        category="defect",
        notes="Shared bank account number with existing approved vendor (DV2). Escalate -> Human Review.",
        expected_outcome="human_review",
        expected_failing_checks=["duplicate_bank_account"],
        is_legitimate=False,
        is_adversarial=False,
        submission={
            "legal_name": "Shared Bank Account Collision Firm",
            "entity_type": "partnership",
            "pan": PAN_DEF13,
            "gstin": make_gstin("27", PAN_DEF13),
            "ifsc": "SBIN0000300",
            "bank_account_number": "SHARED_ACC_EXISTING_APPROVED_HMAC",
            "address_state_code": "27",
            "email": "def13@test.example.com",
        },
        docs={
            "pan_card": {"detected": "pan_card", "fields": {"pan_number": PAN_DEF13, "name_on_pan": "Shared Bank Account Collision Firm"}, "confidences": {"pan_number": 0.99, "name_on_pan": 0.98}},
            "gst_certificate": {"detected": "gst_certificate", "fields": {"gstin_on_cert": make_gstin("27", PAN_DEF13), "legal_name_on_cert": "Shared Bank Account Collision Firm", "principal_place_state_code": "27"}, "confidences": {"gstin_on_cert": 0.99, "legal_name_on_cert": 0.98, "principal_place_state_code": 0.95}},
            "cancelled_cheque": {"detected": "cancelled_cheque", "fields": {"account_holder_name": "Shared Bank Account Collision Firm", "ifsc_on_cheque": "SBIN0000300", "account_last4_on_cheque": "9999"}, "confidences": {"account_holder_name": 0.98, "ifsc_on_cheque": 0.99, "account_last4_on_cheque": 0.95}},
            "address_proof": {"detected": "address_proof", "fields": {"address_text": "Andheri West, Mumbai 400053"}, "confidences": {"address_text": 0.95}},
        },
    ),
    EvalRecord(
        id="DEF14",
        split="tune",
        name="High Soft Risk Score Private Limited",
        category="defect",
        notes="Accumulated soft risk score >= 20.0 (near-miss bank name + state difference + payment term). Human Review.",
        expected_outcome="human_review",
        expected_failing_checks=["cin_state_match", "bank_name_fuzzy_match"],
        is_legitimate=False,
        is_adversarial=False,
        submission={
            "legal_name": "High Soft Risk Score Private Limited",
            "entity_type": "pvt_ltd",
            "pan": PAN_DEF14,
            "gstin": make_gstin("27", PAN_DEF14),
            "cin": "U72200MH2026PTC401234",  # Newly incorporated (2026)
            "ifsc": "HDFC0001234",
            "bank_account_number": "334455667714",
            "address_state_code": "29",        # Address in KA (29), CIN in MH (27) -> cin_state_match warn +10
            "email": "def14@test.example.com",
            "agreed_payment_days": 180,
        },
        docs={
            "pan_card": {"detected": "pan_card", "fields": {"pan_number": PAN_DEF14, "name_on_pan": "High Soft Risk Score Private Limited"}, "confidences": {"pan_number": 0.99, "name_on_pan": 0.98}},
            "gst_certificate": {"detected": "gst_certificate", "fields": {"gstin_on_cert": make_gstin("27", PAN_DEF14), "legal_name_on_cert": "High Soft Risk Score Private Limited", "principal_place_state_code": "27", "_pdf_producer": "Canva"}, "confidences": {"gstin_on_cert": 0.99, "legal_name_on_cert": 0.98, "principal_place_state_code": 0.95}},
            "cancelled_cheque": {"detected": "cancelled_cheque", "fields": {"account_holder_name": "High Soft Risk Services", "ifsc_on_cheque": "HDFC0001234", "account_last4_on_cheque": "7714"}, "confidences": {"account_holder_name": 0.98, "ifsc_on_cheque": 0.99, "account_last4_on_cheque": 0.95}},
            "coi": {"detected": "coi", "fields": {"cin_on_coi": "U72200MH2026PTC401234", "company_name_on_coi": "High Soft Risk Score Private Limited", "incorporation_date": "2026-01-10"}, "confidences": {"cin_on_coi": 0.99, "company_name_on_coi": 0.98}},
        },
    ),
    EvalRecord(
        id="DEF15",
        split="holdout",
        name="Missing Required PAN Card Private Limited",
        category="defect",
        notes="PAN card document slot is missing from upload. Fixable -> Pending.",
        expected_outcome="pending",
        expected_failing_checks=["required_docs_present"],
        is_legitimate=False,
        is_adversarial=False,
        submission={
            "legal_name": "Missing Required PAN Card Private Limited",
            "entity_type": "pvt_ltd",
            "pan": PAN_DEF15,
            "gstin": make_gstin("27", PAN_DEF15),
            "cin": "U72200MH2019PTC311234",
            "ifsc": "SBIN0000300",
            "bank_account_number": "334455667715",
            "address_state_code": "27",
            "email": "def15@test.example.com",
        },
        docs={
            # pan_card missing
            "gst_certificate": {"detected": "gst_certificate", "fields": {"gstin_on_cert": make_gstin("27", PAN_DEF15), "legal_name_on_cert": "Missing Required PAN Card Private Limited", "principal_place_state_code": "27"}, "confidences": {"gstin_on_cert": 0.99, "legal_name_on_cert": 0.98, "principal_place_state_code": 0.95}},
            "cancelled_cheque": {"detected": "cancelled_cheque", "fields": {"account_holder_name": "Missing Required PAN Card Private Limited", "ifsc_on_cheque": "SBIN0000300", "account_last4_on_cheque": "7715"}, "confidences": {"account_holder_name": 0.98, "ifsc_on_cheque": 0.99, "account_last4_on_cheque": 0.95}},
            "coi": {"detected": "coi", "fields": {"cin_on_coi": "U72200MH2019PTC311234", "company_name_on_coi": "Missing Required PAN Card Private Limited", "incorporation_date": "2019-03-15"}, "confidences": {"cin_on_coi": 0.99, "company_name_on_coi": 0.98}},
        },
    ),
    EvalRecord(
        id="DEF16",
        split="tune",
        name="Missing COI Document Private Limited",
        category="defect",
        notes="Certificate of Incorporation is missing for Private Limited company. Fixable -> Pending.",
        expected_outcome="pending",
        expected_failing_checks=["required_docs_present"],
        is_legitimate=False,
        is_adversarial=False,
        submission={
            "legal_name": "Missing COI Document Private Limited",
            "entity_type": "pvt_ltd",
            "pan": PAN_DEF16,
            "gstin": make_gstin("27", PAN_DEF16),
            "cin": "U72200MH2018PTC301234",
            "ifsc": "ICIC0002456",
            "bank_account_number": "334455667716",
            "address_state_code": "27",
            "email": "def16@test.example.com",
        },
        docs={
            "pan_card": {"detected": "pan_card", "fields": {"pan_number": PAN_DEF16, "name_on_pan": "Missing COI Document Private Limited"}, "confidences": {"pan_number": 0.99, "name_on_pan": 0.98}},
            "gst_certificate": {"detected": "gst_certificate", "fields": {"gstin_on_cert": make_gstin("27", PAN_DEF16), "legal_name_on_cert": "Missing COI Document Private Limited", "principal_place_state_code": "27"}, "confidences": {"gstin_on_cert": 0.99, "legal_name_on_cert": 0.98, "principal_place_state_code": 0.95}},
            "cancelled_cheque": {"detected": "cancelled_cheque", "fields": {"account_holder_name": "Missing COI Document Private Limited", "ifsc_on_cheque": "ICIC0002456", "account_last4_on_cheque": "7716"}, "confidences": {"account_holder_name": 0.98, "ifsc_on_cheque": 0.99, "account_last4_on_cheque": 0.95}},
            # coi missing
        },
    ),
    EvalRecord(
        id="DEF17",
        split="holdout",
        name="Duplicate PAN Collision DV1 Firm",
        category="defect",
        notes="PAN collision with different vendor name (DV1). Escalate -> Human Review.",
        expected_outcome="human_review",
        expected_failing_checks=["pan_status"],
        is_legitimate=False,
        is_adversarial=False,
        submission={
            "legal_name": "Duplicate PAN Collision DV1 Firm",
            "entity_type": "partnership",
            "pan": PAN_DEF17,
            "gstin": make_gstin("27", PAN_DEF17),
            "ifsc": "HDFC0001234",
            "bank_account_number": "334455667717",
            "address_state_code": "27",
            "email": "def17@test.example.com",
        },
        docs={
            "pan_card": {"detected": "pan_card", "fields": {"pan_number": PAN_DEF17, "name_on_pan": "Duplicate PAN Collision DV1 Firm"}, "confidences": {"pan_number": 0.99, "name_on_pan": 0.98}},
            "gst_certificate": {"detected": "gst_certificate", "fields": {"gstin_on_cert": make_gstin("27", PAN_DEF17), "legal_name_on_cert": "Duplicate PAN Collision DV1 Firm", "principal_place_state_code": "27"}, "confidences": {"gstin_on_cert": 0.99, "legal_name_on_cert": 0.98, "principal_place_state_code": 0.95}},
            "cancelled_cheque": {"detected": "cancelled_cheque", "fields": {"account_holder_name": "Duplicate PAN Collision DV1 Firm", "ifsc_on_cheque": "HDFC0001234", "account_last4_on_cheque": "7717"}, "confidences": {"account_holder_name": 0.98, "ifsc_on_cheque": 0.99, "account_last4_on_cheque": 0.95}},
            "address_proof": {"detected": "address_proof", "fields": {"address_text": "Nariman Point, Mumbai 400021"}, "confidences": {"address_text": 0.95}},
        },
    ),
    EvalRecord(
        id="DEF18",
        split="tune",
        name="Udyam Activity Unreadable Private Limited",
        category="defect",
        notes="Udyam activity type cannot be parsed from blurry certificate. Fixable -> Pending.",
        expected_outcome="pending",
        expected_failing_checks=["udyam_details_readable"],
        is_legitimate=False,
        is_adversarial=False,
        submission={
            "legal_name": "Udyam Activity Unreadable Private Limited",
            "entity_type": "pvt_ltd",
            "pan": PAN_DEF18,
            "gstin": make_gstin("27", PAN_DEF18),
            "cin": "U72200MH2019PTC311234",
            "ifsc": "SBIN0000300",
            "bank_account_number": "334455667718",
            "udyam_number": "UDYAM-MH-03-0049586",
            "udyam_category": "micro",
            "udyam_activity_type": "",  # Missing
            "address_state_code": "27",
            "email": "def18@test.example.com",
        },
        docs={
            "pan_card": {"detected": "pan_card", "fields": {"pan_number": PAN_DEF18, "name_on_pan": "Udyam Activity Unreadable Private Limited"}, "confidences": {"pan_number": 0.99, "name_on_pan": 0.98}},
            "gst_certificate": {"detected": "gst_certificate", "fields": {"gstin_on_cert": make_gstin("27", PAN_DEF18), "legal_name_on_cert": "Udyam Activity Unreadable Private Limited", "principal_place_state_code": "27"}, "confidences": {"gstin_on_cert": 0.99, "legal_name_on_cert": 0.98, "principal_place_state_code": 0.95}},
            "cancelled_cheque": {"detected": "cancelled_cheque", "fields": {"account_holder_name": "Udyam Activity Unreadable Private Limited", "ifsc_on_cheque": "SBIN0000300", "account_last4_on_cheque": "7718"}, "confidences": {"account_holder_name": 0.98, "ifsc_on_cheque": 0.99, "account_last4_on_cheque": 0.95}},
            "coi": {"detected": "coi", "fields": {"cin_on_coi": "U72200MH2019PTC311234", "company_name_on_coi": "Udyam Activity Unreadable Private Limited", "incorporation_date": "2019-06-20"}, "confidences": {"cin_on_coi": 0.99, "company_name_on_coi": 0.98}},
            "udyam_cert": {"detected": "udyam_cert", "fields": {"udyam_number_on_cert": "UDYAM-MH-03-0049586", "udyam_category": "micro"}, "confidences": {"udyam_number_on_cert": 0.99, "udyam_category": 0.98}},  # activity missing
        },
    ),
]


def get_eval_dataset() -> List[EvalRecord]:
    return EVAL_RECORDS
