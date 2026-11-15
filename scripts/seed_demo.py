#!/usr/bin/env python3
"""
scripts/seed_demo.py

Resets the database and seeds:
1. A GENESIS audit chain entry
2. Several existing "already-approved" vendors (for duplicate-detection scenarios)
3. Pipeline events so the dashboard shows realistic data immediately

Usage:
    cd /Users/ansharora/asa_case_study
    .venv/bin/python3 scripts/seed_demo.py
"""
from __future__ import annotations

import hashlib
import hmac as _hmac_lib
import json
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database import SessionLocal, engine
from app.models import (
    AuditEntry,
    Base,
    CheckResult,
    Decision,
    Outbox,
    PipelineEvent,
    VendorSubmission,
)

from app.security import compute_bank_account_hmac


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_audit(conn, submission_id: str, event_type: str, payload: dict) -> None:
    """Write audit entry with explicit seq computation."""
    cur = conn.cursor()
    try:
        cur.execute("BEGIN IMMEDIATE")
        cur.execute("SELECT entry_hash, seq FROM audit_entry ORDER BY seq DESC LIMIT 1")
        row = cur.fetchone()
        prev_hash = row[0] if row else "GENESIS"
        next_seq = (row[1] + 1) if row else 1
        payload_str = json.dumps(
            {**payload, "submission_id": submission_id, "event_type": event_type},
            sort_keys=True, separators=(",", ":"),
        )
        entry_hash = hashlib.sha256((prev_hash + payload_str).encode()).hexdigest()
        cur.execute(
            "INSERT INTO audit_entry "
            "(id, seq, submission_id, event_type, payload, prev_hash, entry_hash, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), next_seq, submission_id, event_type,
             payload_str, prev_hash, entry_hash, _now()),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()


