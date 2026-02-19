from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _safe_name(s: str) -> str:
    """Sanitize string for use as filename."""
    s = (s or "").strip()
    if not s:
        return "field"
    s = re.sub(r"[^\w\-\.]+", "_", s)
    return s[:120]


def _coords_from_box(box: Any) -> Optional[Tuple[float, float, float, float]]:
    """Extract normalized coordinates from box dict."""
    if box is None:
        return None

    # Common: left/top/right/bottom
    if all(k in box for k in ("left", "top", "right", "bottom")):
        try:
            return (
                float(box["left"]),
                float(box["top"]),
                float(box["right"]),
                float(box["bottom"]),
            )
        except Exception:
            return None

    return None


def _render_pdf_page_to_image(pdf_path: Path, page_num: int, *, scale: int = 2):
    """Render a PDF page to PIL Image."""
    try:
        import pymupdf
    except ImportError as e:
        raise RuntimeError("Missing dependency 'pymupdf'. Install with: pip install pymupdf") from e

    try:
        from PIL import Image
    except ImportError as e:
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
    """Crop image using normalized coordinates and save."""
    img_width, img_height = image.size

    x1 = int(left * img_width)
    y1 = int(top * img_height)
    x2 = int(right * img_width)
    y2 = int(bottom * img_height)

    # Clamp to image bounds
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


def _find_parse_json_for_pdf(pdf_path: Path, search_dirs: List[Path]) -> Optional[Path]:
    """
    Find the parse.json file corresponding to a PDF.
    Looks for patterns like: <pdf_stem>.parse.json or <pdf_stem>.pdf.parse.json
    """
    pdf_stem = pdf_path.stem
    possible_names = [
        f"{pdf_stem}.parse.json",
        f"{pdf_stem}.pdf.parse.json",
        f"{pdf_path.name}.parse.json",
    ]

    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        # Search recursively
        for parse_path in search_dir.rglob("*.parse.json"):
            if parse_path.name in possible_names or pdf_stem in parse_path.stem:
                return parse_path

    return None


