"""Runs an ASGI app on a free local port in a thread, for tests."""
from __future__ import annotations

import threading
import time
from typing import Callable

import uvicorn


def serve(app) -> tuple[int, Callable[[], None]]:
    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", lifespan="on",
                           timeout_graceful_shutdown=2)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            raise RuntimeError("test server did not start")
        time.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]

    def stop() -> None:
        server.should_exit = True
        thread.join(timeout=10)

    return port, stop
