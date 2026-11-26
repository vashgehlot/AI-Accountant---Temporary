import datetime as dt
import io
import re
from decimal import Decimal

import pytest
from openpyxl import load_workbook

from ledgersync import books, ledger, posting
from ledgersync.checks import booked, issue
from ledgersync.errors import ClientArchived, InvalidInput
from ledgersync.ledger import assign_codes
from ledgersync.models import BankAccount, Client, ClientFields, ClientPatch, ManualUpload, RowPatch, Transaction

CUBE = ClientFields(name="Business Cube Ltd", business_type="limited_company", contact_name="Jenny Clarke",
                    first_year_end=dt.date(2027, 3, 31))
YEAR = dt.date(2026, 4, 1)   # the year its rows are in


pytestmark = pytest.mark.mongo


@pytest.fixture
def store(mongo_store):
    return mongo_store


def row(**changes) -> Transaction:
    fields = dict(direction="out", gross="72.00", account_code="7502", date=dt.date(2026, 9, 1), description="BT",
                  document_type="invoice", counterparty="BT Business")
    return Transaction(**{**fields, **changes})


def test_a_bill_and_its_payment_saved_apart_are_paired_in_the_ledger(store):
    client = store.create_client(CUBE)
    store.add_upload(client.id, "BT-0905.pdf", "pdf", [row(document_ref="bt")])
    store.add_upload(client.id, "Barclays.csv", "table", [row(date=dt.date(2026, 9, 5), document_type="statement",
                                                              counterparty="BT BUSINESS DD", document_ref="l1")])
    built = books.ledger(store, client.id, YEAR)
    bill, line = built.transactions
    assert ([s.ref for s in line.pays], line.paid_against, bill.owed) == (["bt"], "2100", Decimal("0.00"))
    assert [u.name for u in built.uploads] == ["Barclays.csv", "BT-0905.pdf"]


def test_a_receipt_dated_away_from_its_file_names_date_asks_and_using_it_settles_the_question(store):
    client = store.create_client(CUBE)
    store.add_upload(client.id, "Southgate_Bath_Car_Park-2026-09-09_19_52_00.jpg", "image",
                     [row(document_type="receipt", gross="36.00", account_code="7400", date=dt.date(2026, 8, 9),
                          counterparty="Southgate Bath Car Park", document_ref="photo")])
    [photo] = books.ledger(store, client.id, YEAR).transactions
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
    line, receipt = books.ledger(store, client.id, YEAR).transactions
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
    line, photo = books.ledger(store, client.id, YEAR).transactions
    line, photo = ledger.change_row(store, client.id, photo.id, RowPatch(apart_from=[line.id])).transactions
    assert (photo.apart_from, photo.edited, photo.date_found, line.date_found) == ([line.id], False, None, None)
    assert [i.code for i in line.issues + photo.issues] == []
    line, photo = ledger.change_row(store, client.id, photo.id, RowPatch(apart_from=[])).transactions   # Undo
    assert [i.code for i in photo.issues] == ["date_conflict"]


@pytest.mark.parametrize("names", ["itself", "another client's row"])
def test_not_the_same_names_only_another_row_of_the_client(store, names):
    client = claim_and_photo(store)
    _, photo = books.ledger(store, client.id, YEAR).transactions
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
    hotel, ee = books.ledger(store, client.id, YEAR).transactions
    hotel, ee = ledger.change_row(store, client.id, ee.id, RowPatch(gross=Decimal("30.22"))).transactions
    # (the claim's hotel line has no receipt, so it also says one is still wanted; that is not what this is about)
    totals = lambda r: [i for i in r.issues if i.code != "document_wanted"]
    assert ([i.code for i in totals(hotel)], [i.code for i in totals(ee)], totals(ee)[0].related) == (
        [], ["total_mismatch"], [hotel.id])


