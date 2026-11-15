"""
app/routers/eval.py — Evaluation dashboard router (§12.6 of SPEC).
"""
from __future__ import annotations

from typing import Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.templates import templates
from scripts.run_eval import run_evaluation
from scripts.run_e2e_eval import run_e2e_evaluation

router = APIRouter()

# In-memory cache for latest eval results
_LAST_EVAL_CACHE: dict = {}


async def _get_or_run_eval(mode: Optional[str] = None) -> tuple[dict, dict, str]:
    global _LAST_EVAL_CACHE
    if not _LAST_EVAL_CACHE or mode is not None:
        res_mocked = run_evaluation()
        res_e2e = await run_e2e_evaluation(mode=mode)
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        _LAST_EVAL_CACHE = {"data": res_mocked, "e2e_data": res_e2e, "timestamp": ts}
    return _LAST_EVAL_CACHE["data"], _LAST_EVAL_CACHE["e2e_data"], _LAST_EVAL_CACHE["timestamp"]


@router.get("/eval", response_class=HTMLResponse)
async def eval_page(request: Request, mode: Optional[str] = Query(None)):
    data, e2e_data, ts = await _get_or_run_eval(mode=mode)
    return templates.TemplateResponse(
        request=request,
        name="eval.html",
        context={"data": data, "e2e_data": e2e_data, "timestamp": ts},
    )


@router.post("/eval/run")
async def eval_run(
    request: Request,
    mode: Optional[str] = Query(None),
):
    global _LAST_EVAL_CACHE
    res_mocked = run_evaluation()
    res_e2e = await run_e2e_evaluation(mode=mode)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    _LAST_EVAL_CACHE = {"data": res_mocked, "e2e_data": res_e2e, "timestamp": ts}
    return RedirectResponse(url="/eval", status_code=303)
