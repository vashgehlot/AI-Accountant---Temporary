"""A client's work as an Excel workbook (design of 2026-10-06): its trial balance and its transactions, from
the same ledger the pages show. Amounts are numbers in pounds and dates are dates, so the sheets add up."""
from __future__ import annotations

import datetime as dt
import io
import re
from decimal import Decimal
from typing import Optional, Union

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Font

from .accounts import BY_CODE, Heading, TaxTreatment
from .models import Direction, Ledger, Transaction, TrialBalance
from .money import ZERO

MONEY = '"£"#,##0.00'
DATE = "dd/mm/yyyy"
COLUMNS = ("Date", "Description", "Counterparty", "Document type", "In/Out", "Amount", "VAT", "Net", "Account",
           "Account name", "Other side", "Still owed", "Issues", "Upload", "Edited", "Left out")
_TYPE_NAMES = {"receipt": "Receipt", "invoice": "Invoice", "expense_claim": "Expense claim",
               "statement": "Bank statement", "write_off": "Bad debt written off", "quote": "Quote", "pro_forma": "Pro forma",
               "purchase_order": "Purchase order", "remittance_advice": "Remittance advice",
               "supplier_statement": "Supplier statement", "other": "Other"}
# How the trial balance sheet marks an account's tax treatment: an allowable one is left blank.
_TAX_WORDS = {TaxTreatment.DISALLOWABLE: "Disallowable", TaxTreatment.CHECK: "Check: part may be disallowable",
              TaxTreatment.NON_TRADING: "Not trading income"}
_UNSAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_SPACES = re.compile(r"\s+")


def file_name(client_name: str, day: dt.date) -> str:
    """'Business Cube Ltd 2026-10-06.xlsx', without characters that file names can't hold."""
    name = _SPACES.sub(" ", _UNSAFE.sub(" ", client_name)).strip(" .") or "Client"
    return f"{name} {day.isoformat()}.xlsx"


def workbook(ledger: Ledger, balance: Union[TrialBalance, list[str]], day: dt.date) -> bytes:
    """The workbook: a "Trial balance" sheet (or, while rows need fixing, what stops it) and a "Transactions"
    sheet with one row per saved row, in the table's order."""
    book = Workbook()
    _trial_balance(book.active, ledger, balance, day)
    _transactions(book.create_sheet("Transactions"), ledger)
    if not isinstance(balance, list):   # the statements are worked from the trial balance: none while it is stopped
        _statements(book, ledger, balance)
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def _append(sheet, values) -> None:
    """Adds a row. Text read from documents stays text: characters a worksheet can't hold are dropped, and
    text starting with "=" is not made a formula."""
    sheet.append([ILLEGAL_CHARACTERS_RE.sub("", v) if isinstance(v, str) else v for v in values])
    for cell in sheet[sheet.max_row]:
        if isinstance(cell.value, str) and cell.value.startswith("="):
            cell.data_type = "s"


def _title(sheet, text: str) -> None:
    _append(sheet, [text])
    sheet["A1"].font = Font(bold=True)


def _widths(sheet, widths) -> None:
    for n, width in enumerate(widths):
        sheet.column_dimensions[chr(ord("A") + n)].width = width


def _trial_balance(sheet, ledger: Ledger, balance, day: dt.date) -> None:
    sheet.title = "Trial balance"
    _title(sheet, f"{ledger.client.name} — trial balance — {ledger.year.label}, as at {day.day} {day:%b %Y}")
    if isinstance(balance, list):
        _append(sheet, ["The trial balance can't be produced yet:"])
        for problem in balance:
            _append(sheet, [problem])
        return
    _append(sheet, ["Code", "Account", "Debit", "Credit", "Heading", "Tax", "SA103F box"])
    for line in balance.lines:
        account = BY_CODE[line.code]
        _append(sheet, [line.code, line.name, line.debit, line.credit, line.heading,
                        _TAX_WORDS.get(account.tax), account.sa103])
    _append(sheet, [None, "Totals", balance.total_debits, balance.total_credits])
    for row in sheet.iter_rows(min_row=3, min_col=3, max_col=4):
        for cell in row:
            cell.number_format = MONEY
    sheet.freeze_panes = "A3"
    _widths(sheet, (8, 34, 14, 14, 44, 14, 11))


def _statements(book, ledger: Ledger, balance: TrialBalance) -> None:
    """A "Profit and loss" sheet and a "Balance sheet" sheet, from the trial balance, laid out as the Trial balance
    page lays them out: by the Companies Act headings each account belongs to (accounts.Heading)."""
    pl_lines, bs_lines = statement_lines(balance)
    for title, lines in (("profit and loss", pl_lines), ("balance sheet", bs_lines)):
        sheet = book.create_sheet(title.capitalize())
        _title(sheet, f"{ledger.client.name} — {title} — {ledger.year.label}")
        for code, label, amount, total in lines:
            _append(sheet, [code, label, amount])
            if total:
                sheet.cell(row=sheet.max_row, column=2).font = Font(bold=True)
        for row in sheet.iter_rows(min_row=2, min_col=3, max_col=3):
            row[0].number_format = MONEY
        _widths(sheet, (8, 52, 16))


# A statement line: an account's code (None for a total), its label, its amount, and whether it is a total.
StatementLine = tuple[Optional[str], str, Decimal, bool]


