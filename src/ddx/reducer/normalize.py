from __future__ import annotations
def _to_float(x):
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        s = x.strip().replace(" ", "")
        if s.count(",") == 1 and s.count(".") > 1:
            s = s.replace(".", "").replace(",", ".")
        elif s.count(",") == 1 and s.count(".") == 0:
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
        try:
            return float(s)
        except Exception:
            return None
    if isinstance(x, bool):
        return x
    return None

def normalize_per_doc(doc_json: dict, field_cfg: dict) -> dict:
    ec = (field_cfg or {}).get("extraction_contract", {}) or {}
    inter_spec = ec.get("intermediate", {}) or {}
    rv = ec.get("return_value")
    allowed = set(inter_spec.keys())

    def cast(v, typ):
        t = (typ or "string").lower()
        if t == "number":
            return _to_float(v)
        if t == "boolean":
            if v is None:
                return None
            if isinstance(v, bool):
                return v
            s = str(v).strip().lower()
            return s in ("true", "1", "yes", "y", "si", "sí")
        if v is None:
            return None
        return str(v)

    out = {
        "value": None,
        "unit": doc_json.get("unit"),
        "intermediate": {},
        "evidence": doc_json.get("evidence") or [],
        "evidence_structured": doc_json.get("evidence_structured") or [],
        "confidence": float(doc_json.get("confidence") or 0),
        "notes": doc_json.get("notes") or []
    }

    got = (doc_json.get("intermediate") or {})
    if isinstance(got, dict):
        for k in allowed:
            if k in got:
                out["intermediate"][k] = cast(got[k], (inter_spec.get(k, {}) or {}).get("type"))

    if "rate_usd_per_kwh" in allowed:
        rate = out["intermediate"].get("rate_usd_per_kwh")
        kwh  = out["intermediate"].get("monthly_kwh")
        cost = out["intermediate"].get("energy_charge_usd")
        if rate is None and kwh and cost:
            try:
                out["intermediate"]["rate_usd_per_kwh"] = float(cost) / float(kwh)
            except Exception:
                pass

    if isinstance(rv, list):
        value_obj = {}
        for k in rv:
            typ = (inter_spec.get(k, {}) or {}).get("type")
            v = out["intermediate"].get(k)
            if v is None:
                if (typ or "").lower() == "boolean":
                    v = False
                elif (typ or "").lower() == "number":
                    v = 0.0
                else:
                    v = ""
            value_obj[k] = v
        out["value"] = value_obj
    for k, spec in inter_spec.items():
        if out["intermediate"].get(k) is None:
            t = (spec.get("type") or "").lower()
            if t == "boolean":
                out["intermediate"][k] = False
            elif t == "number":
                out["intermediate"][k] = 0.0
            else:
                out["intermediate"][k] = ""

    if isinstance(rv, list):
        out["value"] = {k: out["intermediate"][k] for k in rv}
    elif isinstance(rv, str):
        out["value"] = out["intermediate"][rv]

    if rv is None and out["value"] is None:
        out["value"] = False
    return out
