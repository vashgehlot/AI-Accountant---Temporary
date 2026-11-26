"""A local pass-through proxy for the app's model calls, recording each one.

The app is pointed at `base_url(unit)`; every call goes on to the real service
unchanged and is written to `record_dir/calls.jsonl`. The Authorization header
is forwarded but never recorded or logged.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import threading
import time
from collections import deque
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from starlette.routing import Route

# Streams can be quiet for minutes, so the read timeout is generous.
_TIMEOUT = httpx.Timeout(connect=30.0, read=900.0, write=120.0, pool=None)
_SKIP_REQUEST = {"host", "content-length", "accept-encoding", "connection", "transfer-encoding"}
_SKIP_RESPONSE = {"content-encoding", "transfer-encoding", "content-length", "connection"}
# The cost lookup: wait a moment for the service to book the call, then ask up to _LOOKUP_TRIES times.
_LOOKUP_DELAY = 1.0
_LOOKUP_GAP = 2.0
_LOOKUP_TRIES = 5
_LOOKUP_WAIT = 15.0  # how long stop() waits for lookups still running


def _json_or_none(body: bytes):
    try:
        return json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return None


def fingerprint(method: str, path: str, body: bytes) -> str:
    parsed = _json_or_none(body) if body else None
    if parsed is not None:
        canon = json.dumps(parsed, sort_keys=True, separators=(",", ":")).encode()
    else:
        canon = body
    h = hashlib.sha256()
    for part in (method.encode(), path.encode(), canon):
        h.update(part)
        h.update(b"\0")
    return h.hexdigest()


def part_of(method: str, body: bytes, chat: bool) -> str:
    if method.upper() == "GET":
        return "health"
    parsed = _json_or_none(body) if body else None
    if isinstance(parsed, dict) and "tools" in parsed:
        return "chat" if chat else "review"
    return "reader"


def _parse_stream_events(buffer: str, final: bool = False) -> tuple[list[str], str]:
    """Split buffered SSE text into `data:` payloads; return them and the unfinished tail."""
    events: list[str] = []
    lines = buffer.split("\n")
    tail = "" if final else lines.pop()
    for line in lines:
        line = line.rstrip("\r")
        if line.startswith("data:"):
            events.append(line[5:].lstrip(" "))
    return events, tail


def _ids_from_events(events: list[str]) -> tuple[str | None, dict | None]:
    gen_id, usage = None, None
    for ev in events:
        data = _json_or_none(ev.encode())
        if not isinstance(data, dict):
            continue
        if gen_id is None and data.get("id"):
            gen_id = data["id"]
        if data.get("usage"):
            usage = data["usage"]
    return gen_id, usage


def _split_utf8(data: bytes) -> tuple[str, bytes]:
    """Decode as much of `data` as is whole UTF-8; return it and the unfinished bytes."""
    for cut in range(len(data), max(len(data) - 4, -1), -1):
        try:
            return data[:cut].decode("utf-8"), data[cut:]
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace"), b""


class Relay:
    def __init__(self, upstream: str, record_dir: Path, *, replay_from: Path | None = None,
                 strict: bool = False, cost_lookup: bool = True):
        self.upstream = upstream.rstrip("/")
        self.record_dir = Path(record_dir)
        self.replay_from = replay_from
        self.strict = strict
        self.cost_lookup = cost_lookup
        self._lock = threading.Lock()
        self._seq = 0
        self._parts: dict[str, str | None] = {}
        self._replayed = 0
        self._part_of_seq: dict[int, str] = {}
        self._costs: list[dict] = []
        self._pending = 0  # lookups still running
        self._idle = threading.Condition(self._lock)
        self._recordings: dict[str, deque] = {}
        self._last_get: dict[str, dict] = {}
        if replay_from is not None:
            self._load_recordings(Path(replay_from))
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None
        self._client: httpx.AsyncClient | None = None
        self.port: int | None = None
        self._app = Starlette(
            routes=[Route("/c/{unit}/{path:path}", self._handle,
                          methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"])],
            lifespan=self._lifespan)

    # --- lifecycle -----------------------------------------------------
    @asynccontextmanager
    async def _lifespan(self, app):
        self._client = httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False)
        try:
            yield
        finally:
            await self._client.aclose()

    def _last_seq(self) -> int:
        """The highest seq already recorded here, so a resumed run numbers its calls after the earlier ones."""
        last = 0
        try:
            lines = (self.record_dir / "calls.jsonl").read_text(encoding="utf-8").splitlines()
        except OSError:
            return 0
        for line in lines:
            try:
                last = max(last, int(json.loads(line)["seq"]))
            except (ValueError, KeyError, TypeError):
                continue
        return last

    def start(self) -> int:
        self.record_dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._seq = self._last_seq()
        config = uvicorn.Config(self._app, host="127.0.0.1", port=0, log_level="warning", lifespan="on",
                                timeout_graceful_shutdown=5)
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(target=self._server.run, daemon=True)
        self._thread.start()
        deadline = time.monotonic() + 10
        while not self._server.started:
            if not self._thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("relay did not start")
            time.sleep(0.01)
        self.port = self._server.servers[0].sockets[0].getsockname()[1]
        return self.port

    def stop(self) -> None:
        with self._idle:
            if not self._idle.wait_for(lambda: self._pending == 0, timeout=_LOOKUP_WAIT):
                logging.getLogger(__name__).warning("cost lookups still running after %s s", _LOOKUP_WAIT)
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=15)
            if self._thread.is_alive():
                logging.getLogger(__name__).warning("relay server thread did not stop within 15 s")
        self._server = self._thread = None

    # --- public helpers ------------------------------------------------
    def base_url(self, unit: str) -> str:
        return f"http://127.0.0.1:{self.port}/c/{unit}"

    def set_part(self, unit: str, part: str | None) -> None:
        with self._lock:
            if part is None:
                self._parts.pop(unit, None)
            else:
                self._parts[unit] = part

    def totals(self) -> dict:
        with self._lock:
            cost = Decimal(0)
            by_part: dict[str, Decimal] = {}
            unpriced = 0
            for row in self._costs:
                if row["cost"] is None:
                    unpriced += 1
                    continue
                value = Decimal(row["cost"])
                cost += value
                part = self._part_of_seq.get(row["seq"], "reader")
                by_part[part] = by_part.get(part, Decimal(0)) + value
            return {"cost": cost, "calls": self._seq, "replayed": self._replayed, "by_part": by_part,
                    "unpriced": unpriced}

    # --- replay --------------------------------------------------------
    def _load_recordings(self, folder: Path) -> None:
        """Keep, per fingerprint, the earlier run's good answers in order. Errors and unfinished
        streams are left out: replaying one would inject a failure the first run recovered from."""
        f = folder / "calls.jsonl"
        if not f.exists():
            return
        for line in f.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if not isinstance(rec, dict) or not 200 <= rec.get("status", 0) < 300:
                continue
            if rec.get("method") == "GET" and rec.get("path") == "/key":
                continue  # its answer was redacted when recorded
            if rec.get("streamed"):
                events = rec.get("events")
                if not events or events[-1] != "[DONE]":
                    continue
            self._recordings.setdefault(rec["fingerprint"], deque()).append(rec)

    def _next_recording(self, method: str, path: str, body: bytes) -> dict | None:
        fp = fingerprint(method, path, body)
        with self._lock:
            queue = self._recordings.get(fp)
            if queue:
                rec = queue.popleft()
                if method == "GET":
                    self._last_get[fp] = rec
                return rec
            if method == "GET":  # health checks repeat on a timer
                return self._last_get.get(fp)
        return None

    def _replay(self, rec: dict, common: dict, t0: float) -> Response:
        status = rec["status"]
        if rec.get("streamed"):
            events = rec["events"]

            async def emit():
                for ev in events:
                    yield f"data: {ev}\n\n".encode()

            self._record(status=status, seconds=time.perf_counter() - t0, streamed=True, response=None,
                         events=events, generation_id=rec.get("generation_id"), usage=rec.get("usage"),
                         replayed=True, **common)
            return StreamingResponse(emit(), status_code=status, media_type="text/event-stream")
        response = rec["response"]
        content = response.encode() if isinstance(response, str) else json.dumps(response).encode()
        self._record(status=status, seconds=time.perf_counter() - t0, streamed=False, response=response,
                     events=None, generation_id=rec.get("generation_id"), usage=rec.get("usage"),
                     replayed=True, **common)
        return Response(content, status_code=status,
                        media_type="text/plain" if isinstance(response, str) else "application/json")

    # --- cost lookup ---------------------------------------------------
    def _start_lookup(self, seq: int, generation_id, auth: str | None, usage=None) -> None:
        """Prices the call: from its answer when that carries its cost (OpenRouter's usage.cost), else by asking
        /generation, which can answer 404 for a call it priced in the answer."""
        cost = usage.get("cost") if isinstance(usage, dict) else None
        if isinstance(cost, (int, float, Decimal)) and not isinstance(cost, bool):
            row = {"seq": seq, "cost": format(Decimal(str(cost)), "f"), "tokens_in": usage.get("prompt_tokens"),
                   "tokens_out": usage.get("completion_tokens")}
            with self._lock:
                self._costs.append(row)
                with (self.record_dir / "costs.jsonl").open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(row) + "\n")
            return
        if not self.cost_lookup or not generation_id:
            return
        with self._lock:
            self._pending += 1
        threading.Thread(target=self._lookup, args=(seq, str(generation_id), auth), daemon=True).start()

    def _lookup(self, seq: int, generation_id: str, auth: str | None) -> None:
        headers = {"authorization": auth} if auth else {}
        error = "no answer"
        row = None
        try:
            for attempt in range(_LOOKUP_TRIES):
                time.sleep(_LOOKUP_DELAY if attempt == 0 else _LOOKUP_GAP)
                try:
                    resp = httpx.get(f"{self.upstream}/generation", params={"id": generation_id},
                                     headers=headers, timeout=30.0)
                except httpx.HTTPError as exc:
                    error = type(exc).__name__
                    continue
                if resp.status_code != 200:
                    error = str(resp.status_code)
                    continue
                try:
                    data = json.loads(resp.content, parse_float=Decimal)["data"]
                    total = data["total_cost"]
                except (ValueError, KeyError, TypeError):
                    error = "unreadable answer"
                    continue
                if not isinstance(total, (int, Decimal)) or isinstance(total, bool):
                    error = "unreadable answer"
                    continue
                row = {"seq": seq, "cost": format(Decimal(total), "f"),
                       "tokens_in": data.get("tokens_prompt"), "tokens_out": data.get("tokens_completion")}
                break
            if row is None:
                row = {"seq": seq, "cost": None, "tokens_in": None, "tokens_out": None, "error": error}
            with self._lock:
                self._costs.append(row)
                with (self.record_dir / "costs.jsonl").open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(row) + "\n")
        except Exception:  # a lookup must never take the relay down
            logging.getLogger(__name__).exception("cost lookup for call %s failed", seq)
        finally:
            with self._idle:
                self._pending -= 1
                self._idle.notify_all()

    # --- recording -----------------------------------------------------
    def _record(self, *, unit: str, method: str, path: str, req_body: bytes, status: int, started: float,
                seconds: float, streamed: bool, response, events: list[str] | None, generation_id,
                usage, replayed: bool = False) -> tuple[int, str]:
        if method == "GET" and path == "/key":  # its answer can carry a masked form of the key
            response = {"redacted": "key details are not recorded"}
        request = _json_or_none(req_body) if req_body else None
        if request is None and req_body:
            request = req_body.decode("utf-8", "replace")
        with self._lock:
            self._seq += 1
            if replayed:
                self._replayed += 1
            chat = self._parts.get(unit) == "chat"
            row = {
                "seq": self._seq, "unit": unit, "part": part_of(method, req_body, chat),
                "method": method, "path": path, "fingerprint": fingerprint(method, path, req_body),
                "status": status, "started": started, "seconds": seconds, "streamed": streamed,
                "request": request, "response": response, "events": events,
                "generation_id": generation_id, "usage": usage, "replayed": replayed,
            }
            self._part_of_seq[self._seq] = row["part"]
            with (self.record_dir / "calls.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row) + "\n")
            return self._seq, row["part"]

    def _unreachable(self, exc: Exception, t0: float, common: dict) -> Response:
        reason = str(exc) or type(exc).__name__
        payload = {"error": {"message": f"relay could not reach upstream: {reason}"}}
        self._record(status=502, seconds=time.perf_counter() - t0, streamed=False, response=payload,
                     events=None, generation_id=None, usage=None, **common)
        return Response(json.dumps(payload), status_code=502, media_type="application/json")

    # --- the pass-through ----------------------------------------------
    async def _handle(self, request: Request) -> Response:
        unit = request.path_params["unit"]
        path = "/" + request.path_params["path"]
        method = request.method
        body = await request.body()
        url = f"{self.upstream}{path}"
        if request.url.query:
            url += "?" + request.url.query
        headers = [(k, v) for k, v in request.headers.items() if k.lower() not in _SKIP_REQUEST]
        headers.append(("accept-encoding", "identity"))
        started = time.time()
        t0 = time.perf_counter()
        common = dict(unit=unit, method=method, path=path, req_body=body, started=started)
        auth = request.headers.get("authorization")  # held in this call only, never stored

        if self.replay_from is not None or self.strict:
            rec = self._next_recording(method, path, body)
            if rec is not None:
                return self._replay(rec, common, t0)
            if self.strict:
                payload = {"error": {"message": "no recording for this call"}}
                self._record(status=502, seconds=time.perf_counter() - t0, streamed=False,
                             response=payload, events=None, generation_id=None, usage=None, **common)
                return Response(json.dumps(payload), status_code=502, media_type="application/json")

        try:
            upstream = await self._client.send(
                self._client.build_request(method, url, headers=headers, content=body), stream=True)
        except httpx.HTTPError as exc:
            return self._unreachable(exc, t0, common)

        out_headers = {k: v for k, v in upstream.headers.items() if k.lower() not in _SKIP_RESPONSE}

        if upstream.headers.get("content-type", "").startswith("text/event-stream"):
            return StreamingResponse(self._relay_stream(upstream, t0, common, auth),
                                     status_code=upstream.status_code, headers=out_headers)

        try:
            content = await upstream.aread()
        except httpx.HTTPError as exc:
            return self._unreachable(exc, t0, common)
        finally:
            await upstream.aclose()
        parsed = _json_or_none(content) if content else None
        response = parsed if parsed is not None else content.decode("utf-8", "replace")
        gen_id = usage = None
        if isinstance(parsed, dict):
            gen_id = parsed.get("id")
            usage = parsed.get("usage")
        seq, _ = self._record(status=upstream.status_code, seconds=time.perf_counter() - t0, streamed=False,
                              response=response, events=None, generation_id=gen_id, usage=usage, **common)
        self._start_lookup(seq, gen_id, auth, usage)
        return Response(content, status_code=upstream.status_code, headers=out_headers)

    async def _relay_stream(self, upstream: httpx.Response, t0: float, common: dict, auth: str | None):
        events: list[str] = []
        tail = ""
        pending = b""
        try:
            async for chunk in upstream.aiter_bytes():  # decoded, as the content-encoding header is dropped
                pending += chunk
                text, pending = _split_utf8(pending)
                found, tail = _parse_stream_events(tail + text)
                events.extend(found)
                yield chunk
        finally:  # an upstream drop propagates, so the app sees the same failure; the record still lands
            found, _ = _parse_stream_events(tail, final=True)
            events.extend(found)
            gen_id, usage = _ids_from_events(events)
            seq, _ = self._record(status=upstream.status_code, seconds=time.perf_counter() - t0,
                                  streamed=True, response=None, events=events, generation_id=gen_id,
                                  usage=usage, **common)
            self._start_lookup(seq, gen_id, auth, usage)
            try:
                await asyncio.shield(upstream.aclose())
            except BaseException:
                pass
