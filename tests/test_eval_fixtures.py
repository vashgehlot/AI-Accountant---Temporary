import csv
import json
import re
from decimal import Decimal
from pathlib import Path

import pymupdf
import pytest

from ledgersync.intake import from_text, load_upload
from ledgersync.models import DOCUMENT_TYPES

FIXTURES = Path(__file__).parent.parent / "eval" / "fixtures"
CASE_DIRS = sorted(p for p in FIXTURES.iterdir() if p.is_dir()) if FIXTURES.exists() else []
# "1,250.00" is one number; "13576543,950.00" in a CSV row is two (a comma between fields).
NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+(?!\d)(?:\.\d+)?|\d+(?:\.\d+)?")


def numbers_in(text: str) -> set[Decimal]:
    """Every number printed in the document. Whole-text matches handle prose such as
    "£2,400.00"; per-field matches handle CSV rows, where "044,637.72" is two fields."""
    chunks = [text]
    for line in text.splitlines():
        chunks += next(csv.reader([line], delimiter="\t" if "\t" in line else ","), [])
    return {Decimal(n.replace(",", "")) for chunk in chunks for n in NUMBER.findall(chunk)}


def spec_of(case_dir):
    return json.loads((case_dir / "expected.json").read_text())


def intake_of(case_dir, spec):
    data = (case_dir / spec["input"]).read_bytes()
    if spec["input"].endswith(".txt"):
        return from_text(data.decode("utf-8"), 10**7)
    return load_upload(spec["input"], data, max_pdf_pages=30)


def test_there_are_33_cases_covering_every_input_kind():
    assert len(CASE_DIRS) == 33
    assert {spec_of(d)["kind"] for d in CASE_DIRS} == {"text", "table", "pdf", "image"}


@pytest.mark.parametrize("case_dir", CASE_DIRS, ids=lambda p: p.name)
def test_fixture_is_readable_and_well_formed(case_dir):
    spec = spec_of(case_dir)
    assert intake_of(case_dir, spec).kind == spec["kind"]
    assert spec["rows"], "every case records at least one transaction"
    for row in spec["rows"]:
        assert row["direction"] in ("in", "out")
        assert Decimal(row["gross"]) > 0 and Decimal(row["gross"]).as_tuple().exponent == -2
        assert row["vat"] is None or Decimal(row["vat"]) < Decimal(row["gross"])
        assert re.fullmatch(r"\d{4}", row["account_code"])
        assert re.fullmatch(r"2026-\d\d-\d\d", row["date"])
        assert row["document_type"] in DOCUMENT_TYPES and row["document_type"] != "other"


@pytest.mark.parametrize("case_dir", CASE_DIRS, ids=lambda p: p.name)
def test_every_expected_amount_is_printed_in_the_document(case_dir):
    # Independent check on the generator: the answer must actually be in the document.
    spec = spec_of(case_dir)
    if spec["kind"] == "image":
        pytest.skip("pixels only")
    if spec["kind"] == "pdf":
        with pymupdf.open(case_dir / spec["input"]) as doc:
            text = "".join(page.get_text() for page in doc)
        if not text.strip():
            pytest.skip("scanned PDF has no text layer")
    else:
        text = intake_of(case_dir, spec).text
    printed = numbers_in(text)
    for row in spec["rows"]:
        assert Decimal(row["gross"]) in printed, row


def test_a_paid_invoice_is_covered():
    # A real invoice marked "Less Amount Paid ... AMOUNT DUE 0.00" came back with no transactions:
    # the model read "nothing due" as "nothing to record".
    spec = spec_of(FIXTURES / "pdf-paid-invoice")
    with pymupdf.open(FIXTURES / "pdf-paid-invoice" / spec["input"]) as doc:
        text = "".join(page.get_text() for page in doc)
    assert [(r["direction"], r["gross"], r["vat"]) for r in spec["rows"]] == [("out", "1260.00", "210.00")]
    assert "less amount paid" in text.lower() and "amount due" in text.lower() and "0.00" in text


def test_mixed_vat_receipt_is_covered():
    # Spec: receipts including mixed VAT, where "document VAT wins" and a gross/6 estimate differ.
    # Zero-rated food and standard-rated cleaning supplies: its VAT summary divides by rate, not by account, so
    # the reader keeps it whole (mixed_items) and the agent splits it.
    rows = spec_of(FIXTURES / "img-supermarket-mixed-vat")["rows"]
    assert [(r["gross"], r["vat"], r["account_code"]) for r in rows] == [("7.95", "0.70", "7801")]


def test_a_note_of_mixed_expenses_is_split_by_account():
    rows = spec_of(FIXTURES / "text-expense-note-mixed")["rows"]
    assert [(r["gross"], r["account_code"]) for r in rows] == [("18.00", "7406"), ("32.00", "7400")]


def test_a_mixed_receipt_with_one_vat_total_stays_one_row():
    # Its VAT cannot be divided between the coffee and the notebook, so it stays whole.
    rows = spec_of(FIXTURES / "text-mixed-receipt-one-vat")["rows"]
    assert [(r["gross"], r["vat"], r["account_code"]) for r in rows] == [("12.00", "2.00", "7504")]


def test_receipt_renderer_refuses_characters_its_font_lacks():
    # Pillow's built-in font has no "£": the train ticket showed a box instead.
    import eval_cases
    with pytest.raises(ValueError, match="£"):
        eval_cases._receipt_png(["Total paid £87.50"])


def test_a_held_out_statement_of_unseen_payees_checks_account_choice():
    # Its payees appear in no other fixture; its accounts were set before the prompt was changed.
    rows = spec_of(FIXTURES / "csv-unseen-payees")["rows"]
    others = {r["description"] for d in CASE_DIRS if d.name != "csv-unseen-payees" for r in spec_of(d)["rows"]}
    assert len(rows) == 20 and not {r["description"] for r in rows} & others


def test_a_second_held_out_statement_mixes_named_items_and_payees_alone():
    # Written before the third wording of the account rule, once the first held-out statement had
    # been used to choose between wordings. No payee here appears in any other fixture.
    rows = spec_of(FIXTURES / "csv-unseen-mixed")["rows"]
    payees = {r["description"].split(" - ")[0].lower() for r in rows}
    others = [r["description"].lower() for d in CASE_DIRS if d.name != "csv-unseen-mixed" for r in spec_of(d)["rows"]]
    assert len(rows) == 20 and not [p for p in payees if any(p in other for other in others)]
    assert sum(" - " in r["description"] for r in rows) == 5          # what was bought, named
    assert sum(r["account_code"] == "9998" for r in rows) == 4         # anything-sellers, no account fits
