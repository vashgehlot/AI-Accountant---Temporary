"""The background review: which changes ask for one, the wait after the last change, the worker's tick and the run
itself, on a scripted chat model (tests/agent_fakes.py), never a real one."""
import datetime as dt
from types import SimpleNamespace

import pytest
from agent_fakes import ScriptedChatModel, call, say
from langchain.agents.middleware import model_retry

from ledgersync import books, ledger_book, reviews, upkeep
from ledgersync.agent.chat import Chat
from ledgersync.agent.tools import _to_look_at
from ledgersync.blobs import GridFSBlobStore
from ledgersync.config import Settings
from ledgersync.models import ChangeDraft
from ledgersync.records import AgentRecords
from test_agent import YEAR, keep_the_receipt, scripted, STAPLES

pytestmark = pytest.mark.mongo

T = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)   # "now" of a test: read again as each one starts


@pytest.fixture(autouse=True)
def _the_clock_starts_with_the_test():
    """T is the real time when the test starts. The store stamps runs with the real clock and the review counts them
    by day against T; a T left from when the file was read drifts from it, by an hour or over midnight in a long
    suite, and the tests about "today" then fail."""
    global T
    T = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def secs(n: float) -> dt.datetime:
    return T + dt.timedelta(seconds=n)


def test_the_tests_clock_is_read_when_a_test_starts():
    """Runs are stamped by the real clock and compared with T by day, and a recovered review is due by the real
    clock: T must not be the time this file was read, which a long suite leaves an hour, or a midnight, behind."""
    assert abs((dt.datetime.now(dt.timezone.utc) - T).total_seconds()) < 5


def draft(client_id: int, **fields) -> ChangeDraft:
    return ChangeDraft(**{**dict(client_id=client_id, year_start=YEAR, actor="user", kind="upload_read",
                                 summary="statement.csv read: 2 rows"), **fields})


@pytest.fixture
def records(mongo_store):
    return AgentRecords(mongo_store.db)


@pytest.fixture
def staples(mongo_store, records) -> int:
    blobs = GridFSBlobStore(mongo_store.db)
    client_id = scripted._client(STAPLES, mongo_store, records)
    for path in scripted._documents(STAPLES):
        scripted._add_document(mongo_store, blobs, client_id, YEAR, path)
    return client_id


@pytest.fixture
def make(mongo_store, monkeypatch):
    """A worker over a Chat whose model answers `replies`; `.chat`, `.model`, `.records`, `.busy` (a list: busy while
    it isn't empty) and `.change(client_id, at, **fields)`, which a person makes at that time."""
    monkeypatch.setattr(model_retry, "time", SimpleNamespace(sleep=lambda seconds: None))   # retry at once

    def _make(*replies, then=None, **settings):
        model = ScriptedChatModel(replies=list(replies), then=then)
        settings = Settings(warmup=False, **settings)
        chat = Chat(settings, mongo_store, GridFSBlobStore(mongo_store.db), read=None, model=model)
        busy: list = []
        worker = reviews.Worker(chat, settings, busy=lambda client_id: bool(busy))

        def change(client_id: int, at: dt.datetime, **fields):
            upkeep.after_change(mongo_store, chat.records, chat.locks, draft(client_id, **fields), now=at,
                                wait=settings.review_wait_seconds)

        return SimpleNamespace(chat=chat, model=model, records=chat.records, worker=worker, busy=busy,
                               change=change, settings=settings)

    return _make


def test_triggers_ignores_the_agent_chat_reads_closing_and_description_only_edits():
    def t(**fields):
        return reviews.triggers(draft(1, **fields))

    assert t() and t(kind="row_edited", after={"account": "7400"}, actor="import")
    assert not t(actor="agent:qwen/qwen3.8-27b") and not t(in_chat=True)
    assert not t(actor="rules", kind="decision")
    for kind in ("year_closed", "decision_applied", "question_closed"):
        assert not t(kind=kind)
    assert not t(kind="row_edited", after={"description": "Taxi"})
    assert t(kind="row_edited", after={"description": "Taxi", "account": "7400"})
    for field in ("name", "contact_name", "ai_review"):
        assert not t(kind="client_changed", after={field: "x"})
    for field in ("vat_registered", "business_type", "first_year_end", "bank_accounts"):
        assert t(kind="client_changed", after={field: "x"})


