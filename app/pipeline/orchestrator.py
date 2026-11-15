"""
Pipeline orchestrator.

run_pipeline(submission_id, db) is called as a FastAPI BackgroundTask.
It runs:
  1. Extraction (stub)
  2. Rule engine (all checks)
  3. Decision engine
  4. Notification (OutboxNotifier)
  5. Audit log entry

Each step writes events to the DB so the SSE endpoint can stream them.
"""
from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from sqlalchemy.orm import Session

from app.adapters.mock import MockAdapter
from app.check_categories import get_fixable_label, unique_categories
from app.communication.notifier import OutboxNotifier
from app.config import Config, load_config
import app.database
from app.models import (
    AuditEntry,
    CheckResult as CheckResultRow,
    Decision as DecisionRow,
    Document,
    PipelineEvent,
    VendorSubmission,
)
from app.pipeline.decision import decide
from app.pipeline.extractor import ExtractionResult, extract
from app.pipeline.rule_engine import run_all_checks
from app.validators import CheckResult


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_event(
    db: Session,
    submission_id: str,
    run_id: str,
    stage: str,
    check_name: str,
    status: str,
    severity: str,
    message: str,
    score_contribution: float,
    elapsed_ms: int,
) -> None:
    """Write a pipeline event row (used for SSE streaming)."""
    ev = PipelineEvent(
        id=str(uuid.uuid4()),
        submission_id=submission_id,
        run_id=run_id,
        stage=stage,
        check_name=check_name,
        status=status,
        severity=severity,
        message=message,
        score_contribution=score_contribution,
        elapsed_ms=elapsed_ms,
        created_at=_now_iso(),
    )
    db.add(ev)
    db.commit()


from app.audit_chain import append_audit_entry


def _append_audit(
    db: Session,
    submission_id: str,
    event_type: str,
    payload: Dict[str, Any],
) -> str:
    """Append one entry to the hash chain inside a single transaction."""
    return append_audit_entry(db, submission_id, event_type, payload)


def _write_check_result_row(
    db: Session,
    submission_id: str,
    run_id: str,
    r: CheckResult,
) -> None:
    # Extract minimum field confidence from check result evidence or attribute
    conf_val = getattr(r, "confidence", None)
    if conf_val is None and isinstance(r.evidence, dict):
        conf_val = r.evidence.get("confidence")

    row = CheckResultRow(
        id=str(uuid.uuid4()),
        submission_id=submission_id,
        run_id=run_id,
        check_name=r.check_name,
        status=r.status,
        severity=r.severity,
        evidence=json.dumps(r.evidence or {}),
        score_contribution=r.score_contribution or 0.0,
        confidence=conf_val if conf_val is not None else 1.0,
        explanation=r.explanation or "",
        evaluated_at=_now_iso(),
    )
    db.add(row)
    db.commit()


