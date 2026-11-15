"""
Communication layer — OutboxNotifier (default) and SmtpNotifier stub.

OutboxNotifier writes to the `outbox` table so the UI can display and
manually resend messages. Toggle via config.notifier = "outbox" | "smtp".
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Outbox


TEMPLATES: dict[str, dict[str, str]] = {
    "approved": {
        "subject": "Your vendor registration has been approved",
        "body": (
            "Dear {legal_name},\n\n"
            "We are pleased to inform you that your vendor registration "
            "(Reference: {submission_id}) has been approved.\n\n"
            "You are now registered as an approved vendor.\n\n"
            "Regards,\nVendor Onboarding Team"
        ),
    },
    "pending": {
        "subject": "Action required: Please update your vendor registration",
        "body": (
            "Dear {legal_name},\n\n"
            "Your vendor registration requires some corrections before "
            "we can proceed.\n\n"
            "Please address the following:\n"
            "{fixable_items_text}\n\n"
            "Please log in and resubmit with the corrected information.\n\n"
            "Regards,\nVendor Onboarding Team"
        ),
    },
    "rejected": {
        "subject": "Your vendor registration could not be processed",
        "body": (
            "Dear {legal_name},\n\n"
            "We regret to inform you that your vendor registration "
            "(Reference: {submission_id}) could not be processed due to "
            "the following concern(s):\n\n"
            "{rejection_categories_text}\n\n"
            "If you believe this is an error, please contact our support team.\n\n"
            "Regards,\nVendor Onboarding Team"
        ),
    },
    "human_review": {
        "subject": "Your vendor registration is under review",
        "body": (
            "Dear {legal_name},\n\n"
            "Your vendor registration (Reference: {submission_id}) is "
            "currently under review by our team.\n\n"
            "We will notify you once the review is complete. "
            "This typically takes 2–3 business days.\n\n"
            "Regards,\nVendor Onboarding Team"
        ),
    },
}


def _render_template(template_name: str, context: dict) -> tuple[str, str]:
    """Render subject and body from template name and context dict."""
    tmpl = TEMPLATES.get(template_name, TEMPLATES["human_review"])
    subject = tmpl["subject"]
    body = tmpl["body"].format(**{k: str(v) for k, v in context.items()})
    return subject, body


class OutboxNotifier:
    """Writes outgoing emails to the `outbox` table for UI display."""

    def __init__(self, db: Session) -> None:
        self._db = db

    def send(
        self,
        submission_id: str,
        recipient_email: str,
        template: str,
        context: dict,
    ) -> str:
        """Write an outbox row. Returns the outbox row id."""
        subject, body = _render_template(template, context)
        entry = Outbox(
            id=str(uuid.uuid4()),
            submission_id=submission_id,
            recipient=recipient_email,
            template=template,
            subject=subject,
            body=body,
            status="queued",
            queued_at=datetime.now(timezone.utc).isoformat(),
        )
        self._db.add(entry)
        self._db.commit()
        self._db.refresh(entry)
        return entry.id


class SmtpNotifier:
    """Real SMTP notifier — not implemented in v1."""

    def send(
        self,
        submission_id: str,
        recipient_email: str,
        template: str,
        context: dict,
    ) -> str:
        raise NotImplementedError(
            "SmtpNotifier is not wired in v1. Set config.notifier = 'outbox'."
        )
