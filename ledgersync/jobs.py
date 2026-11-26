"""In-memory background jobs: worker threads (several files are read side by side), progress,
cancel and expiry.

Good enough for a single local user; jobs are lost when the server restarts."""
from __future__ import annotations

import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .errors import JobNotFound, LedgerSyncError

logger = logging.getLogger(__name__)

QUEUED, RUNNING = "queued", "running"
SUCCEEDED, FAILED, CANCELLED = "succeeded", "failed", "cancelled"
FINISHED = frozenset({SUCCEEDED, FAILED, CANCELLED})


class JobCancelled(Exception):
    """Raised inside a job's work function once the user has cancelled it."""


@dataclass
class Job:
    id: str
    status: str = QUEUED
    progress: str = "Queued"
    result: Any = None
    error: Optional[dict] = None
    finished_at: Optional[float] = None
    committed: bool = False   # its work has been saved: a cancel can no longer discard it
    on_finish: Optional[Callable[[], None]] = None   # called once when it ends, however it ends
    cancel_requested: threading.Event = field(default_factory=threading.Event)
    done: threading.Event = field(default_factory=threading.Event)

    def to_dict(self) -> dict:
        return {"job_id": self.id, "status": self.status, "progress": self.progress,
                "result": self.result, "error": self.error}


class JobContext:
    """Given to the work function so it can report progress and notice cancellation."""

    def __init__(self, job: Job):
        self._job = job

    def report(self, progress: str) -> None:
        self.check_cancelled()
        self._job.progress = progress

    def check_cancelled(self) -> None:
        if self._job.cancel_requested.is_set() and not self._job.committed:
            raise JobCancelled()

    def commit(self) -> None:
        """Makes the job's work final, just before it saves: from here on a cancel no longer discards it, so a
        job that saved always ends succeeded. Raises JobCancelled if it was cancelled before this point."""
        self.check_cancelled()
        self._job.committed = True


class JobStore:
    def __init__(self, ttl_seconds: float = 3600.0, clock: Callable[[], float] = time.monotonic,
                 max_workers: int = 1):
        self._ttl = ttl_seconds
        self._clock = clock
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=max(1, max_workers), thread_name_prefix="ledgersync-job")

    def submit(self, work: Callable[[JobContext], Any], on_finish: Optional[Callable[[], None]] = None) -> Job:
        """Queues work. on_finish runs when the job succeeds, fails or is cancelled (even while still queued), with the
        store's lock held: it must be quick and must not call the store."""
        job = Job(id=uuid.uuid4().hex, on_finish=on_finish)
        with self._lock:
            self._purge_expired()
            self._jobs[job.id] = job
        self._executor.submit(self._run, job, work)
        return job

    def get(self, job_id: str) -> Job:
        with self._lock:
            return self._get_locked(job_id)

    def cancel(self, job_id: str) -> Job:
        with self._lock:
            job = self._get_locked(job_id)
            if job.status not in FINISHED:
                job.cancel_requested.set()
                if job.status == QUEUED:
                    self._finish_locked(job, CANCELLED, "Cancelled")
            return job

    def shutdown(self) -> None:
        for job in list(self._jobs.values()):
            job.cancel_requested.set()
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _run(self, job: Job, work: Callable[[JobContext], Any]) -> None:
        with self._lock:
            if job.status != QUEUED:          # cancelled while waiting in the queue
                return
            job.status, job.progress = RUNNING, "Starting"
        try:
            ctx = JobContext(job)
            result = work(ctx)
            ctx.check_cancelled()              # cancelled during the last step: discard the result
            outcome = {"status": SUCCEEDED, "progress": "Done", "result": result}
        except JobCancelled:
            outcome = {"status": CANCELLED, "progress": "Cancelled"}
        except LedgerSyncError as exc:
            logger.warning("Job %s failed: %s", job.id, exc.code)
            outcome = {"status": FAILED, "progress": "Failed", "error": exc.to_dict()}
        except Exception:
            logger.exception("Job %s crashed", job.id)
            outcome = {"status": FAILED, "progress": "Failed", "error": LedgerSyncError(
                "Something went wrong while analysing. Details are in the server log.").to_dict()}
        with self._lock:
            self._finish_locked(job, **outcome)

    def _finish_locked(self, job: Job, status: str, progress: str,
                       result: Any = None, error: Optional[dict] = None) -> None:
        if job.status in FINISHED:
            return
        job.status, job.progress, job.result, job.error = status, progress, result, error
        job.finished_at = self._clock()
        job.done.set()
        if job.on_finish is not None:
            job.on_finish()

    def _get_locked(self, job_id: str) -> Job:
        self._purge_expired()
        job = self._jobs.get(job_id)
        if job is None:
            raise JobNotFound("This analysis was not found. It may have expired or the server "
                              "restarted. Please run it again.")
        return job

    def _purge_expired(self) -> None:
        now = self._clock()
        for job_id in [j.id for j in self._jobs.values()
                       if j.finished_at is not None and now - j.finished_at > self._ttl]:
            del self._jobs[job_id]
