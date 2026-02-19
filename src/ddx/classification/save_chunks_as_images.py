from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _safe_name(s: str) -> str:
    s = (s or "").strip()
    if not s:
        return "field"
    s = re.sub(r"[^\w\-\.]+", "_", s)
    return s[:120]


def _coords_from_box(box: Any) -> Optional[Tuple[float, float, float, float]]:
    if box is None:
        return None

    # Common: left/top/right/bottom (SDK parse.json)
    if any(k in box for k in ("left", "top", "right", "bottom")):
        try:
            return (
                float(_get(box, "left")),
                float(_get(box, "top")),
                float(_get(box, "right")),
                float(_get(box, "bottom")),
            )
        except Exception:
            return None

    # Sometimes: l/t/r/b (VA-style)
    if any(k in box for k in ("l", "t", "r", "b")):
        try:
            return (
                float(_get(box, "l")),
                float(_get(box, "t")),
                float(_get(box, "r")),
                float(_get(box, "b")),
            )
        except Exception:
            return None

    return None


def _render_pdf_page_to_image(pdf_path: Path, page_num: int, *, scale: int):
    try:
        import pymupdf  # type: ignore
    except Exception as e:
        raise RuntimeError("Missing dependency 'pymupdf'. Install with: pip install pymupdf") from e

    try:
        from PIL import Image  # type: ignore
    except Exception as e:
        raise RuntimeError("Missing dependency 'Pillow'. Install with: pip install pillow") from e

    pdf = pymupdf.open(pdf_path)
    try:
        page = pdf[page_num]
        pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale))
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        return img
    finally:
        pdf.close()


def _crop_and_save(
    image, *, left: float, top: float, right: float, bottom: float, out_path: Path
) -> bool:
    img_width, img_height = image.size

    x1 = int(left * img_width)
    y1 = int(top * img_height)
    x2 = int(right * img_width)
    y2 = int(bottom * img_height)

    x1 = max(0, min(img_width, x1))
    x2 = max(0, min(img_width, x2))
    y1 = max(0, min(img_height, y1))
    y2 = max(0, min(img_height, y2))

    if x2 <= x1 or y2 <= y1:
        return False

    out_path.parent.mkdir(parents=True, exist_ok=True)
    chunk_img = image.crop((x1, y1, x2, y2))
    chunk_img.save(out_path)
    return True


def _unwrap_extraction_metadata(record_or_meta: Dict[str, Any]) -> Dict[str, Any]:
    """
    Accepts:
      - full pipeline record: {"extraction_raw": {"extraction_metadata": {...}}}
      - extraction_raw: {"mode": ..., "extraction_metadata": {...}}
      - extraction_metadata directly: {"field": {"value": ..., "references": [...]}, ...}
    Returns extraction_metadata dict.
    """
    obj: Any = record_or_meta

    if isinstance(obj, dict) and "extraction_raw" in obj:
        obj = obj.get("extraction_raw") or {}

    if isinstance(obj, dict) and "extraction_metadata" in obj:
        obj = obj.get("extraction_metadata") or {}

    if not isinstance(obj, dict):
        return {}

    return obj


