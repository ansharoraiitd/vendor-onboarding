"""
Unit tests for the extractor interface, caching, provider swapping, and timeout fallback.
"""
from __future__ import annotations

import tempfile
import pytest

from app.pipeline.extractor import (
    ExtractionResult,
    StubLLMProvider,
    clear_extraction_cache,
    compute_file_sha256,
    extract,
    set_llm_provider,
)


@pytest.fixture(autouse=True)
def clean_cache():
    clear_extraction_cache()
    set_llm_provider(StubLLMProvider())
    yield
    clear_extraction_cache()


def test_stub_extraction_pan_card():
    res = extract("dummy_path", "pan_card", {"pan": "AABCU9603R", "legal_name": "Test Co"})
    assert res.doc_type == "pan_card"
    assert res.fields["pan_number"] == "AABCU9603R"
    assert res.fields["name_on_pan"] == "Test Co"
    assert res.confidence("pan_number") >= 0.80
    assert "AABCU9603R" in res.raw_text


def test_sha256_cache():
    with tempfile.NamedTemporaryFile("wb", delete=False) as tf:
        tf.write(b"SAMPLE DOCUMENT CONTENT")
        temp_path = tf.name

    h = compute_file_sha256(temp_path)
    assert len(h) == 64

    # First call - cache miss
    res1 = extract(temp_path, "pan_card", {"pan": "AABCU9603R"})
    assert not res1.cached

    # Second call - cache hit
    res2 = extract(temp_path, "pan_card", {"pan": "AABCU9603R"})
    assert res2.cached
    assert res2.fields == res1.fields


def test_custom_swappable_provider():
    class CustomProvider:
        def extract(self, doc_path, doc_type, submission_fields, timeout_seconds=5.0):
            return ExtractionResult(
                doc_type=doc_type,
                fields={"custom_field": "12345"},
                confidences={"custom_field": 0.99},
            )

    set_llm_provider(CustomProvider())
    res = extract("any_path", "custom_doc", {})
    assert res.fields["custom_field"] == "12345"
    assert res.confidence("custom_field") == 0.99


def test_timeout_fallback():
    res = extract("path", "pan_card", {}, simulate_timeout=True)
    assert res.timed_out
    assert res.confidence("pan_number") < 0.50
    assert res.error is not None


def test_text_layer_pan_name_labels():
    """Unit test: Labels like 'Name on Card:', 'Name as per PAN:', 'Name:' must capture only value after colon."""
    from app.pipeline.extractor import _extract_from_text_layer

    samples = [
        ("INCOME TAX DEPARTMENT\nPAN: AABCU9603R\nName on Card: Acme Industrial Systems\n", "Acme Industrial Systems"),
        ("INCOME TAX DEPARTMENT\nPAN: AABCU9603R\nName as per PAN: Apex Engineering Systems\n", "Apex Engineering Systems"),
        ("INCOME TAX DEPARTMENT\nPAN: AABCU9603R\nCardholder Name: Bharat Precision Forgings\n", "Bharat Precision Forgings"),
        ("INCOME TAX DEPARTMENT\nPAN: AABCU9603R\nName: Delta Agro Exports LLP\n", "Delta Agro Exports LLP"),
    ]

    for text, expected_name in samples:
        _, fields, confs, snippets, _ = _extract_from_text_layer(text, "pan_card")
        assert fields.get("name_on_pan") == expected_name
        assert confs.get("name_on_pan") is not None
        assert snippets.get("name_on_pan") is not None


def test_text_layer_gst_state_code():
    """Unit test: 'Principal Place of Business State: 27', 'State Code: 27', 'State: 27' fill principal_place_state_code."""
    from app.pipeline.extractor import _extract_from_text_layer

    samples = [
        ("FORM GST REG-06\nGSTIN: 27AABCA1001A1ZZ\nPrincipal Place of Business State: 27\nLegal Name: Apex Systems\n", "27"),
        ("FORM GST REG-06\nGSTIN: 27AABCA1001A1ZZ\nState Code: 27\nLegal Name: Apex Systems\n", "27"),
        ("FORM GST REG-06\nGSTIN: 24AAFFD4004D1Z9\nState: 24\nLegal Name: Delta Agro Exports\n", "24"),
    ]

    for text, expected_state in samples:
        _, fields, confs, snippets, _ = _extract_from_text_layer(text, "gst_certificate")
        assert fields.get("principal_place_state_code") == expected_state
        assert confs.get("principal_place_state_code") is not None

