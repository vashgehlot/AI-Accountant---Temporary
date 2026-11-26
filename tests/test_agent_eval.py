"""The agent eval runner's scoring (eval/run_agent_eval.py) agrees with the hand-worked figures: a case worked by
eval/run_scripted_resolutions.py with no model passes every score, and a wrong posted figure fails the trial balance
with its account in the difference."""
import json
from decimal import Decimal
from pathlib import Path

import pytest

import run_agent_eval as agent_eval
import run_scripted_resolutions as scripted
from ledgersync.records import AgentRecords

pytestmark = pytest.mark.mongo

ROOT = Path(__file__).parent.parent
CASES = [ROOT / "eval" / "agent_cases" / "conflict-invoice-vs-expense-report", ROOT / "demo" / "northbridge"]


@pytest.fixture
def records(mongo_db):
    return AgentRecords(mongo_db)


@pytest.mark.parametrize("case", CASES, ids=lambda p: p.name)
def test_scripted_case_passes_every_score(case, mongo_store, records):
    result = scripted.run(case, mongo_store, records)
    expected_decisions = json.loads((case / "expected_decisions.json").read_text())
    expected_questions = json.loads((case / "expected_questions.json").read_text())
    before, after = agent_eval.expected_trial_balances(case)
    decisions = [d.model_dump(mode="json") for d in records.decisions(result.client_id, result.year_start)]

    assert agent_eval.score_trial_balance(after, result.answered.trial_balance) == []
    if before is not None:
        assert agent_eval.score_trial_balance(before, result.review.trial_balance) == []
    assert agent_eval.score_decisions(expected_decisions, decisions, agent_eval.exact_ids(scripted._names(mongo_store, result.client_id))) == []
    assert agent_eval.score_questions(expected_questions["before_answers"], result.review.questions) == []
    assert agent_eval.score_questions(expected_questions["after_answers"], result.answered.questions) == []


def test_a_wrong_posted_figure_fails_the_trial_balance(mongo_store, records):
    case = ROOT / "eval" / "agent_cases" / "clean-month"
    _, expected = agent_eval.expected_trial_balances(case)
    posted = scripted.run(case, mongo_store, records).answered.trial_balance
    account = sorted(posted)[0]
    posted[account] += Decimal("0.01")

    [difference] = agent_eval.score_trial_balance(expected, posted)
    assert difference["code"] == account and difference["difference"] == "0.01"


def test_missing_and_unexpected_questions_and_decisions_fail():
    row = {"file": "a.csv", "description": "X"}
    assert agent_eval.score_questions([{"kind": "date", "row": row}], []) == [
        {"missing": ("date", "a.csv", "X")}]
    assert agent_eval.score_questions([], [{"kind": "date", "row": row}]) == [
        {"unexpected": ("date", "a.csv", "X")}]
    expected = {"resolutions": [], "automatic": [{"rule": "R1", "row": row}], "from_answers": []}
    assert agent_eval.score_decisions(expected, [], lambda name: None) == [{"missing": {"rule": "R1", "row": row}}]


def _every_file():
    cases = [p for p in sorted((ROOT / "eval" / "agent_cases").iterdir()) if (p / "client.json").exists()]
    return [(case, f) for case in [*cases, ROOT / "demo" / "northbridge"] for f in agent_eval.case_files(case)]


@pytest.mark.parametrize("case, path", _every_file(), ids=lambda v: v.name)
def test_prepared_rows_finds_every_file_as_the_server_reads_it(case, path):
    """The file as intake.load_upload gives it to pipeline.analyze maps back to its own .rows.json."""
    from ledgersync import intake
    rows = agent_eval.PreparedRows()
    rows.use(agent_eval.case_files(case))
    assert rows._find(intake.load_upload(path.name, path.read_bytes(), 1000)) == path
    assert path.with_name(f"{path.name}.rows.json").exists()


def test_run_case_goes_through_the_routes_with_prepared_rows(mongo_store, records):
    """The demo, on a chat model that decides nothing: the run completes, the rules' questions are answered through
    the answer and document routes, and the scores and problems are recorded (the scores fail: no decisions)."""
    from agent_fakes import ScriptedChatModel, say
    from fakes import FakeModel
    from fastapi.testclient import TestClient

    from ledgersync.config import Settings
    from server import create_app

    rows = agent_eval.PreparedRows()
    rows.install()
    try:
        app = create_app(Settings(warmup=False), model_client=FakeModel([]), store=mongo_store,
                         chat_model=ScriptedChatModel(then=say("Done.")))
        with TestClient(app, headers={"X-LedgerSync": "1"}) as api:
            result = agent_eval.run_case(api, mongo_store, records, ROOT / "demo" / "northbridge", rows, "scripted")
    finally:
        rows.uninstall()

    assert result["error_events"] == [] and result["failed_steps"] == []
    assert result["answers_not_applied"] == [] and result["steps"] >= 3
    assert result["trial_balance"]["passed"] is False or result["decisions"]["passed"] is False
    assert {"trial_balance", "decisions", "questions", "problems", "seconds", "refused_decisions"} <= set(result)
    assert agent_eval.passed(result) is False


