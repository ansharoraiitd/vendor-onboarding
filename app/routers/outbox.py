"""
Outbox router — list emails and manual resend.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Outbox
from app.templates import templates

router = APIRouter()


@router.get("/outbox", response_class=HTMLResponse)
async def outbox_page(request: Request, db: Session = Depends(get_db)):
    rows = db.query(Outbox).order_by(Outbox.queued_at.desc()).all()
    return templates.TemplateResponse(
        request=request,
        name="outbox.html",
        context={"rows": rows},
    )


@router.get("/api/outbox")
async def list_outbox(db: Session = Depends(get_db)):
    rows = db.query(Outbox).order_by(Outbox.queued_at.desc()).all()
    return [
        {
            "id": r.id,
            "submission_id": r.submission_id,
            "recipient": r.recipient,
            "template": r.template,
            "subject": r.subject,
            "status": r.status,
            "queued_at": r.queued_at,
            "sent_at": r.sent_at,
            "error": r.error,
        }
        for r in rows
    ]


@router.post("/outbox/{outbox_id}/resend")
async def resend(outbox_id: str, db: Session = Depends(get_db)):
    row = db.query(Outbox).filter(Outbox.id == outbox_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Outbox entry not found")
    row.status = "queued"
    row.error = None
    row.sent_at = None
    db.commit()
    return {"id": outbox_id, "status": "queued"}
