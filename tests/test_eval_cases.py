"""The client-level test set (eval/jobs/) against the booking rules, with no real model. Each document is "read" by
a fake model that answers what a good reading should (below, written from the documents), and the case runs through
the real API, books and posting: the year's trial balance must be the one worked out by hand in the case's
expected_trial_balance.json. This checks the expected figures and the runner; how well the real model reads the
documents is what eval/run_job_eval.py measures."""
import json
import time
from pathlib import Path

import pytest
from fakes import FakeModel
from fastapi.testclient import TestClient

import run_job_eval
from ledgersync.config import Settings
from server import create_app

pytestmark = pytest.mark.mongo

JOBS = Path(__file__).parent.parent / "eval" / "jobs"


# ─── What a good reading of each document gives ────────────────────────────────

def reply(*rows, opening=None, closing=None) -> str:
    return json.dumps({"transactions": list(rows), "opening_balance": opening, "closing_balance": closing})


def line(day, who, amount, account, balance=None) -> dict:
    """A bank statement line: money in when the amount is positive."""
    return {"description": who, "counterparty": who, "date": day, "amount": abs(amount),
            "direction": "in" if amount > 0 else "out", "account": account, "vat": None, "currency": "GBP",
            "document_type": "statement", "balance": balance}


def document(kind, day, who, amount, account, *, total, vat=None, net=None, number=None, direction="out",
             description=None, vat_number=None) -> dict:
    """A receipt, invoice or claim line; total is the document's printed total."""
    return {"description": description or who, "counterparty": who, "date": day, "amount": amount,
            "direction": direction, "account": account, "vat": vat, "currency": "GBP", "document_type": kind,
            "document_total": total, "document_vat": vat, "document_net": net, "document_number": number,
            "supplier_vat_number": vat_number}


def payroll(account, amount, owed_to, description) -> dict:
    return {"description": description, "date": "2026-10-28", "amount": amount, "direction": "out",
            "account": account, "vat": None, "currency": "GBP", "document_type": "payroll", "owed_to": owed_to}


SOLE_TRADER_BANK = [
    ("2026-10-01", "ONBUY.COM - A4 COPIER PAPER", -32.40, "7504", 8967.60),
    ("2026-10-01", "BRIGHTWATER DESIGN LTD INV 3107", 3150.00, "4000", 12117.60),
    ("2026-10-02", "TRAVIS PERKINS", -86.30, "7800", 12031.30),
    ("2026-10-03", "GREGGS", -5.60, "7406", 12025.70),
    ("2026-10-05", "GUMTREE - SECOND-HAND OFFICE DESK", -120.00, "0040", 11905.70),
    ("2026-10-06", "PLUSNET", -30.00, "7502", 11875.70),
    ("2026-10-07", "ETSY", -24.50, "3260", 11851.20),
    ("2026-10-08", "ARGOS - LAPTOP FOR NEW STARTER", -549.00, "0030", 11302.20),
    ("2026-10-09", "IBIS LONDON", -94.00, "7402", 11208.20),
    ("2026-10-12", "LINKEDIN ADS", -200.00, "8201", 11008.20),
    ("2026-10-13", "MORRISONS", -21.75, "8205", 10986.45),
    ("2026-10-14", "MARKS & SPENCER - SANDWICHES FOR CLIENT MEETING", -38.20, "7403", 10948.25),
    ("2026-10-15", "CANVA", -10.99, "8201", 10937.26),
    ("2026-10-16", "NCP CAR PARKS", -18.00, "7400", 10919.26),
    ("2026-10-19", "SELFRIDGES", -210.00, "3260", 10709.26),
    ("2026-10-20", "DPD UK", -12.49, "7501", 10696.77),
    ("2026-10-21", "COSTCO - MILK AND COFFEE FOR THE OFFICE", -46.80, "8205", 10649.97),
    ("2026-10-22", "BP CONNECT", -61.05, "7300", 10588.92),
    ("2026-10-26", "CAMDEN COUNCIL PENALTY CHARGE", -65.00, "3260", 10523.92),
    ("2026-10-28", "OFFICE DEPOT", -27.99, "7504", 10495.93),
]

