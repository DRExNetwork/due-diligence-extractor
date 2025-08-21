from __future__ import annotations
import argparse, json
from pathlib import Path

from ddx.config.fields import load_field_config, build_registry_from_field_config, index_registry
from ddx.orchestrator import run_for_fields
from ddx.storage.json_store import save_json_outputs

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--field-config", default=str(Path(__file__).resolve().parents[2] / "config" / "fields.json"),
                    help="Path to fields.json config")
    ap.add_argument("--docs-dir", default=None, help="Directory with source documents (.txt/.csv/.pdf/.kmz)")
    ap.add_argument("--fields", nargs="+", required=True, help="Field keys to extract")

    # LLM
    ap.add_argument("--provider", default="openai", help="LLM provider (default: openai)")
    ap.add_argument("--model", default="", help="LLM model name override (else env LLM_MODEL)")

    # OCR
    ap.add_argument("--ocr", action="store_true", help="Enable OCR fallback when PDFs have no text layer")
    ap.add_argument("--ocr-lang", default="spa+eng", help="Tesseract languages (e.g., 'spa+eng')")
    ap.add_argument("--ocr-dpi", type=int, default=300, help="Render DPI for OCR")

    # Progress
    ap.add_argument("--progress", action="store_true", help="Show file reading / OCR / LLM progress")

    # JSON storage
    ap.add_argument("--store-dir", default=str(Path(__file__).resolve().parents[2] / "store"),
                    help="Directory to persist outputs (JSON + per-field snapshots)")
    ap.add_argument("--project-id", default="default_project", help="Namespace for run/field snapshots")
    ap.add_argument("--run-id", default=None, help="Optional run id; defaults to UTC timestamp")

    args = ap.parse_args()

    store_dir = Path(args.store_dir)
    store_dir.mkdir(parents=True, exist_ok=True)

    # configs
    field_cfg = load_field_config(Path(args.field_config))
    registry = build_registry_from_field_config(field_cfg)
    registry_idx = index_registry(registry)

    docs_dir = Path(args.docs_dir) if args.docs_dir else None

    out = run_for_fields(
        registry_idx, args.fields, docs_dir,
        provider=args.provider, model=args.model,
        progress=args.progress,
        ocr=args.ocr, ocr_lang=args.ocr_lang, ocr_dpi=args.ocr_dpi
    )

    args_meta = {
        "project_id": args.project_id,
        "field_config": str(Path(args.field_config)),
        "docs_dir": str(docs_dir) if docs_dir else None,
        "model": args.model,
        "provider": args.provider,
        "ocr": args.ocr,
        "ocr_lang": args.ocr_lang,
        "ocr_dpi": args.ocr_dpi,
    }
    stored_paths = save_json_outputs(out, store_dir, args.project_id, args.run_id, args_meta)
    out["stored_json"] = stored_paths
    print(json.dumps(out, indent=2))
