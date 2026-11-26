"""Questions worked out from the books, and answers applied without the model: the rules ask for a date or a
document, a person's answer is applied by the services, and a question goes when the books no longer need it."""
from datetime import date
from decimal import Decimal as D

import pytest
from helpers import add_rows, net, row

from ledgersync import books, ledger_book, questions
from ledgersync.errors import InvalidInput, NotFound
from ledgersync.questions import DateAnswer, NoDocumentAnswer, NotSureAnswer, WithoutDocumentAnswer
from ledgersync.records import AgentRecords

pytestmark = pytest.mark.mongo

YEAR_1 = date(2025, 4, 1)
YEAR_2 = date(2026, 4, 1)


@pytest.fixture
def store(mongo_store):
    return mongo_store


@pytest.fixture
def records(mongo_db):
    return AgentRecords(mongo_db)


def travel_line(**changes):
    """A £240.00 payment to Trainline on the bank statement, with no invoice behind it."""
    return row(**{**dict(date=date(2025, 7, 1), gross=D("240.00"), account_code="7400", document_type="statement",
                         counterparty="Trainline", description="TRAINLINE"), **changes})


def trainline_invoice(**changes):
    return row(**{**dict(date=date(2025, 6, 28), gross=D("240.00"), account_code="7400", document_type="invoice",
                         counterparty="Trainline", description="Train tickets", document_ref="TL-1",
                         document_number="TL-1"), **changes})


def undated_taxi(**changes):
    return row(**{**dict(date=None, gross=D("12.00"), account_code="7400", description="taxi"), **changes})


def refresh(store, records, client_id):
    return questions.refresh(store, records, client_id, YEAR_1)


def answer(store, records, client_id, question, given):
    """The open and waiting questions the answer leaves."""
    return questions.answer(store, records, client_id=client_id, thread_id="t1", question_id=question.id,
                            answer=given).questions


def row_named(store, client_id, description):
    return next(r for r in store.rows(client_id) if r.tx.description == description)


def test_undated_receipt_without_bank_match_asks_for_date(store, records, acme):
    add_rows(store, acme, undated_taxi(), year_start=YEAR_1)
    [q] = refresh(store, records, acme)
    assert (q.kind, q.source, q.status) == ("date", "rules", "open")
    assert q.text == "When was this taxi?"
    assert q.why == "£12.00, no date on it and no matching bank line."
    assert q.row_ids == [row_named(store, acme, "taxi").id] and q.year_start == YEAR_1
    assert records.db.questions.find_one({"id": q.id})["key"] == f"date:{q.row_ids[0]}"
    assert [x.id for x in refresh(store, records, acme)] == [q.id]   # asking again asks nothing new


def test_receipt_dated_from_bank_asks_nothing(store, records, acme):
    receipt = undated_taxi(description="Pret lunch", gross=D("30.00"), counterparty="Pret")
    bank = row(date=date(2025, 7, 2), gross=D("30.00"), account_code="7400", document_type="statement",
               counterparty="Pret", description="PRET")
    add_rows(store, acme, receipt, bank, year_start=YEAR_1)
    dated = next(r for r in books.ledger(store, acme, YEAR_1).transactions if r.description == "Pret lunch")
    assert dated.date == date(2025, 7, 2) and any(i.code == "date_from_bank" for i in dated.issues)
    assert refresh(store, records, acme) == []


def test_file_name_date_never_used(store, records, acme):
    store.add_upload(acme, "IMG_20261014.png", "image", [undated_taxi()], year_start=YEAR_1)
    seen = books.ledger(store, acme, YEAR_1).transactions[0]
    assert seen.date is None and seen.date_found == date(2026, 10, 14)   # the name's date is only offered
    [q] = refresh(store, records, acme)
    assert (q.kind, q.text) == ("date", "When was this taxi?")
    assert store.rows(acme)[0].tx.date is None


def test_240_payment_without_invoice_asks_for_document(store, records, acme):
    add_rows(store, acme, travel_line(), year_start=YEAR_1)
    [q] = refresh(store, records, acme)
    assert (q.kind, q.source, q.status) == ("receipt_or_invoice", "rules", "open")
    assert q.text == "Can you upload the receipt or invoice?"
    assert q.why == ("£240.00 to Trainline on 1 Jul 2025. £50 or more, so I need it. "
                     "Held in Suspense as Documentation required until then.")
    assert records.db.questions.find_one({"id": q.id})["key"] == f"doc:{q.row_ids[0]}"


def test_receipt_over_250_asks_for_vat_invoice(store, records, acme):
    add_rows(store, acme, row(date=date(2025, 8, 1), gross=D("300.00"), vat=D("50.00"), account_code="7504",
                              counterparty="Apple", description="Laptop bag", supplier_vat_number="GB123456789"),
             year_start=YEAR_1)
    [q] = refresh(store, records, acme)
    assert q.kind == "vat_invoice" and q.text == "Can you upload the full VAT invoice?"
    assert q.why == ("£300.00 to Apple on 1 Aug 2025. Over £250, so I need it. "
                     "Held in Suspense as Documentation required until then.")


def test_a_row_without_a_counterparty_is_named_by_its_description(store, records, acme):
    add_rows(store, acme, travel_line(counterparty=None), year_start=YEAR_1)
    [q] = refresh(store, records, acme)
    assert q.why.startswith("£240.00 to TRAINLINE on 1 Jul 2025.")


def test_answer_date_dates_row_and_resolves(store, records, acme):
    add_rows(store, acme, undated_taxi(), year_start=YEAR_1)
    [q] = refresh(store, records, acme)
    assert answer(store, records, acme, q, DateAnswer(kind="date", date=date(2025, 8, 14))) == []
    assert row_named(store, acme, "taxi").tx.date == date(2025, 8, 14)
    done = records.question(q.id)
    assert (done.status, done.answer) == ("resolved", "14 Aug 2025") and done.resolved_at
    [d] = records.decisions(acme)
    assert (d.action, d.status, d.actor, d.row_ids) == ("set_date", "applied", "user", [q.row_ids[0]])
    assert ledger_book.unposted_changes(store, records, acme, YEAR_1) == 0   # answering posted the row
    assert net(ledger_book.posted_trial_balance(store, records, acme, YEAR_1), "7400") == D("12.00")


def test_an_applied_answer_records_a_change_and_a_repeat_does_not(store, records, acme):
    add_rows(store, acme, undated_taxi(), year_start=YEAR_1)
    [q] = refresh(store, records, acme)
    for _ in range(2):
        answer(store, records, acme, q, DateAnswer(kind="date", date=date(2025, 8, 14)))
    [change] = [c for c in records.changes(acme) if c.kind == "question_answered"]
    assert (change.actor, change.row_ids, change.summary) == ("user", q.row_ids, f"Answered: {q.text}")


def test_answer_twice_is_one_decision(store, records, acme):
    add_rows(store, acme, undated_taxi(), year_start=YEAR_1)
    [q] = refresh(store, records, acme)
    given = DateAnswer(kind="date", date=date(2025, 8, 14))
    answer(store, records, acme, q, given)
    answer(store, records, acme, q, given)
    assert len(records.decisions(acme)) == 1
    assert records.db.ledger_entries.count_documents({"client_id": acme}) == 2   # posted once


