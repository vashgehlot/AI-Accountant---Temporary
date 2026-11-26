"""The usual account of a supplier: a purchase coded away from where the supplier's other bills went is found, and
anything less sure is left alone."""
import datetime as dt
from decimal import Decimal

from helpers import row
from ledgersync.coding import usual_accounts
from ledgersync.models import Settlement


def bills(n, code, who="Vodafone Ltd", start=0, **more):
    """n invoices from the supplier on the account, a month apart, each its own document."""
    return [row(**{**dict(document_type="invoice", counterparty=who, account_code=code, gross=Decimal("86.40"),
                          date=dt.date(2025, 1, 15) + dt.timedelta(days=30 * (start + k)),
                          document_ref=f"{who}-{code}-{start + k}"), **more}) for k in range(n)]


def found_in(rows, flag=None):
    return usual_accounts(rows, flag=flag or [True] * len(rows))


def test_a_bill_away_from_the_usual_account_is_found():
    rows = [*bills(11, "7502"), *bills(1, "7400", start=11)]
    found = found_in(rows)
    assert found[:11] == [None] * 11
    assert (found[11].code, found[11].others, found[11].on_usual) == ("7502", 11, 11)
    assert found[11].related == [10, 9, 8, 7, 6]   # the latest first


def test_fewer_than_three_others_is_quiet():
    assert found_in([*bills(2, "7502"), *bills(1, "7400", start=2)]) == [None] * 3


def test_three_others_is_enough():
    found = found_in([*bills(3, "7502"), *bills(1, "7400", start=3)])
    assert found[:3] == [None] * 3
    assert (found[3].code, found[3].others) == ("7502", 3)


def test_a_mixed_supplier_is_quiet():
    rows = [*bills(6, "7504", who="Amazon"), *bills(4, "5000", who="Amazon", start=6)]
    assert found_in(rows) == [None] * 10


def test_exactly_eighty_percent_counts():
    rows = [*bills(4, "7502"), *bills(1, "7600", start=4), *bills(1, "7400", start=5)]
    found = found_in(rows)
    assert (found[5].code, found[5].others, found[5].on_usual) == ("7502", 5, 4)
    assert found[:4] == [None] * 4


def test_a_pattern_that_changed_flags_the_old_rows():
    rows = [*bills(3, "7400"), *bills(12, "7502", start=3)]
    found = found_in(rows)
    assert [f.code for f in found[:3]] == ["7502"] * 3
    assert found[3:] == [None] * 12


def test_similar_names_are_not_one_supplier():
    rows = [*bills(5, "7502"), *bills(1, "7303", who="Vodafone Insurance Services", start=5)]
    assert found_in(rows) == [None] * 6


def test_the_bank_and_the_bill_name_one_supplier():
    rows = [*bills(3, "7502"), *bills(1, "7400", who="VODAFONE UK DD 12345", start=3, document_type="statement")]
    assert found_in(rows)[3].code == "7502"


def test_a_row_with_no_supplier_is_never_checked():
    rows = [*bills(3, "7502"), *bills(1, "7400", who=None, start=3), *bills(1, "7400", who="", start=4)]
    assert found_in(rows) == [None] * 5


def test_rows_out_of_the_check():
    """Money in, journals, payroll, rows out of the books, rows in Suspense and bank lines their document books:
    none is flagged, and none counts as history."""
    out = [bills(1, "7400", start=20, direction="in")[0],
           bills(1, "7400", start=21, document_type="journal")[0],
           bills(1, "7400", start=22, document_type="payroll")[0],
           bills(1, "7400", start=23, excluded=True)[0],
           bills(1, "7400", start=24, superseded_by="d1")[0],
           bills(1, "9998", start=25)[0],
           bills(1, "7400", start=26, document_type="statement",
                 recorded_by=Settlement(ref="x", amount=Decimal("86.40")))[0]]
    rows = [*bills(3, "7502"), *out]
    assert found_in(rows) == [None] * len(rows)
    # As history they would make 7400 the commonest account of ten rows; left out, 7502 stays usual.
    found = found_in([*rows, *bills(1, "7600", start=30)])
    assert (found[-1].code, found[-1].others, found[-1].on_usual) == ("7502", 3, 3)


def test_one_document_split_counts_once_per_account():
    split = [r.model_copy(update={"document_ref": "one-bill"}) for r in bills(3, "7502")]
    assert found_in([*split, *bills(1, "7400", start=3)]) == [None] * 4   # one other, not three


def test_the_rows_of_the_documents_own_split_are_not_its_history():
    """A bill split over two accounts is not its own odd one out."""
    bill = [r.model_copy(update={"document_ref": "one-bill"}) for r in [*bills(1, "7400", start=9), *bills(1, "7502", start=9)]]
    found = found_in([*bills(3, "7502"), *bill])
    assert found[3].code == "7502" and found[3].others == 3
    assert found[4] is None


def test_an_unflagged_row_still_counts_as_history():
    rows = [*bills(3, "7502"), *bills(1, "7400", start=3)]
    assert usual_accounts(rows, flag=[True, True, True, False]) == [None] * 4
    found = usual_accounts(rows, flag=[False, False, False, True])
    assert (found[3].code, found[3].others) == ("7502", 3)


def test_bank_lines_that_pay_a_bill_are_not_history():
    """A bank line that pays a supplier's bill posts against Creditors: the account the reader guessed for it is not
    where anything was coded. Kite & Quill's ten invoices on 7602 and one on 7603, with nine payments guessed onto 7602
    or 5002, made 7602 only 70% of its "bills", so the odd invoice was never flagged (agency run, 25 Nov 2026)."""
    paid = Settlement(ref="inv", amount=Decimal("86.40"))
    payments = [*bills(4, "7602", start=20, document_type="statement", pays=[paid], paid_against="2100"),
                *bills(5, "5002", start=24, document_type="statement", pays=[paid], paid_against="2100")]
    rows = [*bills(10, "7602"), *bills(1, "7603", start=10), *payments]
    found = found_in(rows)
    assert (found[10].code, found[10].others, found[10].on_usual) == ("7602", 10, 10)
    assert found[11:] == [None] * len(payments)


def test_a_meal_is_coded_by_who_was_there_not_by_the_restaurant():
    # The paid run of 25 Nov 2026: Marlowe's Kitchen's £186 dinner for a client, rightly on Entertainment (its VAT
    # blocked, disallowed for tax), was flagged against the 32 other bills there on Subsistence, and the rules
    # suggested moving it: that would have reclaimed blocked VAT. Who was at a meal decides its account.
    rows = [*bills(32, "7406", who="Marlowe's Kitchen"), *bills(1, "7403", who="Marlowe's Kitchen", start=32)]
    assert found_in(rows) == [None] * 33
