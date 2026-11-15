"""
app/validators/pdf_meta.py — PDF metadata soft-signal checks (M1, M2, M3).

M1: Producer software is Photoshop/Canva/GIMP/etc on a government-issued doc — Soft (+5)
M2: ModDate - CreationDate > config.pdf_moddate_gap_days — Soft (+3)
M3: CreationDate < claimed_issue_date (impossible date) — Soft (+10)
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from app.validators import CheckResult

# Government document types that should NOT be produced by design tools
GOVT_DOC_TYPES = {"gst_certificate", "coi", "llpin_cert", "udyam_cert", "pan_card"}

# Pattern matching suspicious editing tools
EDITING_TOOL_RE = re.compile(
    r"photoshop|canva|gimp|illustrator|corel|libreoffice\s*draw|microsoft\s*word",
    re.IGNORECASE,
)


def _parse_date(date_str: Optional[str]) -> Optional[datetime]:
    """Parse an ISO-8601 date string, returning None if invalid."""
    if not date_str:
        return None
    try:
        # Handle both date-only (YYYY-MM-DD) and full ISO-8601
        if "T" in date_str:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        else:
            dt = datetime.strptime(date_str[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def run_pdf_editing_tool(
    pdf_producer: Optional[str],
    doc_type: str,
    score: float = 5.0,
) -> CheckResult:
    """
    M1 — Flag if a government-issued document was produced by an editing tool.
    Soft (+score, default 5).
    """
    evidence = {
        "pdf_producer": pdf_producer,
        "doc_type": doc_type,
        "is_govt_doc_type": doc_type in GOVT_DOC_TYPES,
    }

    if doc_type not in GOVT_DOC_TYPES:
        return CheckResult(
            check_name="pdf_editing_tool",
            status="pass",
            severity="soft",
            evidence=evidence,
            message=f"Doc type '{doc_type}' is not a government document; signal not applicable.",
        )

    if not pdf_producer:
        return CheckResult(
            check_name="pdf_editing_tool",
            status="pass",
            severity="soft",
            evidence=evidence,
            message="No PDF producer metadata found.",
        )

    if EDITING_TOOL_RE.search(pdf_producer):
        evidence["matched_producer"] = pdf_producer
        return CheckResult(
            check_name="pdf_editing_tool",
            status="warn",
            severity="soft",
            score_contribution=score,
            evidence=evidence,
            message=(
                f"Government document '{doc_type}' appears to have been produced by "
                f"an editing tool: '{pdf_producer}'."
            ),
        )

    return CheckResult(
        check_name="pdf_editing_tool",
        status="pass",
        severity="soft",
        evidence=evidence,
        message=f"PDF producer '{pdf_producer}' is not a flagged editing tool.",
    )


def run_pdf_moddate_gap(
    pdf_creation_date: Optional[str],
    pdf_mod_date: Optional[str],
    gap_days: int = 30,
    score: float = 3.0,
) -> CheckResult:
    """
    M2 — Flag if ModDate - CreationDate > gap_days.
    Soft (+score, default 3).
    """
    evidence = {
        "pdf_creation_date": pdf_creation_date,
        "pdf_mod_date": pdf_mod_date,
        "gap_days_threshold": gap_days,
    }

    creation = _parse_date(pdf_creation_date)
    mod = _parse_date(pdf_mod_date)

    if creation is None or mod is None:
        return CheckResult(
            check_name="pdf_moddate_gap",
            status="pass",
            severity="soft",
            evidence=evidence,
            message="Cannot compute ModDate gap: one or both dates are missing or invalid.",
        )

    delta_days = (mod - creation).days
    evidence["delta_days"] = delta_days

    if delta_days > gap_days:
        return CheckResult(
            check_name="pdf_moddate_gap",
            status="warn",
            severity="soft",
            score_contribution=score,
            evidence=evidence,
            message=(
                f"PDF ModDate is {delta_days} days after CreationDate "
                f"(threshold: {gap_days} days). Document may have been re-saved."
            ),
        )

    return CheckResult(
        check_name="pdf_moddate_gap",
        status="pass",
        severity="soft",
        evidence=evidence,
        message=f"PDF ModDate gap ({delta_days} days) is within threshold ({gap_days} days).",
    )


def run_pdf_impossible_creation_date(
    pdf_creation_date: Optional[str],
    claimed_issue_date: Optional[str],
    score: float = 10.0,
) -> CheckResult:
    """
    M3 — Flag if CreationDate < claimed_issue_date (impossible: PDF created before the
    government issued the certificate).
    Soft (+score, default 10).
    """
    evidence = {
        "pdf_creation_date": pdf_creation_date,
        "claimed_issue_date": claimed_issue_date,
    }

    creation = _parse_date(pdf_creation_date)
    claimed = _parse_date(claimed_issue_date)

    if creation is None or claimed is None:
        return CheckResult(
            check_name="pdf_impossible_creation_date",
            status="pass",
            severity="soft",
            evidence=evidence,
            message="Cannot check impossible date: one or both dates are missing or invalid.",
        )

    if creation < claimed:
        return CheckResult(
            check_name="pdf_impossible_creation_date",
            status="warn",
            severity="soft",
            score_contribution=score,
            evidence=evidence,
            message=(
                f"PDF CreationDate ({pdf_creation_date}) predates claimed issue date "
                f"({claimed_issue_date}). This is logically impossible for a genuine document."
            ),
        )

    return CheckResult(
        check_name="pdf_impossible_creation_date",
        status="pass",
        severity="soft",
        evidence=evidence,
        message=(
            f"PDF CreationDate ({pdf_creation_date}) is not before claimed issue date "
            f"({claimed_issue_date})."
        ),
    )
