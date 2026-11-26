"""The client-level test set (eval/jobs/) and its runner: a year's trial balance scored against the one worked out by
hand, and the runner's flow through the API, driven by scripted answers. No database or model."""
import json
import subprocess
import sys
from decimal import Decimal as D
from pathlib import Path

import pytest

from job_scoring import compare, net_by_account
import run_eval
import run_job_eval

EVAL_DIR = Path(__file__).parent.parent / "eval"


def test_net_by_account_is_debit_minus_credit_without_zeros():
    trial_balance = {"lines": [{"code": "1200", "debit": "0.00", "credit": "72.00"},
                               {"code": "7502", "debit": "60.00", "credit": "0.00"},
                               {"code": "2201", "debit": "12.00", "credit": "0.00"},
                               {"code": "9998", "debit": "0.00", "credit": "0.00"}]}
    assert net_by_account(trial_balance) == {"1200": D("-72.00"), "7502": D("60.00"), "2201": D("12.00")}


def test_compare_lists_every_account_that_differs():
    assert compare({"7502": D("60.00"), "1200": D("-72.00")}, {"7500": D("60.00"), "1200": D("-72.00")}) == [
        {"code": "7500", "expected": "0.00", "actual": "60.00", "difference": "60.00"},
        {"code": "7502", "expected": "60.00", "actual": "0.00", "difference": "-60.00"}]


def test_every_case_is_complete_and_its_expected_trial_balance_balances():
    cases = sorted((EVAL_DIR / "jobs").iterdir())
    assert len(cases) == 7
    for case in cases:
        assert {p.name for p in case.iterdir()} == {"client.json", "expected_trial_balance.json", "notes.md",
                                                     "documents"}, case.name
        assert any((case / "documents").iterdir())
        client = json.loads((case / "client.json").read_text())
        assert client["first_year_end"] and client["bank_accounts"], case.name
        assert set(client.get("statements", {}).values()) <= {a["name"] for a in client["bank_accounts"]}, case.name
        assert set(client.get("statements", {})) <= {p.name for p in (case / "documents").iterdir()}, case.name
        expected = json.loads((case / "expected_trial_balance.json").read_text())
        assert sum(D(v) for v in expected.values()) == 0, case.name


def test_net_by_account_keeps_two_places_and_adds_up_repeated_codes():
    trial_balance = {"lines": [{"code": "7502", "debit": "60", "credit": "0"},
                               {"code": "7502", "debit": "0.5", "credit": "0.00"}]}
    assert {code: str(net) for code, net in net_by_account(trial_balance).items()} == {"7502": "60.50"}


# ─── The runner, against scripted answers ──────────────────────────────────────

CLIENT = {"name": "Test Co Ltd", "business_type": "limited_company", "contact_name": "Test Contact",
          "contact_email": "test-co@example.com", "vat_registered": True, "first_year_end": "2027-03-31",
          "bank_accounts": [{"name": "Current", "kind": "current"}, {"name": "Savings", "kind": "savings"}]}
ADDED_ACCOUNTS = [{"name": "Current", "kind": "current", "code": "1200"},
                  {"name": "Savings", "kind": "savings", "code": "1210"}]
EXPECTED = {"1200": "-72.00", "2201": "12.00", "7502": "60.00"}


def lines(*rows):
    return [{"code": code, "name": "", "type": "", "debit": debit, "credit": credit} for code, debit, credit in rows]


RIGHT = lines(("1200", "0.00", "72.00"), ("7502", "60.00", "0.00"), ("2201", "12.00", "0.00"))
WRONG = lines(("1200", "0.00", "72.00"), ("7500", "60.00", "0.00"), ("2201", "12.00", "0.00"))
YEAR = "2026-04-01"
TRIAL_BALANCE_PATH = f"/api/clients/7/years/{YEAR}/trial-balance"


class Resp:
    def __init__(self, status_code, body):
        self.status_code, self._body = status_code, body

    def json(self):
        return self._body


