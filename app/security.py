"""
app/security.py — Canonical cryptographic and HMAC utilities.
"""
from __future__ import annotations

import hashlib
import hmac
import os


def compute_bank_account_hmac(account_number: str) -> str:
    """
    Computes deterministic HMAC-SHA256 digest of a bank account number.
    Uses HMAC_SECRET environment variable.
    """
    secret = os.environ.get("HMAC_SECRET", "dev-secret-change-in-production")
    clean = account_number.strip()
    return hmac.new(
        secret.encode("utf-8"),
        clean.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
