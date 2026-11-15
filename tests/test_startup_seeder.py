"""
tests/test_startup_seeder.py — Verification of startup seeder and duplicate bank account detection.

Requirements tested:
1. Fresh empty DATA_DIR + startup seed.
2. Idempotent: repeated calls do not duplicate entries or throw errors.
3. Submitting shared_bank_account scenario -> human_review with duplicate_bank_account flagged.
4. Cryptographic audit chain verification after seeding and submission.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.audit_chain import verify_audit_chain
from app.demo_scenarios import DEMO_SCENARIOS, SEED_EXISTING_APPROVED_ACCOUNT
from app.demo_seeder import SEED_VENDOR_ID, seed_demo_data
from app.models import Base, CheckResult, Decision, Document, VendorSubmission
from app.pipeline.orchestrator import run_pipeline
from app.security import compute_bank_account_hmac


def test_startup_seed_and_shared_bank_account_detection():
    # 1. Fresh empty temporary directory for DATA_DIR and SQLite DB
    temp_dir = tempfile.mkdtemp(prefix="fresh_data_dir_")
    db_file = os.path.join(temp_dir, "fresh_onboarding.db")
    test_db_url = f"sqlite:///{db_file}"

    test_engine = create_engine(test_db_url, connect_args={"check_same_thread": False})
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    # Initialize tables
    Base.metadata.create_all(bind=test_engine)

    try:
        # 2. Run startup seed on fresh empty database
        db = TestingSessionLocal()
        first_seed_result = seed_demo_data(db)
        assert first_seed_result is True, "First seed on fresh database should return True"

        # Verify seeded approved vendor exists
        seeded_vendor = db.query(VendorSubmission).filter(VendorSubmission.id == SEED_VENDOR_ID).first()
        assert seeded_vendor is not None
        assert seeded_vendor.status == "approved"
        assert seeded_vendor.bank_account_number == compute_bank_account_hmac(SEED_EXISTING_APPROVED_ACCOUNT)

        # Verify decision and audit chain
        seed_decision = db.query(Decision).filter(Decision.submission_id == SEED_VENDOR_ID).first()
        assert seed_decision is not None
        assert seed_decision.outcome == "approved"

        res = verify_audit_chain(db)
        assert res["valid"] is True, f"Audit chain verification failed: {res.get('error')}"
        assert res["total_entries"] >= 2, f"Expected at least 2 audit entries, got {res['total_entries']}"

        # 3. Verify Idempotence: running seed again on the same DB returns False and adds no duplicate
        second_seed_result = seed_demo_data(db)
        assert second_seed_result is False, "Second seed call should be idempotent (return False)"
        assert db.query(VendorSubmission).count() == 1

        # 4. Submit shared_bank_account scenario
        scenario = DEMO_SCENARIOS["shared_bank_account"]
        d = scenario.data

        sub_id = "test-shared-bank-sub"
        acct_hmac = compute_bank_account_hmac(d["bank_account_number"])
        sub = VendorSubmission(
            id=sub_id,
            created_at="2026-11-15T00:00:00Z",
            status="submitted",
            legal_name=d["legal_name"],
            entity_type=d["entity_type"],
            pan=d.get("pan"),
            gstin=d.get("gstin"),
            ifsc=d.get("ifsc"),
            bank_account_number=acct_hmac,
            bank_account_number_last4=d["bank_account_number"][-4:],
            address_line=d.get("address_line"),
            address_state_code=d.get("address_state_code"),
            email=d.get("email"),
            attempt_no=1,
        )
        db.add(sub)
        db.commit()

        # Attach scenario documents
        import asyncio
        import hashlib
        import uuid
        from app.demo_scenarios import get_demo_documents
        doc_list = get_demo_documents("shared_bank_account")
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
        asyncio.run(run_pipeline(sub_id, db=db))

        # 5. Assert human_review with duplicate_bank_account flagged
        decision = db.query(Decision).filter(Decision.submission_id == sub_id).first()
        assert decision is not None, "Decision should be created"
        assert decision.outcome == "human_review", (
            f"Expected outcome 'human_review' for shared_bank_account, got {decision.outcome}"
        )

        checks = db.query(CheckResult).filter(CheckResult.submission_id == sub_id).all()
        check_names = {c.check_name: c for c in checks}
        assert "duplicate_bank_account" in check_names, "duplicate_bank_account check must be recorded"
        dup_check = check_names["duplicate_bank_account"]
        assert dup_check.status == "fail"
        assert dup_check.severity in ("escalate", "hard")

        # 6. Verify audit chain remains unbroken
        res_post = verify_audit_chain(db)
        assert res_post["valid"] is True, f"Audit chain verification failed after submission: {res_post.get('error')}"
        db.close()
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