class FakeApi:
    """The API as the runner reaches it through run_eval._call, which the tests point at `call`: each request is
    answered from a script by its method and path, and kept in `calls`."""

    def __init__(self, trial_balance=RIGHT, readable=True, trial_balance_status=200, unbalanced=False):
        self.trial_balance, self.readable = trial_balance, readable
        self.trial_balance_status, self.unbalanced = trial_balance_status, unbalanced
        self.calls: list[tuple[str, str, dict]] = []
        self._reads = 0

    # The runner passes these to _call (client.get and so on), and `call` answers in their place by their names.
    def get(self, *args, **kwargs):
        raise AssertionError("called without run_eval._call")

    def post(self, *args, **kwargs):
        raise AssertionError("called without run_eval._call")

    def delete(self, *args, **kwargs):
        raise AssertionError("called without run_eval._call")

    def call(self, method, path, retries=None, **kwargs):
        verb = method.__name__.upper()
        self.calls.append((verb, path, kwargs))
        if (verb, path) == ("GET", "/api/health"):
            return Resp(200, {"model_available": True, "model": "fake-model"})
        if (verb, path) == ("POST", "/api/clients"):
            return Resp(201, {"id": 7, **kwargs["json"], "bank_accounts": ADDED_ACCOUNTS})
        if (verb, path) == ("GET", "/api/clients/7/years"):
            return Resp(200, [{"start": YEAR, "end": "2027-03-31"}])
        if (verb, path) == ("POST", "/api/analyze"):
            self._reads += 1
            return Resp(202, {"job_id": f"read-{self._reads}", "status": "queued"})
        if verb == "GET" and path.startswith("/api/jobs/read-"):
            if not self.readable:
                return Resp(200, {"status": "failed", "error": {"code": "unreadable_file"}})
            return Resp(200, {"status": "succeeded", "result": {"transactions": [{"gross": "72.00"}], "upload_id": 1}})
        if (verb, path) == ("GET", TRIAL_BALANCE_PATH):
            if self.trial_balance_status == 422:
                return Resp(422, {"detail": {"code": "transactions_need_fixing",
                                             "message": "1 problem(s) must be fixed before the trial balance."}})
            return Resp(200, {"lines": self.trial_balance, "is_balanced": not self.unbalanced})
        raise AssertionError(f"unexpected {verb} {path}")

    def sent(self, verb, path):
        return [kwargs for v, p, kwargs in self.calls if (v, p) == (verb, path)]

    def called(self, verb, path):
        return bool(self.sent(verb, path))


