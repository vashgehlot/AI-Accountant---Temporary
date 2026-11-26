import json
from datetime import date

import pytest

from testbooks_runner import align, books, driver
from testbooks_runner.api import AppError
from testbooks_runner.model import Period, Unit
from testbooks_runner.runs import Progress, load_progress
from testbooks_runner.tests import builders
from testbooks_runner.tests.fake_api import FakeApi
from testbooks_runner.tests.helpers import write_mini_client
from testbooks_runner.tests.test_driver import Clock

START = "2023-04-01"
WHARF = "2024-02-08_wharf_woi-1.pdf"
Q2 = "Can you upload the full VAT invoice?"
Q1 = "Is the Streamflix charge personal?"


class Relay:
    def __init__(self):
        self.parts: list[tuple[str, str | None]] = []

    def set_part(self, unit, part):
        self.parts.append((unit, part))


class ChatApi(FakeApi):
    """FakeApi whose turns answer in turn: `turns` holds, per call, events or an AppError."""

    def __init__(self):
        super().__init__()
        self.turns: list = []
        self.sent: list[tuple] = []
        self.question_script: list[list[dict]] | None = None
        self.running_script: list[bool] = []
        self.answered: list[tuple] = []

    def answer_question(self, thread_id, question_id, answer):
        self.calls.append(("answer_question", (thread_id, question_id, answer)))
        self.answered.append((thread_id, question_id, answer))
        return {"questions": []}

    def send_message(self, thread_id, text, files):
        self.calls.append(("send_message", (thread_id, text, files)))
        self.sent.append((thread_id, text, list(files)))
        step = self.turns.pop(0) if self.turns else [("done", {})]
        if isinstance(step, Exception):
            raise step
        return step

    def questions(self, client_id):
        if self.question_script:
            n = len([c for c in self.calls if c[0] == "questions"])
            self.calls.append(("questions", (client_id,)))
            return self.question_script[min(n, len(self.question_script) - 1)]
        return super().questions(client_id)

    def thread(self, thread_id):
        self.calls.append(("thread", (thread_id,)))
        return {"running": self.running_script.pop(0) if self.running_script else False}


def app_q(id, text, row_ids=(1,), status="open", created_at="2024-02-10T10:00:00"):
    return {"id": id, "text": text, "row_ids": list(row_ids), "status": status, "created_at": created_at}


@pytest.fixture
def setup(tmp_path):
    folder = write_mini_client(tmp_path / "set")
    unit = Unit("mini", "client", folder, Period(date(2023, 4, 1), date(2024, 3, 31)))
    key = books.load_key(unit.key_dir)
    # a journal for deal MN-0010 with counterparty Wharf, so MN-Q0002 can match through the counterparty too
    key.entries.append({"entry_id": "E9", "journal_id": "MN-0010", "date": "2024-02-08", "account": "5000",
                        "debit": "100.00", "credit": "0.00", "counterparty": "Wharf", "deal_id": "MN-0010",
                        "doc_ids": "MN-D0003", "line_ids": ""})
    unit_dir = tmp_path / "unit"
    unit_dir.mkdir()
    progress = Progress(client_id=1, app_year_start=START)
    api = ChatApi()
    api.clients[1] = {"id": 1}
    return api, unit, key, progress, unit_dir


def write_before(unit_dir, questions=(), reviews=(), uploads=None):
    """Save a 'before' snapshot holding the wharf invoice's one row (id 1, upload 7)."""
    raw = unit_dir / "raw" / "before"
    raw.mkdir(parents=True, exist_ok=True)
    rows = [builders.row(1, 7, gross="120.00", date="2024-02-08")]
    ups = uploads if uploads is not None else [{"id": 7, "name": WHARF}]
    (raw / f"ledger-{START}.json").write_text(json.dumps({"transactions": rows, "uploads": ups}))
    (raw / "questions.json").write_text(json.dumps(list(questions)))
    (raw / "reviews.json").write_text(json.dumps(list(reviews)))


def run(setup, relay=None, clock=None, **opts):
    api, unit, key, progress, unit_dir = setup
    clock = clock or Clock()
    options = driver.Options(**opts)
    driver.send_replies(api, unit, key, progress, unit_dir, relay=relay, options=options,
                        clock=clock, now=clock.now, sleep=clock.sleep)
    return clock


def test_client_words_drop_the_key_question():
    assert driver.client_words("Re: Is that right?\n\nYes, that's my personal one.\n") == "Yes, that's my personal one."
    assert driver.client_words("No heading here.\n") == "No heading here."


