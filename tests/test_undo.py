"""Suggesting, applying and undoing an AI decision, and never redoing what a person undid."""
import datetime as dt
from decimal import Decimal

import pytest

from ledgersync import ledger, ledger_book, undo
from ledgersync.agent.locks import ClientLocks
from ledgersync.errors import InvalidInput, YearClosed
from ledgersync.models import ChangeDraft, ClosedYear, RowPatch
from test_resolutions import (ACTOR, YEAR, call, costco_split, keep_receipt, nb, pages, records,  # noqa: F401
                              saved)

pytestmark = pytest.mark.mongo

QUOTE = "total   £64.80"


@pytest.fixture
def locks():
    return ClientLocks()


def lines(store, records, nb):
    return [(l.code, l.debit, l.credit) for l in ledger_book.posted_trial_balance(store, records, nb.id, YEAR).lines]


def suggest(store, records, pages, nb):
    return call(store, records, pages, nb, nb.sheet_costco, keep_receipt(nb), QUOTE, trigger="background",
                review_id="r1", suggest=True)


def apply(store, records, locks, pages, nb, decision):
    return undo.apply_suggestion(store, records, locks, client_id=nb.id, decision_id=decision.id,
                                 texts=lambda uid: pages.get(uid, []))


def test_a_suggested_resolution_changes_no_row_and_records_before_and_after(mongo_store, records, pages, nb):
    d = suggest(mongo_store, records, pages, nb)
    assert (d.status, d.trigger, d.review_id) == ("suggested", "background", "r1")
    assert d.before == {str(nb.sheet_costco): {"excluded": False}}
    assert d.after == {str(nb.sheet_costco): {"excluded": True}}
    assert d.resolution == keep_receipt(nb).model_dump(mode="json")
    assert not saved(mongo_store, nb.id, nb.sheet_costco).excluded
    assert saved(mongo_store, nb.id, nb.sheet_costco).decision_ids == []


def test_applying_a_suggestion_makes_the_change_as_the_person(mongo_store, records, locks, pages, nb):
    s = suggest(mongo_store, records, pages, nb)
    made = apply(mongo_store, records, locks, pages, nb, s)
    assert (made.status, made.actor, made.action) == ("applied", "user", "keep_one")
    assert made.id != s.id and made.review_id == "r1"
    assert saved(mongo_store, nb.id, nb.sheet_costco).excluded
    assert records.applied_suggestions(nb.id) == {s.id: made.id}
    assert records.decisions(nb.id)[0].status == "suggested"   # the suggestion itself is never changed
    with pytest.raises(InvalidInput, match="applied already"):
        apply(mongo_store, records, locks, pages, nb, s)


def test_only_a_suggestion_can_be_applied(mongo_store, records, locks, pages, nb):
    d = call(mongo_store, records, pages, nb, nb.sheet_costco, keep_receipt(nb), QUOTE)
    with pytest.raises(InvalidInput):
        apply(mongo_store, records, locks, pages, nb, d)


def test_a_background_resolution_on_a_row_a_person_changed_is_refused(mongo_store, records, pages, nb):
    ledger.change_row(mongo_store, nb.id, nb.sheet_costco, RowPatch(description="Costco stationery"))
    person_changed(records, nb, nb.sheet_costco, "row_edited")
    refused = call(mongo_store, records, pages, nb, nb.sheet_costco, keep_receipt(nb), QUOTE, trigger="background")
    assert refused.status == "refused"
    assert refused.reason == f"A person changed row {nb.sheet_costco}; a background review leaves it to them."
    assert call(mongo_store, records, pages, nb, nb.sheet_costco, keep_receipt(nb), QUOTE).status == "applied"


def test_undo_puts_the_rows_back_and_records_a_reversal(mongo_store, records, locks, pages, nb):
    from ledgersync import upkeep
    from ledgersync.models import ChangeDraft
    upkeep.after_change(mongo_store, records, locks, ChangeDraft(client_id=nb.id, actor="user", kind="row_edited",
                                                                 summary="x"), today=dt.date(2026, 12, 1))
    before_lines = lines(mongo_store, records, nb)
    before_row = saved(mongo_store, nb.id, nb.sheet_costco)
    d = call(mongo_store, records, pages, nb, nb.sheet_costco, keep_receipt(nb), QUOTE)
    upkeep.after_change(mongo_store, records, locks, ChangeDraft(client_id=nb.id, actor="user", kind="row_edited",
                                                                 summary="x"), today=dt.date(2026, 12, 1))
    assert lines(mongo_store, records, nb) != before_lines
    undone = undo.undo_decision(mongo_store, records, locks, client_id=nb.id, decision_id=d.id)
    assert (undone.action, undone.status, undone.reverses, undone.actor) == ("undo", "applied", d.id, "user")
    assert saved(mongo_store, nb.id, nb.sheet_costco).excluded == before_row.excluded
    assert lines(mongo_store, records, nb) == before_lines
    assert any(c.kind == "decision_undone" and c.after == {"decision_id": d.id} for c in records.changes(nb.id))
    with pytest.raises(InvalidInput, match="undone already"):
        undo.undo_decision(mongo_store, records, locks, client_id=nb.id, decision_id=d.id)