def test_the_clients_vat_setting_and_kind_of_business_are_applied(store):
    client = store.create_client(CUBE.model_copy(update={"vat_registered": False}))
    store.add_upload(client.id, "a.pdf", "pdf", [row(vat="12.00"), row(account_code="3260", document_type="receipt")])
    bill, drawings = books.ledger(store, client.id, YEAR).transactions
    assert (bill.vat_posted, bill.net) == (Decimal("0.00"), Decimal("72.00"))
    assert "director_loan" in [i.code for i in drawings.issues]


def test_each_statement_upload_gets_its_balance_check(store):
    client = store.create_client(CUBE)
    line = dict(document_type="statement", counterparty="Shop")
    statement = store.add_upload(client.id, "Barclays.csv", "table", [
        row(**line, gross="20.00", balance="980.00", document_ref="l1"),
        row(**line, gross="30.00", balance="900.00", document_ref="l2")])
    receipt = store.add_upload(client.id, "r.jpg", "image", [row(document_type="receipt")])
    checks = {u.id: u.statement for u in books.ledger(store, client.id, YEAR).uploads}
    assert (checks[statement].status, checks[statement].difference, checks[receipt]) == ("gap", Decimal("50.00"), None)


def test_summaries_count_rows_and_what_needs_review(store):
    client = store.create_client(CUBE)
    store.add_upload(client.id, "a.pdf", "pdf", [row(), row(account_code="9999", document_ref="x")])
    [summary] = ledger.summaries(store)
    assert (summary.id, summary.rows, summary.to_review) == (client.id, 2, 1)


@pytest.mark.parametrize("left_out", [{"excluded": True}, {"superseded_by": "d1"}])
def test_a_row_left_out_of_the_books_needs_no_review(store, left_out):
    # A duplicate a decision dropped kept its error, and the clients page and the Overview still counted it.
    client = store.create_client(CUBE)
    store.add_upload(client.id, "a.pdf", "pdf", [row(), row(account_code="9999", document_ref="x")])
    store.patch_row(client.id, store.rows(client.id)[1].id, left_out)
    assert (ledger.summaries(store)[0].to_review, books.summary(store, client.id, YEAR).to_review) == (0, 0)


def test_the_clients_page_works_a_client_out_again_only_after_its_work_changes(store, monkeypatch):
    # Final review #5: every visit to the clients page rebuilt every client's whole ledger.
    cube = store.create_client(CUBE)
    jo = store.create_client(CUBE.model_copy(update={"name": "Jo Bloggs"}))
    drawings = store.add_upload(cube.id, "a.pdf", "pdf", [row(account_code="3260", document_type="receipt")])
    store.add_upload(jo.id, "b.pdf", "pdf", [row()])
    [saved] = store.rows(cube.id)
    read, whole = [], store.whole   # a client's ledger is built from one read of the whole client
    monkeypatch.setattr(store, "whole", lambda client_id: read.append(client_id) or whole(client_id))

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
    # (an £80 bank line with no document is held, which the row says; the statement gap is what clears)
    assert (built.uploads[0].statement.status, [i.code for i in built.transactions[1].issues]) == (
        "ok", ["needs_document"])


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


def test_a_row_added_by_hand_is_saved_without_the_marks_only_a_decision_sets(store):
    client = store.create_client(CUBE)
    ledger.add_manual(store, client.id, ManualUpload(transactions=[
        row(document_type="receipt", method="user", excluded=True, superseded_by="dec1", decision_ids=["dec1"])]))
    [saved] = store.rows(client.id)
    assert (saved.tx.excluded, saved.tx.superseded_by, saved.tx.decision_ids) == (False, None, [])


@pytest.mark.parametrize("code", ["9999", "3260"])   # not in the chart; Drawings, not for a limited company
def test_a_row_added_by_hand_needs_an_account_the_client_can_use(store, code):
    # Rows sent to the API by hand were saved with any account, and one not in the chart blocked the trial balance.
    client = store.create_client(CUBE)
    with pytest.raises(InvalidInput, match="This account can't be chosen for Business Cube Ltd."):
        ledger.add_manual(store, client.id, ManualUpload(transactions=[row(document_type="receipt", account_code=code)]))
    assert store.uploads(client.id) == []


