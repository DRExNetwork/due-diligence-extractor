from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List, Optional

from ddx.llm.client import LLMClient
from ddx.prompts.single_doc import build_prompt_single_doc
from ddx.reducer.normalize import normalize_per_doc, _normalize_single_doc_output
from ddx.reducer.policy import reduce_by_policy
from ddx.ingestion.files import discover_files, read_doc_pages
from ddx.utils.progress import _progress_print

def _llm_client(provider: str, model: str):
    return LLMClient(provider=provider, model=model or None)

def llm_extract_single_doc(field: Dict[str, Any], doc_text: str, provider: str, model: str, filename: str = None) -> Dict[str, Any]:
    client = _llm_client(provider, model)
    prompt = build_prompt_single_doc(field, filename)
    if len(doc_text) > 12000:
        doc_text = doc_text[:12000] + "\\n[...truncated...]"
    messages = [
        {"role": "system", "content": "Return ONLY valid JSON matching the schema. No prose."},
        {"role": "user", "content": f"{prompt}\\n\\nDocument:\\n{doc_text}"}
    ]
    raw = client.chat(messages, response_format={"type": "json_object"})
    from ddx.utils.json import _json_loads_lenient
    return _json_loads_lenient(raw)

def run_for_fields(registry_idx: Dict[str, Dict[str, Any]],
                   fields: List[str],
                   docs_dir: Optional[Path],
                   provider: str = "openai",
                   model: str = "",
                   progress: bool = False,
                   *,
                   ocr: bool = False,
                   ocr_lang: str = "spa+eng",
                   ocr_dpi: int = 300) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []
    llm_client = _llm_client(provider=provider, model=model)

    for key in fields:
        meta = registry_idx.get(key)
        orig_key = key
        if not meta:
            candidates = [k for k in registry_idx.keys() if k.endswith(key)]
            if candidates:
                meta = registry_idx[candidates[0]]
                key = candidates[0]
        if not meta:
            results.append({"key": orig_key, "error": "Unknown field key"})
            continue

        files = discover_files(docs_dir)
        _progress_print(0, len(files), "Reading", "(start)", enabled=progress)
        if not files:
            results.append({
                "key": key,
                "meta": {
                    "section": meta.get("Sections"),
                    "document": meta.get("Sub Section/Document"),
                    "data_point": meta.get("Data Point"),
                    "category": meta.get("Category"),
                    "weight": meta.get("Weight"),
                },
                "prompt": "(n/a)",
                "value": None,
                "unit": None,
                "justification": "",
                "confidence": 0.0,
                "evidence": [],
                "files_processed": [],
                "files_count": 0,
                "empty_text_docs": []
            })
            continue

        doc_texts: Dict[str, str] = {}
        empty_text_docs: List[str] = []
        total = len(files)
        for i, pth in enumerate(files, start=1):
            _progress_print(i, total, "Reading", pth.name, enabled=progress)
            pages = read_doc_pages(pth, ocr=ocr, ocr_lang=ocr_lang, ocr_dpi=ocr_dpi, progress=progress)
            if pth.suffix.lower() == ".kmz":
                txt = "\\n".join(pages)
                if not any((s or "").strip() for s in pages):
                    empty_text_docs.append(pth.name)
            else:
                txt = "\\n\\n".join(f"[Page {j}] {pg}" for j, pg in enumerate(pages, start=1))
                if not (txt or "").strip():
                    empty_text_docs.append(pth.name)
            doc_texts[pth.name] = txt

        fcfg = meta.get("_cfg") or {}
        unit = (fcfg.get("reducer_policy", {}) or {}).get("expected_unit") or fcfg.get("unit")

        per_doc_outputs: List[Dict[str, Any]] = []
        prompt_used = build_prompt_single_doc(meta)
        total = len(doc_texts)
        for idx, (fn, txt) in enumerate(doc_texts.items(), start=1):
            _progress_print(idx, total, "LLM map", f"Document {idx}", enabled=progress)
            try:
                j = llm_extract_single_doc(meta, txt, provider, model, filename=fn)
            except Exception as e:
                j = {"error": f"single_doc LLM failed: {e}"}
            j_norm = normalize_per_doc(j, fcfg)
            if fn.lower().endswith(".kmz"):
                evs = j_norm.get("evidence") or []
                for ev in evs:
                    if isinstance(ev, dict):
                        ev["page"] = None
                evs2 = j_norm.get("evidence_structured") or []
                for ev in evs2:
                    if isinstance(ev, dict):
                        ev["page"] = None

            j_norm["_doc_index"] = idx
            j_norm["_filename"] = fn

            inter_spec = ((fcfg.get("extraction_contract") or {}).get("intermediate") or {})
            j_norm = _normalize_single_doc_output(fn, txt, j_norm, inter_spec)

            per_doc_outputs.append(j_norm)

        _progress_print(1, 1, "LLM reduce", "synthesizing", enabled=progress)
        try:
            det = reduce_by_policy(
                field_key=key,
                field_def=fcfg,
                intermediate_results=per_doc_outputs,
                llm_client=llm_client
            )
        except Exception as e:
            det = {
                "value": None,
                "unit": unit,
                "justification": f"Reducer failed: {e}",
                "evidence": [],
                "confidence": 0.0,
                "notes": ["Reducer exception"]
            }

        value = det.get("value")
        unit = det.get("unit") or unit

        structured: List[Dict[str, Any]] = []
        for d in per_doc_outputs:
            for e in (d.get("evidence_structured") or []):
                structured.append(e)

        llm_evidence = []
        for e in (det.get("evidence") or []):
            if isinstance(e, str):
                llm_evidence.append({"doc": None, "page": None, "snippet": e})
            elif isinstance(e, dict):
                llm_evidence.append(e)

        evidence = structured or llm_evidence
        def _is_generic(name: Optional[str]) -> bool:
            n = (name or "").lower()
            return any(s in n for s in ["guidebook", "permitting", "manual", "code"])
        proj_ev = [e for e in evidence if not _is_generic(e.get("doc"))]
        if proj_ev:
            evidence = proj_ev
        confidence = float(det.get("confidence", 0.85))

        result = {
            "key": key,
            "meta": {
                "section": meta.get("Sections"),
                "document": meta.get("Sub Section/Document"),
                "data_point": meta.get("Data Point"),
                "category": meta.get("Category"),
                "weight": meta.get("Weight"),
            },
            "prompt": prompt_used,
            "value": value,
            "unit": unit,
            "justification": det.get("justification", ""),
            "confidence": confidence,
            "evidence": evidence,
            "files_processed": list(doc_texts.keys()),
            "files_count": len(doc_texts),
            "empty_text_docs": empty_text_docs,
            "intermediate_per_doc": per_doc_outputs
        }

        results.append(result)

    return {"results": results}