def test_a_retry_after_a_partial_failure_is_still_one_decision(store, records, acme):
    # The decision was made and the question left open (say the first call failed before resolving it).
    add_rows(store, acme, undated_taxi(), year_start=YEAR_1)
    [q] = refresh(store, records, acme)
    given = DateAnswer(kind="date", date=date(2025, 8, 14))
    answer(store, records, acme, q, given)
    records.set_question(q.id, "open")
    answer(store, records, acme, q, given)
    assert records.question(q.id).status == "resolved" and len(records.decisions(acme)) == 1
    assert records.db.ledger_entries.count_documents({"client_id": acme}) == 2


def test_an_answer_to_a_resolved_question_does_nothing(store, records, acme):
    add_rows(store, acme, undated_taxi(), year_start=YEAR_1)
    [q] = refresh(store, records, acme)
    answer(store, records, acme, q, DateAnswer(kind="date", date=date(2025, 8, 14)))
    answer(store, records, acme, q, DateAnswer(kind="date", date=date(2025, 9, 1)))
    assert row_named(store, acme, "taxi").tx.date == date(2025, 8, 14) and len(records.decisions(acme)) == 1
    answer(store, records, acme, q, NotSureAnswer(kind="not_sure"))
    assert records.question(q.id).status == "resolved" and records.question(q.id).answer == "14 Aug 2025"


def test_a_date_outside_the_books_is_refused_and_the_question_stays_open(store, records, acme):
    add_rows(store, acme, undated_taxi(), year_start=YEAR_1)
    [q] = refresh(store, records, acme)
    with pytest.raises(InvalidInput):
        answer(store, records, acme, q, DateAnswer(kind="date", date=date(2020, 1, 1)))
    assert records.question(q.id).status == "open" and records.decisions(acme) == []


def test_no_document_keeps_suspense_and_waits(store, records, acme):
    add_rows(store, acme, travel_line(), year_start=YEAR_1)
    [q] = refresh(store, records, acme)
    ledger_book.post(store, records, acme, YEAR_1)
    [waiting] = answer(store, records, acme, q, NoDocumentAnswer(kind="no_document"))
    assert (waiting.id, waiting.status, waiting.answer) == (q.id, "waiting", "I don't have it")
    assert [(x.id, x.status) for x in refresh(store, records, acme)] == [(q.id, "waiting")]   # still waiting
    tb = ledger_book.posted_trial_balance(store, records, acme, YEAR_1)
    assert net(tb, "9998") == D("240.00") and tb.suspense[0].needs == "receipt_or_invoice"
    [again] = answer(store, records, acme, q, NotSureAnswer(kind="not_sure"))
    assert (again.status, again.answer) == ("waiting", "Not sure")


def test_a_date_question_cannot_be_answered_with_no_document_nor_a_document_question_with_a_date(
        store, records, acme):
    add_rows(store, acme, undated_taxi(), travel_line(), year_start=YEAR_1)
    by_kind = {q.kind: q for q in refresh(store, records, acme)}
    with pytest.raises(InvalidInput):
        answer(store, records, acme, by_kind["date"], NoDocumentAnswer(kind="no_document"))
    with pytest.raises(InvalidInput):
        answer(store, records, acme, by_kind["receipt_or_invoice"], DateAnswer(kind="date", date=date(2025, 8, 1)))
    assert {q.status for q in records.questions(acme, YEAR_1)} == {"open"}


def test_an_agent_question_accepts_only_not_sure(store, records, acme):
    add_rows(store, acme, undated_taxi(), year_start=YEAR_1)
    [taxi] = refresh(store, records, acme)
    asked = questions.ask(records, client_id=acme, year_start=YEAR_1, row_ids=taxi.row_ids, text="Personal trip?",
                          why="It ends at a home address.")
    with pytest.raises(InvalidInput):
        answer(store, records, acme, asked, NoDocumentAnswer(kind="no_document"))
    with pytest.raises(InvalidInput):
        answer(store, records, acme, asked, DateAnswer(kind="date", date=date(2025, 8, 1)))
    assert records.question(asked.id).status == "open"
    answer(store, records, acme, asked, NotSureAnswer(kind="not_sure"))
    assert records.question(asked.id).status == "waiting"


def test_another_clients_or_unknown_question_is_not_found(store, records, acme):
    add_rows(store, acme, undated_taxi(), year_start=YEAR_1)
    [q] = refresh(store, records, acme)
    given = NotSureAnswer(kind="not_sure")
    with pytest.raises(NotFound):
        questions.answer(store, records, client_id=acme + 1, thread_id=None, question_id=q.id, answer=given)
    with pytest.raises(NotFound):
        questions.answer(store, records, client_id=acme, thread_id=None, question_id="nope", answer=given)


def test_uploaded_invoice_resolves_held_payment(store, records, acme):
    add_rows(store, acme, travel_line(), year_start=YEAR_1)
    [q] = refresh(store, records, acme)
    ledger_book.post(store, records, acme, YEAR_1)
    assert net(ledger_book.posted_trial_balance(store, records, acme, YEAR_1), "9998") == D("240.00")
    add_rows(store, acme, trainline_invoice(), year_start=YEAR_1)
    assert refresh(store, records, acme) == []
    done = records.question(q.id)
    assert done.status == "resolved" and done.resolved_at
    result = ledger_book.post(store, records, acme, YEAR_1)
    assert result.reversals_added == 2 and result.problems == []
    tb = ledger_book.posted_trial_balance(store, records, acme, YEAR_1)
    assert net(tb, "9998") == 0 and tb.suspense == []


def test_a_question_resolved_by_the_books_takes_the_file_that_settled_it_as_its_answer(store, records, acme):
    add_rows(store, acme, travel_line(), year_start=YEAR_1)
    [q] = refresh(store, records, acme)
    answer(store, records, acme, q, NoDocumentAnswer(kind="no_document"))
    assert records.question(q.id).answer == "I don't have it"
    add_rows(store, acme, trainline_invoice(), year_start=YEAR_1)
    assert refresh(store, records, acme) == []
    done = records.question(q.id)
    assert (done.status, done.answer) == ("resolved", "Matched to rows.csv") and done.resolved_at   # not "I don't have it"


def test_invoice_that_does_not_fit_stays_open(store, records, acme):
    # Another supplier's invoice for the same amount is not this payment's: the payment is still held.
    add_rows(store, acme, travel_line(), year_start=YEAR_1)
    [q] = refresh(store, records, acme)
    add_rows(store, acme, trainline_invoice(counterparty="Hotel Bristol", description="Rooms", document_ref="HB-1"),
             year_start=YEAR_1)
    assert [(x.id, x.status) for x in refresh(store, records, acme)] == [(q.id, "open")]
    ledger_book.post(store, records, acme, YEAR_1)
    assert net(ledger_book.posted_trial_balance(store, records, acme, YEAR_1), "9998") == D("240.00")


def test_a_receipt_for_a_payment_over_250_is_not_enough(store, records, acme):
    # The receipt pays the bank line and shows VAT, but only a full VAT invoice will do to reclaim it: the question
    # moves to the receipt. (A fare, or a receipt showing no VAT, has none to reclaim and is booked whole.)
    add_rows(store, acme, travel_line(gross=D("300.00"), account_code="7504", counterparty="Currys",
                                      description="CURRYS"), year_start=YEAR_1)
    [q] = refresh(store, records, acme)
    add_rows(store, acme, row(date=date(2025, 7, 1), gross=D("300.00"), vat=D("50.00"), account_code="7504",
                              counterparty="Currys", description="Printer", document_ref="R-1"), year_start=YEAR_1)
    [now] = refresh(store, records, acme)
    assert now.kind == "vat_invoice" and now.id != q.id and records.question(q.id).status == "resolved"


