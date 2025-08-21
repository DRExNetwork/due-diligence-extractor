from __future__ import annotations
from pathlib import Path
from typing import List
from ddx.utils.progress import _progress_print

def ocr_pdf_to_pages(path: Path, lang: str = "spa+eng", dpi: int = 300, progress: bool = False) -> List[str]:
    pages: List[str] = []
    # Try PyMuPDF
    try:
        import fitz  # PyMuPDF
        import pytesseract
        from PIL import Image
        doc = fitz.open(str(path))
        total = doc.page_count
        for i in range(total):
            _progress_print(i+1, total, "OCR", f"{path.name} page {i+1}", enabled=progress)
            page = doc.load_page(i)
            mat = fitz.Matrix(dpi/72.0, dpi/72.0)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            txt = pytesseract.image_to_string(img, lang=lang)
            pages.append(txt or "")
        return pages
    except Exception:
        pass
    # Try pdf2image
    try:
        from pdf2image import convert_from_path
        import pytesseract
        images = convert_from_path(str(path), dpi=dpi)
        total = len(images)
        for i, img in enumerate(images, start=1):
            _progress_print(i, total, "OCR", f"{path.name} page {i}", enabled=progress)
            txt = pytesseract.image_to_string(img, lang=lang)
            pages.append(txt or "")
        return pages
    except Exception:
        pass
    return []
