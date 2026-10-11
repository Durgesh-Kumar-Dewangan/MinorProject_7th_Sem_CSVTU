"""
Phase 1 - multimodal document ingestion.

For PDFs, in addition to the text layer:

  tables  pdfplumber finds them -> converted to structured text
          ("Table (page 2): Row 1: Unit = 1; Topic = Arrays; Hours = 4.")
  images  PyMuPDF extracts embedded images -> each one gets
            * an image-type classification (chart/diagram, photograph,
              scanned text/screenshot, icon)      [pixel-statistics heuristic]
            * simple feature detection (size, orientation, dominant colours,
              edge density)
            * an optional BLIP caption if `transformers` + torch are installed
              and the model can be loaded (never required; never fatal)
          -> converted to a textual description so the RAG pipeline can retrieve it

The resulting text is appended to the extracted document text under a marker
line, so the normal chunk -> embed -> FAISS/BM25 path indexes it like any other
text and Phase 4 can label evidence as text / table / figure.

Honest scope: image *type* is a heuristic on pixel statistics, not a trained
classifier; captions exist only when BLIP is actually available at runtime.
"""
import io
import os
from typing import Any, Dict, List, Optional

MIN_IMAGE_SIDE = 64          # ignore icons/bullets/decorations smaller than this
MAX_IMAGES = 25
APPENDIX_MARKER = "--- Extracted tables and figures ---"

_blip = {"tried": False, "processor": None, "model": None}


# ------------------------------ tables ------------------------------------

def table_to_text(rows: List[List[Optional[str]]], page: int) -> str:
    cleaned = [[(c or "").strip().replace("\n", " ") for c in r] for r in rows if any((c or "").strip() for c in r)]
    if len(cleaned) < 2:
        return ""
    header, body = cleaned[0], cleaned[1:]
    lines = []
    for i, row in enumerate(body, start=1):
        cells = [f"{h or f'Column {j + 1}'} = {v}" for j, (h, v) in enumerate(zip(header, row)) if v]
        if cells:
            lines.append(f"Row {i}: " + "; ".join(cells) + ".")
    if not lines:
        return ""
    return f"Table (page {page}), columns: {', '.join(h for h in header if h)}.\n" + "\n".join(lines)


def extract_tables(pdf_path: str) -> List[Dict[str, Any]]:
    out = []
    try:
        import pdfplumber

        with pdfplumber.open(pdf_path) as pdf:
            for pno, page in enumerate(pdf.pages, start=1):
                for rows in page.extract_tables() or []:
                    text = table_to_text(rows, pno)
                    if text:
                        out.append({"page": pno, "rows": len(rows), "text": text})
    except Exception:
        pass
    return out


# ------------------------------ images ------------------------------------

_COLOR_NAMES = {
    "red": (220, 40, 40), "green": (40, 170, 70), "blue": (50, 90, 220), "yellow": (235, 210, 50),
    "orange": (240, 140, 40), "purple": (140, 70, 190), "black": (15, 15, 15), "white": (245, 245, 245),
    "gray": (128, 128, 128),
}


def _nearest_color_name(rgb) -> str:
    return min(_COLOR_NAMES, key=lambda n: sum((a - b) ** 2 for a, b in zip(rgb, _COLOR_NAMES[n])))


