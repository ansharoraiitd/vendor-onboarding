"""
scripts/generate_synthetic_vendors.py
──────────────────────────────────────
Generates two eval fixture files:
  tests/fixtures/eval_set_rules.yaml  — 30 rules-only records (no PDFs)
  tests/fixtures/eval_set_e2e.yaml    —  8 end-to-end records (placeholder for PDF paths)

Each record has:
  vendor: dict of submission fields
  expected_outcome: approved | pending | rejected | human_review
  expected_triggered_checks: list of check names that should fire
  notes: free-text rationale
  is_legit_near_miss: bool  (legitimate vendor that should be APPROVED despite soft signals)

Run:
  python scripts/generate_synthetic_vendors.py

The GSTIN checksums are pre-computed using the forward (left-to-right, factor 2→1) algorithm.
"""

from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import hashlib, hmac, json
from app.validators.gstin import _compute_gstin_checksum

# ── Helpers ────────────────────────────────────────────────────────────────────

def make_gstin(state: str, pan: str, reg_no: str = "1") -> str:
    """Build a syntactically valid GSTIN with correct checksum."""
    base14 = f"{state}{pan}{reg_no}Z"
    assert len(base14) == 14, f"base14 must be 14 chars, got {len(base14)}: {base14!r}"
    return base14 + _compute_gstin_checksum(base14)

def make_cin(listing: str, activity_code: str, state: str, year: str, type_code: str, seq: str) -> str:
    """Build a syntactically valid CIN. e.g. U67190MH2010PTC201234"""
    return f"{listing}{activity_code}{state}{year}{type_code}{seq}"

# ── Shared PANs & GSTINs ───────────────────────────────────────────────────────

ACME_PAN     = "AABCA1234A"   # pvt_ltd (char 4 = C)
ACME_GSTIN   = make_gstin("27", ACME_PAN)   # Maharashtra

BHARAT_PAN   = "AABFB5678B"   # partnership (char 4 = F)
BHARAT_GSTIN = make_gstin("29", BHARAT_PAN) # Karnataka

SUNRISE_PAN  = "AAPCS9012C"   # pvt_ltd (char 4 = C)
SUNRISE_GSTIN= make_gstin("07", SUNRISE_PAN)# Delhi

KUBER_PAN    = "AAFCK3456D"   # llp (char 4 = F)
KUBER_GSTIN  = make_gstin("24", KUBER_PAN)  # Gujarat

PROP_PAN     = "AACPE7890E"   # proprietorship (char 4 = P)
PROP_GSTIN   = make_gstin("19", PROP_PAN)   # West Bengal

SECT8_PAN    = "AADCS1122F"   # section8 (char 4 = C)
SECT8_GSTIN  = make_gstin("33", SECT8_PAN)  # Tamil Nadu

PUBCO_PAN    = "AAECG4455G"   # pub_ltd (char 4 = C)
PUBCO_GSTIN  = make_gstin("36", PUBCO_PAN)  # Telangana

MSME_MFG_PAN   = "AAHCM7788H"
MSME_MFG_GSTIN = make_gstin("27", MSME_MFG_PAN)

MSME_SVC_PAN   = "AAJCS9900J"
MSME_SVC_GSTIN = make_gstin("29", MSME_SVC_PAN)

MSME_TRD_PAN   = "AAPCM2211K"
MSME_TRD_GSTIN = make_gstin("07", MSME_TRD_PAN)


# ── 30 Rules-only Records ──────────────────────────────────────────────────────

