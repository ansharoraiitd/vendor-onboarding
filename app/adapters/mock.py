"""
MockAdapter — reads pre-configured responses from a YAML fixture file.
Keyed by (adapter_name, primary_key). Falls back to adapter-specific defaults
when the key is not in the fixture.
"""
from __future__ import annotations

import os
from typing import Any

import yaml

from app.adapters import AdapterResult

_DEFAULT_FIXTURE_PATH = os.path.join(
    os.path.dirname(__file__),
    "../../tests/fixtures/adapter_responses.yaml",
)


def _load_fixture(path: str) -> dict:
    abs_path = os.path.abspath(path)
    if not os.path.exists(abs_path):
        return {}
    with open(abs_path, "r") as fh:
        return yaml.safe_load(fh) or {}


# Default statuses when a key is absent from the fixture
_ADAPTER_DEFAULTS: dict[str, str] = {
    "PANStatusAdapter": "valid",
    "GSTINStatusAdapter": "active",
    "MCAStatusAdapter": "active",
    "DebarmentAdapter": "clear",
    "IFSCAdapter": "found",
    "InternalBlocklistAdapter": "clear",
}


class MockAdapter:
    """
    Reads from tests/fixtures/adapter_responses.yaml.
    Structure:
        PANStatusAdapter:
          AABCP1234C: {status: valid, ...}
        GSTINStatusAdapter:
          27AABCU9603R1ZP: {status: active, ...}
    """

    def __init__(self, fixture_path: str = _DEFAULT_FIXTURE_PATH) -> None:
        self._fixture = _load_fixture(fixture_path)

    def call(self, adapter_name: str, primary_key: str, **kwargs: Any) -> AdapterResult:
        adapter_data: dict = self._fixture.get(adapter_name, {})
        entry: dict = adapter_data.get(primary_key, {})

        if entry:
            status = entry.get("status", _ADAPTER_DEFAULTS.get(adapter_name, "unknown"))
            raw = {k: v for k, v in entry.items() if k != "status"}
            error = entry.get("error")
        else:
            status = _ADAPTER_DEFAULTS.get(adapter_name, "unknown")
            raw = {"note": "not in fixture; using default"}
            error = None

        return AdapterResult(
            status=status,
            source=adapter_name,
            raw=raw,
            error=error,
            available=True,
        )
