"""A thin HTTP client for the app's API: one method per route, each returning parsed JSON."""
from __future__ import annotations

import json
from contextlib import ExitStack
from datetime import date
from pathlib import Path

import httpx

HEADER = {"X-LedgerSync": "testbooks-runner"}
STREAM_READ_TIMEOUT = 600.0
_CUT = 500


class AppError(Exception):
    def __init__(self, status: int, code: str, message: str, events: list | None = None):
        super().__init__(f"{status} {code}: {message}")
        self.events: list[tuple[str, dict]] = list(events) if events else []
        self.status = status
        self.code = code
        self.message = message


def _error(response: httpx.Response) -> AppError:
    status = response.status_code
    try:
        body = response.json()
    except ValueError:
        return AppError(status, f"http_{status}", response.text[:_CUT])
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, dict) and "code" in detail and "message" in detail:
        return AppError(status, str(detail["code"]), str(detail["message"]))
    shown = detail if detail is not None else body
    return AppError(status, f"http_{status}", json.dumps(shown, separators=(",", ":"))[:_CUT])


def _events(lines):
    """Yield (type, data) per SSE event; events end at a blank line."""
    event, data = "message", []
    for line in lines:
        if line == "":
            if data or event != "message":
                text = "\n".join(data)
                yield event, (json.loads(text) if text else {})
            event, data = "message", []
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].lstrip(" "))


class Api:
    def __init__(self, base_url: str, *, timeout: float = 120.0, transport: httpx.BaseTransport | None = None):
        self._timeout = timeout
        self._http = httpx.Client(base_url=base_url, headers=HEADER, timeout=timeout, transport=transport)

    def close(self) -> None:
        self._http.close()

    def _call(self, method: str, url: str, **kw) -> httpx.Response:
        response = self._http.request(method, url, **kw)
        if not response.is_success:
            raise _error(response)
        return response

    def _json(self, method: str, url: str, **kw):
        return self._call(method, url, **kw).json()

    @staticmethod
    def _year(client_id, year_start: date) -> str:
        return f"/api/clients/{client_id}/years/{year_start.isoformat()}"

    def health(self):
        return self._json("GET", "/api/health")

    def accounts(self, client_id):
        return self._json("GET", "/api/accounts", params={"client_id": client_id})

    def create_client(self, fields):
        return self._json("POST", "/api/clients", json=fields)

    def client(self, client_id):
        return self._json("GET", f"/api/clients/{client_id}")

    def years(self, client_id):
        return self._json("GET", f"/api/clients/{client_id}/years")

    def put_opening(self, client_id, opening):
        return self._json("PUT", f"/api/clients/{client_id}/opening-balances", json=opening)

    def analyze(self, client_id, year_start: date, path: Path, bank_account: str | None) -> str:
        data = {"client_id": str(client_id), "year_start": year_start.isoformat()}
        if bank_account is not None:
            data["bank_account"] = bank_account
        path = Path(path)
        with path.open("rb") as fh:
            body = self._json("POST", "/api/analyze", data=data, files={"file": (path.name, fh)})
        return body["job_id"]

    def job(self, job_id):
        return self._json("GET", f"/api/jobs/{job_id}")

    def ledger(self, client_id, year_start: date):
        return self._json("GET", self._year(client_id, year_start) + "/ledger")

    def posted_tb(self, client_id, year_start: date):
        return self._json("GET", self._year(client_id, year_start) + "/posted-trial-balance")

    def tb_shown(self, client_id, year_start: date):
        return self._json("GET", self._year(client_id, year_start) + "/trial-balance", params={"shown": "true"})

    def invoices(self, client_id, year_start: date):
        return self._json("GET", self._year(client_id, year_start) + "/invoices")

    def bank(self, client_id, year_start: date):
        return self._json("GET", self._year(client_id, year_start) + "/bank")

    def summary(self, client_id, year_start: date):
        return self._json("GET", self._year(client_id, year_start) + "/summary")

    def suggestions(self, client_id, year_start: date):
        return self._json("GET", self._year(client_id, year_start) + "/suggestions")

    def vat(self, client_id, year_start: date, start: date, end: date):
        return self._json(
            "GET",
            self._year(client_id, year_start) + "/vat",
            params={"period_start": start.isoformat(), "period_end": end.isoformat()},
        )

    def export_xlsx(self, client_id, year_start: date) -> bytes:
        return self._call("GET", self._year(client_id, year_start) + "/export.xlsx").content

    def questions(self, client_id):
        return self._json("GET", f"/api/clients/{client_id}/questions")

    def decisions(self, client_id):
        return self._json("GET", f"/api/clients/{client_id}/decisions")

    def reviews(self, client_id):
        return self._json("GET", f"/api/clients/{client_id}/reviews")

    def new_thread(self, client_id, year_start: date | None = None):
        body = {"client_id": client_id}
        if year_start is not None:
            body["year_start"] = year_start.isoformat()
        return self._json("POST", "/api/chat/threads", json=body)

    def answer_question(self, thread_id, question_id, answer: dict):
        """Answer one of the app's questions on its card, as the client presses it in the chat."""
        return self._json("POST", f"/api/chat/threads/{thread_id}/questions/{question_id}/answer", json=answer)

    def thread(self, thread_id):
        return self._json("GET", f"/api/chat/threads/{thread_id}")

    def send_message(self, thread_id, text: str, files: list[Path]) -> list[tuple[str, dict]]:
        """Post a chat turn and read its event stream until the `done` event."""
        timeout = httpx.Timeout(self._timeout, read=max(self._timeout, STREAM_READ_TIMEOUT))
        events: list[tuple[str, dict]] = []
        with ExitStack() as stack:
            parts = [
                ("files", (Path(p).name, stack.enter_context(Path(p).open("rb"))))
                for p in files
            ]
            response = stack.enter_context(
                self._http.stream(
                    "POST",
                    f"/api/chat/threads/{thread_id}/messages",
                    data={"text": text},
                    files=parts or None,
                    timeout=timeout,
                )
            )
            if not response.is_success:
                response.read()
                raise _error(response)
            for event in _events(response.iter_lines()):
                events.append(event)
                if event[0] == "done":
                    return events
            raise AppError(
                response.status_code,
                "stream_ended",
                "The chat stream ended before the done event",
                events,
            )