RULES_RECORDS = [

    # ── Clean approvals (5) ───────────────────────────────────────────────────
    {
        "id": "R01",
        "notes": "Perfect pvt_ltd submission — all checks pass",
        "expected_outcome": "approved",
        "expected_triggered_checks": [],
        "is_legit_near_miss": False,
        "vendor": {
            "legal_name": "Acme Technologies Private Limited",
            "entity_type": "pvt_ltd",
            "pan": ACME_PAN,
            "gstin": ACME_GSTIN,
            "cin": make_cin("U", "67190", "MH", "2010", "PTC", "201234"),
            "ifsc": "HDFC0001234",
            "address_state_code": "27",
            "udyam_number": None,
        },
    },
    {
        "id": "R02",
        "notes": "Partnership firm — no CIN needed",
        "expected_outcome": "approved",
        "expected_triggered_checks": [],
        "is_legit_near_miss": False,
        "vendor": {
            "legal_name": "Bharat Traders",
            "entity_type": "partnership",
            "pan": BHARAT_PAN,
            "gstin": BHARAT_GSTIN,
            "cin": None,
            "ifsc": "SBIN0005678",
            "address_state_code": "29",
            "udyam_number": None,
        },
    },
    {
        "id": "R03",
        "notes": "LLP with valid LLPIN",
        "expected_outcome": "approved",
        "expected_triggered_checks": [],
        "is_legit_near_miss": False,
        "vendor": {
            "legal_name": "Kuber Solutions LLP",
            "entity_type": "llp",
            "pan": KUBER_PAN,
            "gstin": KUBER_GSTIN,
            "llpin": "AAA-1234",
            "cin": None,
            "ifsc": "ICIC0003456",
            "address_state_code": "24",
            "udyam_number": None,
        },
    },
    {
        "id": "R04",
        "notes": "Sole proprietor — no CIN/LLPIN",
        "expected_outcome": "approved",
        "expected_triggered_checks": [],
        "is_legit_near_miss": False,
        "vendor": {
            "legal_name": "Ramesh Kumar Enterprises",
            "entity_type": "proprietorship",
            "pan": PROP_PAN,
            "gstin": PROP_GSTIN,
            "cin": None,
            "ifsc": "PUNB0007890",
            "address_state_code": "19",
            "udyam_number": None,
        },
    },
    {
        "id": "R05",
        "notes": "Micro MSME manufacturer — approved with payment cap flag",
        "expected_outcome": "approved",
        "expected_triggered_checks": ["payment_term_cap"],
        "is_legit_near_miss": False,
        "vendor": {
            "legal_name": "Sunrise Manufacturing Pvt Ltd",
            "entity_type": "pvt_ltd",
            "pan": MSME_MFG_PAN,
            "gstin": MSME_MFG_GSTIN,
            "cin": make_cin("U", "27300", "MH", "2015", "PTC", "305678"),
            "ifsc": "AXIS0001111",
            "address_state_code": "27",
            "udyam_number": "UDYAM-MH-00-0001234",
            "udyam_category": "micro",
            "udyam_activity_type": "manufacturing",
        },
    },

    # ── Hard-fail rejections (10) ─────────────────────────────────────────────
    {
        "id": "R06",
        "notes": "PAN format invalid (bad 4th char for pvt_ltd → 'X' not in allowed set)",
        "expected_outcome": "rejected",
        "expected_triggered_checks": ["pan_format"],
        "is_legit_near_miss": False,
        "vendor": {
            "legal_name": "Bad Pan Co",
            "entity_type": "pvt_ltd",
            "pan": "AABXA1234A",   # X is not in [ABCFGHLJPTK]
            "gstin": "27AABXA1234A1ZA",
            "cin": make_cin("U", "67190", "MH", "2010", "PTC", "999001"),
            "ifsc": "HDFC0001234",
            "address_state_code": "27",
        },
    },
    {
        "id": "R07",
        "notes": "GSTIN checksum off-by-one (last char wrong)",
        "expected_outcome": "rejected",
        "expected_triggered_checks": ["gstin_checksum"],
        "is_legit_near_miss": False,
        "vendor": {
            "legal_name": "Checksum Fail Corp",
            "entity_type": "pvt_ltd",
            "pan": ACME_PAN,
            "gstin": ACME_GSTIN[:-1] + ("A" if ACME_GSTIN[-1] != "A" else "B"),  # corrupt last char
            "cin": make_cin("U", "67190", "MH", "2010", "PTC", "999002"),
            "ifsc": "HDFC0001234",
            "address_state_code": "27",
        },
    },
    {
        "id": "R08",
        "notes": "GSTIN embedded PAN does not match submitted PAN",
        "expected_outcome": "rejected",
        "expected_triggered_checks": ["gstin_embedded_pan_match"],
        "is_legit_near_miss": False,
        "vendor": {
            "legal_name": "Pan Mismatch Ltd",
            "entity_type": "pvt_ltd",
            "pan": ACME_PAN,
            "gstin": make_gstin("27", SUNRISE_PAN),  # GSTIN built on a different PAN
            "cin": make_cin("U", "67190", "MH", "2010", "PTC", "999003"),
            "ifsc": "HDFC0001234",
            "address_state_code": "27",
        },
    },
    {
        "id": "R09",
        "notes": "PAN entity-type mismatch: pvt_ltd but PAN 4th char = F (partnership)",
        "expected_outcome": "rejected",
        "expected_triggered_checks": ["pan_entity_type_match"],
        "is_legit_near_miss": False,
        "vendor": {
            "legal_name": "Wrong Type Ltd",
            "entity_type": "pvt_ltd",
            "pan": BHARAT_PAN,  # 4th char = F, should be C for pvt_ltd
            "gstin": make_gstin("29", BHARAT_PAN),
            "cin": make_cin("U", "67190", "KA", "2010", "PTC", "999004"),
            "ifsc": "SBIN0005678",
            "address_state_code": "29",
        },
    },
    {
        "id": "R10",
        "notes": "CIN entity type code (NPL) doesn't match pvt_ltd claim",
        "expected_outcome": "rejected",
        "expected_triggered_checks": ["cin_entity_type_match"],
        "is_legit_near_miss": False,
        "vendor": {
            "legal_name": "Fake Pvt NPL Ltd",
            "entity_type": "pvt_ltd",
            "pan": ACME_PAN,
            "gstin": ACME_GSTIN,
            "cin": make_cin("U", "67190", "MH", "2010", "NPL", "999005"),  # NPL = section8, not pvt_ltd
            "ifsc": "HDFC0001234",
            "address_state_code": "27",
        },
    },
    {
        "id": "R11",
        "notes": "CIN year mismatch (CIN says 1990, COI says 2015)",
        "expected_outcome": "rejected",
        "expected_triggered_checks": ["cin_year_match"],
        "is_legit_near_miss": False,
        "vendor": {
            "legal_name": "Year Mismatch Pvt Ltd",
            "entity_type": "pvt_ltd",
            "pan": ACME_PAN,
            "gstin": ACME_GSTIN,
            "cin": make_cin("U", "67190", "MH", "1990", "PTC", "999006"),
            "cin_year_on_coi": 2015,   # simulated extraction
            "extraction_confidence_cin_year": 0.95,
            "ifsc": "HDFC0001234",
            "address_state_code": "27",
        },
    },
    {
        "id": "R12",
        "notes": "IFSC format invalid (5th char is not 0)",
        "expected_outcome": "rejected",
        "expected_triggered_checks": ["ifsc_format"],
        "is_legit_near_miss": False,
        "vendor": {
            "legal_name": "Bad IFSC Co",
            "entity_type": "partnership",
            "pan": BHARAT_PAN,
            "gstin": BHARAT_GSTIN,
            "cin": None,
            "ifsc": "HDFC1001234",   # 5th char = 1, should be 0
            "address_state_code": "29",
        },
    },
    {
        "id": "R13",
        "notes": "GSTIN 13th char is 0 — invalid format (must be [1-9A-Z])",
        "expected_outcome": "rejected",
        "expected_triggered_checks": ["gstin_format"],
        "is_legit_near_miss": False,
        "vendor": {
            "legal_name": "Zero Reg Co",
            "entity_type": "pvt_ltd",
            "pan": ACME_PAN,
            "gstin": "27" + ACME_PAN + "0ZA",  # 0 at position 13
            "cin": make_cin("U", "67190", "MH", "2010", "PTC", "999007"),
            "ifsc": "HDFC0001234",
            "address_state_code": "27",
        },
    },
    {
        "id": "R14",
        "notes": "LLPIN format invalid (wrong separator)",
        "expected_outcome": "pending",  # llpin is fixable
        "expected_triggered_checks": ["llpin_format"],
        "is_legit_near_miss": False,
        "vendor": {
            "legal_name": "Bad LLPIN Solutions LLP",
            "entity_type": "llp",
            "pan": KUBER_PAN,
            "gstin": KUBER_GSTIN,
            "llpin": "AAA1234",   # missing hyphen
            "cin": None,
            "ifsc": "ICIC0003456",
            "address_state_code": "24",
        },
    },
    {
        "id": "R15",
        "notes": "PAN status = invalid from adapter",
        "expected_outcome": "rejected",
        "expected_triggered_checks": ["pan_status"],
        "is_legit_near_miss": False,
        "vendor": {
            "legal_name": "Invalid PAN Enterprises",
            "entity_type": "partnership",
            "pan": BHARAT_PAN,
            "pan_status_adapter_response": "invalid",
            "gstin": BHARAT_GSTIN,
            "cin": None,
            "ifsc": "SBIN0005678",
            "address_state_code": "29",
        },
    },

    # ── Pending (fixable) (5) ─────────────────────────────────────────────────
    {
        "id": "R16",
        "notes": "Missing required document: COI not uploaded for pvt_ltd",
        "expected_outcome": "pending",
        "expected_triggered_checks": ["required_docs_present"],
        "is_legit_near_miss": False,
        "vendor": {
            "legal_name": "Missing Doc Pvt Ltd",
            "entity_type": "pvt_ltd",
            "pan": ACME_PAN,
            "gstin": ACME_GSTIN,
            "cin": make_cin("U", "67190", "MH", "2010", "PTC", "999008"),
            "ifsc": "HDFC0001234",
            "address_state_code": "27",
            "uploaded_docs": ["pan_card", "gst_certificate", "cancelled_cheque"],  # missing coi
        },
    },
    {
        "id": "R17",
        "notes": "PAN status = missing from adapter",
        "expected_outcome": "pending",
        "expected_triggered_checks": ["pan_status", "tds_higher_rate_flag"],
        "is_legit_near_miss": False,
        "vendor": {
            "legal_name": "Missing PAN Ltd",
            "entity_type": "pvt_ltd",
            "pan": ACME_PAN,
            "pan_status_adapter_response": "missing",
            "gstin": ACME_GSTIN,
            "cin": make_cin("U", "67190", "MH", "2010", "PTC", "999009"),
            "ifsc": "HDFC0001234",
            "address_state_code": "27",
        },
    },
    {
        "id": "R18",
        "notes": "Udyam number supplied but format invalid",
        "expected_outcome": "pending",
        "expected_triggered_checks": ["udyam_format"],
        "is_legit_near_miss": False,
        "vendor": {
            "legal_name": "Udyam Error Mfg Co",
            "entity_type": "pvt_ltd",
            "pan": MSME_MFG_PAN,
            "gstin": MSME_MFG_GSTIN,
            "cin": make_cin("U", "27300", "MH", "2015", "PTC", "999010"),
            "ifsc": "AXIS0001111",
            "address_state_code": "27",
            "udyam_number": "UDYAM-MH-0012345",  # missing district segment
        },
    },
    {
        "id": "R19",
        "notes": "GSTIN state code doesn't match GST cert principal-place state (fixable by design)",
        "expected_outcome": "pending",
        "expected_triggered_checks": ["gstin_state_code_match"],
        "is_legit_near_miss": False,
        "vendor": {
            "legal_name": "State Mismatch Ltd",
            "entity_type": "pvt_ltd",
            "pan": ACME_PAN,
            "gstin": ACME_GSTIN,   # state code 27 (MH)
            "gst_cert_state_code_extracted": "29",   # GST cert says Karnataka
            "extraction_confidence_state": 0.92,
            "cin": make_cin("U", "67190", "MH", "2010", "PTC", "999011"),
            "ifsc": "HDFC0001234",
            "address_state_code": "27",
        },
    },
    {
        "id": "R20",
        "notes": "Low extraction confidence on GST cert state → hard check downgraded to fixable",
        "expected_outcome": "pending",
        "expected_triggered_checks": ["gstin_state_code_match"],
        "is_legit_near_miss": True,  # legit vendor; low-quality scan caused confidence dip
        "vendor": {
            "legal_name": "Legit But Blurry Cert Ltd",
            "entity_type": "pvt_ltd",
            "pan": ACME_PAN,
            "gstin": ACME_GSTIN,
            "gst_cert_state_code_extracted": "29",
            "extraction_confidence_state": 0.60,   # below min_confidence → downgraded
            "cin": make_cin("U", "67190", "MH", "2010", "PTC", "999012"),
            "ifsc": "HDFC0001234",
            "address_state_code": "27",
        },
    },

    # ── Human review (5) ─────────────────────────────────────────────────────
    {
        "id": "R21",
        "notes": "DV2: same bank account HMAC as existing approved vendor",
        "expected_outcome": "human_review",
        "expected_triggered_checks": ["duplicate_bank_account"],
        "is_legit_near_miss": True,  # could be a genuine shared account (family business)
        "vendor": {
            "legal_name": "Ravi Kumar Trading",
            "entity_type": "proprietorship",
            "pan": PROP_PAN,
            "gstin": PROP_GSTIN,
            "cin": None,
            "ifsc": "PUNB0007890",
            "address_state_code": "19",
            "bank_account_hmac_collision": True,  # trigger flag for eval harness
        },
    },
    {
        "id": "R22",
        "notes": "Soft score >= 20: PDF editing tool (5) + bank name warn (10) + CIN state soft (5)",
        "expected_outcome": "human_review",
        "expected_triggered_checks": ["pdf_editing_tool", "bank_name_fuzzy_match", "cin_state_match"],
        "is_legit_near_miss": True,  # legitimate vendor with imperfect docs
        "vendor": {
            "legal_name": "Genuine Corp Pvt Ltd",
            "entity_type": "pvt_ltd",
            "pan": ACME_PAN,
            "gstin": ACME_GSTIN,
            "cin": make_cin("U", "67190", "MH", "2010", "PTC", "999013"),
            "ifsc": "HDFC0001234",
            "address_state_code": "27",
            "simulated_soft_score": 20,
        },
    },
    {
        "id": "R23",
        "notes": "DV3: near-identical name to existing approved vendor (soft +15 → human_review)",
        "expected_outcome": "human_review",
        "expected_triggered_checks": ["duplicate_name_fuzzy"],
        "is_legit_near_miss": False,
        "vendor": {
            "legal_name": "Acme Technologies Pvt Ltd",   # very similar to R01
            "entity_type": "pvt_ltd",
            "pan": SUNRISE_PAN,  # different PAN so not DV1
            "gstin": SUNRISE_GSTIN,
            "cin": make_cin("U", "67190", "DL", "2012", "PTC", "999014"),
            "ifsc": "ICIC0001234",
            "address_state_code": "07",
        },
    },
    {
        "id": "R24",
        "notes": "DV1 — PAN + different GSTIN + non-matching name → human_review",
        "expected_outcome": "human_review",
        "expected_triggered_checks": ["duplicate_pan_gstin"],
        "is_legit_near_miss": False,
        "vendor": {
            "legal_name": "Totally Different Co",  # name mismatch with existing
            "entity_type": "pvt_ltd",
            "pan": ACME_PAN,  # same PAN as R01
            "gstin": make_gstin("29", ACME_PAN),   # different state GSTIN
            "cin": make_cin("U", "67190", "KA", "2010", "PTC", "999015"),
            "ifsc": "HDFC0001234",
            "address_state_code": "29",
        },
    },
    {
        "id": "R25",
        "notes": "DV1 — same GSTIN as R01 → hard → rejected",
        "expected_outcome": "rejected",
        "expected_triggered_checks": ["duplicate_pan_gstin"],
        "is_legit_near_miss": False,
        "vendor": {
            "legal_name": "Duplicate GSTIN Corp",
            "entity_type": "pvt_ltd",
            "pan": ACME_PAN,
            "gstin": ACME_GSTIN,  # exact GSTIN collision with R01
            "cin": make_cin("U", "67190", "MH", "2010", "PTC", "999016"),
            "ifsc": "HDFC0001234",
            "address_state_code": "27",
        },
    },

    # ── Legitimate near-miss vendors (5) ─────────────────────────────────────
    {
        "id": "R26",
        "notes": "Near-miss: 'M/s Bharat Traders' normalises to 'bharat traders' — should pass B3",
        "expected_outcome": "approved",
        "expected_triggered_checks": [],
        "is_legit_near_miss": True,
        "vendor": {
            "legal_name": "Bharat Traders",
            "entity_type": "partnership",
            "pan": BHARAT_PAN,
            "gstin": BHARAT_GSTIN,
            "cin": None,
            "ifsc": "SBIN0005678",
            "address_state_code": "29",
            "bank_account_holder_name": "M/s Bharat Traders",
        },
    },
    {
        "id": "R27",
        "notes": "Near-miss: trading MSME — no payment cap should apply, still approved",
        "expected_outcome": "approved",
        "expected_triggered_checks": ["payment_term_cap"],  # fires but cap=None
        "is_legit_near_miss": True,
        "vendor": {
            "legal_name": "Kuber Traders Pvt Ltd",
            "entity_type": "pvt_ltd",
            "pan": MSME_TRD_PAN,
            "gstin": MSME_TRD_GSTIN,
            "cin": make_cin("U", "52100", "DL", "2018", "PTC", "999017"),
            "ifsc": "PUNB0007890",
            "address_state_code": "07",
            "udyam_number": "UDYAM-DL-01-0001234",
            "udyam_category": "micro",
            "udyam_activity_type": "trading",   # excluded from §37(2)(g)
        },
    },
    {
        "id": "R28",
        "notes": "Near-miss: Section 8 company with valid NPL CIN — should approve",
        "expected_outcome": "approved",
        "expected_triggered_checks": [],
        "is_legit_near_miss": True,
        "vendor": {
            "legal_name": "Education For All Foundation",
            "entity_type": "section8",
            "pan": SECT8_PAN,
            "gstin": SECT8_GSTIN,
            "cin": make_cin("U", "85300", "TN", "2008", "NPL", "999018"),
            "ifsc": "IOBA0001234",
            "address_state_code": "33",
        },
    },
    {
        "id": "R29",
        "notes": "Near-miss: DV1 same PAN + different GSTIN + matching name → additional GST site (allowed)",
        "expected_outcome": "approved",
        "expected_triggered_checks": ["duplicate_pan_gstin"],
        "is_legit_near_miss": True,
        "vendor": {
            "legal_name": "Acme Technologies Private Limited",  # same name as R01
            "entity_type": "pvt_ltd",
            "pan": ACME_PAN,  # same PAN
            "gstin": make_gstin("29", ACME_PAN),   # Karnataka branch
            "cin": make_cin("U", "67190", "KA", "2010", "PTC", "999019"),
            "ifsc": "HDFC0001234",
            "address_state_code": "29",
            "additional_site_flag": True,  # DV1 logic: name matches → additional site
        },
    },
    {
        "id": "R30",
        "notes": "Near-miss: medium MSME — no payment cap, all else clean → approved",
        "expected_outcome": "approved",
        "expected_triggered_checks": ["payment_term_cap"],
        "is_legit_near_miss": True,
        "vendor": {
            "legal_name": "Medium Scale Industries Pvt Ltd",
            "entity_type": "pvt_ltd",
            "pan": MSME_SVC_PAN,
            "gstin": MSME_SVC_GSTIN,
            "cin": make_cin("U", "27300", "KA", "2010", "PTC", "999020"),
            "ifsc": "SBIN0005678",
            "address_state_code": "29",
            "udyam_number": "UDYAM-KA-02-0009999",
            "udyam_category": "medium",
            "udyam_activity_type": "services",   # medium → no cap
        },
    },
]