def test_undo_refuses_once_the_year_is_closed_and_changes_no_row(mongo_store, records, locks, pages, nb):
    d = call(mongo_store, records, pages, nb, nb.sheet_costco, keep_receipt(nb), QUOTE)
    assert d.status == "applied"
    mongo_store.close_year(nb.id, ClosedYear(start=YEAR, end=dt.date(2027, 3, 31), closed_at="2027-04-30T00:00:00",
                                             closing={}))
    rows = mongo_store.row_data(nb.id, [int(n) for n in d.before])
    with pytest.raises(YearClosed):
        undo.undo_decision(mongo_store, records, locks, client_id=nb.id, decision_id=d.id)
    assert mongo_store.row_data(nb.id, [int(n) for n in d.before]) == rows
    assert records.reversal_of(nb.id, d.id) is None


@pytest.mark.parametrize("trigger", ["chat", "background"])
def test_an_undone_change_is_refused_when_asked_again(mongo_store, records, locks, pages, nb, trigger):
    d = call(mongo_store, records, pages, nb, nb.sheet_costco, keep_receipt(nb), QUOTE)
    undo.undo_decision(mongo_store, records, locks, client_id=nb.id, decision_id=d.id)
    again = call(mongo_store, records, pages, nb, nb.sheet_costco, keep_receipt(nb), QUOTE, trigger=trigger)
    assert (again.status, again.reason) == ("refused", "A person undid this change.")
    assert not saved(mongo_store, nb.id, nb.sheet_costco).excluded


def test_undo_refuses_when_a_row_changed_since(mongo_store, records, locks, pages, nb):
    d = call(mongo_store, records, pages, nb, nb.sheet_costco, keep_receipt(nb), QUOTE)
    mongo_store.patch_row(nb.id, nb.sheet_costco, {"excluded": False})
    with pytest.raises(InvalidInput) as err:
        undo.undo_decision(mongo_store, records, locks, client_id=nb.id, decision_id=d.id)
    assert err.value.message == f"Row {nb.sheet_costco} has changed since; change it by hand instead."


def test_undoing_a_split_removes_its_parts(mongo_store, records, locks, pages, nb):
    d = call(mongo_store, records, pages, nb, nb.receipt, costco_split(), "Printer paper 52.80 A", "Biscuits 12.00 Z")
    assert d.status == "applied" and len(mongo_store.rows(nb.id)) == 6
    undo.undo_decision(mongo_store, records, locks, client_id=nb.id, decision_id=d.id)
    assert len(mongo_store.rows(nb.id)) == 4
    assert saved(mongo_store, nb.id, nb.receipt).superseded_by is None


def test_undo_refuses_a_decision_that_is_not_an_applied_one_of_the_client(mongo_store, records, locks, pages, nb):
    s = suggest(mongo_store, records, pages, nb)
    for bad in (s.id, "nope"):
        with pytest.raises(InvalidInput):
            undo.undo_decision(mongo_store, records, locks, client_id=nb.id, decision_id=bad)


def person_changed(records, nb, row_id, kind):
    records.add_change(ChangeDraft(client_id=nb.id, actor="user", kind=kind, row_ids=[row_id], summary="x"))


def test_a_row_the_ai_patched_is_not_a_persons(mongo_store, records, pages, nb):
    from ledgersync.resolutions import VatFromDocument
    first = call(mongo_store, records, pages, nb, nb.sheet_costco, keep_receipt(nb), QUOTE, trigger="background")
    assert first.status == "applied"
    assert saved(mongo_store, nb.id, nb.sheet_costco).excluded
    vat = VatFromDocument(action="set_vat_from_document", vat=Decimal("5.04"))
    patched = call(mongo_store, records, pages, nb, nb.invoice, vat, "VAT 5.04", upload=nb.upload("inkwell-invoice.pdf"),
                   trigger="background")
    assert patched.status == "applied", patched.reason   # edits the invoice's VAT: an editable field
    assert saved(mongo_store, nb.id, nb.invoice).decision_ids == [patched.id]
    split_after = call(mongo_store, records, pages, nb, nb.invoice, VatFromDocument(
        action="set_vat_from_document", vat=Decimal("5.03")), "VAT 5.04", upload=nb.upload("inkwell-invoice.pdf"),
        trigger="background")
    assert "A person changed" not in split_after.reason
    again = call(mongo_store, records, pages, nb, nb.sheet_costco, keep_receipt(nb), QUOTE, trigger="background")
    assert again.status == "applied"   # its own earlier change (same key) is returned, never a refusal


