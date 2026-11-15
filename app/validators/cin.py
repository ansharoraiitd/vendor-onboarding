"""
app/validators/cin.py — CIN checks (C1–C5; C6 is adapter-backed, not in this module).

CIN format: [UL]\\d{5}[A-Z]{2}\\d{4}[A-Z]{3}\\d{6}

C1: Format regex — Hard
C2: Listing status char — Fixable
C3: State match (alpha chars 7-8) — Soft (+5 risk)
C4: Incorporation year match — Hard
C5: Entity-type code match — Hard
"""
from __future__ import annotations

import re
from typing import Optional

from app.validators import CheckResult

# CIN format (21 chars):
#   [UL]      — position 0: U=unlisted, L=listed
#   \d{5}     — 5-digit NIC industry code (positions 1-5)
#   [A-Z]{2}  — 2-letter state code (positions 6-7)
#   \d{4}     — incorporation year (positions 8-11)
#   [A-Z]{3}  — company type (positions 12-14, e.g. PTC, PLC, NPL)
#   \d{6}     — sequential registration number (positions 15-20)
CIN_FORMAT_RE = re.compile(r"^[UL]\d{5}[A-Z]{2}\d{4}[A-Z]{3}\d{6}$")

# Company type code -> allowed entity_types
CIN_ENTITY_TYPE_MAP: dict[str, set[str]] = {
    "PTC": {"pvt_ltd"},
    "PLC": {"pub_ltd"},
    "NPL": {"section8"},
    "OPC": {"pvt_ltd"},
    # FTC is out of scope for v1
}


def run_cin_format(cin: str) -> CheckResult:
    """C1 — Validate CIN format. Hard-fail if invalid."""
    cin = (cin or "").strip().upper()
    match = bool(CIN_FORMAT_RE.match(cin))
    if match:
        return CheckResult(
            check_name="cin_format",
            status="pass",
            severity="hard",
            evidence={"cin": cin},
            message="CIN format is valid.",
        )
    return CheckResult(
        check_name="cin_format",
        status="fail",
        severity="hard",
        evidence={"cin": cin, "regex": CIN_FORMAT_RE.pattern},
        message="CIN format is invalid.",
    )


def run_cin_listing_status(cin: str, claimed_listed: Optional[bool]) -> CheckResult:
    """
    C2 — CIN char 0: 'U' = unlisted, 'L' = listed.
    If claimed_listed is None, skip the check (pass).
    Fixable on mismatch.
    """
    cin = (cin or "").strip().upper()
    if not CIN_FORMAT_RE.match(cin):
        return CheckResult(
            check_name="cin_listing_status",
            status="fail",
            severity="fixable",
            evidence={"cin": cin},
            message="Cannot check listing status: CIN format is invalid.",
        )

    cin_listed = cin[0] == "L"
    evidence = {
        "cin": cin,
        "cin_listed_char": cin[0],
        "cin_listed": cin_listed,
        "claimed_listed": claimed_listed,
    }

    if claimed_listed is None:
        return CheckResult(
            check_name="cin_listing_status",
            status="pass",
            severity="fixable",
            evidence=evidence,
            message="No claimed listing status provided; skipping listing check.",
        )

    if cin_listed == claimed_listed:
        return CheckResult(
            check_name="cin_listing_status",
            status="pass",
            severity="fixable",
            evidence=evidence,
            message="CIN listing status matches claimed listing status.",
        )

    return CheckResult(
        check_name="cin_listing_status",
        status="fail",
        severity="fixable",
        evidence=evidence,
        message=(
            f"CIN char indicates {'listed' if cin_listed else 'unlisted'}, "
            f"but vendor claims {'listed' if claimed_listed else 'unlisted'}."
        ),
    )


