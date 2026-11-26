import datetime as dt

from ledgersync.duplicates import possible_duplicates
from ledgersync.matching import Settlement
from ledgersync.models import Transaction


def tx(gross="12.88", date="2026-09-14", kind="receipt", ref=None, **kw):
    return Transaction(document_type=kind, direction=kw.pop("direction", "out"), gross=gross,
                       date=dt.date.fromisoformat(date) if date else None, description=kw.pop("description", "x"),
                       account_code="7406", document_ref=ref, **kw)


def test_the_same_amount_from_two_uploads_a_day_apart_is_flagged_against_the_first():
    rows = [tx(ref="a"), tx(date="2026-09-15", ref="b")]
    assert possible_duplicates(rows, uploads=[1, 2], ids=[10, 11]) == [None, 0]


def test_rows_of_one_upload_are_not_compared():
    assert possible_duplicates([tx(ref="a"), tx(ref="b")], uploads=[1, 1], ids=[10, 11]) == [None, None]


def test_amounts_more_than_three_days_apart_or_another_way_are_not_flagged():
    rows = [tx(ref="a"), tx(date="2026-09-18", ref="b"), tx(ref="c", direction="in")]
    assert possible_duplicates(rows, uploads=[1, 2, 3], ids=[10, 11, 12]) == [None, None, None]


def test_two_undated_rows_of_one_amount_are_flagged():
    rows = [tx(date=None, ref="a"), tx(date=None, ref="b")]
    assert possible_duplicates(rows, uploads=[1, 2], ids=[10, 11]) == [None, 0]


def test_a_bill_and_the_bank_line_that_pays_it_are_not_duplicates():
    rows = [tx(kind="invoice", ref="a"), tx(kind="statement", ref="b")]
    assert possible_duplicates(rows, uploads=[1, 2], ids=[10, 11]) == [None, None]


def test_rows_matching_linked_or_a_person_kept_apart_are_not_flagged():
    linked = [tx(ref="a"), tx(ref="b", paid_by=[Settlement(ref="a", amount="12.88")])]
    apart = [tx(ref="a"), tx(ref="b", apart_from=[10])]
    assert possible_duplicates(linked, uploads=[1, 2], ids=[10, 11]) == [None, None]
    assert possible_duplicates(apart, uploads=[1, 2], ids=[10, 11]) == [None, None]


def test_two_receipts_on_one_expense_claim_are_not_duplicates():
    on_claim = Settlement(ref="claim", amount="12.88", kind="expense_claim")
    rows = [tx(ref="a", claimed_in=on_claim), tx(ref="b", claimed_in=on_claim)]
    assert possible_duplicates(rows, uploads=[1, 2], ids=[10, 11]) == [None, None]


def test_two_receipts_on_two_lines_of_one_expense_claim_are_not_duplicates():
    # Each receipt is matched to its own line of the claim (claimed_in names the line), and the lines are one upload.
    booked_by = {"recorded_by": Settlement(ref="r", amount="12.88")}   # a claim line is booked from its receipt
    lines = [tx(kind="expense_claim", ref="l1", date="2026-10-07", **booked_by),
             tx(kind="expense_claim", ref="l2", date="2026-10-08", **booked_by)]
    receipts = [tx(ref="r1", date="2026-10-07", claimed_in=Settlement(ref="l1", amount="12.88", kind="expense_claim")),
                tx(ref="r2", date="2026-10-08", claimed_in=Settlement(ref="l2", amount="12.88", kind="expense_claim"))]
    assert possible_duplicates([*lines, *receipts], uploads=[9, 9, 1, 2], ids=[1, 2, 10, 11])[2:] == [None, None]


def test_two_receipts_on_lines_of_two_claims_are_still_compared():
    booked_by = {"recorded_by": Settlement(ref="r", amount="12.88")}
    lines = [tx(kind="expense_claim", ref="l1", **booked_by), tx(kind="expense_claim", ref="l2", **booked_by)]
    receipts = [tx(ref="r1", claimed_in=Settlement(ref="l1", amount="12.88", kind="expense_claim")),
                tx(ref="r2", claimed_in=Settlement(ref="l2", amount="12.88", kind="expense_claim"))]
    assert possible_duplicates([*lines, *receipts], uploads=[8, 9, 1, 2], ids=[1, 2, 10, 11])[2:] == [None, 2]