@pytest.mark.parametrize("kind", ["row_edited", "row_added", "row_linked", "rows_apart"])
def test_a_row_with_a_person_change_on_record_is_refused_to_the_background(mongo_store, records, pages, nb, kind):
    person_changed(records, nb, nb.sheet_costco, kind)
    refused = call(mongo_store, records, pages, nb, nb.sheet_costco, keep_receipt(nb), QUOTE, trigger="background")
    assert refused.status == "refused" and refused.reason.startswith(f"A person changed row {nb.sheet_costco};")


def rows_state(store, nb):
    return {r.id: r.tx.model_dump(mode="json") for r in store.rows(nb.id)}, len(store.uploads(nb.id))


@pytest.mark.parametrize("failing", ["delete_row", "append_decision", "reject_key"])
def test_a_failed_undo_of_a_split_leaves_everything_as_it_was(mongo_store, records, locks, pages, nb, monkeypatch,
                                                              failing):
    d = call(mongo_store, records, pages, nb, nb.receipt, costco_split(), "Printer paper 52.80 A", "Biscuits 12.00 Z")
    assert d.status == "applied"
    key = records.decision_key(nb.id, d.id)
    before = rows_state(mongo_store, nb)
    target, name = (mongo_store, "delete_row") if failing == "delete_row" else (records, failing)
    real = getattr(target, name)
    calls = []

    def boom(*a, **kw):
        calls.append(1)
        if failing != "delete_row" or len(calls) == 2:   # a split's second part: the first is already gone
            raise RuntimeError("down")
        return real(*a, **kw)

    monkeypatch.setattr(target, name, boom)
    with pytest.raises(RuntimeError):
        undo.undo_decision(mongo_store, records, locks, client_id=nb.id, decision_id=d.id)
    monkeypatch.undo()
    assert rows_state(mongo_store, nb) == before
    assert records.reversal_of(nb.id, d.id) is None
    assert not records.is_rejected(nb.id, key)
    undo.undo_decision(mongo_store, records, locks, client_id=nb.id, decision_id=d.id)   # and it still can be
    assert len(mongo_store.rows(nb.id)) == 4


def test_a_failed_undo_is_put_back_even_when_reading_the_record_fails_too(mongo_store, records, locks, pages, nb,
                                                                           monkeypatch):
    d = call(mongo_store, records, pages, nb, nb.receipt, costco_split(), "Printer paper 52.80 A", "Biscuits 12.00 Z")
    key = records.decision_key(nb.id, d.id)
    before = rows_state(mongo_store, nb)
    real = records.reversal_of
    reads = []

    def reversal_of(*a, **kw):
        reads.append(1)
        if len(reads) > 1:   # the pre-check answers; any read after the changes are made fails
            raise RuntimeError("read down")
        return real(*a, **kw)

    def append_down(*a, **kw):
        raise RuntimeError("write down")

    monkeypatch.setattr(records, "reversal_of", reversal_of)
    monkeypatch.setattr(records, "append_decision", append_down)
    with pytest.raises(RuntimeError, match="write down"):
        undo.undo_decision(mongo_store, records, locks, client_id=nb.id, decision_id=d.id)
    monkeypatch.undo()
    assert rows_state(mongo_store, nb) == before
    assert records.reversal_of(nb.id, d.id) is None
    assert not records.is_rejected(nb.id, key)


# ─── Undoing the AI's closing of a question ────────────────────────────────────

def closed_question(store, records, pages, nb):
    from ledgersync import questions
    from ledgersync.models import Evidence
    q = questions.ask(records, client_id=nb.id, year_start=YEAR, row_ids=[nb.receipt], text="For the office?", why="?")
    records.set_question(q.id, "waiting", "Not sure")
    d = questions.close(store, records, client_id=nb.id, year_start=YEAR, question_id=q.id, reason="Receipt.", actor=ACTOR,
                        trigger="background", review_id="r1", texts=lambda n: pages.get(n, []),
                        evidence=[Evidence(upload_id=nb.upload("costco.txt"), quote="Printer paper        52.80")])
    assert d.status == "applied" and records.question(q.id).status == "resolved"
    return q, d


