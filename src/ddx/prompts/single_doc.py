from __future__ import annotations
import os, json
from typing import Dict

def contract_lines(field_cfg: dict) -> str:
    ec = (field_cfg or {}).get("extraction_contract", {})
    inter = (ec or {}).get("intermediate", {}) or {}
    lines = []
    for k, spec in inter.items():
        t = spec.get("type", "string")
        req = "required" if spec.get("required") else "optional"
        desc = spec.get("desc") or ""
        lines.append(f'- "{k}": {t}, {req}. {desc}'.strip())
    return "\n".join(lines) or "- (no intermediate keys)"

def build_prompt_single_doc(field: dict, filename: str = None) -> str:
    fcfg = field.get("_cfg") or {}
    doc_category = fcfg.get("doc_category") or field.get("Sub Section/Document") or "(unspecified)"
    dp = field.get("Data Point", "")
    unit = fcfg.get("unit")

    ecfg = fcfg.get("extraction_contract") or {}
    rv = ecfg.get("return_value")
    inter_spec = (ecfg.get("intermediate") or {}) or {}

    def ph(t: str) -> str:
        t = (t or "string").lower()
        if t == "boolean": return "<true|false|null>"
        if t == "number":  return "<number|null>"
        return "<string|null>"

    if inter_spec:
        inter_fields = ", ".join([f"\"{k}\": {ph(v.get('type'))}" for k, v in inter_spec.items()])
        intermediate_schema = "{ " + inter_fields + " }"
    else:
        intermediate_schema = "{}"

    if isinstance(rv, list):
        value_fields = ", ".join([f"\"{k}\": {ph(inter_spec.get(k,{}).get('type'))}" for k in rv])
        value_placeholder = "{ " + value_fields + " }"
        unit_literal = "null"
    else:
        value_placeholder = "<number|string|boolean|null>"
        unit_literal = f"\"{unit}\"" if unit else "null"

    schema = f"""\nReturn ONLY JSON:\n{{\n  "value": {value_placeholder},\n  "unit": {unit_literal},\n  "intermediate": {intermediate_schema},\n  "evidence": [\n    {{\n      "doc": "{filename or '<string>'}",\n      "page": <number|null>,\n      "snippet": "<string>"\n    }}\n  ],\n  "evidence_structured": [\n    {{\n      "doc": "{filename or '<string>'}",\n      "page": <number|null>,\n      "snippet": "<string>",\n      "label": "<one of the intermediate keys>"\n    }}\n  ],\n  "confidence": <0..1>,\n  "notes": [<string>]\n}}\n""".strip()

    hints = "\n".join(f"- {h}" for h in (fcfg.get("prompt_hints") or []))
    rules = []
    if unit and unit_literal != "null":
        rules.append(f"- Use the field's expected unit: {unit}.")
    rules += [
        "- Only use keys declared in the contract.",
        "- Populate EVERY 'intermediate' key; use null when not found in the doc.",
        "- Evidence: include at least one item with the exact filename in 'doc', a 'page' number using the [Page N] markers present in this document (or null for non-paged sources), and a short quote/phrase snippet (<= 240 chars) justifying your extraction.",
        "- If the source is a KMZ/KML, set page to null; snippet can be a short structured summary."
    ]

    return f"""You are extracting "{dp}" from ONE document in category: {doc_category}.\n\nContract for "intermediate" (allowed keys only):\n{contract_lines(fcfg)}\n\nRules:\n{os.linesep.join(rules) or "- (no special rules)"}\n\nHints:\n{hints or "- (none)"}\n\n{schema}\n\nOutput requirements:\n- For every intermediate key you set (true/false/number/string), add at least one item to "evidence_structured"\n  with a short directly-quoted snippet and the page number where it appears (page may be null for non-paginated docs).\n- The "label" in each evidence_structured item MUST match an intermediate key you returned.\n- If evidence supports FALSE (e.g., explicit “no…”, “not provided”, “absence noted”), quote that text.\n- Prefer citing THIS document over generic manuals or codes when justifying booleans.\n- Always answer in English, however evidence should stay unmodified.\n"""
