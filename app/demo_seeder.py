"""
app/demo_seeder.py — Idempotent seeder for initial baseline vendor state and scenarios.
Runs on EVERY startup to support ephemeral container filesystems (e.g. Render free tier).
"""
from __future__ import annotations

import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy.orm import Session

from app.audit_chain import append_audit_entry
from app.demo_scenarios import (
    DEMO_SCENARIOS,
    SEED_EXISTING_APPROVED_ACCOUNT,
    generate_scenario_pdfs,
    get_demo_documents,
)
from app.models import Decision, Document, VendorSubmission
from app.security import compute_bank_account_hmac

SEED_VENDOR_ID = "seed-vendor-001"
SEED_DECISION_ID = "seed-dec-001"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def seed_demo_data(db: Session) -> bool:
    """
    Idempotent baseline seeder:
    1. Ensures demo scenario PDFs are generated.
    2. Seeds existing approved vendor holding SEED_EXISTING_APPROVED_ACCOUNT with a real approved
       Decision and matching audit-chain entries.
    3. Safe to call on every startup; checks for existing record before inserting.
    """
    generate_scenario_pdfs()

    # Check if baseline approved vendor is already present
    existing_hmac = compute_bank_account_hmac(SEED_EXISTING_APPROVED_ACCOUNT)
    existing = (
        db.query(VendorSubmission)
        .filter(
            (VendorSubmission.id == SEED_VENDOR_ID)
            | (VendorSubmission.bank_account_number == existing_hmac)
        )
        .first()
    )

    if existing:
        return False  # Already seeded

    created_time = _now_iso()

    # 1. Seed baseline approved vendor
    seeded_vendor = VendorSubmission(
        id=SEED_VENDOR_ID,
        created_at=created_time,
        status="approved",
        legal_name="Acme Manufacturing Pvt Ltd",
        trade_name="Acme",
        entity_type="pvt_ltd",
        pan="AABCU9603R",
        gstin="27AABCU9603R1ZP",
        cin="U65110MH2000GOI018559",
        ifsc="SBIN0000300",
        bank_account_number=existing_hmac,
        bank_account_number_last4=SEED_EXISTING_APPROVED_ACCOUNT[-4:],
        udyam_number="UDYAM-MH-00-0012345",
        udyam_category="small",
        udyam_activity_type="manufacturing",
        address_line="123 Industrial Estate, Andheri East, Mumbai",
        address_state_code="27",
        email="vendor@acme.example.com",
        payment_term_cap_days=45,
        attempt_no=1,
    )
    db.add(seeded_vendor)

    # 2. Real approved Decision record
    decision = Decision(
        id=SEED_DECISION_ID,
        submission_id=SEED_VENDOR_ID,
        outcome="approved",
        soft_risk_score=0.0,
        hard_fail_checks=json.dumps([]),
        fixable_checks=json.dumps([]),
        decided_at=created_time,
        decided_by="system",
    )
    db.add(decision)
    db.commit()

    # 3. Matching audit chain entries
    append_audit_entry(
        db,
        submission_id=SEED_VENDOR_ID,
        event_type="submission_created",
        payload={
            "legal_name": "Acme Manufacturing Pvt Ltd",
            "pan": "AABCU9603R",
            "entity_type": "pvt_ltd",
        },
    )
    append_audit_entry(
        db,
        submission_id=SEED_VENDOR_ID,
        event_type="decision_made",
        payload={
            "outcome": "approved",
            "soft_risk_score": 0.0,
            "payment_term_cap_days": 45,
        },
    )

    return True


def reset_and_seed_demo(db: Session) -> None:
    """
    Completely resets database tables and runs idempotent seeder.
    Available for demo reset in UI.
    """
    from app.database import engine
    from app.models import Base

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    seed_demo_data(db)
