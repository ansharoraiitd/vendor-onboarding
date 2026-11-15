"""
Submissions router — intake, listing, detail, and resubmit.
"""
from __future__ import annotations

import hashlib
import hmac as _hmac_lib
import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.check_categories import get_fixable_label
from app.demo_scenarios import DEMO_SCENARIOS, get_demo_documents
from app.models import CheckResult, Decision, Document, PipelineEvent, VendorSubmission
from app.pipeline.orchestrator import run_pipeline
from app.templates import templates

router = APIRouter()

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


from app.security import compute_bank_account_hmac

_hmac_account = compute_bank_account_hmac


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get("/submit", response_class=HTMLResponse)
async def submit_page(request: Request):
    scenarios_dict = {
        k: {**sc.data, "label": sc.name, "description": sc.description}
        for k, sc in DEMO_SCENARIOS.items()
    }
    return templates.TemplateResponse(
        request=request,
        name="submit.html",
        context={"scenarios": scenarios_dict},
    )


@router.post("/submissions")
async def create_submission(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    legal_name: str = Form(""),
    trade_name: str = Form(""),
    entity_type: str = Form(""),
    pan: str = Form(""),
    gstin: str = Form(""),
    cin: str = Form(""),
    llpin: str = Form(""),
    ifsc: str = Form(""),
    bank_account_number: str = Form(""),
    udyam_number: str = Form(""),
    udyam_category: str = Form(""),
    udyam_activity_type: str = Form(""),
    address_line: str = Form(""),
    address_state_code: str = Form(""),
    email: str = Form(""),
    agreed_payment_days: str = Form(""),
    scenario_key: str = Form(""),
    file_pan_card: Optional[UploadFile] = File(None),
    file_gst_certificate: Optional[UploadFile] = File(None),
    file_cancelled_cheque: Optional[UploadFile] = File(None),
    file_coi: Optional[UploadFile] = File(None),
    file_llpin_cert: Optional[UploadFile] = File(None),
    file_address_proof: Optional[UploadFile] = File(None),
    file_udyam_cert: Optional[UploadFile] = File(None),
    files: List[UploadFile] = File(default=[]),
):
    # Auto-fill from demo scenario if provided
    if scenario_key and scenario_key in DEMO_SCENARIOS:
        sc_data = DEMO_SCENARIOS[scenario_key].data
        if not legal_name:
            legal_name = sc_data.get("legal_name", "")
        if not entity_type:
            entity_type = sc_data.get("entity_type", "pvt_ltd")
        if not trade_name:
            trade_name = sc_data.get("trade_name", "")
        if not pan:
            pan = sc_data.get("pan", "")
        if not gstin:
            gstin = sc_data.get("gstin", "")
        if not cin:
            cin = sc_data.get("cin", "")
        if not llpin:
            llpin = sc_data.get("llpin", "")
        if not ifsc:
            ifsc = sc_data.get("ifsc", "")
        if not bank_account_number:
            bank_account_number = sc_data.get("bank_account_number", "")
        if not udyam_number:
            udyam_number = sc_data.get("udyam_number", "")
        if not udyam_category:
            udyam_category = sc_data.get("udyam_category", "")
        if not udyam_activity_type:
            udyam_activity_type = sc_data.get("udyam_activity_type", "")
        if not address_line:
            address_line = sc_data.get("address_line", "")
        if not address_state_code:
            address_state_code = sc_data.get("address_state_code", "")
        if not email:
            email = sc_data.get("email", "")
        if not agreed_payment_days and "agreed_payment_days" in sc_data and sc_data["agreed_payment_days"] is not None:
            agreed_payment_days = str(sc_data["agreed_payment_days"])
    sub_id = str(uuid.uuid4())
    account_hmac = _hmac_account(bank_account_number) if bank_account_number else ""
    last4 = bank_account_number.strip()[-4:] if len(bank_account_number.strip()) >= 4 else bank_account_number.strip()
    agreed_days_int = int(agreed_payment_days) if agreed_payment_days.strip().isdigit() else None

    submission = VendorSubmission(
        id=sub_id,
        created_at=_now_iso(),
        status="submitted",
        legal_name=legal_name.strip(),
        trade_name=trade_name.strip() or None,
        entity_type=entity_type.strip(),
        pan=pan.strip().upper() or None,
        gstin=gstin.strip().upper() or None,
        cin=cin.strip().upper() or None,
        llpin=llpin.strip().upper() or None,
        ifsc=ifsc.strip().upper() or None,
        bank_account_number=account_hmac or None,
        bank_account_number_last4=last4 or None,
        udyam_number=udyam_number.strip().upper() or None,
        udyam_category=udyam_category.strip().lower() or None,
        udyam_activity_type=udyam_activity_type.strip().lower() or None,
        address_line=address_line.strip() or None,
        address_state_code=address_state_code.strip() or None,
        email=email.strip() or None,
        agreed_payment_days=agreed_days_int,
        attempt_no=1,
        soft_risk_score=0.0,
    )
    db.add(submission)
    db.flush()

    uploaded_any = False
    abs_dir = os.path.join(os.getcwd(), UPLOAD_DIR, sub_id)
    os.makedirs(abs_dir, exist_ok=True)

    # 1. Process slot-based uploads
    slot_uploads = [
        ("pan_card", file_pan_card),
        ("gst_certificate", file_gst_certificate),
        ("cancelled_cheque", file_cancelled_cheque),
        ("coi", file_coi),
        ("llpin_cert", file_llpin_cert),
        ("address_proof", file_address_proof),
        ("udyam_cert", file_udyam_cert),
    ]

    for doc_type, file_obj in slot_uploads:
        if file_obj and file_obj.filename:
            uploaded_any = True
            content = await file_obj.read()
            abs_path = os.path.join(abs_dir, file_obj.filename)
            rel_path = os.path.join(UPLOAD_DIR, sub_id, file_obj.filename)
            with open(abs_path, "wb") as fh:
                fh.write(content)
            sha = hashlib.sha256(content).hexdigest()
            doc = Document(
                id=str(uuid.uuid4()),
                submission_id=sub_id,
                doc_type=doc_type,
                filename=file_obj.filename,
                storage_path=abs_path,
                sha256=sha,
                uploaded_at=_now_iso(),
            )
            db.add(doc)

    # 2. Process legacy generic multi-file uploads if any
    for file in files:
        if not file.filename:
            continue
        uploaded_any = True
        doc_type = _infer_doc_type(file.filename)
        content = await file.read()
        abs_path = os.path.join(abs_dir, file.filename)
        rel_path = os.path.join(UPLOAD_DIR, sub_id, file.filename)
        with open(abs_path, "wb") as fh:
            fh.write(content)
        sha = hashlib.sha256(content).hexdigest()
        doc = Document(
            id=str(uuid.uuid4()),
            submission_id=sub_id,
            doc_type=doc_type,
            filename=file.filename,
            storage_path=abs_path,
            sha256=sha,
            uploaded_at=_now_iso(),
        )
        db.add(doc)

    # 2. If no files were manually uploaded and scenario_key is given, attach scenario's real PDFs
    if not uploaded_any and scenario_key and scenario_key in DEMO_SCENARIOS:
        demo_docs = get_demo_documents(scenario_key)
        for doc_type, filename, src_path in demo_docs:
            dest_path = os.path.join(abs_dir, filename)
            shutil.copyfile(src_path, dest_path)
            with open(dest_path, "rb") as fh:
                sha = hashlib.sha256(fh.read()).hexdigest()
            rel_path = os.path.join(UPLOAD_DIR, sub_id, filename)
            doc = Document(
                id=str(uuid.uuid4()),
                submission_id=sub_id,
                doc_type=doc_type,
                filename=filename,
                storage_path=rel_path,
                sha256=sha,
                uploaded_at=_now_iso(),
            )
            db.add(doc)

    db.commit()
    background_tasks.add_task(run_pipeline, sub_id)
    return RedirectResponse(url=f"/submissions/{sub_id}/run", status_code=303)


