"""
app/routers/audit.py — Audit Log and Hash Chain Verification Router (SPEC §6).
"""
from __future__ import annotations

import os
from typing import Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.audit_chain import append_audit_entry, demo_tamper_entry, verify_audit_chain
from app.database import get_db
from app.models import AuditEntry
from app.templates import templates

router = APIRouter()


@router.get("/audit", response_class=HTMLResponse)
async def audit_page(
    request: Request,
    limit: int = Query(50, ge=1, le=500),
    submission_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    query = db.query(AuditEntry)
    if submission_id:
        query = query.filter(AuditEntry.submission_id == submission_id)
    entries = query.order_by(AuditEntry.seq.desc()).limit(limit).all()

    verification = verify_audit_chain(db)
    demo_mode = os.getenv("DEMO_MODE", "true").lower() in ("true", "1", "yes")

    return templates.TemplateResponse(
        request=request,
        name="audit.html",
        context={
            "entries": entries,
            "verification": verification,
            "demo_mode": demo_mode,
            "submission_id": submission_id,
            "limit": limit,
        },
    )


@router.post("/audit/verify")
async def verify_chain(db: Session = Depends(get_db)):
    verification = verify_audit_chain(db)
    # Log verification event into audit chain itself
    try:
        append_audit_entry(
            db=db,
            submission_id=None,
            event_type="chain_verified",
            payload={
                "valid": verification["valid"],
                "total_entries": verification["total_entries"],
            },
        )
    except Exception:
        pass
    return RedirectResponse(url="/audit", status_code=303)


@router.post("/audit/tamper")
async def tamper_entry(
    seq: Optional[int] = Form(None),
    db: Session = Depends(get_db),
):
    demo_mode = os.getenv("DEMO_MODE", "true").lower() in ("true", "1", "yes")
    if not demo_mode:
        raise HTTPException(status_code=403, detail="Demo tamper disabled outside DEMO_MODE.")

    demo_tamper_entry(db, seq=seq)
    return RedirectResponse(url="/audit", status_code=303)


# --- JSON API Endpoints (§6.2 / §6.3) ---

@router.get("/api/audit")
async def api_list_audit(
    limit: int = Query(50, ge=1, le=500),
    submission_id: Optional[str] = None,
    db: Session = Depends(get_db),
):
    query = db.query(AuditEntry)
    if submission_id:
        query = query.filter(AuditEntry.submission_id == submission_id)
    entries = query.order_by(AuditEntry.seq.desc()).limit(limit).all()
    return [
        {
            "id": e.id,
            "seq": e.seq,
            "submission_id": e.submission_id,
            "event_type": e.event_type,
            "payload": e.payload,
            "prev_hash": e.prev_hash,
            "entry_hash": e.entry_hash,
            "current_hash": e.current_hash,
            "created_at": e.created_at,
        }
        for e in entries
    ]


@router.get("/api/audit/verify")
async def api_verify_audit(db: Session = Depends(get_db)):
    res = verify_audit_chain(db)
    return res


@router.post("/api/audit/demo-tamper")
async def api_demo_tamper(
    seq: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    demo_mode = os.getenv("DEMO_MODE", "true").lower() in ("true", "1", "yes")
    if not demo_mode:
        raise HTTPException(status_code=403, detail="Demo tamper disabled outside DEMO_MODE.")
    try:
        res = demo_tamper_entry(db, seq=seq)
        return res
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
