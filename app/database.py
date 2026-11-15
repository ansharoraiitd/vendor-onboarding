"""
app/database.py — SQLite engine + session factory.
Exports `engine`, `SessionLocal`, and `get_db` for FastAPI dependency injection.
"""
from __future__ import annotations

import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

DATA_DIR = Path(os.getenv("DATA_DIR", "."))
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    db_path = Path(os.getenv("DB_PATH", DATA_DIR / "vendor_onboarding.db"))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    DATABASE_URL = f"sqlite:///{db_path.resolve()}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """FastAPI dependency — yields a DB session and closes it after the request."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables (idempotent). Called by main.py at startup."""
    from app.models import Base
    Base.metadata.create_all(bind=engine)