def statement_lines(balance: TrialBalance) -> tuple[list[StatementLine], list[StatementLine]]:
    """The profit and loss account and the balance sheet. Income is shown as a positive amount and so are costs;
    assets are positive and so are what is owed. Each heading lists its accounts and its total; the profit lines
    (gross, operating, before tax) show only where there is something between them. Net assets equal capital and
    reserves with the year's profit, an LLP's debts due to its members among them."""
    used = [line for line in balance.lines if line.debit != line.credit]
    pl: list[StatementLine] = []
    bs: list[StatementLine] = []

    def of(heading: Heading) -> list:
        return [line for line in used if line.heading == heading.value]

    def block(out: list, heading: Heading, sign: int) -> Decimal:
        lines = of(heading)
        total = sum((sign * (line.debit - line.credit) for line in lines), Decimal("0.00"))
        for line in lines:
            out.append((line.code, line.name, sign * (line.debit - line.credit), False))
        if lines:
            out.append((None, heading.value, total, True))
        return total

    def total(out: list, label: str, amount: Decimal) -> None:
        out.append((None, label, amount, True))

    turnover = block(pl, Heading.TURNOVER, -1)
    cost = block(pl, Heading.COST_OF_SALES, 1)
    if of(Heading.COST_OF_SALES):
        total(pl, "Gross profit", turnover - cost)
    operating = turnover - cost - block(pl, Heading.ADMINISTRATIVE, 1) + block(pl, Heading.OTHER_INCOME, -1)
    below = (Heading.INTEREST_RECEIVABLE, Heading.INTEREST_PAYABLE, Heading.TAX)
    if any(of(h) for h in below):
        total(pl, "Operating profit" if operating >= 0 else "Operating loss", operating)
    before_tax = operating + block(pl, Heading.INTEREST_RECEIVABLE, -1) - block(pl, Heading.INTEREST_PAYABLE, 1)
    if of(Heading.TAX):
        total(pl, "Profit before tax" if before_tax >= 0 else "Loss before tax", before_tax)
    profit = before_tax - block(pl, Heading.TAX, 1)
    total(pl, "Net loss" if profit < 0 else "Net profit", profit)

    fixed = sum((block(bs, h, 1) for h in (Heading.INTANGIBLE, Heading.TANGIBLE, Heading.INVESTMENTS)), Decimal("0.00"))
    if fixed or any(of(h) for h in (Heading.INTANGIBLE, Heading.TANGIBLE, Heading.INVESTMENTS)):
        total(bs, "Fixed assets", fixed)
    current = sum((block(bs, h, 1) for h in (Heading.STOCKS, Heading.DEBTORS, Heading.CASH)), Decimal("0.00"))
    total(bs, "Current assets", current)
    short = block(bs, Heading.CREDITORS_SHORT, -1)
    total(bs, "Net current assets" if current >= short else "Net current liabilities", current - short)
    long = block(bs, Heading.CREDITORS_LONG, -1)
    net_assets = fixed + current - short - long
    total(bs, "Net assets", net_assets)
    members = block(bs, Heading.MEMBERS_DEBT, -1)
    capital = sum((-(line.debit - line.credit) for line in of(Heading.CAPITAL)), Decimal("0.00"))
    for line in of(Heading.CAPITAL):
        bs.append((line.code, line.name, -(line.debit - line.credit), False))
    bs.append((None, "Loss for the year" if profit < 0 else "Profit for the year", profit, False))
    total(bs, "Capital and reserves", members + capital + profit)
    return pl, bs


def _transactions(sheet, ledger: Ledger) -> None:
    uploads = {u.id: u.name for u in ledger.uploads}
    _title(sheet, f"{ledger.client.name} — transactions")
    _append(sheet, COLUMNS)
    for tx in ledger.transactions:
        code, name = (tx.paid_against, tx.paid_against_name) if tx.paid_against else (tx.account_code, tx.account_name)
        _append(sheet, [tx.date, tx.description, tx.counterparty, _TYPE_NAMES.get(tx.document_type, tx.document_type),
                      "In" if tx.direction == Direction.IN else "Out", tx.gross,
                      # as the books hold it: VAT the document rules don't reclaim stays in the amount
                      ZERO if tx.vat_not_reclaimed else tx.vat_posted,
                      tx.net + tx.vat_not_reclaimed if tx.vat_not_reclaimed and tx.net is not None else tx.net, code, name,
                      tx.contra_account_code, tx.owed, "; ".join(i.message for i in tx.issues) or None,
                      uploads.get(tx.upload_id), "Yes" if tx.edited else None, _left_out(tx)])
    for row in sheet.iter_rows(min_row=3):
        row[0].number_format = DATE
        for cell in (*row[5:8], row[11]):
            cell.number_format = MONEY
    sheet.freeze_panes = "A3"
    _widths(sheet, (12, 36, 22, 16, 8, 12, 10, 12, 9, 26, 10, 12, 50, 24, 8, 20))


def _left_out(tx: Transaction) -> Optional[str]:
    """Why a row the sheet lists is not in the books: a decision left it out, or replaced it with the rows of a split
    (which the sheet lists too). None for a row in the books, so adding up the rest adds up the books."""
    if tx.removed:
        return "Removed by a person"
    return "Replaced by a split" if tx.superseded_by else "Left out" if tx.excluded else None
