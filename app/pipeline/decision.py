"""
Decision engine — pure deterministic function.

decide(check_results, soft_risk_score, config) -> DecisionOutput

Precedence (§4.1, with user clarification 2026-11-13):
  hard → escalate (attached to memo) → fixable → soft_score >= threshold → approved

If BOTH hard fails and escalate checks fire:
  outcome = rejected (hard wins)
  escalate_checks attached to DecisionOutput for reviewer memo display.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List

from app.validators import CheckResult


@dataclass
class DecisionOutput:
    outcome: str                              # approved/pending/rejected/human_review
    reason: str = ""                          # machine-readable reason code
    hard_fail_checks: List[str] = field(default_factory=list)
    fixable_checks: List[str] = field(default_factory=list)
    escalate_checks: List[str] = field(default_factory=list)   # always populated if any escalate checks fired
    soft_risk_score: float = 0.0
    human_review_threshold: float = 20.0


def _accumulate_risk(check_results: List[CheckResult]) -> float:
    """Sum score_contribution for all soft checks that fired."""
    total = 0.0
    for r in check_results:
        if r.severity == "soft" and r.status in ("fail", "warn"):
            total += r.score_contribution or 0.0
    return min(total, 100.0)


def decide(
    check_results: List[CheckResult],
    config: Any,                     # app.config.Config
    soft_risk_score: float = -1.0,   # pass -1 to auto-compute from check_results
) -> DecisionOutput:
    """
    Apply the §4.1 precedence ladder and return a DecisionOutput.

    Precedence: hard fails → escalate (human_review) → fixable → soft_score → approved.
    Special case: if BOTH hard fails AND escalate checks fire, outcome = rejected
    (hard wins) but escalate_checks is populated so the memo can flag them.

    The confidence gate is applied upstream (in rule_engine); by the time
    we receive check_results, severities are already downgraded where needed.
    """
    if soft_risk_score < 0:
        soft_risk_score = _accumulate_risk(check_results)

    threshold = getattr(
        getattr(config, "decision", None), "human_review_threshold", 20.0
    )
    if threshold is None:
        threshold = 20.0

    # Collect all escalate checks upfront (always attach to output for memo)
    escalate = [
        r for r in check_results
        if r.severity == "escalate" and r.status in ("fail", "warn")
    ]
    escalate_names = [r.check_name for r in escalate]

    # ------------------------------------------------------------------ #
    # Tier 1: Hard fails → rejected (highest priority per user clarification)
    # ------------------------------------------------------------------ #
    hard_fails = [
        r for r in check_results
        if r.severity == "hard" and r.status == "fail"
    ]
    if hard_fails:
        return DecisionOutput(
            outcome="rejected",
            reason="hard_fail",
            hard_fail_checks=[r.check_name for r in hard_fails],
            escalate_checks=escalate_names,   # attach for memo review even on rejected
            soft_risk_score=soft_risk_score,
            human_review_threshold=threshold,
        )

    # ------------------------------------------------------------------ #
    # Tier 2: Escalate → human_review (only if no hard fails)
    # ------------------------------------------------------------------ #
    if escalate:
        return DecisionOutput(
            outcome="human_review",
            reason="escalate",
            escalate_checks=escalate_names,
            soft_risk_score=soft_risk_score,
            human_review_threshold=threshold,
        )

    # ------------------------------------------------------------------ #
    # Tier 3: Fixable issues → pending
    # ------------------------------------------------------------------ #
    fixable = [
        r for r in check_results
        if r.severity == "fixable" and r.status in ("fail", "missing")
    ]
    if fixable:
        return DecisionOutput(
            outcome="pending",
            reason="fixable",
            fixable_checks=[r.check_name for r in fixable],
            soft_risk_score=soft_risk_score,
            human_review_threshold=threshold,
        )

    # ------------------------------------------------------------------ #
    # Tier 4: Soft risk score above threshold → human review
    # ------------------------------------------------------------------ #
    if soft_risk_score >= threshold:
        return DecisionOutput(
            outcome="human_review",
            reason="soft_score",
            soft_risk_score=soft_risk_score,
            human_review_threshold=threshold,
        )

    # ------------------------------------------------------------------ #
    # Tier 5: Approved
    # ------------------------------------------------------------------ #
    return DecisionOutput(
        outcome="approved",
        reason="all_clear",
        soft_risk_score=soft_risk_score,
        human_review_threshold=threshold,
    )