def test_a_batch_of_uploads_causes_one_run_after_the_last_is_read(make, staples):
    h = make(say("Looked: nothing to do."))
    for n in range(3):
        h.change(staples, secs(5 * n))
    h.busy.append("reading")
    assert h.worker.tick(secs(11)) == []   # not due, and busy
    assert h.worker.tick(secs(25)) == []   # the last file was read at 10: due at 30
    h.busy.clear()
    assert h.worker.tick(secs(29)) == []
    h.busy.append("reading")
    assert h.worker.tick(secs(31)) == [] and h.model.seen == []   # due, but a file is still being read
    h.busy.clear()
    [run] = h.worker.tick(secs(32))
    assert run.status == "done" and run.trigger_summary == "for 1 possible duplicate"
    assert h.worker.tick(secs(60)) == []
    assert len(h.model.seen) == 1


def test_a_run_applies_what_the_evidence_supports_and_records_it_as_background(make, mongo_store, staples):
    args = keep_the_receipt(mongo_store, staples)
    h = make(call("resolve_issue", **args), say("Kept the receipt and dropped the sheet line."))
    h.change(staples, T)

    [run] = h.worker.tick(secs(21))

    [decision] = h.records.decisions(staples)
    assert (decision.status, decision.trigger, decision.review_id) == ("applied", "background", run.id)
    assert run.status == "done" and run.decision_ids == [decision.id] and run.year_start == YEAR
    assert run.summary == "Kept the receipt and dropped the sheet line."
    assert next(r for r in mongo_store.rows(staples) if r.id == args["resolution"]["drop_row_ids"][0]).tx.excluded
    assert ledger_book.unposted_changes(mongo_store, h.records, staples, YEAR) == 0   # the books were settled
    state = h.records.review_state(staples)
    assert (state.running, state.due_at, state.retry_at) == (False, None, None)
    assert state.last_seq == next(c.seq for c in h.records.changes(staples) if c.actor == "user")


def test_suggest_only_records_suggestions_and_changes_nothing(make, mongo_store, staples):
    mongo_store.update_client(staples, {"ai_review": "suggest"})
    args = keep_the_receipt(mongo_store, staples)
    h = make(call("resolve_issue", **args), say("Suggested keeping the receipt."))
    h.change(staples, T)

    [run] = h.worker.tick(secs(21))

    [decision] = h.records.decisions(staples)
    assert (decision.status, decision.trigger, decision.review_id) == ("suggested", "background", run.id)
    assert run.status == "done" and run.decision_ids == [decision.id]
    assert not any(r.tx.excluded for r in mongo_store.rows(staples))


def test_off_records_one_quiet_run_a_day_and_moves_the_mark(make, mongo_store, staples):
    mongo_store.update_client(staples, {"ai_review": "off"})
    h = make()
    h.change(staples, T)
    [run] = h.worker.tick(secs(21))
    assert (run.status, run.summary) == ("off", "")
    first = h.records.review_state(staples)
    assert first.last_seq == max(c.seq for c in h.records.changes(staples)) and first.due_at is None

    h.change(staples, secs(100))
    assert h.worker.tick(secs(121)) == []   # the same day: no second note
    assert len(h.records.reviews(staples)) == 1 and h.model.seen == []
    assert h.records.review_state(staples).last_seq > first.last_seq


def test_the_daily_limit_pauses_with_the_exact_note(make, staples):
    h = make(say("Done."), review_daily_limit=1)
    h.change(staples, T)
    [first] = h.worker.tick(secs(21))
    assert first.status == "done"

    h.change(staples, secs(100))
    [paused] = h.worker.tick(secs(121))
    assert (paused.status, paused.summary) == ("limited", "AI review paused for today: limit reached")
    state = h.records.review_state(staples)
    assert state.due_at is not None and state.retry_at is not None   # it waits for tomorrow

    h.change(staples, secs(200))
    assert h.worker.tick(secs(221)) == []
    assert [r.status for r in h.records.reviews(staples)] == ["limited", "done"]
    assert len(h.model.seen) == 1


def test_a_failed_run_is_recorded_and_retried_later(make, staples):
    outage = ConnectionError("OpenRouter hung up")
    h = make(outage, outage, outage, say("Looked again."))
    h.change(staples, T)

    [failed] = h.worker.tick(secs(21))

    assert failed.status == "failed" and "OpenRouter hung up" in failed.error
    state = h.records.review_state(staples)
    assert state.last_seq == 0 and state.due_at is not None and state.running is False
    assert dt.datetime.fromisoformat(state.retry_at) == secs(21) + dt.timedelta(minutes=10)
    assert h.worker.tick(secs(300)) == []
    [again] = h.worker.tick(secs(21 + 601))
    assert again.status == "done" and again.summary == "Looked again."
    state = h.records.review_state(staples)
    assert (state.due_at, state.retry_at) == (None, None) and state.last_seq > 0


