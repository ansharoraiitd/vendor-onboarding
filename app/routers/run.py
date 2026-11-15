"""
SSE run-stream router — streams pipeline events from DB to the browser.
Replays historical events on reconnect so page refresh works correctly.
"""
from __future__ import annotations

import asyncio
import json
from typing import AsyncGenerator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import PipelineEvent

router = APIRouter()


async def _event_generator(
    sub_id: str,
    db: Session,
) -> AsyncGenerator[str, None]:
    """
    1. Replay all existing pipeline_event rows for this submission (sorted by created_at).
    2. Poll for new rows until a "final_decision" event is seen or timeout.
    """
    seen_ids: set[str] = set()
    done = False
    timeout_secs = 120
    elapsed = 0.0
    poll_interval = 0.5

    while not done and elapsed < timeout_secs:
        rows = (
            db.query(PipelineEvent)
            .filter(PipelineEvent.submission_id == sub_id)
            .order_by(PipelineEvent.created_at.asc())
            .all()
        )
        for row in rows:
            if row.id in seen_ids:
                continue
            seen_ids.add(row.id)
            payload = {
                "stage": row.stage,
                "check_name": row.check_name,
                "status": row.status,
                "severity": row.severity,
                "message": row.message or "",
                "score_contribution": row.score_contribution,
                "elapsed_ms": row.elapsed_ms,
            }
            yield f"data: {json.dumps(payload)}\n\n"
            if row.check_name == "final_decision":
                done = True

        if not done:
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

    yield "data: {\"stage\":\"done\",\"check_name\":\"stream_end\",\"status\":\"pass\",\"severity\":\"soft\",\"message\":\"Stream complete\",\"score_contribution\":0,\"elapsed_ms\":0}\n\n"


@router.get("/submissions/{sub_id}/run-stream")
async def run_stream(sub_id: str, db: Session = Depends(get_db)):
    return StreamingResponse(
        _event_generator(sub_id, db),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
