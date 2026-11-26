import csv
from datetime import date
from decimal import Decimal as D

import pytest

from testbooks.checks import run_checks
from testbooks.tests.test_build import built

YE = date(2024, 3, 31)


def results(client):
    return {r.name: r.ok for r in run_checks(client, YE)}


def edit_csv(path, row, column, change, newline="\n"):
    with open(path, newline="") as f:
        rows = list(csv.reader(f))
    rows[row][column] = change(rows[row][column])
    with open(path, "w", newline="") as f:
        csv.writer(f, lineterminator=newline).writerows(rows)


def drop_row(path, row, newline="\n"):
    with open(path, newline="") as f:
        rows = list(csv.reader(f))
    del rows[row]
    with open(path, "w", newline="") as f:
        csv.writer(f, lineterminator=newline).writerows(rows)


def column(path, name):
    with open(path, newline="") as f:
        return next(csv.reader(f)).index(name)


@pytest.fixture(scope="module")
def fresh(tmp_path_factory):
    return built(tmp_path_factory.mktemp("checks"), "a")


def test_all_pass(fresh):
    r = results(fresh)
    assert all(r.values()), r
    assert (fresh / "key" / "2024-03-31" / "checks.txt").read_text().startswith("Key unreviewed")


def test_tb_and_bank_faults_are_caught(tmp_path):
    client = built(tmp_path, "a")
    key = client / "key" / "2024-03-31"
    edit_csv(key / "trial-balance.csv", 1, 7, lambda v: str(D(v) + 1))
    assert results(client)["tb_balances"] is False
    statement = sorted((client / "inbox").rglob("*_hsbc-statement_*.csv"))[0]
    edit_csv(statement, 1, 3, lambda v: str(D(v) + 1), newline="\r\n")
    assert results(client)["bank_recs_tie"] is False


def _key(client):
    return client / "key" / "2024-03-31"


def doctor_vat(client):
    path = _key(client) / "vat-returns.csv"
    edit_csv(path, 1, column(path, "box5"), lambda v: str(D(v) + 1))


def doctor_debtors(client):
    path = _key(client) / "debtors.csv"
    with open(path) as f:
        n = len(f.readlines())
    drop_row(path, n - 1)


def doctor_pdf(client):
    with open(_key(client) / "documents.csv", newline="") as f:
        pdfs = [r["file"] for r in csv.DictReader(f) if r["file"].endswith(".pdf") and r["gross"]]
    (client / pdfs[0]).write_bytes((client / pdfs[-1]).read_bytes())


def doctor_statement(client):
    statement = sorted((client / "inbox").rglob("*_hsbc-statement_*.csv"))[0]
    drop_row(statement, 1, newline="\r\n")


def doctor_payroll(client):
    path = _key(client) / "payroll.csv"
    edit_csv(path, 1, column(path, "tax"), lambda v: str(D(v) + 1))


def doctor_opening(client):
    path = _key(client) / "opening-balances.csv"
    edit_csv(path, 1, column(path, "debit"), lambda v: str(D(v or "0") + 1))


def doctor_cases(client):
    path = _key(client) / "entries.csv"
    edit_csv(path, 1, column(path, "cases"), lambda v: "EC-9999")


@pytest.mark.parametrize("check,doctor", [
    ("vat_control_ties", doctor_vat), ("debtors_creditors_tie", doctor_debtors), ("printed_figures", doctor_pdf),
    ("statements_parse", doctor_statement), ("payroll_controls_clear", doctor_payroll),
    ("opening_matches_prior_tb", doctor_opening), ("catalogue_refs", doctor_cases)])
def test_each_check_catches_its_fault(tmp_path, check, doctor):
    client = built(tmp_path, "a")
    doctor(client)
    assert results(client)[check] is False
