"""
tests/test_extractor_robustness.py — Tests for EXTRACTOR_MODE and Gemini circuit breaker.
"""
from __future__ import annotations

import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from app.pipeline.extractor import (
    GeminiExtractor,
    _CIRCUIT_BREAKER_TRIPPED,
    get_extractor_mode,
    is_ai_extraction_enabled,
    reset_circuit_breaker,
    trip_circuit_breaker,
)


def test_extractor_mode_offline():
    reset_circuit_breaker()
    with patch.dict(os.environ, {"EXTRACTOR_MODE": "offline"}):
        assert get_extractor_mode() == "offline"
        assert is_ai_extraction_enabled() is False

        ext = GeminiExtractor(api_key="fake-test-key")
        # In offline mode, should_call_gemini is False, never calls _call_gemini_api
        with patch.object(ext, "_call_gemini_api") as mock_api:
            # Create a dummy raster image
            with tempfile.NamedTemporaryFile(suffix=".png") as tf:
                tf.write(b"\x89PNG\r\n\x1a\nfakeimagebytes")
                tf.flush()
                res = ext.extract(tf.name, "cancelled_cheque", {})
                mock_api.assert_not_called()
                assert res.extractor_type == "scan_unreadable_fail_closed"


def test_circuit_breaker_trips_on_402():
    reset_circuit_breaker()
    try:
        with patch.dict(os.environ, {"EXTRACTOR_MODE": "auto", "GEMINI_API_KEY": "fake-key"}):
            ext = GeminiExtractor(api_key="fake-key")

            # Mock 402 payment required response from Gemini
            mock_resp = MagicMock()
            mock_resp.status_code = 402
            mock_resp.reason_phrase = "Payment Required"
            mock_resp.text = '{"error": {"code": 402, "message": "Prepayment credits depleted"}}'

            with patch("httpx.Client.post", return_value=mock_resp):
                with tempfile.NamedTemporaryFile(suffix=".png") as tf:
                    tf.write(b"\x89PNG\r\n\x1a\nfresh_test_image_bytes")
                    tf.flush()
                    # First call should trip circuit breaker and NOT retry 4 times
                    res = ext.extract(tf.name, "cancelled_cheque", {})
                    assert is_ai_extraction_enabled() is False
                    assert res.extractor_type == "gemini_api"
                    assert "circuit breaker" in res.error.lower()

                    # Second call should immediately bypass Gemini because breaker is tripped
                    with patch.object(ext, "_call_gemini_api") as mock_api:
                        res2 = ext.extract(tf.name, "cancelled_cheque", {})
                        mock_api.assert_not_called()
                        assert res2.extractor_type == "scan_unreadable_fail_closed"
    finally:
        reset_circuit_breaker()


def test_no_cache_write_on_gemini_failure():
    reset_circuit_breaker()
    try:
        ext = GeminiExtractor(api_key="fake-key")
        with patch.dict(os.environ, {"EXTRACTOR_MODE": "auto"}):
            # Create a mock failure response from Gemini
            mock_resp = MagicMock()
            mock_resp.status_code = 500
            mock_resp.reason_phrase = "Internal Server Error"
            mock_resp.text = "Internal Server Error"

            # Create a genuine text-embedded PDF
            from reportlab.lib.pagesizes import A4
            from reportlab.pdfgen import canvas
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
                pdf_path = tf.name
            c = canvas.Canvas(pdf_path, pagesize=A4)
            c.drawString(100, 700, "CAN TEST DOCUMENT WITH DIGITAL TEXT LAYER")
            c.save()

            try:
                with patch("httpx.Client.post", return_value=mock_resp), \
                     patch.object(ext, "_save_to_disk_cache") as mock_save:
                    res = ext.extract(pdf_path, "cancelled_cheque", {})
                    # Spec: Never write a regex-fallback result to cache when Gemini failed
                    mock_save.assert_not_called()
                    assert res.extractor_type == "text_layer_regex"
                    assert "gemini api failure" in res.error.lower()
            finally:
                if os.path.exists(pdf_path):
                    os.unlink(pdf_path)
    finally:
        reset_circuit_breaker()
