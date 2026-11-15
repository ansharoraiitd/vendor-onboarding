"""
Dashboard router — submission list with KPIs and filters.
"""
from __future__ import annotations

import os
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.demo_seeder import reset_and_seed_demo
from app.models import VendorSubmission
from app.templates import templates

router = APIRouter()


@router.post("/api/demo/reset")
async def reset_demo(request: Request, db: Session = Depends(get_db)):
    """Reset all submissions and restore baseline demo data (active only when DEMO_MODE=true)."""
    if os.getenv("DEMO_MODE", "true").lower() in ("true", "1", "yes"):
        reset_and_seed_demo(db)
    referer = request.headers.get("referer", "/")
    return RedirectResponse(url=referer, status_code=303)


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    status: str = "",
    entity_type: str = "",
    q: str = "",
):
    query = db.query(VendorSubmission)
    if status:
        query = query.filter(VendorSubmission.status == status)
    if entity_type:
        query = query.filter(VendorSubmission.entity_type == entity_type)
    if q:
        query = query.filter(VendorSubmission.legal_name.ilike(f"%{q}%"))

    rows = query.order_by(VendorSubmission.created_at.desc()).all()

    # KPI calculations
    all_rows = db.query(VendorSubmission).all()
    kpis = {
        "total": len(all_rows),
        "approved": sum(1 for r in all_rows if r.status == "approved"),
        "pending": sum(1 for r in all_rows if r.status == "pending"),
        "rejected": sum(1 for r in all_rows if r.status == "rejected"),
        "human_review": sum(1 for r in all_rows if r.status == "human_review"),
        "avg_risk": (
            round(
                sum(r.soft_risk_score or 0 for r in all_rows) / len(all_rows), 1
            )
            if all_rows
            else 0
        ),
    }

    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "rows": rows,
            "kpis": kpis,
            "filters": {"status": status, "entity_type": entity_type, "q": q},
        },
    )
