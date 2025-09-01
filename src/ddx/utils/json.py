# src/ddx/utils/json.py
from __future__ import annotations
import json, re
from typing import Any


def _json_loads_lenient(s: str) -> Any:
    try:
        return json.loads(s)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", s)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                pass
    return {"raw": s, "parse_error": True}
