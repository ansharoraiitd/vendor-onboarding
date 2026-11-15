"""
app/validators/pan.py — PAN format and entity-type checks (P1, P2).

P1: Format regex [A-Z]{3}[ABCFGHLJPTK][A-Z]\\d{4}[A-Z]  — Hard
P2: 4th character encodes entity type; must match entity_type field — Hard
"""
from __future__ import annotations

import re
from typing import Optional

from app.validators import CheckResult

# Valid PAN format (10 chars):
#   [A-Z]{3}  — first 3 alpha
#   [ABCFGHLJPTK] — 4th char: entity-type indicator
#   [A-Z]     — 5th char: initial of surname/entity name
#   \d{4}     — 6 through 9: sequential number
#   [A-Z]     — 10th: check letter
PAN_FORMAT_RE = re.compile(r"^[A-Z]{3}[ABCFGHLJPTK][A-Z]\d{4}[A-Z]$")

# Mapping from entity_type to expected set of valid 4th-char codes
PAN_ENTITY_MAP: dict[str, set[str]] = {
    "proprietorship": {"P"},
    "partnership": {"F"},
    "llp": {"F"},
    "pvt_ltd": {"C"},
    "pub_ltd": {"C"},
    "section8": {"C"},
}


def run_pan_format(pan: str) -> CheckResult:
    """
    P1 — Validate PAN format.
    Hard-fail if the format is invalid.
    """
    pan = (pan or "").strip().upper()
    match = bool(PAN_FORMAT_RE.match(pan))
    if match:
        return CheckResult(
            check_name="pan_format",
            status="pass",
            severity="hard",
            evidence={"pan": pan, "regex": PAN_FORMAT_RE.pattern},
            message="PAN format is valid.",
        )
    return CheckResult(
        check_name="pan_format",
        status="fail",
        severity="hard",
        evidence={"pan": pan, "regex": PAN_FORMAT_RE.pattern},
        message="PAN format is invalid.",
    )


def run_pan_entity_type_match(pan: str, entity_type: str) -> CheckResult:
    """
    P2 — 4th character of PAN must encode the correct entity type.
    Hard-fail on mismatch.
    """
    pan = (pan or "").strip().upper()
    entity_type = (entity_type or "").strip().lower()

    # If PAN format is invalid we can't decode the entity char
    if not PAN_FORMAT_RE.match(pan):
        return CheckResult(
            check_name="pan_entity_type_match",
            status="fail",
            severity="hard",
            evidence={"pan": pan, "entity_type": entity_type},
            message="Cannot check entity-type match because PAN format is invalid.",
        )

    pan_char = pan[3]  # 0-indexed position 3 = 4th character
    expected_chars = PAN_ENTITY_MAP.get(entity_type)

    if expected_chars is None:
        return CheckResult(
            check_name="pan_entity_type_match",
            status="fail",
            severity="hard",
            evidence={"pan": pan, "entity_type": entity_type, "pan_char": pan_char},
            message=f"Unknown entity_type '{entity_type}'.",
        )

    if pan_char in expected_chars:
        return CheckResult(
            check_name="pan_entity_type_match",
            status="pass",
            severity="hard",
            evidence={
                "pan": pan,
                "entity_type": entity_type,
                "pan_char": pan_char,
                "expected_chars": sorted(expected_chars),
            },
            message="PAN entity-type character matches declared entity type.",
        )

    return CheckResult(
        check_name="pan_entity_type_match",
        status="fail",
        severity="hard",
        evidence={
            "pan": pan,
            "entity_type": entity_type,
            "pan_char": pan_char,
            "expected_chars": sorted(expected_chars),
        },
        message=(
            f"PAN 4th character '{pan_char}' does not match entity type "
            f"'{entity_type}' (expected one of {sorted(expected_chars)})."
        ),
    )
