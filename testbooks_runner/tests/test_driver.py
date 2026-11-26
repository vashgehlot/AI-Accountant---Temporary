import csv
import shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from testbooks_runner import books, driver, mapping
from testbooks_runner.api import AppError
from testbooks_runner.model import Period, Unit
from testbooks_runner.runs import Progress, load_progress, save_progress
from testbooks_runner.tests.fake_api import FakeApi
from testbooks_runner.tests.helpers import write_mini_client

FIX = Path(__file__).parent / "fixtures" / "set"
BASE = datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc)
FIELDS = "doc_id,file,arrived,kind,issuer,recipient,number,date,currency,net,vat,gross,treatment,reason,cases".split(",")


class Clock:
    """Simulated time: sleeping moves it, so waits take no real time."""

    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds

    def now(self):
        return BASE + timedelta(seconds=self.t)


@pytest.fixture
def mini(tmp_path):
    shutil.copytree(FIX, tmp_path / "set")
    return write_mini_client(tmp_path / "set")


@pytest.fixture
def unit(mini):
    return Unit("mini", "client", mini, Period(date(2023, 4, 1), date(2024, 3, 31)))


@pytest.fixture
def key(mini):
    return books.load_key(mini / "key" / "2024-03-31")


@pytest.fixture
def profile(mini):
    return books.load_profile(mini)


@pytest.fixture
def progress():
    return Progress(client_id=1, app_year_start="2023-04-01", bank_codes={"hsbc": "1200", "amex": "1240"})


@pytest.fixture
def unit_dir(tmp_path):
    d = tmp_path / "unit"
    d.mkdir()
    return d


