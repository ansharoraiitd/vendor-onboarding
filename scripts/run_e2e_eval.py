"""
scripts/run_e2e_eval.py — Runs End-to-End Pipeline Evaluation on the 24-record dataset.
Uses real physical PDFs and executes run_pipeline in isolated temporary database.
Computes:
- False-Rejection Rate with n
- False-Approval Rate with n
- 4x4 Confusion Matrix
- Table of every mismatch with the actual reason (does not hide or tune away mismatches)
- Before / After baseline tracking
- Extractor mode per record and circuit breaker reporting
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.security import compute_bank_account_hmac

import yaml

from app.models import CheckResult as CheckResultModel, Decision, Document, VendorSubmission
from app.pipeline.extractor import (
    get_extractor_mode,
    is_ai_extraction_enabled,
    is_circuit_breaker_tripped,
)
from app.pipeline.orchestrator import run_pipeline

E2E_YAML_PATH = Path("tests/fixtures/eval_set_e2e.yaml")
E2E_DOCS_DIR = Path("tests/fixtures/e2e_eval_docs")

# Frozen baseline results from previous run before parser & label fixes
BASELINE_PREVIOUS_RUN = {
    "overall_accuracy": 0.583,
    "total_correct": 14,
    "total_records": 24,
    "false_rejection_rate": 0.769,
    "false_approval_rate": 0.0,
    "mismatches_count": 10,
    "record_outcomes": {
        "E2E01": {"outcome": "approved", "match": True},
        "E2E02": {"outcome": "pending", "match": False, "reason": "gstin_state_code_match"},
        "E2E03": {"outcome": "pending", "match": False, "reason": "pan_card_name_match"},
        "E2E04": {"outcome": "approved", "match": True},
        "E2E05": {"outcome": "pending", "match": False, "reason": "gstin_state_code_match"},
        "E2E06": {"outcome": "pending", "match": False, "reason": "pan_card_name_match"},
        "E2E07": {"outcome": "pending", "match": False, "reason": "gstin_state_code_match"},
        "E2E08": {"outcome": "approved", "match": True},
        "E2E09": {"outcome": "pending", "match": False, "reason": "pan_card_name_match"},
        "E2E10": {"outcome": "pending", "match": False, "reason": "expected human_review"},
        "E2E11": {"outcome": "pending", "match": True},
        "E2E12": {"outcome": "pending", "match": False, "reason": "expected human_review"},
        "E2E13": {"outcome": "rejected", "match": True},
        "E2E14": {"outcome": "rejected", "match": True},
        "E2E15": {"outcome": "pending", "match": False, "reason": "expected rejected"},
        "E2E16": {"outcome": "pending", "match": False, "reason": "expected rejected"},
        "E2E17": {"outcome": "pending", "match": True},
        "E2E18": {"outcome": "pending", "match": True},
        "E2E19": {"outcome": "pending", "match": True},
        "E2E20": {"outcome": "pending", "match": True},
        "E2E21": {"outcome": "pending", "match": True},
        "E2E22": {"outcome": "pending", "match": True},
        "E2E23": {"outcome": "pending", "match": True},
        "E2E24": {"outcome": "pending", "match": True},
    },
}


async def run_e2e_evaluation(mode: Optional[str] = None) -> Dict[str, Any]:
    if mode:
        os.environ["EXTRACTOR_MODE"] = mode.strip().lower()

    with open(E2E_YAML_PATH, "r", encoding="utf-8") as f:
        records = yaml.safe_load(f)

    # Run in an isolated temporary SQLite database per SPEC §11
    import tempfile
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    import app.database
    from app.models import Base

    temp_db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    temp_db_path = temp_db_file.name
    temp_db_file.close()

    temp_engine = create_engine(f"sqlite:///{temp_db_path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=temp_engine)
    temp_SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=temp_engine)

    old_engine = app.database.engine
    old_SessionLocal = app.database.SessionLocal
    app.database.engine = temp_engine
    app.database.SessionLocal = temp_SessionLocal

    try:
        outcomes = ["approved", "pending", "rejected", "human_review"]
        confusion_matrix = {exp: {act: 0 for act in outcomes} for exp in outcomes}

        results_detail = []
        total_records = len(records)
        total_correct = 0

        legit_total = 0
        legit_false_rejected = 0

        legit_readable_total = 0
        legit_readable_false_rejected = 0

        legit_vision_total = 0
        legit_vision_false_rejected = 0

        non_legit_total = 0
        non_legit_false_approved = 0

        ai_enabled = is_ai_extraction_enabled()
        active_mode = get_extractor_mode()
        cb_tripped, cb_reason = is_circuit_breaker_tripped()

        needs_vision_count = 0
        offline_unreadable_count = 0

        secret = os.environ.get("HMAC_SECRET", "dev-secret-change-in-production")

        for rec in records:
            r_id = rec["id"]
            is_legit = rec.get("is_legitimate", False)
            needs_vision = rec.get("needs_vision", False)
            if needs_vision:
                needs_vision_count += 1
                if not ai_enabled:
                    offline_unreadable_count += 1

            db = temp_SessionLocal()
            sub_id = str(uuid.uuid4())
            acct_raw = rec.get("bank_account_number", "987654321001")
            acct_hmac = compute_bank_account_hmac(acct_raw)

            sub = VendorSubmission(
                id=sub_id,
                created_at="2026-11-13T12:00:00Z",
                status="submitted",
                legal_name=rec["name"],
                trade_name=rec["name"],
                entity_type=rec["entity_type"],
                pan=rec["pan"],
                gstin=rec["gstin"],
                cin=rec.get("cin"),
                llpin=rec.get("llpin"),
                ifsc=rec["ifsc"],
                bank_account_number=acct_hmac,
                bank_account_number_last4=acct_raw[-4:],
                address_line="101 Commercial Zone, Industrial Area",
                address_state_code=rec.get("address_state_code", "27"),
                email=f"{r_id.lower()}@vendor.example.com",
                attempt_no=1,
            )
            db.add(sub)
            db.flush()

            # Attach real generated PDFs
            r_dir = E2E_DOCS_DIR / r_id
            if r_dir.exists():
                for p in r_dir.glob("*.pdf"):
                    dt = (
                        "pan_card" if "pan" in p.name
                        else ("gst_certificate" if "gst" in p.name
                        else ("cancelled_cheque" if "cheque" in p.name
                        else ("coi" if "coi" in p.name
                        else ("llpin_cert" if "llp" in p.name else "unknown"))))
                    )
                    with open(p, "rb") as fh:
                        sha = hashlib.sha256(fh.read()).hexdigest()
                    db.add(
                        Document(
                            id=str(uuid.uuid4()),
                            submission_id=sub_id,
                            doc_type=dt,
                            filename=p.name,
                            storage_path=str(p),
                            sha256=sha,
                            uploaded_at="2026-11-13T12:00:00Z",
                        )
                    )

            db.commit()
            db.close()

            # Run full pipeline end-to-end in temporary DB
            await run_pipeline(sub_id)

            db = temp_SessionLocal()
            dec = db.query(Decision).filter(Decision.submission_id == sub_id).first()
            checks = db.query(CheckResultModel).filter(CheckResultModel.submission_id == sub_id).all()
            docs = db.query(Document).filter(Document.submission_id == sub_id).all()
            actual_outcome = dec.outcome if dec else "error"
            soft_score = dec.soft_risk_score if dec else 0.0

            # Inspect extractor types across attached documents
            extractor_types_seen = set()
            for d in docs:
                if d.extracted_fields:
                    try:
                        f_json = json.loads(d.extracted_fields)
                        if "_extractor_type" in f_json:
                            extractor_types_seen.add(f_json["_extractor_type"])
                    except Exception:
                        pass
            db.close()

            if extractor_types_seen:
                record_extractor_mode = ", ".join(sorted(extractor_types_seen))
            elif needs_vision and not ai_enabled:
                record_extractor_mode = "scan_unreadable_fail_closed"
            else:
                record_extractor_mode = "text_layer_regex"

            # Metrics & Ground Truth matching
            exp_outcome = rec["expected_outcome"]
            if exp_outcome == "not approved":
                # Per spec, non-approved outcome (pending or human_review) is compliant
                is_match = (actual_outcome in ("human_review", "pending", "rejected"))
                cm_key = "human_review" if actual_outcome == "human_review" else "pending"
                confusion_matrix[cm_key][actual_outcome] += 1
            else:
                is_match = (actual_outcome == exp_outcome)
                if exp_outcome in confusion_matrix:
                    confusion_matrix[exp_outcome][actual_outcome] += 1

            if is_match:
                total_correct += 1

            if is_legit:
                legit_total += 1
                if needs_vision:
                    legit_vision_total += 1
                    if actual_outcome != "approved":
                        legit_vision_false_rejected += 1
                else:
                    legit_readable_total += 1
                    if actual_outcome != "approved":
                        legit_readable_false_rejected += 1

                if actual_outcome != "approved":
                    legit_false_rejected += 1
            else:
                non_legit_total += 1
                if actual_outcome == "approved":
                    non_legit_false_approved += 1

            actual_failing = [c.check_name for c in checks if c.status in ("fail", "warn", "missing")]
            mismatch_reason = ""
            if not is_match:
                mismatch_reason = (
                    f"Expected '{exp_outcome}', but got '{actual_outcome}'. "
                    f"Failing checks: {', '.join(actual_failing) if actual_failing else 'none'}. "
                    f"Soft score: {soft_score}."
                )

            # Baseline comparison
            prev_data = BASELINE_PREVIOUS_RUN["record_outcomes"].get(r_id, {})
            prev_outcome = prev_data.get("outcome", "unknown")
            prev_match = prev_data.get("match", False)

            diff_note = ""
            if not prev_match and is_match:
                diff_note = "Resolved in this run"
            elif prev_match and not is_match:
                diff_note = "Regression"
            elif not is_match:
                diff_note = "Ongoing mismatch"
            else:
                diff_note = "Consistently passing"

            results_detail.append({
                "id": r_id,
                "name": rec["name"],
                "layout_style": rec.get("layout_style", ""),
                "notes": rec.get("notes", ""),
                "expected_outcome": exp_outcome,
                "actual_outcome": actual_outcome,
                "match": is_match,
                "prev_outcome": prev_outcome,
                "prev_match": prev_match,
                "diff_note": diff_note,
                "extractor_mode": record_extractor_mode,
                "is_legitimate": is_legit,
                "needs_vision": needs_vision,
                "needs_ai_extraction": needs_vision and not ai_enabled,
                "expected_failing_checks": rec.get("expected_failing_checks", []),
                "actual_failing_checks": actual_failing,
                "soft_risk_score": soft_score,
                "mismatch_reason": mismatch_reason,
            })

        false_rejection_rate = (legit_false_rejected / legit_total) if legit_total > 0 else 0.0
        legit_readable_fr_rate = (legit_readable_false_rejected / legit_readable_total) if legit_readable_total > 0 else 0.0
        legit_vision_fr_rate = (legit_vision_false_rejected / legit_vision_total) if legit_vision_total > 0 else 0.0
        false_approval_rate = (non_legit_false_approved / non_legit_total) if non_legit_total > 0 else 0.0
        overall_accuracy = (total_correct / total_records) if total_records > 0 else 0.0

        return {
            "summary": {
                "total_records": total_records,
                "total_correct": total_correct,
                "overall_accuracy": overall_accuracy,
                "legitimate_total": legit_total,
                "legitimate_false_rejected": legit_false_rejected,
                "false_rejection_rate": false_rejection_rate,
                "false_rejection_text": f"{legit_false_rejected}/{legit_total} legitimate vendors incorrectly rejected ({false_rejection_rate:.1%})",
                "legit_readable_total": legit_readable_total,
                "legit_readable_false_rejected": legit_readable_false_rejected,
                "legit_readable_fr_rate": legit_readable_fr_rate,
                "legit_readable_fr_text": f"{legit_readable_false_rejected}/{legit_readable_total} ({legit_readable_fr_rate:.1%})",
                "legit_vision_total": legit_vision_total,
                "legit_vision_false_rejected": legit_vision_false_rejected,
                "legit_vision_fr_rate": legit_vision_fr_rate,
                "legit_vision_fr_text": f"{legit_vision_false_rejected}/{legit_vision_total} ({legit_vision_fr_rate:.1%})",
                "non_legit_total": non_legit_total,
                "non_legit_false_approved": non_legit_false_approved,
                "false_approval_rate": false_approval_rate,
                "false_approval_text": f"{non_legit_false_approved}/{non_legit_total} non-legitimate vendors incorrectly approved ({false_approval_rate:.1%})",
                "needs_vision_count": needs_vision_count,
                "offline_unreadable_count": offline_unreadable_count,
                "ai_extraction_enabled": ai_enabled,
                "active_extractor_mode": active_mode,
                "circuit_breaker_tripped": cb_tripped,
                "circuit_breaker_reason": cb_reason,
                "mismatches_count": total_records - total_correct,
                "baseline": BASELINE_PREVIOUS_RUN,
            },
            "confusion_matrix": confusion_matrix,
            "records": results_detail,
            "mismatches": [r for r in results_detail if not r["match"]],
        }
    finally:
        # Restore database configuration and remove temporary file
        app.database.engine = old_engine
        app.database.SessionLocal = old_SessionLocal
        try:
            if os.path.exists(temp_db_path):
                os.remove(temp_db_path)
        except Exception:
            pass


def print_e2e_report(res: Dict[str, Any]) -> None:
    s = res["summary"]
    print("=" * 78)
    print("       END-TO-END PIPELINE EVALUATION REPORT (REAL GENERATED PDFS)")
    print("=" * 78)
    print(f"Extractor Mode:        {s['active_extractor_mode'].upper()} (AI Enabled: {s['ai_extraction_enabled']})")
    if s["circuit_breaker_tripped"]:
        print(f"⚠️ CIRCUIT BREAKER:   TRIPPED: {s['circuit_breaker_reason']}")
    print(f"Total Dataset Records: {s['total_records']}")
    print(f"Overall Accuracy:      {s['overall_accuracy']:.1%} ({s['total_correct']}/{s['total_records']} matched)")
    print(f"Baseline (Previous):   {s['baseline']['overall_accuracy']:.1%} ({s['baseline']['total_correct']}/{s['total_records']} matched)")
    print()
    print("CRITICAL ACCURACY METRICS:")
    print(f"  • FALSE-REJECTION RATE (OVERALL): {s['false_rejection_text']} (Prev: {s['baseline']['false_rejection_rate']:.1%})")
    print(f"    - Legit records fully readable:  {s['legit_readable_fr_text']}")
    print(f"    - Legit records needing vision:  {s['legit_vision_fr_text']}")
    print(f"  • FALSE-APPROVAL RATE:            {s['false_approval_text']} (Prev: {s['baseline']['false_approval_rate']:.1%})")
    print(f"  • VISION MODEL RECORDS:           {s['needs_vision_count']} marked needs_vision ({s['offline_unreadable_count']} unreadable in offline mode)")
    print("=" * 78)
    print()
    print("CONFUSION MATRIX (Expected Rows × Actual Columns):")
    print(f"{'Expected':14} | {'approved':8} | {'pending':8} | {'rejected':8} | {'human_review':12}")
    print("-" * 62)
    for exp, row in res["confusion_matrix"].items():
        print(f"{exp:14} | {row['approved']:8} | {row['pending']:8} | {row['rejected']:8} | {row['human_review']:12}")
    print("=" * 78)
    print()
    print("BEFORE / AFTER COMPARISON TABLE:")
    print(f"{'ID':6} | {'Prev Result':12} | {'Current':12} | {'Extractor Mode':22} | Status")
    print("-" * 78)
    for r in res["records"]:
        prev_str = "✓ Pass" if r["prev_match"] else f"✗ {r['prev_outcome']}"
        curr_str = "✓ Pass" if r["match"] else f"✗ {r['actual_outcome']}"
        print(f"{r['id']:6} | {prev_str:12} | {curr_str:12} | {r['extractor_mode'][:22]:22} | {r['diff_note']}")

    if res["mismatches"]:
        print("\n" + "!" * 78)
        print("REMAINING MISMATCH DETAILS (DO NOT HIDE OR TUNE AWAY):")
        print("!" * 78)
        for m in res["mismatches"]:
            print(f"[{m['id']}] {m['name']}:")
            print(f"  Reason: {m['mismatch_reason']}")
            print(f"  Notes:  {m['notes']}")
    else:
        print("\nAll 24/24 end-to-end pipeline records matched ground truth perfectly!")
    print("=" * 78)


def run_e2e_evaluation_sync(mode: Optional[str] = None) -> Dict[str, Any]:
    return asyncio.run(run_e2e_evaluation(mode=mode))


if __name__ == "__main__":
    res = asyncio.run(run_e2e_evaluation())
    print_e2e_report(res)