def generate_proofs_from_final_extraction(
    *,
    final_extraction_path: Path,
    out_dir: Path,
    parse_search_dirs: Optional[List[Path]] = None,
    scale: int = 2,
    max_locations_per_field: int = 3,
) -> Dict[str, Any]:
    """
    Generate proof images from a final_extraction.json file.

    Args:
        final_extraction_path: Path to final_extraction.json
        out_dir: Output directory for proof images
        parse_search_dirs: Directories to search for parse.json files (optional)
        scale: PDF render scale factor
        max_locations_per_field: Max locations to crop per field

    Returns:
        Manifest dict with generated proofs info
    """
    final_data = json.loads(final_extraction_path.read_text(encoding="utf-8"))

    evidence_dir = out_dir / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    # Build source file mapping
    sources = final_data.get("sources", [])
    if not sources and "pdf_path" in final_data:
        # Single source case
        pdf_path_str = final_data["pdf_path"]
        if pdf_path_str and not pdf_path_str.startswith("["):
            sources = [pdf_path_str]

    # Default search dirs for parse.json
    if parse_search_dirs is None:
        parse_search_dirs = [
            final_extraction_path.parent.parent.parent / "out_new" / "markdown",
            final_extraction_path.parent.parent.parent / "markdown",
            final_extraction_path.parent,
        ]

    # Map source files to their parse.json paths
    source_parse_map: Dict[str, Optional[Path]] = {}
    for src in sources:
        src_path = Path(src)
        parse_path = _find_parse_json_for_pdf(src_path, parse_search_dirs)
        source_parse_map[src] = parse_path

    manifest: Dict[str, Any] = {
        "final_extraction_path": str(final_extraction_path),
        "category": final_data.get("category", ""),
        "sources": sources,
        "source_parse_map": {k: str(v) if v else None for k, v in source_parse_map.items()},
        "evidence_dir": str(evidence_dir),
        "fields": {},
        "missing_locations": {},
        "errors": [],
    }

    extracted = final_data.get("extracted", {})
    if not extracted:
        manifest["errors"].append("No 'extracted' field found in final_extraction.json")
        return manifest

    # Cache for rendered page images: (pdf_path, page_num) -> image
    page_images: Dict[Tuple[str, int], Any] = {}

    def get_page_img(pdf_path: str, page_num: int):
        key = (pdf_path, page_num)
        if key not in page_images:
            page_images[key] = _render_pdf_page_to_image(Path(pdf_path), page_num, scale=scale)
        return page_images[key]

    for field_name, field_data in extracted.items():
        if not isinstance(field_data, dict):
            continue

        locations = field_data.get("locations", [])
        if not locations:
            continue

        # Deduplicate locations by (page, chunk_id)
        seen_locs = set()
        unique_locations = []
        for loc in locations:
            loc_key = (loc.get("page"), loc.get("chunk_id"))
            if loc_key not in seen_locs:
                seen_locs.add(loc_key)
                unique_locations.append(loc)

        # Limit locations
        unique_locations = unique_locations[:max_locations_per_field]

        source_file = field_data.get("source_file", "")
        if not source_file or not Path(source_file).exists():
            manifest["missing_locations"][field_name] = f"Source file not found: {source_file}"
            continue

        field_key = _safe_name(field_name)
        field_dir = evidence_dir / field_key
        field_dir.mkdir(parents=True, exist_ok=True)

        saved: List[Dict[str, Any]] = []
        missing: List[str] = []

        for i, loc in enumerate(unique_locations):
            page_num = loc.get("page")
            box = loc.get("box")
            chunk_id = loc.get("chunk_id", f"loc_{i}")

            if page_num is None:
                missing.append(f"No page number for location {i}")
                continue

            coords = _coords_from_box(box)
            if not coords:
                missing.append(f"Invalid box for location {i}: {box}")
                continue

            try:
                img = get_page_img(source_file, page_num)
            except Exception as e:
                missing.append(f"Failed to render page {page_num}: {e}")
                continue

            out_path = field_dir / f"{field_key}__{i}.{chunk_id[:8]}.png"

            if not _crop_and_save(
                img,
                left=coords[0],
                top=coords[1],
                right=coords[2],
                bottom=coords[3],
                out_path=out_path,
            ):
                missing.append(f"Crop failed for location {i}")
                continue

            # Update the location with image path
            loc["image_path"] = str(out_path)

            saved.append(
                {
                    "field": field_name,
                    "value": field_data.get("value"),
                    "extracted_text": field_data.get("extracted_text"),
                    "chunk_id": chunk_id,
                    "page": page_num,
                    "box": box,
                    "image_path": str(out_path),
                    "source_file": source_file,
                }
            )

        if saved:
            manifest["fields"][field_name] = saved
        if missing:
            manifest["missing_locations"][field_name] = missing

    # Save manifest
    manifest_path = evidence_dir / "evidence_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    # Also update the original final_extraction.json with image paths
    updated_extraction_path = evidence_dir / "final_extraction_with_images.json"
    updated_extraction_path.write_text(
        json.dumps(final_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return manifest


def process_validation_folder(
    validation_dir: Path,
    out_base_dir: Path,
    scale: int = 2,
    max_locations_per_field: int = 3,
) -> Dict[str, Any]:
    """
    Process all final_extraction.json files in a validation folder structure.

    Args:
        validation_dir: Root validation directory (e.g., out_validation/validated)
        out_base_dir: Base output directory for proofs
        scale: PDF render scale
        max_locations_per_field: Max locations per field

    Returns:
        Summary of all processed categories
    """
    results = {
        "validation_dir": str(validation_dir),
        "out_base_dir": str(out_base_dir),
        "categories": {},
        "errors": [],
    }

    # Find all final_extraction.json files
    for final_json in validation_dir.rglob("final_extraction.json"):
        category_dir = final_json.parent
        category_name = category_dir.name

        print(f"\nProcessing: {category_name}")
        print(f"  Source: {final_json}")

        try:
            out_dir = out_base_dir / category_name
            manifest = generate_proofs_from_final_extraction(
                final_extraction_path=final_json,
                out_dir=out_dir,
                scale=scale,
                max_locations_per_field=max_locations_per_field,
            )

            results["categories"][category_name] = {
                "final_extraction": str(final_json),
                "evidence_dir": manifest.get("evidence_dir"),
                "fields_processed": len(manifest.get("fields", {})),
                "fields_with_missing": len(manifest.get("missing_locations", {})),
            }

            print(f"  ✓ Generated proofs for {len(manifest.get('fields', {}))} fields")
            if manifest.get("missing_locations"):
                print(f"  ! {len(manifest['missing_locations'])} fields had missing locations")

        except Exception as e:
            error_msg = f"Failed to process {category_name}: {e}"
            results["errors"].append(error_msg)
            print(f"  ✗ {error_msg}")

    return results


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Generate proof images from final_extraction.json files."
    )
    ap.add_argument(
        "--input",
        required=True,
        help="Path to final_extraction.json OR validation folder containing multiple categories.",
    )
    ap.add_argument(
        "--out-dir",
        default=r".\out\validation_proofs",
        help="Base output directory for proofs.",
    )
    ap.add_argument(
        "--scale",
        type=int,
        default=2,
        help="PDF render scale factor (default: 2).",
    )
    ap.add_argument(
        "--max-locations",
        type=int,
        default=3,
        help="Max locations to crop per field (default: 3).",
    )
    ap.add_argument(
        "--parse-search-dir",
        action="append",
        default=None,
        help="Additional directories to search for parse.json files (can be specified multiple times).",
    )

    args = ap.parse_args()

    input_path = Path(args.input).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()

    parse_dirs = None
    if args.parse_search_dir:
        parse_dirs = [Path(p).expanduser().resolve() for p in args.parse_search_dir]

    if input_path.is_file() and input_path.name == "final_extraction.json":
        # Single file mode
        print(f"Processing single file: {input_path}")
        manifest = generate_proofs_from_final_extraction(
            final_extraction_path=input_path,
            out_dir=out_dir / input_path.parent.name,
            parse_search_dirs=parse_dirs,
            scale=args.scale,
            max_locations_per_field=args.max_locations,
        )
        print(f"\nEvidence saved to: {manifest.get('evidence_dir')}")
        print(f"Fields processed: {len(manifest.get('fields', {}))}")

    elif input_path.is_dir():
        # Folder mode - process all final_extraction.json files
        print(f"Processing validation folder: {input_path}")
        results = process_validation_folder(
            validation_dir=input_path,
            out_base_dir=out_dir,
            scale=args.scale,
            max_locations_per_field=args.max_locations,
        )

        # Save summary
        summary_path = out_dir / "processing_summary.json"
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

        print(f"\n{'='*60}")
        print(f"Processing complete!")
        print(f"Categories processed: {len(results['categories'])}")
        print(f"Errors: {len(results['errors'])}")
        print(f"Summary saved to: {summary_path}")

    else:
        print(f"Error: Input must be a final_extraction.json file or a directory containing them.")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