def reset_and_seed() -> None:
    print("Dropping and recreating all tables...")
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    print("Schema created.")

    db = SessionLocal()
    raw = engine.raw_connection()

    # 1. Genesis audit entry
    _append_audit(raw, "GENESIS", "genesis", {"note": "Chain start sentinel"})
    print("Genesis audit entry written.")

    # 2. Seed approved vendors
    approved_vendors = [
        {
            "legal_name": "Acme Manufacturing Pvt Ltd",
            "trade_name": "Acme",
            "entity_type": "pvt_ltd",
            "pan": "AABCU9603R1",
            "gstin": "27AABCU9603R1ZP",
            "cin": "U65110MH2000GOI018559",
            "ifsc": "SBIN0000300",
            "bank_account_number": "123456781234",
            "udyam_number": "UDYAM-MH-00-0012345",
            "udyam_category": "small",
            "udyam_activity_type": "manufacturing",
            "address_line": "123 Industrial Estate, Andheri East, Mumbai",
            "address_state_code": "27",
            "email": "vendor@acme.example.com",
            "payment_term_cap_days": 45,
            "soft_risk_score": 0.0,
        },
        {
            "legal_name": "Global Supplies LLP",
            "trade_name": "GlobalSupply",
            "entity_type": "llp",
            "pan": "AABCT3518Q",
            "gstin": "19AABCT3518Q1ZP",
            "llpin": "AAA-9999",
            "ifsc": "HDFC0001234",
            "bank_account_number": "987654321234",
            "address_line": "45 Business Park, Kolkata",
            "address_state_code": "19",
            "email": "vendor@globalsupplies.example.com",
            "soft_risk_score": 5.0,
        },
        {
            "legal_name": "Reliance Trading Partnership",
            "entity_type": "partnership",
            "pan": "AAACR5055K",
            "gstin": "07AAACR5055K1ZF",
            "ifsc": "ICIC0002456",
            "bank_account_number": "111122223333",
            "address_line": "Commerce House, Connaught Place, Delhi",
            "address_state_code": "07",
            "email": "vendor@reltrading.example.com",
            "soft_risk_score": 0.0,
        },
    ]

    for v in approved_vendors:
        sub_id = str(uuid.uuid4())
        account = v.pop("bank_account_number")
        last4 = account[-4:]
        sub = VendorSubmission(
            id=sub_id,
            created_at=_now(),
            status="approved",
            legal_name=v.get("legal_name"),
            trade_name=v.get("trade_name"),
            entity_type=v.get("entity_type"),
            pan=v.get("pan"),
            gstin=v.get("gstin"),
            cin=v.get("cin"),
            llpin=v.get("llpin"),
            ifsc=v.get("ifsc"),
            bank_account_number=compute_bank_account_hmac(account),
            bank_account_number_last4=last4,
            udyam_number=v.get("udyam_number"),
            udyam_category=v.get("udyam_category"),
            udyam_activity_type=v.get("udyam_activity_type"),
            address_line=v.get("address_line"),
            address_state_code=v.get("address_state_code"),
            email=v.get("email"),
            soft_risk_score=v.get("soft_risk_score", 0.0),
            payment_term_cap_days=v.get("payment_term_cap_days"),
            attempt_no=1,
        )
        db.add(sub)
        db.flush()

        dec = Decision(
            id=str(uuid.uuid4()),
            submission_id=sub_id,
            outcome="approved",
            hard_fail_checks="[]",
            fixable_checks="[]",
            soft_risk_score=v.get("soft_risk_score", 0.0),
            decided_at=_now(),
            decided_by="system",
            llm_explanation="All validation checks passed.",
        )
        db.add(dec)

        outbox = Outbox(
            id=str(uuid.uuid4()),
            submission_id=sub_id,
            recipient=v.get("email", ""),
            template="approved",
            subject="Your vendor registration has been approved",
            body=(
                f"Dear {v.get('legal_name')},\n\n"
                "We are pleased to inform you that your vendor registration has been approved.\n\n"
                "Regards,\nVendor Onboarding Team"
            ),
            status="sent",
            queued_at=_now(),
            sent_at=_now(),
        )
        db.add(outbox)
        db.commit()

        _append_audit(raw, sub_id, "submission_created", {"legal_name": v.get("legal_name")})
        _append_audit(raw, sub_id, "decision_made", {"outcome": "approved"})
        print(f"  Approved: {v.get('legal_name')} ({sub_id[:8]}...)")

    # 3. One pending vendor
    pending_id = str(uuid.uuid4())
    pending_sub = VendorSubmission(
        id=pending_id,
        created_at=_now(),
        status="pending",
        legal_name="Quick Parts Proprietorship",
        entity_type="proprietorship",
        pan="BBBPP9999Z",
        gstin="27BBBPP9999Z1Z0",
        ifsc="PUNB0123400",
        bank_account_number=compute_bank_account_hmac("444455556666"),
        bank_account_number_last4="6666",
        address_line="10 Workshop Lane, Pune",
        address_state_code="27",
        email="vendor@quickparts.example.com",
        soft_risk_score=0.0,
        attempt_no=1,
    )
    db.add(pending_sub)
    db.flush()
    dec_p = Decision(
        id=str(uuid.uuid4()),
        submission_id=pending_id,
        outcome="pending",
        hard_fail_checks="[]",
        fixable_checks='["pan_status","required_docs_present"]',
        soft_risk_score=0.0,
        decided_at=_now(),
        decided_by="system",
        llm_explanation="Pending: PAN status invalid; PAN card document missing.",
    )
    db.add(dec_p)
    db.commit()
    _append_audit(raw, pending_id, "submission_created", {"legal_name": "Quick Parts"})
    _append_audit(raw, pending_id, "decision_made", {"outcome": "pending"})
    print(f"  Pending: Quick Parts Proprietorship ({pending_id[:8]}...)")

    # 4. One human-review vendor
    hr_id = str(uuid.uuid4())
    hr_sub = VendorSubmission(
        id=hr_id,
        created_at=_now(),
        status="human_review",
        legal_name="Dual Entity Trading Co",
        entity_type="partnership",
        pan="AAACI1289P",
        gstin="24AAACI1289P1ZG",
        ifsc="HDFC0001234",
        bank_account_number=compute_bank_account_hmac("123456781234"),  # same HMAC as first approved vendor -> DV2
        bank_account_number_last4="1234",
        address_line="10 Finance Street, Ahmedabad",
        address_state_code="24",
        email="vendor@dualentity.example.com",
        soft_risk_score=25.0,
        attempt_no=1,
    )
    db.add(hr_sub)
    db.flush()
    dec_hr = Decision(
        id=str(uuid.uuid4()),
        submission_id=hr_id,
        outcome="human_review",
        hard_fail_checks="[]",
        fixable_checks="[]",
        soft_risk_score=25.0,
        decided_at=_now(),
        decided_by="system",
        llm_explanation="Soft risk score (25) exceeded review threshold (20). Manual review required.",
    )
    db.add(dec_hr)
    db.commit()
    _append_audit(raw, hr_id, "submission_created", {"legal_name": "Dual Entity Trading"})
    _append_audit(raw, hr_id, "decision_made", {"outcome": "human_review"})
    print(f"  Human review: Dual Entity Trading Co ({hr_id[:8]}...)")

    db.close()
    raw.close()
    print("\nDatabase seeded. Run the server:")
    print("  cd /Users/ansharora/asa_case_study")
    print("  .venv/bin/uvicorn app.main:app --reload --port 8000")


if __name__ == "__main__":
    reset_and_seed()
