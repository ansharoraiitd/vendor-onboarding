"""
app/models.py — SQLAlchemy ORM models (§2 of spec).

All PKs are String (UUID v4).
Dates stored as TEXT (ISO-8601 strings).
No FK enforcement (SQLite ignores FK by default).
"""
from __future__ import annotations

from sqlalchemy import Boolean, Column, Float, Integer, String, Text
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class VendorSubmission(Base):
    __tablename__ = "vendor_submission"

    id = Column(String, primary_key=True)
    created_at = Column(String, nullable=False)
    status = Column(String, nullable=False, default="draft")

    legal_name = Column(String, nullable=False)
    trade_name = Column(String, nullable=True)
    entity_type = Column(String, nullable=False)

    pan = Column(String, nullable=True)
    gstin = Column(String, nullable=True)
    cin = Column(String, nullable=True)
    llpin = Column(String, nullable=True)

    ifsc = Column(String, nullable=True)
    bank_account_number = Column(String, nullable=True)       # HMAC-SHA256 digest
    bank_account_number_last4 = Column(String, nullable=True)

    udyam_number = Column(String, nullable=True)
    udyam_category = Column(String, nullable=True)
    udyam_activity_type = Column(String, nullable=True)

    address_line = Column(Text, nullable=True)
    address_state_code = Column(String, nullable=True)
    email = Column(String, nullable=True)

    raw_json = Column(Text, nullable=True)

    soft_risk_score = Column(Float, nullable=True, default=0.0)
    payment_term_cap_days = Column(Integer, nullable=True)
    agreed_payment_days = Column(Integer, nullable=True)      # buyer-side input; NULL → 15-day default
    attempt_no = Column(Integer, nullable=False, default=1)

    def __repr__(self) -> str:
        return (
            f"<VendorSubmission id={self.id!r} legal_name={self.legal_name!r} "
            f"status={self.status!r} attempt_no={self.attempt_no}>"
        )


class Document(Base):
    __tablename__ = "document"

    id = Column(String, primary_key=True)
    submission_id = Column(String, nullable=False)
    doc_type = Column(String, nullable=False)

    filename = Column(String, nullable=True)
    storage_path = Column(String, nullable=True)
    sha256 = Column(String, nullable=True)

    pdf_producer = Column(String, nullable=True)
    pdf_creation_date = Column(String, nullable=True)
    pdf_mod_date = Column(String, nullable=True)

    extracted_fields = Column(Text, nullable=True)
    extraction_confidence = Column(Float, nullable=True)
    doc_type_detected = Column(String, nullable=True)
    cached = Column(Boolean, nullable=True, default=False)

    uploaded_at = Column(String, nullable=False)

    def __repr__(self) -> str:
        return (
            f"<Document id={self.id!r} submission_id={self.submission_id!r} "
            f"doc_type={self.doc_type!r}>"
        )


class CheckResult(Base):
    __tablename__ = "check_result"

    id = Column(String, primary_key=True)
    submission_id = Column(String, nullable=False)
    run_id = Column(String, nullable=False)
    check_name = Column(String, nullable=False)
    status = Column(String, nullable=False)               # pass / fail / warn / missing
    severity = Column(String, nullable=False)             # hard / fixable / soft / escalate
    evidence = Column(Text, nullable=True)
    score_contribution = Column(Float, nullable=False, default=0.0)
    confidence = Column(Float, nullable=True, default=1.0)
    explanation = Column(Text, nullable=True)
    evaluated_at = Column(String, nullable=False)

    def __repr__(self) -> str:
        return (
            f"<CheckResult id={self.id!r} check_name={self.check_name!r} "
            f"status={self.status!r} severity={self.severity!r}>"
        )


class Decision(Base):
    __tablename__ = "decision"

    id = Column(String, primary_key=True)
    submission_id = Column(String, nullable=False)
    outcome = Column(String, nullable=False)
    hard_fail_checks = Column(Text, nullable=True)
    fixable_checks = Column(Text, nullable=True)
    soft_risk_score = Column(Float, nullable=True)
    decided_at = Column(String, nullable=False)
    decided_by = Column(String, nullable=False, default="system")
    override_reason = Column(Text, nullable=True)
    llm_explanation = Column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<Decision id={self.id!r} submission_id={self.submission_id!r} "
            f"outcome={self.outcome!r}>"
        )


class AuditEntry(Base):
    __tablename__ = "audit_entry"

    id = Column(String, primary_key=True)
    seq = Column(Integer, nullable=True)   # auto-assigned via MAX(seq)+1 in audit writer
    submission_id = Column(String, nullable=True)
    event_type = Column(String, nullable=False)
    payload = Column(Text, nullable=False)
    prev_hash = Column(String, nullable=False)
    entry_hash = Column(String, nullable=False)
    created_at = Column(String, nullable=False)

    @property
    def current_hash(self) -> str:
        return self.entry_hash

    def __repr__(self) -> str:
        return (
            f"<AuditEntry seq={self.seq} event_type={self.event_type!r} "
            f"entry_hash={self.entry_hash[:12]!r}...>"
        )


class Outbox(Base):
    __tablename__ = "outbox"

    id = Column(String, primary_key=True)
    submission_id = Column(String, nullable=False)
    recipient = Column(String, nullable=False)
    subject = Column(String, nullable=False)
    body = Column(Text, nullable=True)
    template = Column(String, nullable=False)
    status = Column(String, nullable=False, default="queued")
    queued_at = Column(String, nullable=False)
    sent_at = Column(String, nullable=True)
    error = Column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<Outbox id={self.id!r} submission_id={self.submission_id!r} "
            f"template={self.template!r} status={self.status!r}>"
        )


class PipelineEvent(Base):
    """Transient pipeline events streamed via SSE. Written as pipeline progresses."""
    __tablename__ = "pipeline_event"

    id = Column(String, primary_key=True)
    submission_id = Column(String, nullable=False)
    run_id = Column(String, nullable=False)
    stage = Column(String, nullable=False)         # extraction/validation/decision/notification
    check_name = Column(String, nullable=False)
    status = Column(String, nullable=False)
    severity = Column(String, nullable=False)
    message = Column(Text, nullable=True)
    score_contribution = Column(Float, nullable=False, default=0.0)
    elapsed_ms = Column(Integer, nullable=False, default=0)
    created_at = Column(String, nullable=False)

    def __repr__(self) -> str:
        return (
            f"<PipelineEvent id={self.id!r} stage={self.stage!r} "
            f"check_name={self.check_name!r} status={self.status!r}>"
        )