def test_the_trial_balance_comes_from_the_saved_rows(store):
    client = store.create_client(CUBE)
    store.add_upload(client.id, "a.pdf", "pdf", [row(document_type="receipt", vat="12.00", supplier_vat_number="GB123456789")])
    assert [(l.code, l.debit, l.credit) for l in books.trial_balance(store, client.id, YEAR).lines] == [
        ("1200", Decimal("0.00"), Decimal("72.00")), ("7502", Decimal("60.00"), Decimal("0.00")),
        ("2201", Decimal("12.00"), Decimal("0.00"))]


SOUTHGATE = "Southgate Bath Car Park"


def receipt_and_its_card_line(store, client=None):
    """A receipt and the bank line that pays it (the same shop, amount and day), so the ledger takes them as one
    payment. Saved to the client, or to a new one."""
    client = client or store.create_client(CUBE)
    paid = dict(gross="36.00", account_code="7400", date=dt.date(2026, 9, 9))
    store.add_upload(client.id, "photo.jpg", "image", [row(document_type="receipt", counterparty=SOUTHGATE,
                                                           document_ref="photo", **paid)])
    store.add_upload(client.id, "Barclays.csv", "table", [row(document_type="statement", counterparty=SOUTHGATE.upper(),
                                                              document_ref="card", **paid)])
    return client


def booked_in_the_ledger(store, client_id) -> set[int]:
    return {r.id for r in books.ledger(store, client_id, YEAR).transactions if booked(r)}


def booked_in_the_trial_balance(store, client_id) -> set[int]:
    """The rows the trial balance posts, from the places its journal names in the client's rows."""
    rows = store.rows(client_id)
    return {rows[line.transaction].id for line in books.trial_balance(store, client_id, YEAR).journal}


def test_a_card_line_and_its_receipt_are_one_payment_in_the_ledger_and_the_trial_balance(store):
    client = receipt_and_its_card_line(store)
    receipt, _ = store.rows(client.id)
    assert booked_in_the_ledger(store, client.id) == booked_in_the_trial_balance(store, client.id) == {receipt.id}


def test_a_payment_marked_not_the_same_as_a_receipt_is_booked_by_the_trial_balance_too(store):
    # The ledger booked both rows; the trial balance matched without what the person said and booked only the receipt,
    # so the bank line's money was missing from the figures while the quality gate, which reads the ledger, passed.
    client = receipt_and_its_card_line(store)
    receipt, line = store.rows(client.id)
    ledger.change_row(store, client.id, line.id, RowPatch(apart_from=[receipt.id]))
    balance = books.trial_balance(store, client.id, YEAR)
    assert booked_in_the_ledger(store, client.id) == {receipt.id, line.id}
    assert booked_in_the_trial_balance(store, client.id) == booked_in_the_ledger(store, client.id)
    assert [(l.code, l.debit, l.credit) for l in balance.lines if l.code in ("1200", "7400")] == [
        ("1200", Decimal("0.00"), Decimal("72.00")), ("7400", Decimal("72.00"), Decimal("0.00"))]
    assert {l.transaction for l in balance.journal if l.credit == Decimal("36.00")} == {0, 1}   # one bank leg each


def test_the_exported_trial_balance_sheet_has_the_payment_marked_not_the_same(store):
    client = receipt_and_its_card_line(store)
    receipt, line = store.rows(client.id)
    ledger.change_row(store, client.id, line.id, RowPatch(apart_from=[receipt.id]))
    content, _ = books.export(store, client.id, YEAR, dt.date(2026, 10, 1))
    sheet = load_workbook(io.BytesIO(content))["Trial balance"]
    assert [(r[0], r[2], r[3]) for r in sheet.iter_rows(min_row=3, values_only=True) if r[0] in ("1200", "7400")] == [
        ("1200", 0, 72), ("7400", 72, 0)]


