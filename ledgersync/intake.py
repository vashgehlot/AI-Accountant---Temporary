"""Validates uploads before any expensive work: size, real file type (by content, not just
the name) and readability. Nothing unreadable ever reaches the model."""
from __future__ import annotations

import io
import threading
from dataclasses import dataclass
from pathlib import PurePath
from typing import BinaryIO, Literal, Optional

from .errors import FileTooLarge, UnreadableFile, UnsupportedFile

# PyMuPDF is not thread-safe: uploads are checked while several jobs run, so every use takes this lock.
PYMUPDF_LOCK = threading.Lock()

Kind = Literal["text", "table", "pdf", "image"]

SUPPORTED = "CSV, TSV, TXT, XLSX, XLS, PDF, PNG, JPG, WEBP, BMP or TIFF"
TEXT_KINDS = {".txt": "text", ".csv": "table", ".tsv": "table"}
EXCEL_EXTENSIONS = {".xlsx", ".xls"}
# The extensions a file can have to be accepted: SUPPORTED, as a set.
EXTENSIONS = (set(TEXT_KINDS) | EXCEL_EXTENSIONS
              | {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"})

_ZIP = b"PK\x03\x04"
_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"   # legacy .xls container
_UTF16_BOMS = (b"\xff\xfe", b"\xfe\xff")


@dataclass(frozen=True)
class Intake:
    kind: Kind
    text: Optional[str] = None     # "text" and "table" kinds
    data: Optional[bytes] = None   # "pdf" and "image" kinds


def read_limited(stream: BinaryIO, max_bytes: int) -> bytes:
    """Reads at most max_bytes, refusing anything larger instead of loading it all."""
    data = stream.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise FileTooLarge(f"The file is larger than the {_limit(max_bytes)} limit.")
    return data


def from_text(text: str, max_bytes: int) -> Intake:
    if len(text.encode("utf-8")) > max_bytes:
        raise FileTooLarge(f"The pasted text is larger than the {_limit(max_bytes)} limit.")
    if not text.strip():
        raise UnreadableFile("There is no text to analyse.")
    return Intake("text", text=text.strip())


def load_upload(filename: str, data: bytes, max_pdf_pages: int) -> Intake:
    if not data:
        raise UnreadableFile(f"'{filename}' is empty.")
    ext = PurePath(filename).suffix.lower()
    if b"%PDF-" in data[:1024]:
        return Intake("pdf", data=_check_pdf(data, filename, max_pdf_pages))
    if _is_image(data):
        return Intake("image", data=_check_image(data, filename))
    return _read_text_file(filename, data)


def text_of_bytes(filename: str, data: bytes) -> Optional[str]:
    """The text of a CSV, TXT or spreadsheet (sheets as tab-separated lines), or None for a PDF or an image,
    which are not text files. Raises as load_upload does for a file that is none of these."""
    if b"%PDF-" in data[:1024] or _is_image(data):
        return None
    return _read_text_file(filename, data, sep="\t").text


def _read_text_file(filename: str, data: bytes, sep: str = ",") -> Intake:
    """A spreadsheet or a text file as an Intake; sep separates the cells of a spreadsheet's rows."""
    ext = PurePath(filename).suffix.lower()
    if ext in EXCEL_EXTENSIONS:
        if data.startswith(_ZIP):
            return Intake("table", text=_excel_to_text(data, filename, engine="openpyxl", sep=sep))
        if data.startswith(_OLE):
            return Intake("table", text=_excel_to_text(data, filename, engine="xlrd", sep=sep))
        if _looks_like_text(data):    # some banks export tab-separated text or HTML named .xls
            return Intake("table", text=_decode_text(data, filename))
        raise UnreadableFile(f"'{filename}' is not a valid Excel file.")
    if ext in TEXT_KINDS:
        return Intake(TEXT_KINDS[ext], text=_decode_text(data, filename))
    raise UnsupportedFile(f"'{filename}' is not a supported file type. Use {SUPPORTED}.")


def _is_image(data: bytes) -> bool:
    return (data.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"II*\x00", b"MM\x00*"))
            or (data[:2] == b"BM" and data[6:10] == b"\x00\x00\x00\x00")   # BMP: reserved bytes are zero
            or (data[:4] == b"RIFF" and data[8:12] == b"WEBP"))


def _check_pdf(data: bytes, filename: str, max_pages: int) -> bytes:
    import pymupdf
    with PYMUPDF_LOCK:
        try:
            doc = pymupdf.open(stream=data, filetype="pdf")
        except Exception:
            raise UnreadableFile(f"'{filename}' is not a valid PDF. It may be corrupt.") from None
        with doc:
            if doc.needs_pass:
                raise UnreadableFile(f"'{filename}' is password-protected. Save a copy without the "
                                     "password and upload that.")
            if doc.page_count == 0:
                raise UnreadableFile(f"'{filename}' has no pages.")
            if doc.page_count > max_pages:
                raise FileTooLarge(f"'{filename}' has {doc.page_count} pages; the limit is {max_pages}. "
                                   "Split it and upload the parts.")
    return data


def _check_image(data: bytes, filename: str) -> bytes:
    from PIL import Image
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
    except Exception:
        raise UnreadableFile(f"'{filename}' could not be read as an image. It may be corrupt.") from None
    return data


def _excel_to_text(data: bytes, filename: str, engine: str, sep: str = ",") -> str:
    import pandas as pd
    try:
        sheets = pd.read_excel(io.BytesIO(data), sheet_name=None, header=None, engine=engine)
    except ImportError:
        raise UnreadableFile("Reading this spreadsheet needs a missing package. "
                             "Run: pip install -r requirements.txt") from None
    except Exception:
        raise UnreadableFile(f"'{filename}' could not be read as a spreadsheet. It may be corrupt.") from None
    parts = []
    for name, frame in sheets.items():
        frame = frame.dropna(how="all").dropna(axis=1, how="all")
        if not frame.empty:
            parts.append(f"# Sheet: {name}\n{frame.to_csv(index=False, header=False, sep=sep).strip()}")
    if not parts:
        raise UnreadableFile(f"'{filename}' has no data in any sheet.")
    return "\n\n".join(parts)


def _looks_like_text(data: bytes) -> bool:
    return data.startswith(_UTF16_BOMS) or b"\x00" not in data[:8192]


def _decode_text(data: bytes, filename: str) -> str:
    if not _looks_like_text(data):
        raise UnreadableFile(f"'{filename}' is not a text file.")
    if data.startswith(_UTF16_BOMS):                 # Excel "Unicode Text" exports
        text = data.decode("utf-16", errors="replace")
    else:
        for encoding in ("utf-8-sig", "cp1252", "latin-1"):   # latin-1 accepts any byte
            try:
                text = data.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        raise UnreadableFile(f"'{filename}' has no text.")
    return text


def _limit(max_bytes: int) -> str:
    mb = max_bytes / (1024 * 1024)
    return f"{mb:g} MB" if mb >= 1 else f"{max_bytes} bytes"