async def run_pipeline(submission_id: str, db: Optional[Session] = None) -> None:
    """
    Main pipeline entry point. Called as a background task.
    Opens its own DB session so it doesn't share with the request session.
    """
    should_close = False
    if db is None:
        db = app.database.SessionLocal()
        should_close = True
    config: Config = load_config()
    run_id = str(uuid.uuid4())
    start = time.monotonic()

    try:
        submission_row: Optional[VendorSubmission] = (
            db.query(VendorSubmission).filter(VendorSubmission.id == submission_id).first()
        )
        if not submission_row:
            return

        # Mark as processing
        submission_row.status = "processing"
        db.commit()

        _write_event(
            db, submission_id, run_id,
            stage="pipeline", check_name="pipeline_start",
            status="pass", severity="soft",
            message="Pipeline started",
            score_contribution=0,
            elapsed_ms=0,
        )

        # ---------------------------------------------------------------- #
        # 1. EXTRACTION
        # ---------------------------------------------------------------- #
        docs: List[Document] = (
            db.query(Document).filter(Document.submission_id == submission_id).all()
        )
        submission_dict = _submission_to_dict(submission_row)
        extracted_fields_by_doc: Dict[str, Dict] = {}
        confidences_by_doc: Dict[str, Dict] = {}
        raw_text_by_doc: Dict[str, str] = {}
        uploaded_doc_types: List[str] = []

        for doc in docs:
            uploaded_doc_types.append(doc.doc_type)
            result: ExtractionResult = extract(
                doc_path=doc.storage_path or "",
                doc_type=doc.doc_type,
                submission_fields=submission_dict,
            )
            # Tag detected document type into extracted fields
            result.fields["_doc_type_detected"] = result.doc_type_detected
            result.fields["_extractor_type"] = result.extractor_type
            result.fields["_cached"] = result.cached
            extracted_fields_by_doc[doc.doc_type] = result.fields
            confidences_by_doc[doc.doc_type] = result.confidences
            raw_text_by_doc[doc.doc_type] = result.raw_text

            # Persist extracted_fields and PDF metadata back to document row
            doc.extracted_fields = json.dumps(result.fields)
            doc.doc_type_detected = result.doc_type_detected
            doc.cached = result.cached
            if "_pdf_producer" in result.fields:
                doc.pdf_producer = result.fields["_pdf_producer"]
            if "_pdf_creation_date" in result.fields:
                doc.pdf_creation_date = result.fields["_pdf_creation_date"]
            if "_pdf_mod_date" in result.fields:
                doc.pdf_mod_date = result.fields["_pdf_mod_date"]
            if result.confidences:
                doc.extraction_confidence = sum(result.confidences.values()) / len(result.confidences)

            db.commit()

            cache_tag = " [Cached Extraction]" if result.cached else ""
            _write_event(
                db, submission_id, run_id,
                stage="extraction",
                check_name=f"extract_{doc.doc_type}",
                status="pass" if not result.error else "fail",
                severity="soft",
                message=f"Extracted {len(result.fields)} fields from {doc.doc_type}{cache_tag}" + (
                    f" (error: {result.error})" if result.error else ""
                ),
                score_contribution=0,
                elapsed_ms=int((time.monotonic() - start) * 1000),
            )

        _append_audit(
            db, submission_id, "extraction_complete",
            {"docs_extracted": len(docs), "run_id": run_id},
        )

        # ---------------------------------------------------------------- #
        # 2. RULE ENGINE
        # ---------------------------------------------------------------- #
        # Collect prior failures (high-confidence) for repeat escalation
        prior_failures: Set[str] = _get_prior_failures(
            db, submission_id, run_id,
            min_confidence=getattr(
                getattr(config, "extraction", None), "min_confidence", 0.80
            ),
        )

        # Query existing approved/pending/human_review vendors' bank HMACs (DV2) and PANs (DV1)
        existing_hmacs: Set[str] = set(
            r[0] for r in db.query(VendorSubmission.bank_account_number)
            .filter(
                VendorSubmission.id != submission_id,
                VendorSubmission.bank_account_number.isnot(None),
                VendorSubmission.status.in_(["approved", "pending", "human_review"]),
            )
            .all()
            if r[0]
        )
        existing_pans: Dict[str, str] = {
            r[0]: r[1] for r in db.query(VendorSubmission.pan, VendorSubmission.legal_name)
            .filter(
                VendorSubmission.id != submission_id,
                VendorSubmission.pan.isnot(None),
                VendorSubmission.status.in_(["approved", "pending", "human_review"]),
            )
            .all()
            if r[0]
        }

        adapter = MockAdapter()
        check_results: List[CheckResult] = run_all_checks(
            submission=submission_dict,
            extracted_fields_by_doc=extracted_fields_by_doc,
            confidences_by_doc=confidences_by_doc,
            raw_text_by_doc=raw_text_by_doc,
            config=config,
            prior_failures=prior_failures,
            adapter=adapter,
            uploaded_doc_types=uploaded_doc_types,
            existing_bank_account_hmacs=existing_hmacs,
            existing_pans=existing_pans,
        )

        soft_score = 0.0
        for r in check_results:
            _write_check_result_row(db, submission_id, run_id, r)
            if r.severity == "soft" and r.status in ("fail", "warn"):
                soft_score += r.score_contribution or 0.0
            _write_event(
                db, submission_id, run_id,
                stage="validation",
                check_name=r.check_name,
                status=r.status,
                severity=r.severity,
                message=r.explanation or f"{r.check_name}: {r.status}",
                score_contribution=r.score_contribution or 0.0,
                elapsed_ms=int((time.monotonic() - start) * 1000),
            )
        soft_score = min(soft_score, 100.0)

        _append_audit(
            db, submission_id, "check_run_complete",
            {"run_id": run_id, "check_count": len(check_results),
             "soft_risk_score": soft_score},
        )

        # ---------------------------------------------------------------- #
        # 3. DECISION & MASTER RECORD UPDATE
        # ---------------------------------------------------------------- #
        decision = decide(check_results, config, soft_risk_score=soft_score)

        # Persist payment term cap days on vendor master record
        cap_result = next((r for r in check_results if r.check_name == "payment_term_cap"), None)
        if cap_result and cap_result.evidence:
            submission_row.payment_term_cap_days = cap_result.evidence.get("payment_term_cap_days")

        dec_row = DecisionRow(
            id=str(uuid.uuid4()),
            submission_id=submission_id,
            outcome=decision.outcome,
            hard_fail_checks=json.dumps(decision.hard_fail_checks),
            fixable_checks=json.dumps(decision.fixable_checks),
            soft_risk_score=decision.soft_risk_score,
            decided_at=_now_iso(),
            decided_by="system",
            llm_explanation=_generate_explanation(decision, check_results),
        )
        db.add(dec_row)

        submission_row.status = decision.outcome
        submission_row.soft_risk_score = decision.soft_risk_score
        db.commit()

        _write_event(
            db, submission_id, run_id,
            stage="decision",
            check_name="final_decision",
            status=decision.outcome,
            severity="hard" if decision.outcome == "rejected" else "soft",
            message=f"Decision: {decision.outcome.upper()}",
            score_contribution=decision.soft_risk_score,
            elapsed_ms=int((time.monotonic() - start) * 1000),
        )
        _append_audit(
            db, submission_id, "decision_made",
            {
                "outcome": decision.outcome,
                "soft_risk_score": decision.soft_risk_score,
                "hard_fail_checks": decision.hard_fail_checks,
                "fixable_checks": decision.fixable_checks,
                "run_id": run_id,
            },
        )

        # ---------------------------------------------------------------- #
        # 4. NOTIFICATION
        # ---------------------------------------------------------------- #
        email = submission_row.email or ""
        if email:
            notifier = OutboxNotifier(db)
            context = _build_notification_context(
                decision.outcome, submission_dict, decision, check_results
            )
            template = decision.outcome
            # Externally: human_review → pending (under review)
            notifier.send(submission_id, email, template, context)

            _write_event(
                db, submission_id, run_id,
                stage="notification",
                check_name="email_queued",
                status="pass",
                severity="soft",
                message=f"Email queued to {email}",
                score_contribution=0,
                elapsed_ms=int((time.monotonic() - start) * 1000),
            )
            _append_audit(
                db, submission_id, "notification_sent",
                {"recipient": email, "template": template},
            )

    except Exception as exc:  # noqa: BLE001
        # On error, set status to 'error' (distinct from pending)
        if submission_row:
            submission_row.status = "error"
            db.commit()
        _write_event(
            db, submission_id, run_id,
            stage="pipeline", check_name="pipeline_error",
            status="fail", severity="hard",
            message=f"Pipeline error: {exc}",
            score_contribution=0,
            elapsed_ms=int((time.monotonic() - start) * 1000),
        )
        _append_audit(
            db, submission_id, "pipeline_error",
            {"error": str(exc), "run_id": run_id},
        )
    finally:
        if should_close:
            db.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _submission_to_dict(row: VendorSubmission) -> Dict[str, Any]:
    return {
        "id": row.id,
        "legal_name": row.legal_name or "",
        "trade_name": row.trade_name or "",
        "entity_type": row.entity_type or "",
        "pan": row.pan or "",
        "gstin": row.gstin or "",
        "cin": row.cin or "",
        "llpin": row.llpin or "",
        "ifsc": row.ifsc or "",
        "bank_account_number": row.bank_account_number or "",   # HMAC digest for duplicate comparison
        "bank_account_number_last4": row.bank_account_number_last4 or "",
        "udyam_number": row.udyam_number or "",
        "udyam_category": row.udyam_category or "",
        "udyam_activity_type": row.udyam_activity_type or "",
        "address_line": row.address_line or "",
        "address_state_code": row.address_state_code or "",
        "email": row.email or "",
        "agreed_payment_days": row.agreed_payment_days,
        "attempt_no": row.attempt_no or 1,
    }