def claim_with_a_corrected_line(store):
    """A claim whose EE line a person changed from £27.50 to £30.22, so the claim no longer adds up to its total."""
    client = store.create_client(CUBE)
    lines = [row(document_type="expense_claim", counterparty="Matt Barnes", description=f"Matt Barnes - {shop}",
                 gross=gross, account_code=account, date=dt.date(2026, 9, day), document_ref="claim",
                 document_total="201.25")
             for shop, gross, account, day in (("Clayton Hotel", "173.75", "7402", 14),
                                               ("EE, mobile phone bill", "27.50", "7502", 3))]
    store.add_upload(client.id, "claim.xlsx", "table", lines)
    ee = store.rows(client.id)[1]
    ledger.change_row(store, client.id, ee.id, RowPatch(gross="30.22"))
    return client


def test_a_row_a_person_corrected_is_booked_by_the_trial_balance_as_the_ledger_books_it(store):
    client = claim_with_a_corrected_line(store)
    assert store.rows(client.id)[1].original["gross"] == "27.50"
    built = books.ledger(store, client.id, YEAR)
    assert [i.code for i in built.transactions[1].issues] == ["total_mismatch"]
    assert booked_in_the_trial_balance(store, client.id) == booked_in_the_ledger(store, client.id)
    tb = books.trial_balance(store, client.id, YEAR)
    # the corrected amount, not the one first read; the £173.75 hotel line has no receipt, and is booked as the claim
    # shows it, so nothing sits in Suspense
    assert [(l.code, l.debit) for l in tb.lines if l.type == "expense"] == [("7402", Decimal("173.75")),
                                                                            ("7502", Decimal("30.22"))]
    assert [(l.debit, l.credit) for l in tb.lines if l.code == "9998" and (l.debit or l.credit)] == []


def test_the_trial_balance_and_the_ledger_match_with_the_same_decisions(store, monkeypatch):
    # Amounts a person corrected (read) and rows they said are not the same (apart) reach both matches alike.
    client = receipt_and_its_card_line(store, claim_with_a_corrected_line(store))
    receipt, line = store.rows(client.id)[2:]
    ledger.change_row(store, client.id, line.id, RowPatch(apart_from=[receipt.id]))
    seen, real_documents, real_match = [], books.match_documents, posting.match

    def spy_documents(rows, settings, read=None, apart=None, open_items=(), name_days=None, upload_ids=None):
        seen.append((read, apart, name_days, upload_ids))
        return real_documents(rows, settings, read, apart, open_items, name_days=name_days, upload_ids=upload_ids)

    def spy(rows, settings, read=None, apart=None, open_items=(), name_days=None, upload_ids=None):
        seen.append((read, apart, name_days, upload_ids))
        return real_match(rows, settings, read=read, apart=apart, open_items=open_items, name_days=name_days,
                          upload_ids=upload_ids)

    monkeypatch.setattr(books, "match_documents", spy_documents)
    monkeypatch.setattr(posting, "match", spy)
    books.ledger(store, client.id, YEAR)
    books.trial_balance(store, client.id, YEAR)
    (built_read, built_apart, built_days, built_uploads), balance = seen
    assert built_read == [None, Decimal("27.50"), None, None] and built_apart == [set(), set(), {3}, {2}]
    assert balance == (built_read, built_apart, built_days, built_uploads)
    assert built_days is not None and len(built_days) == 4   # the file names' days reach both matches alike
    assert built_uploads is not None and len(built_uploads) == 4   # and so do the rows' uploads


