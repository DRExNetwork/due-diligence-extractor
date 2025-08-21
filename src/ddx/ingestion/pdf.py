from __future__ import annotations
import subprocess
from pathlib import Path
from typing import List

def _run_pdftotext(path: Path) -> List[str]:
    try:
        out = subprocess.run(
            ["pdftotext", "-layout", str(path), "-"],
            capture_output=True, text=True, timeout=60
        )
        if out.returncode == 0 and out.stdout:
            txt = out.stdout
            pages = [p for p in txt.split("\f") if p.strip()]
            return pages or [txt]
    except Exception:
        pass
    return []

def extract_text_pages_from_pdf(path: Path) -> List[str]:
    # Try PyPDF2
    try:
        import PyPDF2  # type: ignore
        pages: List[str] = []
        with open(path, "rb") as f:
            reader = PyPDF2.PdfReader(f)
            for pg in reader.pages:
                try:
                    pages.append(pg.extract_text() or "")
                except Exception:
                    pages.append("")
        if any(p.strip() for p in pages):
            return pages
    except Exception:
        pass
    # Try pdfminer.six
    try:
        from pdfminer.high_level import extract_text  # type: ignore
        txt = extract_text(str(path))
        if txt:
            pages = [p for p in txt.split("\x0c") if p.strip()]
            if pages:
                return pages
    except Exception:
        pass
    # Try pdftotext CLI
    pages = _run_pdftotext(path)
    if pages:
        return pages
    return []
