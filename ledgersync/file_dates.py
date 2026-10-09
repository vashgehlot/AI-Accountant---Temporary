"""The date in an upload's file name, as a check on the date read from a receipt or an invoice: an expense app's
export (Southgate_Bath_Car_Park-2026-09-09_19_52_00.jpg) or a phone's photo (IMG_20260909_195200.jpg) names the
day. A name can also carry the day a document was scanned or saved, so its date is offered, never taken."""
from __future__ import annotations

import datetime as dt
import re
from typing import Optional

from .checks import issue, long_date
from .models import Transaction

_YEAR_FIRST = re.compile(r"(?<!\d)(20\d{2})[-_.]?(\d{2})[-_.]?(\d{2})(?!\d)")
_DAY_FIRST = re.compile(r"(?<!\d)(\d{2})[-_.](\d{2})[-_.](20\d{2})(?!\d)")
NEAR = dt.timedelta(days=3)   # a file named a day or two after the purchase is the same purchase


def date_in_name(name: str) -> Optional[dt.date]:
    """The one date a file name holds, year first or day first; None when it holds none, or more than one."""
    found = set()
    for pattern, year, month, day in ((_YEAR_FIRST, 1, 2, 3), (_DAY_FIRST, 3, 2, 1)):
        for match in pattern.finditer(name):
            try:
                found.add(dt.date(int(match.group(year)), int(match.group(month)), int(match.group(day))))
            except ValueError:   # 2026-13-45: digits, not a date
                continue
    return found.pop() if len(found) == 1 else None


def check_file_date(rows: list[Transaction], name: str) -> list[Transaction]:
    """The rows of one upload. When they are one receipt or invoice whose date nothing else confirms (its claim line,
    or a receipt's card payment), and the file name holds a date more than a few days from it, or it has none, the
    document asks which date is right."""
    named = date_in_name(name)
    if named is None or not rows or len({tx.document_ref for tx in rows}) != 1:
        return rows
    first = rows[0]
    if first.document_type not in ("receipt", "invoice") or any(
            tx.date_found or tx.claimed_in or (tx.document_type == "receipt" and tx.paid_by) for tx in rows):
        return rows
    if first.date is not None and abs(first.date - named) <= NEAR:
        return rows
    read = f"Read as {long_date(first.date)}" if first.date else "No date"
    asks = issue("file_date", f"{read}; the file name says {long_date(named)}.")
    return [first.model_copy(update={"date_found": named, "issues": first.issues + [asks]}), *rows[1:]]
