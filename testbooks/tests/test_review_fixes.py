"""The final review's findings, each pinned by a test (fix pass of build step 1)."""
import csv
import random
import re
from collections import defaultdict
from datetime import date
from decimal import Decimal as D

import pytest
from pypdf import PdfReader

from testbooks.build import build
from testbooks.checks import run_checks
from testbooks.clients import agency
from testbooks.engine.simulate import simulate
from testbooks.ids import ie_vat_number, ie_vat_number_valid
from testbooks.rules.vat import vat_return

W = simulate(agency.define(), until=date(2024, 6, 30), seed=7)
PACK = "EC-0346-receipt-over-250"


def rows(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def tb(folder, end):
    return defaultdict(lambda: {c: "0.00" for c in ("opening", "books", "before_answers", "year_end", "final")},
                       {r["account"]: r for r in rows(folder / "key" / end / "trial-balance.csv")})


def text(path):
    return "".join(p.extract_text() for p in PdfReader(path).pages)


@pytest.fixture(scope="module")
def out(tmp_path_factory):
    o = tmp_path_factory.mktemp("fixes")
    build(o, seed=7, clients=["agency"], packs=["EC-0301", "EC-0346"], until=date(2024, 6, 30))
    return o


def test_before_answers_holds_the_vat_in_suspense_and_its_sweep(out):
    """Critical 1 and Important 4: before the answer the £53.33 is held in Suspense, and the VAT sweep into 2202
    is the one that state would make."""
    pack = tb(out / "packs" / PACK, "2024-06-30")
    assert pack["9998"]["before_answers"] == "53.33" and pack["9998"]["final"] == "0.00"
    assert pack["2201"]["before_answers"] == "0.00"
    assert D(pack["2202"]["final"]) - D(pack["2202"]["before_answers"]) == D("53.33")
    agency_tb = tb(out / "clients" / "agency", "2024-03-31")
    assert agency_tb["9998"]["before_answers"] == "53.33"
    assert D(agency_tb["2201"]["final"]) - D(agency_tb["2201"]["before_answers"]) == D("53.33")
    assert agency_tb["2202"]["final"] == agency_tb["2202"]["before_answers"]


def test_vat_on_the_chairs_is_reclaimed_when_the_invoice_is_in_hand():
    """Important 2: the full invoice comes with the answer in March, so the VAT is in the March to May return."""
    chairs = next(d for d in W.deals if "EC-0346" in d.cases)
    assert chairs.query.answer_date >= date(2024, 3, 7)
    assert vat_return([chairs], date(2023, 12, 1), date(2024, 2, 29)).box4 == D("0.00")
    assert vat_return([chairs], date(2024, 3, 1), date(2024, 5, 31)).box4 == D("53.33")


def test_every_answer_comes_after_its_paperwork_arrives(out):
    """Important 2: a check, and it catches an answer dated too early."""
    for folder, end in ((out / "clients" / "agency", date(2024, 3, 31)), (out / "packs" / PACK, date(2024, 6, 30))):
        assert {r.name: r.ok for r in run_checks(folder, end)}["answers_after_arrival"]
    path = out / "packs" / PACK / "key" / "2024-06-30" / "queries.csv"
    data = rows(path)
    data[0]["answer_date"] = "2024-06-01"
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(data[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(data)
    assert {r.name: r.ok for r in run_checks(out / "packs" / PACK, date(2024, 6, 30))}["answers_after_arrival"] is False


def test_the_full_invoice_is_evidence_not_a_second_purchase(out):
    """Important 3: one £320 purchase, one booked document."""
    docs = [r for r in rows(out / "clients" / "agency" / "key" / "2024-03-31" / "documents.csv")
            if "EC-0346" in r["cases"]]
    assert sorted(r["treatment"] for r in docs) == ["book", "evidence"]


def test_the_pack_asset_register_matches_its_books(tmp_path_factory, out):
    """Important 5: no year end in a one-month pack, so no depreciation in its register either."""
    register = rows(out / "packs" / "EC-0301-laptop-bought" / "key" / "2024-06-30" / "fixed-assets.csv")
    assert [(r["depreciation"], r["net_book_value"]) for r in register] == [("0.00", "1082.50")]
    for folder, end in ((out / "clients" / "agency", date(2024, 3, 31)),
                        (out / "packs" / "EC-0301-laptop-bought", date(2024, 6, 30))):
        assert {r.name: r.ok for r in run_checks(folder, end)}["fixed_assets_tie"]


def test_vat_invoices_print_both_addresses(out):
    """Important 6: Notice 700 16.3 wants the supplier's and the customer's name and address."""
    from testbooks.render.documents import address_of
    docs = rows(out / "clients" / "agency" / "key" / "2024-03-31" / "documents.csv")
    laptop = next(r for r in docs if "EC-0301" in r["cases"])
    sale = next(r for r in docs if r["kind"] == "sales_invoice" and r["recipient"] == "Brightwater Homes Ltd")
    laptop_text = text(out / "clients" / "agency" / laptop["file"])
    sale_text = text(out / "clients" / "agency" / sale["file"])
    assert address_of("Brightcore Computers Ltd") in laptop_text and agency.define().address in laptop_text
    assert address_of("Brightwater Homes Ltd") in sale_text and agency.define().address in sale_text


def test_a_receipt_summarises_its_vat_by_rate(out):
    """Important 7: the rail receipt's fare is zero-rated; only the booking fee carries 20%."""
    docs = rows(out / "clients" / "agency" / "key" / "2024-03-31" / "documents.csv")
    rail = next(r for r in docs if "EC-0226" in r["cases"])
    t = text(out / "clients" / "agency" / rail["file"])
    assert "Zero-rated £142.60" in t and "VAT 20%: net £1.25, VAT £0.25" in t
    assert "net £143.85, VAT £0.25" not in t.replace("Total net £143.85, total VAT £0.25", "")


def test_no_unregistered_freelancer_bills_over_the_vat_threshold():
    """Important 8: each freelancer not registered for VAT stays under the £85,000 threshold."""
    billed = defaultdict(D)
    for d in W.deals:
        if d.kind == "purchase" and d.lines and all(ln.account == "5100" for ln in d.lines):
            if date(2023, 4, 1) <= d.date <= date(2024, 3, 31):
                billed[d.counterparty] += d.gross
    assert len(billed) == 3 and max(billed.values()) < D("85000")


def test_the_irish_supplier_shows_an_irish_vat_number(out):
    """Re-graded minor 10: Irish VAT numbers are seven digits and a check letter."""
    docs = rows(out / "clients" / "agency" / "key" / "2024-03-31" / "documents.csv")
    corrib = next(r for r in docs if r["issuer"] == "Corrib Cloud Ltd")
    match = re.search(r"VAT number IE(\d{7}[A-W])\b", text(out / "clients" / "agency" / corrib["file"]))
    assert match and ie_vat_number_valid(match.group(1))
    assert all(ie_vat_number_valid(ie_vat_number(random.Random(n))) for n in range(20))
    assert not ie_vat_number_valid("1234567A")  # 1x8+2x7+3x6+4x5+5x4+6x3+7x2 = 112, 112 mod 23 = 20: "T", not "A"


def test_stripe_fees_carry_no_deferred_income_case():
    """Re-graded minor 11: the catalogue points at the deferred retainers, not at the fees on their payments."""
    fees = [d for d in W.deals if d.counterparty == "Stripe" and d.kind == "purchase"]
    assert fees and not any({"EC-0502", "EC-0706"} & set(d.cases) for d in fees)