def test_a_restart_keeps_a_due_review_and_retries_a_running_one(make, staples):
    h = make(say("Looked."))
    h.change(staples, T)
    h.records.patch_review_state(staples, running=True)   # the process died during its run

    restarted = reviews.Worker(h.chat, h.settings, busy=lambda client_id: False)
    restarted.recover()
    state = h.records.review_state(staples)
    assert state.running is False and state.due_at is not None

    assert len(restarted.tick(secs(3600))) == 1
    assert restarted.tick(secs(3700)) == []

    # a review that was only due keeps waiting for its time
    h.change(staples, secs(200))
    after = reviews.Worker(h.chat, h.settings, busy=lambda client_id: False)
    after.recover()
    assert after.tick(secs(205)) == []


def test_the_agents_own_changes_cause_no_further_run(make, mongo_store, staples):
    args = keep_the_receipt(mongo_store, staples)
    h = make(call("resolve_issue", **args), say("Kept the receipt."))
    h.change(staples, T)
    assert len(h.worker.tick(secs(21))) == 1
    assert any(c.actor.startswith("agent:") for c in h.records.changes(staples))   # the decision was recorded

    assert h.worker.tick(secs(100)) == []
    assert h.records.review_state(staples).due_at is None
    assert len(h.records.reviews(staples)) == 1


def test_a_change_during_a_run_causes_exactly_one_more_run(make, mongo_store, staples):
    from decimal import Decimal
    from helpers import row

    def mid_run(messages):   # an undated receipt arrives while the first run thinks: a new issue the AI can settle
        upload = mongo_store.add_upload(staples, "taxi.jpg", "image", [row(date=None, description="Taxi",
                                                                           gross=Decimal("18.00"))], year_start=YEAR)
        h.change(staples, secs(30), summary="taxi.jpg read: 1 row", upload_id=upload)
        return say("First look done.")

    h = make(mid_run, say("Second look done."))
    h.change(staples, T)

    [first] = h.worker.tick(secs(21))

    assert first.status == "done"
    state = h.records.review_state(staples)
    assert state.due_at is not None and state.running is False and state.last_seq < max(
        c.seq for c in h.records.changes(staples))
    [second] = h.worker.tick(secs(60))
    assert second.trigger_summary == "for 1 date to settle"
    assert h.worker.tick(secs(100)) == []
    assert h.records.review_state(staples).due_at is None


def test_a_name_change_causes_no_run_and_a_vat_change_does(make, staples):
    h = make(say("Looked."))
    h.change(staples, T, kind="client_changed", after={"name": "Staples Ltd"}, year_start=None)
    assert h.records.review_state(staples).due_at is None
    assert h.worker.tick(secs(100)) == []

    h.change(staples, secs(100), kind="client_changed", after={"vat_registered": False}, year_start=None)
    [run] = h.worker.tick(secs(121))   # the VAT change makes the client due; the run is named for its issues
    assert run.trigger_summary == "for 1 possible duplicate"


def test_a_run_names_each_issue_no_run_has_looked_at(make, mongo_store, staples):
    flagged = _to_look_at(books.ledger(mongo_store, staples, YEAR))
    assert flagged
    h = make(say("Looked."), say("Looked again."))
    h.change(staples, T)

    [run] = h.worker.tick(secs(21))

    text = h.model.seen[0][-1].content
    assert "Issues no review has looked at yet:" in text
    settleable = [(row, reviews.issue_keys(row)) for row, _, _ in flagged]
    for row, keys in settleable:   # only what the AI has an action for; a missing document is the person's to send
        assert (f"- Row {row.id} " in text) == bool(keys)
        assert all(said.split(": ", 1)[1] in text for _, said in keys)
    assert run.looked_at == [row.id for row, keys in settleable if keys]
    assert h.records.issues_seen(staples, YEAR) == set(run.issues_seen) != set()

    # A person's change brings no new issue the AI can settle, and the AI leaves a person's rows to them: no run.
    h.change(staples, secs(100), kind="row_edited", row_ids=[flagged[0][0].id], after={"description": "x", "date": "y"})
    assert h.worker.tick(secs(121)) == [] and len(h.model.seen) == 1


