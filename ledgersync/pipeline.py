"""Turns a validated upload into what the model reads and runs the extractor: text goes as text;
photos and scanned pages go as upright, downscaled JPEGs, client.max_images per request.
Replaced in Phase 4 by the hybrid pipeline (deterministic parsing + LLM classification)."""
from __future__ import annotations

import base64
import io
import logging
from typing import Optional

from .intake import PYMUPDF_LOCK, Intake
from .jobs import JobContext

logger = logging.getLogger(__name__)


def analyze(intake: Intake, extractor, ctx: JobContext):
    """Runs one analysis and returns the extractor's TransactionExtractionResult."""
    text = intake.text
    if intake.kind == "image":
        return _read_pages([intake.data], extractor, ctx)
    if intake.kind == "pdf":
        ctx.report("Extracting text from the PDF")
        text = _pdf_text(intake.data)
        if not text:   # a scan: the model reads the page images
            return _read_pages(_pdf_pages(intake.data), extractor, ctx)
    ctx.report(f"Asking the AI model ({extractor.client.model})")
    return extractor.extract_accounting_data(text_input=text, images=None)


def prepare_image(data: bytes, max_side: int = 1200) -> str:
    """A photo or page as a vision model should get it: upright (the camera's EXIF orientation
    applied), at most max_side pixels on its long side, as a base64 JPEG."""
    from PIL import Image, ImageOps
    with Image.open(io.BytesIO(data)) as img:
        upright = ImageOps.exif_transpose(img).convert("RGB")
    upright.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    upright.save(buf, "JPEG", quality=75)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _read_pages(pages: list[bytes], extractor, ctx: JobContext):
    """Sends page images to the model, client.max_images per request, and merges the answers.
    With several requests, each warning says which pages it came from."""
    size = max(1, extractor.client.max_images)
    several = len(pages) > size
    result = None
    for start in range(0, len(pages), size):
        batch = pages[start:start + size]
        label = f"Page {start + 1}" if len(batch) == 1 else f"Pages {start + 1}-{start + len(batch)}"
        ctx.report(f"Asking the AI model ({extractor.client.model})" + (f": {label.lower()}" if several else ""))
        part = extractor.extract_accounting_data(text_input=None, images=[prepare_image(p) for p in batch])
        if several:
            part = part.model_copy(update={"warnings": [f"{label}: {w}" for w in part.warnings]})
        result = part if result is None else result.model_copy(update={
            "data": result.data + part.data, "warnings": result.warnings + part.warnings,
            # A statement's opening balance is on its first pages, its closing balance on its last.
            "opening_balance": result.opening_balance if result.opening_balance is not None else part.opening_balance,
            "closing_balance": part.closing_balance if part.closing_balance is not None else result.closing_balance,
            "agent": result.agent or part.agent,
            "model": _joined(result.model, part.model)})
    return result


def _joined(names: Optional[str], name: Optional[str]) -> Optional[str]:
    """The models that read an input's pages, with their hosts, each named once: each request may go to another host."""
    seen = names.split("; ") if names else []
    return "; ".join(seen + [name]) if name and name not in seen else names


def _pdf_pages(data: bytes) -> list[bytes]:
    import pymupdf
    with PYMUPDF_LOCK, pymupdf.open(stream=data, filetype="pdf") as doc:
        return [page.get_pixmap(dpi=150).tobytes("png") for page in doc]


def _pdf_text(data: bytes) -> Optional[str]:
    """The text layer, in reading order with each line of the page kept together: a table's cells
    stay in their row, where a column-by-column read would separate dates from their amounts."""
    import pymupdf
    try:
        with PYMUPDF_LOCK, pymupdf.open(stream=data, filetype="pdf") as doc:
            text = "\n\n".join(page.get_text("text", sort=True) for page in doc)
    except Exception as exc:
        logger.warning("PDF text extraction failed (%s); the model will read the pages instead", type(exc).__name__)
        return None
    return text.strip() or None