def test_reply_files_exclude_other_replies(setup):
    _, unit, *_ = setup
    folder = unit.folder / "answers" / "2024-03-12"
    files = driver.reply_files(folder / "2024-03-12_reply_mn-q0002.txt")
    assert [p.name for p in files] == [WHARF]


def test_reply_files_skip_hidden_files(setup):
    _, unit, *_ = setup
    folder = unit.folder / "answers" / "2024-03-12"
    (folder / ".DS_Store").write_bytes(b"finder")
    files = driver.reply_files(folder / "2024-03-12_reply_mn-q0002.txt")
    assert [p.name for p in files] == [WHARF]


def test_plan_sends_only_what_the_app_asked(setup):
    api, unit, key, progress, unit_dir = setup
    write_before(unit_dir, questions=[app_q("a", Q2)])
    snap = align.load_snapshot(unit_dir, "before")
    al = align.align(key, snap, {}, books.load_profile(unit.folder), {})
    plan = driver.plan_replies(unit, key, snap, al)
    assert [(p["query_id"], p["send"]) for p in plan] == [("MN-Q0001", False), ("MN-Q0002", True)]
    sent = plan[1]
    assert (sent["question_id"], sent["question_text"]) == ("a", Q2)
    assert plan[0]["question_id"] is None


def test_plan_ignores_resolved_and_finds_review_questions(setup):
    api, unit, key, progress, unit_dir = setup
    review = {"id": "r", "status": "done", "started_at": "2024-02-01T00:00:00+00:00",
              "questions": [app_q("b", Q2, status="waiting")]}
    write_before(unit_dir, questions=[app_q("a", Q2, status="resolved")], reviews=[review])
    snap = align.load_snapshot(unit_dir, "before")
    al = align.align(key, snap, {}, books.load_profile(unit.folder), {})
    plan = driver.plan_replies(unit, key, snap, al)
    assert plan[1]["send"] is True and plan[1]["question_id"] == "b"
    write_before(unit_dir, questions=[app_q("a", Q2, status="resolved")])
    snap = align.load_snapshot(unit_dir, "before")
    al = align.align(key, snap, {}, books.load_profile(unit.folder), {})
    assert driver.plan_replies(unit, key, snap, al)[1]["send"] is False


def test_plan_replies_under_the_earliest_question(setup):
    api, unit, key, progress, unit_dir = setup
    write_before(unit_dir, questions=[app_q("late", "Later wording?", created_at="2024-02-12T10:00:00"),
                                      app_q("early", Q2, created_at="2024-02-10T10:00:00")])
    snap = align.load_snapshot(unit_dir, "before")
    al = align.align(key, snap, {}, books.load_profile(unit.folder), {})
    assert driver.plan_replies(unit, key, snap, al)[1]["question_id"] == "early"


def test_reply_sent_only_when_the_app_asked(setup):
    api, unit, key, progress, unit_dir = setup
    write_before(unit_dir, questions=[app_q("a", Q2)])
    run(setup)
    [(thread_id, text, files)] = api.sent
    assert text.startswith("> " + Q2) and "Re:" not in text
    assert text == f"> {Q2}\n\nAttached."
    assert [p.name for p in files] == [WHARF]
    assert progress.replies["MN-Q0001"]["sent"] is False
    assert progress.replies["MN-Q0001"]["events"] == []
    assert progress.replies["MN-Q0002"]["sent"] is True
    assert progress.replies["MN-Q0002"]["question_id"] == "a"
    assert load_progress(unit_dir).replies == progress.replies


def test_nothing_sent_means_no_wait_and_no_message(setup):
    api, unit, key, progress, unit_dir = setup
    write_before(unit_dir)
    run(setup)
    assert api.sent == []
    assert "after-replies" not in progress.review_waits
    assert not any(c[0] == "reviews" for c in api.calls)


def test_chat_year_recorded(setup):
    api, unit, key, progress, unit_dir = setup
    write_before(unit_dir, questions=[app_q("a", Q2)])
    api.returns["new_thread"] = {"id": "t9", "year_start": "2026-04-01"}
    run(setup)
    assert progress.chat_year == "2026-04-01" and progress.thread_id == "t9"
    assert api.sent[0][0] == "t9"
    assert ("new_thread", (1, date(2023, 4, 1))) in api.calls
    assert progress.chat_refusal is None


def test_year_refused_opens_the_thread_without_it(setup):
    api, unit, key, progress, unit_dir = setup
    write_before(unit_dir, questions=[app_q("a", Q2)])
    api.raise_on["new_thread"] = [AppError(422, "invalid_input", "no year_start here"), None]
    api.returns["new_thread"] = {"id": "t1", "year_start": "2026-04-01"}
    run(setup)
    opened = [a for n, a in api.calls if n == "new_thread"]
    assert opened == [(1, date(2023, 4, 1)), (1, None)]
    assert progress.chat_refusal == {"status": 422, "code": "invalid_input", "message": "no year_start here"}
    assert progress.chat_year == "2026-04-01"