def test_an_applied_decision_on_an_unknown_row_is_unexpected():
    odd = {"status": "applied", "row_ids": [99], "rule": "R9"}
    assert agent_eval.score_decisions({"resolutions": [], "automatic": [], "from_answers": []}, [odd],
                                         lambda name: None) == [
        {"unexpected": {"row_ids": [99], "rule": "R9"}}]


def test_a_duplicate_resolution_matches_whatever_order_its_rows_come_in():
    keep, drop = {"file": "a.txt", "description": "K"}, {"file": "b.csv", "description": "D"}
    expected = {"resolutions": [{"rule": "R2", "row": keep, "arguments": {"keep": keep, "drop": [drop]}}],
                "automatic": [], "from_answers": []}
    ids = agent_eval.exact_ids({1: keep, 2: drop})
    for row_ids in ([1, 2], [2, 1]):
        assert agent_eval.score_decisions(expected, [{"status": "applied", "rule": "R2", "row_ids": row_ids}],
                                          ids) == []
    assert agent_eval.score_decisions(expected, [{"status": "applied", "rule": "R3", "row_ids": [1]}], ids) == [
        {"missing": {"rule": "R2", "row": keep}}, {"unexpected": {"row_ids": [1], "rule": "R3"}}]


def test_a_run_with_a_failed_step_but_right_scores_passes_and_is_not_clean():
    ok = {"passed": True, "differences": []}
    run = {"case": "c", "run": 1, "seconds": 1, "trial_balance": ok, "decisions": ok, "questions": ok,
           "problems": [], "failed_steps": ["Reading x.png failed"], "refused_decisions": [], "row_fallbacks": []}
    assert agent_eval.passed(run) and not agent_eval.clean(run)
    assert agent_eval.passed({**run, "problems": ["answer not applied: x"]}) is False
    assert agent_eval.table([run]).splitlines()[1].split()[-3] == "NO"


def test_a_renamed_row_is_found_by_file_and_amount_for_answers_and_questions(mongo_store, records):
    """The vision model words the taxi's description its own way: the case's name still finds the row, the date
    answer is applied to it, and its question counts as the one expected."""
    from agent_fakes import ScriptedChatModel, say
    from fakes import FakeModel
    from fastapi.testclient import TestClient

    from ledgersync.config import Settings
    from server import create_app

    from ledgersync import adapter
    case = ROOT / "eval" / "agent_cases" / "missing-date-must-ask"
    rows = agent_eval.PreparedRows()
    rows.install()
    prepared = adapter.to_transactions
    adapter.to_transactions = lambda *a, **k: [   # the vision model words the taxi its own way
        t.model_copy(update={"description": "Taxi fare"}) if "Leeds" in t.description else t
        for t in prepared(*a, **k)]
    try:
        app = create_app(Settings(warmup=False), model_client=FakeModel([]), store=mongo_store,
                         chat_model=ScriptedChatModel(then=say("Done.")))
        with TestClient(app, headers={"X-LedgerSync": "1"}) as api:
            rows.use(agent_eval.case_files(case))   # read as --read model would: rows from the files, names by amount
            result = agent_eval.run_case(api, mongo_store, records, case, None, "scripted")
    finally:
        rows.uninstall()

    assert result["answers_not_applied"] == []
    assert result["questions"]["passed"], result["questions"]
    assert result["row_fallbacks"] == [{"expected": {"file": "IMG_20261009_081502.png",
                                                     "description": "Leeds City Cabs taxi, Leeds Station to Kirkstall"},
                                        "found": {"file": "IMG_20261009_081502.png", "description": "Taxi fare"}}]


def test_a_decision_must_cover_exactly_the_expected_rows():
    keep, drop = {"file": "a.txt", "description": "K"}, {"file": "b.csv", "description": "D"}
    expected = {"resolutions": [{"rule": "R2", "row": keep, "arguments": {"keep": keep, "drop": [drop]}}],
                "automatic": [], "from_answers": []}
    ids = agent_eval.exact_ids({1: keep, 2: drop, 7: {"file": "c", "description": "X"}})
    for row_ids in ([1, 2, 7], [2], [1]):   # an extra wrong row; only the secondary row; only the main row
        diff = agent_eval.score_decisions(expected, [{"status": "applied", "rule": "R2", "row_ids": row_ids}], ids)
        assert diff == [{"missing": {"rule": "R2", "row": keep}},
                        {"unexpected": {"row_ids": row_ids, "rule": "R2"}}]


