"""A perfect app's books, in the shape the app's API sends rows, scored against the fixture pack's real key."""
from pathlib import Path

from testbooks_runner import checks
from testbooks_runner.align import align
from testbooks_runner.books import load_key, load_profile
from testbooks_runner.mapping import app_code, load_chart, load_vat
from testbooks_runner.runs import Progress
from testbooks_runner.selection import select_units
from testbooks_runner.tests import builders as b

FIX = Path(__file__).parent / "fixtures" / "set"
FILES = {11: "inbox/2024-06-04/2024-06-03_fernbrook-consulting-ltd_fc-0412.pdf",
         12: "inbox/2024-06-11/2024-06-10_wharfside-office-interiors_0911-04.pdf",
         13: "inbox/2024-06-12/2024-06-11_the-brunswick-cafe_2418-19.pdf",
         14: "inbox/2024-06-20/2024-06-19_kingsholm-deli_1660-93.pdf",
         15: "inbox/2024-07-01/2024-06-01_hsbc-statement_2024-06-30.csv"}
YEAR = "2023-07-01"  # the app's year ending with the pack's month


def perfect_books():
    """The pack read and booked as the key says: each document's row, each statement line's row (the card payments
    recorded by their receipts, as the app records them), and the key's books journals posted on the rows."""
    chart = load_chart()
    unit = select_units(FIX, packs=["EC-0346"])[0]
    key = load_key(unit.key_dir)
    rows = [
        b.api_row(1, 11, direction="in", gross="3000.00", date="2024-06-03", document_type="invoice", vat="500.00",
                  vat_posted="500.00"),
        b.api_row(2, 12, gross="320.00", date="2024-06-10", vat="53.33", vat_posted="53.33"),
        b.api_row(3, 13, gross="12.40", date="2024-06-11", vat="2.07", vat_posted="2.07"),
        b.api_row(4, 14, gross="8.95", date="2024-06-19", vat="1.49", vat_posted="1.49"),
    ]
    card = {"kind": "receipt", "amount": "0"}
    for rid, (day, gross, direction, balance, recorded) in enumerate(
            [("2024-06-11", "320.00", "out", "4680.00", True), ("2024-06-11", "12.40", "out", "4667.60", True),
             ("2024-06-17", "3000.00", "in", "7667.60", False), ("2024-06-19", "8.95", "out", "7658.65", True)],
            start=5):
        rows.append(b.api_row(rid, 15, document_type="statement", bank_account="1200", gross=gross, date=day,
                              direction=direction, balance=balance,
                              recorded_by=dict(card, amount=gross) if recorded else None))
    booked_on = {"PK-0001": 1, "PK-0002": 2, "PK-0003": 3, "PK-0004": 4, "PK-0001/hsbc-2024-06-0001": 7}
    posted = [b.posted(booked_on[e["journal_id"]], app_code(chart, e["account"]), debit=e["debit"],
                       credit=e["credit"])
              for e in key.entries if e["journal_id"] in booked_on]
    snap = b.snapshot(rows=rows, posted_lines=posted, scored_year=YEAR,
                      uploads=[{"id": uid, "name": Path(f).name} for uid, f in FILES.items()])
    progress = Progress(app_year_start=YEAR, chat_year=YEAR, bank_codes={"hsbc": "1200"},
                        uploads=b.uploads_progress({f: uid for uid, f in FILES.items()}))
    return unit, key, snap, progress


def test_a_perfect_app_in_the_apis_row_shape_passes_every_row_check():
    unit, key, snap, progress = perfect_books()
    profile = load_profile(unit.folder)
    al = align(key, snap, progress.uploads, profile, progress.bank_codes)
    out = (checks.check_documents(unit, key, snap, al, profile, "before", progress)
           + checks.check_lines(unit, key, al, "before") + checks.check_extra_rows(unit, al, "before")
           + checks.check_entries(unit, key, snap, al, load_chart(), load_vat(), "before", progress))
    assert {(o.check, o.status) for o in out} == {("document", "pass"), ("line", "pass"), ("entry", "pass")}
    assert len([o for o in out if o.check == "document"]) == 4  # the statement is judged by its lines
    assert len([o for o in out if o.check == "line"]) == 4 and al.unpaired == []
    assert len([o for o in out if o.check == "entry"]) == 4
