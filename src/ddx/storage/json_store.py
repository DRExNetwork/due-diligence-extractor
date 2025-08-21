from __future__ import annotations
import json, re
from pathlib import Path
from typing import Dict, Any, Optional

def save_json_outputs(out: Dict[str, Any],
                      store_dir: Path,
                      project_id: str,
                      run_id: Optional[str],
                      args_meta: Dict[str, Any]) -> Dict[str, Any]:
    from datetime import datetime, timezone
    rid = run_id or datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")

    run_dir = store_dir / "runs" / project_id
    run_dir.mkdir(parents=True, exist_ok=True)
    run_path = run_dir / f"{rid}.json"

    snapshot = {"meta": {"run_id": rid, **args_meta}, "results": out["results"]}
    run_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")

    fields_dir = store_dir / "fields" / project_id
    fields_dir.mkdir(parents=True, exist_ok=True)

    def _slug(s: str) -> str:
        return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")

    stored_fields = []
    for r in out["results"]:
        key = r.get("key", "")
        slug = _slug(key)
        latest_path = fields_dir / f"{slug}.latest.json"
        history_path = fields_dir / f"{slug}.history.jsonl"
        latest_path.write_text(json.dumps({"run_id": rid, **r}, indent=2), encoding="utf-8")
        with history_path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps({"run_id": rid, **r}) + "\n")
        stored_fields.append({"key": key, "latest": str(latest_path), "history": str(history_path)})

    return {"run_json": str(run_path), "fields": stored_fields, "store_dir": str(store_dir)}
