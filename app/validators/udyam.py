"""
app/validators/udyam.py — Udyam certificate checks (U1, U4).

U1: Format regex — Fixable (non-mandatory; if supplied must be valid)
U4: Payment term cap logic — Soft (informational)
"""
from __future__ import annotations

import re
from typing import Optional

from app.validators import CheckResult

# UDYAM format: UDYAM-[A-Z]{2}-\d{2}-\d{7}  e.g. UDYAM-MH-00-0012345
UDYAM_FORMAT_RE = re.compile(r"^UDYAM-[A-Z]{2}-\d{2}-\d{7}$")

# Valid category values
VALID_CATEGORIES = {"micro", "small", "medium"}

# Valid activity types
VALID_ACTIVITY_TYPES = {"manufacturing", "services", "trading"}


def run_udyam_format(udyam_number: str) -> CheckResult:
    """U1 — Validate Udyam format. Fixable if invalid (non-mandatory field)."""
    udyam_number = (udyam_number or "").strip().upper()
    match = bool(UDYAM_FORMAT_RE.match(udyam_number))
    if match:
        return CheckResult(
            check_name="udyam_format",
            status="pass",
            severity="fixable",
            evidence={"udyam_number": udyam_number, "regex": UDYAM_FORMAT_RE.pattern},
            message="Udyam registration number format is valid.",
        )
    return CheckResult(
        check_name="udyam_format",
        status="fail",
        severity="fixable",
        evidence={"udyam_number": udyam_number, "regex": UDYAM_FORMAT_RE.pattern},
        message="Udyam registration number format is invalid.",
    )


def run_udyam_category(category: Optional[str]) -> CheckResult:
    """U2 — Validate that udyam_category is one of micro/small/medium. Fixable if not."""
    category = (category or "").strip().lower()
    evidence = {"udyam_category": category, "valid_categories": sorted(VALID_CATEGORIES)}
    if category in VALID_CATEGORIES:
        return CheckResult(
            check_name="udyam_category",
            status="pass",
            severity="fixable",
            evidence=evidence,
            message=f"Udyam category '{category}' is valid.",
        )
    return CheckResult(
        check_name="udyam_category",
        status="fail",
        severity="fixable",
        evidence=evidence,
        message=f"Udyam category '{category}' is invalid or unreadable.",
    )


def run_udyam_activity_type(activity_type: Optional[str]) -> CheckResult:
    """U3 — Validate that udyam_activity_type is one of manufacturing/services/trading. Fixable."""
    activity_type = (activity_type or "").strip().lower()
    evidence = {
        "udyam_activity_type": activity_type,
        "valid_activity_types": sorted(VALID_ACTIVITY_TYPES),
    }
    if activity_type in VALID_ACTIVITY_TYPES:
        return CheckResult(
            check_name="udyam_activity_type",
            status="pass",
            severity="fixable",
            evidence=evidence,
            message=f"Udyam activity type '{activity_type}' is valid.",
        )
    return CheckResult(
        check_name="udyam_activity_type",
        status="fail",
        severity="fixable",
        evidence=evidence,
        message=f"Udyam activity type '{activity_type}' is invalid or unreadable.",
    )


def compute_payment_term_cap(
    category: Optional[str],
    activity_type: Optional[str],
    written_agreement: bool = False,
    agreed_days: Optional[int] = None,
) -> Optional[int]:
    """
    Compute payment_term_cap_days per MSMED Act 2006 / IT Act 2025 §37(2)(g).

    Rules:
    - Only micro or small + activity_type != trading → cap applies
    - written_agreement=True: cap = min(agreed_days, 45)
    - written_agreement=False: cap = 15
    - medium → None
    - trading → None
    - no Udyam → None
    """
    if not category or not activity_type:
        return None
    category = category.strip().lower()
    activity_type = activity_type.strip().lower()

    if category == "medium":
        return None
    if activity_type == "trading":
        return None
    if category not in {"micro", "small"}:
        return None

    # micro or small, non-trading
    if written_agreement and agreed_days is not None:
        return min(agreed_days, 45)
    return 15  # MSMED Act default: 15 days from day of acceptance


def run_payment_term_cap(
    category: Optional[str],
    activity_type: Optional[str],
    written_agreement: bool = False,
    agreed_days: Optional[int] = None,
) -> CheckResult:
    """
    U4 — Compute and report payment term cap. Soft / informational; +0 risk.
    """
    cap = compute_payment_term_cap(category, activity_type, written_agreement, agreed_days)
    evidence = {
        "udyam_category": category,
        "udyam_activity_type": activity_type,
        "written_agreement": written_agreement,
        "agreed_days": agreed_days,
        "payment_term_cap_days": cap,
    }

    return CheckResult(
        check_name="payment_term_cap",
        status="pass",
        severity="soft",
        score_contribution=0.0,
        evidence=evidence,
        message=(
            f"Payment term cap: {cap} days."
            if cap is not None
            else "No payment term cap applies."
        ),
    )
