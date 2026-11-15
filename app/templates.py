"""
Shared Jinja2 templates instance with custom filters.
All routers import from here to get consistent template rendering.
"""
from __future__ import annotations

import json
import os

from fastapi.templating import Jinja2Templates

from app.pipeline.extractor import get_extractor_mode, is_ai_extraction_enabled


def is_demo_mode() -> bool:
    return os.getenv("DEMO_MODE", "true").lower() in ("true", "1", "yes")


templates = Jinja2Templates(directory="templates")
templates.env.filters["from_json"] = lambda s: json.loads(s) if s else []
templates.env.filters["min"] = min
templates.env.filters["max"] = max
templates.env.globals["is_ai_extraction_enabled"] = is_ai_extraction_enabled
templates.env.globals["get_extractor_mode"] = get_extractor_mode
templates.env.globals["is_demo_mode"] = is_demo_mode
