from __future__ import annotations
import json

def reduce_by_policy(field_key: str, field_def: dict, intermediate_results: list, llm_client) -> dict:
    pol = field_def.get("reducer_policy") or {}
    expected_unit = pol.get("expected_unit") if "expected_unit" in pol else field_def.get("unit")
    method = pol.get("method")
    strategy = pol.get("strategy")
    rules = pol.get("rules")
    ec = field_def.get("extraction_contract", {}) or {}
    rv = ec.get("return_value")

    RULE_ALIASES = {
        "true_if_any": "any_true",
        "any": "any_true",
        "or": "any_true",
        "false_if_any": "any_false",
        "all_true": "all_true",
        "majority": "majority_vote",
    }
    def _normalize_rule(r):
        return RULE_ALIASES.get(r, r)

    if isinstance(rules, dict):
        rules = {k: _normalize_rule(v) for k, v in rules.items()}
    elif isinstance(rules, list):
        rules = [_normalize_rule(v) for v in rules]

    candidates = []
    rv = (field_def.get("extraction_contract", {}) or {}).get("return_value")
    for r in intermediate_results:
        v = r.get("value")
        if v is None and isinstance(rv, str):
            v = (r.get("intermediate") or {}).get(rv, None)
        candidates.append({
            "value": v,
            "unit": r.get("unit"),
            "intermediate": r.get("intermediate"),
            "evidence": r.get("evidence", []),
            "confidence": r.get("confidence"),
            "page": r.get("_page", None),
            "filename": r.get("_filename", None),
        })

    def _unit_json_value(u):
        return None if u in (None, "None") else u

    def _llm_reduce(schema_json: str) -> dict:
        prompt = f"""
You are the reducer for "{field_key}".

Reducer policy:
- expected_unit = {expected_unit}
- method = {method}
- strategy = {strategy}
- rules = {json.dumps(rules, ensure_ascii=False)}

Intermediate results (per-doc):
{json.dumps(candidates, ensure_ascii=False, indent=2)}

Return STRICT JSON only in this schema:
{schema_json}
"""
        try:
            messages = [
                {"role": "system", "content": "Return ONLY valid JSON matching the schema. No prose."},
                {"role": "user", "content": prompt}
            ]
            raw = llm_client.chat(messages, response_format={"type": "json_object"})
            return _json_loads_lenient(raw)
        except Exception:
            return {}

    # lazy import to avoid cycle
    from ddx.utils.json import _json_loads_lenient

    if isinstance(rv, list):
        inter_spec = (ec.get("intermediate") or {})
        def placeholder(t: str) -> str:
            t = (t or "string").lower()
            if t == "boolean": return "<true|false|null>"
            if t == "number":  return "<number|null>"
            return "<string|null>"

        value_fields = ", ".join([f"\"{k}\": {placeholder(inter_spec.get(k,{}).get('type'))}" for k in rv])
        value_schema = "{ " + value_fields + " }"
        unit_json = "null" if expected_unit in (None, "None") else f"\"{expected_unit}\""

        schema_json = f"""{{
  "value": {value_schema},
  "unit": {unit_json},
  "justification": "<string>",
  "evidence": [{{"doc":"<string>","page":<number|null>,"snippet":"<string>"}}],
  "confidence": <0..1>,
  "notes": [<string>]

  INSTRUCTIONS: Always answer in English.
}}"""

        result = _llm_reduce(schema_json)
        if result and isinstance(result, dict) and "value" in result:
            if result.get("unit") in (None, "None") and expected_unit in (None, "None"):
                result["unit"] = None
            return result

        merged = {}
        for k in rv:
            vals, confs = [], []
            for c in candidates:
                v = (c.get("intermediate") or {}).get(k)
                if v is not None:
                    vals.append(v)
                    confs.append(c.get("confidence") or 0.0)
            if not vals:
                t = ((ec.get("intermediate") or {}).get(k, {}) or {}).get("type", "string").lower()
                if t == "boolean":
                    merged[k] = False
                elif t == "number":
                    merged[k] = 0.0
                else:
                    merged[k] = ""
                continue
            rule = (rules or {}).get(k)
            if rule == "any_true":
                merged[k] = any(bool(v) for v in vals)
            elif rule == "any_false":
                merged[k] = any(v is False for v in vals)
            elif rule == "all_true":
                merged[k] = all(bool(v) for v in vals)
            elif rule == "take_max":
                merged[k] = max(vals)
            elif rule == "take_min":
                merged[k] = min(vals)
            elif rule == "majority_vote":
                merged[k] = max(set(vals), key=vals.count)
            else:
                best_idx = max(range(len(vals)), key=lambda i: confs[i])
                merged[k] = vals[best_idx]

        return {
            "value": merged or None,
            "unit": _unit_json_value(expected_unit),
            "justification": "Fallback: merged per rules from per-doc results.",
            "evidence": [e for c in candidates for e in (c.get("evidence") or [])],
            "confidence": max([c.get("confidence", 0.0) for c in candidates] or [0.0]),
            "notes": ["Reducer fallback: LLM aggregation failed or returned invalid JSON."]
        }

    unit_json = "null" if expected_unit in (None, "None") else f"\"{expected_unit}\""
    schema_json = f"""{{
  "value": <number|string|boolean|null>,
  "unit": {unit_json},
  "justification": "<string>",
  "evidence": [{{"doc":"<string>","page":<number|null>,"snippet":"<string>"}}],
  "confidence": <0..1>,
  "notes": [<string>]
}}"""
    result = _llm_reduce(schema_json)
    if result and isinstance(result, dict) and "value" in result:
        if result.get("unit") in (None, "None") and expected_unit in (None, "None"):
            result["unit"] = None
        return result

    best = None
    for c in candidates:
        if best is None or (c.get("confidence", 0) or 0) > (best.get("confidence", 0) or 0):
            best = c
    return {
        "value": best.get("value") if best else None,
        "unit": _unit_json_value(expected_unit),
        "evidence": best.get("evidence", []) if best else [],
        "confidence": best.get("confidence", 0.5) if best else 0.0,
        "notes": ["Fallback: selected highest confidence candidate due to LLM reduce failure."],
        "justification": "Reducer fallback"
    }
