"""
tests/test_audit_chain.py — Tests for SPEC §6 Hash-Chained Audit Trail and Tamper Detection.
"""
import json
import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.audit_chain import append_audit_entry, compute_hash, demo_tamper_entry, verify_audit_chain
from app.models import AuditEntry, Base


@pytest.fixture
def test_db(tmp_path):
    db_file = tmp_path / "test_audit.db"
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()


def test_pristine_chain_verification(test_db):
    """Test that a sequence of audit entries produces a valid hash chain from genesis."""
    # 1. Empty chain is valid
    res_empty = verify_audit_chain(test_db)
    assert res_empty["valid"] is True
    assert res_empty["total_entries"] == 0

    # 2. Append multiple entries
    h1 = append_audit_entry(test_db, "sub-001", "submission_created", {"vendor": "Acme Corp"})
    h2 = append_audit_entry(test_db, "sub-001", "extraction_complete", {"docs": 3})
    h3 = append_audit_entry(test_db, "sub-001", "check_run_complete", {"score": 0.0})
    h4 = append_audit_entry(test_db, "sub-001", "decision_made", {"outcome": "approved"})

    # 3. Verify chain
    res = verify_audit_chain(test_db)
    assert res["valid"] is True
    assert res["total_entries"] == 4
    assert res["first_tampered_seq"] is None
    assert res["error"] is None
    assert res["latest_hash"] == h4

    # 4. Verify individual records in DB
    entries = test_db.query(AuditEntry).order_by(AuditEntry.seq.asc()).all()
    assert len(entries) == 4
    assert entries[0].seq == 1
    assert entries[0].prev_hash == "GENESIS"
    assert entries[0].entry_hash == h1

    assert entries[1].seq == 2
    assert entries[1].prev_hash == h1
    assert entries[1].entry_hash == h2

    assert entries[2].seq == 3
    assert entries[2].prev_hash == h2
    assert entries[2].entry_hash == h3

    assert entries[3].seq == 4
    assert entries[3].prev_hash == h3
    assert entries[3].entry_hash == h4


def test_tamper_payload_detected(test_db, monkeypatch):
    """Test that unauthorized modification of a payload in SQLite is immediately detected."""
    monkeypatch.setenv("DEMO_MODE", "true")

    append_audit_entry(test_db, "sub-001", "submission_created", {"amount": 1000})
    append_audit_entry(test_db, "sub-001", "extraction_complete", {"docs": 2})
    append_audit_entry(test_db, "sub-001", "decision_made", {"outcome": "rejected"})

    # Pristine check passes
    assert verify_audit_chain(test_db)["valid"] is True

    # Tamper with seq=2
    tamper_res = demo_tamper_entry(test_db, seq=2)
    assert tamper_res["tampered"] is True
    assert tamper_res["tampered_seq"] == 2

    # Verification must fail and report seq 2
    verify_res = verify_audit_chain(test_db)
    assert verify_res["valid"] is False
    assert verify_res["first_tampered_seq"] == 2
    assert "Tampered entry detected at seq 2" in verify_res["error"]


def test_tamper_prev_hash_detected(test_db):
    """Test that modifying a prev_hash pointer is detected as a broken chain link."""
    append_audit_entry(test_db, "sub-001", "event_1", {"k": 1})
    append_audit_entry(test_db, "sub-001", "event_2", {"k": 2})
    append_audit_entry(test_db, "sub-001", "event_3", {"k": 3})

    # Break link at seq=3
    raw = test_db.get_bind().raw_connection()
    cur = raw.cursor()
    cur.execute("UPDATE audit_entry SET prev_hash = 'FORGED_HASH_1234567890' WHERE seq = 3")
    raw.commit()
    cur.close()
    raw.close()

    # Verification must fail and report broken chain link at seq 3
    verify_res = verify_audit_chain(test_db)
    assert verify_res["valid"] is False
    assert verify_res["first_tampered_seq"] == 3
    assert "Broken chain link at seq 3" in verify_res["error"]


def test_demo_tamper_disabled_outside_demo_mode(test_db, monkeypatch):
    """Test that demo tampering cannot be triggered when DEMO_MODE is false."""
    monkeypatch.setenv("DEMO_MODE", "false")
    append_audit_entry(test_db, "sub-001", "event_1", {"k": 1})

    with pytest.raises(PermissionError):
        demo_tamper_entry(test_db, seq=1)


def test_audit_http_routes():
    """Test /audit page and API endpoints via TestClient."""
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)

    # 1. Page render
    res = client.get("/audit")
    assert res.status_code == 200
    assert "Audit Trail" in res.text
    assert "Verify Hash Chain" in res.text

    # 2. API list
    res_api = client.get("/api/audit")
    assert res_api.status_code == 200
    assert isinstance(res_api.json(), list)

    # 3. API verify
    res_verify = client.get("/api/audit/verify")
    assert res_verify.status_code == 200
    assert "valid" in res_verify.json()

    # 4. Form verify POST
    res_post_verify = client.post("/audit/verify", follow_redirects=True)
    assert res_post_verify.status_code == 200
