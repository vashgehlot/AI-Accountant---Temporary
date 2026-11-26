"""Excel files a client or the previous accountant sends, written so the same input gives the same bytes: fixed
document properties, and every zip entry stamped with one fixed time."""
from __future__ import annotations

import re
import zipfile
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook

FIXED = datetime(2024, 1, 1)
FIXED_ZIP_TIME = (2024, 1, 1, 0, 0, 0)


def normalise_zip(path: Path) -> Path:
    """Rewrite an .xlsx with every entry's timestamp fixed, and the document's "modified" time too: openpyxl stamps
    both with the time of saving, whatever the properties say."""
    with zipfile.ZipFile(path) as src:
        entries = [(info, src.read(info.filename)) for info in src.infolist()]
    entries = [(info, re.sub(rb"(<dcterms:modified[^>]*>)[^<]*(</dcterms:modified>)",
                             rb"\g<1>2024-01-01T00:00:00Z\g<2>", data) if info.filename == "docProps/core.xml" else data)
               for info, data in entries]
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as dst:
        for info, data in entries:
            fixed = zipfile.ZipInfo(info.filename, date_time=FIXED_ZIP_TIME)
            fixed.compress_type = zipfile.ZIP_DEFLATED
            fixed.external_attr = info.external_attr
            dst.writestr(fixed, data)
    return path


def save(wb: Workbook, path: Path) -> Path:
    """Save a workbook with fixed properties and fixed zip times."""
    wb.properties.creator = "testbooks"
    wb.properties.created = wb.properties.modified = FIXED
    wb.save(path)
    return normalise_zip(path)


def write_xlsx(path: Path, sheets: dict[str, list[list]]) -> Path:
    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name[:31])
        for row in rows:
            ws.append(row)
    wb.properties.description = "Synthetic test data, not a real document"
    return save(wb, path)
