# src/ddx/reducer/normalize.py
from __future__ import annotations
from typing import Any, Dict


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


def _normalize_single_doc_output(fn: str, doc_text: str, j_norm: dict, inter_spec: dict) -> dict:
    evs_struct = [e for e in (j_norm.get("evidence_structured") or []) if isinstance(e, dict)]
    has_any_real = any(
        (isinstance(e.get("snippet"), str) and e.get("snippet").strip()) for e in evs_struct
    )
    if not evs_struct or not has_any_real:
        evs_struct = []
        for e in j_norm.get("evidence") or []:
            if isinstance(e, dict):
                sn = (e.get("snippet") or "")[:240]
                evs_struct.append(
                    {
                        "doc": e.get("doc") or fn,
                        "page": e.get("page"),
                        "snippet": sn if sn else None,
                    }
                )
            elif isinstance(e, str):
                evs_struct.append({"doc": fn, "page": None, "snippet": (e[:240] or None)})
    j_norm["evidence_structured"] = evs_struct
    return j_norm


def normalize_single_doc_output(fn: str, doc_text: str, j_norm: dict, inter_spec: dict) -> dict:
    return _normalize_single_doc_output(fn, doc_text, j_norm, inter_spec)


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
        "notes": doc_json.get("notes") or [],
    }

    got = doc_json.get("intermediate") or {}
    if isinstance(got, dict):
        for k in allowed:
            if k in got:
                out["intermediate"][k] = cast(got[k], (inter_spec.get(k, {}) or {}).get("type"))

    if "rate_usd_per_kwh" in allowed:
        rate = out["intermediate"].get("rate_usd_per_kwh")
        kwh = out["intermediate"].get("monthly_kwh")
        cost = out["intermediate"].get("energy_charge_usd")
        if rate is None and kwh and cost:
            try:
                out["intermediate"]["rate_usd_per_kwh"] = float(cost) / float(kwh)
            except Exception:
                pass
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
    else:
        if out["value"] is None:
            out["value"] = False

    return out