def _infer_doc_type(filename: str) -> str:
    name = filename.lower()
    if "pan" in name:
        return "pan_card"
    if "gst" in name or "gstin" in name:
        return "gst_certificate"
    if "cheque" in name or "chq" in name:
        return "cancelled_cheque"
    if "bank" in name and "letter" in name:
        return "bank_letter"
    if "coi" in name or "incorporation" in name:
        return "coi"
    if "llpin" in name:
        return "llpin_cert"
    if "udyam" in name or "msme" in name:
        return "udyam_cert"
    if "address" in name or "proof" in name:
        return "address_proof"
    return "other"


@router.get("/submissions/{sub_id}/run", response_class=HTMLResponse)
async def run_view(request: Request, sub_id: str, db: Session = Depends(get_db)):
    submission = db.query(VendorSubmission).filter(VendorSubmission.id == sub_id).first()
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")
    return templates.TemplateResponse(
        request=request,
        name="run_view.html",
        context={"submission": submission},
    )


@router.get("/api/submissions/{sub_id}")
async def get_submission_api(sub_id: str, db: Session = Depends(get_db)):
    submission = db.query(VendorSubmission).filter(VendorSubmission.id == sub_id).first()
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")
    decision = (
        db.query(Decision)
        .filter(Decision.submission_id == sub_id)
        .order_by(Decision.decided_at.desc())
        .first()
    )
    return {
        "id": submission.id,
        "status": submission.status,
        "legal_name": submission.legal_name,
        "attempt_no": submission.attempt_no,
        "decision": {
            "outcome": decision.outcome,
            "soft_risk_score": decision.soft_risk_score,
            "hard_fail_checks": json.loads(decision.hard_fail_checks or "[]"),
            "fixable_checks": json.loads(decision.fixable_checks or "[]"),
        } if decision else None,
    }


