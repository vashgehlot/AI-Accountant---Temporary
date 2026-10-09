import datetime as dt
import re
from decimal import Decimal

import pytest

from ledgersync import ledger
from ledgersync.checks import issue
from ledgersync.errors import ClientArchived, InvalidInput
from ledgersync.models import ClientFields, ClientPatch, ManualUpload, RowPatch, Transaction
from ledgersync.store import Store

CUBE = ClientFields(name="Business Cube Ltd", business_type="limited_company", contact_name="Jenny Clarke")


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "ledgersync.db")


def row(**changes) -> Transaction:
    fields = dict(direction="out", gross="72.00", account_code="7502", date=dt.date(2026, 9, 1), description="BT",
                  document_type="invoice", counterparty="BT Business")
    return Transaction(**{**fields, **changes})


def test_a_bill_and_its_payment_saved_apart_are_paired_in_the_ledger(store):
    client = store.create_client(CUBE)
    store.add_upload(client.id, "BT-0905.pdf", "pdf", [row(document_ref="bt")])
    store.add_upload(client.id, "Barclays.csv", "table", [row(date=dt.date(2026, 9, 5), document_type="statement",
                                                              counterparty="BT BUSINESS DD", document_ref="l1")])
    built = ledger.build(store, client.id)
    bill, line = built.transactions
    assert ([s.ref for s in line.pays], line.paid_against, bill.owed) == (["bt"], "2100", Decimal("0.00"))
    assert [u.name for u in built.uploads] == ["Barclays.csv", "BT-0905.pdf"]


def test_a_receipt_dated_away_from_its_file_names_date_asks_and_using_it_settles_the_question(store):
    client = store.create_client(CUBE)
    store.add_upload(client.id, "Southgate_Bath_Car_Park-2026-09-09_19_52_00.jpg", "image",
                     [row(document_type="receipt", gross="36.00", account_code="7400", date=dt.date(2026, 8, 9),
                          counterparty="Southgate Bath Car Park", document_ref="photo")])
    [photo] = ledger.build(store, client.id).transactions
    assert (photo.date_found, [i.code for i in photo.issues]) == (dt.date(2026, 9, 9), ["file_date"])
    [photo] = ledger.change_row(store, client.id, photo.id, RowPatch(date=dt.date(2026, 9, 9))).transactions   # Use
    assert (photo.date, photo.date_found, photo.issues, photo.edited) == (dt.date(2026, 9, 9), None, [], True)


def test_rows_a_question_is_about_are_given_by_their_row_ids(store):
    # Show both: the table shows the receipt and the claim line that ask which date is right, side by side.
    client = store.create_client(CUBE)
    store.add_upload(client.id, "claim.xlsx", "table", [row(document_type="expense_claim", counterparty="Jenny Hogg",
                     description="Jenny Hogg - Southgate Bath Car Park", gross="36.00", account_code="7400",
                     date=dt.date(2026, 9, 9), document_ref="claim")])
    store.add_upload(client.id, "photo.jpg", "image", [row(document_type="receipt", counterparty="Southgate Bath Car Park",
                     gross="36.00", account_code="7400", date=dt.date(2026, 8, 9), document_ref="photo")])
    line, receipt = ledger.build(store, client.id).transactions
    assert (line.issues[0].related, receipt.issues[0].related) == ([receipt.id], [line.id])


def claim_and_photo(store):
    client = store.create_client(CUBE)
    store.add_upload(client.id, "claim.xlsx", "table", [row(document_type="expense_claim", counterparty="Jenny Hogg",
                     description="Jenny Hogg - Southgate Bath Car Park", gross="36.00", account_code="7400",
                     date=dt.date(2026, 9, 9), document_ref="claim")])
    store.add_upload(client.id, "photo.jpg", "image", [row(document_type="receipt", counterparty="Southgate Bath Car Park",
                     gross="36.00", account_code="7400", date=dt.date(2026, 8, 9), document_ref="photo")])
    return client