def test_undoing_a_closed_question_reopens_it_to_its_old_status_and_the_ai_does_not_close_it_again(
        mongo_store, records, locks, pages, nb):
    q, d = closed_question(mongo_store, records, pages, nb)
    undone = undo.undo_decision(mongo_store, records, locks, client_id=nb.id, decision_id=d.id)
    assert (undone.action, undone.reverses, undone.before, undone.after) == (
        "undo", d.id, {"question": {"status": "resolved"}}, {"question": {"status": "waiting", "answer": "Not sure"}})
    assert records.question(q.id).status == "waiting"
    assert any(c.kind == "decision_undone" and c.after == {"decision_id": d.id} for c in records.changes(nb.id))
    from ledgersync import questions
    again = questions.close(mongo_store, records, client_id=nb.id, year_start=YEAR, question_id=q.id, reason="Receipt.", actor=ACTOR,
                            trigger="background", texts=lambda n: pages.get(n, []), evidence=d.evidence)
    assert (again.status, again.reason) == ("refused", "A person undid this change.")
    assert records.question(q.id).status == "waiting"


def test_a_failed_undo_of_a_closed_question_leaves_it_closed(mongo_store, records, locks, pages, nb, monkeypatch):
    q, d = closed_question(mongo_store, records, pages, nb)
    real = records.append_decision

    def fail(draft, key, id=None):
        if draft.action == "undo":
            raise RuntimeError("down")
        return real(draft, key, id)
    monkeypatch.setattr(records, "append_decision", fail)
    with pytest.raises(RuntimeError):
        undo.undo_decision(mongo_store, records, locks, client_id=nb.id, decision_id=d.id)
    assert records.question(q.id).status == "resolved"
    assert not records.is_rejected(nb.id, records.decision_key(nb.id, d.id))
    monkeypatch.undo()
    undo.undo_decision(mongo_store, records, locks, client_id=nb.id, decision_id=d.id)
    assert records.question(q.id).status == "waiting"


def test_undoing_a_closed_question_gives_back_its_earlier_answer(mongo_store, records, locks, pages, nb):
    q, d = closed_question(mongo_store, records, pages, nb)
    assert d.before == {"question": {"status": "waiting", "answer": "Not sure"}}
    undo.undo_decision(mongo_store, records, locks, client_id=nb.id, decision_id=d.id)
    back = records.question(q.id)
    assert (back.status, back.answer) == ("waiting", "Not sure")


def test_a_suggested_closing_is_applied_as_the_person_once(mongo_store, records, locks, pages, nb):
    from ledgersync import questions
    from ledgersync.models import Evidence
    q = questions.ask(records, client_id=nb.id, year_start=YEAR, row_ids=[nb.receipt], text="For the office?", why="?")
    s = questions.close(mongo_store, records, client_id=nb.id, year_start=YEAR, question_id=q.id, reason="Receipt.",
                        actor=ACTOR, trigger="background", review_id="r1", texts=lambda n: pages.get(n, []),
                        evidence=[Evidence(upload_id=nb.upload("costco.txt"), quote="Printer paper        52.80")],
                        suggest=True)
    assert s.status == "suggested" and s.resolution["action"] == "close_question"
    assert records.question(q.id).status == "open"
    made = apply(mongo_store, records, locks, pages, nb, s)
    assert (made.status, made.actor, made.action, made.review_id) == ("applied", "user", "close_question", "r1")
    assert made.id != s.id and records.question(q.id).status == "resolved"
    assert records.applied_suggestions(nb.id) == {s.id: made.id}
    assert any(c.kind == "decision_applied" and c.after == {"decision_id": s.id, "applied_as": made.id}
               for c in records.changes(nb.id))
    with pytest.raises(InvalidInput, match="applied already"):
        apply(mongo_store, records, locks, pages, nb, s)


def test_an_undo_makes_the_client_due_after_the_wait_it_is_given(mongo_store, records, locks, pages, nb):
    d = call(mongo_store, records, pages, nb, nb.sheet_costco, keep_receipt(nb), QUOTE)
    undo.undo_decision(mongo_store, records, locks, client_id=nb.id, decision_id=d.id, wait=777)
    due = dt.datetime.fromisoformat(records.review_state(nb.id).due_at)
    assert abs((due - dt.datetime.now(dt.timezone.utc)).total_seconds() - 777) < 60


def test_undo_refuses_a_row_a_person_removed_since(mongo_store, records, locks, pages, nb):
    # The AI left the sheet's line out, then a person removed it: undoing the AI's change would book a row the
    # person took out, and leave it marked removed with nothing to put back.
    d = call(mongo_store, records, pages, nb, nb.sheet_costco, keep_receipt(nb), QUOTE)
    mongo_store.patch_row(nb.id, nb.sheet_costco, {"excluded": True, "removed": True})
    with pytest.raises(InvalidInput) as err:
        undo.undo_decision(mongo_store, records, locks, client_id=nb.id, decision_id=d.id)
    assert f"Row {nb.sheet_costco} was removed by a person" in err.value.message
    assert saved(mongo_store, nb.id, nb.sheet_costco).excluded
