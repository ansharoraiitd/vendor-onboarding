"""
app/validators/llpin.py — LLPIN format check (L1).

LLPIN format: [A-Z]{3}-\\d{4}  (e.g. AAA-1234)
L1: Format regex — Hard
"""
from __future__ import annotations

import re

from app.validators import CheckResult

LLPIN_FORMAT_RE = re.compile(r"^[A-Z]{3}-\d{4}$")


def run_llpin_format(llpin: str) -> CheckResult:
    """L1 — Validate LLPIN format. Hard-fail if invalid."""
    llpin = (llpin or "").strip().upper()
    match = bool(LLPIN_FORMAT_RE.match(llpin))
    if match:
        return CheckResult(
            check_name="llpin_format",
            status="pass",
            severity="hard",
            evidence={"llpin": llpin, "regex": LLPIN_FORMAT_RE.pattern},
            message="LLPIN format is valid.",
        )
    return CheckResult(
        check_name="llpin_format",
        status="fail",
        severity="hard",
        evidence={"llpin": llpin, "regex": LLPIN_FORMAT_RE.pattern},
        message="LLPIN format is invalid.",
    )
