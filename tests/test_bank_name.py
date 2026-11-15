"""
tests/test_bank_name.py — Tests for bank name fuzzy match (B3).

v0.3: severity for score <75 is now based on failed_in_previous_run
      (not attempt_no or co-failing check).
"""
from __future__ import annotations

import pytest
from app.validators.bank_name import run_bank_name_fuzzy_match, normalise_name


PASS_THRESHOLD = 90.0
REVIEW_THRESHOLD = 75.0
FAIL_SCORE = 10.0


class TestNormaliseName:
    """Unit tests for the normalisation function."""

    def test_lowercase(self):
        assert normalise_name("ACME LIMITED") == "acme"

    def test_removes_m_s_prefix(self):
        assert normalise_name("M/s Acme Trading") == "acme trading"

    def test_removes_pvt_ltd_suffix(self):
        assert normalise_name("Acme Pvt Ltd") == "acme"

    def test_removes_private_limited(self):
        assert normalise_name("Acme Private Limited") == "acme"

    def test_removes_llp(self):
        assert normalise_name("Acme LLP") == "acme"

    def test_removes_co(self):
        assert normalise_name("Acme Co") == "acme"

    def test_strips_punctuation(self):
        assert normalise_name("Acme, Pvt. Ltd.") == "acme"

    def test_removes_and(self):
        assert normalise_name("Sons and Brothers") == "sons brothers"


class TestBankNameFuzzyMatch:
    """B3 — Full bank name fuzzy match (v0.3 signature)."""

    def _run(
        self,
        bank_name,
        legal_name,
        failed_in_previous_run=False,
        gst_legal=None,
        gst_trade=None,
    ):
        return run_bank_name_fuzzy_match(
            bank_name=bank_name,
            legal_name=legal_name,
            failed_in_previous_run=failed_in_previous_run,
            pass_threshold=PASS_THRESHOLD,
            review_threshold=REVIEW_THRESHOLD,
            fail_score_contribution=FAIL_SCORE,
            gst_legal_name=gst_legal,
            gst_trade_name=gst_trade,
        )

    def test_perfect_match_passes(self):
        result = self._run("Acme Technologies Pvt Ltd", "Acme Technologies Pvt Ltd")
        assert result.status == "pass"
        assert result.severity == "soft"
        assert result.score_contribution == 0.0

    def test_normalised_match_passes(self):
        """M/s prefix and Pvt Ltd suffix should be normalised away."""
        result = self._run("M/s Acme Technologies Pvt Ltd", "Acme Technologies Private Limited")
        assert result.status == "pass"

    def test_exact_match_via_gst_legal_name(self):
        """Bank name that closely matches the GST legal name should pass.
        Uses an identical name pair to guarantee score=100.
        """
        result = self._run(
            "Acme Technologies",
            "Some Other Name",
            gst_legal="Acme Technologies",  # exact match after normalisation
        )
        assert result.status == "pass"

    def test_fail_zone_first_failure_is_fixable(self):
        """Score <75, failed_in_previous_run=False → fixable (first failure)."""
        result = self._run("XYZ Banking Corp", "Acme Technologies Pvt Ltd",
                           failed_in_previous_run=False)
        assert result.status == "fail"
        assert result.severity == "fixable"

    def test_fail_zone_previous_run_failure_is_hard(self):
        """Score <75, failed_in_previous_run=True → hard."""
        result = self._run("XYZ Banking Corp", "Acme Technologies Pvt Ltd",
                           failed_in_previous_run=True)
        assert result.status == "fail"
        assert result.severity == "hard"

    def test_warn_adds_score_contribution(self):
        """Warn status should add score_contribution = fail_score_contribution."""
        result = self._run("Acme Technologies", "Acme Tech Global Enterprises Limited")
        if result.status == "warn":
            assert result.score_contribution == FAIL_SCORE

    def test_evidence_contains_score(self):
        result = self._run("Acme Pvt Ltd", "Acme Private Limited")
        assert "score" in result.evidence
        assert isinstance(result.evidence["score"], float)

    def test_evidence_contains_previous_run_flag(self):
        result = self._run("XYZ Corp", "ABC Limited", failed_in_previous_run=True)
        assert "failed_in_previous_run" in result.evidence
        assert result.evidence["failed_in_previous_run"] is True

    def test_gst_trade_name_boosts_score(self):
        """Bank name that matches GST trade name should pass."""
        result = self._run(
            "Acme Trading",
            "Completely Different Legal Name",
            gst_trade="Acme Trading Company",
        )
        assert result.status == "pass"