def test_a_receipt_showing_no_vat_settles_a_payment_over_250(store, records, acme):
    # No VAT on the receipt, so no VAT invoice would add anything: the receipt is the record of the cost.
    add_rows(store, acme, travel_line(gross=D("300.00"), account_code="7504", counterparty="Currys",
                                      description="CURRYS"), year_start=YEAR_1)
    [q] = refresh(store, records, acme)
    add_rows(store, acme, row(date=date(2025, 7, 1), gross=D("300.00"), account_code="7504", counterparty="Currys",
                              description="Printer", document_ref="R-1"), year_start=YEAR_1)
    assert refresh(store, records, acme) == [] and records.question(q.id).status == "resolved"


def test_a_question_comes_back_when_the_document_is_taken_away(store, records, acme):
    add_rows(store, acme, travel_line(), year_start=YEAR_1)
    [q] = refresh(store, records, acme)
    upload_id = add_rows(store, acme, trainline_invoice(), year_start=YEAR_1)
    assert refresh(store, records, acme) == []
    store.delete_upload(acme, upload_id)
    [back] = refresh(store, records, acme)
    assert (back.id, back.status, back.resolved_at) == (q.id, "open", None)


def test_a_receipt_edited_to_over_250_asks_for_a_vat_invoice_and_back(store, records, acme):
    add_rows(store, acme, row(date=date(2025, 8, 1), gross=D("100.00"), vat=D("16.67"), account_code="7504",
                              counterparty="Staples", description="Printer paper"), year_start=YEAR_1)
    assert refresh(store, records, acme) == []
    rid = store.rows(acme)[0].id
    store.patch_row(acme, rid, {"gross": "300.00"})
    [q] = refresh(store, records, acme)
    assert (q.kind, q.row_ids) == ("vat_invoice", [rid]) and "Over £250" in q.why
    store.patch_row(acme, rid, {"gross": "100.00"})
    assert refresh(store, records, acme) == [] and records.question(q.id).status == "resolved"


@pytest.mark.parametrize("order", [(YEAR_1, YEAR_2), (YEAR_2, YEAR_1)])
def test_a_held_line_moved_to_the_next_year_is_asked_there_only(store, records, acme, order):
    add_rows(store, acme, travel_line(), year_start=YEAR_1)
    [q] = refresh(store, records, acme)
    store.patch_row(acme, store.rows(acme)[0].id, {"date": "2026-05-01"})
    for year in (*order, *order):
        questions.refresh(store, records, acme, year)
    assert records.questions(acme, YEAR_1) == []
    [there] = records.questions(acme, YEAR_2)
    assert (there.id, there.status, there.year_start) == (q.id, "open", YEAR_2)
    assert "on 1 May 2026" in there.why


def test_a_held_receipt_patched_to_a_statement_line_is_asked_for_the_other_document(store, records, acme):
    add_rows(store, acme, row(date=date(2025, 8, 1), gross=D("300.00"), vat=D("50.00"), account_code="7504",
                              counterparty="Staples", description="Printer"), year_start=YEAR_1)
    [q] = refresh(store, records, acme)
    assert q.kind == "vat_invoice"
    store.patch_row(acme, store.rows(acme)[0].id, {"document_type": "statement", "gross": "240.00"})
    [again] = refresh(store, records, acme)
    assert (again.id, again.kind, again.text) == (q.id, "receipt_or_invoice", "Can you upload the receipt or invoice?")
    assert "£50 or more" in again.why


def test_ask_creates_an_agent_question_that_refresh_leaves_alone(store, records, acme):
    add_rows(store, acme, undated_taxi(), year_start=YEAR_1)
    [taxi] = refresh(store, records, acme)
    rid = taxi.row_ids[0]
    asked = questions.ask(records, client_id=acme, year_start=YEAR_1, row_ids=[rid], text="Was this a personal trip?",
                          why="The taxi ride ends at a home address.")
    assert (asked.kind, asked.source, asked.status, asked.row_ids) == ("other", "agent", "open", [rid])
    again = questions.ask(records, client_id=acme, year_start=YEAR_1, row_ids=[rid], text="Was this a personal trip?",
                          why="The ride ends at a home address.")
    assert again.id == asked.id and again.why == "The ride ends at a home address."
    answer(store, records, acme, taxi, DateAnswer(kind="date", date=date(2025, 8, 14)))   # the rule question goes
    assert [q.id for q in refresh(store, records, acme)] == [asked.id]
    [still] = answer(store, records, acme, asked, NotSureAnswer(kind="not_sure"))
    assert (still.id, still.status) == (asked.id, "waiting")
    assert [q.id for q in refresh(store, records, acme)] == [asked.id]


def test_an_answer_change_records_the_answer_and_a_repeated_one_records_nothing(store, records, acme):
    add_rows(store, acme, travel_line(), undated_taxi(), year_start=YEAR_1)
    by_kind = {q.kind: q for q in refresh(store, records, acme)}
    answer(store, records, acme, by_kind["date"], DateAnswer(kind="date", date=date(2025, 8, 14)))
    for _ in range(2):
        answer(store, records, acme, by_kind["receipt_or_invoice"], NoDocumentAnswer(kind="no_document"))

    made = [c for c in records.changes(acme) if c.kind == "question_answered"]

    assert [c.after for c in made] == [{"answer": "14 Aug 2025"}, {"answer": "I don't have it"}]


# ─── Closing the agent's own question ──────────────────────────────────────────

from ledgersync.models import Evidence, QuestionDraft  # noqa: E402
from test_resolutions import nb, pages  # noqa: E402,F401


def close_args(records, nb, pages, q, *quotes, **kw):
    uid = nb.upload("costco.txt")
    return dict(client_id=nb.id, year_start=date(2026, 4, 1), question_id=q.id, reason="The receipt says so.", actor="agent:test",
                trigger="background", review_id="r1", texts=lambda n: pages.get(n, []),
                evidence=[Evidence(upload_id=uid, quote=t) for t in quotes], **kw)


def test_a_question_is_closed_by_a_quote_from_its_rows_document(store, records, pages, nb):
    q = questions.ask(records, client_id=nb.id, year_start=date(2026, 4, 1), row_ids=[nb.receipt],
                      text="Is the paper for the office?", why="Unclear.")
    d = questions.close(store, records, **close_args(records, nb, pages, q, "Printer paper        52.80"))
    assert (d.status, d.action, d.trigger, d.review_id) == ("applied", "close_question", "background", "r1")
    assert d.evidence[0].upload_name == "costco.txt"
    assert records.question(q.id).answer == "Closed by the AI: The receipt says so."
    again = questions.close(store, records, **close_args(records, nb, pages, q, "Printer paper        52.80"))
    assert again.id == d.id   # asked again, the same decision


