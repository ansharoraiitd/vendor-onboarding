"""
app/validators/bank_name.py — Bank name fuzzy match (B3).

Normalises both names and computes token-set ratio via rapidfuzz.
Implements previous-run-based severity logic per v0.3 spec:
  - Hard only if B3 also failed in a PREVIOUS run (prior check_result row
    with check_name='bank_name_fuzzy_match' and status='fail').
  - Drop the co-failing-hard-check clause (removed in v0.3).
"""
from __future__ import annotations

import re
from typing import Optional

from rapidfuzz.fuzz import token_sort_ratio

from app.validators import CheckResult

# Stop and noise tokens to strip during normalisation
BANK_REGISTRY_NOISE_TOKENS: set[str] = {
    "m/s", "pvt", "private", "ltd", "limited", "llp", "co", "company", "and", "&",
    "current", "savings", "account", "ac", "branch", "division",
    "proprietor", "prop", "unit"
}
STOP_TOKENS: set[str] = BANK_REGISTRY_NOISE_TOKENS


def normalise_name(name: str) -> str:
    """
    Lowercase, strip parenthesised text like (India), remove bank/registry noise
    (current, savings, a/c, unit <n>, branch, division, proprietor of, m/s),
    strip punctuation and standard stop tokens.
    Distinctive words (e.g. Trading, Someone, Holdings) are preserved.
    """
    if not name:
        return ""
    name = name.lower().strip()
    # 1. Strip parenthesised text e.g. (India), (Unit 2), (Branch)
    name = re.sub(r"\([^)]*\)", " ", name)
    # 2. Strip compound phrases before word tokenisation
    name = re.sub(r"\bproprietor\s+of\b", " ", name, flags=re.IGNORECASE)
    name = re.sub(r"\bunit\s+\d+\b", " ", name, flags=re.IGNORECASE)
    name = re.sub(r"\bm/s\.?\b", " ", name, flags=re.IGNORECASE)
    name = re.sub(r"\ba/c\.?\b", " ", name, flags=re.IGNORECASE)
    # 3. Strip punctuation
    name = re.sub(r"[^\w\s]", " ", name)
    tokens = [t for t in name.split() if t not in BANK_REGISTRY_NOISE_TOKENS]
    return " ".join(tokens)


def _best_score(bank_name: str, candidates: list[str]) -> float:
    """Return the highest token_sort_ratio between bank_name and any candidate."""
    norm_bank = normalise_name(bank_name)
    best = 0.0
    for candidate in candidates:
        if candidate:
            score = float(token_sort_ratio(norm_bank, normalise_name(candidate)))
            if score > best:
                best = score
    return best


def bank_name_severity(
    score: float,
    failed_in_previous_run: bool,
    pass_threshold: float,
    review_threshold: float,
) -> Optional[str]:
    """
    Return severity string or None (pass).

    None      → pass   (score >= pass_threshold)
    'soft'    → warn   (review_threshold <= score < pass_threshold)
    'hard'    → fail   (score < review_threshold AND failed in a previous run)
    'fixable' → fail   (score < review_threshold AND first failure)
    """
    if score >= pass_threshold:
        return None  # pass
    if score >= review_threshold:
        return "soft"
    # score < review_threshold → fail
    return "hard" if failed_in_previous_run else "fixable"


def run_bank_name_fuzzy_match(
    bank_name: str,
    legal_name: str,
    failed_in_previous_run: bool,
    pass_threshold: float,
    review_threshold: float,
    fail_score_contribution: float,
    gst_legal_name: Optional[str] = None,
    gst_trade_name: Optional[str] = None,
) -> CheckResult:
    """
    B3 — Compare bank account holder name against legal_name (and optionally
    GST legal/trade names). Uses token_set_ratio after normalisation.

    failed_in_previous_run: True if a prior check_result row exists for this
    submission with check_name='bank_name_fuzzy_match' and status='fail'.
    """
    candidates = [legal_name]
    if gst_legal_name:
        candidates.append(gst_legal_name)
    if gst_trade_name:
        candidates.append(gst_trade_name)

    score = _best_score(bank_name, candidates)
    severity = bank_name_severity(
        score,
        failed_in_previous_run,
        pass_threshold,
        review_threshold,
    )

    evidence = {
        "bank_name": bank_name,
        "normalised_bank_name": normalise_name(bank_name),
        "legal_name": legal_name,
        "gst_legal_name": gst_legal_name,
        "gst_trade_name": gst_trade_name,
        "score": score,
        "pass_threshold": pass_threshold,
        "review_threshold": review_threshold,
        "failed_in_previous_run": failed_in_previous_run,
    }

    if severity is None:
        return CheckResult(
            check_name="bank_name_fuzzy_match",
            status="pass",
            severity="soft",
            evidence=evidence,
            message=f"Bank name matches with score {score:.1f} (threshold {pass_threshold}).",
        )

    if severity == "soft":
        # Check if bank_name has extra substantive unshared tokens (lookalike entity like 'Trading')
        norm_bank = normalise_name(bank_name)
        bank_tokens = set(norm_bank.split())
        is_lookalike = False
        for cand in candidates:
            if cand:
                cand_tokens = set(normalise_name(cand).split())
                extra = bank_tokens - cand_tokens
                # An extra token is a lookalike if it is not a prefix, suffix, or common abbreviation
                unmatched_extra = [
                    tok for tok in extra
                    if not any(
                        c_tok.startswith(tok)
                        or tok.startswith(c_tok)
                        or (len(tok) >= 3 and len(c_tok) >= 3 and tok[:3] == c_tok[:3])
                        for c_tok in cand_tokens
                    )
                ]
                if unmatched_extra:
                    is_lookalike = True
                    break

        effective_contrib = fail_score_contribution * 2.0 if is_lookalike else fail_score_contribution

        return CheckResult(
            check_name="bank_name_fuzzy_match",
            status="warn",
            severity="soft",
            score_contribution=effective_contrib,
            evidence=evidence,
            message=(
                f"Bank name partial match (score {score:.1f}); "
                f"between review threshold {review_threshold} and pass threshold {pass_threshold}."
                + (" (Potential lookalike entity detected)" if is_lookalike else "")
            ),
        )

    # severity is "hard" or "fixable"
    return CheckResult(
        check_name="bank_name_fuzzy_match",
        status="fail",
        severity=severity,
        evidence=evidence,
        message=(
            f"Bank name mismatch (score {score:.1f} < review threshold {review_threshold}). "
            f"Severity: {severity}."
        ),
    )
