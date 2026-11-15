"""
tests/test_adversarial.py — Permanent adversarial test suite.
A false approval is the worst outcome.

Tests:
1. wrong-name text cheque: Digital PDF cheque with different name -> MUST NOT approve.
2. wrong-name image-only cheque: Raster image PDF cheque with no text layer -> MUST NOT approve.
3. cheque with a different layout: Uses 'Beneficiary Name' layout with mismatched name -> MUST NOT approve.
4. irrelevant PDF as cheque: Generic essay uploaded as cheque -> doc classification detects unknown -> MUST NOT approve.
5. GST certificate uploaded as PAN card: Doc classification detects GST -> mismatch fail -> MUST NOT approve.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import tempfile
import uuid
from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.demo_scenarios import (
    DEMO_DOCS_DIR,
    PAN_CLEAN,
    GSTIN_CLEAN,
    CIN_CLEAN,
    get_demo_documents,
)
from app.models import CheckResult, Decision, Document, VendorSubmission
from app.pipeline.orchestrator import run_pipeline
from scripts.seed_demo import reset_and_seed

ADVERSARIAL_DIR = Path("tests/fixtures/adversarial_docs")
ADVERSARIAL_DIR.mkdir(parents=True, exist_ok=True)


@pytest.fixture(scope="module", autouse=True)
def init_db():
    reset_and_seed()


def _create_clean_submission(db: Session, sub_id: str, legal_name: str = "Acme Industrial Solutions Private Limited") -> VendorSubmission:
    unique_acct = f"9876543{uuid.uuid4().int % 100000:05d}"
    secret = os.environ.get("HMAC_SECRET", "dev-secret-change-in-production")
    acct_hmac = hashlib.sha256(f"{secret}:{unique_acct}".encode()).hexdigest()
    sub = VendorSubmission(
        id=sub_id,
        created_at="2026-11-13T12:00:00Z",
        status="submitted",
        legal_name=legal_name,
        trade_name=legal_name,
        entity_type="pvt_ltd",
        pan=PAN_CLEAN,
        gstin=GSTIN_CLEAN,
        cin=CIN_CLEAN,
        ifsc="SBIN0000300",
        bank_account_number=acct_hmac,
        bank_account_number_last4="1234",
        address_line="101 Nariman Point, Mumbai",
        address_state_code="27",
        email="test@example.com",
        attempt_no=1,
    )
    db.add(sub)
    db.flush()
    return sub


def _attach_valid_docs_except(db: Session, sub_id: str, exclude_types: list[str]):
    """Attach genuine clean approval docs except the specified slot(s)."""
    clean_docs = get_demo_documents("clean_approval")
    for doc_type, filename, abs_path in clean_docs:
        if doc_type in exclude_types:
            continue
        with open(abs_path, "rb") as fh:
            sha = hashlib.sha256(fh.read()).hexdigest()
        db.add(
            Document(
                id=str(uuid.uuid4()),
                submission_id=sub_id,
                doc_type=doc_type,
                filename=filename,
                storage_path=abs_path,
                sha256=sha,
                uploaded_at="2026-11-13T12:00:00Z",
            )
        )


def test_adversarial_wrong_name_text_cheque():
    """1. Digital text cheque with a wrong name -> MUST NOT approve."""
    db: Session = SessionLocal()
    sub_id = str(uuid.uuid4())
    _create_clean_submission(db, sub_id)
    _attach_valid_docs_except(db, sub_id, ["cancelled_cheque"])

    # Generate wrong-name digital text cheque
    pdf_path = ADVERSARIAL_DIR / "wrong_name_text_cheque.pdf"
    c = canvas.Canvas(str(pdf_path), pagesize=A4)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(2 * cm, 26 * cm, "CANCELLED CHEQUE")
    c.setFont("Helvetica", 11)
    c.drawString(2 * cm, 24 * cm, "Pay to: Fraudster Holdings Limited")
    c.drawString(2 * cm, 22 * cm, "Account Number: XXXX XXXX 1234")
    c.drawString(2 * cm, 20 * cm, "IFSC: SBIN0000300")
    c.save()

    with open(pdf_path, "rb") as fh:
        sha = hashlib.sha256(fh.read()).hexdigest()

    db.add(
        Document(
            id=str(uuid.uuid4()),
            submission_id=sub_id,
            doc_type="cancelled_cheque",
            filename="cancelled_cheque.pdf",
            storage_path=str(pdf_path),
            sha256=sha,
            uploaded_at="2026-11-13T12:00:00Z",
        )
    )
    db.commit()
    db.close()

    asyncio.run(run_pipeline(sub_id))

    db = SessionLocal()
    dec = db.query(Decision).filter(Decision.submission_id == sub_id).first()
    checks = db.query(CheckResult).filter(CheckResult.submission_id == sub_id).all()
    db.close()

    assert dec.outcome != "approved", f"Adversarial wrong-name text cheque was falsely approved! Outcome: {dec.outcome}"
    assert dec.outcome in ("pending", "rejected")
    failing = [c.check_name for c in checks if c.status in ("fail", "missing")]
    assert "bank_name_fuzzy_match" in failing


def test_adversarial_wrong_name_image_only_cheque():
    """2. Raster image-only cheque with wrong name and zero digital text layer -> MUST NOT approve."""
    db: Session = SessionLocal()
    sub_id = str(uuid.uuid4())
    _create_clean_submission(db, sub_id)
    _attach_valid_docs_except(db, sub_id, ["cancelled_cheque"])

    # Generate raster image with wrong name
    img = Image.new("RGB", (1000, 500), color=(255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text(
        (50, 50),
        "STATE BANK OF INDIA\nCANCELLED CHEQUE\nPay to: Imposter Operations Limited\nAccount No: XXXX 1234\nIFS Code: SBIN0000300",
        fill=(0, 0, 0),
    )
    img_path = ADVERSARIAL_DIR / "wrong_cheque_scan.png"
    img.save(img_path)

    pdf_path = ADVERSARIAL_DIR / "wrong_name_image_only_cheque.pdf"
    c = canvas.Canvas(str(pdf_path), pagesize=A4)
    c.drawImage(str(img_path), 2 * cm, 15 * cm, 16 * cm, 8 * cm)
    c.save()

    with open(pdf_path, "rb") as fh:
        sha = hashlib.sha256(fh.read()).hexdigest()

    db.add(
        Document(
            id=str(uuid.uuid4()),
            submission_id=sub_id,
            doc_type="cancelled_cheque",
            filename="scanned_cheque.pdf",
            storage_path=str(pdf_path),
            sha256=sha,
            uploaded_at="2026-11-13T12:00:00Z",
        )
    )
    db.commit()
    db.close()

    asyncio.run(run_pipeline(sub_id))

    db = SessionLocal()
    dec = db.query(Decision).filter(Decision.submission_id == sub_id).first()
    checks = db.query(CheckResult).filter(CheckResult.submission_id == sub_id).all()
    db.close()

    assert dec.outcome != "approved", f"Adversarial wrong-name scanned cheque was falsely approved! Outcome: {dec.outcome}"
    assert dec.outcome in ("pending", "rejected")
    failing = [c.check_name for c in checks if c.status in ("fail", "missing")]
    assert "bank_name_fuzzy_match" in failing


def test_adversarial_cheque_different_layout():
    """3. Cheque with alternate layout ('Beneficiary Name') but wrong entity -> MUST NOT approve."""
    db: Session = SessionLocal()
    sub_id = str(uuid.uuid4())
    _create_clean_submission(db, sub_id)
    _attach_valid_docs_except(db, sub_id, ["cancelled_cheque"])

    # Generate alternate layout cheque
    pdf_path = ADVERSARIAL_DIR / "different_layout_wrong_cheque.pdf"
    c = canvas.Canvas(str(pdf_path), pagesize=A4)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(2 * cm, 26 * cm, "HDFC BANK LIMITED - CANCELLED CHEQUE")
    c.setFont("Helvetica", 11)
    c.drawString(2 * cm, 24 * cm, "Beneficiary Name: Completely Different Enterprises LLP")
    c.drawString(2 * cm, 22 * cm, "A/c Number: 50100012345678")
    c.drawString(2 * cm, 20 * cm, "IFS Code: HDFC0001234")
    c.save()

    with open(pdf_path, "rb") as fh:
        sha = hashlib.sha256(fh.read()).hexdigest()

    db.add(
        Document(
            id=str(uuid.uuid4()),
            submission_id=sub_id,
            doc_type="cancelled_cheque",
            filename="cancelled_cheque.pdf",
            storage_path=str(pdf_path),
            sha256=sha,
            uploaded_at="2026-11-13T12:00:00Z",
        )
    )
    db.commit()
    db.close()

    asyncio.run(run_pipeline(sub_id))

    db = SessionLocal()
    dec = db.query(Decision).filter(Decision.submission_id == sub_id).first()
    checks = db.query(CheckResult).filter(CheckResult.submission_id == sub_id).all()
    db.close()

    assert dec.outcome != "approved", f"Alternate layout with mismatched name was falsely approved! Outcome: {dec.outcome}"
    assert dec.outcome in ("pending", "rejected")
    failing = [c.check_name for c in checks if c.status in ("fail", "missing")]
    assert "bank_name_fuzzy_match" in failing


def test_adversarial_irrelevant_pdf_as_cheque():
    """4. Irrelevant literature PDF uploaded into cheque slot -> doc classification fails -> MUST NOT approve."""
    db: Session = SessionLocal()
    sub_id = str(uuid.uuid4())
    _create_clean_submission(db, sub_id)
    _attach_valid_docs_except(db, sub_id, ["cancelled_cheque"])

    # Generate irrelevant essay document
    pdf_path = ADVERSARIAL_DIR / "irrelevant_essay.pdf"
    c = canvas.Canvas(str(pdf_path), pagesize=A4)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(2 * cm, 26 * cm, "A STUDY ON MODERN ARCHITECTURE")
    c.setFont("Helvetica", 11)
    c.drawString(2 * cm, 24 * cm, "Lorem ipsum dolor sit amet, consectetur adipiscing elit.")
    c.drawString(2 * cm, 22 * cm, "Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.")
    c.drawString(2 * cm, 20 * cm, "Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris.")
    c.save()

    with open(pdf_path, "rb") as fh:
        sha = hashlib.sha256(fh.read()).hexdigest()

    db.add(
        Document(
            id=str(uuid.uuid4()),
            submission_id=sub_id,
            doc_type="cancelled_cheque",
            filename="essay_cheque.pdf",
            storage_path=str(pdf_path),
            sha256=sha,
            uploaded_at="2026-11-13T12:00:00Z",
        )
    )
    db.commit()
    db.close()

    asyncio.run(run_pipeline(sub_id))

    db = SessionLocal()
    dec = db.query(Decision).filter(Decision.submission_id == sub_id).first()
    checks = db.query(CheckResult).filter(CheckResult.submission_id == sub_id).all()
    db.close()

    assert dec.outcome != "approved", f"Irrelevant document in cheque slot was falsely approved! Outcome: {dec.outcome}"
    assert dec.outcome == "pending"
    failing = [c.check_name for c in checks if c.status in ("fail", "missing")]
    assert "document_type_match_cancelled_cheque" in failing or "bank_name_fuzzy_match" in failing


def test_adversarial_gst_uploaded_as_pan():
    """5. GST Certificate uploaded into PAN slot -> doc classification fails -> MUST NOT approve."""
    db: Session = SessionLocal()
    sub_id = str(uuid.uuid4())
    _create_clean_submission(db, sub_id)
    _attach_valid_docs_except(db, sub_id, ["pan_card"])

    # Use the clean GST certificate PDF in the pan_card slot
    clean_docs = get_demo_documents("clean_approval")
    gst_path = next(p for t, f, p in clean_docs if t == "gst_certificate")

    with open(gst_path, "rb") as fh:
        sha = hashlib.sha256(fh.read()).hexdigest()

    db.add(
        Document(
            id=str(uuid.uuid4()),
            submission_id=sub_id,
            doc_type="pan_card",
            filename="gst_as_pan.pdf",
            storage_path=gst_path,
            sha256=sha,
            uploaded_at="2026-11-13T12:00:00Z",
        )
    )
    db.commit()
    db.close()

    asyncio.run(run_pipeline(sub_id))

    db = SessionLocal()
    dec = db.query(Decision).filter(Decision.submission_id == sub_id).first()
    checks = db.query(CheckResult).filter(CheckResult.submission_id == sub_id).all()
    db.close()

    assert dec.outcome != "approved", f"GST cert in PAN slot was falsely approved! Outcome: {dec.outcome}"
    assert dec.outcome in ("pending", "rejected")
    failing = [c.check_name for c in checks if c.status in ("fail", "missing")]
    assert "document_type_match_pan_card" in failing or "pan_card_number_match" in failing


def _generate_custom_doc(doc_type: str, filename: str, custom_name: str, pan: str = PAN_CLEAN, gstin: str = GSTIN_CLEAN, cin: str = CIN_CLEAN) -> str:
    pdf_path = ADVERSARIAL_DIR / filename
    c = canvas.Canvas(str(pdf_path), pagesize=A4)
    if doc_type == "pan_card":
        c.setFont("Helvetica-Bold", 14)
        c.drawString(2 * cm, 26 * cm, "INCOME TAX DEPARTMENT - GOVT OF INDIA")
        c.setFont("Helvetica", 11)
        c.drawString(2 * cm, 24 * cm, f"Name: {custom_name}")
        c.drawString(2 * cm, 22 * cm, f"PAN: {pan}")
    elif doc_type == "gst_certificate":
        c.setFont("Helvetica-Bold", 14)
        c.drawString(2 * cm, 26 * cm, "GOVERNMENT OF INDIA - GST REGISTRATION CERTIFICATE")
        c.setFont("Helvetica", 11)
        c.drawString(2 * cm, 24 * cm, f"Legal Name: {custom_name}")
        c.drawString(2 * cm, 22 * cm, f"GSTIN: {gstin}")
        c.drawString(2 * cm, 20 * cm, "State Code: 27")
    elif doc_type == "cancelled_cheque":
        c.setFont("Helvetica-Bold", 14)
        c.drawString(2 * cm, 26 * cm, "CANCELLED CHEQUE - STATE BANK OF INDIA")
        c.setFont("Helvetica", 11)
        c.drawString(2 * cm, 24 * cm, f"Pay to: {custom_name}")
        c.drawString(2 * cm, 22 * cm, "Account Number: XXXX XXXX 1234")
        c.drawString(2 * cm, 20 * cm, "IFSC: SBIN0000300")
    elif doc_type == "coi":
        c.setFont("Helvetica-Bold", 14)
        c.drawString(2 * cm, 26 * cm, "CERTIFICATE OF INCORPORATION")
        c.setFont("Helvetica", 11)
        c.drawString(2 * cm, 24 * cm, f"This is to certify that: {custom_name}")
        c.drawString(2 * cm, 22 * cm, f"CIN: {cin}")
        c.drawString(2 * cm, 20 * cm, "Date of Incorporation: 2018-06-15")
    c.save()
    return str(pdf_path)


@pytest.mark.parametrize("lookalike_name", [
    "Someone Industrial Systems",
    "Acme Industrial Systems Trading",
    "Acme Industrial Systems Holdings",
])
@pytest.mark.parametrize("target_slot", [
    "pan_card",
    "gst_certificate",
    "cancelled_cheque",
    "coi",
])
def test_adversarial_lookalike_names_must_not_approve(lookalike_name: str, target_slot: str):
    """
    Lookalike entities must NOT approve on PAN card, COI, GST cert or cheque.
    - 'Someone Industrial Systems' (unshared word 'someone' -> fail/pending)
    - 'Acme Industrial Systems Trading' (unshared word 'trading' -> not approved)
    - 'Acme Industrial Systems Holdings' (unshared word 'holdings' -> not approved)
    """
    db: Session = SessionLocal()
    sub_id = str(uuid.uuid4())
    _create_clean_submission(db, sub_id, legal_name="Acme Industrial Systems")
    _attach_valid_docs_except(db, sub_id, [target_slot])

    fn = f"lookalike_{target_slot}_{lookalike_name.replace(' ', '_').lower()}.pdf"
    doc_path = _generate_custom_doc(target_slot, fn, lookalike_name)

    with open(doc_path, "rb") as fh:
        sha = hashlib.sha256(fh.read()).hexdigest()

    db.add(
        Document(
            id=str(uuid.uuid4()),
            submission_id=sub_id,
            doc_type=target_slot,
            filename=fn,
            storage_path=doc_path,
            sha256=sha,
            uploaded_at="2026-11-13T12:00:00Z",
        )
    )
    db.commit()
    db.close()

    asyncio.run(run_pipeline(sub_id))

    db = SessionLocal()
    dec = db.query(Decision).filter(Decision.submission_id == sub_id).first()
    db.close()

    assert dec.outcome != "approved", (
        f"Lookalike entity '{lookalike_name}' in slot '{target_slot}' was falsely approved! Outcome: {dec.outcome}"
    )


@pytest.mark.parametrize("legit_variant", [
    "Acme Industrial Systems Pvt Ltd",
    "M/s Acme Industrial Systems",
    "Industrial Systems Acme",
    "Acme Industrial Systems (India) Pvt Ltd",
    "Acme Industrial Systems Pvt Ltd Unit 2",
    "M/s Acme Industrial Systems Pvt Ltd Current A/C",
])
def test_legit_name_variants_must_approve(legit_variant: str):
    """
    Legit variants ('Pvt Ltd' vs 'Private Limited', 'M/s' prefix, reordered words,
    parenthesised text e.g. '(India)', 'Unit <n>', 'Current A/C')
    must still approve with token_sort_ratio >= 90 through the full pipeline.
    """
    db: Session = SessionLocal()
    sub_id = str(uuid.uuid4())
    _create_clean_submission(db, sub_id, legal_name="Acme Industrial Systems Private Limited")
    _attach_valid_docs_except(db, sub_id, ["cancelled_cheque"])

    fn = f"legit_cheque_{legit_variant.replace(' ', '_').replace('/', '_').lower()}.pdf"
    doc_path = _generate_custom_doc("cancelled_cheque", fn, legit_variant)

    with open(doc_path, "rb") as fh:
        sha = hashlib.sha256(fh.read()).hexdigest()

    db.add(
        Document(
            id=str(uuid.uuid4()),
            submission_id=sub_id,
            doc_type="cancelled_cheque",
            filename=fn,
            storage_path=doc_path,
            sha256=sha,
            uploaded_at="2026-11-13T12:00:00Z",
        )
    )
    db.commit()
    db.close()

    asyncio.run(run_pipeline(sub_id))

    db = SessionLocal()
    dec = db.query(Decision).filter(Decision.submission_id == sub_id).first()
    db.close()

    assert dec.outcome == "approved", (
        f"Legitimate variant '{legit_variant}' was incorrectly rejected/pending! Outcome: {dec.outcome}, "
        f"Hard: {dec.hard_fail_checks}, Fixable: {dec.fixable_checks}"
    )