def test_asked_back_leaves_out_questions_known_before_the_turn(setup):
    api, unit, key, progress, unit_dir = setup
    write_before(unit_dir, questions=[app_q("a", Q2)])
    api.question_script = [[app_q("a", Q2), app_q("old", "Old one?")]]
    new = app_q("n", "Which month was it?")
    api.turns = [[("token", {"text": "Thanks"}),
                  ("result", {"questions": [app_q("old", "Old one?"), new]}), ("done", {})]]
    run(setup)
    record = progress.replies["MN-Q0002"]
    assert record["asked_back"] == [new]
    assert [e[0] for e in record["events"]] == ["token", "result", "done"]
    lines = [json.loads(x) for x in (unit_dir / "chat.jsonl").read_text().splitlines()]
    assert [(l["query_id"], l["event"]) for l in lines] == [("MN-Q0002", "token"), ("MN-Q0002", "result"),
                                                            ("MN-Q0002", "done")]


def test_a_stream_that_ends_early_counts_as_sent(setup):
    api, unit, key, progress, unit_dir = setup
    write_before(unit_dir, questions=[app_q("a", Q2)])
    api.turns = [AppError(200, "stream_ended", "cut", [("token", {"text": "Thi"})])]
    run(setup)
    record = progress.replies["MN-Q0002"]
    assert record["sent"] is True
    assert record["events"] == [["token", {"text": "Thi"}]]
    assert record["error"] == {"status": 200, "code": "stream_ended", "message": "cut"}


def test_another_error_records_not_sent_and_goes_on(setup):
    api, unit, key, progress, unit_dir = setup
    write_before(unit_dir, questions=[app_q("a", Q2)])
    api.turns = [AppError(500, "boom", "bad")]
    run(setup)
    record = progress.replies["MN-Q0002"]
    assert record["sent"] is False
    assert record["error"] == {"status": 500, "code": "boom", "message": "bad"}
    assert "after-replies" not in progress.review_waits


def test_still_working_waits_then_tries_once_more(setup):
    api, unit, key, progress, unit_dir = setup
    write_before(unit_dir, questions=[app_q("a", Q2)])
    api.turns = [AppError(409, "still_working", "busy"), [("done", {})]]
    api.running_script = [True, True, False]
    clock = run(setup, review="off")
    assert len(api.sent) == 2 and api.sent[0][1] == api.sent[1][1]
    assert progress.replies["MN-Q0002"]["sent"] is True
    assert clock.t == 4.0  # two polls of 2 seconds


def test_still_working_twice_gives_up(setup):
    api, unit, key, progress, unit_dir = setup
    write_before(unit_dir, questions=[app_q("a", Q2)])
    api.turns = [AppError(409, "still_working", "busy"), AppError(409, "still_working", "busy")]
    run(setup)
    assert len(api.sent) == 2
    assert progress.replies["MN-Q0002"]["sent"] is False
    assert progress.replies["MN-Q0002"]["error"]["code"] == "still_working"


def test_resume_skips_sent_replies_and_reuses_the_thread(setup):
    api, unit, key, progress, unit_dir = setup
    write_before(unit_dir, questions=[app_q("a", Q2)])
    progress.thread_id, progress.chat_year = "old", "2026-04-01"
    progress.replies["MN-Q0002"] = {"sent": True, "question_id": "a", "events": [], "asked_back": []}
    run(setup)
    assert api.sent == []
    assert not any(c[0] == "new_thread" for c in api.calls)
    assert progress.replies["MN-Q0002"]["question_id"] == "a"


def test_resume_retries_a_reply_that_was_not_sent(setup):
    api, unit, key, progress, unit_dir = setup
    write_before(unit_dir, questions=[app_q("a", Q2)])
    progress.thread_id = "old"
    progress.replies["MN-Q0002"] = {"sent": False, "question_id": "a", "events": [], "asked_back": [],
                                    "error": {"status": 500, "code": "boom", "message": "bad"}}
    run(setup)
    assert [s[0] for s in api.sent] == ["old"]
    assert progress.replies["MN-Q0002"]["sent"] is True
    assert "error" not in progress.replies["MN-Q0002"]


def test_the_relay_part_is_set_and_cleared_even_on_failure(setup):
    api, unit, key, progress, unit_dir = setup
    write_before(unit_dir, questions=[app_q("a", Q2)])
    relay = Relay()
    api.turns = [AppError(500, "boom", "bad")]
    run(setup, relay=relay)
    assert relay.parts == [(unit.slug, "chat"), (unit.slug, None)]