def test_a_row_out_of_the_books_is_no_ones_duplicate():
    rows = [tx(ref="a"), tx(ref="b", excluded=True), tx(ref="c", copy_of=Settlement(ref="a", amount="12.88"))]
    assert possible_duplicates(rows, uploads=[1, 2, 3], ids=[10, 11, 12]) == [None, None, None]


def test_a_payroll_line_and_the_bank_line_that_pays_it_are_not_duplicates():
    # Kestrel's January net pay: flagged as a possible duplicate, the review dropped the bank payment, leaving the
    # bank £4,750.00 away from its statement and the wages owed never cleared.
    rows = [tx(gross="2400.00", date="2026-01-30", kind="payroll"), tx(gross="2400.00", date="2026-01-30", kind="statement")]
    assert possible_duplicates(rows, uploads=[1, 2], ids=[1, 2]) == [None, None]


def invoice(number, total, date, ref, who="Ashdown Supplies Ltd", **kw):
    return tx(gross=total, date=date, kind="invoice", ref=ref, document_number=number, document_total=total,
              counterparty=who, **kw)


def test_an_invoice_under_a_number_already_used_for_another_total_is_flagged_against_the_earlier_one():
    from ledgersync.duplicates import renumbered_invoices
    rows = [invoice("A-551", "240.00", "2026-05-12", "revised"), invoice("A-551", "360.00", "2026-05-10", "original"),
            invoice("A 551", "360.00", "2026-05-10", "elsewhere", who="Travis Perkins"),
            invoice("A-552", "99.00", "2026-05-12", "next")]
    assert renumbered_invoices(rows, ids=[10, 11, 12, 13]) == [[1], None, None, None]


def test_the_same_number_at_the_same_total_or_kept_apart_or_the_other_way_is_not_flagged():
    from ledgersync.duplicates import renumbered_invoices
    same_total = [invoice("7", "50.00", "2026-05-10", "a"), invoice("7", "50.00", "2026-05-12", "b")]
    apart = [invoice("7", "50.00", "2026-05-10", "a"), invoice("7", "60.00", "2026-05-12", "b", apart_from=[10])]
    ways = [invoice("7", "50.00", "2026-05-10", "a"), invoice("7", "60.00", "2026-05-12", "b", direction="in")]
    for rows in (same_total, apart, ways):
        assert renumbered_invoices(rows, ids=[10, 11]) == [None, None]


def test_two_write_offs_of_the_same_amount_are_not_duplicates():
    from decimal import Decimal
    import datetime as dt
    from ledgersync.duplicates import possible_duplicates
    from ledgersync.models import Transaction
    off = dict(date=dt.date(2024, 1, 31), direction="out", gross=Decimal("600.00"), account_code="8100",
               document_type="write_off", description="Bad debt written off")
    assert possible_duplicates([Transaction(**off, writes_off="a"), Transaction(**off, writes_off="b")],
                               uploads=[1, 2], ids=[1, 2]) == [None, None]


def test_two_till_receipts_with_different_numbers_are_two_purchases():
    # The test books' EC-0430, in the paid run of 25 Nov 2026: two £4.50 coffees at Quayside Coffee on 6 Mar 2024,
    # receipts QC-301 and QC-302, were flagged as a possible duplicate. A till numbers every receipt: a second photo
    # of one receipt has its number, another purchase has its own.
    first = tx(gross="4.50", counterparty="Quayside Coffee Co", document_number="QC-301")
    second = tx(gross="4.50", counterparty="Quayside Coffee Co", document_number="QC-302")
    assert possible_duplicates([first, second], uploads=[1, 2], ids=[1, 2]) == [None, None]
    again = tx(gross="4.50", counterparty="Quayside Coffee Co", document_number="QC 301")
    assert possible_duplicates([first, again], uploads=[1, 2], ids=[1, 2]) == [None, 0]
