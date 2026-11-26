"""A stand-in for api.Api that answers from data a test sets, and records every call.

Data attributes (the method names `years`, `client` and so on are taken by the methods):
  clients        {id: client record}, filled by create_client; set it to pre-load clients
  years_list     what years() returns; None means one year ending on the client's first year end
  returns        {method name: value} for the plain reads (accounts, ledger, posted_tb, tb_shown, invoices,
                 bank, summary, suggestions, vat, export_xlsx, questions, decisions, thread, send_message,
                 health, new_thread); a missing name gives an empty default
  job_script     {file name: [job dicts]}: successive polls of that file's jobs, the last repeating. Every
                 submission of the file shares the one script, so a retry sees the next entry. A file with no
                 script gets a succeeded job with an upload_id.
  raise_on       {file name or method name: AppError, or a list of AppError/None used one per call}
  review_script  [[review dicts], ...]: successive reviews() answers, the last repeating
`calls` holds (method name, args); `max_in_flight` is the most jobs submitted and not yet seen finished.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

FINISHED = {"succeeded", "failed", "cancelled"}
_DEFAULTS = {
    "accounts": list, "ledger": dict, "posted_tb": dict, "tb_shown": dict, "invoices": dict, "bank": dict,
    "summary": dict, "suggestions": list, "vat": dict, "export_xlsx": bytes, "questions": list,
    "decisions": list, "thread": dict, "health": lambda: {"ok": True},
    "send_message": lambda: [("done", {})], "new_thread": lambda: {"id": "thread-1"},
}
_CODES = {"current": 1200, "savings": 1210, "petty_cash": 1230, "credit_card": 1240}


class FakeApi:
    def __init__(self):
        self.calls: list[tuple[str, tuple]] = []
        self.clients: dict[int, dict] = {}
        self.years_list: list[dict] | None = None
        self.returns: dict = {}
        self.job_script: dict[str, list[dict]] = {}
        self.raise_on: dict = {}
        self.review_script: list[list[dict]] = []
        self.max_in_flight = 0
        self.next_client_id = 1
        self._job_file: dict[str, str] = {}
        self._polls: dict[str, int] = {}
        self._reviews_seen = 0
        self._submissions = 0
        self._in_flight: set[str] = set()

    def _record(self, name: str, *args, key: str | None = None):
        self.calls.append((name, args))
        planned = self.raise_on.get(key if key is not None else name)
        if isinstance(planned, list):
            planned = planned.pop(0) if planned else None
        if planned is not None:
            raise planned

    def _read(self, name: str, *args):
        self._record(name, *args)
        value = self.returns.get(name)
        return _DEFAULTS[name]() if value is None else value

    def close(self):
        self.calls.append(("close", ()))

    def health(self):
        return self._read("health")

    def accounts(self, client_id):
        return self._read("accounts", client_id)

    def create_client(self, fields):
        self._record("create_client", fields)
        used: dict[str, int] = {}
        accounts = []
        for a in fields.get("bank_accounts", []):
            kind = a["kind"]
            code = a["code"] or str(_CODES[kind] + used.get(kind, 0))
            used[kind] = used.get(kind, 0) + 1
            accounts.append({"code": code, "name": a["name"], "kind": kind})
        client = {**fields, "id": self.next_client_id, "bank_accounts": accounts}
        self.clients[self.next_client_id] = client
        self.next_client_id += 1
        return client

    def client(self, client_id):
        self._record("client", client_id)
        return self.clients[client_id]

    def years(self, client_id):
        self._record("years", client_id)
        if self.years_list is not None:
            return self.years_list
        end = date.fromisoformat(self.clients[client_id]["first_year_end"])
        start = date(end.year - 1, end.month, end.day) + timedelta(days=1)
        return [{"start": start.isoformat(), "end": end.isoformat(), "label": "", "closed": False}]

    def put_opening(self, client_id, opening):
        self._record("put_opening", client_id, opening)
        return opening

    def analyze(self, client_id, year_start, path, bank_account):
        name = Path(path).name
        self._record("analyze", client_id, year_start, path, bank_account, key=name)
        self._submissions += 1
        job_id = f"job-{self._submissions}"
        self._job_file[job_id] = name
        self._in_flight.add(job_id)
        self.max_in_flight = max(self.max_in_flight, len(self._in_flight))
        return job_id

    def job(self, job_id):
        self._record("job", job_id)
        name = self._job_file[job_id]
        script = self.job_script.get(name)
        if script:
            n = self._polls.get(name, 0)
            self._polls[name] = n + 1
            job = script[min(n, len(script) - 1)]
        else:
            job = {"status": "succeeded", "result": {"upload_id": f"up-{job_id}"}}
        job = {"job_id": job_id, "progress": None, "result": None, "error": None, **job}
        if job["status"] in FINISHED:
            self._in_flight.discard(job_id)
        return job

    def ledger(self, client_id, year_start):
        return self._read("ledger", client_id, year_start)

    def posted_tb(self, client_id, year_start):
        return self._read("posted_tb", client_id, year_start)

    def tb_shown(self, client_id, year_start):
        return self._read("tb_shown", client_id, year_start)

    def invoices(self, client_id, year_start):
        return self._read("invoices", client_id, year_start)

    def bank(self, client_id, year_start):
        return self._read("bank", client_id, year_start)

    def summary(self, client_id, year_start):
        return self._read("summary", client_id, year_start)

    def suggestions(self, client_id, year_start):
        return self._read("suggestions", client_id, year_start)

    def vat(self, client_id, year_start, start, end):
        return self._read("vat", client_id, year_start, start, end)

    def export_xlsx(self, client_id, year_start):
        return self._read("export_xlsx", client_id, year_start)

    def questions(self, client_id):
        return self._read("questions", client_id)

    def decisions(self, client_id):
        return self._read("decisions", client_id)

    def reviews(self, client_id):
        self._record("reviews", client_id)
        if not self.review_script:
            return []
        n = min(self._reviews_seen, len(self.review_script) - 1)
        self._reviews_seen += 1
        return self.review_script[n]

    def new_thread(self, client_id, year_start=None):
        return self._read("new_thread", client_id, year_start)

    def thread(self, thread_id):
        return self._read("thread", thread_id)

    def send_message(self, thread_id, text, files):
        return self._read("send_message", thread_id, text, files)
