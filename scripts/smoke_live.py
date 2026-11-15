#!/usr/bin/env python3
"""
scripts/smoke_live.py — End-to-end live smoke test over HTTP.

Usage:
    python scripts/smoke_live.py [BASE_URL]
    Example: python scripts/smoke_live.py http://127.0.0.1:8000

Runs all 8 demo scenarios over HTTP using per-slot multipart uploads
(no pre-seeded shortcuts), waits for each pipeline decision, and prints
a formatted terminal table: scenario | expected | actual | match.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

import httpx

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.demo_scenarios import DEMO_SCENARIOS, get_demo_documents

DOC_SLOT_MAP = {
    "pan_card": "file_pan_card",
    "gst_certificate": "file_gst_certificate",
    "cancelled_cheque": "file_cancelled_cheque",
    "coi": "file_coi",
    "llpin_cert": "file_llpin_cert",
    "address_proof": "file_address_proof",
    "udyam_cert": "file_udyam_cert",
}


def run_smoke_test(base_url: str) -> bool:
    base_url = base_url.rstrip("/")
    print(f"\nTarget Base URL: {base_url}")
    print("Checking /health endpoint...")

    with httpx.Client(timeout=10.0) as client:
        try:
            r = client.get(f"{base_url}/health")
            r.raise_for_status()
            health_data = r.json()
            print(f"Server is HEALTHY: {health_data}\n")
        except Exception as e:
            print(f"❌ Error connecting to {base_url}/health: {e}")
            return False

    results: List[Dict[str, Any]] = []
    all_passed = True

    print("Running 8 demo scenarios over HTTP with real per-slot multipart uploads...\n")

    for sc_key, sc in DEMO_SCENARIOS.items():
        d = sc.data
        data_fields: Dict[str, str] = {
            "legal_name": str(d.get("legal_name") or ""),
            "trade_name": str(d.get("trade_name") or ""),
            "entity_type": str(d.get("entity_type") or "pvt_ltd"),
            "pan": str(d.get("pan") or ""),
            "gstin": str(d.get("gstin") or ""),
            "cin": str(d.get("cin") or ""),
            "llpin": str(d.get("llpin") or ""),
            "ifsc": str(d.get("ifsc") or ""),
            "bank_account_number": str(d.get("bank_account_number") or ""),
            "udyam_number": str(d.get("udyam_number") or ""),
            "udyam_category": str(d.get("udyam_category") or ""),
            "udyam_activity_type": str(d.get("udyam_activity_type") or ""),
            "address_line": str(d.get("address_line") or ""),
            "address_state_code": str(d.get("address_state_code") or ""),
            "email": str(d.get("email") or ""),
            "agreed_payment_days": str(d.get("agreed_payment_days") or "") if d.get("agreed_payment_days") is not None else "",
            # Explicitly omit scenario_key to verify pure form + per-slot uploads
            "scenario_key": "",
        }

        # Gather per-slot files
        doc_list = get_demo_documents(sc_key)
        files_to_upload: List[Tuple[str, Tuple[str, bytes, str]]] = []
        opened_files = []

        try:
            for doc_type, filename, file_path in doc_list:
                slot_field = DOC_SLOT_MAP.get(doc_type)
                if slot_field and os.path.exists(file_path):
                    with open(file_path, "rb") as fh:
                        content = fh.read()
                    files_to_upload.append(
                        (slot_field, (filename, content, "application/pdf"))
                    )

            # 1. Submit form via HTTP POST
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(
                    f"{base_url}/submissions",
                    data=data_fields,
                    files=files_to_upload,
                    follow_redirects=False,
                )

                if resp.status_code not in (302, 303):
                    print(f"❌ Failed to submit {sc_key}: HTTP {resp.status_code} - {resp.text[:200]}")
                    results.append({
                        "key": sc_key,
                        "name": sc.name,
                        "expected": sc.expected_outcome,
                        "actual": f"HTTP_{resp.status_code}",
                        "match": "FAIL",
                    })
                    all_passed = False
                    continue

                location = resp.headers.get("location", "")
                # Location looks like /submissions/<sub_id>/run
                sub_id = location.strip("/").split("/")[1]

                # 2. Poll /api/submissions/{sub_id} until decision is made
                actual_outcome = "timeout"
                soft_score = 0.0
                poll_deadline = time.time() + 20.0

                while time.time() < poll_deadline:
                    time.sleep(0.3)
                    stat_resp = client.get(f"{base_url}/api/submissions/{sub_id}")
                    if stat_resp.status_code == 200:
                        sub_data = stat_resp.json()
                        dec = sub_data.get("decision")
                        if dec and dec.get("outcome"):
                            actual_outcome = dec["outcome"]
                            soft_score = dec.get("soft_risk_score", 0.0)
                            break
                        if sub_data.get("status") in ("approved", "pending", "rejected", "human_review"):
                            actual_outcome = sub_data["status"]
                            break

                match_str = "PASS" if actual_outcome == sc.expected_outcome else "FAIL"
                if match_str == "FAIL":
                    all_passed = False

                results.append({
                    "key": sc_key,
                    "name": sc.name,
                    "expected": sc.expected_outcome,
                    "actual": actual_outcome,
                    "match": match_str,
                    "soft_score": soft_score,
                })
        finally:
            for fh in opened_files:
                fh.close()

    # 3. Print formatted terminal table
    header_sep = "=" * 80
    row_sep = "-" * 80
    print(header_sep)
    print("                    LIVE SMOKE TEST RESULTS OVER HTTP")
    print(header_sep)
    print(f"{'Scenario Key':24} | {'Expected':14} | {'Actual':14} | {'Status':8}")
    print(row_sep)
    for r in results:
        status_display = f"✓ {r['match']}" if r["match"] == "PASS" else f"✗ {r['match']}"
        print(f"{r['key']:24} | {r['expected']:14} | {r['actual']:14} | {status_display:8}")
    print(header_sep)

    if all_passed:
        print("\n🎉 ALL 8 SCENARIOS MATCHED GROUND TRUTH PERFECTLY OVER HTTP!\n")
    else:
        print("\n⚠️ SOME SCENARIOS FAILED TO MATCH EXPECTED OUTCOMES.\n")

    return all_passed


if __name__ == "__main__":
    target_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    success = run_smoke_test(target_url)
    sys.exit(0 if success else 1)
