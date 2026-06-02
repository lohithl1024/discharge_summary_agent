from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory


class OcrUnavailableError(RuntimeError):
    pass


def ocr_pdf_pages(path: Path, max_pages: int | None = None, dpi: int = 200) -> dict[str, str]:
    try:
        import fitz
    except ImportError as exc:
        raise OcrUnavailableError(
            "PyMuPDF is not installed. Install Python OCR requirements with: "
            "python3 -m pip install PyMuPDF pytesseract"
        ) from exc

    try:
        import pytesseract
    except ImportError as exc:
        raise OcrUnavailableError(
            "pytesseract is not installed. Install Python OCR requirements with: "
            "python3 -m pip install PyMuPDF pytesseract"
        ) from exc

    if not _tesseract_available(pytesseract):
        raise OcrUnavailableError(
            "Tesseract OCR engine is not installed or not on PATH. On macOS run: "
            "brew install tesseract"
        )

    documents: dict[str, str] = {}
    zoom = dpi / 72
    matrix = fitz.Matrix(zoom, zoom)

    with fitz.open(str(path)) as pdf, TemporaryDirectory() as temp_dir:
        page_count = len(pdf) if max_pages is None else min(len(pdf), max_pages)
        for page_index in range(page_count):
            page = pdf[page_index]
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            image_path = Path(temp_dir) / f"page_{page_index + 1:03d}.png"
            pix.save(str(image_path))
            text = pytesseract.image_to_string(str(image_path)).strip()
            if text:
                documents[f"{path.stem}_ocr_page_{page_index + 1:03d}"] = text

    if documents:
        documents[f"{path.stem}_ocr_combined_text"] = "\n".join(documents.values())

    return documents


def _tesseract_available(pytesseract_module) -> bool:
    try:
        pytesseract_module.get_tesseract_version()
    except Exception:
        return False
    return True
