"""Working days in England and Wales, and the dates tax falls due."""
from __future__ import annotations

from datetime import date, timedelta

# England and Wales bank holidays (source: https://www.gov.uk/bank-holidays).
BANK_HOLIDAYS: frozenset[date] = frozenset(date.fromisoformat(d) for d in (
    "2023-01-02", "2023-04-07", "2023-04-10", "2023-05-01", "2023-05-08", "2023-05-29", "2023-08-28",
    "2023-12-25", "2023-12-26",
    "2024-01-01", "2024-03-29", "2024-04-01", "2024-05-06", "2024-05-27", "2024-08-26", "2024-12-25",
    "2024-12-26",
    "2025-01-01", "2025-04-18", "2025-04-21", "2025-05-05", "2025-05-26", "2025-08-25", "2025-12-25",
    "2025-12-26",
    "2026-01-01", "2026-04-03", "2026-04-06", "2026-05-04", "2026-05-25", "2026-08-31", "2026-12-25",
    "2026-12-28",
    "2027-01-01",
))

ONE_DAY = timedelta(days=1)


def is_working_day(d: date) -> bool:
    return d.weekday() < 5 and d not in BANK_HOLIDAYS


def next_working_day(d: date) -> date:
    """`d` itself when it is a working day, otherwise the next one."""
    while not is_working_day(d):
        d += ONE_DAY
    return d


def previous_working_day(d: date) -> date:
    """`d` itself when it is a working day, otherwise the one before."""
    while not is_working_day(d):
        d -= ONE_DAY
    return d


def add_working_days(d: date, n: int) -> date:
    """The nth working day after `d`."""
    while n > 0:
        d += ONE_DAY
        if is_working_day(d):
            n -= 1
    return d


def add_months(d: date, months: int) -> date:
    """The same day `months` later, or the month's last day when it has fewer days."""
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    last = (date(year + (month == 12), month % 12 + 1, 1) - ONE_DAY).day
    return date(year, month, min(d.day, last))


def month_end(d: date) -> date:
    return add_months(date(d.year, d.month, 1), 1) - ONE_DAY


def vat_deadline(period_end: date) -> date:
    """One calendar month and seven days after a month-end VAT period: the 7th of the second month after it."""
    return add_months(date(period_end.year, period_end.month, 7), 2)


def vat_dd_date(period_end: date) -> date:
    """HMRC collects a VAT Direct Debit three working days after the payment deadline."""
    return add_working_days(vat_deadline(period_end), 3)


def paye_due(pay_date: date) -> date:
    """PAYE paid electronically is due by the 22nd after the tax month (6th to 5th) the pay date falls in; when the
    22nd isn't a working day it has to arrive the working day before."""
    base = date(pay_date.year, pay_date.month, 22)
    due = add_months(base, 1) if pay_date.day >= 6 else base
    return previous_working_day(due)


def ct_due(period_end: date) -> date:
    """Corporation tax is due nine months and one day after the period ends (TMA 1970 s59D): nine months on from
    the day after it, so a 30 April year end is due on 1 February. Paid by the working day before when that day
    isn't one."""
    return previous_working_day(add_months(period_end + ONE_DAY, 9))
