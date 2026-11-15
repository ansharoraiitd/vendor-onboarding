"""
app/demo_scenarios.py — Canonical demo scenario generator with valid identifiers
and matching synthetic documents attached server-side.

Produces:
- Valid PAN (10 chars, 4th char matching entity type)
- Valid GSTIN (mod-36 checksum calculated via left-to-right alternating factor 2,1)
- Valid CIN (format, ROC state, year, company type PTC/PLC/NPL)
- Real generated matching PDF attachments
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.validators.gstin import _compute_gstin_checksum

DEMO_DOCS_DIR = Path(__file__).parent.parent / "tests" / "fixtures" / "demo_docs"


def make_pan(entity_type: str, prefix_alpha: str = "AAB", seq_num: str = "1001", check_char: str = "A") -> str:
    """Generate a valid 10-char PAN matching entity type."""
    type_char_map = {
        "proprietorship": "P",
        "partnership": "F",
        "llp": "F",
        "pvt_ltd": "C",
        "pub_ltd": "C",
        "section8": "C",
    }
    type_char = type_char_map.get(entity_type.lower(), "C")
    return f"{prefix_alpha[:3].upper()}{type_char}{prefix_alpha[-1].upper()}{seq_num[:4]}{check_char.upper()}"


def make_gstin(state_code: str, pan: str, entity_num: str = "1") -> str:
    """Generate a valid 15-char GSTIN with mathematical mod-36 checksum."""
    prefix14 = f"{state_code[:2]}{pan[:10]}{entity_num[:1]}Z"
    checksum = _compute_gstin_checksum(prefix14)
    return f"{prefix14}{checksum}"


def make_cin(state_alpha: str, year: int, entity_type: str, seq: str = "123456", listed: bool = False) -> str:
    """Generate a valid 21-char CIN."""
    l_char = "L" if listed else "U"
    industry = "24100"  # Manufacturing / chemicals
    ownership_map = {
        "pvt_ltd": "PTC",
        "pub_ltd": "PLC",
        "section8": "NPL",
    }
    ownership = ownership_map.get(entity_type.lower(), "PTC")
    return f"{l_char}{industry}{state_alpha.upper()[:2]}{year}{ownership}{seq[:6]}"


@dataclass
class DemoScenario:
    key: str
    name: str
    description: str
    expected_outcome: str
    expected_failing_checks: List[str]
    data: Dict[str, Any]
    cheque_holder_override: Optional[str] = None
    expected_payment_cap: Optional[int] = None


# Existing approved vendor bank account from seed_demo.py
SEED_EXISTING_APPROVED_ACCOUNT = "123456781234"

# ---------------------------------------------------------------------------
# Definitive Scenario Registry
# ---------------------------------------------------------------------------

PAN_CLEAN = make_pan("pvt_ltd", "AAC", "1234", "D")
GSTIN_CLEAN = make_gstin("27", PAN_CLEAN)
CIN_CLEAN = make_cin("MH", 2018, "pvt_ltd", "112233")

PAN_NEAR_MISS = make_pan("pvt_ltd", "AAB", "2345", "E")
GSTIN_NEAR_MISS = make_gstin("27", PAN_NEAR_MISS)
CIN_NEAR_MISS = make_cin("MH", 2019, "pvt_ltd", "223344")

PAN_MISMATCH = "BBBPP9999Z"  # 4th char P does not match pvt_ltd C + invalid in adapter
GSTIN_FOR_MISMATCH = make_gstin("27", "AABCC1111A")
CIN_FOR_MISMATCH = make_cin("MH", 2020, "pvt_ltd", "334455")

PAN_GSTIN_FAIL = make_pan("pvt_ltd", "AAD", "4567", "F")
# Deliberately invalidate 15th checksum char
_gstin_clean_tmp = make_gstin("27", PAN_GSTIN_FAIL)
_wrong_check = "0" if _gstin_clean_tmp[-1] != "0" else "1"
GSTIN_INVALID_CHECKSUM = f"{_gstin_clean_tmp[:14]}{_wrong_check}"
CIN_GSTIN_FAIL = make_cin("MH", 2021, "pvt_ltd", "445566")

PAN_WRONG_CHQ = make_pan("pvt_ltd", "AAE", "5678", "G")
GSTIN_WRONG_CHQ = make_gstin("27", PAN_WRONG_CHQ)
CIN_WRONG_CHQ = make_cin("MH", 2017, "pvt_ltd", "556677")

PAN_TRADING = make_pan("llp", "AAF", "6789", "H")
GSTIN_TRADING = make_gstin("24", PAN_TRADING)

PAN_MICRO_MFG = make_pan("proprietorship", "AAG", "7890", "J")
GSTIN_MICRO_MFG = make_gstin("27", PAN_MICRO_MFG)

PAN_SHARED_BANK = make_pan("partnership", "AAH", "8901", "K")
GSTIN_SHARED_BANK = make_gstin("27", PAN_SHARED_BANK)


DEMO_SCENARIOS: Dict[str, DemoScenario] = {
    "clean_approval": DemoScenario(
        key="clean_approval",
        name="Clean Approval",
        description="Pristine Pvt Ltd vendor, micro manufacturer with 30-day agreement.",
        expected_outcome="approved",
        expected_failing_checks=[],
        expected_payment_cap=30,
        data={
            "legal_name": "Acme Industrial Systems Private Limited",
            "trade_name": "Acme Industrial",
            "entity_type": "pvt_ltd",
            "pan": PAN_CLEAN,
            "gstin": GSTIN_CLEAN,
            "cin": CIN_CLEAN,
            "ifsc": "SBIN0000300",
            "bank_account_number": "987654321001",
            "udyam_number": "UDYAM-MH-00-0012345",
            "udyam_category": "micro",
            "udyam_activity_type": "manufacturing",
            "address_line": "123 Industrial Estate, Andheri East, Mumbai",
            "address_state_code": "27",
            "email": "vendor@acmeindustrial.example.com",
            "agreed_payment_days": 30,
        },
    ),
    "bank_name_near_miss": DemoScenario(
        key="bank_name_near_miss",
        name="Bank Name Near-Miss",
        description="Cheque says 'Pvt Ltd' vs submitted 'Private Limited' (should approve).",
        expected_outcome="approved",
        expected_failing_checks=[],
        cheque_holder_override="Bharat Precision Tools Pvt Ltd",
        data={
            "legal_name": "Bharat Precision Tools Private Limited",
            "trade_name": "Bharat Tools",
            "entity_type": "pvt_ltd",
            "pan": PAN_NEAR_MISS,
            "gstin": GSTIN_NEAR_MISS,
            "cin": CIN_NEAR_MISS,
            "ifsc": "HDFC0001234",
            "bank_account_number": "987654321002",
            "address_line": "45 MIDC Industrial Area, Pune",
            "address_state_code": "27",
            "email": "vendor@bharattools.example.com",
        },
    ),
    "pan_mismatch": DemoScenario(
        key="pan_mismatch",
        name="PAN Mismatch",
        description="PAN format / status invalid for private limited entity (rejected).",
        expected_outcome="rejected",
        expected_failing_checks=["pan_entity_type_match", "pan_status"],
        data={
            "legal_name": "Apex Tech Solutions Private Limited",
            "entity_type": "pvt_ltd",
            "pan": PAN_MISMATCH,
            "gstin": GSTIN_FOR_MISMATCH,
            "cin": CIN_FOR_MISMATCH,
            "ifsc": "SBIN0000300",
            "bank_account_number": "987654321003",
            "address_line": "78 Cyber Park, Mumbai",
            "address_state_code": "27",
            "email": "vendor@apextech.example.com",
        },
    ),
    "gstin_fail": DemoScenario(
        key="gstin_fail",
        name="GSTIN Checksum Fail",
        description="GSTIN fails mod-36 checksum verification (rejected).",
        expected_outcome="rejected",
        expected_failing_checks=["gstin_checksum"],
        data={
            "legal_name": "Zenith Logistics Private Limited",
            "entity_type": "pvt_ltd",
            "pan": PAN_GSTIN_FAIL,
            "gstin": GSTIN_INVALID_CHECKSUM,
            "cin": CIN_GSTIN_FAIL,
            "ifsc": "ICIC0002456",
            "bank_account_number": "987654321004",
            "address_line": "12 Transport Nagar, Mumbai",
            "address_state_code": "27",
            "email": "vendor@zenithlogistics.example.com",
        },
    ),
    "wrong_cheque_resubmit": DemoScenario(
        key="wrong_cheque_resubmit",
        name="Wrong Cheque -> Pending",
        description="Cheque name mismatch on attempt 1 causes Pending; resubmission approves.",
        expected_outcome="pending",
        expected_failing_checks=["bank_name_fuzzy_match"],
        cheque_holder_override="Ramesh Chandra Sharma",  # Mismatch < 75
        data={
            "legal_name": "Kalyan Engineering Private Limited",
            "entity_type": "pvt_ltd",
            "pan": PAN_WRONG_CHQ,
            "gstin": GSTIN_WRONG_CHQ,
            "cin": CIN_WRONG_CHQ,
            "ifsc": "HDFC0001234",
            "bank_account_number": "987654321005",
            "address_line": "89 Kalyan Complex, Thane",
            "address_state_code": "27",
            "email": "vendor@kalyaneng.example.com",
        },
    ),
    "trading_msme": DemoScenario(
        key="trading_msme",
        name="Trading MSME",
        description="Trading activity enterprise: approved, but MSME cap exempt (NULL).",
        expected_outcome="approved",
        expected_failing_checks=[],
        expected_payment_cap=None,
        data={
            "legal_name": "Delta Commodities LLP",
            "entity_type": "llp",
            "pan": PAN_TRADING,
            "gstin": GSTIN_TRADING,
            "llpin": "AAA-1234",
            "ifsc": "SBIN0000300",
            "bank_account_number": "987654321006",
            "udyam_number": "UDYAM-GJ-00-0098765",
            "udyam_category": "small",
            "udyam_activity_type": "trading",
            "address_line": "10 Trade Center, Ahmedabad",
            "address_state_code": "24",
            "email": "vendor@deltacommodities.example.com",
            "agreed_payment_days": 45,
        },
    ),
    "micro_manufacturer": DemoScenario(
        key="micro_manufacturer",
        name="Micro Manufacturer (15d Default)",
        description="Micro manufacturing enterprise without written agreement -> 15d default cap.",
        expected_outcome="approved",
        expected_failing_checks=[],
        expected_payment_cap=15,
        data={
            "legal_name": "Omkar Precision Fabricators",
            "entity_type": "proprietorship",
            "pan": PAN_MICRO_MFG,
            "gstin": GSTIN_MICRO_MFG,
            "ifsc": "ICIC0002456",
            "bank_account_number": "987654321007",
            "udyam_number": "UDYAM-MH-01-0001234",
            "udyam_category": "micro",
            "udyam_activity_type": "manufacturing",
            "address_line": "5 Artisan Alley, Nashik",
            "address_state_code": "27",
            "email": "vendor@omkarfab.example.com",
            "agreed_payment_days": None,
        },
    ),
    "shared_bank_account": DemoScenario(
        key="shared_bank_account",
        name="Shared Bank Account",
        description="Bank account HMAC matches another approved vendor (escalate -> human_review).",
        expected_outcome="human_review",
        expected_failing_checks=["duplicate_bank_account"],
        data={
            "legal_name": "Sahyadri Agro Enterprises",
            "entity_type": "partnership",
            "pan": PAN_SHARED_BANK,
            "gstin": GSTIN_SHARED_BANK,
            "ifsc": "SBIN0000300",
            "bank_account_number": SEED_EXISTING_APPROVED_ACCOUNT,  # Triggers DV2
            "address_line": "22 Market Yard, Pune",
            "address_state_code": "27",
            "email": "vendor@sahyadriagro.example.com",
        },
    ),
}


# ---------------------------------------------------------------------------
# Synthetic PDF Generation for Demo Scenarios
# ---------------------------------------------------------------------------

def generate_scenario_pdfs() -> None:
    """Generate valid PDFs for all scenarios in tests/fixtures/demo_docs/."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.pdfgen import canvas

    DEMO_DOCS_DIR.mkdir(parents=True, exist_ok=True)

    for key, sc in DEMO_SCENARIOS.items():
        sc_dir = DEMO_DOCS_DIR / key
        sc_dir.mkdir(parents=True, exist_ok=True)
        d = sc.data

        # 1. PAN Card
        c = canvas.Canvas(str(sc_dir / "pan_card.pdf"), pagesize=A4)
        c.setFont("Helvetica-Bold", 14)
        c.drawString(2 * cm, 26 * cm, "INCOME TAX DEPARTMENT")
        c.setFont("Helvetica", 11)
        c.drawString(2 * cm, 24 * cm, f"Permanent Account Number Card")
        c.drawString(2 * cm, 22 * cm, f"Name: {d['legal_name']}")
        c.drawString(2 * cm, 20 * cm, f"PAN: {d.get('pan', '')}")
        c.drawString(2 * cm, 18 * cm, "Date of Issue: 2022-01-01")
        c.save()

        # 2. GST Certificate
        c = canvas.Canvas(str(sc_dir / "gst_certificate.pdf"), pagesize=A4)
        c.setFont("Helvetica-Bold", 14)
        c.drawString(2 * cm, 26 * cm, "GOODS AND SERVICES TAX REGISTRATION CERTIFICATE")
        c.setFont("Helvetica", 11)
        c.drawString(2 * cm, 24 * cm, f"Legal Name of Business: {d['legal_name']}")
        c.drawString(2 * cm, 22 * cm, f"Trade Name: {d.get('trade_name') or d['legal_name']}")
        c.drawString(2 * cm, 20 * cm, f"GSTIN: {d.get('gstin', '')}")
        c.drawString(2 * cm, 18 * cm, f"State Code: {d.get('address_state_code', '27')}")
        c.drawString(2 * cm, 16 * cm, f"Principal Place of Business: {d.get('address_line', 'Mumbai')}")
        c.drawString(2 * cm, 14 * cm, "Date of Liability: 2022-04-01")
        c.save()

        # 3. Cancelled Cheque
        chq_holder = sc.cheque_holder_override or d["legal_name"]
        acct_last4 = str(d.get("bank_account_number", "1234"))[-4:]
        c = canvas.Canvas(str(sc_dir / "cancelled_cheque.pdf"), pagesize=A4)
        c.setFont("Helvetica-Bold", 14)
        c.drawString(2 * cm, 26 * cm, "CANCELLED CHEQUE")
        c.setFont("Helvetica", 11)
        c.drawString(2 * cm, 24 * cm, f"Pay to: {chq_holder}")
        c.drawString(2 * cm, 22 * cm, f"Account Number: XXXX XXXX {acct_last4}")
        c.drawString(2 * cm, 20 * cm, f"IFSC: {d.get('ifsc', 'SBIN0000300')}")
        c.save()

        # For wrong_cheque_resubmit, also generate a corrected cheque with matching legal name
        if key == "wrong_cheque_resubmit":
            c = canvas.Canvas(str(sc_dir / "corrected_cheque.pdf"), pagesize=A4)
            c.setFont("Helvetica-Bold", 14)
            c.drawString(2 * cm, 26 * cm, "CANCELLED CHEQUE")
            c.setFont("Helvetica", 11)
            c.drawString(2 * cm, 24 * cm, f"Pay to: {d['legal_name']}")
            c.drawString(2 * cm, 22 * cm, f"Account Number: XXXX XXXX {acct_last4}")
            c.drawString(2 * cm, 20 * cm, f"IFSC: {d.get('ifsc', 'HDFC0001234')}")
            c.save()

        # 4. COI or LLPIN cert
        if d.get("cin"):
            cin_str = d["cin"]
            cin_year = cin_str[8:12] if len(cin_str) >= 12 and cin_str[8:12].isdigit() else "2018"
            c = canvas.Canvas(str(sc_dir / "coi.pdf"), pagesize=A4)
            c.setFont("Helvetica-Bold", 14)
            c.drawString(2 * cm, 26 * cm, "CERTIFICATE OF INCORPORATION")
            c.setFont("Helvetica", 11)
            c.drawString(2 * cm, 24 * cm, f"This is to certify that: {d['legal_name']}")
            c.drawString(2 * cm, 22 * cm, f"CIN: {d['cin']}")
            c.drawString(2 * cm, 20 * cm, f"Date of Incorporation: {cin_year}-06-15")
            c.save()

        if d.get("llpin"):
            c = canvas.Canvas(str(sc_dir / "llpin_cert.pdf"), pagesize=A4)
            c.setFont("Helvetica-Bold", 14)
            c.drawString(2 * cm, 26 * cm, "LLPIN REGISTRATION CERTIFICATE")
            c.setFont("Helvetica", 11)
            c.drawString(2 * cm, 24 * cm, f"LLP Name: {d['legal_name']}")
            c.drawString(2 * cm, 22 * cm, f"LLPIN: {d['llpin']}")
            c.drawString(2 * cm, 20 * cm, "Date of Registration: 2019-01-10")
            c.save()

        # 5. Address Proof (Required for proprietorship and partnership)
        if d.get("entity_type") in ("proprietorship", "partnership"):
            c = canvas.Canvas(str(sc_dir / "address_proof.pdf"), pagesize=A4)
            c.setFont("Helvetica-Bold", 14)
            c.drawString(2 * cm, 26 * cm, "ELECTRICITY BILL / PROOF OF ADDRESS")
            c.setFont("Helvetica", 11)
            c.drawString(2 * cm, 24 * cm, f"Name: {d['legal_name']}")
            c.drawString(2 * cm, 22 * cm, f"Address: {d.get('address_line', 'Maharashtra')}")
            c.drawString(2 * cm, 20 * cm, f"State Code: {d.get('address_state_code', '27')}")
            c.drawString(2 * cm, 18 * cm, "Date of Issue: 2024-01-10")
            c.save()

        # 6. Udyam cert
        if d.get("udyam_number"):
            c = canvas.Canvas(str(sc_dir / "udyam_cert.pdf"), pagesize=A4)
            c.setFont("Helvetica-Bold", 14)
            c.drawString(2 * cm, 26 * cm, "UDYAM REGISTRATION CERTIFICATE")
            c.setFont("Helvetica", 11)
            c.drawString(2 * cm, 24 * cm, f"Enterprise: {d['legal_name']}")
            c.drawString(2 * cm, 22 * cm, f"Udyam Number: {d['udyam_number']}")
            c.drawString(2 * cm, 20 * cm, f"Category: {str(d.get('udyam_category', 'micro')).title()}")
            c.drawString(2 * cm, 18 * cm, f"Activity: {str(d.get('udyam_activity_type', 'manufacturing')).title()}")
            c.save()


def get_demo_documents(scenario_key: str) -> List[tuple[str, str, str]]:
    """
    Returns list of (doc_type, filename, absolute_filepath) for a scenario.
    Generates them on-the-fly if not present.
    """
    sc_dir = DEMO_DOCS_DIR / scenario_key
    if not sc_dir.exists() or not list(sc_dir.glob("*.pdf")):
        generate_scenario_pdfs()

    docs = []
    doc_mapping = {
        "pan_card.pdf": "pan_card",
        "gst_certificate.pdf": "gst_certificate",
        "cancelled_cheque.pdf": "cancelled_cheque",
        "coi.pdf": "coi",
        "llpin_cert.pdf": "llpin_cert",
        "udyam_cert.pdf": "udyam_cert",
        "address_proof.pdf": "address_proof",
    }
    for p in sc_dir.glob("*.pdf"):
        if p.name not in doc_mapping:
            continue
        doc_type = doc_mapping[p.name]
        docs.append((doc_type, p.name, str(p)))
    return docs