def analyse_image(img) -> Dict[str, Any]:
    """Feature detection + type classification from pixel statistics (PIL image in)."""
    import numpy as np

    w, h = img.size
    rgb = img.convert("RGB")
    small = rgb.resize((min(w, 128), min(h, 128)))
    arr = np.asarray(small).astype("int32")
    quant = (arr // 32).reshape(-1, 3)
    uniq, counts = np.unique(quant, axis=0, return_counts=True)
    order = counts.argsort()[::-1]
    top_share = float(counts[order[:3]].sum() / counts.sum())
    n_colors = len(uniq)

    gray = np.asarray(small.convert("L")).astype("float32")
    gx = np.abs(np.diff(gray, axis=1)).mean()
    gy = np.abs(np.diff(gray, axis=0)).mean()
    edge_density = float((gx + gy) / 2 / 255)
    bg = gray > 225
    white_share = float(bg.mean())
    # share of non-background pixels that are visibly coloured (charts use
    # coloured fills; scanned pages / screenshots of text are near-monochrome)
    hsv = np.asarray(small.convert("HSV")).astype("float32") / 255.0
    ink = ~bg
    coloured_ink = float(((hsv[..., 1] > 0.35) & ink).sum() / max(int(ink.sum()), 1))

    dominant = []
    for idx in order[:3]:
        name = _nearest_color_name(tuple(int(v) * 32 + 16 for v in uniq[idx]))
        if name not in dominant:
            dominant.append(name)

    if max(w, h) < 96:
        kind = "icon or logo"
    elif n_colors > 60 and top_share < 0.55:
        kind = "photograph"
    elif white_share > 0.5 and coloured_ink < 0.15:
        kind = "scanned text or screenshot"
    else:
        kind = "chart or diagram"

    return {
        "width": w,
        "height": h,
        "orientation": "landscape" if w > h * 1.15 else ("portrait" if h > w * 1.15 else "square"),
        "type": kind,
        "dominant_colors": dominant,
        "edge_density": round(edge_density, 3),
        "coloured_share": round(coloured_ink, 3),
        "colors_used": int(n_colors),
    }


def caption_image(img) -> Optional[str]:
    """BLIP caption if available; None otherwise (never raises)."""
    if not _blip["tried"]:
        _blip["tried"] = True
        try:
            from transformers import BlipForConditionalGeneration, BlipProcessor

            name = os.environ.get("BLIP_MODEL", "Salesforce/blip-image-captioning-base")
            _blip["processor"] = BlipProcessor.from_pretrained(name)
            _blip["model"] = BlipForConditionalGeneration.from_pretrained(name)
        except Exception:
            _blip["processor"] = _blip["model"] = None
    if _blip["model"] is None:
        return None
    try:
        inputs = _blip["processor"](img.convert("RGB"), return_tensors="pt")
        ids = _blip["model"].generate(**inputs, max_new_tokens=40)
        return _blip["processor"].decode(ids[0], skip_special_tokens=True).strip() or None
    except Exception:
        return None


def describe_image(page: int, info: Dict[str, Any], caption: Optional[str]) -> str:
    base = (
        f"Figure (page {page}): a {info['orientation']} {info['type']}, {info['width']}x{info['height']} px, "
        f"mostly {' and '.join(info['dominant_colors'][:2]) or 'neutral colours'}"
    )
    return base + (f'; caption: "{caption}".' if caption else ".")


def extract_images(pdf_path: str) -> List[Dict[str, Any]]:
    out = []
    try:
        import fitz
        from PIL import Image

        doc = fitz.open(pdf_path)
        seen = set()
        for pno, page in enumerate(doc, start=1):
            for img_ref in page.get_images(full=True):
                xref = img_ref[0]
                if xref in seen or len(out) >= MAX_IMAGES:
                    continue
                seen.add(xref)
                try:
                    data = doc.extract_image(xref)["image"]
                    img = Image.open(io.BytesIO(data))
                    img.load()
                except Exception:
                    continue
                if min(img.size) < MIN_IMAGE_SIDE:
                    continue
                info = analyse_image(img)
                caption = caption_image(img)
                out.append({"page": pno, **info, "caption": caption, "text": describe_image(pno, info, caption)})
        doc.close()
    except Exception:
        pass
    return out


# ------------------------------ entry point --------------------------------

def extract_multimodal_appendix(pdf_path: str) -> Dict[str, Any]:
    """Tables + figures of a PDF as {'text': appendix, 'tables': [...], 'images': [...]}."""
    tables = extract_tables(pdf_path)
    images = extract_images(pdf_path)
    parts = [t["text"] for t in tables] + [i["text"] for i in images]
    text = f"\n\n{APPENDIX_MARKER}\n" + "\n\n".join(parts) + "\n" if parts else ""
    return {"text": text, "tables": tables, "images": images}


def modality_of(chunk_text: str) -> str:
    t = (chunk_text or "").lstrip()
    if t.startswith("Table (page") or "\nTable (page" in chunk_text or "Row 1:" in chunk_text:
        return "table"
    if "Figure (page" in chunk_text:
        return "figure"
    return "text"
