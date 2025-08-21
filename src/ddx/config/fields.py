from __future__ import annotations
import json, re
from pathlib import Path
from typing import Any, Dict, List

def load_field_config(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {"version": "0", "fields": {}}

def build_registry_from_field_config(field_cfg: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    fields = (field_cfg or {}).get("fields") or {}
    for key, fcfg in fields.items():
        doc_cat = fcfg.get("doc_category") or ""
        doc_sub = fcfg.get("doc_subcategory") or ""
        dp = key.split(".")[-1].replace("_", " ").title() or "Data Point"
        out.append({
            "_key": key,
            "Sections": doc_cat,
            "Sub Section/Document": doc_sub,
            "Data Point": dp,
            "_source_type": "single_doc",
            "_cfg": fcfg,
        })
    return out

def index_registry(fields: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {r["_key"]: r for r in fields if r.get("_key")}

def slugify(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s