# ── 8 End-to-End Records (with PDFs) ──────────────────────────────────────────

E2E_RECORDS = [
    {
        "id": "E01",
        "notes": "Clean approval — all docs present, good OCR quality",
        "expected_outcome": "approved",
        "expected_triggered_checks": [],
        "is_legit_near_miss": False,
        "pdf_set": ["pan_card", "gst_certificate", "cancelled_cheque", "coi"],
        "extraction_scenarios": {
            "pan_on_card": ACME_PAN,
            "name_on_card": "Acme Technologies Pvt Ltd",
            "gstin_on_cert": ACME_GSTIN,
            "legal_name_on_cert": "Acme Technologies Private Limited",
            "state_on_cert": "27",
            "confidence": 0.95,
        },
        "vendor": RULES_RECORDS[0]["vendor"],
    },
    {
        "id": "E02",
        "notes": "PAN card name mismatch (CD2): cheque says 'Acme Tech' vs 'Acme Technologies'",
        "expected_outcome": "pending",  # first failure → fixable
        "expected_triggered_checks": ["pan_card_name_match"],
        "is_legit_near_miss": True,
        "pdf_set": ["pan_card", "gst_certificate", "cancelled_cheque", "coi"],
        "extraction_scenarios": {
            "pan_on_card": ACME_PAN,
            "name_on_card": "Acme Tech",   # abbreviated → score ~80 → fixable
            "confidence": 0.92,
        },
        "vendor": RULES_RECORDS[0]["vendor"],
    },
    {
        "id": "E03",
        "notes": "Low-quality GST cert scan: confidence=0.55 → state check skipped",
        "expected_outcome": "approved",  # state check skipped, no other issues
        "expected_triggered_checks": ["gstin_state_code_match"],  # fires as fixable from confidence gate
        "is_legit_near_miss": True,
        "pdf_set": ["pan_card", "gst_certificate", "cancelled_cheque", "coi"],
        "extraction_scenarios": {
            "gstin_on_cert": ACME_GSTIN,
            "state_on_cert": "27",
            "confidence": 0.55,   # below threshold → state check downgraded to fixable
        },
        "vendor": RULES_RECORDS[0]["vendor"],
    },
    {
        "id": "E04",
        "notes": "PDF editing tool signal: Canva used to create GST certificate",
        "expected_outcome": "human_review",  # +5 from pdf_editing_tool + other soft signals
        "expected_triggered_checks": ["pdf_editing_tool"],
        "is_legit_near_miss": False,
        "pdf_set": ["pan_card", "gst_certificate", "cancelled_cheque", "coi"],
        "extraction_scenarios": {
            "pdf_producer_gst_cert": "Canva",
            "confidence": 0.90,
        },
        "vendor": RULES_RECORDS[1]["vendor"],
    },
    {
        "id": "E05",
        "notes": "Impossible creation date: GST cert PDF CreationDate < claimed issue date",
        "expected_outcome": "human_review",  # +10 impossible date → score 10 (< threshold 20)
        "expected_triggered_checks": ["pdf_impossible_creation_date"],
        "is_legit_near_miss": False,
        "pdf_set": ["pan_card", "gst_certificate", "cancelled_cheque", "coi"],
        "extraction_scenarios": {
            "pdf_creation_date": "2018-01-01",   # before claimed issue date
            "claimed_issue_date": "2020-06-15",
            "confidence": 0.91,
        },
        "vendor": RULES_RECORDS[2]["vendor"],
    },
    {
        "id": "E06",
        "notes": "IFSC on cheque doesn't match submission (CD6, hard, confidence-gated)",
        "expected_outcome": "rejected",
        "expected_triggered_checks": ["cheque_ifsc_account_match"],
        "is_legit_near_miss": False,
        "pdf_set": ["pan_card", "gst_certificate", "cancelled_cheque", "coi"],
        "extraction_scenarios": {
            "ifsc_on_cheque": "SBIN0001111",   # different from submission IFSC
            "confidence": 0.95,
        },
        "vendor": RULES_RECORDS[0]["vendor"],
    },
    {
        "id": "E07",
        "notes": "COI CIN mismatch (CD5a): CIN on COI differs from submission",
        "expected_outcome": "rejected",
        "expected_triggered_checks": ["coi_cin_match"],
        "is_legit_near_miss": False,
        "pdf_set": ["pan_card", "gst_certificate", "cancelled_cheque", "coi"],
        "extraction_scenarios": {
            "cin_on_coi": make_cin("U", "67190", "MH", "2010", "PTC", "DIFFER"),
            "confidence": 0.93,
        },
        "vendor": RULES_RECORDS[0]["vendor"],
    },
    {
        "id": "E08",
        "notes": "Legit near-miss: 'Pvt Ltd' vs 'Private Limited' across all docs — should approve",
        "expected_outcome": "approved",
        "expected_triggered_checks": [],
        "is_legit_near_miss": True,
        "pdf_set": ["pan_card", "gst_certificate", "cancelled_cheque", "coi"],
        "extraction_scenarios": {
            "pan_on_card": ACME_PAN,
            "name_on_card": "Acme Technologies Pvt Ltd",        # normalises same
            "legal_name_on_cert": "Acme Technologies Pvt Ltd",  # normalises same
            "confidence": 0.94,
        },
        "vendor": RULES_RECORDS[0]["vendor"],
    },
]