@router.get("/submissions/{sub_id}/memo", response_class=HTMLResponse)
async def memo_view(request: Request, sub_id: str, db: Session = Depends(get_db)):
    submission = db.query(VendorSubmission).filter(VendorSubmission.id == sub_id).first()
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")
    decision = (
        db.query(Decision)
        .filter(Decision.submission_id == sub_id)
        .order_by(Decision.decided_at.desc())
        .first()
    )
    checks = (
        db.query(CheckResult)
        .filter(CheckResult.submission_id == sub_id)
        .order_by(CheckResult.evaluated_at.asc())
        .all()
    )
    checks_data = []
    for c in checks:
        checks_data.append({
            "check_name": c.check_name,
            "status": c.status,
            "severity": c.severity,
            "evidence": c.evidence,
            "score_contribution": c.score_contribution,
            "explanation": c.explanation,
            "evaluated_at": c.evaluated_at,
        })
    return templates.TemplateResponse(
        request=request,
        name="memo.html",
        context={
            "submission": submission,
            "decision": decision,
            "checks": checks_data,
        },
    )


SLOT_CONFIG = {
    "pan_card": {"key": "pan_card", "label": "PAN Card", "field_name": "file_pan_card", "accept": ".pdf,.png,.jpg,.jpeg"},
    "gst_certificate": {"key": "gst_certificate", "label": "GST Registration Certificate", "field_name": "file_gst_certificate", "accept": ".pdf,.png,.jpg,.jpeg"},
    "cancelled_cheque": {"key": "cancelled_cheque", "label": "Cancelled Cheque or Bank Letter", "field_name": "file_cancelled_cheque", "accept": ".pdf,.png,.jpg,.jpeg"},
    "bank_letter": {"key": "cancelled_cheque", "label": "Cancelled Cheque or Bank Letter", "field_name": "file_cancelled_cheque", "accept": ".pdf,.png,.jpg,.jpeg"},
    "coi": {"key": "coi", "label": "Certificate of Incorporation (COI)", "field_name": "file_coi", "accept": ".pdf,.png,.jpg,.jpeg"},
    "llpin_cert": {"key": "llpin_cert", "label": "LLPIN Certificate", "field_name": "file_llpin_cert", "accept": ".pdf,.png,.jpg,.jpeg"},
    "udyam_cert": {"key": "udyam_cert", "label": "Udyam Registration Certificate", "field_name": "file_udyam_cert", "accept": ".pdf,.png,.jpg,.jpeg"},
    "address_proof": {"key": "address_proof", "label": "Address Proof Document", "field_name": "file_address_proof", "accept": ".pdf,.png,.jpg,.jpeg"},
}

CHECK_TO_SLOT = {
    "pan_card_number_match": "pan_card",
    "pan_card_name_match": "pan_card",
    "gst_cert_gstin_match": "gst_certificate",
    "gst_cert_name_match": "gst_certificate",
    "gstin_state_code_match": "gst_certificate",
    "gst_cert_address_vs_proof": "address_proof",
    "b1_bank_account_proof": "cancelled_cheque",
    "bank_name_fuzzy_match": "cancelled_cheque",
    "cheque_ifsc_account_match": "cancelled_cheque",
    "coi_cin_match": "coi",
    "coi_name_match": "coi",
    "cin_year_match": "coi",
    "cin_registered_name_match": "coi",
    "udyam_format": "udyam_cert",
    "udyam_category": "udyam_cert",
    "udyam_activity_type": "udyam_cert",
}