def test_a_change_that_brings_no_new_issue_and_touches_no_row_causes_no_run(make, mongo_store, staples):
    h = make(say("Looked."), say("Should not be asked."))
    h.change(staples, T)
    [first] = h.worker.tick(secs(21))

    h.change(staples, secs(100), summary="another.pdf read: 1 row")   # an upload that adds no issue
    assert h.worker.tick(secs(121)) == []
    assert len(h.model.seen) == 1 and h.records.reviews(staples, year_start=YEAR) == [first]
    assert h.records.review_state(staples).due_at is None


def test_an_issue_that_pops_up_later_is_reviewed_and_only_it(make, mongo_store, staples):
    from decimal import Decimal
    from helpers import row
    h = make(say("Looked."), say("Looked at the new one."))
    h.change(staples, T)
    h.worker.tick(secs(21))
    before = h.records.issues_seen(staples, YEAR)

    upload = mongo_store.add_upload(staples, "taxi.jpg", "image", [row(date=None, description="Taxi", gross=Decimal("18.00"))], year_start=YEAR)
    [taxi] = [r.id for r in mongo_store.rows(staples) if r.upload_id == upload]
    h.change(staples, secs(100), summary="taxi.jpg read: 1 row", upload_id=upload)
    [run] = h.worker.tick(secs(121))

    text = h.model.seen[1][-1].content
    assert f"- Row {taxi} " in text and "has no date" in text
    assert all(f"- Row {k.split(':')[0]} " not in text for k in before)
    assert run.summary == "Looked at the new one."


def test_the_first_review_of_a_year_says_to_look_at_everything(make, staples):
    h = make(say("Looked."))
    h.change(staples, T)
    h.worker.tick(secs(21))
    assert "First review of this year: look at everything." in h.model.seen[0][-1].content


def test_a_run_that_changes_nothing_says_why_in_its_own_words(make, staples):
    h = make(say("Looked at everything.\nAll in order: the receipts match the bank."))
    h.change(staples, T)
    [run] = h.worker.tick(secs(21))
    assert (run.status, run.decision_ids, run.question_ids) == ("done", [], [])
    assert run.summary == "All in order: the receipts match the bank."


def first_row(h, client_id: int) -> int:
    return h.chat.store.rows(client_id)[0].id


def test_a_run_lists_the_questions_it_asked(make, staples):
    h = make(lambda m: call("ask_user", row_ids=[first_row(h, staples)], question="Is it personal?", why="Unclear."),
             say("Asked about the row."))
    h.change(staples, T)
    [run] = h.worker.tick(secs(21))
    [asked] = [q for q in h.records.questions(staples, YEAR) if q.source == "agent"]
    assert run.question_ids == [asked.id] and run.summary == "Asked about the row."


def test_a_change_in_a_year_that_is_not_open_causes_no_run(make, staples):
    h = make(say("Looked."))
    h.change(staples, T, year_start=YEAR - dt.timedelta(days=365))
    assert h.worker.tick(secs(21)) == []
    assert h.records.review_state(staples).due_at is None


def test_two_workers_ticking_the_same_due_client_run_it_once(make, staples):
    from_other = []

    def while_running(messages):
        # the other worker, which read the client as due and idle before this run began, ticks now
        from_other.extend(other.tick(secs(21)))
        return say("Looked.")

    h = make(while_running, say("A second run."))
    other = reviews.Worker(h.chat, h.settings, busy=lambda client_id: False)
    h.change(staples, T)
    stale = h.records.due_review_states()
    h.records.due_review_states = lambda: stale

    first = h.worker.tick(secs(21))

    assert len(first) == 1 and from_other == [] and len(h.model.seen) == 1


def test_claiming_a_running_review_fails(records):
    records.patch_review_state(5, running=False)
    assert records.claim_review(5) is True
    assert records.claim_review(5) is False
    records.patch_review_state(5, running=False)
    assert records.claim_review(5) is True


def test_a_client_that_is_gone_or_archived_is_not_retried(make, mongo_store, staples):
    h = make(say("Looked."))
    h.change(staples, T)
    mongo_store.update_client(staples, {"archived": True})
    assert h.worker.tick(secs(21)) == []
    state = h.records.review_state(staples)
    assert (state.due_at, state.retry_at, state.running) == (None, None, False)

    h.records.patch_review_state(9999, due_at=reviews._iso(T))   # a client that does not exist
    assert h.worker.tick(secs(21)) == []
    assert h.records.review_state(9999).due_at is None and h.records.review_state(9999).retry_at is None


def test_one_bad_state_does_not_stop_the_tick(make, staples):
    h = make(say("Looked."))
    h.records.patch_review_state(4242, due_at="not a time")
    h.change(staples, T)
    assert len(h.worker.tick(secs(21))) == 1