def add_files(mini, names, batch="2023-06-01"):
    """Put files into a batch folder and list them in documents.csv, so files_to_send sends them."""
    docs = mini / "key" / "2024-03-31" / "documents.csv"
    with docs.open("a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, FIELDS, lineterminator="\n")
        for n, name in enumerate(names):
            rel = f"inbox/{batch}/{name}"
            (mini / rel).parent.mkdir(parents=True, exist_ok=True)
            (mini / rel).write_bytes(b"data " + name.encode())
            w.writerow({"doc_id": f"X-{batch}-{n}", "file": rel, "arrived": batch, "kind": "other"})
    return [f"inbox/{batch}/{name}" for name in names]


def send(fake, unit, key, profile, progress, unit_dir, review="off", clock=None, **kw):
    clock = clock or Clock()
    key = books.load_key(unit.key_dir)  # re-read: a test may have listed more files
    options = driver.Options(review=review, poll=1.0, job_timeout=60.0, review_timeout=100.0, review_grace=25.0)
    driver.send_batches(fake, unit, key, profile, progress, options, unit_dir=unit_dir,
                        clock=clock, now=clock.now, sleep=clock.sleep, **kw)


def analyzed(fake):
    return [c[1] for c in fake.calls if c[0] == "analyze"]


def test_set_up_creates_the_client_and_its_opening(unit, key, profile):
    fake = FakeApi()
    progress = Progress()
    chart = mapping.load_chart()
    warnings = driver.set_up(fake, unit, key, profile, chart, progress, driver.Options())
    names = [c[0] for c in fake.calls]
    assert names.index("create_client") < names.index("put_opening")
    assert progress.client_id == 1 and progress.app_year_start == "2023-04-01"
    assert progress.bank_codes == {"hsbc": "1200", "amex": "1240"}
    assert isinstance(warnings, list)
    opening = next(c[1] for c in fake.calls if c[0] == "put_opening")
    assert opening[0] == 1 and opening[1]["lines"]
    # a second call changes nothing
    fake.calls.clear()
    assert driver.set_up(fake, unit, key, profile, chart, progress, driver.Options()) == []
    assert fake.calls == []


def test_set_up_names_the_dates_when_no_year_matches(unit, key, profile):
    fake = FakeApi()
    fake.years_list = [{"start": "2022-04-01", "end": "2023-03-31", "label": "", "closed": False}]
    chart = mapping.load_chart()
    with pytest.raises(driver.SetupError, match="2024-03-31"):
        driver.set_up(fake, unit, key, profile, chart, Progress(), driver.Options())


def test_batches_in_date_order_never_more_than_five_reading(mini, unit, key, profile, progress, unit_dir):
    rels = add_files(mini, [f"f{n}.pdf" for n in range(7)])
    fake = FakeApi()
    send(fake, unit, key, profile, progress, unit_dir)
    assert fake.max_in_flight <= 5 and fake.max_in_flight > 1
    assert progress.batches_done == ["2023-04-12", "2023-05-09", "2023-06-01"]
    assert all(progress.uploads[r]["status"] == "saved" for r in rels)
    names = [Path(a[2]).name for a in analyzed(fake)]
    assert names[0] == "2023-03-31_prior_tb.xlsx"
    assert {"2023-04-15_cabot_62874.pdf", "2023-04-01_hsbc-statement_2023-04-30.csv"} == set(names[1:3])
    assert not any("99999" in n for n in names)  # next year's file is not sent


def test_entry_fields_and_epoch_times(unit, key, profile, progress, unit_dir):
    fake = FakeApi()
    send(fake, unit, key, profile, progress, unit_dir)
    entry = progress.uploads["inbox/2023-04-12/2023-03-31_prior_tb.xlsx"]
    assert set(entry) == {"status", "job_id", "upload_id", "error", "submitted", "finished", "tries"}
    assert entry["status"] == "saved" and entry["tries"] == 1 and entry["upload_id"].startswith("up-")
    assert entry["error"] is None
    assert BASE.timestamp() <= entry["submitted"] <= entry["finished"]


def test_statement_gets_its_bank_account(unit, key, profile, progress, unit_dir):
    fake = FakeApi()
    send(fake, unit, key, profile, progress, unit_dir)
    accounts = {Path(a[2]).name: a[3] for a in analyzed(fake)}
    assert accounts["2023-04-01_hsbc-statement_2023-04-30.csv"] == "1200"
    assert accounts["2023-04-15_cabot_62874.pdf"] is None
    assert accounts["2023-03-31_prior_tb.xlsx"] is None
    assert all(a[0] == 1 and a[1] == date(2023, 4, 1) for a in analyzed(fake))


def test_stripe_export_goes_without_an_account(mini, unit, key, profile, progress, unit_dir):
    add_files(mini, ["stripe-export.csv"])
    fake = FakeApi()
    send(fake, unit, key, profile, progress, unit_dir)
    accounts = {Path(a[2]).name: a[3] for a in analyzed(fake)}
    assert accounts["stripe-export.csv"] is None


def test_refusal_recorded_and_the_batch_goes_on(mini, unit, key, profile, progress, unit_dir):
    a, b = add_files(mini, ["a.pdf", "b.pdf"])
    fake = FakeApi()
    fake.raise_on = {"a.pdf": AppError(413, "file_too_large", "too big")}
    send(fake, unit, key, profile, progress, unit_dir)
    assert progress.uploads[a]["status"] == "refused" and progress.uploads[b]["status"] == "saved"
    assert progress.uploads[a]["error"] == {"code": "file_too_large", "message": "too big", "status": 413}
    assert "2023-06-01" in progress.batches_done


def test_job_failing_invalid_input_is_refused_and_not_retried(mini, unit, key, profile, progress, unit_dir):
    (a,) = add_files(mini, ["a.pdf"])
    fake = FakeApi()
    fake.job_script = {"a.pdf": [{"status": "failed", "error": {
        "code": "invalid_input", "message": "Choose which bank account", "status_code": 422}}]}
    send(fake, unit, key, profile, progress, unit_dir)
    assert progress.uploads[a]["status"] == "refused" and progress.uploads[a]["tries"] == 1
    assert progress.uploads[a]["error"]["code"] == "invalid_input"
    assert len([x for x in analyzed(fake) if Path(x[2]).name == "a.pdf"]) == 1


def test_provider_failure_retried_once(mini, unit, key, profile, progress, unit_dir):
    a, b = add_files(mini, ["a.pdf", "b.pdf"])
    limited = {"status": "failed", "error": {"code": "ai_rate_limited", "message": "slow down", "status_code": 429}}
    fake = FakeApi()
    fake.job_script = {"a.pdf": [limited, {"status": "succeeded", "result": {"upload_id": "up-a"}}],
                       "b.pdf": [limited]}
    send(fake, unit, key, profile, progress, unit_dir)
    assert progress.uploads[a]["status"] == "saved" and progress.uploads[a]["tries"] == 2
    assert progress.uploads[b]["status"] == "failed" and progress.uploads[b]["tries"] == 2
    assert progress.uploads[b]["error"]["code"] == "ai_rate_limited"
    assert len([x for x in analyzed(fake) if Path(x[2]).name == "b.pdf"]) == 2


def test_503_at_submission_retried_once(mini, unit, key, profile, progress, unit_dir):
    a, b = add_files(mini, ["a.pdf", "b.pdf"])
    fake = FakeApi()
    fake.raise_on = {"a.pdf": [AppError(503, "ai_offline", "offline"), None],
                     "b.pdf": AppError(503, "ai_offline", "offline")}
    send(fake, unit, key, profile, progress, unit_dir)
    assert progress.uploads[a]["status"] == "saved" and progress.uploads[a]["tries"] == 2
    assert progress.uploads[b]["status"] == "failed" and progress.uploads[b]["tries"] == 2
    assert progress.uploads[b]["error"]["status"] == 503


def test_a_retry_waits_before_it_sends_the_file_again(mini, unit, key, profile, progress, unit_dir):
    # the app keeps a failed model check for 15 seconds, so an immediate retry meets the same 503
    a, b = add_files(mini, ["a.pdf", "b.pdf"])
    limited = {"status": "failed", "error": {"code": "ai_rate_limited", "message": "slow down", "status_code": 429}}
    fake = FakeApi()
    fake.raise_on = {"a.pdf": [AppError(503, "ai_offline", "offline"), None]}
    fake.job_script = {"b.pdf": [limited, {"status": "succeeded", "result": {"upload_id": "up-b"}}]}
    clock, times = Clock(), {}
    original = fake.analyze

    def spy(client_id, year_start, path, bank_account):
        times.setdefault(Path(path).name, []).append(clock())
        return original(client_id, year_start, path, bank_account)

    fake.analyze = spy
    send(fake, unit, key, profile, progress, unit_dir, clock=clock)
    assert progress.uploads[a]["status"] == "saved" and progress.uploads[b]["status"] == "saved"
    for name in ("a.pdf", "b.pdf"):
        first, second = times[name]
        assert second - first >= driver.Options().retry_pause == 20, name


def test_other_errors_at_submission_are_refused(mini, unit, key, profile, progress, unit_dir):
    (a,) = add_files(mini, ["a.pdf"])
    fake = FakeApi()
    fake.raise_on = {"a.pdf": AppError(422, "invalid_input", "no")}
    send(fake, unit, key, profile, progress, unit_dir)
    assert progress.uploads[a]["status"] == "refused" and progress.uploads[a]["tries"] == 1


def test_no_rows_failed_and_cancelled_jobs(mini, unit, key, profile, progress, unit_dir):
    a, b, c = add_files(mini, ["a.pdf", "b.pdf", "c.pdf"])
    fake = FakeApi()
    fake.job_script = {
        "a.pdf": [{"status": "succeeded", "result": {}}],
        "b.pdf": [{"status": "cancelled"}],
        "c.pdf": [{"status": "failed", "error": {"code": "mystery", "message": "?", "status_code": 500}}],
    }
    send(fake, unit, key, profile, progress, unit_dir)
    assert progress.uploads[a]["status"] == "no rows" and progress.uploads[a]["upload_id"] is None
    assert progress.uploads[b]["status"] == "failed" and progress.uploads[b]["tries"] == 1
    assert progress.uploads[c]["status"] == "failed" and progress.uploads[c]["tries"] == 1


def test_job_unfinished_at_the_timeout_is_failed(mini, unit, key, profile, progress, unit_dir):
    (a,) = add_files(mini, ["a.pdf"])
    fake = FakeApi()
    fake.job_script = {"a.pdf": [{"status": "running"}]}
    clock = Clock()
    send(fake, unit, key, profile, progress, unit_dir, clock=clock)
    assert progress.uploads[a]["status"] == "failed" and progress.uploads[a]["tries"] == 1
    assert clock.t >= 60


def test_waits_for_the_review_after_a_batch(mini, unit, key, profile, progress, unit_dir):
    prior = "2023-03-31_prior_tb.xlsx"  # refused, so the first batch saves nothing and waits for nothing
    slow = "2023-04-15_cabot_62874.pdf"
    fake = FakeApi()
    fake.raise_on = {prior: AppError(413, "file_too_large", "x")}
    fake.job_script = {slow: [{"status": "running"}] * 3 + [{"status": "succeeded", "result": {"upload_id": "u"}}]}
    clock = Clock()
    seen = []

    def reviews(client_id):
        # the slow job finished by now, so the batch's last finish time is known
        last = max(e["finished"] for r, e in progress.uploads.items() if "2023-05-09" in r)
        since = datetime.fromtimestamp(last, timezone.utc)
        script = [
            [{"id": "old", "status": "done", "started_at": (since - timedelta(seconds=1)).isoformat()}],
            [{"id": "new", "status": "running", "started_at": since.isoformat()}],
            [{"id": "new", "status": "done", "started_at": since.isoformat()}],
        ]
        seen.append(clock())
        return script[min(len(seen) - 1, 2)]

    fake.reviews = reviews
    send(fake, unit, key, profile, progress, unit_dir, review="automatic", clock=clock)
    # the older finished review is ignored, the running one waited for, then the done one ends the wait
    assert len(seen) == 3 and seen[1] > seen[0] and seen[2] > seen[1]
    assert progress.review_waits == {"2023-05-09": "done"}
    assert progress.batches_done == ["2023-04-12", "2023-05-09"]


def test_a_wait_with_no_review_is_recorded_as_none(unit, key, profile, progress, unit_dir):
    fake = FakeApi()
    send(fake, unit, key, profile, progress, unit_dir, review="automatic")
    assert progress.review_waits == {"2023-04-12": "none", "2023-05-09": "none"}
    assert load_progress(unit_dir).review_waits == progress.review_waits


def test_a_review_that_never_finishes_is_recorded_as_timeout_and_the_run_goes_on(unit, key, profile, progress,
                                                                               unit_dir):
    fake = FakeApi()
    fake.review_script = [[{"id": "r", "status": "running", "started_at": (BASE + timedelta(days=1)).isoformat()}]]
    send(fake, unit, key, profile, progress, unit_dir, review="automatic")
    assert set(progress.review_waits.values()) == {"timeout"}
    assert progress.batches_done == ["2023-04-12", "2023-05-09"]


def test_no_review_wait_when_review_is_off(unit, key, profile, progress, unit_dir):
    fake = FakeApi()
    send(fake, unit, key, profile, progress, unit_dir, review="off")
    assert "reviews" not in [c[0] for c in fake.calls]


def test_no_review_wait_when_nothing_was_saved(mini, unit, key, profile, progress, unit_dir):
    fake = FakeApi()
    fake.raise_on = {n: AppError(413, "file_too_large", "x") for n in
                     ["2023-03-31_prior_tb.xlsx", "2023-04-15_cabot_62874.pdf",
                      "2023-04-01_hsbc-statement_2023-04-30.csv"]}
    send(fake, unit, key, profile, progress, unit_dir, review="automatic")
    assert "reviews" not in [c[0] for c in fake.calls]


def test_resume_skips_done_batches_and_counts_same_file_as_saved(unit, key, profile, progress, unit_dir):
    progress.batches_done = ["2023-04-12"]
    fake = FakeApi()
    fake.raise_on = {"2023-04-15_cabot_62874.pdf": AppError(409, "same_file", "Skipped")}
    send(fake, unit, key, profile, progress, unit_dir)
    names = [Path(a[2]).name for a in analyzed(fake)]
    assert "2023-03-31_prior_tb.xlsx" not in names
    assert progress.uploads["inbox/2023-05-09/2023-04-15_cabot_62874.pdf"]["status"] == "same file"
    assert progress.batches_done == ["2023-04-12", "2023-05-09"]


def test_resume_inside_a_batch_skips_finished_files(unit, key, profile, progress, unit_dir):
    done = "inbox/2023-05-09/2023-04-15_cabot_62874.pdf"
    progress.uploads[done] = {"status": "saved", "job_id": "j", "upload_id": "u", "error": None,
                              "submitted": 1.0, "finished": 2.0, "tries": 1}
    progress.batches_done = ["2023-04-12"]
    fake = FakeApi()
    send(fake, unit, key, profile, progress, unit_dir)
    assert [Path(a[2]).name for a in analyzed(fake)] == ["2023-04-01_hsbc-statement_2023-04-30.csv"]
    assert progress.uploads[done]["upload_id"] == "u"


def test_progress_is_saved_after_each_file(unit, key, profile, progress, unit_dir):
    fake = FakeApi()
    seen = []
    original = fake.job

    def spy(job_id):
        seen.append(len(load_progress(unit_dir).uploads))
        return original(job_id)

    fake.job = spy
    send(fake, unit, key, profile, progress, unit_dir)
    assert seen[0] == 0 and max(seen) >= 1
    assert len(load_progress(unit_dir).uploads) == 3


def test_spend_guard_stops_after_saving(unit, key, profile, progress, unit_dir):
    fake = FakeApi()
    with pytest.raises(driver.Stopped):
        send(fake, unit, key, profile, progress, unit_dir, after_batch=lambda: False)
    saved = load_progress(unit_dir)
    assert saved.batches_done == ["2023-04-12"]
    assert len(analyzed(fake)) == 1


def test_wait_jobs_returns_finished_and_gives_up_on_the_rest():
    fake = FakeApi()
    fake.job_script = {"a.pdf": [{"status": "running"}, {"status": "succeeded"}], "b.pdf": [{"status": "running"}]}
    ids = [fake.analyze(1, date(2023, 4, 1), Path("a.pdf"), None), fake.analyze(1, date(2023, 4, 1), Path("b.pdf"), None)]
    clock = Clock()
    jobs = driver.wait_jobs(fake, ids, timeout=10, poll=1, clock=clock, sleep=clock.sleep)
    assert jobs[ids[0]]["status"] == "succeeded" and jobs[ids[1]]["status"] == "running"
    assert 10 <= clock.t < 12


def wait(fake, since=BASE, **kw):
    clock = Clock()
    args = {"timeout": 100, "grace": 25, "poll": 1, **kw}
    return driver.wait_review(fake, 1, since, clock=clock, sleep=clock.sleep, **args), clock


def test_wait_review_none_when_nothing_starts():
    fake = FakeApi()
    fake.review_script = [[{"id": "old", "status": "done", "started_at": (BASE - timedelta(hours=1)).isoformat()}]]
    result, clock = wait(fake)
    assert result == "none" and 25 <= clock.t < 27


def test_wait_review_an_older_running_review_keeps_it_waiting_and_naive_times_are_utc():
    fake = FakeApi()
    old = {"id": "old", "status": "running", "started_at": (BASE - timedelta(hours=1)).isoformat()}
    fake.review_script = [[old]] * 40 + [[{"id": "new", "status": "limited",
                                             "started_at": BASE.replace(tzinfo=None).isoformat()}, old]]
    result, clock = wait(fake)
    assert result == "done" and clock.t > 25


def test_wait_review_times_out_and_accepts_a_trailing_z():
    fake = FakeApi()
    fake.review_script = [[{"id": "r", "status": "running", "started_at": BASE.strftime("%Y-%m-%dT%H:%M:%SZ")}]]
    result, clock = wait(fake, timeout=30)
    assert result == "timeout" and 30 <= clock.t < 32


def test_window_rolls_a_slow_job_does_not_hold_back_the_next_files(mini, unit, key, profile, progress, unit_dir):
    names = ["a_slow.pdf"] + [f"f{n}.pdf" for n in range(6)]
    add_files(mini, names)
    fake = FakeApi()
    fake.job_script = {"a_slow.pdf": [{"status": "running"}] * 8 + [{"status": "succeeded", "result": {"upload_id": "u"}}]}
    submitted_when_slow_finished = []
    original = fake.job

    def spy(job_id):
        job = original(job_id)
        if fake._job_file[job_id] == "a_slow.pdf" and job["status"] == "succeeded":
            submitted_when_slow_finished.append(
                len([a for a in analyzed(fake) if Path(a[2]).name in names]))
        return job

    fake.job = spy
    send(fake, unit, key, profile, progress, unit_dir)
    assert submitted_when_slow_finished == [7]  # all seven were submitted while the slow one was still reading
    assert fake.max_in_flight == 5


def test_a_retry_counts_against_the_window(mini, unit, key, profile, progress, unit_dir):
    names = ["a.pdf"] + [f"f{n}.pdf" for n in range(5)]
    add_files(mini, names)
    limited = {"status": "failed", "error": {"code": "ai_rate_limited", "message": "slow", "status_code": 429}}
    slow = [{"status": "running"}] * 3 + [{"status": "succeeded", "result": {"upload_id": "u"}}]
    fake = FakeApi()
    fake.job_script = {"a.pdf": [limited, limited], **{f"f{n}.pdf": slow for n in range(5)}}
    send(fake, unit, key, profile, progress, unit_dir)
    assert fake.max_in_flight <= 5
    assert progress.uploads["inbox/2023-06-01/a.pdf"]["tries"] == 2
    assert progress.uploads["inbox/2023-06-01/a.pdf"]["status"] == "failed"
    assert all(progress.uploads[f"inbox/2023-06-01/f{n}.pdf"]["status"] == "saved" for n in range(5))


def test_a_poll_that_raises_fails_that_file_and_the_unit_goes_on(unit, key, profile, progress, unit_dir):
    fake = FakeApi()
    fake.raise_on = {"job": [AppError(404, "job_not_found", "No such job")]}
    send(fake, unit, key, profile, progress, unit_dir)
    gone = progress.uploads["inbox/2023-04-12/2023-03-31_prior_tb.xlsx"]
    assert gone["status"] == "failed" and gone["error"] == {"code": "job_not_found", "message": "No such job",
                                                            "status": 404}
    assert progress.uploads["inbox/2023-05-09/2023-04-15_cabot_62874.pdf"]["status"] == "saved"
    assert progress.batches_done == ["2023-04-12", "2023-05-09"]


def test_set_up_after_a_failed_opening_does_not_create_a_second_client(unit, key, profile):
    fake = FakeApi()
    fake.raise_on = {"put_opening": [AppError(500, "boom", "down"), None]}
    progress = Progress()
    chart = mapping.load_chart()
    with pytest.raises(AppError):
        driver.set_up(fake, unit, key, profile, chart, progress, driver.Options())
    assert progress.client_id == 1 and progress.app_year_start == "2023-04-01" and not progress.opening_done
    driver.set_up(fake, unit, key, profile, chart, progress, driver.Options())
    names = [c[0] for c in fake.calls]
    assert names.count("create_client") == 1 and names.count("put_opening") == 2
    assert progress.opening_done and len(fake.clients) == 1


def test_set_up_after_a_year_mismatch_carries_on_from_the_year(unit, key, profile):
    fake = FakeApi()
    fake.years_list = [{"start": "2022-04-01", "end": "2023-03-31", "label": "", "closed": False}]
    progress = Progress()
    chart = mapping.load_chart()
    with pytest.raises(driver.SetupError):
        driver.set_up(fake, unit, key, profile, chart, progress, driver.Options())
    assert progress.client_id == 1 and "put_opening" not in [c[0] for c in fake.calls]
    fake.years_list = [{"start": "2023-04-01", "end": "2024-03-31", "label": "", "closed": False}]
    driver.set_up(fake, unit, key, profile, chart, progress, driver.Options())
    names = [c[0] for c in fake.calls]
    assert names.count("create_client") == 1 and names.count("client") == 1 and names.count("put_opening") == 1
    assert progress.bank_codes == {"hsbc": "1200", "amex": "1240"} and progress.opening_done


def test_fake_close_is_recorded():
    fake = FakeApi()
    fake.close()
    assert fake.calls == [("close", ())]