def _get_prior_failures(
    db: Session,
    submission_id: str,
    current_run_id: str,
    min_confidence: float = 0.80,
) -> Set[str]:
    """
    Return check_names that failed in a PRIOR run (not the current run_id)
    where the extracted field confidence was >= min_confidence.
    Low-confidence prior failures (confidence < min_confidence) do NOT count
    toward repeat-failure escalation (§3.13 / §11 of SPEC).
    """
    rows = (
        db.query(CheckResultRow)
        .filter(
            CheckResultRow.submission_id == submission_id,
            CheckResultRow.run_id != current_run_id,
            CheckResultRow.status == "fail",
            CheckResultRow.severity.in_(["hard", "fixable"]),
            (CheckResultRow.confidence >= min_confidence) | (CheckResultRow.confidence.is_(None)),
        )
        .all()
    )
    return {r.check_name for r in rows}


def _generate_explanation(decision: Any, check_results: List[CheckResult]) -> str:
    """
    Generate a plain-language LLM explanation placeholder.
    In production, call Gemini here with a prompt template.
    """
    outcome = decision.outcome
    if outcome == "approved":
        return (
            "All validation checks passed. The vendor's identity, registration, "
            "and banking details have been verified successfully."
        )
    if outcome == "rejected":
        checks = ", ".join(decision.hard_fail_checks[:3])
        return (
            f"The submission could not be approved due to fundamental "
            f"verification failures ({checks}). These issues cannot be resolved "
            f"by resubmission."
        )
    if outcome == "pending":
        checks = ", ".join(decision.fixable_checks[:3])
        return (
            f"The submission is pending because some information needs to be "
            f"corrected or provided ({checks}). Please address the listed items "
            f"and resubmit."
        )
    # human_review
    return (
        "The submission requires manual review by our compliance team. "
        "You will be notified once the review is complete (typically 2–3 business days)."
    )


def _build_notification_context(
    outcome: str,
    submission: Dict[str, Any],
    decision: Any,
    check_results: List[CheckResult],
) -> Dict[str, Any]:
    ctx: Dict[str, Any] = {
        "legal_name": submission.get("legal_name", "Vendor"),
        "submission_id": submission.get("id", ""),
        "decided_at": _now_iso(),
    }
    if outcome == "pending":
        items = []
        for cn in decision.fixable_checks:
            label = get_fixable_label(cn)
            if label not in items:
                items.append(label)
        ctx["fixable_items_text"] = "\n".join(f"• {i}" for i in items) or "• Please review your submission."
    if outcome == "rejected":
        cats = unique_categories(decision.hard_fail_checks)
        ctx["rejection_categories_text"] = "\n".join(f"• {c}" for c in cats) or "• Verification issue"
    return ctx
