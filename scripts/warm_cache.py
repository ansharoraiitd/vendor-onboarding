"""
scripts/warm_cache.py — Pre-extracts and warms data/extraction_cache with verified
extraction outputs for all demo documents, fixtures, and adversarial cases.
Ensures instant, zero-latency, offline-capable demo and evaluation runs.
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import pypdf
from app.demo_scenarios import DEMO_DOCS_DIR, DEMO_SCENARIOS, generate_scenario_pdfs, get_demo_documents
from app.pipeline.extractor import (
    DISK_CACHE_DIR,
    PROMPT_SCHEMA_VERSION,
    ExtractionResult,
    _extract_from_text_layer,
    compute_cache_key,
    compute_file_sha256,
    extract,
    get_llm_provider,
    parse_pdf_date_str,
)

# Also generate adversarial fixtures if missing
def _ensure_adversarial_fixtures():
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.pdfgen import canvas

    adv_dir = Path("tests/fixtures/adversarial_docs")
    adv_dir.mkdir(parents=True, exist_ok=True)

    # 1. Lookalike names
    lookalikes = [
        ("Someone Industrial Systems", "someone_industrial_systems"),
        ("Acme Industrial Systems Trading", "acme_industrial_systems_trading"),
    ]
    slots = ["pan_card", "gst_certificate", "cancelled_cheque", "coi"]

    for name, slug in lookalikes:
        for slot in slots:
            p = adv_dir / f"lookalike_{slot}_{slug}.pdf"
            if not p.exists():
                c = canvas.Canvas(str(p), pagesize=A4)
                c.setFont("Helvetica-Bold", 14)
                c.drawString(2 * cm, 26 * cm, f"DOCUMENT - {slot.upper()}")
                c.setFont("Helvetica", 11)
                c.drawString(2 * cm, 24 * cm, f"Name: {name}")
                if slot == "pan_card":
                    c.drawString(2 * cm, 22 * cm, "PAN: AAECK1234G")
                elif slot == "gst_certificate":
                    c.drawString(2 * cm, 22 * cm, "GSTIN: 27AAECK1234G1Z5")
                elif slot == "cancelled_cheque":
                    c.drawString(2 * cm, 22 * cm, "Account: 1234567890 IFSC: SBIN0000300")
                elif slot == "coi":
                    c.drawString(2 * cm, 22 * cm, "CIN: U72900MH2018PTC123456")
                c.save()

    # 2. Legit variants
    legit_variants = [
        ("Acme Industrial Systems Pvt Ltd", "acme_industrial_systems_pvt_ltd"),
        ("M/s Acme Industrial Systems", "m_s_acme_industrial_systems"),
        ("Industrial Systems Acme", "industrial_systems_acme"),
    ]
    for name, slug in legit_variants:
        p = adv_dir / f"legit_cheque_{slug}.pdf"
        if not p.exists():
            c = canvas.Canvas(str(p), pagesize=A4)
            c.setFont("Helvetica-Bold", 14)
            c.drawString(2 * cm, 26 * cm, "CANCELLED CHEQUE - STATE BANK OF INDIA")
            c.setFont("Helvetica", 11)
            c.drawString(2 * cm, 24 * cm, f"Pay to: {name}")
            c.drawString(2 * cm, 22 * cm, "Account Number: XXXX XXXX 1234")
            c.drawString(2 * cm, 20 * cm, "IFSC: SBIN0000300")
            c.save()


def warm_all_caches() -> dict:
    """Extract and cache all demo documents, adversarial fixtures, and report counts."""
    DISK_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    generate_scenario_pdfs()
    _ensure_adversarial_fixtures()

    provider = get_llm_provider()
    counts = Counter()
    failed_docs = []

    print("Warming extraction cache with active provider: %s" % type(provider).__name__)
    documents_to_process = []

    # 1. Demo scenarios
    for sc_key, sc in DEMO_SCENARIOS.items():
        sc_dir = DEMO_DOCS_DIR / sc_key
        doc_mapping = {
            "pan_card.pdf": "pan_card",
            "gst_certificate.pdf": "gst_certificate",
            "cancelled_cheque.pdf": "cancelled_cheque",
            "corrected_cheque.pdf": "cancelled_cheque",
            "coi.pdf": "coi",
            "llpin_cert.pdf": "llpin_cert",
            "udyam_cert.pdf": "udyam_cert",
            "address_proof.pdf": "address_proof",
        }
        if sc_dir.exists():
            for p in sorted(sc_dir.glob("*.pdf")):
                dt = doc_mapping.get(p.name)
                if dt:
                    documents_to_process.append((str(p), dt, f"[{sc_key}] {p.name}", sc.data))

    # 2. Adversarial test fixtures
    adv_dir = Path("tests/fixtures/adversarial_docs")
    if adv_dir.exists():
        for f in sorted(list(adv_dir.glob("*.pdf")) + list(adv_dir.glob("*.png"))):
            doc_type = "cancelled_cheque" if "cheque" in f.name else ("pan_card" if "pan" in f.name else ("gst_certificate" if "gst" in f.name else ("coi" if "coi" in f.name else "unknown")))
            documents_to_process.append((str(f), doc_type, f"[adversarial] {f.name}", {}))

    for path, dt, label, sub_data in documents_to_process:
        file_sha = compute_file_sha256(path)
        cache_key = compute_cache_key(file_sha, dt)
        cache_file = DISK_CACHE_DIR / f"{cache_key}.json"
        legacy_file = DISK_CACHE_DIR / f"{file_sha}.json"

        # Check if already in persistent disk cache
        if cache_file.exists():
            counts["disk_cache"] += 1
            if not legacy_file.exists():
                import shutil
                shutil.copyfile(cache_file, legacy_file)
            print(f"  {label} -> disk_cache")
            continue

        if legacy_file.exists():
            counts["disk_cache"] += 1
            if not cache_file.exists():
                import shutil
                shutil.copyfile(legacy_file, cache_file)
            print(f"  {label} -> disk_cache")
            continue

        # Extract using provider
        res = extract(doc_path=path, doc_type=dt, submission_fields=sub_data)
        ext_type = res.extractor_type

        # Sleep 4 seconds between calls as requested
        time.sleep(4)

        counts[ext_type] += 1
        if res.error or ext_type in ("scan_unreadable_fail_closed", "corrupt_pdf_error", "missing_file_error", "error_fallback"):
            failed_docs.append((label, res.error or f"Extraction type: {ext_type}"))
            print(f"  {label} -> {ext_type} (FAILED: {res.error})")
        else:
            print(f"  {label} -> {ext_type}")

    print("\n" + "="*50)
    print("EXTRACTION CACHE WARMUP SUMMARY")
    print("="*50)
    for k in ["gemini_api", "text_layer_regex", "disk_cache", "scan_unreadable_fail_closed"]:
        print(f"  {k}: {counts[k]}")
    for k, v in counts.items():
        if k not in ["gemini_api", "text_layer_regex", "disk_cache", "scan_unreadable_fail_closed"]:
            print(f"  {k}: {v}")

    print(f"\nFailed documents ({len(failed_docs)}):")
    for f_label, err in failed_docs:
        print(f"  - {f_label}: {err}")
    print("="*50)

    return {"counts": dict(counts), "failed": failed_docs}


if __name__ == "__main__":
    warm_all_caches()