def test_not_the_same_is_kept_on_the_row_and_ends_the_question_until_undone(store):
    client = claim_and_photo(store)
    line, photo = ledger.build(store, client.id).transactions
    line, photo = ledger.change_row(store, client.id, photo.id, RowPatch(apart_from=[line.id])).transactions
    assert (photo.apart_from, photo.edited, photo.date_found, line.date_found) == ([line.id], False, None, None)
    assert [i.code for i in line.issues + photo.issues] == []
    line, photo = ledger.change_row(store, client.id, photo.id, RowPatch(apart_from=[])).transactions   # Undo
    assert [i.code for i in photo.issues] == ["date_conflict"]


@pytest.mark.parametrize("names", ["itself", "another client's row"])
def test_not_the_same_names_only_another_row_of_the_client(store, names):
    client = claim_and_photo(store)
    _, photo = ledger.build(store, client.id).transactions
    other = store.create_client(CUBE)
    store.add_upload(other.id, "x.pdf", "pdf", [row(document_ref="x")])
    wrong = photo.id if names == "itself" else store.rows(other.id)[0].id
    with pytest.raises(InvalidInput):
        ledger.change_row(store, client.id, photo.id, RowPatch(apart_from=[wrong]))


def test_a_total_put_out_by_a_persons_change_is_said_on_the_line_they_changed(store):
    client = store.create_client(CUBE)
    lines = [row(document_type="expense_claim", counterparty="Matt Barnes", description=f"Matt Barnes - {shop}",
                 gross=gross, account_code="7400", document_ref="claim", document_total="201.25")
             for shop, gross in (("Clayton Hotel", "173.75"), ("EE, mobile phone bill", "27.50"))]
    store.add_upload(client.id, "Matt.xlsx", "table", lines)
    hotel, ee = ledger.build(store, client.id).transactions
    hotel, ee = ledger.change_row(store, client.id, ee.id, RowPatch(gross=Decimal("30.22"))).transactions
    assert ([i.code for i in hotel.issues], [i.code for i in ee.issues], ee.issues[0].related) == (
        [], ["total_mismatch"], [hotel.id])


def test_the_clients_vat_setting_and_kind_of_business_are_applied(store):
    client = store.create_client(CUBE.model_copy(update={"vat_registered": False}))
    store.add_upload(client.id, "a.pdf", "pdf", [row(vat="12.00"), row(account_code="3260", document_type="receipt")])
    bill, drawings = ledger.build(store, client.id).transactions
    assert (bill.vat_posted, bill.net) == (Decimal("0.00"), Decimal("72.00"))
    assert "director_loan" in [i.code for i in drawings.issues]


def test_each_statement_upload_gets_its_balance_check(store):
    client = store.create_client(CUBE)
    line = dict(document_type="statement", counterparty="Shop")
    statement = store.add_upload(client.id, "Barclays.csv", "table", [
        row(**line, gross="20.00", balance="980.00", document_ref="l1"),
        row(**line, gross="30.00", balance="900.00", document_ref="l2")])
    receipt = store.add_upload(client.id, "r.jpg", "image", [row(document_type="receipt")])
    checks = {u.id: u.statement for u in ledger.build(store, client.id).uploads}
    assert (checks[statement].status, checks[statement].difference, checks[receipt]) == ("gap", Decimal("50.00"), None)


def test_summaries_count_rows_and_what_needs_review(store):
    client = store.create_client(CUBE)
    store.add_upload(client.id, "a.pdf", "pdf", [row(), row(account_code="9999", document_ref="x")])
    [summary] = ledger.summaries(store)
    assert (summary.id, summary.rows, summary.to_review) == (client.id, 2, 1)


