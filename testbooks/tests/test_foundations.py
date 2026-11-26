import ast
import pathlib
import random
from datetime import date
from decimal import Decimal as D

from testbooks.dates import (ct_due, next_working_day, paye_due, previous_working_day, vat_dd_date,
                             vat_deadline)
from testbooks.ids import ni_number, vat_number, vat_number_valid
from testbooks.money import pennies, vat_in, vat_on, whole_pounds

BANNED = {"ledgersync", "server", "eval", "eval_cases", "eval_scoring", "openai", "langchain", "httpx", "requests"}


def test_nothing_imports_the_app_or_the_network():
    root = pathlib.Path(__file__).resolve().parents[1]
    for path in sorted(root.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                assert name.split(".")[0] not in BANNED, f"{path} imports {name}"


def test_money():
    assert pennies("2.345") == D("2.35") and pennies(D("2.344")) == D("2.34")
    assert vat_on(D("1082.50"), D("0.20")) == D("216.50")
    assert vat_in(D("320.00"), D("0.20")) == D("53.33")
    assert whole_pounds(D("1234.99")) == 1234 and whole_pounds(D("-1234.99")) == -1234


def test_identifiers():
    rng = random.Random(1)
    assert all(len(n) == 9 and n.isdigit() and vat_number_valid(n) for n in (vat_number(rng) for _ in range(50)))
    assert vat_number_valid("284619331")
    assert not vat_number_valid("123456789")
    n = ni_number(rng)
    assert n[:2] == "QQ" and n[2:8].isdigit() and n[8] in "ABCD"


def test_working_days_and_due_dates():
    assert next_working_day(date(2024, 3, 29)) == date(2024, 4, 2)        # Good Friday, then Easter Monday
    assert previous_working_day(date(2024, 1, 1)) == date(2023, 12, 29)
    assert vat_deadline(date(2023, 5, 31)) == date(2023, 7, 7)
    assert vat_deadline(date(2024, 2, 29)) == date(2024, 4, 7)
    assert vat_dd_date(date(2023, 2, 28)) == date(2023, 4, 13)            # deadline is Good Friday 2023
    assert vat_dd_date(date(2023, 5, 31)) == date(2023, 7, 12)
    assert vat_dd_date(date(2024, 2, 29)) == date(2024, 4, 10)
    assert paye_due(date(2023, 4, 28)) == date(2023, 5, 22)
    assert paye_due(date(2023, 6, 28)) == date(2023, 7, 21)               # 22 Jul 2023 is a Saturday
    assert ct_due(date(2023, 3, 31)) == date(2023, 12, 29)                # 1 Jan 2024 is a bank holiday
