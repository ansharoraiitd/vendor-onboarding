"""
scripts/generate_e2e_eval_docs.py — Generates real physical PDFs for the 24-record E2E eval set.
Produces:
- 3 distinct layout styles per document type
- Extra noise lines, varied field order, UPPERCASE labels
- Image-only scans (zero digital text layer, pure raster bitmaps)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml
from PIL import Image, ImageDraw
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas

E2E_DOCS_DIR = Path("tests/fixtures/e2e_eval_docs")
E2E_DOCS_DIR.mkdir(parents=True, exist_ok=True)


def _generate_pan_pdf(path: Path, pan: str, name: str, layout: str) -> None:
    c = canvas.Canvas(str(path), pagesize=A4)
    if layout == "layout_beneficiary_uppercase":
        c.setFont("Helvetica-Bold", 14)
        c.drawString(2 * cm, 26 * cm, "INCOME TAX DEPARTMENT - GOVT. OF INDIA")
        c.setFont("Helvetica-Bold", 12)
        c.drawString(2 * cm, 24 * cm, f"PERMANENT ACCOUNT NUMBER: {pan}")
        c.setFont("Helvetica", 11)
        c.drawString(2 * cm, 22 * cm, f"CARDHOLDER NAME: {name.upper()}")
        c.drawString(2 * cm, 20 * cm, "DATE OF ISSUE: 2018-05-15")
    elif layout == "layout_pay_to_noise":
        c.setFont("Helvetica-Bold", 14)
        c.drawString(2 * cm, 26 * cm, "GOVERNMENT OF INDIA - INCOME TAX DEPARTMENT")
        c.setFont("Helvetica", 10)
        c.drawString(2 * cm, 25 * cm, "Identity Verification Card / Ref: NSDL-TIN-8892")
        c.setFont("Helvetica", 11)
        c.drawString(2 * cm, 23 * cm, f"Name: {name}")
        c.drawString(2 * cm, 21 * cm, f"Permanent Account Number: {pan}")
        c.drawString(2 * cm, 19 * cm, "Father's Name: Late R. K. Sharma")
    else:  # layout_ac_holder_reversed or default
        c.setFont("Helvetica-Bold", 14)
        c.drawString(2 * cm, 26 * cm, "INCOME TAX DEPARTMENT")
        c.setFont("Helvetica", 11)
        c.drawString(2 * cm, 24 * cm, f"PAN: {pan}")
        c.drawString(2 * cm, 22 * cm, f"Name on Card: {name}")
    c.save()


def _generate_gst_pdf(path: Path, gstin: str, name: str, layout: str) -> None:
    c = canvas.Canvas(str(path), pagesize=A4)
    state_code = gstin[:2]
    if layout == "layout_beneficiary_uppercase":
        c.setFont("Helvetica-Bold", 14)
        c.drawString(2 * cm, 26 * cm, "FORM GST REG-06 - REGISTRATION CERTIFICATE")
        c.setFont("Helvetica", 11)
        c.drawString(2 * cm, 24 * cm, f"REGISTRATION NUMBER (GSTIN): {gstin}")
        c.drawString(2 * cm, 22 * cm, f"LEGAL NAME: {name.upper()}")
        c.drawString(2 * cm, 20 * cm, f"STATE CODE: {state_code}")
    elif layout == "layout_pay_to_noise":
        c.setFont("Helvetica-Bold", 14)
        c.drawString(2 * cm, 26 * cm, "GOODS AND SERVICES TAX REGISTRATION")
        c.setFont("Helvetica", 10)
        c.drawString(2 * cm, 25 * cm, "Tax Invoice Reference Verification / Tax Office: Ward 4B")
        c.setFont("Helvetica", 11)
        c.drawString(2 * cm, 23 * cm, f"Legal Name: {name}")
        c.drawString(2 * cm, 21 * cm, f"GSTIN: {gstin}")
        c.drawString(2 * cm, 19 * cm, f"Principal Place of Business State: {state_code}")
    else:
        c.setFont("Helvetica-Bold", 14)
        c.drawString(2 * cm, 26 * cm, "CERTIFICATE OF REGISTRATION UNDER GST")
        c.setFont("Helvetica", 11)
        c.drawString(2 * cm, 24 * cm, f"State Code: {state_code}")
        c.drawString(2 * cm, 22 * cm, f"GSTIN on Cert: {gstin}")
        c.drawString(2 * cm, 20 * cm, f"Trade Name / Legal Name: {name}")
    c.save()


def _generate_cheque_pdf(path: Path, name: str, ifsc: str, acct: str, layout: str) -> None:
    c = canvas.Canvas(str(path), pagesize=A4)
    last4 = acct[-4:] if len(acct) >= 4 else "1001"
    masked_acct = f"XXXX XXXX {last4}"

    if layout == "layout_beneficiary_uppercase":
        c.setFont("Helvetica-Bold", 14)
        c.drawString(2 * cm, 26 * cm, "STATE BANK OF INDIA - CANCELLED CHEQUE")
        c.setFont("Helvetica", 11)
        c.drawString(2 * cm, 24 * cm, f"BENEFICIARY NAME: {name.upper()}")
        c.drawString(2 * cm, 22 * cm, f"ACCOUNT NUMBER: {masked_acct}")
        c.drawString(2 * cm, 20 * cm, f"IFS CODE: {ifsc}")
    elif layout == "layout_pay_to_noise":
        c.setFont("Helvetica-Bold", 14)
        c.drawString(2 * cm, 26 * cm, "HDFC BANK LIMITED - CANCELLED CHEQUE")
        c.setFont("Helvetica", 10)
        c.drawString(2 * cm, 25 * cm, "Nariman Point Branch / Clearance: RTGS/NEFT / Code: 000300")
        c.setFont("Helvetica", 11)
        c.drawString(2 * cm, 23 * cm, f"Pay to: {name}")
        c.drawString(2 * cm, 21 * cm, f"Account No: {masked_acct}")
        c.drawString(2 * cm, 19 * cm, f"IFSC: {ifsc}")
        c.drawString(2 * cm, 17 * cm, "Stamp: VERIFIED & CANCELLED")
    elif layout == "layout_ac_holder_reversed":
        c.setFont("Helvetica-Bold", 14)
        c.drawString(2 * cm, 26 * cm, "ICICI BANK - CANCELLED CHEQUE")
        c.setFont("Helvetica", 11)
        c.drawString(2 * cm, 24 * cm, f"IFSC: {ifsc}")
        c.drawString(2 * cm, 22 * cm, f"A/c Number: {masked_acct}")
        c.drawString(2 * cm, 20 * cm, f"A/c Holder: {name}")
    elif layout == "layout_wrong_name_cheque":
        c.setFont("Helvetica-Bold", 14)
        c.drawString(2 * cm, 26 * cm, "CANCELLED CHEQUE")
        c.setFont("Helvetica", 11)
        c.drawString(2 * cm, 24 * cm, "Pay to: Rajesh Sharma")
        c.drawString(2 * cm, 22 * cm, f"Account Number: {masked_acct}")
        c.drawString(2 * cm, 20 * cm, f"IFSC: {ifsc}")
    elif layout == "layout_irrelevant_essay":
        c.setFont("Helvetica-Bold", 14)
        c.drawString(2 * cm, 26 * cm, "A BRIEF ESSAY ON MODERN ARCHITECTURE")
        c.setFont("Helvetica", 11)
        c.drawString(2 * cm, 24 * cm, "Architecture is both the process and the product of sketching.")
        c.drawString(2 * cm, 22 * cm, "Buildings in their architectural form are often perceived as cultural symbols.")
    c.save()


def _generate_raster_scan_pdf(path: Path, text: str) -> None:
    """Generate pure bitmap PDF with ZERO digital text layer."""
    img = Image.new("RGB", (800, 400), color=(255, 255, 255))
    d = ImageDraw.Draw(img)
    d.rectangle([20, 20, 780, 380], outline=(100, 100, 100), width=2)
    d.text((40, 50), text, fill=(0, 0, 0))
    d.text((40, 100), "CANCELLED CHEQUE - SCANNED COPY ONLY", fill=(50, 50, 50))
    # Save as image-only PDF
    img.save(str(path), "PDF", resolution=150.0)


def generate_all_e2e_docs() -> int:
    yaml_path = Path("tests/fixtures/eval_set_e2e.yaml")
    with open(yaml_path, "r", encoding="utf-8") as f:
        records = yaml.safe_load(f)

    count = 0
    for rec in records:
        r_id = rec["id"]
        r_dir = E2E_DOCS_DIR / r_id
        r_dir.mkdir(parents=True, exist_ok=True)

        layout = rec.get("layout_style", "layout_beneficiary_uppercase")
        name = rec["name"]
        pan = rec["pan"]
        gstin = rec["gstin"]
        ifsc = rec["ifsc"]
        acct = rec["bank_account_number"]
        is_scan = rec.get("needs_vision", False)

        # 1. PAN Card
        pan_p = r_dir / "pan_card.pdf"
        if layout == "layout_slot_swapped":
            # Upload GST cert into PAN slot
            _generate_gst_pdf(pan_p, gstin, name, "layout_pay_to_noise")
        else:
            _generate_pan_pdf(pan_p, pan, name, layout)
        count += 1

        # 2. GST Certificate
        gst_p = r_dir / "gst_certificate.pdf"
        _generate_gst_pdf(gst_p, gstin, name, layout)
        count += 1

        # 3. Cancelled Cheque
        cheque_p = r_dir / "cancelled_cheque.pdf"
        if is_scan:
            _generate_raster_scan_pdf(cheque_p, f"A/C HOLDER: {name} | IFSC: {ifsc}")
        elif r_id == "E2E10":
            _generate_cheque_pdf(cheque_p, "Acme Industrial Systems Trading", ifsc, acct, layout)
        elif r_id == "E2E11":
            _generate_cheque_pdf(cheque_p, "Someone Industrial Systems", ifsc, acct, layout)
        elif r_id == "E2E12":
            _generate_cheque_pdf(cheque_p, "Acme Industrial Systems Holdings", ifsc, acct, layout)
        elif r_id == "E2E05":
            _generate_cheque_pdf(cheque_p, "Falcon Electronics (India) Pvt Ltd", ifsc, acct, layout)
        elif r_id == "E2E06":
            _generate_cheque_pdf(cheque_p, "M/s Greenfield Packaging Solutions Pvt Ltd Current A/C", ifsc, acct, layout)
        elif r_id == "E2E07":
            _generate_cheque_pdf(cheque_p, "Horizon Logistics Pvt Ltd Unit 2", ifsc, acct, layout)
        elif r_id == "E2E09":
            _generate_cheque_pdf(cheque_p, "Kalyan Heavy Machineries Private Limited (Branch Division)", ifsc, acct, layout)
        else:
            _generate_cheque_pdf(cheque_p, name, ifsc, acct, layout)
        count += 1

        # 4. COI or LLPIN
        if rec.get("cin"):
            coi_p = r_dir / "coi.pdf"
            c = canvas.Canvas(str(coi_p), pagesize=A4)
            c.setFont("Helvetica-Bold", 14)
            c.drawString(2 * cm, 26 * cm, "CERTIFICATE OF INCORPORATION")
            c.setFont("Helvetica", 11)
            c.drawString(2 * cm, 24 * cm, f"Company Name: {name}")
            c.drawString(2 * cm, 22 * cm, f"CIN: {rec['cin']}")
            cin_val = str(rec['cin'])
            incorp_year = cin_val[8:12] if len(cin_val) >= 12 and cin_val[8:12].isdigit() else "2018"
            c.drawString(2 * cm, 20 * cm, f"Date of Incorporation: {incorp_year}-06-15")
            c.save()
            count += 1
        elif rec.get("llpin"):
            llp_p = r_dir / "llpin_cert.pdf"
            c = canvas.Canvas(str(llp_p), pagesize=A4)
            c.setFont("Helvetica-Bold", 14)
            c.drawString(2 * cm, 26 * cm, "LLP REGISTRATION CERTIFICATE")
            c.setFont("Helvetica", 11)
            c.drawString(2 * cm, 24 * cm, f"LLP Name: {name}")
            c.drawString(2 * cm, 22 * cm, f"LLPIN: {rec['llpin']}")
            c.save()
            count += 1

    print(f"Generated {count} PDFs across {len(records)} records in {E2E_DOCS_DIR}")
    return count


if __name__ == "__main__":
    generate_all_e2e_docs()
