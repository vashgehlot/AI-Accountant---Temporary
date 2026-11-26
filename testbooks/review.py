"""The folder an accountant at the firm reviews before the test books are trusted (build step 2)."""
from __future__ import annotations

import shutil
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font

from testbooks.catalogue import CASES_CSV, CATEGORIES, load_cases
from testbooks.render.sheets import save

REVIEWER_COLUMNS = ["Agree? (Y/N)", "Correct treatment", "Notes"]

README = """REVIEW OF THE TEST BOOKS' ANSWER KEY
=====================================

Thank you for checking this. Everything here is synthetic test data: the clients, people, suppliers and banks are
made up. The answer key is unreviewed until you sign it off, and the rest of the test books (five more clients and
three more years) waits for your corrections.

What to check
-------------

1. catalogue.xlsx (roughly 2 hours)
   353 edge cases, one per row. For each, read "An accountant expects" and fill the three columns on the right:
   Agree? (Y/N), the correct treatment if you disagree, and any notes. "Stakes" says whether the case changes the
   tax, the accounts, only presentation, or only which question gets asked.

2. Kestrel & Finch Digital Ltd, year to 31 March 2024 (roughly half a day)
   The paperwork is in clients/agency/inbox (in the dated batches the client sent it) and the client's replies are
   in clients/agency/answers. The key is in agency-2024-03-31/:
     key.xlsx       one sheet per table: entries (every posting), vat-returns (boxes 1 to 9), bank-recs,
                    debtors, creditors, payroll, year-end (the adjustments), trial-balance, queries, ct-working
     accounts.xlsx  profit and loss account and balance sheet (FRS 105), with last year's figures
   Please check that each treatment is what you would book, the VAT returns, the year-end adjustments, the
   corporation tax charge and the accounts. The "cases" column on each row names the edge case it plants.

How to send corrections
-----------------------

Fill the reviewer columns in catalogue.xlsx. For the agency's key, note the entry_id (or adjustment_id) of any row
you'd change, what you'd book instead, and why. Send both back; they are corrected before the build goes on.
"""


def write_catalogue(out: Path) -> tuple[Path, Path]:
    out.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(CASES_CSV, out / "catalogue.csv")
    return out / "catalogue.csv", _catalogue_xlsx(out / "catalogue.xlsx", reviewer=False)


def _catalogue_xlsx(path: Path, reviewer: bool) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "Edge cases"
    header = ["ID", "Category", "Case", "Where", "An accountant expects", "Stakes", "Needs a run of years",
              "Layout unconfirmed", "Build step"] + (REVIEWER_COLUMNS if reviewer else [])
    ws.append(header)
    for c in load_cases():
        ws.append([c.id, CATEGORIES[c.category], c.title, c.where, c.expects, c.stakes,
                   "Yes" if c.needs_years else "", "Yes" if c.layout_unconfirmed else "", c.step or ""]
                  + ([""] * 3 if reviewer else []))
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for col, width in zip("ABCDEFGHIJKL", (9, 22, 50, 10, 60, 12, 10, 10, 8, 10, 40, 40)):
        ws.column_dimensions[col].width = width
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "B2"
    return save(wb, path)


def write_review(out: Path) -> Path:
    review = out / "review"
    if review.exists():
        shutil.rmtree(review)
    review.mkdir(parents=True)
    (review / "README.txt").write_text(README, encoding="utf-8")
    _catalogue_xlsx(review / "catalogue.xlsx", reviewer=True)
    agency_key = out / "clients" / "agency" / "key" / "2024-03-31"
    if agency_key.exists():
        dest = review / "agency-2024-03-31"
        dest.mkdir()
        for name in ("key.xlsx", "accounts.xlsx", "checks.txt"):
            if (agency_key / name).exists():
                shutil.copyfile(agency_key / name, dest / name)
    return review
