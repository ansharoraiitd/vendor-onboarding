"""
tests/conftest.py — Shared fixtures for the test suite.
"""
from __future__ import annotations

import os
import tempfile

import pytest

from app.config import Config, BankNameMatchConfig, ExtractionConfig, DuplicateDetectionConfig
from app.database import SessionLocal, init_db
from app.models import Base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture(scope="session")
def default_config() -> Config:
    """Return a default Config loaded from the project's policy.yaml."""
    # Try loading from the project root
    policy_path = os.path.join(os.path.dirname(__file__), "..", "policy.yaml")
    from app.config import load_config
    return load_config(policy_path)


@pytest.fixture
def temp_db():
    """Create an in-memory SQLite database for tests."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def bank_name_config():
    """Return a BankNameMatchConfig with default thresholds."""
    return BankNameMatchConfig(
        pass_threshold=90.0,
        review_threshold=75.0,
        fail_score_contribution=10.0,
    )
