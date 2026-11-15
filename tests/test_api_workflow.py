"""
tests/test_api_workflow.py — Integration test for MUST-tier endpoints:
submit -> background run -> outbox -> memo -> dashboard.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


def test_dashboard_page(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "Vendor Onboarding" in res.text


def test_submit_page(client):
    res = client.get("/submit")
    assert res.status_code == 200
    assert "New Vendor Submission" in res.text


def test_eval_page(client):
    res = client.get("/eval")
    assert res.status_code == 200
    assert "Rule-engine eval (extraction mocked)" in res.text
    assert "False-Rejection Rate" in res.text
    assert "False-Approval Rate" in res.text


def test_create_submission_and_memo(client):
    sub_data = {
        "legal_name": "Integrated Test Vendor Pvt Ltd",
        "entity_type": "pvt_ltd",
        "pan": "AABCU9603R",
        "gstin": "27AABCU9603R1ZP",
        "cin": "U65110MH2000GOI018559",
        "ifsc": "SBIN0000300",
        "bank_account_number": "123456789012",
        "udyam_number": "UDYAM-MH-00-0012345",
        "udyam_category": "small",
        "udyam_activity_type": "manufacturing",
        "address_state_code": "27",
        "email": "integration@vendor.com",
    }
    res = client.post("/submissions", data=sub_data, follow_redirects=False)
    assert res.status_code == 303
    loc = res.headers["location"]
    sub_id = loc.split("/")[-2]

    # Live run view
    res_run = client.get(f"/submissions/{sub_id}/run")
    assert res_run.status_code == 200
    assert "Live Run" in res_run.text

    # Memo page
    res_memo = client.get(f"/submissions/{sub_id}/memo")
    assert res_memo.status_code == 200
    assert "Integrated Test Vendor Pvt Ltd" in res_memo.text


def test_wrong_cheque_resubmit_ui_flow(client):
    """
    Test §12.8 / requirement:
    wrong cheque -> pending -> corrected cheque -> approved, through the UI route.
    """
    import io
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.pdfgen import canvas
    from app.database import SessionLocal
    from app.models import VendorSubmission, Decision

    # Clean up any prior runs with the same account/vendor
    db = SessionLocal()
    db.query(VendorSubmission).filter(VendorSubmission.legal_name == "Kalyan Engineering Private Limited").delete()
    db.commit()
    db.close()

    # 1. Submit scenario "wrong_cheque_resubmit"
    res = client.post("/submissions", data={"scenario_key": "wrong_cheque_resubmit"}, follow_redirects=False)
    assert res.status_code == 303
    sub_id = res.headers["location"].split("/")[-2]

    # Check attempt 1 outcome
    db = SessionLocal()
    try:
        sub = db.query(VendorSubmission).filter(VendorSubmission.id == sub_id).first()
        assert sub.status == "pending"
        assert sub.attempt_no == 1

        dec1 = db.query(Decision).filter(Decision.submission_id == sub_id).order_by(Decision.decided_at.desc()).first()
        assert dec1 is not None
        assert dec1.outcome == "pending"
        assert "bank_name_fuzzy_match" in (dec1.fixable_checks or "")
    finally:
        db.close()

    # 2. Visit GET /submissions/{id}/resubmit
    res_get = client.get(f"/submissions/{sub_id}/resubmit")
    assert res_get.status_code == 200
    assert "Vendor Resubmission" in res_get.text
    assert "file_cancelled_cheque" in res_get.text
    assert "Cancelled Cheque or Bank Letter" in res_get.text
    assert "Attempt #1" in res_get.text

    # 3. Generate corrected cheque PDF matching legal name and IFSC
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(2 * cm, 26 * cm, "CANCELLED CHEQUE - HDFC BANK")
    c.setFont("Helvetica", 11)
    c.drawString(2 * cm, 24 * cm, "Pay to: Kalyan Engineering Private Limited")
    c.drawString(2 * cm, 22 * cm, "Account Number: XXXX XXXX 1005")
    c.drawString(2 * cm, 20 * cm, "IFSC: HDFC0001234")
    c.save()
    buf.seek(0)
    corrected_pdf_bytes = buf.getvalue()

    from app.demo_scenarios import DEMO_SCENARIOS, DEMO_DOCS_DIR
    sc = DEMO_SCENARIOS["wrong_cheque_resubmit"]

    # 4. POST corrected cheque via the UI route POST /submissions/{id}/resubmit
    corr_path = DEMO_DOCS_DIR / "wrong_cheque_resubmit" / "corrected_cheque.pdf"
    with open(corr_path, "rb") as fh:
        corr_bytes = fh.read()

    res_post = client.post(
        f"/submissions/{sub_id}/resubmit",
        data={
            "legal_name": sc.data["legal_name"],
            "entity_type": sc.data["entity_type"],
            "pan": sc.data["pan"],
            "gstin": sc.data["gstin"],
            "cin": sc.data["cin"],
            "ifsc": sc.data["ifsc"],
            "address_state_code": sc.data["address_state_code"],
        },
        files={
            "file_cancelled_cheque": ("corrected_cheque.pdf", corr_bytes, "application/pdf")
        },
        follow_redirects=False,
    )
    assert res_post.status_code == 303
    assert f"/submissions/{sub_id}/run" in res_post.headers["location"]

    # 5. Verify attempt 2 outcome in DB is now approved
    db = SessionLocal()
    try:
        sub = db.query(VendorSubmission).filter(VendorSubmission.id == sub_id).first()
        assert sub.attempt_no == 2
        assert sub.status == "approved"

        dec2 = db.query(Decision).filter(Decision.submission_id == sub_id).order_by(Decision.decided_at.desc()).first()
        assert dec2 is not None
        assert dec2.outcome == "approved"
    finally:
        db.close()
