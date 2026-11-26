import datetime as dt

import pytest

from ledgersync.file_dates import check_file_date, date_in_name
from ledgersync.models import Settlement, Transaction


@pytest.mark.parametrize("name, date", [
    ("Southgate_Bath_Car_Park-2026-09-09_19_52_00.jpg", dt.date(2026, 9, 9)),    # an Expensify export
    ("P01 HML service charge demand 2025-01-06.pdf", dt.date(2025, 1, 6)),
    ("IMG_20260909_195200.jpg", dt.date(2026, 9, 9)),                             # a phone's photo
    ("receipt 09.09.2026.pdf", dt.date(2026, 9, 9)),                              # day first, as in the UK
    ("Jenny (1).xlsx", None),
    ("parkside-rent-invoice-PE-2026-0619.txt", None),                             # an invoice number, not a date
    ("Statement 2026-09-01 to 2026-09-30.pdf", None),                             # two dates: neither is the one
    ("Invoice 2026-13-45.pdf", None),                                             # not a date
    ("Order 204-0803551-5813137.pdf", None),                                      # an order number
])
def test_the_date_in_a_file_name(name, date):
    assert date_in_name(name) == date


def receipt(date="2026-08-09", ref="photo", **kw):
    return Transaction(document_type="receipt", direction="out", gross="36.00", account_code="7400",
                       date=dt.date.fromisoformat(date) if date else None, counterparty="Southgate Bath Car Park",
                       document_ref=ref, **kw)


NAME = "Southgate_Bath_Car_Park-2026-09-09_19_52_00.jpg"


def codes(t):
    return [(i.code, i.severity) for i in t.issues]


def test_a_receipt_read_with_another_date_than_its_file_name_asks_which_is_right():
    # The Southgate photo was read as 9 August; its file name says 9 September.
    [checked] = check_file_date([receipt()], NAME)
    assert (checked.date, checked.date_found, codes(checked)) == (dt.date(2026, 8, 9), dt.date(2026, 9, 9),
                                                                  [("file_date", "warning")])
    assert all(d in checked.issues[0].message for d in ("9 Sep 2026", "9 Aug 2026"))


def test_a_receipt_without_a_date_is_offered_its_file_names():
    [checked] = check_file_date([receipt(date=None)], NAME)
    assert (checked.date, checked.date_found, codes(checked)) == (None, dt.date(2026, 9, 9), [("file_date", "warning")])


CLAIM = Settlement(ref="claim", amount="36.00", date=dt.date(2026, 8, 9), description="Jenny Hogg's expense claim")
CARD = Settlement(ref="card", amount="36.00", date=dt.date(2026, 8, 10), description="SOUTHGATE", kind="statement")


@pytest.mark.parametrize("rows, name", [
    ([receipt("2026-09-07")], NAME),                                   # within a few days: the same
    ([receipt(claimed_in=CLAIM)], NAME),                               # its claim line has the same date
    ([receipt(paid_by=[CARD])], NAME),                                 # so has its card payment
    ([receipt(date_found=dt.date(2026, 9, 9))], NAME),                 # matching already asks
    ([receipt(), receipt(ref="another")], NAME),                       # a file of two documents
    ([receipt().model_copy(update={"document_type": "statement"})], NAME),   # a bank line
    ([receipt()], "Southgate car park.jpg"),                           # no date in the name
])
def test_no_question_when_the_date_is_confirmed_or_the_file_name_cannot_say(rows, name):
    assert [(t.date_found, codes(t)) for t in check_file_date(rows, name)] == [(r.date_found, codes(r)) for r in rows]


def test_an_invoices_payment_weeks_later_does_not_confirm_its_date():
    invoice = receipt(paid_by=[CARD]).model_copy(update={"document_type": "invoice"})
    [checked] = check_file_date([invoice], NAME)
    assert (checked.date_found, codes(checked)) == (dt.date(2026, 9, 9), [("file_date", "warning")])


def test_a_date_a_person_confirmed_is_not_asked_about_again():
    assert codes(check_file_date([receipt(accepted=["file_date"])], NAME)[0]) == []
