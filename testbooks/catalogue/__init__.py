"""The catalogue: every edge case planted in the test books, from cases.csv (made once from the edge-case list in
docs/superpowers/specs/2026-11-18-test-books-edge-cases.md)."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

CASES_CSV = Path(__file__).with_name("cases.csv")
CATEGORIES = {"01": "Reading the paper", "02": "What is it, and should it be booked?",
              "03": "Coding, VAT, payroll and CIS", "04": "Bank and matching", "05": "Periods and years",
              "06": "Owners", "07": "Year end", "08": "Suspicious", "09": "The client's own mess"}


@dataclass(frozen=True)
class Case:
    id: str
    category: str
    title: str
    where: str
    expects: str
    stakes: str
    needs_years: bool
    layout_unconfirmed: bool
    step: int | None


def load_cases() -> list[Case]:
    with open(CASES_CSV, newline="", encoding="utf-8") as f:
        return [Case(r["id"], r["category"], r["title"], r["where"], r["expects"], r["stakes"],
                     r["needs_years"] == "Y", r["layout_unconfirmed"] == "Y", int(r["step"]) if r["step"] else None)
                for r in csv.DictReader(f)]