def test_a_suggested_closing_leaves_the_question_open_and_a_rule_question_cannot_be_closed(store, records, pages, nb):
    q = questions.ask(records, client_id=nb.id, year_start=date(2026, 4, 1), row_ids=[nb.receipt],
                      text="Is the paper for the office?", why="Unclear.")
    d = questions.close(store, records, **close_args(records, nb, pages, q, "Printer paper        52.80",
                                                     suggest=True))
    assert d.status == "suggested" and records.question(q.id).status == "open"
    assert not [c for c in records.changes(nb.id) if c.kind == "question_closed"]
    rule = records.upsert_question(QuestionDraft(client_id=nb.id, year_start=date(2026, 4, 1), row_ids=[nb.receipt],
                                                 kind="date", text="When?", why="No date.", source="rules"), "k")
    with pytest.raises(InvalidInput):
        questions.close(store, records, **close_args(records, nb, pages, rule, "Printer paper        52.80"))


def test_a_question_of_another_year_cannot_be_closed(store, records, pages, nb):
    q = questions.ask(records, client_id=nb.id, year_start=date(2026, 4, 1), row_ids=[nb.receipt], text="Q?", why="?")
    args = close_args(records, nb, pages, q, "Printer paper        52.80")
    args["year_start"] = date(2025, 4, 1)
    with pytest.raises(InvalidInput, match="That question belongs to another year."):
        questions.close(store, records, **args)
    assert records.question(q.id).status == "open"


def test_an_answer_outside_a_chat_makes_the_client_due_and_one_in_a_chat_does_not(store, records, acme):
    from datetime import datetime, timezone
    add_rows(store, acme, undated_taxi(), year_start=YEAR_1)
    [q] = refresh(store, records, acme)
    questions.answer(store, records, client_id=acme, thread_id="t1", question_id=q.id,
                     answer=DateAnswer(kind="date", date=date(2025, 8, 14)))
    assert records.review_state(acme).due_at is None   # the chat's agent handles it

    add_rows(store, acme, undated_taxi(description="taxi 2"), year_start=YEAR_1)
    [q2] = [x for x in refresh(store, records, acme) if x.id != q.id]
    at = datetime(2026, 11, 4, 10, 0, tzinfo=timezone.utc)
    questions.answer(store, records, client_id=acme, thread_id=None, question_id=q2.id,
                     answer=DateAnswer(kind="date", date=date(2025, 8, 15)), now=at, wait=30)
    assert records.review_state(acme).due_at == "2026-11-04T10:00:30+00:00"


def test_a_payout_with_no_report_asks_for_it(store, records, acme):
    add_rows(store, acme, row(date=date(2025, 10, 15), direction="in", gross=D("1163.10"), account_code="1250",
                              document_type="statement", counterparty="Stripe Payments UK"), year_start=YEAR_1)
    [q] = refresh(store, records, acme)
    assert (q.kind, q.source, q.text) == ("payout_report", "rules", "Can you upload the Stripe payout report?")
    assert q.why == ("£1,163.10 paid out by Stripe Payments UK on 15 Oct 2025 is sales less Stripe's fees and "
                     "refunds. Held in Payment Processor Clearing until the report shows each.")


def test_a_payment_of_paye_with_no_payroll_report_asks_for_it(store, records, acme):
    add_rows(store, acme, row(date=date(2025, 10, 25), gross=D("612.40"), account_code="2210",
                              document_type="statement", counterparty="HMRC PAYE"), year_start=YEAR_1)
    [q] = refresh(store, records, acme)
    assert (q.kind, q.text) == ("payroll_report", "Can you upload the payroll report for October 2025?")
    assert q.why == ("£612.40 paid to HMRC PAYE on 25 Oct 2025, and no payroll report books the wages it is for.")
    left = answer(store, records, acme, q, NoDocumentAnswer(kind="no_document"))
    assert [(x.id, x.status) for x in left] == [(q.id, "waiting")]


def test_a_person_can_book_a_purchase_without_the_document_it_needs(store, records, acme):
    add_rows(store, acme, travel_line(), year_start=YEAR_1)
    [q] = refresh(store, records, acme)
    left = answer(store, records, acme, q, WithoutDocumentAnswer(kind="without_document",
                                                                  reason="Tickets bought online; no invoice"))
    assert left == []
    closed = records.question(q.id)
    assert (closed.status, closed.answer) == ("resolved", "Booked without a receipt: Tickets bought online; no invoice")
    assert row_named(store, acme, "TRAINLINE").tx.without_document == "Tickets bought online; no invoice"
    tb = ledger_book.posted_trial_balance(store, records, acme, YEAR_1)
    assert net(tb, "9998") == D("0.00") and net(tb, "7400") == D("240.00") and tb.suspense == []
    assert refresh(store, records, acme) == []   # it stays closed


def test_booking_without_a_document_needs_a_reason_and_a_document_question(store, records, acme):
    add_rows(store, acme, travel_line(), undated_taxi(), year_start=YEAR_1)
    by_kind = {q.kind: q for q in refresh(store, records, acme)}
    with pytest.raises(InvalidInput):
        answer(store, records, acme, by_kind["receipt_or_invoice"],
               WithoutDocumentAnswer(kind="without_document", reason="  "))
    with pytest.raises(InvalidInput):
        answer(store, records, acme, by_kind["date"], WithoutDocumentAnswer(kind="without_document", reason="Lost"))


# ─── The agent's questions go when the books answer them ───────────────────────

def person_changed(records, client_id, row_id, kind="row_edited"):
    """A person's change to a row, as the API records it."""
    from ledgersync.models import ChangeDraft
    records.add_change(ChangeDraft(client_id=client_id, year_start=YEAR_1, actor="user", kind=kind, row_ids=[row_id],
                                   summary=f"Row {row_id} changed: account_code"))


def asked_about(store, records, client_id, *rows):
    ids = [r.id for r in store.rows(client_id)][-len(rows):] if rows else []
    return questions.ask(records, client_id=client_id, year_start=YEAR_1, row_ids=ids,
                         text="Which account should this go to?", why="Its account is unclear.")


def test_an_agent_question_goes_once_a_person_changes_its_row(store, records, acme):
    add_rows(store, acme, travel_line(gross=D("12.00")), year_start=YEAR_1)
    asked = asked_about(store, records, acme, "the line")
    assert [q.id for q in refresh(store, records, acme)] == [asked.id]   # nothing has changed: it stays
    import time
    time.sleep(1.1)   # times are kept to the second
    person_changed(records, acme, asked.row_ids[0])
    assert refresh(store, records, acme) == []
    closed = records.question(asked.id)
    assert closed.status == "resolved" and closed.answer == "You changed this row after it was asked."
    assert records.changes(acme)[-1].kind == "question_closed"


def test_an_agent_question_goes_once_its_rows_are_removed(store, records, acme):
    add_rows(store, acme, travel_line(gross=D("12.00")), year_start=YEAR_1)
    asked = asked_about(store, records, acme, "the line")
    store.delete_row(acme, asked.row_ids[0])
    assert refresh(store, records, acme) == []
    assert records.question(asked.id).answer == "Its row is no longer in the books."


def test_an_agent_question_asked_after_the_change_stays(store, records, acme):
    add_rows(store, acme, travel_line(gross=D("12.00")), year_start=YEAR_1)
    [line] = store.rows(acme)
    person_changed(records, acme, line.id)
    import time
    time.sleep(1.1)   # times are kept to the second
    asked = asked_about(store, records, acme, "the line")
    assert [q.id for q in refresh(store, records, acme)] == [asked.id]


