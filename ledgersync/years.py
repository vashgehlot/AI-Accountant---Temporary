"""A client's accounting years: each ends on the day and month of its first year end, and starts the day after the
year before it ends. Year 0 is the first. Pure date arithmetic."""
from __future__ import annotations

import calendar
import datetime as dt
from typing import Optional

DAY = dt.timedelta(days=1)


def _end_in(year: int, first_year_end: dt.date) -> dt.date:
    """The year end that falls in a calendar year: 29 Feb is 28 Feb in a year without one."""
    day = first_year_end.day
    if first_year_end.month == 2 and day == 29 and not calendar.isleap(year):
        day = 28
    return dt.date(year, first_year_end.month, day)


def year_bounds(first_year_end: dt.date, n: int) -> tuple[dt.date, dt.date]:
    """The first and last day of year n."""
    end = _end_in(first_year_end.year + n, first_year_end)
    return _end_in(first_year_end.year + n - 1, first_year_end) + DAY, end


def year_index(first_year_end: dt.date, day: dt.date) -> Optional[int]:
    """The year that holds the day; None before the first year starts."""
    if day < year_bounds(first_year_end, 0)[0]:
        return None
    n = max(day.year - first_year_end.year, 0)
    while year_bounds(first_year_end, n)[0] > day:
        n -= 1
    while year_bounds(first_year_end, n)[1] < day:
        n += 1
    return n


def label(end: dt.date) -> str:
    """Year to 31 Mar 2026."""
    return f"Year to {end.day} {end:%b %Y}"