# ── Write output ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import yaml
    output_dir = os.path.join(os.path.dirname(__file__), "..", "tests", "fixtures")
    os.makedirs(output_dir, exist_ok=True)

    rules_path = os.path.join(output_dir, "eval_set_rules.yaml")
    with open(rules_path, "w") as f:
        yaml.dump({"records": RULES_RECORDS}, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    print(f"Wrote {len(RULES_RECORDS)} rules-only records → {rules_path}")

    e2e_path = os.path.join(output_dir, "eval_set_e2e.yaml")
    with open(e2e_path, "w") as f:
        yaml.dump({"records": E2E_RECORDS}, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
    print(f"Wrote {len(E2E_RECORDS)} end-to-end records → {e2e_path}")

    # Summarise legit near-misses
    near_misses_rules = [r for r in RULES_RECORDS if r["is_legit_near_miss"]]
    near_misses_e2e   = [r for r in E2E_RECORDS if r["is_legit_near_miss"]]
    print(f"\nLegit near-misses: {len(near_misses_rules)} rules-only + {len(near_misses_e2e)} e2e")
    print("Near-miss IDs:", [r["id"] for r in near_misses_rules + near_misses_e2e])
    print("\nOutcome distribution (rules):")
    from collections import Counter
    for outcome, count in Counter(r["expected_outcome"] for r in RULES_RECORDS).most_common():
        print(f"  {outcome}: {count}")
