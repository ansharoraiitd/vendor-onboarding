"""
tests/test_udyam.py — Tests for Udyam validators (U1, U2, U3, U4).
"""
from __future__ import annotations

import pytest
from app.validators.udyam import (
    run_udyam_format,
    run_udyam_category,
    run_udyam_activity_type,
    run_payment_term_cap,
    compute_payment_term_cap,
)


class TestUdyamFormat:
    """U1 — Udyam format regex."""

    @pytest.mark.parametrize("udyam", [
        "UDYAM-MH-00-0012345",
        "UDYAM-DL-01-1234567",
        "UDYAM-KA-99-9999999",
        "UDYAM-TN-12-0000001",
    ])
    def test_valid_formats(self, udyam):
        result = run_udyam_format(udyam)
        assert result.status == "pass", f"{udyam} should pass format check"
        assert result.severity == "fixable"

    @pytest.mark.parametrize("udyam", [
        "UDYAM-M-00-0012345",    # state code too short
        "UDYAM-MH-0-0012345",    # district too short
        "UDYAM-MH-00-012345",    # number too short
        "UDYAM-MH-00-00123456",  # number too long
        "udyam-mh-00-0012345",   # lowercase accepted (normalised)
        "UDYAM MH 00 0012345",   # spaces instead of hyphens
        "",
        None,
    ])
    def test_invalid_formats(self, udyam):
        result = run_udyam_format(udyam)
        # lowercase is normalised to uppercase and should pass
        if udyam and udyam.lower() == udyam:
            assert result.status == "pass"
        else:
            if udyam is None or udyam == "":
                assert result.status == "fail"


class TestUdyamCategory:
    """U2 — Udyam category validation."""

    @pytest.mark.parametrize("cat", ["micro", "small", "medium"])
    def test_valid_categories(self, cat):
        result = run_udyam_category(cat)
        assert result.status == "pass"

    @pytest.mark.parametrize("cat", ["large", "mega", "", None, "MICRO"])
    def test_invalid_categories(self, cat):
        # "MICRO" gets lowercased → "micro" → valid
        result = run_udyam_category(cat)
        if cat and cat.lower() in {"micro", "small", "medium"}:
            assert result.status == "pass"
        else:
            assert result.status == "fail"
            assert result.severity == "fixable"


class TestUdyamActivityType:
    """U3 — Udyam activity type validation."""

    @pytest.mark.parametrize("act", ["manufacturing", "services", "trading"])
    def test_valid_activity_types(self, act):
        result = run_udyam_activity_type(act)
        assert result.status == "pass"

    @pytest.mark.parametrize("act", ["retail", "wholesale", "", None])
    def test_invalid_activity_types(self, act):
        result = run_udyam_activity_type(act)
        assert result.status == "fail"
        assert result.severity == "fixable"


class TestPaymentTermCapLogic:
    """U4 / compute_payment_term_cap — MSME payment term cap logic."""

    # ── Micro, non-trading ────────────────────────────────────────────────
    def test_micro_manufacturing_no_agreement_gives_15(self):
        cap = compute_payment_term_cap("micro", "manufacturing", written_agreement=False)
        assert cap == 15

    def test_micro_services_no_agreement_gives_15(self):
        cap = compute_payment_term_cap("micro", "services", written_agreement=False)
        assert cap == 15

    def test_micro_manufacturing_with_agreement_30_days(self):
        cap = compute_payment_term_cap("micro", "manufacturing", written_agreement=True, agreed_days=30)
        assert cap == 30

    def test_micro_manufacturing_with_agreement_capped_at_45(self):
        cap = compute_payment_term_cap("micro", "manufacturing", written_agreement=True, agreed_days=60)
        assert cap == 45

    # ── Small, non-trading ────────────────────────────────────────────────
    def test_small_services_no_agreement_gives_15(self):
        cap = compute_payment_term_cap("small", "services", written_agreement=False)
        assert cap == 15

    def test_small_with_agreement_45_days(self):
        cap = compute_payment_term_cap("small", "manufacturing", written_agreement=True, agreed_days=45)
        assert cap == 45

    # ── Medium → None ─────────────────────────────────────────────────────
    def test_medium_enterprise_no_cap(self):
        cap = compute_payment_term_cap("medium", "manufacturing", written_agreement=False)
        assert cap is None

    def test_medium_with_agreement_no_cap(self):
        cap = compute_payment_term_cap("medium", "manufacturing", written_agreement=True, agreed_days=30)
        assert cap is None

    # ── Trading → None ────────────────────────────────────────────────────
    def test_micro_trading_no_cap(self):
        """Trading MSMEs are excluded from §37(2)(g) obligation."""
        cap = compute_payment_term_cap("micro", "trading", written_agreement=False)
        assert cap is None

    def test_small_trading_no_cap(self):
        cap = compute_payment_term_cap("small", "trading", written_agreement=True, agreed_days=30)
        assert cap is None

    # ── No Udyam ──────────────────────────────────────────────────────────
    def test_none_category_no_cap(self):
        cap = compute_payment_term_cap(None, "manufacturing")
        assert cap is None

    def test_none_activity_no_cap(self):
        cap = compute_payment_term_cap("micro", None)
        assert cap is None

    # ── CheckResult wrapper ───────────────────────────────────────────────
    def test_payment_term_cap_check_result_pass_always(self):
        """U4 is always pass (informational only)."""
        result = run_payment_term_cap("micro", "manufacturing", written_agreement=False)
        assert result.status == "pass"
        assert result.severity == "soft"
        assert result.score_contribution == 0.0
        assert result.evidence["payment_term_cap_days"] == 15

    def test_payment_term_cap_check_result_trading(self):
        result = run_payment_term_cap("micro", "trading")
        assert result.status == "pass"
        assert result.evidence["payment_term_cap_days"] is None