def test_issues_over_the_limit_of_one_run_get_a_run_of_their_own(make, monkeypatch, mongo_store, staples):
    from decimal import Decimal
    from helpers import row
    mongo_store.add_upload(staples, "taxi.jpg", "image", [row(date=None, description="Taxi", gross=Decimal("18.00"))],
                           year_start=YEAR)   # an undated receipt: a second issue the AI can settle
    monkeypatch.setattr(reviews, "MAX_UNREVIEWED", 1)
    h = make(say("Looked at one."), say("Looked at the next."))
    h.change(staples, T)
    [first] = h.worker.tick(secs(21))
    assert len(first.issues_seen) == 1 and "more: list_issues shows them all" in h.model.seen[0][-1].content
    assert h.records.review_state(staples).due_at is not None   # the rest are due at once, with no new change
    [second] = h.worker.tick(secs(23))
    assert second.issues_seen and set(second.issues_seen).isdisjoint(first.issues_seen)


def test_issues_the_ai_has_no_action_for_cause_no_run(make, mongo_store, records):
    # A bank payment of £120 with no receipt: the rules ask the person for it; the AI can't settle it.
    from decimal import Decimal
    from helpers import row
    from ledgersync.models import ClientFields
    client_id = mongo_store.create_client(ClientFields(name="Held Ltd", business_type="limited_company",
                                                       contact_name="Sam", vat_registered=True,
                                                       first_year_end=dt.date(2027, 3, 31))).id
    mongo_store.add_upload(client_id, "bank.csv", "table", [row(
        date=dt.date(2026, 9, 20), description="SCREWFIX", gross=Decimal("120.00"), account_code="7600",
        document_type="statement")], year_start=YEAR)
    h = make(say("Should not be asked."))
    h.change(client_id, T, summary="bank.csv read: 1 row")
    assert h.worker.tick(secs(21)) == [] and h.model.seen == []
    assert h.records.review_state(client_id).due_at is None


def test_a_run_is_named_for_the_issues_it_looks_at(make, staples):
    h = make(say("Looked."))
    h.change(staples, T)
    [run] = h.worker.tick(secs(21))
    assert run.trigger_summary == "for 1 possible duplicate"


def test_a_database_that_was_switching_servers_is_tried_again_within_a_minute(make, monkeypatch, staples):
    from pymongo.errors import ServerSelectionTimeoutError

    def blip(*args, **kwargs):   # as the agent's checkpoint write failed while Atlas chose a new primary
        raise ServerSelectionTimeoutError("No primary available for writes")
        yield

    h = make(say("Looked again."))
    monkeypatch.setattr(h.chat, "_agent", type("Agent", (), {"stream": staticmethod(blip)})())
    h.change(staples, T)
    [failed] = h.worker.tick(secs(21))
    assert failed.status == "failed" and "database" in failed.error and "try again" in failed.error
    assert dt.datetime.fromisoformat(h.records.review_state(staples).retry_at) == secs(21) + dt.timedelta(minutes=1)


def test_a_review_cut_off_while_thinking_is_asked_once_to_act_on_what_it_read(make, staples):
    from langchain_core.messages import AIMessage
    cut = AIMessage(content="", response_metadata={"finish_reason": "length"})
    h = make(cut, say("Settled what I could."))
    h.change(staples, T)
    [run] = h.worker.tick(secs(21))
    assert (run.status, run.summary) == ("done", "Settled what I could.")
    assert "cut off" in h.model.seen[1][-1].content


def test_a_review_cut_off_twice_fails(make, staples):
    from langchain_core.messages import AIMessage
    cut = AIMessage(content="", response_metadata={"finish_reason": "length"})
    h = make(cut, cut)
    h.change(staples, T)
    [run] = h.worker.tick(secs(21))
    assert run.status == "failed" and "length limit" in run.error and len(h.model.seen) == 2


def test_a_background_review_is_the_reviewers(make, staples):
    from ledgersync.agent.middleware import BOOKS_NOW
    from ledgersync.agent.specialists import PROFILES
    h = make(say("Looked: nothing to do."))
    h.change(staples, secs(0))
    [run] = h.worker.tick(secs(32))
    assert run.status == "done" and h.model.tools == list(PROFILES["reviewer"].tools)
    prompt, told = h.model.seen[0][0].content.split(BOOKS_NOW)
    assert prompt == PROFILES["reviewer"].prompt
    assert set(__import__("json").loads(told)) == {"overview"}   # the review's message names the issues itself