def _names_case(folder, rows):
    """A case folder with one file, x.csv, whose prepared rows are `rows`, and no answers."""
    (folder / "documents").mkdir(parents=True)
    (folder / "documents" / "x.csv").write_text("x")
    (folder / "documents" / "x.csv.rows.json").write_text(json.dumps({"file": "x.csv", "kind": "table",
                                                                       "bank_account": None, "transactions": rows}))
    (folder / "notes.md").write_text("## Answers\n\n```json\n[]\n```\n")
    return folder


def _row(description, gross="10.00", direction="out", date="2026-10-01"):
    return {"description": description, "gross": gross, "direction": direction, "date": date,
            "account_code": "7500", "source": "table", "method": "llm", "document_type": "statement"}


def _store_rows(mongo_store, *rows):
    """The year holds x.csv with these rows, as the model read them."""
    import datetime as dt
    from ledgersync import ledger
    from ledgersync.models import ClientFields, Transaction
    fields = json.loads((ROOT / "eval" / "agent_cases" / "clean-month" / "client.json").read_text())
    fields["name"] = f'{fields["name"]} {len(mongo_store.list_clients()) + 1}'   # two clients can't share a name
    client = ledger.add_client(mongo_store, ClientFields.model_validate(fields))
    mongo_store.add_upload(client.id, "x.csv", "table", [Transaction.model_validate(r) for r in rows],
                           year_start=dt.date(2026, 4, 1))
    return client.id


def name(description):
    return {"file": "x.csv", "description": description}


def test_the_amount_fallback_checks_direction_and_date_and_flags_what_it_used(mongo_store, tmp_path):
    case = _names_case(tmp_path / "one", [_row("Payment")])
    client_id = _store_rows(mongo_store, _row("Credit", direction="in"), _row("Pay"), _row("Late", date="2026-10-09"))
    names = agent_eval.RowNames(mongo_store, client_id, case, fallback=True)
    assert names.id(name("Payment")) is not None and names.id(name("Payment")) == names.id(name("Payment"))
    assert [f["expected"]["description"] for f in names.fallbacks] == ["Payment"]
    assert names.fallbacks[0]["found"]["description"] == "Pay"   # not the refund, nor the other date

    refund = _names_case(tmp_path / "two", [_row("Refund")])
    client_id = _store_rows(mongo_store, _row("Credit", direction="in"))
    assert agent_eval.RowNames(mongo_store, client_id, refund, fallback=True).id(name("Refund")) is None


def test_two_names_cannot_map_to_one_row_and_a_tie_is_not_guessed(mongo_store, tmp_path):
    case = _names_case(tmp_path / "one", [_row("A"), _row("B")])
    client_id = _store_rows(mongo_store, _row("Only one"))
    names = agent_eval.RowNames(mongo_store, client_id, case, fallback=True)
    assert [names.id(name("A")), names.id(name("B"))].count(None) == 1

    tied = _names_case(tmp_path / "tied", [_row("A")])
    client_id = _store_rows(mongo_store, _row("P"), _row("Q"))
    names = agent_eval.RowNames(mongo_store, client_id, tied, fallback=True)
    assert names.id(name("A")) is None and "2 rows" in names.unmatched[0]["why"]


def test_without_the_fallback_an_unmatched_name_stays_unmatched(mongo_store, tmp_path):
    case = _names_case(tmp_path, [_row("A")])
    client_id = _store_rows(mongo_store, _row("Renamed"))
    names = agent_eval.RowNames(mongo_store, client_id, case)
    assert names.id(name("A")) is None and names.fallbacks == []