def test_an_edited_suspense_row_leaves_to_review(store):
    client = store.create_client(CUBE)
    store.add_upload(client.id, "a.pdf", "pdf", [row(account_code="9998",
                                                     issues=[issue("account_not_recognised", "Went to Suspense.")])])
    rid = store.rows(client.id)[0].id
    assert ledger.summaries(store)[0].to_review == 1
    ledger.change_row(store, client.id, rid, RowPatch(account_code="7500"))
    assert ledger.summaries(store)[0].to_review == 0


# ─── Bank accounts and credit cards ──────────────────────────────────────────

MAIN = BankAccount(name="Barclays current", kind="current", code="1200")
AMEX = BankAccount(name="Amex card", kind="credit_card")


def test_a_client_starts_with_one_current_account():
    assert CUBE.bank_accounts == [BankAccount(code="1200", name="Bank current account", kind="current")]
    settings = ledger.settings_for(Client(**CUBE.model_dump(), id=1, created_at="", updated_at=""))
    assert (settings.bank_accounts, settings.bank_account) == (("1200",), "1200")


def test_a_clients_settings_name_its_owners():
    from ledgersync.models import Owner
    client = Client(**CUBE.model_dump(exclude={"owners"}), id=1, created_at="", updated_at="",
                    owners=[Owner(slot=0, name="Hannah Finch"), Owner(slot=1, name="Omar Kestrel")])
    settings = ledger.settings_for(client)
    assert (settings.owners, settings.owner_names) == ((0, 1), ("Hannah Finch", "Omar Kestrel"))


def test_new_accounts_get_the_next_free_code_of_their_kind():
    got = assign_codes([BankAccount(name="Main", kind="current", code="1200"), BankAccount(name="Second", kind="current"),
                        BankAccount(name="Amex", kind="credit_card")], kept=[])
    assert [a.code for a in got] == ["1200", "1201", "1240"]


def test_an_account_whose_code_is_sent_keeps_it():
    got = assign_codes([BankAccount(name="Savings", kind="savings"), BankAccount(name="Old", kind="savings", code="1210")],
                       kept=[])
    assert [a.code for a in got] == ["1211", "1210"]


def test_an_account_rows_still_use_cannot_be_dropped():
    with pytest.raises(InvalidInput, match=re.escape("Amex card has transactions: move them to another account first.")):
        assign_codes([MAIN], kept=[AMEX.model_copy(update={"code": "1240"})])


@pytest.mark.parametrize("accounts, message", [
    ([], "Add at least one bank account."),
    ([BankAccount(name=" ", kind="current")], "Name each bank account."),
    ([MAIN, MAIN.model_copy(update={"code": ""})], "Two bank accounts are called Barclays current: give each its own name."),
    ([BankAccount(name=f"Card {n}", kind="credit_card") for n in range(3)], "You can add up to 2 credit card accounts."),
])
def test_a_clients_bank_accounts_are_checked(store, accounts, message):
    with pytest.raises(InvalidInput, match=re.escape(message)):
        ledger.add_client(store, CUBE.model_copy(update={"bank_accounts": accounts}))


def test_a_clients_bank_accounts_are_saved_with_their_codes_and_its_first_current_account_is_the_bank(store):
    client = ledger.add_client(store, CUBE.model_copy(update={"bank_accounts": [AMEX, MAIN]}))
    assert [(a.code, a.name, a.kind) for a in store.get_client(client.id).bank_accounts] == [
        ("1240", "Amex card", "credit_card"), ("1200", "Barclays current", "current")]
    settings = ledger.settings_for(client)
    assert (settings.bank_accounts, settings.bank_account) == (("1240", "1200"), "1200")


def test_an_account_with_transactions_stays_until_they_are_moved(store):
    client = ledger.add_client(store, CUBE.model_copy(update={"bank_accounts": [MAIN, AMEX]}))
    upload = store.add_upload(client.id, "Amex.pdf", "pdf", [row(document_type="statement")], bank_account="1240")
    with pytest.raises(InvalidInput, match="Amex card has transactions"):
        ledger.change_client(store, client.id, ClientPatch(bank_accounts=[MAIN]))
    ledger.set_upload_bank(store, client.id, upload, "1200")
    assert [a.code for a in ledger.change_client(store, client.id, ClientPatch(bank_accounts=[MAIN])).bank_accounts] == [
        "1200"]


