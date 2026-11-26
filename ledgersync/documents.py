"""One service that returns any uploaded document's text, page by page, for the accountant chat. The
text is kept by the file's SHA-256, so a scan or photo is sent to the vision model once, ever."""
from __future__ import annotations

from typing import Optional

from . import intake
from .errors import ModelUnavailable
from .pipeline import _pdf_pages, pdf_page_texts, prepare_image

PAGE_CHARS = 12_000   # the most characters in one page of text


def text_of(upload: dict, blobs, records, vision=None) -> list[str]:
    """The pages of text of an upload's original file. Spreadsheets, CSV, TXT and PDFs with a text layer are
    read directly; images and scanned PDFs are transcribed by `vision` (ModelClient.transcribe). An upload
    with no original (a manual row, a split) has no text: []. Needing vision without one raises
    ModelUnavailable."""
    sha256 = upload.get("sha256") or ""
    if not sha256:
        return []
    cached = records.document_text(sha256)
    if cached is not None:
        return cached
    data = blobs.get(sha256).data
    pages, method = _read(upload.get("name") or "", data, vision)
    if pages:   # nothing read is not kept, so a later try can read it again
        records.save_document_text(sha256, pages, method, vision.model if method == "vision" else "")
    return pages


def _read(name: str, data: bytes, vision) -> tuple[list[str], str]:
    """(pages, "text" or "vision") for the file's bytes."""
    text = intake.text_of_bytes(name, data)
    if text is not None:
        return _split(text), "text"
    if b"%PDF-" in data[:1024]:
        texts = pdf_page_texts(data)
        if texts:   # each page is its own page of text, split further only if it is long
            return [part for text in texts for part in _split(text)], "text"
        images = [prepare_image(page) for page in _pdf_pages(data)]   # a scan
    else:
        images = [prepare_image(data)]
    if vision is None:
        raise ModelUnavailable("This document is an image; reading it needs the vision model.")
    pages = []
    for image in images:   # each page is its own page of text, split further only if it is long
        pages += _split(vision.transcribe(image))
    return pages, "vision"


def _split(text: str, limit: int = PAGE_CHARS) -> list[str]:
    """The text in pages of at most `limit` characters, each ending at a line break where the text has one."""
    pages = []
    while len(text) > limit:
        cut = text.rfind("\n", 1, limit + 1)
        if cut == -1:   # one line longer than a page: cut it
            pages.append(text[:limit])
            text = text[limit:]
        else:
            pages.append(text[:cut])
            text = text[cut + 1:]
    if text.strip():
        pages.append(text)
    return pages