def test_an_agent_question_about_rows_a_person_said_are_not_the_same_goes_however_early_they_said_it(
        store, records, acme):
    # Jenny's two £3.99 Victoria Food receipts: she pressed Not the same at 15:02:30, and a review that had read the
    # books at 15:02:23 asked at 15:03:16 whether they were one purchase. Her answer came first, so it was never seen.
    import time
    add_rows(store, acme, travel_line(gross=D("3.99")), travel_line(gross=D("3.99"), description="Again"),
             year_start=YEAR_1)
    first, second = store.rows(acme)
    store.patch_row(acme, second.id, {"apart_from": [first.id]})
    person_changed(records, acme, second.id, kind="rows_apart")
    time.sleep(1.1)   # times are kept to the second
    asked = questions.ask(records, client_id=acme, year_start=YEAR_1, row_ids=[second.id, first.id],
                          text="Were these two separate purchases?", why="Same shop and amount a day apart.")
    assert refresh(store, records, acme) == []
    assert records.question(asked.id).answer == "You said these are not the same."


def test_an_agent_question_about_one_of_two_rows_set_apart_stays(store, records, acme):
    # Not the same answers whether two rows are one, not every question about one of them.
    add_rows(store, acme, travel_line(gross=D("3.99")), travel_line(gross=D("3.99"), description="Again"),
             year_start=YEAR_1)
    first, second = store.rows(acme)
    store.patch_row(acme, second.id, {"apart_from": [first.id]})
    asked = questions.ask(records, client_id=acme, year_start=YEAR_1, row_ids=[second.id],
                          text="Which account should this go to?", why="Its account is unclear.")
    assert [q.id for q in refresh(store, records, acme)] == [asked.id]


def test_an_agent_question_about_no_row_stays(store, records, acme):
    add_rows(store, acme, travel_line(gross=D("12.00")), year_start=YEAR_1)
    asked = asked_about(store, records, acme)
    person_changed(records, acme, store.rows(acme)[0].id)
    assert [q.id for q in refresh(store, records, acme)] == [asked.id]


def test_the_answered_questions_of_every_year_are_closed_for_a_page_that_lists_them(store, records, acme):
    add_rows(store, acme, travel_line(gross=D("12.00")), year_start=YEAR_1)
    asked = asked_about(store, records, acme, "the line")
    questions.close_answered(store, records, acme)
    assert [q.id for q in records.questions(acme, None)] == [asked.id]   # nothing has changed: it stays
    store.delete_row(acme, asked.row_ids[0])
    questions.close_answered(store, records, acme)
    assert records.questions(acme, None) == []


def test_an_agent_question_about_a_claim_line_goes_once_a_person_changes_its_receipt(store, records, acme):
    import time
    add_rows(store, acme, row(date=date(2025, 7, 1), gross=D("255.98"), vat=D("42.66"), account_code="7402",
                              document_type="expense_claim", counterparty="Mark McNee", description="Mark McNee - hotel",
                              document_ref="claim"), year_start=YEAR_1)
    add_rows(store, acme, row(date=date(2025, 7, 1), gross=D("255.98"), account_code="7402", description="Hotel stay",
                              counterparty="Booking.com", document_ref="stay"), year_start=YEAR_1)
    line, receipt = store.rows(acme)
    assert next(t for t in books.ledger(store, acme, YEAR_1).transactions if t.id == line.id).recorded_by.ref == "stay"
    asked = questions.ask(records, client_id=acme, year_start=YEAR_1, row_ids=[line.id],
                          text="Book it with no VAT, as the receipt shows?", why="The receipt prints no VAT.")
    time.sleep(1.1)   # times are kept to the second
    person_changed(records, acme, receipt.id)   # the person settles it on the receipt, the other record of the pair
    assert asked.id not in [q.id for q in refresh(store, records, acme)]
    assert records.question(asked.id).answer == "You changed this row after it was asked."


def test_an_agent_question_goes_once_the_lines_it_waited_for_pair_with_its_rows(store, records, acme):
    # The agency's April 2023 receipts: asked whether the card paid them, as no card statement was in yet. The card
    # statement came in the next batch and every receipt paired with its card line, but the question stayed open all
    # year (agency run, 25 Nov 2026).
    import time
    add_rows(store, acme, trainline_invoice(), year_start=YEAR_1)
    [invoice] = store.rows(acme)
    asked = questions.ask(records, client_id=acme, year_start=YEAR_1, row_ids=[invoice.id],
                          text="Was this paid by the company card?", why="No statement shows it yet.")
    time.sleep(1.1)   # times are kept to the second
    add_rows(store, acme, travel_line(), year_start=YEAR_1)
    assert asked.id not in [q.id for q in refresh(store, records, acme)]
    assert records.question(asked.id).answer == questions.PAIRED_SINCE


def test_an_agent_question_about_rows_already_paired_when_asked_stays(store, records, acme):
    add_rows(store, acme, trainline_invoice(), year_start=YEAR_1)
    add_rows(store, acme, travel_line(), year_start=YEAR_1)
    import time
    time.sleep(1.1)
    invoice, line = store.rows(acme)
    asked = questions.ask(records, client_id=acme, year_start=YEAR_1, row_ids=[invoice.id, line.id],
                          text="Is this the right invoice for the payment?", why="Two bills of this amount.")
    assert asked.id in [q.id for q in refresh(store, records, acme)]


# ─── Opening prepayments and accruals ─────────────────────────────────────────

from ledgersync.models import OpeningBalances, OpeningLine  # noqa: E402
from ledgersync.questions import SplitAnswer, SplitLine  # noqa: E402


def opened_with_prepayments_and_an_accrual(store, client_id):
    # The test books' agency year: £6,558.46 prepaid (rent and insurance) and £2,400 of accountancy accrued, from the
    # previous accountant's trial balance; the app never released them, so rent and insurance were short and
    # accountancy booked twice.
    books.set_opening(store, client_id, OpeningBalances(lines=[
        OpeningLine(code="1200", debit=D("10000.00")), OpeningLine(code="1103", debit=D("6558.46")),
        OpeningLine(code="2109", credit=D("2400.00")), OpeningLine(code="3200", credit=D("14158.46"))]))


def opening_question(store, records, client_id, kind):
    return next(q for q in refresh(store, records, client_id) if q.kind == kind)


def test_opening_prepayments_and_accruals_ask_which_costs_they_are_for(store, records, acme):
    opened_with_prepayments_and_an_accrual(store, acme)
    asked = {q.kind: q for q in refresh(store, records, acme) if q.kind.startswith("opening_")}
    assert set(asked) == {"opening_prepayments", "opening_accruals"}
    assert asked["opening_prepayments"].text == "Opening prepayments of £6,558.46: which costs are they for?"
    assert asked["opening_accruals"].text == "Opening accruals of £2,400.00: which costs are they for?"
    assert asked["opening_prepayments"].row_ids == []


