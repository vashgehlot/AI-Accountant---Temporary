"""Small helpers shared by tests: a row with sensible defaults, the figures a test asks about, and clients with
years to close."""
import datetime as dt
from decimal import Decimal
from typing import Optional

import pytest

from ledgersync import ledger
from ledgersync.checks import normalise
from ledgersync.matching import match
from ledgersync.models import BusinessSettings, RowPatch, Transaction

SETTINGS = BusinessSettings(business_name="Acme Ltd", vat_registered=True, business_type="limited_company")


def row(**overrides) -> Transaction:
    """A receipt for £0.00 on 7600 dated 1 Jan 2026, paid out in GBP, with whatever is overridden."""
    fields = dict(date=dt.date(2026, 1, 1), description="x", direction="out", gross=Decimal("0.00"), vat=None,
                  account_code="7600", currency="GBP", document_type="receipt")
    return Transaction(**{**fields, **overrides})


def net(tb, code: str) -> Decimal:
    """Debit minus credit of the trial balance's line for the account; 0 if it has none."""
    return sum((line.debit - line.credit for line in tb.lines if line.code == code), Decimal(0))


def match_one(document: Transaction, line: Transaction) -> Transaction:
    """The bank line after matching it against the document."""
    return match([normalise(document, SETTINGS), normalise(line, SETTINGS)], SETTINGS)[1]


def only_issue(tx: Transaction, code: str):
    """The row's one issue with this code."""
    found = [i for i in tx.issues if i.code == code]
    assert len(found) == 1, f"expected one {code} issue, found {[i.code for i in tx.issues]}"
    return found[0]


def normalise_and_match(rows: list[Transaction], settings: BusinessSettings = SETTINGS) -> list[Transaction]:
    """The rows as the ledger shows them: each one normalised, then matched together."""
    return match([normalise(tx, settings) for tx in rows], settings)


def payroll_row(**overrides) -> dict:
    """One row of a payroll report as the model answers it: net pay out on 7000, dated the pay date."""
    fields = dict(description="Net pay", date="2026-03-28", amount=3000.0, direction="out", account="7000",
                  currency="GBP", document_type="payroll", owed_to="net_pay")
    return {**fields, **overrides}


def add_rows(store, client_id: int, *rows: Transaction, year_start: Optional[dt.date] = None,
             bank_account: Optional[str] = None) -> int:
    """Saves the rows to the client as one upload, added to the year starting year_start; its id."""
    return store.add_upload(client_id, "rows.csv", "table", list(rows), year_start=year_start,
                            bank_account=bank_account)


# ─── Clients with a year to close (Task 8) ─────────────────────────────────────

@pytest.fixture
def acme_with_year_one(store, acme) -> int:
    """acme with a £60.00 stationery receipt paid from the bank on 1 Jun 2025, in its first year."""
    add_rows(store, acme, row(date=dt.date(2025, 6, 1), gross=Decimal("60.00"), account_code="7504"))
    return acme


@pytest.fixture
def acme_two_years(store, acme_with_year_one) -> int:
    """acme_with_year_one and, in its second year, a £25.00 telephone receipt on 1 May 2026."""
    add_rows(store, acme_with_year_one, row(date=dt.date(2026, 5, 1), gross=Decimal("25.00"), account_code="7502"))
    return acme_with_year_one


@pytest.fixture
def acme_with_unpaid_bill_in_year_one(store, acme) -> int:
    """acme with a £300.00 bill from Smith Solicitors dated 1 Mar 2026, unpaid at the first year's end."""
    add_rows(store, acme, row(date=dt.date(2026, 3, 1), gross=Decimal("300.00"), document_type="invoice",
                              counterparty="Smith Solicitors", document_ref="bill"))
    return acme


def the_bills_payment_dated(day: dt.date) -> Transaction:
    """The bank line paying acme_with_unpaid_bill_in_year_one's bill."""
    return row(date=day, gross=Decimal("300.00"), document_type="statement", counterparty="SMITH SOLICITORS")


@pytest.fixture
def acme_with_statement_missing_a_line(store, acme) -> int:
    """acme with a bank statement for September 2025 that closes at £100.00. Its rows are a £100.00 sale (with £16.67 VAT) on 2 Sep
    and a £25.00 stationery payment on 30 Sep, so the books hold £75.00: a £25.00 deposit was missed."""
    line = dict(document_type="statement")
    add_rows(store, acme,
             row(**line, date=dt.date(2025, 9, 2), direction="in", gross=Decimal("100.00"), vat=Decimal("16.67"),
                 account_code="4000", counterparty="Bright Cafe", opening_balance=Decimal("0.00"), balance=Decimal("100.00")),
             row(**line, date=dt.date(2025, 9, 30), gross=Decimal("25.00"), account_code="7504",
                 counterparty="Paper Shop", balance=Decimal("75.00"), closing_balance=Decimal("100.00")))
    return acme


@pytest.fixture
def acme_with_a_non_gbp_row(store, acme) -> int:
    """acme with a $50.00 receipt in its first year, which has to be converted to pounds before it can be booked."""
    add_rows(store, acme, row(date=dt.date(2025, 6, 1), gross=Decimal("50.00"), currency="USD"))
    return acme


def bill_row(ledger_):
    """The ledger's row of acme_with_unpaid_bill_in_year_one's bill."""
    return next(r for r in ledger_.transactions if r.document_ref == "bill")


def first_row_id(store, client_id: int) -> int:
    return store.rows(client_id)[0].id


def change_stationery_receipt_to(store, client_id: int, gross: Decimal) -> None:
    """Edits the amount of the client's stationery receipt (on 7504)."""
    found = next(r for r in store.rows(client_id) if r.tx.account_code == "7504")
    ledger.change_row(store, client_id, found.id, RowPatch(gross=gross))