def test_an_uploads_bank_account_moves_its_statement_lines(store):
    client = ledger.add_client(store, CUBE.model_copy(update={"bank_accounts": [MAIN, AMEX]}))
    upload = store.add_upload(client.id, "Amex.pdf", "pdf", [row(document_type="statement"), row(document_type="receipt", gross="10.00")],
                              bank_account="1200")
    built = ledger.set_upload_bank(store, client.id, upload, "1240")
    assert [u.bank_account for u in built.uploads] == ["1240"]
    assert [(t.bank_account, t.contra_account_code) for t in built.transactions] == [("1240", "1240"), (None, "1200")]
    with pytest.raises(InvalidInput, match="Choose one of Business Cube Ltd's bank accounts."):
        ledger.set_upload_bank(store, client.id, upload, "1210")


def test_a_credit_card_upload_is_checked_as_a_card_statement(store):
    client = ledger.add_client(store, CUBE.model_copy(update={"bank_accounts": [MAIN, AMEX]}))
    lines = [row(document_type="statement", gross="40.00", balance="140.00", opening_balance="100.00"),
             row(document_type="statement", gross="10.00", balance="150.00", closing_balance="150.00")]
    store.add_upload(client.id, "Amex.pdf", "pdf", lines, bank_account="1240")
    store.add_upload(client.id, "Barclays.pdf", "pdf", lines, bank_account="1200")
    assert [(u.name, u.statement.status) for u in books.ledger(store, client.id, YEAR).uploads] == [
        ("Barclays.pdf", "gap"), ("Amex.pdf", "ok")]


def test_a_row_may_be_coded_to_another_of_the_clients_own_accounts(store):
    client = ledger.add_client(store, CUBE.model_copy(update={"bank_accounts": [MAIN, AMEX]}))
    built = ledger.add_manual(store, client.id, ManualUpload(transactions=[
        row(document_type="statement", account_code="1240", bank_account="1200")]))
    [line] = built.transactions
    assert (line.account_code, line.contra_account_code) == ("1240", "1200")
    with pytest.raises(InvalidInput, match="This account can't be chosen"):
        ledger.change_row(store, client.id, line.id, RowPatch(account_code="1241"))


def test_a_one_account_client_keeps_the_old_account_offer(store):
    client = ledger.add_client(store, CUBE)
    built = ledger.add_manual(store, client.id, ManualUpload(transactions=[row(document_type="statement")]))
    [line] = built.transactions
    assert ledger.change_row(store, client.id, line.id, RowPatch(account_code="1210")).transactions[0].account_code == "1210"
    with pytest.raises(InvalidInput, match=re.escape("This account can't be chosen for Business Cube Ltd.")):
        ledger.change_row(store, client.id, line.id, RowPatch(account_code="1200"))
    with pytest.raises(InvalidInput, match=re.escape("This account can't be chosen for Business Cube Ltd.")):
        ledger.add_manual(store, client.id, ManualUpload(transactions=[row(document_type="statement", account_code="1200")]))


def test_a_client_with_two_accounts_is_offered_both_in_edits(store):
    savings = BankAccount(name="Savings", kind="savings", code="1210")
    client = ledger.add_client(store, CUBE.model_copy(update={"bank_accounts": [MAIN, savings]}))
    [line] = ledger.add_manual(store, client.id, ManualUpload(transactions=[
        row(document_type="statement", bank_account="1210")])).transactions
    for code in ("1200", "1210"):
        assert ledger.change_row(store, client.id, line.id, RowPatch(account_code=code)).transactions[0].account_code == code