def test_the_split_answer_releases_them_on_the_first_day(store, records, acme):
    opened_with_prepayments_and_an_accrual(store, acme)
    q = opening_question(store, records, acme, "opening_prepayments")
    left = answer(store, records, acme, q, SplitAnswer(kind="split", lines=[
        SplitLine(account="8204", amount=D("1020.00")), SplitLine(account="7100", amount=D("5538.46"))]))
    assert "opening_prepayments" not in {x.kind for x in left}
    a = opening_question(store, records, acme, "opening_accruals")
    answer(store, records, acme, a, SplitAnswer(kind="split", lines=[SplitLine(account="7601", amount=D("2400.00"))]))
    tb = books.trial_balance(store, acme, YEAR_1)
    assert (net(tb, "1103"), net(tb, "2109"), net(tb, "7100"), net(tb, "8204"), net(tb, "7601")) == (
        0, 0, D("5538.46"), D("1020.00"), D("-2400.00"))
    journals = [r.tx for r in store.rows(acme) if r.tx.document_type == "journal"]
    assert {j.date for j in journals} == {YEAR_1} and len(journals) == 3
    assert not [q for q in refresh(store, records, acme) if q.kind.startswith("opening_")]


def test_a_split_that_does_not_add_up_is_refused(store, records, acme):
    opened_with_prepayments_and_an_accrual(store, acme)
    q = opening_question(store, records, acme, "opening_prepayments")
    with pytest.raises(InvalidInput, match="add up to £1,020.00.*£6,558.46"):
        answer(store, records, acme, q, SplitAnswer(kind="split", lines=[SplitLine(account="8204", amount=D("1020.00"))]))
    with pytest.raises(InvalidInput):
        answer(store, records, acme, q, SplitAnswer(kind="split", lines=[SplitLine(account="1103", amount=D("6558.46"))]))
    assert not [r for r in store.rows(acme) if r.tx.document_type == "journal"]


def test_journals_a_person_enters_by_hand_settle_the_question(store, records, acme):
    opened_with_prepayments_and_an_accrual(store, acme)
    add_rows(store, acme, row(date=YEAR_1, gross=D("6558.46"), account_code="7100", contra_account_code="1103",
                              document_type="journal", description="Prepayments released"))
    kinds = {q.kind for q in refresh(store, records, acme)}
    assert "opening_prepayments" not in kinds and "opening_accruals" in kinds


# ─── Bad debts ────────────────────────────────────────────────────────────────

from ledgersync.questions import WriteOffAnswer  # noqa: E402


def unpaid_sale(store, client_id):
    add_rows(store, client_id, row(date=date(2025, 5, 1), direction="in", gross=D("4800.00"), vat=D("800.00"),
                                   account_code="4000", document_type="invoice", document_ref="KF-1017",
                                   document_number="KF-1017", counterparty="Lowther Interiors Ltd",
                                   description="Showroom website build"),
             bank_line(date(2026, 3, 31)))


def bank_line(day):
    """A bank charge on the statement: the books' statements reach that day."""
    return row(date=day, gross=D("5.00"), account_code="7901", document_type="statement", description="Charges")


def debt_question(store, records, client_id):
    return next(q for q in refresh(store, records, client_id) if q.kind == "bad_debt")


def test_an_invoice_six_months_overdue_asks_to_be_written_off(store, records, acme):
    unpaid_sale(store, acme)
    q = debt_question(store, records, acme)
    assert q.text == "Write off the £4,800.00 Lowther Interiors Ltd owes as a bad debt?"
    assert "VAT bad debt relief" in q.why and len(q.row_ids) == 1


def test_writing_it_off_settles_it_and_claims_the_relief_in_that_quarter(store, records, acme):
    unpaid_sale(store, acme)
    q = debt_question(store, records, acme)
    left = answer(store, records, acme, q, WriteOffAnswer(kind="write_off", date=date(2026, 1, 31)))
    assert "bad_debt" not in {x.kind for x in left}
    tb = books.trial_balance(store, acme, YEAR_1)
    assert (net(tb, "8100"), net(tb, "1100"), net(tb, "4000")) == (D("4000.00"), 0, D("-4000.00"))
    assert books.vat_figures(store, acme, YEAR_1, date(2025, 12, 1), date(2026, 2, 28)).box4 == D("800.00")


def test_a_write_off_date_outside_the_year_or_before_the_six_months_is_refused(store, records, acme):
    unpaid_sale(store, acme)
    q = debt_question(store, records, acme)
    for day in (date(2026, 5, 1), date(2025, 9, 1)):
        with pytest.raises(InvalidInput):
            answer(store, records, acme, q, WriteOffAnswer(kind="write_off", date=day))
    assert not [r for r in store.rows(acme) if r.tx.document_type == "write_off"]


def test_removing_the_write_off_asks_again(store, records, acme):
    from ledgersync import ledger
    unpaid_sale(store, acme)
    answer(store, records, acme, debt_question(store, records, acme), WriteOffAnswer(kind="write_off"))
    [off] = [r for r in store.rows(acme) if r.tx.document_type == "write_off"]
    assert off.tx.date == date(2026, 3, 31)   # by default today, kept in the year: a past year's end
    ledger.remove_row(store, acme, off.id)
    assert debt_question(store, records, acme).status == "open"


def test_an_invoice_overdue_only_in_the_next_year_is_asked_about_there(store, records, acme):
    # Review: an invoice of February whose six months end after the year was never asked about in either year.
    add_rows(store, acme, row(date=date(2026, 2, 1), direction="in", gross=D("1200.00"), vat=D("200.00"),
                              account_code="4000", document_type="invoice", document_ref="KF-2001",
                              counterparty="Brightline Print Ltd", description="Brochure design"),
             bank_line(date(2026, 3, 31)), bank_line(date(2026, 9, 30)))   # the second year
    assert not [q for q in refresh(store, records, acme) if q.kind == "bad_debt"]
    [q] = [q for q in questions.refresh(store, records, acme, YEAR_2) if q.kind == "bad_debt"]
    questions.answer(store, records, client_id=acme, thread_id="t1", question_id=q.id,
                     answer=WriteOffAnswer(kind="write_off", date=date(2026, 9, 30)))
    assert net(books.trial_balance(store, acme, YEAR_2), "8100") == D("1000.00")


def test_an_invoice_whose_payment_may_be_on_a_statement_not_yet_in_is_not_asked_about(store, records, acme):
    # The agency run: invoices of April asked to be written off in May, before the statements that paid them came.
    add_rows(store, acme, row(date=date(2025, 5, 1), direction="in", gross=D("4800.00"), vat=D("800.00"),
                              account_code="4000", document_type="invoice", document_ref="KF-1017",
                              counterparty="Northgate Dental Group", description="Retainer"),
             bank_line(date(2025, 11, 29)))   # six months past due is 30 Nov 2025: the statements stop before it
    assert not [q for q in refresh(store, records, acme) if q.kind == "bad_debt"]
    add_rows(store, acme, bank_line(date(2025, 11, 30)))
    assert [q.kind for q in refresh(store, records, acme) if q.kind == "bad_debt"] == ["bad_debt"]


def test_without_a_bank_statement_no_invoice_is_asked_about(store, records, acme):
    add_rows(store, acme, row(date=date(2025, 5, 1), direction="in", gross=D("4800.00"), vat=D("800.00"),
                              account_code="4000", document_type="invoice", document_ref="KF-1017",
                              counterparty="Lowther Interiors Ltd", description="Showroom website build"))
    assert not [q for q in refresh(store, records, acme) if q.kind == "bad_debt"]


