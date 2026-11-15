"""
Adapter layer — mockable interface for external data sources.
All adapters share AdapterResult and the BaseAdapter Protocol.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol


@dataclass
class AdapterResult:
    """Standardised result returned by every adapter."""
    status: str                        # adapter-specific status string
    source: str                        # adapter name, e.g. "GSTINStatusAdapter"
    raw: dict[str, Any] = field(default_factory=dict)   # raw response excerpt
    error: Optional[str] = None        # non-None when call failed
    available: bool = True             # False when adapter is unreachable


class BaseAdapter(Protocol):
    """Protocol that every adapter must satisfy."""

    def call(self, primary_key: str, **kwargs: Any) -> AdapterResult:
        """
        Call the adapter for the given primary key.

        Args:
            primary_key: The identifier to look up (GSTIN, PAN, IFSC, etc.)
            **kwargs: Adapter-specific extras

        Returns:
            AdapterResult with at minimum `status` and `source` populated.
        """
        ...
