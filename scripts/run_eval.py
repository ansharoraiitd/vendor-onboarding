"""
scripts/run_eval.py — Runs evaluation on the 38-record dataset (§11 of SPEC).
Outputs:
- False-Rejection Rate with n (e.g. "0/15 legitimate vendors incorrectly rejected (0.0%)")
- False-Approval Rate with n (e.g. "0/23 non-legitimate vendors incorrectly approved (0.0%)")
- 4x4 Confusion Matrix across {approved, pending, rejected, human_review}
- Per-check TP, FP, TN, FN, precision, recall
- Detail breakdown for Tune and Holdout splits
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Set

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Config, load_config
from app.adapters.mock import MockAdapter, AdapterResult
from app.eval_dataset import EVAL_RECORDS, EvalRecord, get_eval_dataset
from app.models import CheckResult as CheckResultModel
from app.pipeline.decision import decide
from app.pipeline.extractor import is_ai_extraction_enabled
from app.pipeline.rule_engine import run_all_checks
from app.validators import CheckResult


class EvalAdapter(MockAdapter):
    """External adapter for evaluation runs."""
    def call(self, adapter_name: str, primary_key: str, **kwargs: Any) -> AdapterResult:
        if "0000M" in primary_key:
            return AdapterResult(status="missing", source=adapter_name, raw={})
        if "XXXX" in primary_key:
            return AdapterResult(status="not_found", source=adapter_name, raw={})
        res = super().call(adapter_name, primary_key, **kwargs)
        if adapter_name == "MCAStatusAdapter" and "company_name" not in res.raw:
            res.raw["company_name"] = ""
        return res


def run_evaluation(records: Optional[List[EvalRecord]] = None, config: Optional[Config] = None) -> Dict[str, Any]:
    if records is None:
        records = get_eval_dataset()
    if config is None:
        policy_path = Path(__file__).resolve().parent.parent / "policy.yaml"
        config = load_config(str(policy_path))

    adapter = EvalAdapter()
    existing_bank_hmacs = {"SHARED_ACC_EXISTING_APPROVED_HMAC"}
    existing_pans = {"AAFFP7890Q": "Another Registered Company Limited"}
    outcomes = ["approved", "pending", "rejected", "human_review"]

    # 4x4 Confusion matrix: expected -> actual -> count
    confusion_matrix = {exp: {act: 0 for act in outcomes} for exp in outcomes}
    split_confusion = {
        "tune": {exp: {act: 0 for act in outcomes} for exp in outcomes},
        "holdout": {exp: {act: 0 for act in outcomes} for exp in outcomes},
    }

    # Per-check tracking: check_name -> {tp, fp, tn, fn}
    check_stats: Dict[str, Dict[str, int]] = defaultdict(lambda: {"tp": 0, "fp": 0, "tn": 0, "fn": 0})

    results_detail = []
    total_records = len(records)
    total_correct = 0

    legit_total = 0
    legit_false_rejected = 0

    non_legit_total = 0
    non_legit_false_approved = 0

    ai_enabled = is_ai_extraction_enabled()
    offline_needs_ai_count = 0
    offline_unreadable_count = 0

    for rec in records:
        is_needs_ai = getattr(rec, "needs_vision", False)
        if is_needs_ai and not ai_enabled:
            offline_needs_ai_count += 1
            offline_unreadable_count += 1

        sub_dict = dict(rec.submission)
        extracted_fields_by_doc = {}
        confidences_by_doc = {}
        raw_text_by_doc = {}
        uploaded_doc_types = list(rec.docs.keys())

        for dt, d_data in rec.docs.items():
            flds = dict(d_data.get("fields", {}))
            if "detected" in d_data:
                flds["_doc_type_detected"] = d_data["detected"]
            extracted_fields_by_doc[dt] = flds
            confidences_by_doc[dt] = dict(d_data.get("confidences", {}))
            raw_text_by_doc[dt] = d_data.get("raw_text", "")

        # Execute rule engine
        checks: List[CheckResult] = run_all_checks(
            submission=sub_dict,
            extracted_fields_by_doc=extracted_fields_by_doc,
            confidences_by_doc=confidences_by_doc,
            raw_text_by_doc=raw_text_by_doc,
            config=config,
            prior_failures=set(),
            adapter=adapter,
            uploaded_doc_types=uploaded_doc_types,
            existing_bank_account_hmacs=existing_bank_hmacs,
            existing_pans=existing_pans,
        )

        # Execute decision engine
        decision = decide(checks, config=config)
        actual_outcome = decision.outcome

        # Update confusion matrices
        confusion_matrix[rec.expected_outcome][actual_outcome] += 1
        split_confusion[rec.split][rec.expected_outcome][actual_outcome] += 1

        is_match = (actual_outcome == rec.expected_outcome)
        if is_match:
            total_correct += 1

        # False rejection: legitimate vendor that got rejected or failed approval
        if rec.is_legitimate:
            legit_total += 1
            if actual_outcome != "approved":
                legit_false_rejected += 1

        # False approval: non-legitimate vendor that was approved
        if not rec.is_legitimate:
            non_legit_total += 1
            if actual_outcome == "approved":
                non_legit_false_approved += 1

        # Per-check stats
        actual_failing = {c.check_name for c in checks if c.status in ("fail", "warn", "missing")}
        expected_failing = set(rec.expected_failing_checks)

        all_checks_seen = actual_failing.union(expected_failing)
        for cn in all_checks_seen:
            exp = cn in expected_failing
            act = cn in actual_failing
            if exp and act:
                check_stats[cn]["tp"] += 1
            elif not exp and act:
                check_stats[cn]["fp"] += 1
            elif exp and not act:
                check_stats[cn]["fn"] += 1
            else:
                check_stats[cn]["tn"] += 1

        results_detail.append({
            "id": rec.id,
            "split": rec.split,
            "name": rec.name,
            "category": rec.category,
            "notes": rec.notes,
            "expected_outcome": rec.expected_outcome,
            "actual_outcome": actual_outcome,
            "match": is_match,
            "is_legitimate": rec.is_legitimate,
            "is_adversarial": rec.is_adversarial,
            "needs_ai_extraction": is_needs_ai and not ai_enabled,
            "expected_failing_checks": rec.expected_failing_checks,
            "actual_failing_checks": list(actual_failing),
            "soft_risk_score": decision.soft_risk_score,
            "hard_fail_checks": decision.hard_fail_checks,
            "fixable_checks": decision.fixable_checks,
        })

    # Calculate per-check precision & recall
    per_check_metrics = {}
    for cn, s in check_stats.items():
        tp, fp, fn, tn = s["tp"], s["fp"], s["fn"], s["tn"]
        prec = tp / (tp + fp) if (tp + fp) > 0 else 1.0
        rec = tp / (tp + fn) if (tp + fn) > 0 else 1.0
        per_check_metrics[cn] = {
            "tp": tp, "fp": fp, "tn": tn, "fn": fn,
            "precision": prec,
            "recall": rec,
        }

    false_rejection_rate = (legit_false_rejected / legit_total) if legit_total > 0 else 0.0
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
            "non_legit_total": non_legit_total,
            "non_legit_false_approved": non_legit_false_approved,
            "false_approval_rate": false_approval_rate,
            "false_approval_text": f"{non_legit_false_approved}/{non_legit_total} non-legitimate vendors incorrectly approved ({false_approval_rate:.1%})",
            "tune_total": sum(1 for r in records if r.split == "tune"),
            "holdout_total": sum(1 for r in records if r.split == "holdout"),
            "ai_extraction_enabled": ai_enabled,
            "offline_needs_ai_count": offline_needs_ai_count,
            "offline_unreadable_count": offline_unreadable_count,
            "offline_notice": f"{offline_needs_ai_count} record requiring vision model marked 'needs AI extraction'; unreadable scans safely fail closed." if not ai_enabled else "AI extraction active.",
        },
        "confusion_matrix": confusion_matrix,
        "split_confusion": split_confusion,
        "per_check": per_check_metrics,
        "records": results_detail,
    }


def print_eval_report(res: Dict[str, Any]) -> None:
    s = res["summary"]
    print("=" * 78)
    print("           INDIAN VENDOR ONBOARDING — EVALUATION REPORT (SPEC §11)")
    print("=" * 78)
    print(f"Total Dataset Records: {s['total_records']} (Tune: {s['tune_total']}, Holdout: {s['holdout_total']})")
    print(f"Overall Accuracy:      {s['overall_accuracy']:.1%} ({s['total_correct']}/{s['total_records']} matched)")
    print()
    print("CRITICAL ACCURACY METRICS:")
    print(f"  • FALSE-REJECTION RATE:  {s['false_rejection_text']}")
    print(f"  • FALSE-APPROVAL RATE:   {s['false_approval_text']}")
    print("=" * 78)
    print()
    print("CONFUSION MATRIX (Expected Rows × Actual Columns):")
    outcomes = ["approved", "pending", "rejected", "human_review"]
    header = f"{'Expected':<14} | " + " | ".join(f"{o[:8]:>8}" for o in outcomes)
    print(header)
    print("-" * len(header))
    for exp in outcomes:
        row = f"{exp:<14} | "
        row += " | ".join(f"{res['confusion_matrix'][exp][act]:>8}" for act in outcomes)
        print(row)
    print()
    print("PER-CHECK PRECISION & RECALL:")
    print(f"{'Check Name':<30} | {'TP':>3} {'FP':>3} {'FN':>3} | {'Precision':>9} | {'Recall':>9}")
    print("-" * 65)
    for cn, m in sorted(res["per_check"].items()):
        print(f"{cn:<30} | {m['tp']:>3} {m['fp']:>3} {m['fn']:>3} | {m['precision']:>8.1%} | {m['recall']:>8.1%}")
    print()
    print("INDIVIDUAL RECORD OUTCOMES:")
    print(f"{'ID':<6} | {'Split':<7} | {'Category':<16} | {'Expected':<12} | {'Actual':<12} | Match")
    print("-" * 78)
    for r in res["records"]:
        m_str = "✓ Pass" if r["match"] else "✗ FAIL"
        print(f"{r['id']:<6} | {r['split']:<7} | {r['category']:<16} | {r['expected_outcome']:<12} | {r['actual_outcome']:<12} | {m_str}")
    print("=" * 78)


if __name__ == "__main__":
    results = run_evaluation()
    print_eval_report(results)
