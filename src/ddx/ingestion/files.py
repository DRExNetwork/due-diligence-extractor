from __future__ import annotations
from pathlib import Path
from typing import Optional, List
from ddx.ingestion.pdf import extract_text_pages_from_pdf
from ddx.ingestion.ocr import ocr_pdf_to_pages
from ddx.kmz.reader import read_kmz_file

def read_doc_pages(path: Path, ocr: bool = False, ocr_lang: str = "spa+eng", ocr_dpi: int = 300, progress: bool = False) -> List[str]:
    suf = path.suffix.lower()
    if suf == ".pdf":
        pages = extract_text_pages_from_pdf(path)
        if not any(p.strip() for p in pages) and ocr:
            pages = ocr_pdf_to_pages(path, lang=ocr_lang, dpi=ocr_dpi, progress=progress)
        return pages or [""]
    if suf == ".txt":
        try:
            return [path.read_text(encoding="utf-8", errors="ignore")]
        except Exception:
            return [""]
    if suf == ".csv":
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
            lines = content.splitlines()
            head = lines[0] if lines else ""
            n_rows = max(0, len(lines) - 1)
            return [f"CSV:{path.name}\nHeader:{head}\nRows:{n_rows}\n\n{content[:2000]}"]
        except Exception:
            return [""]
    if suf == ".kmz":
        return read_kmz_file(path)
    return [""]

def discover_files(docs_dir: Optional[Path]) -> List[Path]:
    if not docs_dir or not docs_dir.exists():
        return []
    return (
        sorted(docs_dir.glob("*.pdf"))
        + sorted(docs_dir.glob("*.txt"))
        + sorted(docs_dir.glob("*.csv"))
        + sorted(docs_dir.glob("*.kmz"))
    )
