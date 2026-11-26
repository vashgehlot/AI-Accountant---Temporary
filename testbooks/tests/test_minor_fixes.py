"""The six minor findings the final review deferred, each pinned by a test."""
import csv
import filecmp
from datetime import date
from decimal import Decimal as D

import pytest
from openpyxl import load_workbook

from testbooks.build import build
from testbooks.checks import run_checks
from testbooks.clients import agency
from testbooks.dates import add_months, ct_due
from testbooks.engine.simulate import simulate

W = simulate(agency.define(), until=date(2024, 6, 30), seed=7)
ELECTRONIC = ("BP", "DD", "SO", "TRF")


@pytest.fixture(scope="module")
def two_builds(tmp_path_factory):
    a, b = tmp_path_factory.mktemp("a"), tmp_path_factory.mktemp("b")
    for out in (a, b):
        build(out, seed=7, clients=["agency"], packs=["EC-0301"], until=date(2024, 6, 30))
    return a, b


def test_ct_is_due_nine_months_and_a_day_after_any_year_end():
    assert ct_due(date(2023, 4, 30)) == date(2024, 2, 1)       # the day after is 1 May; nine months on is 1 Feb
    assert ct_due(date(2023, 3, 31)) == date(2023, 12, 29)     # 1 Jan 2024 is a bank holiday
    assert ct_due(date(2024, 12, 31)) == date(2025, 10, 1)
    ct = next(d for d in W.deals if d.kind == "ct_payment")
    assert ct.payments[0].date == ct_due(date(2023, 3, 31))


def test_bank_charges_count_every_electronic_payment():
    charges = [d for d in W.deals if "EC-0437" in d.cases and d.date >= date(2023, 6, 1)]
    assert charges
    for charge in charges:
        before = add_months(date(charge.date.year, charge.date.month, 1), -1)
        count = sum(1 for d in W.deals for p in d.payments
                    if p.account == "hsbc" and p.amount < 0 and p.type_code in ELECTRONIC
                    and (p.date.year, p.date.month) == (before.year, before.month))
        assert -charge.payments[0].amount == D("8.50") + D("0.35") * count, charge.date


def test_excel_files_are_byte_identical_between_builds(two_builds):
    a, b = two_builds
    workbooks = sorted(a.rglob("*.xlsx"))
    assert workbooks
    for path in workbooks:
        assert filecmp.cmp(path, b / path.relative_to(a), shallow=False), path


def test_balance_sheet_shows_the_format_subtotals(two_builds):
    a, _ = two_builds
    ws = load_workbook(a / "clients" / "agency" / "key" / "2024-03-31" / "accounts.xlsx")["Balance sheet"]
    rows = {r[0]: r[1] for r in ws.iter_rows(min_row=2, values_only=True)}
    assert rows["Net current assets"] == pytest.approx(
        rows["Current assets"] + rows["Prepayments and accrued income"]
        - rows["Creditors: amounts falling due within one year"])
    assert rows["Total assets less current liabilities"] == pytest.approx(
        rows["Called up share capital not paid"] + rows["Fixed assets"] + rows["Net current assets"])
    assert rows["Net assets"] == pytest.approx(
        rows["Total assets less current liabilities"] - rows["Creditors: amounts falling due after more than one year"]
        - rows["Provisions for liabilities"] - rows["Accruals and deferred income"])


def test_each_client_chart_names_its_own_directors(two_builds):
    a, _ = two_builds

    def chart(folder):
        with open(folder / "chart.csv", newline="") as f:
            return {r["code"]: r["name"] for r in csv.DictReader(f)}

    assert chart(a / "packs" / "EC-0301-laptop-bought")["2250"] == "Director's loan - Sam Carter"
    assert chart(a / "clients" / "agency")["2251"] == "Director's loan - Omar Kestrel"


def test_statement_balances_chain_and_a_broken_one_is_caught(tmp_path):
    folder = build(tmp_path, seed=7, clients=[], packs=["EC-0430"])[0]
    assert {r.name: r.ok for r in run_checks(folder, date(2024, 6, 30))}["statement_balances_chain"]
    statement = next((folder / "inbox").rglob("*_hsbc-statement_*.csv"))
    with open(statement, newline="") as f:
        rows = list(csv.reader(f))
    rows[1][4] = str(D(rows[1][4]) + 1)        # the newest line's balance no longer follows from the line before
    with open(statement, "w", newline="") as f:
        csv.writer(f, lineterminator="\r\n").writerows(rows)
    assert {r.name: r.ok for r in run_checks(folder, date(2024, 6, 30))}["statement_balances_chain"] is False
