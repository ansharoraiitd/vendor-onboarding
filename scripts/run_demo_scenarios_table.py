#!/usr/bin/env python3
"""
scripts/run_demo_scenarios_table.py — Execute all 8 demo scenarios on a fresh DATA_DIR
and print the outcome table.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import sys
import tempfile
import uuid

# Force temporary DATA_DIR
fresh_dir = tempfile.mkdtemp(prefix="fresh_demo_data_")
os.environ["DATA_DIR"] = fresh_dir
db_path = os.path.join(fresh_dir, "vendor_onboarding.db")
os.environ["DB_PATH"] = db_path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.database
from app.demo_scenarios import DEMO_SCENARIOS, get_demo_documents
from app.demo_seeder import seed_demo_data
from app.models import Base, Decision, Document, VendorSubmission
from app.pipeline.orchestrator import run_pipeline
from app.security import compute_bank_account_hmac


async def main():
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    app.database.engine = engine
    app.database.SessionLocal = SessionLocal

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    # 1. Run startup seed
    seeded = seed_demo_data(db)

    print(f"Fresh DATA_DIR: {fresh_dir}")
    print(f"Startup Seed Applied: {seeded}\n")

    results = []
    for sc_key, sc in DEMO_SCENARIOS.items():
        sub_id = f"demo-run-{sc_key}"
        d = sc.data
        raw_acct = str(d.get("bank_account_number") or "")
        acct_hmac = compute_bank_account_hmac(raw_acct) if raw_acct else None
        last4 = raw_acct[-4:] if len(raw_acct) >= 4 else raw_acct

        sub = VendorSubmission(
            id=sub_id,
            created_at="2026-11-15T00:00:00Z",
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
        db.commit()

        # Attach documents
        doc_list = get_demo_documents(sc_key)
        for doc_type, filename, file_path in doc_list:
            if os.path.exists(file_path):
                with open(file_path, "rb") as f:
                    sha = hashlib.sha256(f.read()).hexdigest()
                doc = Document(
                    id=str(uuid.uuid4()),
                    submission_id=sub_id,
                    doc_type=doc_type,
                    filename=filename,
                    storage_path=str(file_path),
                    sha256=sha,
                    uploaded_at="2026-11-15T00:00:00Z",
                )
                db.add(doc)
        db.commit()

        # Run pipeline
        await run_pipeline(sub_id, db=db)

        # Inspect outcome
        dec = db.query(Decision).filter(Decision.submission_id == sub_id).first()
        actual = dec.outcome if dec else "no_decision"
        expected = sc.expected_outcome
        match = "PASS" if actual == expected else "FAIL"

        results.append({
            "key": sc_key,
            "name": sc.name,
            "expected": expected,
            "actual": actual,
            "match": match,
            "payment_cap": getattr(sub, "payment_term_cap_days", None),
        })

    # Print markdown table
    print("| Scenario Key | Scenario Name | Expected Outcome | Actual Outcome | Status |")
    print("|--------------|---------------|------------------|----------------|--------|")
    for r in results:
        print(f"| `{r['key']}` | {r['name']} | `{r['expected']}` | `{r['actual']}` | **{r['match']}** |")

    db.close()
    shutil.rmtree(fresh_dir, ignore_errors=True)


if __name__ == "__main__":
    asyncio.run(main())
