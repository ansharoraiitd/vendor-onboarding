"""
app/audit_chain.py — Hash-chained audit log with SQLite BEGIN IMMEDIATE semantics (SPEC §6).
Formula: current_hash = sha256(f"{prev_hash}:{event_type}:{payload_json}:{timestamp}".encode("utf-8")).hexdigest()
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session
from app.models import AuditEntry


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def compute_hash(prev_hash: str, event_type: str, payload_json: str, timestamp: str) -> str:
    """Computes sha256(prev_hash:event_type:payload_json:timestamp)."""
    data = f"{prev_hash}:{event_type}:{payload_json}:{timestamp}".encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def append_audit_entry(
    db: Session,
    submission_id: Optional[str],
    event_type: str,
    payload: Dict[str, Any],
) -> str:
    """
    Append one entry to the hash chain inside a single BEGIN IMMEDIATE transaction.
    Guarantees monotonic sequence ordering without chain forks.
    """
    raw = db.get_bind().raw_connection()
    cur = raw.cursor()
    try:
        cur.execute("BEGIN IMMEDIATE")
        cur.execute("SELECT entry_hash, seq FROM audit_entry ORDER BY seq DESC LIMIT 1")
        row = cur.fetchone()
        prev_hash = row[0] if row else "GENESIS"
        next_seq = (row[1] + 1) if row else 1

        timestamp = _now_iso()
        payload_dict = {**payload}
        if submission_id:
            payload_dict.setdefault("submission_id", submission_id)
        payload_dict.setdefault("event_type", event_type)
        payload_json = json.dumps(payload_dict, sort_keys=True, separators=(",", ":"))

        current_hash = compute_hash(prev_hash, event_type, payload_json, timestamp)
        entry_id = str(uuid.uuid4())

        cur.execute(
            """
            INSERT INTO audit_entry
                (id, seq, submission_id, event_type, payload, prev_hash, entry_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry_id,
                next_seq,
                submission_id,
                event_type,
                payload_json,
                prev_hash,
                current_hash,
                timestamp,
            ),
        )
        raw.commit()
        return current_hash
    except Exception:
        raw.rollback()
        raise
    finally:
        cur.close()
        raw.close()


def verify_audit_chain(db: Session) -> Dict[str, Any]:
    """
    Verifies the entire audit hash chain from genesis to head.
    Returns:
      valid: bool
      total_entries: int
      first_tampered_seq: Optional[int]
      error: Optional[str]
    """
    entries: List[AuditEntry] = (
        db.query(AuditEntry).order_by(AuditEntry.seq.asc()).all()
    )

    if not entries:
        return {
            "valid": True,
            "total_entries": 0,
            "first_tampered_seq": None,
            "error": None,
            "latest_hash": "GENESIS",
        }

    expected_prev = "GENESIS"
    for e in entries:
        # 1. Verify prev_hash link
        if e.prev_hash != expected_prev:
            return {
                "valid": False,
                "total_entries": len(entries),
                "first_tampered_seq": e.seq,
                "error": f"Broken chain link at seq {e.seq}: expected prev_hash '{expected_prev}', got '{e.prev_hash}'",
                "latest_hash": entries[-1].entry_hash,
            }

        # 2. Recompute current hash
        recomputed = compute_hash(e.prev_hash, e.event_type, e.payload, e.created_at)
        if recomputed != e.entry_hash:
            return {
                "valid": False,
                "total_entries": len(entries),
                "first_tampered_seq": e.seq,
                "error": f"Tampered entry detected at seq {e.seq}: recomputed hash '{recomputed[:16]}...' does not match stored hash '{e.entry_hash[:16]}...'",
                "latest_hash": entries[-1].entry_hash,
            }

        expected_prev = e.entry_hash

    return {
        "valid": True,
        "total_entries": len(entries),
        "first_tampered_seq": None,
        "error": None,
        "latest_hash": entries[-1].entry_hash,
    }


def demo_tamper_entry(db: Session, seq: Optional[int] = None) -> Dict[str, Any]:
    """
    Mutates payload of an entry in the database without updating hashes.
    Only permitted when DEMO_MODE=true.
    """
    demo_mode = os.getenv("DEMO_MODE", "true").lower() in ("true", "1", "yes")
    if not demo_mode:
        raise PermissionError("Demo tamper is disabled outside DEMO_MODE.")

    if seq is not None:
        entry = db.query(AuditEntry).filter(AuditEntry.seq == seq).first()
    else:
        # Pick latest entry or entry 1
        entry = db.query(AuditEntry).order_by(AuditEntry.seq.desc()).first()

    if not entry:
        raise ValueError("No audit entries available to tamper.")

    # Mutate payload directly via SQL to prevent SQLAlchemy auto-fixing or hooks
    try:
        data = json.loads(entry.payload)
        data["tampered_unauthorized_modification"] = True
        data["tampered_at"] = _now_iso()
        new_payload = json.dumps(data, sort_keys=True, separators=(",", ":"))
    except Exception:
        new_payload = entry.payload + '{"tampered": true}'

    raw = db.get_bind().raw_connection()
    cur = raw.cursor()
    try:
        cur.execute("UPDATE audit_entry SET payload = ? WHERE id = ?", (new_payload, entry.id))
        raw.commit()
    finally:
        cur.close()
        raw.close()

    return {
        "tampered": True,
        "tampered_seq": entry.seq,
        "tampered_id": entry.id,
        "message": f"Successfully tampered payload at seq {entry.seq} without updating hash.",
    }