def test_waits_for_the_review_after_the_last_turn(setup):
    api, unit, key, progress, unit_dir = setup
    write_before(unit_dir, questions=[app_q("a", Q2)])
    api.review_script = [[{"id": "r", "status": "done", "started_at": "2024-06-01T12:00:01+00:00"}]]
    run(setup)
    assert progress.review_waits["after-replies"] == "done"
    assert load_progress(unit_dir).review_waits["after-replies"] == "done"


def test_review_off_does_not_wait(setup):
    api, unit, key, progress, unit_dir = setup
    write_before(unit_dir, questions=[app_q("a", Q2)])
    run(setup, review="off")
    assert "after-replies" not in progress.review_waits


def test_the_review_wait_starts_after_the_last_turn(setup):
    api, unit, key, progress, unit_dir = setup
    key.entries.append({"entry_id": "E8", "journal_id": "MN-0009", "date": "2023-04-15", "account": "5000",
                        "debit": "120.00", "credit": "0.00", "counterparty": "Cabot", "deal_id": "MN-0009",
                        "doc_ids": "MN-D0002", "line_ids": ""})
    write_before(unit_dir, questions=[app_q("a", Q2), app_q("b", Q1, row_ids=(2,))],
                 uploads=[{"id": 7, "name": WHARF}, {"id": 8, "name": "2023-04-15_cabot_62874.pdf"}])
    ledger = unit_dir / "raw" / "before" / f"ledger-{START}.json"
    data = json.loads(ledger.read_text())
    data["transactions"].append(builders.row(2, 8, gross="120.00", date="2023-04-15"))
    ledger.write_text(json.dumps(data))
    clock = Clock()
    send = api.send_message

    def slow(thread_id, text, files):
        out = send(thread_id, text, files)
        clock.t += 10
        return out

    api.send_message = slow
    # the only review started during turn 1 (at 1 second) and is finished
    api.review_script = [[{"id": "r1", "status": "done", "started_at": "2024-06-01T12:00:01+00:00"}]]
    run(setup, clock=clock)
    assert [s[1].split("\n")[0] for s in api.sent] == ["> " + Q1, "> " + Q2]
    assert progress.review_waits["after-replies"] == "none"


def test_a_question_on_a_statement_row_in_the_apis_shape_gets_its_reply(setup):
    api, unit, key, progress, unit_dir = setup
    key.queries[0]["about"] = "MN-0002"  # MN-Q0001 now asks about the Cabot payment on the bank statement
    stmt = "inbox/2023-05-09/2023-04-01_hsbc-statement_2023-04-30.csv"
    progress.bank_codes = {"hsbc": "1200"}
    progress.uploads = builders.uploads_progress({stmt: 9})
    write_before(unit_dir, questions=[app_q("s", Q1, row_ids=(3,))], uploads=[{"id": 9, "name": stmt.split("/")[-1]}])
    ledger = unit_dir / "raw" / "before" / f"ledger-{START}.json"
    data = json.loads(ledger.read_text())
    # as the API sends it: include is false on a row nobody ticked
    data["transactions"] = [builders.api_row(3, 9, document_type="statement", bank_account="1200",
                                             gross="300.00", date="2023-04-20")]
    ledger.write_text(json.dumps(data))
    run(setup, review="off")
    assert progress.replies["MN-Q0001"]["sent"] is True and progress.replies["MN-Q0001"]["question_id"] == "s"
    assert [s[1].split("\n")[0] for s in api.sent] == ["> " + Q1]


def test_the_runner_confirms_the_answer_the_app_offered_in_its_own_chat(setup):
    # The app's agent fills in a books question's answer from the client's reply, for the client to confirm
    # (design of 2026-11-25): the client's yes is the runner confirming it unchanged. An offer made in another chat
    # is not the runner's client's to confirm.
    api, unit, key, progress, unit_dir = setup
    write_before(unit_dir, questions=[app_q("a", Q2)])
    progress.thread_id = "t-runner"
    answer = {"kind": "split", "lines": [{"account": "8250", "amount": "312.00"}]}
    mine = {**app_q("vat", "The VAT payment differs?"), "offer": {"answer": answer, "thread_id": "t-runner"}}
    theirs = {**app_q("other", "Opening accruals?"), "offer": {"answer": answer, "thread_id": "t-else"}}
    api.question_script = [[app_q("a", Q2)], [app_q("a", Q2), mine, theirs]]
    run(setup)
    assert api.answered == [("t-runner", "vat", answer)]
    assert progress.replies["MN-Q0002"]["confirmed"] == [{"question_id": "vat", "answer": answer}]
