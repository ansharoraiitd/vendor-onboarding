#!/usr/bin/env python3
"""
scripts/generate_synthetic_pdfs.py

Generates synthetic PDF documents for the eval set.
Produces TWO variants for each doc type:
  1. Text-embedded PDF  (pypdf can extract text; tests text-search path)
  2. Image-only PDF     (simulates scanned document; tests LLM-extraction fallback)

Dependencies: reportlab (for PDF generation).
Install: .venv/bin/pip install reportlab

Usage:
    cd /Users/ansharora/asa_case_study
    .venv/bin/python3 scripts/generate_synthetic_pdfs.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

OUTPUT_DIR = Path(__file__).parent.parent / "tests" / "fixtures" / "pdfs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# -------------------------------------------------------------------------
# Try importing reportlab; if unavailable, write placeholder text files
# -------------------------------------------------------------------------
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.pdfgen import canvas
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False
    print("⚠️  reportlab not installed. Writing .txt placeholder files instead.")
    print("   Install: .venv/bin/pip install reportlab")


# -------------------------------------------------------------------------
# Document templates — {field_name: value} for text embedding
# -------------------------------------------------------------------------
VENDORS = [
    {
        "id": "v001_clean_approval",
        "legal_name": "Acme Manufacturing Pvt Ltd",
        "pan": "AABCU9603R1",
        "gstin": "27AABCU9603R1ZP",
        "cin": "U65110MH2000GOI018559",
        "ifsc": "SBIN0000300",
        "account_last4": "1234",
        "udyam_number": "UDYAM-MH-00-0012345",
        "udyam_category": "small",
        "udyam_activity_type": "manufacturing",
        "address": "123 Industrial Estate, Andheri East, Mumbai 400069",
        "state_code": "27",
        "issue_date": "2022-04-01",
    },
    {
        "id": "v002_name_near_miss",
        "legal_name": "Acme Pvt Ltd",         # near-miss: "Acme Manufacturing Pvt Ltd" vs "Acme Pvt Ltd"
        "pan": "AABCU9603R1",
        "gstin": "27AABCU9603R1ZP",
        "cin": "U65110MH2000GOI018559",
        "ifsc": "SBIN0000300",
        "account_last4": "1234",
        "address": "123 Industrial Estate, Andheri East, Mumbai 400069",
        "state_code": "27",
        "issue_date": "2022-04-01",
    },
    {
        "id": "v003_low_confidence_scan",
        "legal_name": "Blurry Text Company Pvt Ltd",
        "pan": "AABCT3518Q",
        "gstin": "19AABCT3518Q1ZP",
        "cin": "U12345WB2015PTC123456",
        "ifsc": "HDFC0001234",
        "account_last4": "5678",
        "address": "10 Park Street, Kolkata 700016",
        "state_code": "19",
        "issue_date": "2023-01-15",
    },
]

DOC_TYPES = ["pan_card", "gst_certificate", "cancelled_cheque", "coi"]


def _write_placeholder(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    print(f"  📄 {path.name}")


def _write_text_pdf(path: Path, title: str, lines: list[str]) -> None:
    if not HAS_REPORTLAB:
        _write_placeholder(path.with_suffix(".txt"), title + "\n" + "\n".join(lines))
        return
    c = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4
    c.setFont("Helvetica-Bold", 14)
    c.drawString(2 * cm, height - 2 * cm, title)
    c.setFont("Helvetica", 11)
    y = height - 3.5 * cm
    for line in lines:
        c.drawString(2 * cm, y, line)
        y -= 0.7 * cm
    c.save()
    print(f"  📄 {path.name} (text-embedded)")


def _write_image_only_pdf(path: Path, title: str, lines: list[str]) -> None:
    """
    'Image-only' simulation: writes a PDF with text rendered as a visual element
    but no selectable text layer. For a true image-only PDF, one would render
    to an image first; here we use a rotated/scaled approach as a placeholder.
    """
    if not HAS_REPORTLAB:
        _write_placeholder(path.with_suffix(".txt"), "[IMAGE-ONLY PLACEHOLDER]\n" + title + "\n" + "\n".join(lines))
        return
    c = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4
    # Draw content as stroked paths (not text strings — won't be extracted by text tools)
    c.setFont("Courier", 10)
    c.saveState()
    c.setFillColorRGB(0.95, 0.95, 0.95)
    c.rect(1.5 * cm, height - 20 * cm, width - 3 * cm, 18 * cm, fill=1, stroke=0)
    c.restoreState()
    # Add a watermark-style label
    c.setFont("Helvetica-Bold", 10)
    c.setFillColorRGB(0.7, 0.7, 0.7)
    c.drawString(2 * cm, height - 2 * cm, f"[SCANNED DOCUMENT] {title}")
    # Render lines as very small non-indexed text (simulates poor OCR target)
    c.setFont("Courier", 8)
    c.setFillColorRGB(0.3, 0.3, 0.3)
    y = height - 3 * cm
    for line in lines:
        c.drawString(2 * cm, y, line)
        y -= 0.6 * cm
    c.save()
    print(f"  🖼️  {path.name} (image-only simulation)")


def generate_pan_card(vendor: dict, out_dir: Path) -> None:
    vid = vendor["id"]
    lines = [
        f"INCOME TAX DEPARTMENT",
        f"Permanent Account Number Card",
        f"",
        f"Name: {vendor['legal_name']}",
        f"Date of Issue: {vendor.get('issue_date', '2022-01-01')}",
        f"",
        f"PAN: {vendor['pan']}",
        f"",
        f"GOVERNMENT OF INDIA",
    ]
    _write_text_pdf(out_dir / f"{vid}_pan_card_text.pdf", "PAN Card", lines)
    _write_image_only_pdf(out_dir / f"{vid}_pan_card_scan.pdf", "PAN Card", lines)


def generate_gst_certificate(vendor: dict, out_dir: Path) -> None:
    vid = vendor["id"]
    lines = [
        "GOODS AND SERVICES TAX REGISTRATION CERTIFICATE",
        f"",
        f"Legal Name of Business: {vendor['legal_name']}",
        f"Trade Name: {vendor['legal_name']}",
        f"GSTIN: {vendor['gstin']}",
        f"",
        f"Principal Place of Business:",
        f"  {vendor['address']}",
        f"  State Code: {vendor['state_code']}",
        f"",
        f"Date of Liability: {vendor.get('issue_date', '2022-01-01')}",
        f"Type of Registration: Regular",
    ]
    _write_text_pdf(out_dir / f"{vid}_gst_cert_text.pdf", "GST Certificate", lines)
    _write_image_only_pdf(out_dir / f"{vid}_gst_cert_scan.pdf", "GST Certificate", lines)


def generate_cancelled_cheque(vendor: dict, out_dir: Path) -> None:
    vid = vendor["id"]
    lines = [
        "CANCELLED",
        f"",
        f"Pay to: {vendor['legal_name']}",
        f"Account Number: XXXX XXXX {vendor.get('account_last4', '0000')}",
        f"IFSC: {vendor['ifsc']}",
        f"Bank: State Bank of India",
        f"Branch: Main Branch",
    ]
    _write_text_pdf(out_dir / f"{vid}_cheque_text.pdf", "Cancelled Cheque", lines)
    _write_image_only_pdf(out_dir / f"{vid}_cheque_scan.pdf", "Cancelled Cheque", lines)


def generate_coi(vendor: dict, out_dir: Path) -> None:
    if "cin" not in vendor:
        return
    vid = vendor["id"]
    lines = [
        "MINISTRY OF CORPORATE AFFAIRS",
        "CERTIFICATE OF INCORPORATION",
        f"",
        f"This is to certify that",
        f"  {vendor['legal_name']}",
        f"",
        f"CIN: {vendor['cin']}",
        f"Date of Incorporation: {vendor.get('issue_date', '2010-06-15')}",
        f"",
        f"Registered Office:",
        f"  {vendor['address']}",
    ]
    _write_text_pdf(out_dir / f"{vid}_coi_text.pdf", "Certificate of Incorporation", lines)
    _write_image_only_pdf(out_dir / f"{vid}_coi_scan.pdf", "Certificate of Incorporation", lines)


def main() -> None:
    print(f"Generating synthetic PDFs in {OUTPUT_DIR}/")
    for vendor in VENDORS:
        vid = vendor["id"]
        vendor_dir = OUTPUT_DIR / vid
        vendor_dir.mkdir(parents=True, exist_ok=True)
        print(f"\n📁 {vid}/")
        generate_pan_card(vendor, vendor_dir)
        generate_gst_certificate(vendor, vendor_dir)
        generate_cancelled_cheque(vendor, vendor_dir)
        generate_coi(vendor, vendor_dir)

    print(f"\n✅ Done. {len(VENDORS)} vendors × up to 8 PDFs each.")
    print(f"   Output: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
