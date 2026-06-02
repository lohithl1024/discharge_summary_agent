from __future__ import annotations

from pathlib import Path

from schemas import CaseState, ToolResult
from ocr import OcrUnavailableError, ocr_pdf_pages


MIN_TEXT_CHARS_PER_PDF = 100
OCR_TRIGGER_MIN_CHARS = 500


def ingest_pdf_documents(case: CaseState) -> ToolResult:
    if not case.source_paths:
        return ToolResult(ok=False, error="No PDF paths were provided.", retryable=False)

    try:
        import pypdf
    except ImportError:
        return ToolResult(
            ok=False,
            error="pypdf is not installed. Install requirements.txt before running PDF ingestion.",
            retryable=False,
        )

    documents: dict[str, str] = {}
    pdf_reports = []
    ocr_reports = []

    for source_path in case.source_paths:
        path = Path(source_path).expanduser()
        if not path.exists():
            return ToolResult(
                ok=False,
                error=f"PDF not found: {path}",
                retryable=False,
            )

        try:
            reader = pypdf.PdfReader(str(path))
        except Exception as exc:
            return ToolResult(
                ok=False,
                error=f"Failed to open PDF {path}: {exc}",
                retryable=True,
            )

        extracted_chars = 0
        non_empty_pages = 0
        pdf_documents: dict[str, str] = {}
        for page_index, page in enumerate(reader.pages, start=1):
            try:
                text = (page.extract_text() or "").strip()
            except Exception as exc:
                pdf_documents[f"{path.stem}_page_{page_index:03d}_read_error"] = (
                    f"PDF page read failed: {exc}"
                )
                continue

            if not text:
                continue

            non_empty_pages += 1
            extracted_chars += len(text)
            pdf_documents[f"{path.stem}_page_{page_index:03d}"] = text

        page_texts = [
            text
            for key, text in pdf_documents.items()
            if key.startswith(path.stem) and not key.endswith("_read_error")
        ]
        if page_texts:
            pdf_documents[f"{path.stem}_combined_text"] = "\n".join(page_texts)

        pdf_reports.append(
            {
                "path": str(path),
                "pages": len(reader.pages),
                "non_empty_pages": non_empty_pages,
                "extracted_chars": extracted_chars,
            }
        )

        if extracted_chars < OCR_TRIGGER_MIN_CHARS:
            try:
                ocr_documents = ocr_pdf_pages(path)
            except OcrUnavailableError as exc:
                if extracted_chars < MIN_TEXT_CHARS_PER_PDF:
                    return ToolResult(
                        ok=False,
                        data={"pdf_reports": pdf_reports, "ocr_reports": ocr_reports},
                        error=(
                            f"PDF text extraction returned only {extracted_chars} characters for {path}. "
                            f"OCR fallback is required but unavailable: {exc}"
                        ),
                        retryable=False,
                    )
                documents.update(pdf_documents)
                ocr_reports.append(
                    {
                        "path": str(path),
                        "attempted": True,
                        "used": False,
                        "reason": str(exc),
                    }
                )
                continue

            ocr_chars = sum(len(text) for text in ocr_documents.values())
            ocr_reports.append(
                {
                    "path": str(path),
                    "attempted": True,
                    "used": bool(ocr_documents),
                    "ocr_chunks": len(ocr_documents),
                    "ocr_chars": ocr_chars,
                }
            )
            if ocr_chars > extracted_chars:
                documents.update(ocr_documents)
                continue

        documents.update(pdf_documents)

    case.source_documents = documents
    case.expected_documents = [Path(path).name for path in case.source_paths]
    case.missing_documents = []

    return ToolResult(
        ok=True,
        data={
            "pdf_reports": pdf_reports,
            "ocr_reports": ocr_reports,
            "source_document_chunks": len(case.source_documents),
        },
    )
