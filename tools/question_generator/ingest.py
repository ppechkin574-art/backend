"""Extract clean text from a chapter file.

Per page:
  - Pull the embedded text layer (pypdf).
  - If a page yields little/no text (a scan), render it to a PNG and OCR it
    with Claude vision (text + LaTeX formulas).
Auto-detects text vs scan by characters-per-page.

PDF rendering needs PyMuPDF (fitz). pypdf handles the text layer. Both are
optional at import time so the pure parts of the package import without them;
ingest raises a clear error if a needed dep is missing when actually used.

Non-PDF inputs: .txt / .md are read directly.
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from typing import List, Optional

from .config import get_logger
from .prompts import OCR_SYSTEM, OCR_USER

logger = get_logger("qgen.ingest")

# Below this many extractable chars on a page, treat it as a scan and OCR.
SCAN_TEXT_THRESHOLD = 40


@dataclass
class PageText:
    page_number: int  # 1-based
    text: str
    source: str  # "text-layer" | "ocr" | "empty"


def _read_plain_text(path: str) -> List[PageText]:
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        content = fh.read()
    return [PageText(page_number=1, text=content, source="text-layer")]


def _extract_pdf_text_layer(path: str):
    """Yield (page_number, text) using pypdf. Lazy import."""
    from pypdf import PdfReader  # noqa: WPS433

    reader = PdfReader(path)
    for i, page in enumerate(reader.pages):
        try:
            txt = page.extract_text() or ""
        except Exception as e:  # pragma: no cover - per-page robustness
            logger.warning("Text extraction failed on page %d: %s", i + 1, e)
            txt = ""
        yield i + 1, txt


def _render_page_png_b64(path: str, page_index0: int, zoom: float = 2.0) -> Optional[str]:
    """Render one PDF page (0-based) to base64 PNG via PyMuPDF. None on failure."""
    try:
        import fitz  # PyMuPDF  # noqa: WPS433
    except Exception:
        logger.error(
            "PyMuPDF (fitz) not installed — cannot OCR scanned pages. "
            "Install with: pip install pymupdf"
        )
        return None
    try:
        doc = fitz.open(path)
        page = doc.load_page(page_index0)
        matrix = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=matrix)
        png_bytes = pix.tobytes("png")
        doc.close()
        return base64.standard_b64encode(png_bytes).decode("utf-8")
    except Exception as e:  # pragma: no cover
        logger.warning("Render failed on page %d: %s", page_index0 + 1, e)
        return None


_WATERMARK_MARKERS = (
    "okulyk",
    "учебники казахстана",
    "книга предоставлена",
    "приказа министр",
)


def _strip_watermark(text: str) -> str:
    """Drop the per-page OKULYK.KZ watermark lines that pollute scanned pages
    (both in the thin text layer and in OCR output)."""
    if not text:
        return text
    out = []
    for line in text.split("\n"):
        low = line.lower()
        if any(m in low for m in _WATERMARK_MARKERS):
            continue
        out.append(line)
    return "\n".join(out).strip()


def ingest_chapter(
    path: str,
    client=None,
    ocr_model: Optional[str] = None,
    max_pages: Optional[int] = None,
    scan_threshold: int = SCAN_TEXT_THRESHOLD,
    start_page: int = 1,
    force_ocr: bool = False,
) -> str:
    """Return cleaned chapter text.

    Args:
        path: chapter file (.pdf / .txt / .md).
        client: vision client (required only if any page needs OCR).
        ocr_model: model id for vision OCR.
        max_pages: number of pages to process FROM start_page (None = all).
        scan_threshold: chars/page below which a page is OCR'd.
        start_page: 1-indexed first page to process (skip front matter).
        force_ocr: OCR every page even if it has a text layer — needed for
            scans whose only text layer is a per-page watermark.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(path)

    ext = os.path.splitext(path)[1].lower()
    if ext in (".txt", ".md"):
        pages = _read_plain_text(path)
    elif ext == ".pdf":
        pages = []
        for page_no, txt in _extract_pdf_text_layer(path):
            if page_no < start_page:
                continue
            if max_pages and (page_no - start_page + 1) > max_pages:
                break
            clean = _strip_watermark((txt or "").strip())
            if not force_ocr and len(clean) >= scan_threshold:
                pages.append(PageText(page_no, clean, "text-layer"))
            else:
                # Likely a scan — OCR via vision if we can.
                if client is None:
                    logger.warning(
                        "Page %d looks scanned (%d chars) but no Claude client "
                        "provided for OCR; keeping the sparse text.",
                        page_no,
                        len(clean),
                    )
                    pages.append(
                        PageText(page_no, clean, "text-layer" if clean else "empty")
                    )
                    continue
                b64 = _render_page_png_b64(path, page_no - 1)
                if b64 is None:
                    pages.append(PageText(page_no, clean, "empty"))
                    continue
                ocr_text = _strip_watermark(_ocr_page(client, ocr_model, b64, page_no))
                pages.append(
                    PageText(page_no, ocr_text, "ocr" if ocr_text else "empty")
                )
    else:
        raise ValueError(f"Unsupported chapter file type: {ext}")

    n_ocr = sum(1 for p in pages if p.source == "ocr")
    logger.info(
        "Ingested %d page(s) from %s (%d OCR'd).", len(pages), os.path.basename(path), n_ocr
    )
    return _stitch(pages)


def _ocr_page(client, ocr_model: Optional[str], image_b64: str, page_no: int) -> str:
    from .llm import call_vision_text  # lazy to keep imports light

    try:
        text = call_vision_text(
            client=client,
            model=ocr_model,
            system=OCR_SYSTEM,
            user=OCR_USER,
            image_b64=image_b64,
        )
        return (text or "").strip()
    except Exception as e:  # pragma: no cover - network path
        logger.warning("OCR failed on page %d: %s", page_no, e)
        return ""


def _stitch(pages: List[PageText]) -> str:
    """Join page texts with light page markers (helps source page tracking)."""
    out: List[str] = []
    for p in pages:
        if not p.text.strip():
            continue
        out.append(p.text.strip())
    return "\n\n".join(out)