def test_run_case_saves_the_runs_transcript(mongo_store, records, tmp_path):
    """The demo on a chat model that says "Done.": the run's ids are in its result, and the transcript holds the
    thread's messages from the chat's checkpoints, the events of the turn, and each answer route's reply."""
    from agent_fakes import ScriptedChatModel, say
    from fakes import FakeModel
    from fastapi.testclient import TestClient
    from langgraph.checkpoint.mongodb import MongoDBSaver

    from ledgersync.config import Settings
    from server import create_app

    rows = agent_eval.PreparedRows()
    rows.install()
    try:
        app = create_app(Settings(warmup=False), model_client=FakeModel([]), store=mongo_store,
                         chat_model=ScriptedChatModel(then=say("Done.")))
        saver = MongoDBSaver(mongo_store.client, db_name=f"{mongo_store.db_name}_checkpoints")
        with TestClient(app, headers={"X-LedgerSync": "1"}) as api:
            result = agent_eval.run_case(api, mongo_store, records, ROOT / "demo" / "northbridge", rows, "scripted",
                                         run=2, transcripts=tmp_path / "runs", saver=saver, label="demo")
    finally:
        rows.uninstall()

    saved = json.loads((tmp_path / "runs" / "demo-r2.json").read_text())
    assert result["transcript"] == "demo-r2.json" and result["run"] == 2
    assert saved["thread_id"] == result["thread_id"] and saved["client_id"] == result["client_id"]
    assert saved["result"]["case"] == result["case"]
    humans = [m for m in saved["messages"] if m["type"] == "human"]
    assert humans and "Review these documents" in humans[0]["content"]
    assert "Done." in [m["content"] for m in saved["messages"] if m["type"] == "ai"]
    assert [kind for kind, data in saved["events"]][-1] == "done"
    assert saved["answers"] and all(a["status"] == 200 for a in saved["answers"] if "status" in a)
    # what the review left and what the answers added, as stored
    assert {r["description"] for r in saved["rows_after_review"]} <= {r["description"] for r in saved["rows_final"]}
    assert len(saved["rows_final"]) > len(saved["rows_after_review"])   # the Brightline invoice's row
    assert saved["questions_after_review"] and isinstance(saved["decisions"], list)


R5_ROW = {"file": "inv.pdf", "description": "Fibre"}
R5_EXPECTED = {"resolutions": [{"action": "set_vat_from_document", "rule": "R5", "row": R5_ROW,
                                "arguments": {"vat": "12.00"}}], "automatic": [], "from_answers": []}


def _r5(decisions, vat, **kw):
    rows_read = {805: {"vat": vat}} if kw.get("read", True) else None
    return agent_eval.score_decisions(R5_EXPECTED, decisions, lambda name: 805, rows_read=rows_read)


def test_an_r5_the_reader_already_booked_counts_as_in_the_reading_not_missing():
    assert _r5([], "12.00") == [{"already_in_reading": {"rule": "R5", "row": R5_ROW}}]


@pytest.mark.parametrize("vat", [None, "10.00"])
def test_an_r5_is_missing_when_the_reading_has_no_or_another_vat(vat):
    assert _r5([], vat) == [{"missing": {"rule": "R5", "row": R5_ROW}}]


def test_an_r5_is_missing_without_a_reading_to_check():
    assert _r5([], "12.00", read=False) == [{"missing": {"rule": "R5", "row": R5_ROW}}]


def test_an_applied_r5_is_matched_whatever_the_reading_says():
    applied = {"status": "applied", "rule": "R5", "row_ids": [805]}
    assert _r5([applied], "12.00") == []


def test_a_refused_r5_on_the_row_leaves_it_missing():
    refused = {"status": "refused", "rule": "R5", "row_ids": [805]}
    assert _r5([refused], "12.00") == [{"missing": {"rule": "R5", "row": R5_ROW}}]


def test_an_r5_on_another_row_is_unexpected_and_the_expected_one_stays_in_the_reading():
    other = {"status": "applied", "rule": "R5", "row_ids": [900]}
    assert _r5([other], "12.00") == [{"already_in_reading": {"rule": "R5", "row": R5_ROW}},
                                     {"unexpected": {"row_ids": [900], "rule": "R5"}}]


def test_a_case_is_added_though_an_earlier_one_left_a_client_of_the_same_name(mongo_store, records):
    # Every case's client is Northbridge Consulting Ltd, and two clients that aren't archived can't share a name:
    # the second case of an eval was refused, and every case after it.
    from agent_fakes import ScriptedChatModel, say
    from fakes import FakeModel
    from fastapi.testclient import TestClient

    from ledgersync.config import Settings
    from server import create_app

    case, other = ROOT / "eval" / "agent_cases" / "clean-month", ROOT / "eval" / "agent_cases" / "combined-vat"
    app = create_app(Settings(warmup=False), model_client=FakeModel([]), store=mongo_store,
                     chat_model=ScriptedChatModel(then=say("Done.")))
    with TestClient(app, headers={"X-LedgerSync": "1"}) as api:
        first = agent_eval._add_client(api, mongo_store, records, case)
        second = agent_eval._add_client(api, mongo_store, records, other)
        third = agent_eval._add_client(api, mongo_store, records, case)       # a second run of the first case
    assert len({first, second, third}) == 3
    assert [c.id for c in mongo_store.list_clients()] == [third]             # the one the chat starts from
    assert sorted(c.id for c in mongo_store.list_clients(archived=True)) == sorted([first, second])
    demo_id = agent_eval._add_client(None, mongo_store, records, ROOT / "demo" / "northbridge")   # the demo resets one
    assert [c.name for c in mongo_store.list_clients()].count("Northbridge Consulting Ltd") == 1
    assert mongo_store.get_client(demo_id).archived is False
