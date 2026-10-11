import shutil
import json
import subprocess
from datetime import date
from pathlib import Path

import pytest
from fakes import FakeModel, transactions_json
from fastapi.testclient import TestClient

from ledgersync.config import Settings
from run_eval import check_ready, exit_code, load_cases, main, rescore, results_dir, run_all, run_case
from server import create_app

FIXTURES = Path(__file__).parent.parent / "eval" / "fixtures"
HMRC_ROW = {"description": "HMRC VAT settlement payment", "date": "2026-09-07", "amount": 1450.0,
            "direction": "out", "account": "2202 VAT Liability", "vat": None, "currency": "GBP",
            "document_type": "statement"}


@pytest.fixture
def api():
    clients = []

    def _make(model):
        client = TestClient(create_app(Settings(warmup=False), model_client=model))
        client.__enter__()
        clients.append(client)
        return client

    yield _make
    for client in clients:
        client.__exit__(None, None, None)


def test_load_cases_filters_by_id():
    cases = load_cases(FIXTURES, "csv-")
    assert cases and all(c["case"].startswith("csv-") and c["path"].exists() for c in cases)


def test_case_is_run_through_the_api_and_scored(api):
    case = load_cases(FIXTURES, "text-hmrc-vat-payment")[0]
    outcome = run_case(api(FakeModel([transactions_json(HMRC_ROW)])), case, timeout=10)
    assert (outcome["matched"], outcome["expected"], outcome["error"]) == (1, 1, None)
    assert outcome["checks"]["direction"] == [1, 1] and outcome["exact"] is True
    assert outcome["model"] == "fake-model" and outcome["latency_s"] >= 0
    assert outcome["tb_balanced"] is True                 # double entry balances by construction
    assert outcome["checks"]["account"] == [1, 1]         # 2202 VAT Liability, as expected


def test_rows_that_cannot_be_posted_count_as_no_trial_balance(api):
    # Skipping a refused trial balance would hide it from the metric.
    case = load_cases(FIXTURES, "text-hmrc-vat-payment")[0]
    outcome = run_case(api(FakeModel([transactions_json(dict(HMRC_ROW, currency="USD"))])), case, timeout=10)
    assert outcome["tb_balanced"] is False



def test_failed_case_is_recorded_not_fatal(api):
    case = load_cases(FIXTURES, "text-hmrc-vat-payment")[0]
    outcome = run_case(api(FakeModel(healthy=False)), case, timeout=10)
    assert outcome["error"] == "ai_offline"
    assert (outcome["matched"], outcome["predicted"], outcome["tb_balanced"]) == (0, 0, None)


class FlakyClient:
    """Wraps a TestClient; the first `failures` job polls fail like a dropped connection."""

    def __init__(self, client, failures):
        self.client, self.failures = client, failures

    def post(self, *args, **kwargs):
        return self.client.post(*args, **kwargs)

    def delete(self, *args, **kwargs):
        return self.client.delete(*args, **kwargs)

    def get(self, url, **kwargs):
        if url.startswith("/api/jobs/") and self.failures:
            self.failures -= 1
            raise ConnectionResetError("[Errno 54] Connection reset by peer")
        return self.client.get(url, **kwargs)


def test_dropped_connection_while_polling_is_retried(api, monkeypatch):
    # Seen in the first baseline run: one reset connection killed the whole run.
    monkeypatch.setattr("run_eval.RETRY_SECONDS", 0)
    case = load_cases(FIXTURES, "text-hmrc-vat-payment")[0]
    client = FlakyClient(api(FakeModel([transactions_json(HMRC_ROW)])), failures=2)
    outcome = run_case(client, case, timeout=10)
    assert (outcome["error"], outcome["matched"]) == (None, 1)


def test_api_that_stays_down_is_recorded_not_fatal(api, monkeypatch):
    monkeypatch.setattr("run_eval.RETRY_SECONDS", 0)
    case = load_cases(FIXTURES, "text-hmrc-vat-payment")[0]
    client = FlakyClient(api(FakeModel([transactions_json(HMRC_ROW)])), failures=99)
    outcome = run_case(client, case, timeout=10)
    assert (outcome["error"], outcome["matched"]) == ("api_unreachable", 0)


