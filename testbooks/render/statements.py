"""Statement exports in the layouts real UK banks and platforms use (research notes 1.1; several are unconfirmed and
the catalogue marks them so), under the made-up bank's name."""
from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

from testbooks.books.bank import StatementLine
from testbooks.engine.model import MoneyAccount

AMEX_HEADER = ["Date", "Description", "Amount", "Extended Details", "Appears On Your Statement As", "Address",
               "Town/City", "Postcode", "Country", "Reference", "Category"]
STRIPE_HEADER = ["automatic_payout_id", "automatic_payout_effective_at", "balance_transaction_id", "created_utc",
                 "currency", "gross", "fee", "net", "reporting_category", "description", "customer_name"]


def hsbc_amount(x: Decimal) -> str:
    """HSBC's export drops a trailing zero: -70.0, 1010.0, 276.1, -80.78."""
    s = f"{x:.2f}"
    return s[:-1] if s.endswith("0") else s


def _hsbc(lines, f):
    w = csv.writer(f, lineterminator="\r\n")
    w.writerow(["Date", "Type", "Description", "Amount", "Balance"])
    for ln in sorted(lines, key=lambda x: (x.date, x.id), reverse=True):
        w.writerow([f"{ln.date:%d %b %Y}", ln.type_code, ln.description, hsbc_amount(ln.amount),
                    hsbc_amount(ln.balance)])


def _amex(lines, f):
    w = csv.writer(f, lineterminator="\n")
    w.writerow(AMEX_HEADER)
    for ln in sorted(lines, key=lambda x: (x.date, x.id)):
        w.writerow([f"{ln.date:%d/%m/%Y}", ln.description, f"{-ln.amount:.2f}", "", ln.description, "", "", "", "",
                    f"'{ln.id.upper().replace('-', '')}'", ""])


def _stripe(lines, f):
    w = csv.writer(f, lineterminator="\n")
    w.writerow(STRIPE_HEADER)
    fees = {(ln.date, ln.description): ln.amount for ln in lines if ln.type_code == "fee"}
    for ln in sorted(lines, key=lambda x: (x.date, x.id)):
        stamp = f"{ln.date:%Y-%m-%d} 12:00:00"
        if ln.type_code == "charge":
            fee = -fees.get((ln.date, ln.description), Decimal("0"))
            w.writerow(["", "", f"txn_{ln.id.replace('-', '')}", stamp, "gbp", f"{ln.amount:.2f}", f"{fee:.2f}",
                        f"{ln.amount - fee:.2f}", "charge", ln.description, ln.description.rsplit(" retainer", 1)[0]])
        elif ln.type_code == "payout":
            w.writerow([f"po_{ln.id.replace('-', '')}", f"{ln.date:%Y-%m-%d}", f"txn_{ln.id.replace('-', '')}", stamp,
                        "gbp", f"{ln.amount:.2f}", "0.00", f"{ln.amount:.2f}", "payout", ln.description, ""])
        elif ln.type_code != "fee":
            w.writerow(["", "", f"txn_{ln.id.replace('-', '')}", stamp, "gbp", f"{ln.amount:.2f}", "0.00",
                        f"{ln.amount:.2f}", "other_adjustment", ln.description, ""])


WRITERS = {"hsbc_csv": _hsbc, "amex_csv": _amex, "stripe_csv": _stripe}


def statement_name(account: MoneyAccount, start: date, end: date) -> str:
    return f"{start:%Y-%m-%d}_{account.id}-statement_{end:%Y-%m-%d}.csv"


def render_statement(account: MoneyAccount, lines: list[StatementLine], start: date, end: date, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / statement_name(account, start, end)
    with open(path, "w", newline="", encoding="utf-8") as f:
        WRITERS[account.layout]([ln for ln in lines if start <= ln.date <= end], f)
    return path