@pytest.fixture
def jobs(tmp_path, monkeypatch):
    """One case folder in a test set of its own, and a results folder; the runner polls without waiting."""
    case = tmp_path / "jobs" / "ltd-test"
    (case / "documents").mkdir(parents=True)
    (case / "documents" / "bank.csv").write_text("Date,Description,Amount\n01/09/2026,BT,-72.00\n")
    (case / "documents" / "note.txt").write_text("Expenses 01/09/2026\nTaxi £10.00\n")
    (case / "documents" / "savings.csv").write_text("Date,Description,Amount\n02/09/2026,Interest,1.00\n")
    (case / "client.json").write_text(json.dumps({**CLIENT, "statements": {"savings.csv": "Savings"}}))
    (case / "expected_trial_balance.json").write_text(json.dumps(EXPECTED))
    (case / "notes.md").write_text("Worked out by hand.\n")
    monkeypatch.setattr(run_job_eval, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(run_job_eval, "RESULTS_DIR", tmp_path / "results")
    monkeypatch.setattr(run_eval, "POLL_SECONDS", 0)
    return tmp_path


@pytest.fixture
def fake_api(monkeypatch):
    """A FakeApi that run_eval._call answers from."""
    api = FakeApi()
    monkeypatch.setattr(run_eval, "_call", api.call)
    return api


def run_main(api, jobs, monkeypatch):
    """Runs the runner's command line against the scripted API; its exit code and the case it reported."""
    monkeypatch.setattr(run_eval, "_call", api.call)
    code = run_job_eval.main(["--label", "test"])
    report = json.loads(next((jobs / "results").glob("*-jobs-test.json")).read_text())
    return code, report["cases"][0]


def test_a_case_is_scored_from_the_years_trial_balance(jobs, fake_api):
    outcome = run_job_eval.run_case(fake_api, jobs / "jobs" / "ltd-test", sleep=lambda s: None)
    assert fake_api.called("GET", TRIAL_BALANCE_PATH) and outcome["verdict"] == "match"
    assert (outcome["differences"], outcome["is_balanced"], outcome["error"], outcome["year_start"]) == (
        [], True, None, YEAR)
    assert outcome["run_time_s"] >= 0


def test_the_client_is_added_without_statements_and_each_document_goes_to_its_account_in_the_first_year(
        jobs, fake_api):
    run_job_eval.run_case(fake_api, jobs / "jobs" / "ltd-test", sleep=lambda s: None)
    pages = {"X-LedgerSync": "1"}
    assert fake_api.sent("POST", "/api/clients") == [{"json": CLIENT, "headers": pages}]
    reads = fake_api.sent("POST", "/api/analyze")
    assert [r["data"] for r in reads] == [
        {"client_id": "7", "year_start": YEAR, "bank_account": "1200"},
        {"client_id": "7", "year_start": YEAR, "bank_account": "1200", "text": "Expenses 01/09/2026\nTaxi £10.00\n"},
        {"client_id": "7", "year_start": YEAR, "bank_account": "1210"}]   # bank.csv, note.txt, savings.csv
    assert all(r["headers"] == pages for r in reads)
    assert [r["files"]["file"][0] for r in reads if "files" in r] == ["bank.csv", "savings.csv"]


def test_a_case_whose_trial_balance_differs_fails_with_the_differences(jobs, monkeypatch):
    code, case = run_main(FakeApi(trial_balance=WRONG), jobs, monkeypatch)
    assert code != 0
    assert (case["verdict"], case["error"]) == ("differences", None)
    assert case["differences"] == [
        {"code": "7500", "expected": "0.00", "actual": "60.00", "difference": "60.00"},
        {"code": "7502", "expected": "60.00", "actual": "0.00", "difference": "-60.00"}]


def test_a_trial_balance_that_does_not_balance_fails_the_case(jobs, monkeypatch):
    code, case = run_main(FakeApi(unbalanced=True), jobs, monkeypatch)
    assert code != 0 and (case["verdict"], case["is_balanced"]) == ("not_balanced", False)


def test_a_trial_balance_that_could_not_be_built_fails_with_what_the_api_says(jobs, monkeypatch):
    code, case = run_main(FakeApi(trial_balance_status=422), jobs, monkeypatch)
    assert code != 0
    assert (case["verdict"], case["error"]) == ("trial_balance_not_built", "trial_balance_not_built")
    assert case["error_detail"] == "1 problem(s) must be fixed before the trial balance."
    assert case["differences"] is None


def test_a_document_that_cannot_be_read_stops_the_case_before_the_trial_balance(jobs, monkeypatch):
    api = FakeApi(readable=False)
    code, case = run_main(api, jobs, monkeypatch)
    assert code != 0
    assert (case["verdict"], case["error"]) == ("analysis_failed", "analysis_failed")
    assert case["documents"][0] == {"name": "bank.csv", "bank_account": "1200", "error": "unreadable_file", "rows": 0}
    assert not api.called("GET", TRIAL_BALANCE_PATH)


def test_a_statement_for_an_account_the_client_does_not_have_stops_the_case(jobs, fake_api):
    (jobs / "jobs" / "ltd-test" / "client.json").write_text(
        json.dumps({**CLIENT, "statements": {"savings.csv": "Rainy day"}}))
    outcome = run_job_eval.run_case(fake_api, jobs / "jobs" / "ltd-test", sleep=lambda s: None)
    assert outcome["verdict"] == "unknown_bank_account" and not fake_api.called("POST", "/api/analyze")


def test_the_report_counts_the_cases_that_match(jobs, monkeypatch):
    code, _ = run_main(FakeApi(), jobs, monkeypatch)
    report = json.loads(next((jobs / "results").glob("*-jobs-test.json")).read_text())
    assert code == 0 and report["summary"] == {"cases": 1, "matched": 1, "failed": []}


def test_help_names_the_label_and_case_options():
    shown = subprocess.run([sys.executable, str(EVAL_DIR / "run_job_eval.py"), "--help"], capture_output=True,
                           text=True, check=True).stdout
    assert "--label" in shown and "--case" in shown