@router.get("/submissions/{sub_id}/resubmit", response_class=HTMLResponse)
async def resubmit_view(request: Request, sub_id: str, db: Session = Depends(get_db)):
    submission = db.query(VendorSubmission).filter(VendorSubmission.id == sub_id).first()
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    latest_decision = (
        db.query(Decision)
        .filter(Decision.submission_id == sub_id)
        .order_by(Decision.decided_at.desc())
        .first()
    )

    fixable_check_names = []
    if latest_decision and latest_decision.fixable_checks:
        try:
            fixable_check_names = json.loads(latest_decision.fixable_checks)
        except Exception:
            pass

    fixable_labels = [get_fixable_label(cn) for cn in fixable_check_names]

    # Determine failing slots
    failing_slot_keys = set()
    for cn in fixable_check_names:
        if cn.startswith("document_type_match_"):
            slot = cn.replace("document_type_match_", "")
            if slot in ("bank_letter", "cancelled_cheque"):
                failing_slot_keys.add("cancelled_cheque")
            elif slot in SLOT_CONFIG:
                failing_slot_keys.add(slot)
        elif cn in CHECK_TO_SLOT:
            failing_slot_keys.add(CHECK_TO_SLOT[cn])
        elif cn == "required_docs_present":
            uploaded_types = {d.doc_type for d in db.query(Document).filter(Document.submission_id == sub_id).all()}
            if submission.entity_type in ("pvt_ltd", "pub_ltd", "section8"):
                for req in ["pan_card", "gst_certificate", "cancelled_cheque", "coi"]:
                    if req not in uploaded_types:
                        failing_slot_keys.add(req)
            elif submission.entity_type == "llp":
                for req in ["pan_card", "gst_certificate", "cancelled_cheque", "llpin_cert"]:
                    if req not in uploaded_types:
                        failing_slot_keys.add(req)
            else:
                for req in ["pan_card", "gst_certificate", "cancelled_cheque"]:
                    if req not in uploaded_types:
                        failing_slot_keys.add(req)

    failing_slots = []
    for k in failing_slot_keys:
        if k in SLOT_CONFIG:
            failing_slots.append(SLOT_CONFIG[k])

    # Reconstruct attempt history
    decisions = (
        db.query(Decision)
        .filter(Decision.submission_id == sub_id)
        .order_by(Decision.decided_at.asc())
        .all()
    )
    attempt_history = []
    for idx, d in enumerate(decisions):
        f_items = []
        if d.fixable_checks:
            try:
                f_names = json.loads(d.fixable_checks)
                f_items = [get_fixable_label(fn) for fn in f_names]
            except Exception:
                pass
        attempt_history.append({
            "attempt_number": idx + 1,
            "decided_at": d.decided_at,
            "outcome": d.outcome,
            "fixable_items": f_items,
        })

    return templates.TemplateResponse(
        request=request,
        name="resubmit.html",
        context={
            "submission": submission,
            "fixable_labels": fixable_labels,
            "failing_slots": failing_slots,
            "attempt_history": attempt_history,
        },
    )


