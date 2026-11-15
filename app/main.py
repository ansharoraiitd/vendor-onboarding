"""
FastAPI application entry point.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root at startup
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.database import SessionLocal, engine
from app.demo_seeder import reset_and_seed_demo, seed_demo_data
from app.models import Base
from app.pipeline.extractor import (
    DISK_CACHE_DIR,
    get_extractor_mode,
    is_ai_extraction_enabled,
    is_circuit_breaker_tripped,
)
from app.routers import audit, dashboard, eval, outbox, run, submissions


@asynccontextmanager
async def lifespan(app: FastAPI):
    # If seed_cache exists in container and extraction cache is empty, populate it
    seed_cache = Path("/app/seed_cache")
    if seed_cache.exists():
        DISK_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            if not any(DISK_CACHE_DIR.iterdir()):
                for item in seed_cache.glob("*"):
                    if item.is_file():
                        shutil.copy2(item, DISK_CACHE_DIR / item.name)
        except Exception:
            pass

    # Create all tables and seed baseline demo state on every startup (idempotent)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_demo_data(db)
    finally:
        db.close()
    yield


app = FastAPI(
    title="Vendor Onboarding Automation",
    description="Indian market vendor onboarding with deterministic rule engine",
    version="0.4.0",
    lifespan=lifespan,
)


@app.get("/health")
def health_check():
    """Health check endpoint for deployment orchestration (e.g. Render / Docker)."""
    cb_tripped, cb_reason = is_circuit_breaker_tripped()
    return {
        "status": "healthy",
        "database": "connected",
        "extractor_mode": get_extractor_mode(),
        "ai_extraction_enabled": is_ai_extraction_enabled(),
        "circuit_breaker_tripped": cb_tripped,
        "circuit_breaker_reason": cb_reason if cb_tripped else None,
        "demo_mode": True,
    }


# Static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Add custom Jinja2 filter for JSON parsing in templates
_templates = Jinja2Templates(directory="templates")
_templates.env.filters["from_json"] = json.loads

# Routers
app.include_router(dashboard.router)
app.include_router(submissions.router)
app.include_router(run.router)
app.include_router(outbox.router)
app.include_router(eval.router)
app.include_router(audit.router)
