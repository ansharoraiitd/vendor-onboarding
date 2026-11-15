"""
tests/test_demo_scenarios.py — Integration test running EVERY demo scenario
through run_pipeline and asserting expected outcomes and check failures.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import uuid
import pytest
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.demo_scenarios import DEMO_DOCS_DIR, DEMO_SCENARIOS, SEED_EXISTING_APPROVED_ACCOUNT, get_demo_documents
from app.models import CheckResult, Decision, Document, VendorSubmission
from app.security import compute_bank_account_hmac
from app.pipeline.orchestrator import run_pipeline
from scripts.seed_demo import reset_and_seed


@pytest.fixture(scope="module", autouse=True)
def setup_seeded_database():
    """Ensure database has seed records (specifically approved vendor with SEED_EXISTING_APPROVED_ACCOUNT)."""
    reset_and_seed()


@pytest.mark.parametrize("scenario_key", list(DEMO_SCENARIOS.keys()))
def test_run_every_demo_scenario(scenario_key: str):
    sc = DEMO_SCENARIOS[scenario_key]
    db: Session = SessionLocal()
    sub_id = str(uuid.uuid4())

    d = sc.data
    raw_acct = str(d.get("bank_account_number") or "")
    acct_hmac = compute_bank_account_hmac(raw_acct) if raw_acct else None
    last4 = raw_acct[-4:] if len(raw_acct) >= 4 else raw_acct

    sub = VendorSubmission(
        id=sub_id,
        created_at="2026-11-13T12:00:00Z",
        status="submitted",
        legal_name=d["legal_name"],
        trade_name=d.get("trade_name"),
        entity_type=d["entity_type"],
        pan=d.get("pan"),
        gstin=d.get("gstin"),
        cin=d.get("cin"),
        llpin=d.get("llpin"),
        ifsc=d.get("ifsc"),
        bank_account_number=acct_hmac,
        bank_account_number_last4=last4,
        udyam_number=d.get("udyam_number"),
        udyam_category=d.get("udyam_category"),
        udyam_activity_type=d.get("udyam_activity_type"),
        address_line=d.get("address_line"),
        address_state_code=d.get("address_state_code"),
        email=d.get("email"),
        agreed_payment_days=d.get("agreed_payment_days"),
        attempt_no=1,
    )
    db.add(sub)
    db.flush()

    # Attach generated demo documents
    demo_docs = get_demo_documents(scenario_key)
    for doc_type, filename, abs_path in demo_docs:
        with open(abs_path, "rb") as fh:
            sha = hashlib.sha256(fh.read()).hexdigest()
        doc = Document(
            id=str(uuid.uuid4()),
            submission_id=sub_id,
            doc_type=doc_type,
            filename=filename,
            storage_path=abs_path,
            sha256=sha,
            uploaded_at="2026-11-13T12:00:00Z",
        )
        db.add(doc)

    db.commit()
    db.close()

    # Run the pipeline
    asyncio.run(run_pipeline(sub_id))

    # Verify decision in DB
    db = SessionLocal()
    sub_row = db.query(VendorSubmission).filter(VendorSubmission.id == sub_id).first()
    dec_row = db.query(Decision).filter(Decision.submission_id == sub_id).order_by(Decision.decided_at.desc()).first()

    assert sub_row is not None
    assert dec_row is not None
    assert dec_row.outcome == sc.expected_outcome, (
        f"Scenario '{scenario_key}': Expected outcome '{sc.expected_outcome}', got '{dec_row.outcome}'. "
        f"Hard fails: {dec_row.hard_fail_checks}, Fixables: {dec_row.fixable_checks}, "
        f"Soft risk score: {dec_row.soft_risk_score}"
    )

    # Verify payment term cap days
    if sc.expected_payment_cap is not None:
        assert sub_row.payment_term_cap_days == sc.expected_payment_cap

    # Verify failing checks
    if sc.expected_failing_checks:
        checks = db.query(CheckResult).filter(CheckResult.submission_id == sub_id).all()
        failing_names = {c.check_name for c in checks if c.status in ("fail", "warn", "missing")}
        for expected_check in sc.expected_failing_checks:
            assert expected_check in failing_names, (
                f"Scenario '{scenario_key}': Expected '{expected_check}' to fail/warn, but failing checks were: {failing_names}"
            )

    # Test resubmission workflow for wrong_cheque_resubmit
    if scenario_key == "wrong_cheque_resubmit":
        assert sub_row.status == "pending"
        # Vendor updates cheque to the correct name and resubmits
        sub_row.attempt_no = 2
        sub_row.status = "submitted"
        # Overwrite cheque document with correct legal name
        cheque_doc = db.query(Document).filter(
            Document.submission_id == sub_id, Document.doc_type == "cancelled_cheque"
        ).first()
        corr_path = str(DEMO_DOCS_DIR / "wrong_cheque_resubmit" / "corrected_cheque.pdf")
        cheque_doc.storage_path = corr_path
        with open(corr_path, "rb") as fh:
            cheque_doc.sha256 = hashlib.sha256(fh.read()).hexdigest()
        db.commit()
        db.close()

        asyncio.run(run_pipeline(sub_id))

        db = SessionLocal()
        sub_resubmit = db.query(VendorSubmission).filter(VendorSubmission.id == sub_id).first()
        dec_resubmit = db.query(Decision).filter(Decision.submission_id == sub_id).order_by(Decision.decided_at.desc()).first()
        assert sub_resubmit.status == "approved"
        assert dec_resubmit.outcome == "approved"

    db.close()
