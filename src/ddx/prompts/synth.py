from __future__ import annotations
import json

def reducer_instructions_from_policy(field_cfg: dict) -> str:
    pol = field_cfg.get("reducer_policy", {}) or {}
    method = pol.get("method")
    expected_unit = pol.get("expected_unit") or field_cfg.get("unit")
    sk = pol.get("source_keys", {})
    custom_instr = pol.get("instructions", "")

    instructions = []
    if method:
        instructions.append(f"- Use reducer method: {method}")
    if expected_unit:
        instructions.append(f"- Expected output unit: {expected_unit}")
    if sk:
        instructions.append(f"- Source keys: {', '.join(sk.values())}")
    if custom_instr:
        if isinstance(custom_instr, list):
            instructions.extend(custom_instr)
        else:
            instructions.append(custom_instr)

    instructions.append("- Always include a 'justification' field explaining how you aggregated across documents/snippets. Be specific, when referring to documents, cite the snippet and page number")
    return "\n".join(instructions)

def build_prompt_synthesizer(field: dict) -> str:
    fcfg = field.get("_cfg") or {}
    dp = field.get("Data Point", "")
    pol = fcfg.get("reducer_policy") or {}
    expected_unit = pol.get("expected_unit")
    method = pol.get("method")
    strategy = pol.get("strategy")
    rules = pol.get("rules")
    sk = pol.get("source_keys", {})

    ec = fcfg.get("extraction_contract", {}) or {}
    rv = ec.get("return_value")
    inter_spec = ec.get("intermediate", {}) or {}

    def placeholder(t: str) -> str:
        t = (t or "string").lower()
        if t == "boolean":
            return "<true|false|null>"
        if t == "number":
            return "<number|null>"
        return "<string|null>"

    if isinstance(rv, list):
        value_fields = ", ".join([f"\"{k}\": {placeholder(inter_spec.get(k,{}).get('type'))}" for k in rv])
        value_placeholder = "{ " + value_fields + " }"
        per_doc_placeholder = "{ " + value_fields + " }"
    elif isinstance(rv, str):
        value_placeholder = placeholder(inter_spec.get(rv, {}).get("type", "string"))
        per_doc_placeholder = "{ \"" + rv + "\": " + value_placeholder + " }"
    else:
        value_placeholder = "<string|null>"
        per_doc_placeholder = "{ }"

    rules_lines = []
    if isinstance(rules, dict):
        for k, v in rules.items():
            rules_lines.append(f"- {k}: {v}")
    elif isinstance(rules, list):
        for v in rules:
            rules_lines.append(f"- {v}")
    rules_text = "\n".join(rules_lines)
    unit_json = "null" if expected_unit in (None, "None") else f"\"{expected_unit}\""

    schema = f"""\nReturn ONLY JSON:\n{{\n  "value": {value_placeholder},\n  "unit": {unit_json},\n  "justification": "<string>",\n  "intermediate": {{\n    "final_method": "{method or ''}",\n    "per_doc": [{per_doc_placeholder}]\n  }},\n  "evidence": [{{"doc":"<string>","page":<number|null>,"snippet":"<string>"}}],\n  "confidence": <0..1>,\n  "notes": [<string>]\n}}\n""".strip()

    return f"""You are synthesizing the final value for "{dp}" from multiple per-document JSON objects.\n\nReducer policy:\n- expected_unit = {expected_unit}\n- method = {method}\n- strategy = {strategy}\n- source_keys = {json.dumps(sk)}\n- rules:\n{rules_text or "- (none)"}\n\nFinal "value" must be computed strictly from the structured per-document fields listed in the extraction contract.\n{reducer_instructions_from_policy(fcfg)}\n\nAlways set unit to "{expected_unit}". Output STRICT JSON only. No prose.\n{schema}"""