def test_a_question_about_an_earlier_year_stays_in_that_year_when_a_later_year_is_worked_out(store, records, acme):
    # The paid run of 25 Nov 2026: once the later years were settled too, the opening prepayments and accruals
    # questions moved to the year starting 1 Apr 2026 ("released on 1 Apr 2026"), and Lowther's bad debt to the year
    # after it fell overdue: one key per client, so the last year worked out took the question.
    opened_with_prepayments_and_an_accrual(store, acme)
    unpaid_sale(store, acme)
    refresh(store, records, acme)
    later = questions.refresh(store, records, acme, YEAR_2)
    assert not {q.kind for q in later} & {"opening_prepayments", "opening_accruals", "bad_debt"}
    kept = {q.kind: q for q in records.questions(acme, None)}
    for kind in ("opening_prepayments", "opening_accruals", "bad_debt"):
        assert kept[kind].year_start == YEAR_1, kind
    assert "released on 1 Apr 2025" in kept["opening_prepayments"].why


def test_a_supplier_credit_note_is_not_a_bad_debt(store, records, acme):
    add_rows(store, acme, row(date=date(2025, 5, 1), direction="in", gross=D("120.00"), account_code="7500",
                              document_type="invoice", document_ref="CN-1", counterparty="Paper Co",
                              description="Credit note"))
    assert not [q for q in refresh(store, records, acme) if q.kind == "bad_debt"]


# ─── A VAT payment that differs from the VAT owed when the year began ─────────

def opened_owing_vat(store, client_id, paid="27412.00"):
    books.set_opening(store, client_id, OpeningBalances(lines=[
        OpeningLine(code="1200", debit=D("30000.00")), OpeningLine(code="2202", credit=D("27100.00")),
        OpeningLine(code="3200", credit=D("2900.00"))]))
    add_rows(store, client_id, row(date=date(2025, 4, 13), gross=D(paid), account_code="2202",
                                   document_type="statement", counterparty="HMRC", description="HMRC VAT"))


def test_a_vat_payment_more_than_the_vat_owed_asks_what_the_difference_was(store, records, acme):
    # The test books' agency year (EC-0512): £27,412 paid for the £27,100 owed, never asked about.
    opened_owing_vat(store, acme)
    [q] = [q for q in refresh(store, records, acme) if q.kind == "opening_vat"]
    assert q.text == ("The VAT payment of £27,412.00 on 13 Apr 2025 is £312.00 more than the £27,100.00 owed when the "
                      "year began: what was the difference for?")
    answer(store, records, acme, q, SplitAnswer(kind="split", lines=[SplitLine(account="8250", amount=D("312.00"))]))
    tb = books.trial_balance(store, acme, YEAR_1)
    assert (net(tb, "2202"), net(tb, "8250")) == (0, D("312.00"))
    assert not [q for q in refresh(store, records, acme) if q.kind == "opening_vat"]


def test_a_vat_payment_of_what_was_owed_asks_nothing(store, records, acme):
    opened_owing_vat(store, acme, paid="27100.00")
    assert not [q for q in refresh(store, records, acme) if q.kind == "opening_vat"]


# ─── Answers the agent offers for the person to confirm (design of 2026-11-25) ──────────────────────────────

from ledgersync.models import Offer, OfferSource, QuestionDraft  # noqa: E402


def books_question(records, client_id, text="Opening prepayments of £6,558.46: which costs are they for?",
                   kind="opening_prepayments", year_start=YEAR_1):
    return records.upsert_question(QuestionDraft(client_id=client_id, year_start=year_start, kind=kind, text=text,
                                                 why="Carried in from last year.", source="rules"), f"open:{kind}")


def an_offer(thread_id="t1"):
    return Offer(answer={"kind": "split", "lines": [{"account": "7100", "amount": "5538.46"},
                                                     {"account": "8204", "amount": "1020.00"}]},
                 sources=[OfferSource(kind="said", quote="the rent and the insurance"),
                          OfferSource(kind="document", upload_id=1, quote="Rent, quarter to 23 June", **{"for": "line:1"},
                                      working="£6,000.00 for 91 days, 84 of them next year")],
                 reason="The client said they were the rent and the insurance.", thread_id=thread_id,
                 offered_at="2026-11-25T12:00:00+00:00", offered_by="agent:test")


def test_an_offer_is_kept_on_its_question_and_read_back(records, acme):
    q = books_question(records, acme)
    assert q.offer is None
    records.set_offer(q.id, an_offer())
    kept = records.question(q.id).offer
    assert kept == an_offer() and kept.sources[1].for_ == "line:1"
    assert kept.model_dump(mode="json", by_alias=True)["sources"][1]["for"] == "line:1"   # as the page reads it


def test_answering_or_waiting_clears_the_offer(records, acme):
    for status, said in (("resolved", "Released to 7100"), ("waiting", "Not sure")):
        q = books_question(records, acme, kind="opening_accruals" if status == "waiting" else "opening_prepayments")
        records.set_offer(q.id, an_offer())
        records.set_question(q.id, status, said)
        assert records.question(q.id).offer is None, status


def test_an_offer_goes_when_the_question_text_changes(records, acme):
    q = books_question(records, acme)
    records.set_offer(q.id, an_offer())
    assert books_question(records, acme).offer == an_offer()   # asked again in the same words: kept
    changed = books_question(records, acme, text="Opening prepayments of £6,000.00: which costs are they for?")
    assert changed.id == q.id and changed.offer is None
    records.set_offer(q.id, an_offer())
    records.clear_offer(q.id)
    assert records.question(q.id).offer is None


def _rows(store, client_id):
    return [(r.id, r.tx.model_dump_json()) for r in store.rows(client_id)]


def test_checking_an_answer_writes_nothing_and_says_what_would_be_refused(store, records, acme):
    opened_with_prepayments_and_an_accrual(store, acme)
    q = opening_question(store, records, acme, "opening_prepayments")
    before = _rows(store, acme)
    good = SplitAnswer(kind="split", lines=[SplitLine(account="7100", amount=D("5538.46")),
                                            SplitLine(account="8204", amount=D("1020.00"))])
    assert questions.check_answer(store, acme, q, good) is None
    short = SplitAnswer(kind="split", lines=[SplitLine(account="7100", amount=D("6000.00"))])
    assert questions.check_answer(store, acme, q, short) == (
        "The lines add up to £6,000.00; the opening prepayments still to release are £6,558.46.")
    assert _rows(store, acme) == before


def test_checking_a_vat_difference_answer_refuses_the_vat_liability(store, records, acme):
    opened_owing_vat(store, acme)
    [q] = [q for q in refresh(store, records, acme) if q.kind == "opening_vat"]
    to_vat = SplitAnswer(kind="split", lines=[SplitLine(account="2202", amount=D("312.00"))])
    assert questions.check_answer(store, acme, q, to_vat) == (
        "Choose an account for each line, not the VAT liability or a bank.")
    sundry = SplitAnswer(kind="split", lines=[SplitLine(account="8250", amount=D("312.00"))])
    assert questions.check_answer(store, acme, q, sundry) is None


