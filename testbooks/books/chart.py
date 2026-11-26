"""The answer key's chart of accounts: Sage 50 numbering, each account with its FRS 105 heading and tax treatment."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

HEADINGS: tuple[str, ...] = (
    # Profit and loss (FRS 105 / micro-entity format)
    "Turnover",
    "Other income",
    "Cost of raw materials and consumables",
    "Staff costs",
    "Depreciation and other amounts written off assets",
    "Other charges",
    "Tax",
    # Balance sheet
    "Called up share capital not paid",
    "Fixed assets",
    "Current assets",
    "Prepayments and accrued income",
    "Creditors: amounts falling due within one year",
    "Creditors: amounts falling due after more than one year",
    "Provisions for liabilities",
    "Accruals and deferred income",
    "Capital and reserves",
)

KINDS = ("asset", "liability", "equity", "income", "expense")
TAX = ("allowable", "disallowable", "capital", "not_trading", "n/a")


@dataclass(frozen=True)
class Account:
    code: str
    name: str
    kind: str
    heading: str
    tax: str


def _load() -> dict[str, Account]:
    with open(Path(__file__).with_name("chart.csv"), newline="") as f:
        accounts = [Account(**row) for row in csv.DictReader(f)]
    for a in accounts:
        if a.kind not in KINDS or a.tax not in TAX or a.heading not in HEADINGS:
            raise ValueError(f"chart.csv: bad row for {a.code}")
    return {a.code: a for a in accounts}


CHART: dict[str, Account] = _load()
FIELDS = ("code", "name", "kind", "heading", "tax")


def for_client(owners) -> dict[str, Account]:
    """The chart as one client sees it: each owner's loan account named after them."""
    chart = dict(CHART)
    for o in owners:
        if o.loan_code in chart:
            a = chart[o.loan_code]
            chart[o.loan_code] = Account(a.code, f"Director's loan - {o.name}", a.kind, a.heading, a.tax)
    return chart


def write_chart(path: Path, owners) -> Path:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(FIELDS)
        for a in for_client(owners).values():
            w.writerow([a.code, a.name, a.kind, a.heading, a.tax])
    return path