class StopOnSecondUpload:
    """Wraps a TestClient; the second document upload raises like Ctrl+C or a session ending."""

    def __init__(self, client):
        self.client, self.uploads = client, 0

    def post(self, url, **kwargs):
        if url == "/api/analyze":
            self.uploads += 1
            if self.uploads == 2:
                raise KeyboardInterrupt
        return self.client.post(url, **kwargs)

    def get(self, *args, **kwargs):
        return self.client.get(*args, **kwargs)

    def delete(self, *args, **kwargs):
        return self.client.delete(*args, **kwargs)


PAYE_ROW = {"description": "HMRC PAYE and National Insurance", "date": "2026-09-19", "amount": 2140.37,
            "direction": "out", "account": "2210 PAYE and National Insurance", "vat": None, "currency": "GBP"}


def test_interrupted_run_keeps_finished_cases(api, tmp_path):
    # Seen in the second baseline run: the session ended at case 5 and no results were kept.
    cases = load_cases(FIXTURES, "text-hmrc-vat-payment") + load_cases(FIXTURES, "text-paye")
    out = tmp_path / "run.json"
    client = StopOnSecondUpload(api(FakeModel([transactions_json(HMRC_ROW)])))
    with pytest.raises(KeyboardInterrupt):
        run_all(client, cases, out, label="t", api="test", model="fake-model", timeout=10)
    saved = json.loads(out.read_text())
    assert [c["case"] for c in saved["cases"]] == ["text-hmrc-vat-payment"]
    assert saved["summary"]["cases"] == 1


def test_resume_skips_finished_cases(api, tmp_path):
    cases = load_cases(FIXTURES, "text-hmrc-vat-payment") + load_cases(FIXTURES, "text-paye")
    out = tmp_path / "run.json"
    model = FakeModel([transactions_json(HMRC_ROW)])
    run_all(api(model), cases[:1], out, label="t", api="test", model="fake-model", timeout=10)
    model.replies.append(transactions_json(PAYE_ROW))
    report = run_all(api(model), cases, out, label="t", api="test", model="fake-model", timeout=10, resume=True)
    assert len(model.calls) == 2          # the finished case was not sent to the model again
    assert [c["case"] for c in report["cases"]] == ["text-hmrc-vat-payment", "text-paye"]
    assert report["summary"]["matched"] == 2


class RestartedApi(FlakyClient):
    """Job polls reach an API that has forgotten the job, as after a restart."""

    def get(self, url, **kwargs):
        return self.client.get("/api/jobs/forgotten" if url.startswith("/api/jobs/") else url, **kwargs)


def test_job_lost_in_an_api_restart_is_recorded_not_fatal(api):
    case = load_cases(FIXTURES, "text-hmrc-vat-payment")[0]
    outcome = run_case(RestartedApi(api(FakeModel([transactions_json(HMRC_ROW)])), 0), case, timeout=10)
    assert (outcome["error"], outcome["matched"]) == ("job_not_found", 0)


def test_resume_reruns_cases_the_harness_did_not_finish(api, tmp_path, monkeypatch):
    monkeypatch.setattr("run_eval.RETRY_SECONDS", 0)
    cases = load_cases(FIXTURES, "text-hmrc-vat-payment")
    out = tmp_path / "run.json"
    down = FlakyClient(api(FakeModel([transactions_json(HMRC_ROW)])), failures=99)
    run_all(down, cases, out, label="t", api="test", model="m", timeout=10)
    report = run_all(api(FakeModel([transactions_json(HMRC_ROW)])), cases, out, label="t", api="test",
                     model="m", timeout=10, resume=True)
    assert (report["cases"][0]["error"], report["cases"][0]["matched"]) == (None, 1)


def test_filtered_rerun_keeps_the_other_cases(api, tmp_path):
    both = load_cases(FIXTURES, "text-hmrc-vat-payment") + load_cases(FIXTURES, "text-paye")
    out = tmp_path / "run.json"
    model = FakeModel([transactions_json(HMRC_ROW), transactions_json(PAYE_ROW), transactions_json(PAYE_ROW)])
    run_all(api(model), both, out, label="t", api="test", model="m", timeout=10)
    report = run_all(api(model), both[1:], out, label="t", api="test", model="m", timeout=10,
                     resume=True, rerun=True, known_cases=both)
    assert len(model.calls) == 3                         # only text-paye ran again
    assert [c["case"] for c in report["cases"]] == ["text-hmrc-vat-payment", "text-paye"]


