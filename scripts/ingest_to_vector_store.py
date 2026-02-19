from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from ddx.llm.client import LLMClient


def slugify(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return (s or "uncategorized")[:60]


def category_store_name(category: str) -> str:
    # one vector store per category (global); project is an attribute filter
    return f"cat__{slugify(category)}"


def load_results(path: Path) -> List[Dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"Expected JSON list in {path}")
    return [x for x in data if isinstance(x, dict)]


def index_openai_files_by_filename(
    llm: LLMClient, *, purpose: Optional[str], limit: int = 1000
) -> Dict[str, str]:
    """
    filename -> file_id (newest wins due to desc order in client.list_files default)
    """
    out: Dict[str, str] = {}
    for f in llm.list_files(purpose=purpose, limit=limit, order="desc"):
        name = f.get("filename")
        fid = f.get("id")
        if isinstance(name, str) and isinstance(fid, str) and name and fid:
            out.setdefault(name, fid)
    return out


def extract_categories(item: Dict[str, Any]) -> List[str]:
    """
    Supports:
      - single: item["category"] : str
      - multi:  item["categories"] : [{name: str, ...}, ...] or [str, ...]
    """
    # multi
    raw = item.get("categories")
    if isinstance(raw, list) and raw:
        cats: List[str] = []
        for c in raw:
            if isinstance(c, dict) and isinstance(c.get("name"), str) and c["name"].strip():
                cats.append(c["name"].strip())
            elif isinstance(c, str) and c.strip():
                cats.append(c.strip())

        # de-dupe keep order
        seen = set()
        deduped = [c for c in cats if not (c in seen or seen.add(c))]
        if deduped:
            return deduped

    # single
    c = item.get("category")
    if isinstance(c, str) and c.strip():
        return [c.strip()]

    # fallback
    pc = item.get("primary_category")
    if isinstance(pc, str) and pc.strip():
        return [pc.strip()]

    return ["Uncategorized Document"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True, help="Project name stored as VS file attribute")
    ap.add_argument(
        "--results-json", required=True, help="Path to results.json or results_multi_category.json"
    )
    ap.add_argument(
        "--openai-purpose", default="assistants", help="Purpose used when files were uploaded"
    )
    ap.add_argument(
        "--update-existing", action="store_true", help="Update attributes if file already attached"
    )
    args = ap.parse_args()

    llm = LLMClient(provider="openai")
    results = load_results(Path(args.results_json))

    # Used only when an item doesn't include file_id
    openai_by_name = index_openai_files_by_filename(llm, purpose=args.openai_purpose, limit=100)

    print(f"Project: {args.project}")
    print(f"Results items: {len(results)}")
    print(f"OpenAI files indexed: {len(openai_by_name)} (purpose={args.openai_purpose})")

    ok = skipped = missing = errors = 0

    for item in results:
        if item.get("error"):
            skipped += 1
            continue

        file_name = str(item.get("file_name") or "").strip()
        if not file_name:
            skipped += 1
            continue

        # Prefer explicit file_id from results (your multi-category file has it)
        file_id = item.get("file_id")
        if not (isinstance(file_id, str) and file_id.strip()):
            file_id = openai_by_name.get(file_name)

        if not file_id:
            missing += 1
            print(f"MISS {file_name} (no file_id in results and not found via list_files)")
            continue

        categories = extract_categories(item)

        for cat in categories:
            vs_name = category_store_name(cat)
            try:
                vs_id = llm.get_or_create_vector_store_id_by_name(vs_name)

                attrs = {
                    "project": str(args.project)[:512],
                    "file_name": file_name[:512],
                    "category": str(cat)[:512],
                }

                if llm.vector_store_has_file(vector_store_id=vs_id, file_id=file_id):
                    if args.update_existing:
                        llm.update_vector_store_file_attributes(
                            vector_store_id=vs_id,
                            file_id=file_id,
                            attributes=attrs,
                        )
                        print(f"UPD  {file_name} -> {vs_name} (category='{cat}')")
                        ok += 1
                    else:
                        skipped += 1
                    continue

                llm.add_file_to_vector_store(
                    vector_store_id=vs_id, file_id=file_id, attributes=attrs
                )
                llm.wait_until_vector_store_file_ready(vector_store_id=vs_id, file_id=file_id)
                print(f"ADD  {file_name} -> {vs_name} (category='{cat}')")
                ok += 1
            except Exception as e:
                errors += 1
                print(f"ERR  {file_name} -> {vs_name}: {e}")

    print(f"\nDone. ok={ok} skipped={skipped} missing={missing} errors={errors}")
    return 0 if errors == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