def test_the_clients_page_works_a_client_out_again_only_after_its_work_changes(store, monkeypatch):
    # Final review #5: every visit to the clients page rebuilt every client's whole ledger.
    cube = store.create_client(CUBE)
    jo = store.create_client(CUBE.model_copy(update={"name": "Jo Bloggs"}))
    drawings = store.add_upload(cube.id, "a.pdf", "pdf", [row(account_code="3260", document_type="receipt")])
    store.add_upload(jo.id, "b.pdf", "pdf", [row()])
    [saved] = store.rows(cube.id)
    read, rows = [], store.rows
    monkeypatch.setattr(store, "rows", lambda client_id: read.append(client_id) or rows(client_id))

    def visit():
        read.clear()
        return [(s.rows, s.to_review) for s in ledger.summaries(store)], read

    assert visit() == ([(1, 1), (1, 0)], [cube.id, jo.id])
    assert visit() == ([(1, 1), (1, 0)], [])
    store.update_client(cube.id, {"business_type": "sole_trader"})   # drawings are a sole trader's
    assert visit() == ([(1, 0), (1, 0)], [cube.id])
    store.patch_row(cube.id, saved.id, {"account_code": "9999"})
    assert visit() == ([(1, 1), (1, 0)], [cube.id])
    store.add_upload(jo.id, "c.pdf", "pdf", [row(gross="30.00", date=dt.date(2026, 9, 20), document_ref="c")])
    assert visit() == ([(1, 1), (2, 0)], [jo.id])
    store.delete_upload(cube.id, drawings)
    assert visit() == ([(0, 0), (2, 0)], [cube.id])


def test_an_edit_is_checked_before_it_is_saved(store):
    client = store.create_client(CUBE)
    store.add_upload(client.id, "a.pdf", "pdf", [row()])
    rid = store.rows(client.id)[0].id
    for patch, message in ((RowPatch(gross="0"), "The amount must be above zero."),
                           (RowPatch(vat="72.00"), "VAT must be below the amount."),
                           (RowPatch(description=" "), "Enter a description."),
                           (RowPatch(account_code="3260"), "This account can't be chosen for Business Cube Ltd."),
                           (RowPatch(link=[]),
                            "Only a bank line, or an item of an agent's statement, can be linked to documents.")):
        with pytest.raises(InvalidInput, match=re.escape(message)):
            ledger.change_row(store, client.id, rid, patch)
    assert store.rows(client.id)[0].original is None


def test_a_row_of_an_agents_statement_can_be_linked_to_a_bill_the_agent_paid(store):
    client = store.create_client(CUBE)
    store.add_upload(client.id, "a.pdf", "pdf", [row(document_type="agent_statement", agent="R+R PR Ltd")])
    rid = store.rows(client.id)[0].id
    [linked] = ledger.change_row(store, client.id, rid, RowPatch(link=[])).transactions
    assert linked.link == []


def test_an_edit_rebooks_the_row_and_revert_brings_back_what_was_read(store):
    client = store.create_client(CUBE)
    store.add_upload(client.id, "a.pdf", "pdf", [row()])
    rid = store.rows(client.id)[0].id
    [edited] = ledger.change_row(store, client.id, rid, RowPatch(document_type="receipt", gross="70.00")).transactions
    assert (edited.edited, edited.owed, edited.contra_account_code, edited.original["gross"]) == (
        True, None, "1200", "72.00")
    [back] = ledger.change_row(store, client.id, rid, RowPatch(revert=True)).transactions
    assert (back.edited, back.gross, back.owed) == (False, Decimal("72.00"), Decimal("72.00"))


def test_a_bank_line_turned_into_an_invoice_becomes_owed(store):
    client = store.create_client(CUBE)
    store.add_upload(client.id, "s.csv", "table", [row(document_type="statement", counterparty="Clearway")])
    rid = store.rows(client.id)[0].id
    [invoice] = ledger.change_row(store, client.id, rid, RowPatch(document_type="invoice")).transactions
    assert (bool(invoice.document_ref), invoice.owed, invoice.contra_account_code) == (True, Decimal("72.00"), "2100")


