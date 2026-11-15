"""
Unit tests for the decision engine (§4.1 and user clarifications).
Precedence: hard -> escalate (attached to memo) -> fixable -> soft_score -> approved.
"""
from __future__ import annotations

import pytest

from app.config import Config
from app.pipeline.decision import decide
from app.validators import CheckResult
from app.check_categories import get_category, unique_categories


@pytest.fixture
def dummy_config():
    class DummyDecision:
        human_review_threshold = 20.0

    class DummyConfig:
        decision = DummyDecision()

    return DummyConfig()


def test_approved_when_all_pass(dummy_config):
    checks = [
        CheckResult("pan_format", "pass", "hard"),
        CheckResult("gstin_format", "pass", "hard"),
    ]
    dec = decide(checks, dummy_config)
    assert dec.outcome == "approved"
    assert dec.reason == "all_clear"


def test_hard_fail_overrides_escalate(dummy_config):
    """If both hard fail and escalate checks fire, outcome is rejected, but escalate checks are attached."""
    checks = [
        CheckResult("gstin_checksum", "fail", "hard"),
        CheckResult("duplicate_pan_gstin", "fail", "escalate"),
    ]
    dec = decide(checks, dummy_config)
    assert dec.outcome == "rejected"
    assert "gstin_checksum" in dec.hard_fail_checks
    assert "duplicate_pan_gstin" in dec.escalate_checks


def test_escalate_triggers_human_review_when_no_hard_fails(dummy_config):
    checks = [
        CheckResult("gstin_checksum", "pass", "hard"),
        CheckResult("duplicate_bank_account", "warn", "escalate"),
    ]
    dec = decide(checks, dummy_config)
    assert dec.outcome == "human_review"
    assert dec.reason == "escalate"
    assert "duplicate_bank_account" in dec.escalate_checks


def test_fixable_triggers_pending(dummy_config):
    checks = [
        CheckResult("gstin_checksum", "pass", "hard"),
        CheckResult("required_docs_present", "missing", "fixable"),
    ]
    dec = decide(checks, dummy_config)
    assert dec.outcome == "pending"
    assert "required_docs_present" in dec.fixable_checks


def test_soft_score_triggers_human_review(dummy_config):
    checks = [
        CheckResult("cin_state_match", "warn", "soft", score_contribution=10.0),
        CheckResult("bank_name_fuzzy_match", "warn", "soft", score_contribution=12.0),
    ]
    dec = decide(checks, dummy_config)
    assert dec.outcome == "human_review"
    assert dec.soft_risk_score == 22.0
    assert dec.reason == "soft_score"


def test_deterministic_email_categories():
    cats = unique_categories(["pan_format", "pan_entity_type_match", "gstin_checksum"])
    assert "Identity number issue" in cats
    assert "Tax registration issue" in cats
    # Deduplication test
    assert len(cats) == 2
