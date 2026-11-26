"""The year's accounts from the final trial balance: profit and loss and balance sheet under the FRS 105 headings,
with last year's figures beside them."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from testbooks.books.chart import CHART, HEADINGS
from testbooks.engine.model import Period
from testbooks.money import ZERO

PL_HEADINGS = HEADINGS[:7]
INCOME = ("Turnover", "Other income")
ASSET_HEADINGS = ("Called up share capital not paid", "Fixed assets", "Current assets",
                  "Prepayments and accrued income")
LIABILITY_HEADINGS = ("Creditors: amounts falling due within one year",
                      "Creditors: amounts falling due after more than one year", "Provisions for liabilities",
                      "Accruals and deferred income")
LOANS = ("2250", "2251", "2252", "2253")


@dataclass(frozen=True)
class Accounts:
    pl: tuple[tuple[str, Decimal, Decimal], ...]
    bs: tuple[tuple[str, Decimal, Decimal], ...]
    profit_after_tax: Decimal


def _sheet(balances: dict[str, Decimal], profit: Decimal) -> dict[str, Decimal]:
    out: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for code, v in balances.items():
        acc = CHART[code]
        if acc.kind in ("income", "expense"):
            continue
        heading = "Current assets" if code in LOANS and v > 0 else acc.heading
        out[heading] += v if heading in ASSET_HEADINGS else -v
    out["Capital and reserves"] += profit
    # The micro-entity balance sheet format: F = C + D - E; G = A + B + F; net assets = G - H - I - J.
    out["Net current assets"] = (out["Current assets"] + out["Prepayments and accrued income"]
                                 - out["Creditors: amounts falling due within one year"])
    out["Total assets less current liabilities"] = (out["Called up share capital not paid"] + out["Fixed assets"]
                                                    + out["Net current assets"])
    out["Net assets"] = (out["Total assets less current liabilities"]
                         - out["Creditors: amounts falling due after more than one year"]
                         - out["Provisions for liabilities"] - out["Accruals and deferred income"])
    if out["Net assets"] != out["Capital and reserves"]:
        raise ValueError(f"balance sheet doesn't balance: {out['Net assets']} vs {out['Capital and reserves']}")
    return out


def accounts(books, period: Period, prior_pl: dict[str, Decimal]) -> Accounts:
    balances = books.balances(period.end, ("opening", "books", "answers", "year_end"))
    pl: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for code, v in balances.items():
        acc = CHART[code]
        if acc.kind in ("income", "expense"):
            pl[acc.heading] += -v if acc.heading in INCOME else v
    profit = sum((pl[h] for h in INCOME), ZERO) - sum((pl[h] for h in PL_HEADINGS if h not in INCOME), ZERO)
    opening = books.balances(period.start, ("opening",))
    this_year, last_year = _sheet(balances, profit), _sheet(opening, ZERO)
    pl_rows = tuple((h, pl[h], prior_pl.get(h, ZERO)) for h in PL_HEADINGS)
    order = ASSET_HEADINGS + ("Creditors: amounts falling due within one year", "Net current assets",
                              "Total assets less current liabilities") + LIABILITY_HEADINGS[1:] + (
        "Net assets", "Capital and reserves")
    bs_rows = tuple((h, this_year[h], last_year[h]) for h in order)
    return Accounts(pl_rows, bs_rows, profit)
