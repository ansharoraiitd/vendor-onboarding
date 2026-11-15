"""
app/validators/gstin.py — GSTIN checks (G1, G2, G3, G4).

G1: Format regex (corrected) — Hard
G2: Mod-36 checksum (factors alternate 2,1) — Hard
G3: Embedded PAN match (chars 3-12 == submitted PAN) — Hard
G4: State code match from GST certificate (subject to confidence gate) — Fixable
"""
from __future__ import annotations

import re
from typing import Optional

from app.validators import CheckResult

# GSTIN format (15 chars):
#   \d{2}             — 2-digit state code
#   [A-Z]{3}          — first 3 chars of PAN
#   [ABCFGHLJPTK]     — 4th char of PAN (entity type)
#   [A-Z]             — 5th char of PAN
#   \d{4}             — PAN sequential digits
#   [A-Z]             — PAN check letter (10th char of PAN)
#   [1-9A-Z]          — registration number within state (NOT \d — corrected)
#   [Z]               — always Z
#   [A-Z0-9]          — checksum character
GSTIN_FORMAT_RE = re.compile(
    r"^\d{2}[A-Z]{3}[ABCFGHLJPTK][A-Z]\d{4}[A-Z][1-9A-Z][Z][A-Z0-9]$"
)

# Value map for mod-36 checksum
_VALUE_MAP: dict[str, int] = {str(i): i for i in range(10)}
_VALUE_MAP.update({chr(65 + i): 10 + i for i in range(26)})  # A=10 … Z=35
_REVERSE_VALUE_MAP: dict[int, str] = {v: k for k, v in _VALUE_MAP.items()}


def _compute_gstin_checksum(gstin_14: str) -> str:
    """Given first 14 chars of a GSTIN, return expected 15th char (checksum)."""
    total = 0
    factor = 2
    for char in gstin_14:  # left-to-right; factor starts at 2 and alternates 2→1→2→…
        v = _VALUE_MAP[char] * factor
        total += (v // 36) + (v % 36)
        factor = 1 if factor == 2 else 2  # alternates 2, 1 — NOT 2, 3
    check = (36 - (total % 36)) % 36
    return _REVERSE_VALUE_MAP[check]


def run_gstin_format(gstin: str) -> CheckResult:
    """G1 — Validate GSTIN format. Hard-fail if invalid."""
    gstin = (gstin or "").strip().upper()
    match = bool(GSTIN_FORMAT_RE.match(gstin))
    if match:
        return CheckResult(
            check_name="gstin_format",
            status="pass",
            severity="hard",
            evidence={"gstin": gstin, "regex": GSTIN_FORMAT_RE.pattern},
            message="GSTIN format is valid.",
        )
    return CheckResult(
        check_name="gstin_format",
        status="fail",
        severity="hard",
        evidence={"gstin": gstin, "regex": GSTIN_FORMAT_RE.pattern},
        message="GSTIN format is invalid.",
    )


def run_gstin_checksum(gstin: str) -> CheckResult:
    """G2 — Validate GSTIN mod-36 checksum. Hard-fail if mismatch."""
    gstin = (gstin or "").strip().upper()

    # Need valid format to even attempt checksum
    if not GSTIN_FORMAT_RE.match(gstin):
        return CheckResult(
            check_name="gstin_checksum",
            status="fail",
            severity="hard",
            evidence={"gstin": gstin},
            message="Cannot check GSTIN checksum because format is invalid.",
        )

    expected = _compute_gstin_checksum(gstin[:14])
    actual = gstin[14]

    if actual == expected:
        return CheckResult(
            check_name="gstin_checksum",
            status="pass",
            severity="hard",
            evidence={"gstin": gstin, "expected_checksum": expected, "actual_checksum": actual},
            message="GSTIN checksum is valid.",
        )
    return CheckResult(
        check_name="gstin_checksum",
        status="fail",
        severity="hard",
        evidence={"gstin": gstin, "expected_checksum": expected, "actual_checksum": actual},
        message=f"GSTIN checksum mismatch: expected '{expected}', got '{actual}'.",
    )


def run_gstin_embedded_pan_match(gstin: str, pan: str) -> CheckResult:
    """G3 — Chars 3-12 (0-indexed 2:12) of GSTIN must equal the submitted PAN. Hard."""
    gstin = (gstin or "").strip().upper()
    pan = (pan or "").strip().upper()

    if len(gstin) != 15:
        return CheckResult(
            check_name="gstin_embedded_pan_match",
            status="fail",
            severity="hard",
            evidence={"gstin": gstin, "pan": pan},
            message="GSTIN must be 15 characters for PAN extraction.",
        )

    embedded = gstin[2:12]  # chars at positions 2 through 11 (0-indexed) = 10 chars = PAN
    if embedded == pan:
        return CheckResult(
            check_name="gstin_embedded_pan_match",
            status="pass",
            severity="hard",
            evidence={"gstin": gstin, "pan": pan, "embedded_pan": embedded},
            message="GSTIN embedded PAN matches submitted PAN.",
        )
    return CheckResult(
        check_name="gstin_embedded_pan_match",
        status="fail",
        severity="hard",
        evidence={"gstin": gstin, "pan": pan, "embedded_pan": embedded},
        message=f"GSTIN embedded PAN '{embedded}' does not match submitted PAN '{pan}'.",
    )


def run_gstin_state_code_match(
    gstin: str,
    gst_cert_state_code: str,
    confidence: float,
    min_confidence: float,
) -> CheckResult:
    """
    G4 — First 2 digits of GSTIN (state code) must match the principal place of business
    state extracted from the GST registration certificate.

    Subject to confidence gate: if confidence < min_confidence, downgrade to fixable.
    Severity is Fixable by default (not Hard).
    """
    gstin = (gstin or "").strip().upper()
    gst_cert_state_code = (gst_cert_state_code or "").strip()

    if len(gstin) < 2:
        return CheckResult(
            check_name="gstin_state_code_match",
            status="fail",
            severity="fixable",
            evidence={"gstin": gstin, "gst_cert_state_code": gst_cert_state_code},
            message="GSTIN too short to extract state code.",
        )

    gstin_state = gstin[:2]

    # Confidence gate
    if confidence < min_confidence:
        return CheckResult(
            check_name="gstin_state_code_match",
            status="fail",
            severity="fixable",
            evidence={
                "gstin": gstin,
                "gstin_state_code": gstin_state,
                "gst_cert_state_code": gst_cert_state_code,
                "confidence": confidence,
                "min_confidence": min_confidence,
            },
            message=(
                f"State code check downgraded to fixable: extraction confidence "
                f"{confidence:.2f} is below minimum {min_confidence:.2f}. "
                "Please upload a clearer GST certificate."
            ),
        )

    if gstin_state == gst_cert_state_code:
        return CheckResult(
            check_name="gstin_state_code_match",
            status="pass",
            severity="fixable",
            evidence={
                "gstin": gstin,
                "gstin_state_code": gstin_state,
                "gst_cert_state_code": gst_cert_state_code,
                "confidence": confidence,
            },
            message="GSTIN state code matches GST certificate principal-place state.",
        )

    return CheckResult(
        check_name="gstin_state_code_match",
        status="fail",
        severity="fixable",
        evidence={
            "gstin": gstin,
            "gstin_state_code": gstin_state,
            "gst_cert_state_code": gst_cert_state_code,
            "confidence": confidence,
        },
        message=(
            f"GSTIN state code '{gstin_state}' does not match "
            f"GST certificate state '{gst_cert_state_code}'."
        ),
    )
