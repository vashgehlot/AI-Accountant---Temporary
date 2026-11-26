from datetime import date
from decimal import Decimal as D

from testbooks.books.chart import CHART, HEADINGS
from testbooks.rules.rates import RATE_SOURCES, rate


def test_rates_change_on_their_own_dates():
    assert rate("ni_employee_main", date(2024, 1, 5)) == D("0.12")
    assert rate("ni_employee_main", date(2024, 1, 6)) == D("0.10")
    assert rate("ni_employee_main", date(2024, 4, 6)) == D("0.08")
    assert rate("ni_employer", date(2025, 4, 5)) == D("0.138")
    assert rate("ni_employer", date(2025, 4, 6)) == D("0.15")
    assert rate("ni_st_month", date(2023, 4, 6)) == D("758") and rate("ni_st_month", date(2025, 4, 6)) == D("417")
    assert rate("employment_allowance", date(2025, 4, 6)) == D("10500")
    assert rate("vat_threshold", date(2024, 3, 31)) == D("85000")
    assert rate("vat_threshold", date(2024, 4, 1)) == D("90000")
    assert rate("mileage_car_first", date(2026, 4, 5)) == D("0.45")
    assert rate("mileage_car_first", date(2026, 4, 6)) == D("0.55")
    assert all(src.startswith("https://") for src in RATE_SOURCES.values())


def test_chart():
    for code in ("1100", "1200", "1240", "1290", "2100", "2200", "2201", "2202", "2210", "2220", "2230",
                 "2250", "2320", "3200", "3260", "4000", "7000", "7403", "7410", "8000", "9100", "9998"):
        assert code in CHART
    assert all(a.heading in HEADINGS for a in CHART.values())
    assert CHART["1240"].kind == "liability" and CHART["7403"].tax == "disallowable"