def test_checking_a_write_off_refuses_a_date_before_the_six_months(store, records, acme):
    unpaid_sale(store, acme)
    q = debt_question(store, records, acme)
    before = _rows(store, acme)
    assert "six months after the invoice fell due" in questions.check_answer(
        store, acme, q, WriteOffAnswer(kind="write_off", date=date(2025, 9, 1)))
    assert questions.check_answer(store, acme, q, WriteOffAnswer(kind="write_off")) is None
    assert _rows(store, acme) == before


SAID = ["> Opening prepayments of £6,558.46: which costs are they for?\n\nThey were the rent and the insurance."]
RENT = "Harbourside Estates Ltd Rent, quarter 25 Mar to 23 Jun 2025 £6,000.00"


def offering(store, records, client_id, q, answer, sources, *, said=SAID, texts=None, upload=None):
    pages = {upload: [RENT]} if upload else {}
    return questions.offer(store, records, client_id=client_id, thread_id="t1", question_id=q.id, answer=answer,
                           sources=sources, reason="As the client said.", texts=texts or (lambda u: pages.get(u, [])),
                           said=said, actor="agent:test")


def two_lines():
    return SplitAnswer(kind="split", lines=[SplitLine(account="7100", amount=D("5538.46")),
                                            SplitLine(account="8204", amount=D("1020.00"))])


def rent_sources(upload):
    return [OfferSource(kind="said", quote="the rent and the insurance"),
            OfferSource(kind="document", upload_id=upload, quote="Rent, quarter 25 Mar to 23 Jun 2025", **{"for": "line:1"},
                        working="£6,000.00 for 91 days, 84 of them in this year"),
            OfferSource(kind="said", quote="the insurance", **{"for": "line:2"})]


@pytest.fixture
def prepaid(store, records, acme):
    opened_with_prepayments_and_an_accrual(store, acme)
    upload = add_rows(store, acme, row(date=date(2025, 3, 25), gross=D("6000.00"), account_code="7100",
                                       document_type="invoice", counterparty="Harbourside Estates Ltd",
                                       description="Rent", document_ref="he"), year_start=YEAR_1)
    return opening_question(store, records, acme, "opening_prepayments"), upload


def test_an_offer_backed_by_the_clients_words_and_a_document_is_kept(store, records, acme, prepaid):
    q, upload = prepaid
    made = offering(store, records, acme, q, two_lines(), rent_sources(upload), upload=upload)
    assert made.offer.answer["lines"][0] == {"account": "7100", "amount": "5538.46"}
    assert made.offer.thread_id == "t1" and made.offer.offered_by == "agent:test"
    assert records.changes(acme)[-1].kind == "question_offered"
    again = offering(store, records, acme, q, SplitAnswer(kind="split", lines=[
        SplitLine(account="7100", amount=D("6558.46"))]), [OfferSource(kind="said", quote="all of it was rent"),
                                                           OfferSource(kind="question")],
        said=["All of it was rent."])
    assert again.offer.answer["lines"] == [{"account": "7100", "amount": "6558.46"}]   # replaces the first


@pytest.mark.parametrize("case, why", [
    ("no_said", "needs the person's own words"),
    ("note_only", "isn't in what the person said"),
    ("bad_quote", "isn't in"),
    ("short_quote", "too short"),
    ("no_source", "line 2 has no source"),
    ("short_total", "The lines add up to £5,538.46"),
])
def test_an_offer_is_refused_without_what_backs_it(store, records, acme, prepaid, case, why):
    q, upload = prepaid
    answer, sources, said = two_lines(), rent_sources(upload), SAID
    if case == "no_said":
        sources = [s for s in sources if s.kind != "said"] + [OfferSource(kind="question")]
    elif case == "note_only":
        said = []   # the words are only in a note the app wrote: not the person's
    elif case == "bad_quote":
        sources[1] = sources[1].model_copy(update={"quote": "Rent for the whole of 2026"})
    elif case == "short_quote":
        sources[1] = sources[1].model_copy(update={"quote": "Re"})
    elif case == "no_source":
        sources = sources[:2]
    elif case == "short_total":
        answer = SplitAnswer(kind="split", lines=[SplitLine(account="7100", amount=D("5538.46"))])
    with pytest.raises(InvalidInput, match=why):
        offering(store, records, acme, q, answer, sources, said=said, upload=upload)
    assert records.question(q.id).offer is None


def test_only_an_open_books_question_of_the_four_kinds_takes_an_offer(store, records, acme, prepaid):
    q, upload = prepaid
    asked = questions.ask(records, client_id=acme, year_start=YEAR_1, row_ids=[], text="Which bank?", why="To know.")
    with pytest.raises(InvalidInput, match="isn't a books question that takes an answer"):
        offering(store, records, acme, asked, two_lines(), rent_sources(upload), upload=upload)
    records.set_question(q.id, "resolved", "Released")
    with pytest.raises(InvalidInput, match="already answered"):
        offering(store, records, acme, q, two_lines(), rent_sources(upload), upload=upload)


def test_the_vat_difference_offer_takes_its_amount_from_the_question(store, records, acme):
    # The agency's £312: the client's words say where it goes; the amount is the question's own.
    opened_owing_vat(store, acme)
    [q] = [q for q in refresh(store, records, acme) if q.kind == "opening_vat"]
    made = offering(store, records, acme, q, SplitAnswer(kind="split", lines=[SplitLine(account="8250", amount=D("312.00"))]),
                    [OfferSource(kind="said", quote="Fine to correct it this year"), OfferSource(kind="question")],
                    said=["Redland & Co say a February invoice was left off their VAT figure. Fine to correct it this year."])
    assert made.offer.answer["lines"] == [{"account": "8250", "amount": "312.00"}]


def test_the_questions_own_amount_backs_only_a_split_of_one_line(store, records, acme, prepaid):
    # Final review, 25 Nov 2026: one {kind: question} source made every line "sourced", so an invented split that
    # added up (£1.00 and £6,557.46) was offered with nothing beside either figure.
    q, upload = prepaid
    invented = SplitAnswer(kind="split", lines=[SplitLine(account="7100", amount=D("1.00")),
                                                SplitLine(account="8204", amount=D("6557.46"))])
    with pytest.raises(InvalidInput, match="line 1 has no source"):
        offering(store, records, acme, q, invented,
                 [OfferSource(kind="said", quote="the rent and the insurance"), OfferSource(kind="question")])
    whole = SplitAnswer(kind="split", lines=[SplitLine(account="7100", amount=D("6558.46"))])
    assert offering(store, records, acme, q, whole, [OfferSource(kind="said", quote="the rent and the insurance"),
                                                     OfferSource(kind="question")]).offer is not None


def test_a_document_quote_must_name_a_line_or_the_date_it_backs(store, records, acme, prepaid):
    q, upload = prepaid
    for wrong in ("line:7", None):
        sources = rent_sources(upload)
        sources[1] = sources[1].model_copy(update={"for_": wrong})
        with pytest.raises(InvalidInput, match="names no line"):
            offering(store, records, acme, q, two_lines(), sources, upload=upload)


def test_the_persons_words_are_a_quote_of_four_characters_or_more(store, records, acme, prepaid):
    q, upload = prepaid
    sources = rent_sources(upload)
    sources[0] = OfferSource(kind="said", quote="e")
    with pytest.raises(InvalidInput, match="too short"):
        offering(store, records, acme, q, two_lines(), sources, upload=upload)
