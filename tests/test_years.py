from datetime import date

from ledgersync.years import label, year_bounds, year_index


def test_years_run_from_the_first_year_end():
    assert year_bounds(date(2026,3,31), 0) == (date(2025,4,1), date(2026,3,31))
    assert year_bounds(date(2026,3,31), 1) == (date(2026,4,1), date(2027,3,31))
    assert year_bounds(date(2024,2,29), 1) == (date(2024,3,1), date(2025,2,28))
    assert year_index(date(2026,3,31), date(2025,3,31)) is None


def test_a_day_falls_in_the_year_that_holds_it():
    end = date(2026, 3, 31)
    assert [year_index(end, day) for day in (date(2025, 4, 1), date(2026, 3, 31), date(2026, 4, 1),
                                             date(2028, 12, 25))] == [0, 0, 1, 3]
    assert year_index(date(2024, 2, 29), date(2025, 2, 28)) == 1
    assert year_index(date(2024, 2, 29), date(2028, 2, 29)) == 4   # a leap year ends on its own 29 Feb


def test_a_year_is_named_by_its_end():
    assert label(date(2026, 3, 31)) == "Year to 31 Mar 2026"
    assert label(date(2025, 2, 28)) == "Year to 28 Feb 2025"