def test_fixing_a_misread_amount_clears_the_statement_gap(store):
    client = store.create_client(CUBE)
    line = dict(document_type="statement", counterparty="Shop")
    store.add_upload(client.id, "s.csv", "table", [row(**line, gross="20.00", balance="980.00", document_ref="l1"),
                                                   row(**line, gross="30.00", balance="900.00", document_ref="l2")])
    second = store.rows(client.id)[1].id
    built = ledger.change_row(store, client.id, second, RowPatch(gross="80.00"))
    assert (built.uploads[0].statement.status, built.transactions[1].issues) == ("ok", [])


def test_an_archived_clients_rows_cannot_change(store):
    client = store.create_client(CUBE)
    store.add_upload(client.id, "a.pdf", "pdf", [row()])
    rid = store.rows(client.id)[0].id
    store.update_client(client.id, {"archived": True})
    with pytest.raises(ClientArchived):
        ledger.change_row(store, client.id, rid, RowPatch(include=True))


def test_a_client_needs_a_name_a_responsible_person_and_a_real_email(store):
    for change, message in (({"name": ""}, "Enter the company name."),
                            ({"contact_name": ""}, "Enter the responsible person."),
                            ({"contact_email": "jenny"}, "Enter a valid email.")):
        with pytest.raises(InvalidInput, match=re.escape(message)):
            ledger.add_client(store, CUBE.model_copy(update=change))
    client = ledger.add_client(store, CUBE)
    with pytest.raises(InvalidInput, match="Enter the company name"):
        ledger.change_client(store, client.id, ClientPatch(name="  "))
    assert ledger.change_client(store, client.id, ClientPatch(contact_phone=" 07700 900123 ")).contact_phone == "07700 900123"


def test_a_manual_entry_is_saved_as_its_own_upload(store):
    client = store.create_client(CUBE)
    built = ledger.add_manual(store, client.id, ManualUpload(transactions=[row(document_type="receipt", method="user")]))
    assert [(u.name, u.kind, u.rows) for u in built.uploads] == [("Manual entry", "manual", 1)]
    with pytest.raises(InvalidInput):
        ledger.add_manual(store, client.id, ManualUpload(transactions=[]))


@pytest.mark.parametrize("code", ["9999", "3260"])   # not in the chart; Drawings, not for a limited company
def test_a_row_added_by_hand_needs_an_account_the_client_can_use(store, code):
    # Rows sent to the API by hand were saved with any account, and one not in the chart blocked the trial balance.
    client = store.create_client(CUBE)
    with pytest.raises(InvalidInput, match="This account can't be chosen for Business Cube Ltd."):
        ledger.add_manual(store, client.id, ManualUpload(transactions=[row(document_type="receipt", account_code=code)]))
    assert store.uploads(client.id) == []


def test_the_trial_balance_comes_from_the_saved_rows(store):
    client = store.create_client(CUBE)
    store.add_upload(client.id, "a.pdf", "pdf", [row(document_type="receipt", vat="12.00")])
    assert [(l.code, l.debit, l.credit) for l in ledger.trial_balance(store, client.id).lines] == [
        ("1200", Decimal("0.00"), Decimal("72.00")), ("7502", Decimal("60.00"), Decimal("0.00")),
        ("2201", Decimal("12.00"), Decimal("0.00"))]


def test_an_edited_suspense_row_leaves_to_review(store):
    client = store.create_client(CUBE)
    store.add_upload(client.id, "a.pdf", "pdf", [row(account_code="9998",
                                                     issues=[issue("account_not_recognised", "Went to Suspense.")])])
    rid = store.rows(client.id)[0].id
    assert ledger.summaries(store)[0].to_review == 1
    ledger.change_row(store, client.id, rid, RowPatch(account_code="7500"))
    assert ledger.summaries(store)[0].to_review == 0