@router.post("/submissions/{sub_id}/resubmit")
async def resubmit_post(
    sub_id: str,
    background_tasks: BackgroundTasks,
    legal_name: Optional[str] = Form(None),
    trade_name: Optional[str] = Form(None),
    entity_type: Optional[str] = Form(None),
    email: Optional[str] = Form(None),
    pan: Optional[str] = Form(None),
    gstin: Optional[str] = Form(None),
    cin: Optional[str] = Form(None),
    ifsc: Optional[str] = Form(None),
    bank_account_number: Optional[str] = Form(None),
    udyam_number: Optional[str] = Form(None),
    udyam_activity_type: Optional[str] = Form(None),
    address_line: Optional[str] = Form(None),
    address_state_code: Optional[str] = Form(None),
    agreed_payment_days: Optional[int] = Form(None),
    file_pan_card: Optional[UploadFile] = File(None),
    file_gst_certificate: Optional[UploadFile] = File(None),
    file_cancelled_cheque: Optional[UploadFile] = File(None),
    file_bank_letter: Optional[UploadFile] = File(None),
    file_coi: Optional[UploadFile] = File(None),
    file_llpin_cert: Optional[UploadFile] = File(None),
    file_udyam_cert: Optional[UploadFile] = File(None),
    file_address_proof: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
):
    submission = db.query(VendorSubmission).filter(VendorSubmission.id == sub_id).first()
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")

    # Update submission fields if provided
    if legal_name is not None:
        submission.legal_name = legal_name
    if trade_name is not None:
        submission.trade_name = trade_name
    if entity_type is not None:
        submission.entity_type = entity_type
    if email is not None:
        submission.email = email
    if pan is not None:
        submission.pan = pan.strip().upper()
    if gstin is not None:
        submission.gstin = gstin.strip().upper()
    if cin is not None:
        submission.cin = cin.strip().upper()
    if ifsc is not None:
        submission.ifsc = ifsc.strip().upper()
    if bank_account_number and bank_account_number.strip():
        clean_acc = bank_account_number.strip()
        submission.bank_account_number = _hmac_account(clean_acc)
        submission.bank_account_number_last4 = clean_acc[-4:]
    if udyam_number is not None:
        submission.udyam_number = udyam_number.strip().upper()
    if udyam_activity_type is not None:
        submission.udyam_activity_type = udyam_activity_type
    if address_line is not None:
        submission.address_line = address_line
    if address_state_code is not None:
        submission.address_state_code = address_state_code.strip()
    if agreed_payment_days is not None:
        submission.agreed_payment_days = agreed_payment_days

    # Process re-uploaded files
    file_map = {
        "pan_card": file_pan_card,
        "gst_certificate": file_gst_certificate,
        "cancelled_cheque": file_cancelled_cheque,
        "bank_letter": file_bank_letter,
        "coi": file_coi,
        "llpin_cert": file_llpin_cert,
        "udyam_cert": file_udyam_cert,
        "address_proof": file_address_proof,
    }

    sub_dir = os.path.join(UPLOAD_DIR, sub_id)
    abs_dir = os.path.abspath(sub_dir)
    os.makedirs(abs_dir, exist_ok=True)

    for doc_type, file_obj in file_map.items():
        if file_obj and file_obj.filename:
            content = await file_obj.read()
            abs_path = os.path.join(abs_dir, file_obj.filename)
            with open(abs_path, "wb") as fh:
                fh.write(content)
            sha = hashlib.sha256(content).hexdigest()

            # Check if document already exists for this doc_type
            existing_doc = (
                db.query(Document)
                .filter(Document.submission_id == sub_id, Document.doc_type == doc_type)
                .first()
            )
            if existing_doc:
                existing_doc.filename = file_obj.filename
                existing_doc.storage_path = abs_path
                existing_doc.sha256 = sha
                existing_doc.uploaded_at = _now_iso()
                existing_doc.extracted_fields = None
                existing_doc.extraction_confidence = None
                existing_doc.doc_type_detected = None
                existing_doc.cached = False
            else:
                new_doc = Document(
                    id=str(uuid.uuid4()),
                    submission_id=sub_id,
                    doc_type=doc_type,
                    filename=file_obj.filename,
                    storage_path=abs_path,
                    sha256=sha,
                    uploaded_at=_now_iso(),
                )
                db.add(new_doc)

    submission.attempt_no = (submission.attempt_no or 1) + 1
    submission.status = "submitted"
    db.commit()

    background_tasks.add_task(run_pipeline, sub_id)
    return RedirectResponse(url=f"/submissions/{sub_id}/run", status_code=303)


@router.patch("/submissions/{sub_id}/resubmit")
async def resubmit(
    sub_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    submission = db.query(VendorSubmission).filter(VendorSubmission.id == sub_id).first()
    if not submission:
        raise HTTPException(status_code=404, detail="Submission not found")
    if submission.status != "pending":
        raise HTTPException(status_code=400, detail="Only pending submissions can be resubmitted")
    submission.attempt_no = (submission.attempt_no or 1) + 1
    submission.status = "submitted"
    db.commit()
    background_tasks.add_task(run_pipeline, sub_id)
    return {"id": sub_id, "attempt_no": submission.attempt_no, "status": "submitted"}