READINGS = {
    "ltd-bank-and-receipts": {
        "barclays-september.csv": reply(
            line("2026-09-02", "VODAFONE LTD", -45.99, "7502"), line("2026-09-10", "STAPLES UK", -32.40, "7504"),
            line("2026-09-13", "BRIGHTWELL LTD", 950.00, "4000"), line("2026-09-18", "ROYAL MAIL", -15.60, "7501"),
            line("2026-09-22", "PREMIER INN", -89.00, "7402"), line("2026-09-27", "HMRC VAT", -1210.33, "2202")),
        "cafe-receipt.png": reply(document("receipt", "2026-09-12", "The Daily Grind Cafe", 7.50, "7406",
                                           total=7.50, vat=1.25, net=6.25,
                                           vat_number="318447192")),
        "tesco-receipt.txt": reply(document("receipt", "2026-09-03", "Tesco Express", 12.50, "7406", total=12.50)),
    },
    "ltd-matched-payments": {
        "business-account-october.csv": reply(
            line("2026-10-09", "Harbour Street Stationers", -24.00, "7504", 4976.00),
            line("2026-10-16", "Pemberton & Hale", -216.00, "7601", 4760.00),
            line("2026-10-31", "Bank charges", -6.50, "7901", 4753.50), opening=5000.00, closing=4753.50),
        "harbour-street-receipt.txt": reply(document("receipt", "2026-10-08", "Harbour Street Stationers", 24.00,
                                                     "7504", total=24.00, vat=4.00, net=20.00,
                                                     vat_number="412773058")),
        "pemberton-hale-invoice.txt": reply(document("invoice", "2026-10-05", "Pemberton & Hale", 216.00, "7601",
                                                     total=216.00, vat=36.00, net=180.00, number="PH-2026-114")),
    },
    "ltd-unpaid-invoices": {
        "clearway-invoice.pdf": reply(document("invoice", "2026-09-08", "Clearway Office Supplies Ltd", 300.00,
                                               "7504", total=300.00, vat=50.00, net=250.00, number="CW-20931")),
        "starling-september.csv": reply(
            line("2026-09-03", "WeWork", -295.00, "7100", 2905.00),
            line("2026-09-07", "Hartley & Co", -360.00, "7601", 2545.00),
            line("2026-09-15", "Brightwell Ltd", 2100.00, "4000", 4645.00),
            line("2026-09-23", "Avanti West Coast", -64.30, "7400", 4580.70), opening=3200.00, closing=4580.70),
    },
    "sole-trader-expense-claim": {
        "bank-october.csv": reply(*(line(*row[:4], balance=row[4]) for row in SOLE_TRADER_BANK),
                                  opening=9000.00, closing=10495.93),
        "expense-note.txt": reply(
            document("expense_claim", "2026-09-12", None, 18.00, "7406", total=50.00, description="Breakfast"),
            document("expense_claim", "2026-09-12", None, 32.00, "7400", total=50.00, description="Taxi to client")),
    },
    "ltd-late-paid-invoice": {
        "calder-rowe-invoice.txt": reply(document("invoice", "2026-08-04", "Calder & Rowe Print Ltd", 480.00, "7500",
                                                  total=480.00, vat=80.00, net=400.00, number="CR-5521")),
        "current-account-september.csv": reply(
            line("2026-09-03", "Northern Electric", -86.40, "7200", 5913.60),
            line("2026-09-22", "Calder & Rowe Print Ltd", -480.00, "7500", 5433.60),
            line("2026-09-30", "Bank charges", -8.00, "7901", 5425.60), opening=6000.00, closing=5425.60),
    },
    "ltd-payroll": {
        "current-account-oct-nov.csv": reply(
            line("2026-10-28", "Elif Demir", -1750.00, "2220", 10250.00),
            line("2026-10-28", "Owen Price", -1500.00, "2220", 8750.00),
            line("2026-10-30", "Bank charges", -6.50, "7901", 8743.50),
            line("2026-11-05", "Aviva Workplace Pension", -280.00, "2230", 8463.50),
            line("2026-11-22", "HMRC PAYE", -1025.00, "2210", 7438.50), opening=12000.00, closing=7438.50),
        "payroll-report-october.txt": reply(
            payroll("7000", 3250.00, "net_pay", "Net pay"),
            payroll("7000", 630.00, "paye_ni", "Income tax and employee National Insurance"),
            payroll("7000", 120.00, "pension", "Employee pension contribution"),
            payroll("7006", 395.00, "paye_ni", "Employer National Insurance"),
            payroll("7007", 160.00, "pension", "Employer pension contribution")),
    },
    "ltd-two-accounts-transfer": {
        "current-account-october.csv": reply(
            line("2026-10-06", "Pennine Telecom", -54.00, "7502", 7946.00),
            line("2026-10-12", "Greywell Surveying Savings", -5000.00, "1210", 2946.00),
            line("2026-10-20", "Bank charges", -7.50, "7901", 2938.50), opening=8000.00, closing=2938.50),
        "savings-account-october.csv": reply(
            line("2026-10-12", "Greywell Surveying Current", 5000.00, "1200", 6000.00),
            line("2026-10-31", "Interest", 4.20, "4900", 6004.20), opening=1000.00, closing=6004.20),
    },
}


@pytest.fixture
def api(mongo_store):
    clients = []

    def _make(model):
        client = TestClient(create_app(Settings(warmup=False), model_client=model, store=mongo_store))
        client.__enter__()
        clients.append(client)
        return client

    yield _make
    for client in clients:
        client.__exit__(None, None, None)


def test_every_case_has_a_reading():
    assert sorted(READINGS) == sorted(p.name for p in run_job_eval.load_cases(JOBS))
    for name, documents in READINGS.items():
        assert sorted(documents) == [p.name for p in run_job_eval._documents(JOBS / name)], name


@pytest.mark.parametrize("name", sorted(READINGS))
def test_a_case_read_as_intended_gives_the_trial_balance_worked_out_by_hand(api, name):
    # The runner reads the documents by name, one after another, so the answers go in that order.
    model = FakeModel([READINGS[name][doc] for doc in sorted(READINGS[name])])
    outcome = run_job_eval.run_case(api(model), JOBS / name, sleep=lambda s: time.sleep(0.01), analysis_timeout=30)
    assert (outcome["error"], outcome["error_detail"]) == (None, None)
    assert outcome["differences"] == [] and outcome["is_balanced"] is True
    assert outcome["verdict"] == "match"