def _build_grounding_lookup(parse_obj: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Returns (grounding_map, chunk_by_id).
    grounding_map: parse["grounding"] if present
    chunk_by_id: from parse["chunks"][i] keyed by chunks[i]["id"]
    """
    if isinstance(parse_obj.get("data"), dict):
        parse_obj = parse_obj["data"]

    grounding_map = parse_obj.get("grounding") or {}
    chunks = parse_obj.get("chunks") or []

    chunk_by_id: Dict[str, Any] = {}
    if isinstance(chunks, list):
        for ch in chunks:
            cid = _get(ch, "id", None) or _get(ch, "chunk_id", None)
            if cid is None:
                continue
            chunk_by_id[str(cid)] = ch

    return (grounding_map if isinstance(grounding_map, dict) else {}), chunk_by_id


def _resolve_grounding(
    chunk_id: str, grounding_map: Dict[str, Any], chunk_by_id: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    g = grounding_map.get(chunk_id)
    if isinstance(g, dict):
        return g

    ch = chunk_by_id.get(chunk_id)
    if not ch:
        return None

    g2 = _get(ch, "grounding", None)
    if isinstance(g2, dict):
        return g2
    if isinstance(g2, list) and g2 and isinstance(g2[0], dict):
        return g2[0]

    return None


def generate_proofs_from_record(
    *,
    record: Dict[str, Any],
    parse_obj: Dict[str, Any],
    pdf_path: Path,
    out_dir: Path,
    scale: int = 2,
    max_refs_per_field: int = 3,
) -> Path:
    evidence_dir = out_dir / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    extraction_meta = _unwrap_extraction_metadata(record)
    grounding_map, chunk_by_id = _build_grounding_lookup(parse_obj)

    manifest: Dict[str, Any] = {
        "pdf_path": str(pdf_path),
        "record_source": str(record.get("_record_path", "")) if isinstance(record, dict) else "",
        "parse_source": str(record.get("_parse_path", "")) if isinstance(record, dict) else "",
        "evidence_dir": str(evidence_dir),
        "fields": {},
        "missing_references": {},
    }

    page_images: Dict[int, Any] = {}

    def get_page_img(page_num: int):
        if page_num not in page_images:
            page_images[page_num] = _render_pdf_page_to_image(pdf_path, page_num, scale=scale)
        return page_images[page_num]

    for field_name, info in extraction_meta.items():
        if not isinstance(info, dict):
            continue

        refs = info.get("references")
        if refs is None:
            refs = info.get("chunk_references")
        if not isinstance(refs, list) or not refs:
            continue

        refs = refs[: max_refs_per_field if max_refs_per_field > 0 else len(refs)]

        field_key = _safe_name(str(field_name))
        field_dir = evidence_dir / field_key
        field_dir.mkdir(parents=True, exist_ok=True)

        saved: List[Dict[str, Any]] = []
        missing: List[str] = []

        for i, rid in enumerate(refs):
            chunk_id = str(rid)
            g = _resolve_grounding(chunk_id, grounding_map, chunk_by_id)
            if not g:
                missing.append(chunk_id)
                continue

            page_val = _get(g, "page", None)
            try:
                page_num = int(page_val)
            except Exception:
                missing.append(chunk_id)
                continue

            coords = _coords_from_box(_get(g, "box", None))
            if not coords:
                missing.append(chunk_id)
                continue

            out_path = field_dir / f"{field_key}__{i}.{chunk_id}.png"
            img = get_page_img(page_num)

            if not _crop_and_save(
                img,
                left=coords[0],
                top=coords[1],
                right=coords[2],
                bottom=coords[3],
                out_path=out_path,
            ):
                missing.append(chunk_id)
                continue

            saved.append(
                {
                    "field": field_name,
                    "value": info.get("value", None),
                    "chunk_id": chunk_id,
                    "page": page_num,
                    "box": {
                        "left": coords[0],
                        "top": coords[1],
                        "right": coords[2],
                        "bottom": coords[3],
                    },
                    "image_path": str(out_path),
                }
            )

        if saved:
            manifest["fields"][field_name] = saved
        if missing:
            manifest["missing_references"][field_name] = missing

    (evidence_dir / "evidence_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return evidence_dir


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Generate proof images from pipeline record.json + parse.json (no parsing; uses references -> grounding -> crop)."
    )
    ap.add_argument(
        "--record-json",
        required=True,
        help="Path to per-file pipeline record JSON (contains extraction_raw + parse_json_path).",
    )
    ap.add_argument("--out-dir", default=r".\out\proofs", help="Base output directory for proofs.")
    ap.add_argument(
        "--scale", type=int, default=2, help="PDF render scale factor (2 is usually fine)."
    )
    ap.add_argument(
        "--max-refs-per-field", type=int, default=3, help="Max reference chunks to crop per field."
    )

    # Optional overrides
    ap.add_argument(
        "--pdf", default=None, help="Override PDF path (otherwise uses record['pdf_path'])."
    )
    ap.add_argument(
        "--parse-json",
        default=None,
        help="Override parse.json path (otherwise uses record['parse_json_path']).",
    )

    args = ap.parse_args()

    record_path = Path(args.record_json).expanduser().resolve()
    record = json.loads(record_path.read_text(encoding="utf-8"))
    if not isinstance(record, dict):
        raise RuntimeError("record-json must contain a JSON object.")

    pdf_path = (
        Path(args.pdf).expanduser().resolve()
        if args.pdf
        else Path(record["pdf_path"]).expanduser().resolve()
    )
    parse_path = (
        Path(args.parse_json).expanduser().resolve()
        if args.parse_json
        else Path(record["parse_json_path"]).expanduser().resolve()
    )

    parse_obj = json.loads(parse_path.read_text(encoding="utf-8"))
    if not isinstance(parse_obj, dict):
        raise RuntimeError("parse-json must contain a JSON object.")

    # annotate sources for manifest
    record["_record_path"] = str(record_path)
    record["_parse_path"] = str(parse_path)

    out_base = Path(args.out_dir).expanduser().resolve()
    out_dir = out_base / pdf_path.stem
    out_dir.mkdir(parents=True, exist_ok=True)

    evidence_dir = generate_proofs_from_record(
        record=record,
        parse_obj=parse_obj,
        pdf_path=pdf_path,
        out_dir=out_dir,
        scale=args.scale,
        max_refs_per_field=args.max_refs_per_field,
    )

    print(f"Wrote evidence to: {evidence_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
