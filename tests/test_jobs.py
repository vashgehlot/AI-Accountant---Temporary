import threading
import time

import pytest

from ledgersync.errors import JobNotFound, ModelTimeout
from ledgersync.jobs import JobStore


@pytest.fixture
def store():
    s = JobStore()
    yield s
    s.shutdown()


def finished(store, job, timeout=5):
    assert job.done.wait(timeout), "job did not finish in time"
    return store.get(job.id)


def test_successful_job_returns_result(store):
    job = finished(store, store.submit(lambda ctx: {"answer": 42}))
    assert job.status == "succeeded"
    assert job.to_dict()["result"] == {"answer": 42}


def test_progress_is_visible_while_running(store):
    reported, release = threading.Event(), threading.Event()

    def work(ctx):
        ctx.report("Reading page 1 of 2")
        reported.set()
        release.wait(5)
        return "ok"

    job = store.submit(work)
    assert reported.wait(5)
    assert (store.get(job.id).status, store.get(job.id).progress) == ("running", "Reading page 1 of 2")
    release.set()
    assert finished(store, job).status == "succeeded"


def test_ledgersync_error_becomes_failed_job_with_code(store):
    def work(ctx):
        raise ModelTimeout("Groq did not answer within 60 seconds.")

    job = finished(store, store.submit(work))
    assert job.status == "failed"
    assert job.error == {"code": "ai_timeout", "status_code": 504,
                         "message": "Groq did not answer within 60 seconds."}


def test_unexpected_error_is_reported_without_internals(store):
    def work(ctx):
        raise ValueError("secret stack detail")

    job = finished(store, store.submit(work))
    assert job.status == "failed" and job.error["code"] == "internal_error"
    assert "secret" not in job.error["message"]


def test_cancel_queued_job_never_runs(store):
    release, ran = threading.Event(), threading.Event()
    first = store.submit(lambda ctx: release.wait(5))
    second = store.submit(lambda ctx: ran.set())
    assert store.cancel(second.id).status == "cancelled"
    release.set()
    finished(store, first)
    assert not ran.wait(0.2)
    assert store.get(second.id).status == "cancelled"


def test_cancel_running_job_stops_at_next_checkpoint(store):
    started = threading.Event()

    def work(ctx):
        started.set()
        while True:
            ctx.report("working")
            time.sleep(0.01)

    job = store.submit(work)
    assert started.wait(5)
    store.cancel(job.id)
    assert finished(store, job).status == "cancelled"


def test_result_discarded_if_cancelled_during_last_step(store):
    in_call, release = threading.Event(), threading.Event()

    def work(ctx):
        in_call.set()
        release.wait(5)          # stands in for a blocking model call
        return {"data": ["late"]}

    job = store.submit(work)
    assert in_call.wait(5)
    store.cancel(job.id)
    release.set()
    job = finished(store, job)
    assert job.status == "cancelled" and job.result is None


def test_jobs_run_one_at_a_time_in_order(store):
    order = []
    jobs = [store.submit(lambda ctx, i=i: order.append(i)) for i in range(3)]
    for job in jobs:
        finished(store, job)
    assert order == [0, 1, 2]


def test_unknown_job_raises_not_found(store):
    with pytest.raises(JobNotFound, match="run it again"):
        store.get("does-not-exist")


def test_finished_jobs_expire_after_ttl():
    now = [1000.0]
    store = JobStore(ttl_seconds=60, clock=lambda: now[0])
    try:
        job = finished(store, store.submit(lambda ctx: "ok"))
        now[0] += 61
        with pytest.raises(JobNotFound):
            store.get(job.id)
    finally:
        store.shutdown()


def test_four_jobs_can_run_at_the_same_time():
    # Files of one upload are read side by side: with four workers, four jobs must overlap.
    store = JobStore(max_workers=4)
    together = threading.Barrier(4, timeout=5)
    try:
        jobs = [store.submit(lambda ctx: together.wait()) for _ in range(4)]
        assert [finished(store, job).status for job in jobs] == ["succeeded"] * 4
    finally:
        store.shutdown()


def test_one_worker_runs_jobs_one_after_another():
    store = JobStore(max_workers=1)
    lock, running, most = threading.Lock(), [0], [0]

    def work(ctx):
        with lock:
            running[0] += 1
            most[0] = max(most[0], running[0])
        time.sleep(0.05)
        with lock:
            running[0] -= 1

    try:
        for job in [store.submit(work) for _ in range(3)]:
            finished(store, job)
        assert most[0] == 1
    finally:
        store.shutdown()


@pytest.mark.parametrize("how", ["succeeds", "fails", "is cancelled while queued"])
def test_on_finish_runs_once_however_the_job_ends(how):
    store = JobStore(max_workers=1)
    ended, blocker = [], threading.Event()
    try:
        if how == "is cancelled while queued":
            store.submit(lambda ctx: blocker.wait(5))   # keeps the only worker busy
        if how == "fails":
            def work(ctx):
                raise ModelTimeout("slow")
        else:
            def work(ctx):
                return "ok"
        job = store.submit(work, on_finish=lambda: ended.append(1))
        if how == "is cancelled while queued":
            store.cancel(job.id)
        assert job.done.wait(5)
        assert ended == [1]
    finally:
        blocker.set()
        store.shutdown()
