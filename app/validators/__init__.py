"""
app/validators/__init__.py — Shared CheckResult dataclass used by all validators.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class CheckResult:
    check_name: str
    status: str                                  # pass | fail | warn | missing
    severity: str                                # hard | fixable | soft | escalate
    evidence: dict = field(default_factory=dict) # raw values used
    score_contribution: float = 0.0
    message: str = ""                            # human-readable label/message
    explanation: str = ""                        # detailed explanation

    def __post_init__(self):
        # Sync message and explanation if only one was provided
        if self.message and not self.explanation:
            self.explanation = self.message
        elif self.explanation and not self.message:
            self.message = self.explanation
