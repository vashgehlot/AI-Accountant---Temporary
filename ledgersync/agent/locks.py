"""Who may work on what at once, for the chat API, in this process (ported from the accounting-agent runner, 947ae1b,
which kept one job running for each client). A chat runs one message at a time: another while it runs is refused,
and an answer waits its turn. The writes that end a turn or apply an answer (dating rows from the bank, working out
the questions, posting) take the client's lock and wait their turn for it, so two chats on one client never post at
once."""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator

from ledgersync.errors import StillWorking

STILL_WORKING = "Still working on the last message."


class ClientLocks:
    """One lock for each client. hold waits for the client's lock rather than refusing."""

    def __init__(self):
        self._guard = threading.Lock()
        self._locks: dict[int, threading.Lock] = {}

    @contextmanager
    def hold(self, client_id: int) -> Iterator[None]:
        with self._guard:
            lock = self._locks.setdefault(client_id, threading.Lock())
        with lock:
            yield


class ThreadRuns:
    """The chats working on a message (or an answer) now, one run each, and those asked to stop."""

    def __init__(self):
        self._changed = threading.Condition()
        self._running: set[str] = set()
        self._stopping: set[str] = set()

    def start(self, thread_id: str, wait: float = 0.0) -> None:
        """Takes the chat's one run, waiting up to `wait` seconds for the one it has to end; StillWorking if it
        doesn't."""
        with self._changed:
            if not self._changed.wait_for(lambda: thread_id not in self._running, timeout=wait):
                raise StillWorking(STILL_WORKING)
            self._running.add(thread_id)
            self._stopping.discard(thread_id)

    def finish(self, thread_id: str) -> None:
        """Lets the chat's run go, and forgets that it was asked to stop."""
        with self._changed:
            self._running.discard(thread_id)
            self._stopping.discard(thread_id)
            self._changed.notify_all()

    @contextmanager
    def running(self, thread_id: str, wait: float = 0.0) -> Iterator[None]:
        """The chat's run while the block runs (see start)."""
        self.start(thread_id, wait)
        try:
            yield
        finally:
            self.finish(thread_id)

    def stop(self, thread_id: str) -> bool:
        """Asks the chat's run to stop at its next model call; False when it has none."""
        with self._changed:
            if thread_id not in self._running:
                return False
            self._stopping.add(thread_id)
            return True

    def is_running(self, thread_id: str) -> bool:
        """Whether the chat has a run now."""
        with self._changed:
            return thread_id in self._running

    def is_cancelled(self, thread_id: str) -> bool:
        with self._changed:
            return thread_id in self._stopping
