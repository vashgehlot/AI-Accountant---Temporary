import json
from datetime import date

import pytest

from testbooks_runner import books, driver
from testbooks_runner.api import AppError
from testbooks_runner.model import Period
from testbooks_runner.runs import Progress, load_progress
from testbooks_runner.tests.fake_api import FakeApi
from testbooks_runner.tests.helpers import write_mini_client

START = "2023-04-01"
PERIOD = Period(date(2023, 4, 1), date(2024, 3, 31))
VAT = [(date(2023, 6, 1), date(2023, 8, 31))]
ALWAYS = {"client", "years", "accounts", f"ledger-{START}", f"posted-{START}", "tb-shown", "vat-2023-06-01-2023-08-31",
          "invoices", "bank", "summary", "suggestions", "questions", "decisions", "reviews"}


@pytest.fixture
def progress():
    return Progress(client_id=1, app_year_start=START)


def fake():
    api = FakeApi()
    api.clients[1] = {"id": 1, "first_year_end": "2024-03-31"}
    return api


def raw(tmp_path, which="before"):
    return tmp_path / "raw" / which


def names(folder):
    return {p.name for p in folder.iterdir()}


def test_vat_periods_inside_only(tmp_path):
    key = books.load_key(write_mini_client(tmp_path) / "key" / "2024-03-31")
    assert driver.vat_periods(key, PERIOD) == [(date(2023, 6, 1), date(2023, 8, 31))]
    # the March-May 2023 quarter starts before the year, so it is left out of any period that starts in April
    assert (date(2023, 3, 1), date(2023, 5, 31)) not in driver.vat_periods(key, PERIOD)


def test_vat_periods_in_date_order(tmp_path):
    key = books.Key(vat_returns=[{"period_start": "2023-09-01", "period_end": "2023-11-30"},
                                 {"period_start": "2023-06-01", "period_end": "2023-08-31"}])
    assert [s for s, _ in driver.vat_periods(key, PERIOD)] == [date(2023, 6, 1), date(2023, 9, 1)]


def test_snapshot_writes_every_file(tmp_path, progress):
    api = fake()
    api.returns["export_xlsx"] = b"PK\x03\x04bytes"
    api.returns["ledger"] = {"transactions": [{"id": 1}]}
    driver.take_snapshot(api, progress, tmp_path, "before", VAT)
    assert names(raw(tmp_path)) == {n + ".json" for n in ALWAYS} | {"export.xlsx"}
    assert (raw(tmp_path) / "export.xlsx").read_bytes() == b"PK\x03\x04bytes"
    assert json.loads((raw(tmp_path) / f"ledger-{START}.json").read_text()) == {"transactions": [{"id": 1}]}


def test_snapshot_survives_a_failing_call(tmp_path, progress):
    api = fake()
    api.raise_on["tb_shown"] = AppError(422, "transactions_need_fixing", "x")
    driver.take_snapshot(api, progress, tmp_path, "before", VAT)
    assert (tmp_path / "raw/before/tb-shown.error.json").exists() and (tmp_path / "raw/before/questions.json").exists()
    assert not (tmp_path / "raw/before/tb-shown.json").exists()
    assert json.loads((tmp_path / "raw/before/tb-shown.error.json").read_text()) == {
        "status": 422, "code": "transactions_need_fixing", "message": "x"}
    assert load_progress(tmp_path).before_done


def test_snapshot_vat_error_recorded_per_period(tmp_path, progress):
    api = fake()
    api.raise_on["vat"] = AppError(422, "vat_period", "outside the year")
    driver.take_snapshot(api, progress, tmp_path, "before", VAT)
    assert (raw(tmp_path) / "vat-2023-06-01-2023-08-31.error.json").exists()


def test_chat_only_in_after_and_with_a_thread(tmp_path, progress):
    api = fake()
    api.returns["thread"] = {"id": "t1", "messages": []}
    driver.take_snapshot(api, progress, tmp_path / "a", "before", [])
    progress.thread_id = "t1"
    driver.take_snapshot(api, progress, tmp_path / "b", "before", [])
    assert not (raw(tmp_path / "b") / "chat.json").exists()
    driver.take_snapshot(api, progress, tmp_path / "c", "after", [])
    assert json.loads((raw(tmp_path / "c", "after") / "chat.json").read_text()) == {"id": "t1", "messages": []}
    progress.thread_id = None
    driver.take_snapshot(api, progress, tmp_path / "d", "after", [])
    assert not (raw(tmp_path / "d", "after") / "chat.json").exists()


def test_posted_only_for_years_with_rows(tmp_path, progress):
    api = fake()
    api.years_list = [{"start": "2022-04-01", "end": "2023-03-31"}, {"start": START, "end": "2024-03-31"},
                      {"start": "2024-04-01", "end": "2025-03-31"}]

    def ledger(client_id, year_start):
        api.calls.append(("ledger", (client_id, year_start)))
        return {"transactions": [{"id": 1}] if year_start == date(2022, 4, 1) else []}
    api.ledger = ledger
    driver.take_snapshot(api, progress, tmp_path, "before", [])
    got = names(raw(tmp_path))
    assert {"ledger-2022-04-01.json", f"ledger-{START}.json", "ledger-2024-04-01.json"} <= got
    assert {n for n in got if n.startswith("posted-")} == {"posted-2022-04-01.json", f"posted-{START}.json"}


def test_scored_year_used_for_year_calls(tmp_path, progress):
    api = fake()
    driver.take_snapshot(api, progress, tmp_path, "before", VAT)
    calls = dict((n, a) for n, a in api.calls if n in {"tb_shown", "vat", "invoices"})
    assert calls["tb_shown"] == (1, date(2023, 4, 1))
    assert calls["vat"] == (1, date(2023, 4, 1), VAT[0][0], VAT[0][1])


def test_stale_error_file_removed_on_success_and_reverse(tmp_path, progress):
    api = fake()
    api.raise_on["summary"] = [AppError(500, "boom", "m"), None]
    driver.take_snapshot(api, progress, tmp_path, "before", [])
    assert (raw(tmp_path) / "summary.error.json").exists() and not (raw(tmp_path) / "summary.json").exists()
    driver.take_snapshot(api, progress, tmp_path, "before", [])
    assert (raw(tmp_path) / "summary.json").exists() and not (raw(tmp_path) / "summary.error.json").exists()
    api.raise_on["summary"] = AppError(500, "boom", "m")
    driver.take_snapshot(api, progress, tmp_path, "before", [])
    assert (raw(tmp_path) / "summary.error.json").exists() and not (raw(tmp_path) / "summary.json").exists()


def test_done_flags_saved(tmp_path, progress):
    api = fake()
    driver.take_snapshot(api, progress, tmp_path, "before", [])
    saved = load_progress(tmp_path)
    assert saved.before_done and not saved.after_done
    driver.take_snapshot(api, progress, tmp_path, "after", [])
    saved = load_progress(tmp_path)
    assert saved.before_done and saved.after_done


def test_app_down_propagates_and_marks_nothing(tmp_path, progress):
    api = fake()
    api.raise_on["bank"] = ConnectionError("down")
    with pytest.raises(ConnectionError):
        driver.take_snapshot(api, progress, tmp_path, "before", [])
    assert not progress.before_done
    assert not (tmp_path / "progress.json").exists()