def test_existing_report_is_not_replaced_without_resume(capsys, tmp_path, monkeypatch):
    monkeypatch.setattr("run_eval.EVAL_DIR", tmp_path)
    try:
        (tmp_path / "fixtures").symlink_to(FIXTURES)
    except OSError:
        shutil.copytree(FIXTURES, tmp_path / "fixtures")
    existing = results_dir(private=False) / f"{date.today().isoformat()}-t.json"
    existing.parent.mkdir(parents=True)
    existing.write_text("KEEP")
    assert main(["--api", "http://127.0.0.1:9", "--label", "t"]) == 1
    assert existing.read_text() == "KEEP" and "--resume" in capsys.readouterr().err


def test_model_not_ready_stops_the_run_with_the_reason():
    assert "Set GROQ_API_KEY in .env" in check_ready({"model_available": False, "ai_error": "Set GROQ_API_KEY in .env"})
    assert check_ready({"model_available": True}) is None


def test_unfinished_cases_fail_the_run_but_model_errors_do_not():
    assert exit_code({"cases": [{"case": "a", "error": "api_unreachable"}, {"case": "b", "error": None}]}) == 1
    assert exit_code({"cases": [{"case": "a", "error": "ai_timeout"}]}) == 0


def test_report_records_run_conditions(api, tmp_path):
    cases = load_cases(FIXTURES, "text-hmrc-vat-payment")
    report = run_all(api(FakeModel([transactions_json(HMRC_ROW)])), cases, tmp_path / "run.json", label="t",
                     api="test", model="m", timeout=10, note="Groq free plan, GROQ_MAX_OUTPUT_TOKENS=4096")
    assert (report["note"], report["timeout_s"]) == ("Groq free plan, GROQ_MAX_OUTPUT_TOKENS=4096", 10)


def test_rescore_updates_saved_results_without_the_api(tmp_path):
    # The committed baseline was scored before net-instead-of-gross counted as an amount error.
    saved = {"label": "b", "date": "2026-09-28", "api": "x", "model": "m", "cases": [{
        "case": "pdf-sales-invoice", "kind": "pdf", "error": None, "latency_s": 6.4, "model": "m",
        "tb_balanced": False, "expected": 1, "predicted": 1, "matched": 0, "exact": False,
        "checks": {f: [0, 0] for f in ("amount", "date", "direction", "account", "vat", "document_type")},
        "predicted_rows": [{"date": "2026-09-30", "direction": "in", "gross": "2000.00", "vat": None,
                            "account_code": None, "description": "Strategy consultancy",
                            "has_account": False, "has_vat": False}]}]}
    out = tmp_path / "old.json"
    out.write_text(json.dumps(saved))
    report = rescore(out, load_cases(FIXTURES))
    case = report["cases"][0]
    assert (case["matched"], case["correct"], case["checks"]["amount"]) == (1, 0, [0, 1])
    assert report["summary"]["correct_rows"] == 0.0 and report["date"] == "2026-09-28"


def test_unreachable_api_exits_with_advice(capsys, tmp_path, monkeypatch):
    monkeypatch.setattr("run_eval.EVAL_DIR", tmp_path)
    try:
        (tmp_path / "fixtures").symlink_to(FIXTURES)
    except OSError:
        shutil.copytree(FIXTURES, tmp_path / "fixtures")
    assert main(["--api", "http://127.0.0.1:9", "--label", "t"]) == 2
    assert "server.py" in capsys.readouterr().err
    assert not (tmp_path / "results").exists()


def test_private_results_are_git_ignored():
    target = results_dir(private=True) / "2026-01-01-check.json"
    assert subprocess.run(["git", "check-ignore", "-q", str(target)]).returncode == 0
    assert subprocess.run(["git", "check-ignore", "-q", str(results_dir(private=False) / "x.json")]).returncode == 1


def test_rate_limited_cases_count_as_unfinished():
    # A free plan's per-minute limit is not a model failure: --resume runs those cases again.
    assert exit_code({"cases": [{"case": "a", "error": "ai_rate_limited"}]}) == 1


def test_the_harness_can_pause_between_documents_for_rate_limits(api, tmp_path):
    # Groq's free plan allows a few requests a minute: --pause spaces the documents out.
    cases = load_cases(FIXTURES, "text-hmrc-vat-payment") + load_cases(FIXTURES, "text-paye")
    slept = []
    run_all(api(FakeModel([transactions_json(HMRC_ROW), transactions_json(PAYE_ROW)])), cases, tmp_path / "run.json",
            label="t", api="test", model="m", timeout=10, pause=12, sleep=slept.append)
    assert slept == [12]
