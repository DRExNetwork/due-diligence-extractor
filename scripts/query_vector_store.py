from __future__ import annotations

import argparse
import json
import re
from typing import Any, Dict, List, Tuple

from ddx.llm.client import LLMClient
from ddx.extraction.extractor import DataExtractor


def slugify(s: str) -> str:
    # MUST match ingestion logic
    s = s.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return (s or "uncategorized")[:60]


def category_store_name(category: str) -> str:
    # MUST match ingestion logic
    return f"cat__{slugify(category)}"


def project_filter(project: str) -> Dict[str, Any]:
    return {"type": "eq", "key": "project", "value": project}


def _field_line(field: Dict[str, Any]) -> str:
    name = str(field.get("name", "")).strip()
    unit = str(field.get("unit", "")).strip()
    required = field.get("required", False)
    req = "required" if required else "optional"
    if unit:
        return f"- {name} ({unit}) [{req}]"
    return f"- {name} [{req}]"


def flatten_template_fields(template: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    field_names: List[str] = []
    bullet_lines: List[str] = []

    fields = template.get("fields")
    if isinstance(fields, list):
        for f in fields:
            if isinstance(f, dict) and f.get("name"):
                field_names.append(str(f["name"]))
                bullet_lines.append(_field_line(f))

    sections = template.get("sections")
    if isinstance(sections, dict):
        for section_name, section_fields in sections.items():
            if not isinstance(section_fields, list):
                continue
            bullet_lines.append(f"\n## {section_name}")
            for f in section_fields:
                if isinstance(f, dict) and f.get("name"):
                    field_names.append(str(f["name"]))
                    bullet_lines.append(_field_line(f))

    monthly_stats = template.get("monthly_statistics")
    if isinstance(monthly_stats, list) and monthly_stats:
        bullet_lines.append("\n## Monthly statistics")
        for s in monthly_stats:
            if isinstance(s, str) and s.strip():
                field_names.append(s.strip())
                bullet_lines.append(f"- {s.strip()} [optional]")

    seen = set()
    field_names_deduped: List[str] = []
    for n in field_names:
        if n not in seen:
            seen.add(n)
            field_names_deduped.append(n)

    return field_names_deduped, bullet_lines


def build_question_from_template(category: str) -> str:
    template = DataExtractor.CATEGORY_TO_TEMPLATE.get(category)
    if not template:
        raise ValueError(f"No extraction template configured for category: {category}")

    field_names, bullet_lines = flatten_template_fields(template)
    if not field_names:
        raise ValueError(f"Template for category '{category}' has no fields.")

    schema = {
        name: {"value": None, "unit": "", "snippet": "", "page_reference": ""}
        for name in field_names
    }

    return f"""You are extracting structured data from project documents.

Only use information found in the provided files. If a value is not present, return null.

Category: {category}

Extract the following fields:
{chr(10).join(bullet_lines)}

Return ONLY valid JSON with exactly these keys (no extra keys), using this shape:
{json.dumps(schema, indent=2)}

Rules:
- value: string/number when present, otherwise null
- unit: unit string if known, otherwise empty string
- snippet: short supporting quote (max 200 chars) from the document
- page_reference: page number or section name if available, otherwise empty string
"""


def find_vector_store_id_by_name(llm: LLMClient, name: str) -> str:
    # Uses list_vector_stores (limit<=100). If you have >100 stores, we can add pagination.
    stores = llm.list_vector_stores(limit=100)
    for vs in stores:
        if vs.get("name") == name and vs.get("id"):
            return str(vs["id"])
    raise ValueError(f"Vector store not found by name: '{name}'")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--project", required=True, help="Project name stored in vector store file attributes"
    )
    ap.add_argument(
        "--category", required=True, help="Document category (exact string used in ingestion)"
    )
    ap.add_argument("--use-template", action="store_true")
    ap.add_argument("--question", required=False)
    ap.add_argument("--max-results", type=int, default=6)
    ap.add_argument(
        "--include-results",
        action="store_true",
        help="Include file_search_call.results for debugging",
    )
    args = ap.parse_args()

    if not args.question and not args.use_template:
        raise SystemExit("Provide --question or set --use-template")

    question = args.question or build_question_from_template(args.category)

    llm = LLMClient(provider="openai")

    vs_name = category_store_name(args.category)
    vector_store_id = find_vector_store_id_by_name(llm, vs_name)

    print(f"Using category vector store: name='{vs_name}' id='{vector_store_id}'")
    print(f"Filtering by project attribute: project='{args.project}'")

    resp = llm.responses_file_search(
        query=question,
        vector_store_ids=[vector_store_id],
        filters=project_filter(args.project),
        max_num_results=args.max_results,
        include_results=bool(args.include_results),
        temperature=0.0,
    )

    text = llm.extract_text_from_responses_output(resp)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