def run_cin_state_match(cin: str, registered_state_code: str) -> CheckResult:
    """
    C3 — CIN chars 6-7 (alpha state code) must match the ROC state.
    Soft (+5 risk). MCA records sometimes reflect historical ROC state.
    """
    cin = (cin or "").strip().upper()
    registered_state_code = (registered_state_code or "").strip().upper()

    if not CIN_FORMAT_RE.match(cin):
        return CheckResult(
            check_name="cin_state_match",
            status="fail",
            severity="soft",
            score_contribution=5.0,
            evidence={"cin": cin},
            message="Cannot check state: CIN format is invalid.",
        )

    cin_state = cin[6:8]
    evidence = {
        "cin": cin,
        "cin_state_code": cin_state,
        "registered_state_code": registered_state_code,
    }

    if cin_state == registered_state_code:
        return CheckResult(
            check_name="cin_state_match",
            status="pass",
            severity="soft",
            evidence=evidence,
            message="CIN state code matches registered address state.",
        )

    return CheckResult(
        check_name="cin_state_match",
        status="warn",
        severity="soft",
        score_contribution=5.0,
        evidence=evidence,
        message=(
            f"CIN state code '{cin_state}' differs from registered state "
            f"'{registered_state_code}' (soft signal)."
        ),
    )


def run_cin_year_match(cin: str, coi_year: int) -> CheckResult:
    """
    C4 — CIN chars 8-11 (incorporation year) must match the COI document year.
    Hard-fail on any mismatch.
    """
    cin = (cin or "").strip().upper()
    if not CIN_FORMAT_RE.match(cin):
        return CheckResult(
            check_name="cin_year_match",
            status="fail",
            severity="hard",
            evidence={"cin": cin, "coi_year": coi_year},
            message="Cannot check year: CIN format is invalid.",
        )

    cin_year = int(cin[8:12])
    evidence = {"cin": cin, "cin_year": cin_year, "coi_year": coi_year}

    if cin_year == coi_year:
        return CheckResult(
            check_name="cin_year_match",
            status="pass",
            severity="hard",
            evidence=evidence,
            message="CIN incorporation year matches COI document year.",
        )

    return CheckResult(
        check_name="cin_year_match",
        status="fail",
        severity="hard",
        evidence=evidence,
        message=f"CIN year {cin_year} does not match COI year {coi_year}.",
    )


def run_cin_entity_type_match(cin: str, entity_type: str) -> CheckResult:
    """
    C5 — CIN chars 12-14 (company type code) must match entity_type.
    Hard-fail on mismatch.
    """
    cin = (cin or "").strip().upper()
    entity_type = (entity_type or "").strip().lower()

    if not CIN_FORMAT_RE.match(cin):
        return CheckResult(
            check_name="cin_entity_type_match",
            status="fail",
            severity="hard",
            evidence={"cin": cin, "entity_type": entity_type},
            message="Cannot check entity type: CIN format is invalid.",
        )

    cin_type_code = cin[12:15]
    allowed_types = CIN_ENTITY_TYPE_MAP.get(cin_type_code, set())
    evidence = {
        "cin": cin,
        "cin_type_code": cin_type_code,
        "entity_type": entity_type,
        "allowed_entity_types": sorted(allowed_types),
    }

    if not allowed_types:
        return CheckResult(
            check_name="cin_entity_type_match",
            status="fail",
            severity="hard",
            evidence=evidence,
            message=f"Unknown CIN company type code '{cin_type_code}'.",
        )

    if entity_type in allowed_types:
        return CheckResult(
            check_name="cin_entity_type_match",
            status="pass",
            severity="hard",
            evidence=evidence,
            message=f"CIN type code '{cin_type_code}' matches entity type '{entity_type}'.",
        )

    return CheckResult(
        check_name="cin_entity_type_match",
        status="fail",
        severity="hard",
        evidence=evidence,
        message=(
            f"CIN type code '{cin_type_code}' (allowed for: {sorted(allowed_types)}) "
            f"does not match entity type '{entity_type}'."
        ),
    )
