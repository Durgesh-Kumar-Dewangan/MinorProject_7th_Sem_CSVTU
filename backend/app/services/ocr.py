"""
file path in → raw extracted text out
"""
import os
from typing import Literal

def extract_text_from_file(file_path: str, file_type: Literal["pdf", "image", "text"]) -> str:
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    if file_type == "text":
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()

    if file_type == "pdf":
        return _extract_from_pdf(file_path)

    if file_type == "image":
        return _extract_from_image(file_path)

    raise ValueError(f"Unsupported file_type: {file_type}")

def _extract_from_pdf(file_path: str) -> str:
    """Try text-layer first (PyMuPDF / pdfplumber), then tables (camelot), then OCR.

    Each strategy collects into its OWN list. They used to share one
    `text_parts` list that was never reset between attempts, so a PyMuPDF
    pass that produced *some* text but fell under the 80-char threshold left
    that text sitting in the list for pdfplumber to append to - and every
    page came out duplicated in the extracted text (which then gets chunked,
    embedded and retrieved as evidence, so the duplication propagated all
    the way into the lesson's grounding).
    """
    # 1. PyMuPDF (fast, good for text PDFs)
    try:
        import fitz  # PyMuPDF
        parts = []
        doc = fitz.open(file_path)
        for page in doc:
            parts.append(page.get_text("text"))
        doc.close()
        joined = "\n".join(parts).strip()
        if len(joined) > 80:          # enough signal that it is not a pure scan
            return joined + _multimodal_appendix(file_path)
    except Exception:
        pass

    # 2. pdfplumber (sometimes better layout)
    try:
        import pdfplumber
        parts = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                parts.append(page.extract_text() or "")
        joined = "\n".join(parts).strip()
        if len(joined) > 80:
            return joined + _multimodal_appendix(file_path)
    except Exception:
        pass

    # 3. camelot for tables (optional, can be slow)
    try:
        import camelot
        parts = []
        tables = camelot.read_pdf(file_path, pages="all", flavor="lattice")
        for t in tables:
            parts.append(t.df.to_string())
        if any(p.strip() for p in parts):
            return "\n".join(parts)
    except Exception:
        pass

    # 4. Fallback: render pages → PaddleOCR
    return _ocr_pdf_pages(file_path)

def _multimodal_appendix(file_path: str) -> str:
    """Phase 1 multimodal ingestion: tables -> structured text, images -> descriptions.
    Never allowed to break plain-text extraction."""
    try:
        from app.services.multimodal import extract_multimodal_appendix

        return extract_multimodal_appendix(file_path)["text"]
    except Exception:
        return ""


def _ocr_pdf_pages(file_path: str) -> str:
    try:
        import fitz
        from paddleocr import PaddleOCR
    except ImportError as e:
        raise RuntimeError(
            f"'{os.path.basename(file_path)}' appears to be a scanned PDF with no "
            "extractable text layer, so it needs OCR - but the OCR package isn't "
            "installed. Run install-ocr.sh (Mac/Linux) or install-ocr.cmd "
            "(Windows) from the project root to add it, or re-upload a "
            "text-based PDF instead."
        ) from e
    ocr = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
    doc = fitz.open(file_path)
    all_text = []
    for page in doc:
        pix = page.get_pixmap(dpi=200)
        img_bytes = pix.tobytes("png")
        result = ocr.ocr(img_bytes, cls=True)
        if result and result[0]:
            page_text = "\n".join([line[1][0] for line in result[0]])
            all_text.append(page_text)
    doc.close()
    return "\n".join(all_text)

def _extract_from_image(file_path: str) -> str:
    try:
        from paddleocr import PaddleOCR
    except ImportError as e:
        raise RuntimeError(
            f"'{os.path.basename(file_path)}' is an image file, which needs OCR to "
            "extract text - but the OCR package isn't installed. Run "
            "install-ocr.sh (Mac/Linux) or install-ocr.cmd (Windows) from the "
            "project root to add it, or re-upload a PDF/text file instead."
        ) from e
    ocr = PaddleOCR(use_angle_cls=True, lang="en", show_log=False)
    result = ocr.ocr(file_path, cls=True)
    if not result or not result[0]:
        return ""
    return "\n".join([line[1][0] for line in result[0]])