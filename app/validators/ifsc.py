"""
app/validators/ifsc.py — IFSC format check (B1).

IFSC format: [A-Z]{4}0[A-Z0-9]{6}  (11 chars; 5th char always '0')
B1: Format regex — Hard
"""
from __future__ import annotations

import re

from app.validators import CheckResult

# 11 chars: 4 alpha (bank code) + '0' + 6 alphanumeric (branch code)
IFSC_FORMAT_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")


def run_ifsc_format(ifsc: str) -> CheckResult:
    """B1 — Validate IFSC format. Hard-fail if invalid."""
    ifsc = (ifsc or "").strip().upper()
    match = bool(IFSC_FORMAT_RE.match(ifsc))
    if match:
        return CheckResult(
            check_name="ifsc_format",
            status="pass",
            severity="hard",
            evidence={"ifsc": ifsc, "regex": IFSC_FORMAT_RE.pattern},
            message="IFSC format is valid.",
        )
    return CheckResult(
        check_name="ifsc_format",
        status="fail",
        severity="hard",
        evidence={"ifsc": ifsc, "regex": IFSC_FORMAT_RE.pattern},
        message="IFSC format is invalid.",
    )
