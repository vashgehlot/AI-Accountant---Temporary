"""FastAPI entry point: a thin HTTP layer over the ledgersync package."""
import datetime as dt
import hashlib
import io
import logging
import threading
from collections import Counter
from contextlib import asynccontextmanager
from typing import Optional
from urllib.parse import quote

from fastapi import BackgroundTasks, FastAPI, File, Form, Header, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse

from ledgersync.materiality import Levels
from ledgersync import (accounts, adapter, books, demo, intake, ledger, ledger_book, pipeline, posting, questions,
                        resolutions, reviews, undo, upkeep)
from ledgersync.agent.tools import AgentDeps, upload_texts
from ledgersync.agent.chat import AnswerResult, Chat, ChatFile, NewThread, ThreadDetail, ThreadPatch
from ledgersync.blobs import BlobStore, GridFSBlobStore
from ledgersync.accounts import choosable
from ledgersync.checks import long_date, normalise
from ledgersync.config import Settings
from ledgersync.errors import (InvalidInput, LedgerSyncError, NotFound, RefusedRequest, SameFile, StorageError,
                               UnreadableFile)
from ledgersync.extractor import TransactionExtractor
from ledgersync.model_client import ModelClient
from ledgersync.jobs import JobStore
from ledgersync.matching import match
from ledgersync.models import (AnalysisResult, BankCheck, BusinessSettings, BusinessType, ChangeDraft, ChatThread,
                               Client,
                               ClientFields, ClientPatch, ClientSummary, Decision, InvoiceSummary, Ledger,
                               LedgerRequest, ManualUpload, VatFigures, OpeningBalances, PostedTrialBalance, Question, ReviewDetail, RowPatch,
                               TransactionList, TrialBalance, UploadPatch, Year, YearSummary)
from ledgersync.questions import Answer
from ledgersync.store_mongo import MongoStore

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def configure_logging(level: str) -> None:
    """LEDGERSYNC_LOG_LEVEL applies to our own loggers only. Third-party libraries stay at
    WARNING because some can log document text at DEBUG."""
    logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger().setLevel(logging.WARNING)
    logging.getLogger("ledgersync").setLevel(level)


# The kinds of file a page may show in place (the original of an upload, beside what was read from it). Nothing that
# a browser would run: not SVG, not HTML.
SHOWN_IN_PAGE = frozenset({"application/pdf", "image/png", "image/jpeg", "image/webp", "image/gif"})


def create_app(settings: Optional[Settings] = None, *, model_client=None, store: Optional[MongoStore] = None,
               blobs: Optional[BlobStore] = None, chat_model=None) -> FastAPI:
    """The API; tests pass a stand-in for the model client as model_client, a store on a test database, and the
    accountant chat's model as chat_model (OPENROUTER_MODEL, the one that reads the files, otherwise)."""
    settings = settings or Settings.from_env()
    configure_logging(settings.log_level)
    model_client = model_client or ModelClient(settings)
    owns_store = store is None   # a store handed in stays open for whoever made it
    if store is None:
        if not settings.mongodb_uri:
            raise StorageError("Set MONGODB_URI in .env: Super Accountant keeps its data in MongoDB.")
        store = MongoStore(settings.mongodb_uri, settings.mongodb_db_name, max_pool=settings.mongodb_max_pool)
    if blobs is None:
        blobs = GridFSBlobStore(store.db)   # originals live beside the rows
    extractor = TransactionExtractor(model_client, business_name=settings.business_name)
    jobs = JobStore(ttl_seconds=settings.job_ttl_seconds, max_workers=settings.max_parallel_jobs)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.warmup:
            threading.Thread(target=model_client.warm_up, name="model-warmup", daemon=True).start()
        worker = None
        if settings.warmup and settings.review_worker:   # tests turn warmup off, so no thread runs there
            worker = reviews.Worker(chat, settings, busy=files_being_read)
            worker.start()
        yield
        try:
            if worker is not None:
                worker.stop()
            jobs.shutdown()
        finally:
            if owns_store:
                store.close()

    app = FastAPI(
        title="Super Accountant API",
        description="Qwen vision model on OpenRouter or Groq → structured accounting data → trial balance",
        lifespan=lifespan,
    )
    app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
                       allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["*"])

    class ReadsClientOnce:
        """Each request works from one copy of a client, read again only after the request changes it
        (MongoStore.reading): a page's figures cost one round trip to the database for the client, not one each.
        A chat turn and a file being read work on threads of their own, outside it."""

        def __init__(self, inner):
            self.inner = inner

        async def __call__(self, scope, receive, send):
            reading = getattr(store, "reading", None)   # a stand-in store has none
            if scope["type"] != "http" or reading is None:
                await self.inner(scope, receive, send)
                return
            with reading():
                await self.inner(scope, receive, send)

    app.add_middleware(ReadsClientOnce)

    @app.exception_handler(LedgerSyncError)
    async def ledgersync_error(request: Request, exc: LedgerSyncError):
        return JSONResponse(status_code=exc.status_code,
                            content={"detail": {"code": exc.code, "message": exc.message}})

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception):
        """A fault here that nothing else names: said as one, in JSON, so the page doesn't take it for the API being
        down. What went wrong is in the log."""
        logging.getLogger("ledgersync").exception("Unexpected error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": {
            "code": "server_error",
            "message": "Something went wrong working this out. Nothing was changed. The server's log has the details."}})

    @app.exception_handler(AssertionError)
    async def row_cannot_post(request: Request, exc: AssertionError):
        """A row the books can't post (its debits and credits differ) is a fault here, not the API being down: the
        page names the row, which a person can delete or edit to get the books back."""
        logging.getLogger("ledgersync").error("A row could not be posted: %s", exc)
        return JSONResponse(status_code=500, content={"detail": {
            "code": "row_cannot_post",
            "message": f"One row can't be posted, so these figures can't be worked out. {exc}. "
                       "Delete or edit that row in Transactions."}})

    # ─── Health ────────────────────────────────────────────────────────────────

    @app.get("/api/health")
    def health_check():
        health = model_client.health()
        return {
            "status": "online",
            "model": model_client.model,
            "ai_reachable": health.reachable,
            "model_available": health.model_available,
            "ai_error": health.error,
            "max_upload_mb": settings.max_upload_mb,
            "max_parallel_jobs": settings.max_parallel_jobs,   # the UI sends this many files at once
            "demo": settings.demo,   # LEDGERSYNC_DEMO=1: POST /api/demo/reset puts the demo client back
        }

    def changed(client_id: int, kind: str, summary: str, *, actor: str = "user", year_start: Optional[dt.date] = None,
                row_ids=(), upload_id: Optional[int] = None, before: Optional[dict] = None,
                after: Optional[dict] = None, settle: bool = True, in_chat: bool = False) -> None:
        """Records a change to the client's books once it has been made, then settles them: the rows matching dated,
        the questions and the posting are brought up to date at once. Never raises after the change is recorded.
        With settle False the change is only recorded: a chat turn settles the books itself once its files are read."""
        draft = ChangeDraft(client_id=client_id, year_start=year_start, actor=actor, kind=kind, row_ids=list(row_ids),
                            upload_id=upload_id, before=before or {}, after=after or {}, summary=summary,
                            in_chat=in_chat)
        try:   # the change is already saved: recording or settling it must never fail the request or the read job
            if settle:
                upkeep.after_change(store, chat.records, chat.locks, draft, wait=settings.review_wait_seconds)
            else:
                chat.records.add_change(draft)
        except Exception:
            logging.getLogger("ledgersync.upkeep").exception("Couldn't record or settle a change to client %s: %s",
                                                             client_id, summary)

    # A person's change to a row or a document is answered with the year's ledger as soon as it is saved; recording
    # it and settling the books (the questions, the posting) follow once the answer is sent (BackgroundTasks), so the
    # page shows the change at once. Anything that reads the posting meanwhile waits for the client's lock.

    def rows_word(n: int) -> str:
        return f"{n} {'row' if n == 1 else 'rows'}"

    # ─── Step 2 — Analyze (background job) ─────────────────────────────────────

    def run_analysis(item, ctx, client: Optional[Client] = None, name: str = "Pasted text", sha256: str = "",
                     bank_account: Optional[str] = None, year_start: Optional[dt.date] = None,
                     settle: bool = True, in_chat: bool = False) -> dict:
        """Reads one input. For a client: the model is told its name, kind of business and its other bank accounts,
        the rows are booked with its settings, and they are saved to it as an upload when any were found (not after
        a cancel), added to the year starting year_start; none is saved when any falls in a closed year. A
        statement is for bank_account, or the client's only account; a client with several must say which, and is
        refused once the reading shows it is a statement."""
        own = None
        if client is None:
            reader, rules = extractor, BusinessSettings(business_name=settings.business_name)
        else:
            rules = ledger.settings_for(client)
            codes = ledger.bank_codes(client)
            own = bank_account or (codes[0] if len(codes) == 1 else None)
            reader = TransactionExtractor(model_client, business_name=client.name, business_type=client.business_type,
                                          bank_codes=ledger.bank_choices(client, own or rules.bank_account),
                                          owners=ledger.owners_of(client))
        extraction = pipeline.analyze(item, reader, ctx, name=name, account=own)
        # What the file prints, when it has a text layer; an image or a scanned PDF has none to check a total against.
        printed = item.text if item.data is None else pipeline.pdf_text(item.data) if item.kind == "pdf" else None
        # A line coded to the statement's own account goes to Suspense; one coded to another is a transfer.
        reading = rules.model_copy(update={"bank_account": own or rules.bank_account})
        transactions = adapter.to_transactions([row.model_dump() for row in extraction.data], source=item.kind,
                                               settings=reading, opening_balance=extraction.opening_balance,
                                               closing_balance=extraction.closing_balance, agent=extraction.agent,
                                               text=printed)
        statement = any(tx.document_type == "statement" for tx in transactions)
        if client is not None and statement and own is None:
            raise InvalidInput("Choose which bank account this statement is for.")
        if client is not None:   # booked as the ledger books them: the statement's lines on its account
            transactions = [normalise(tx.model_copy(update={"bank_account": own}) if tx.document_type == "statement"
                                      else tx, rules) for tx in transactions]
        result = AnalysisResult(transactions=transactions, warnings=extraction.warnings,
                                model=extraction.model).model_dump(mode="json")
        if client is not None and transactions:
            # an undated row waits in the year picked, or the year it is saved in
            ledger.ensure_open(store.get_client(client.id), [tx.date for tx in transactions],
                               year_start or dt.date.today())
            ctx.commit()   # from here a cancel can't discard the job: the rows are being saved
            result["client_id"] = client.id
            result["upload_id"] = store.add_upload(client.id, name, item.kind, transactions, sha256=sha256,
                                                   model=extraction.model or "", warnings=extraction.warnings,
                                                   bank_account=own if statement else None,
                                                   year_start=year_start)
            changed(client.id, "upload_read", f"{name} read: {rows_word(len(transactions))}",
                    year_start=year_start, upload_id=result["upload_id"], settle=settle, in_chat=in_chat)
        return result

    reading: Counter = Counter()   # (client id, sha256) of each file a job is reading for a client, once per job
    reading_jobs: dict[str, dict] = {}   # job id: the client, name and year of each file being read for a client
    reading_lock = threading.Lock()

    def refuse_saved(client_id: int, name: str, sha256: str) -> None:
        """Refuses (SameFile) a file already saved for the client: read again, its rows would be booked twice."""
        saved = next((u for u in store.uploads(client_id) if sha256 and u["sha256"] == sha256), None)
        if saved is not None:
            day = dt.datetime.fromisoformat(saved["created_at"])
            raise SameFile(f"Skipped {name}: same file as {saved['name']}, uploaded {day.day} {day:%b}, so its "
                           "rows are already in the books.")

    def being_read(client_id: int) -> list[dict]:
        """The files jobs are reading for the client now, the oldest first: each one's job, name, year and how far it
        got. A page opened again after a refresh shows them and reloads as each is saved."""
        with reading_lock:
            found = [dict(job_id=job_id, **info) for job_id, info in reading_jobs.items()
                     if info["client_id"] == client_id]
        listed, ended = [], []
        for item in found:
            try:
                job = jobs.get(item["job_id"])
            except LedgerSyncError:   # expired
                ended.append(item["job_id"])
                continue
            if job.status in ("queued", "running"):
                listed.append({"job_id": job.id, "name": item["name"], "status": job.status, "progress": job.progress,
                               "year_start": item["year_start"]})
            else:
                ended.append(job.id)
        with reading_lock:
            for job_id in ended:
                reading_jobs.pop(job_id, None)
        return listed

    def files_being_read(client_id: int) -> bool:
        """Whether a job is reading a file for the client: its review waits."""
        with reading_lock:
            return any(owner == client_id for owner, _ in reading)

    def submit_analysis(item, client: Optional[Client], name: str, sha256: str, content_type: str, data: bytes,
                        year_start: Optional[dt.date], bank_account: Optional[str], *, once: bool = False,
                        settle: bool = True, in_chat: bool = False):
        """Keeps the original file (when it has a sha256) and queues the analysis of an input already checked. With
        once, a file a job is already reading for the client is not queued again: returns None."""
        key = (client.id, sha256) if client is not None and sha256 else None

        submitted: list[str] = []   # the job's id, once it has one

        def release():
            with reading_lock:
                reading[key] -= 1
                if not reading[key]:
                    del reading[key]
                for job_id in submitted:
                    reading_jobs.pop(job_id, None)

        if key is not None:
            with reading_lock:
                if once and reading[key]:
                    return None
                reading[key] += 1

        def work(ctx):
            return run_analysis(item, ctx, client, name, sha256, bank_account,
                                year_start if client is not None else None, settle, in_chat)

        try:
            if sha256:
                blobs.put(data, name=name, content_type=content_type)
            job = jobs.submit(work, on_finish=release if key is not None else None)
            if key is not None:   # a job that ended meanwhile is left out of being_read, and dropped there
                with reading_lock:
                    submitted.append(job.id)
                    reading_jobs[job.id] = {"client_id": client.id, "name": name,
                                            "year_start": year_start.isoformat() if year_start else None}
            return job
        except BaseException:
            if key is not None:
                release()
            raise

    @app.post("/api/analyze", status_code=202)
    def analyze_transaction(text: Optional[str] = Form(None), file: Optional[UploadFile] = File(None),
                            client_id: Optional[int] = Form(None), bank_account: Optional[str] = Form(None),
                            year_start: Optional[dt.date] = Form(None), x_ledgersync: Optional[str] = Header(None)):
        """Validates the input now (403/404/413/415/422), then analyses it in a background job; with a
        client_id, the job saves the rows it finds to that client, a statement's on bank_account (one of its codes),
        added to the year starting year_start (the year picked when the file was added)."""
        if not x_ledgersync:
            # A form on any web page can post here without the browser asking the API first. The LedgerSync
            # pages send this header, which a form can't, and another site's script can't unless CORS allows it.
            raise RefusedRequest("Analyses are taken from the Super Accountant pages only: the X-LedgerSync "
                                 "header is missing.")
        client = None
        if client_id is not None:
            client = store.get_client(client_id)
            ledger.require_active(client)
            if bank_account:
                ledger.check_bank_account(client, bank_account)
            if year_start is not None:
                year_of(client_id, year_start)
        name, sha256, content_type, data = "Pasted text", "", "", b""
        if file is not None and file.filename:
            data = intake.read_limited(file.file, settings.max_upload_bytes)
            item = intake.load_upload(file.filename, data, settings.max_pdf_pages)
            name, sha256 = file.filename, hashlib.sha256(data).hexdigest()
            content_type = file.content_type or "application/octet-stream"
        elif text is not None:
            item = intake.from_text(text, settings.max_upload_bytes)
        else:
            raise UnreadableFile("Provide text or a file to analyse.")
        if client is not None:   # read again, its rows would be booked twice
            refuse_saved(client.id, name, sha256)
        model_client.ensure_available()   # fail fast with 503 instead of queueing doomed work
        job = submit_analysis(item, client, name, sha256, content_type, data, year_start,
                              bank_account or None, once=True)
        if job is None:
            raise SameFile(f"Skipped {name}: the same file is still being read for this client.")
        return {"job_id": job.id, "status": job.status}

    @app.get("/api/clients/{client_id}/reading")
    def files_reading(client_id: int):
        """The files being read for the client now (see being_read)."""
        store.get_client(client_id)
        return being_read(client_id)

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str):
        return jobs.get(job_id).to_dict()

    @app.delete("/api/jobs/{job_id}")
    def cancel_job(job_id: str):
        return jobs.cancel(job_id).to_dict()

    # ─── Ledger ─────────────────────────────────────────────────────────────────

    @app.get("/api/accounts")
    def list_accounts(business_type: Optional[BusinessType] = None, client_id: Optional[int] = None):
        """The chart; with a business type, only the accounts a row of that business can be coded to; with a client,
        those a row of that client can be coded to, its own bank accounts and cards among them."""
        if client_id is not None:
            client = store.get_client(client_id)
            chosen = choosable(client.business_type, ledger.bank_choices(client), ledger.owners_of(client))
        else:
            chosen = choosable(business_type) if business_type else accounts.CHART
        return [{"code": a.code, "name": a.name, "type": a.type.value, "vat": a.vat.value, "heading": a.heading.value,
                 "tax": a.tax.value if a.tax else None, "sa103": a.sa103} for a in chosen]

    @app.post("/api/transactions/validate", response_model=TransactionList)
    def validate_transactions(request: LedgerRequest):
        """Splits VAT, works out the other side of each row, matches bank lines to the documents they pay
        and lists issues; no posting."""
        ready = [normalise(tx, request.settings) for tx in request.transactions]
        return TransactionList(transactions=match(ready, request.settings))

    @app.post("/api/trial-balance", response_model=TrialBalance)
    def generate_trial_balance(request: LedgerRequest):
        """Double-entry trial balance; 422 when a transaction cannot be posted."""
        return posting.trial_balance(request.transactions, request.settings)

    # ─── Clients: saved work (design of 2026-10-06) ─────────────────────────────

    @app.get("/api/clients", response_model=list[ClientSummary])
    def list_clients(archived: bool = False):
        return ledger.summaries(store, archived, chat.records)

    @app.post("/api/clients", response_model=Client, status_code=201)
    def add_client(fields: ClientFields):
        return ledger.add_client(store, fields)

    @app.get("/api/clients/{client_id}", response_model=Client)
    def get_client(client_id: int):
        return store.get_client(client_id)

    @app.patch("/api/clients/{client_id}", response_model=Client)
    def change_client(client_id: int, patch: ClientPatch):
        sent = [f for f in ClientPatch.model_fields if f in patch.model_fields_set]
        before = store.get_client(client_id).model_dump(mode="json", include=set(sent))
        client = ledger.change_client(store, client_id, patch)
        changed(client_id, "client_changed", f"Client details changed: {', '.join(sent)}", before=before,
                after=patch.model_dump(mode="json", include=set(sent)))
        return client

    # ─── A client's years ────────────────────────────────────────────────────────

    def year_of(client_id: int, start: dt.date) -> Year:
        """The client's year starting on start; 404 when it is not one."""
        year = next((y for y in books.years_of(store, client_id, dt.date.today()) if y.start == start), None)
        if year is None:
            raise NotFound("That year was not found.")
        return year

    @app.get("/api/clients/{client_id}/years", response_model=list[Year])
    def client_years(client_id: int):
        return books.years_of(store, client_id, dt.date.today())

    @app.get("/api/clients/{client_id}/years/{start}/ledger", response_model=Ledger)
    def year_ledger(client_id: int, start: dt.date):
        return books.ledger(store, client_id, start)

    @app.get("/api/clients/{client_id}/years/{start}/trial-balance", response_model=TrialBalance)
    def year_trial_balance(client_id: int, start: dt.date, shown: bool = False):
        """shown: for a page. While rows need fixing, the figures without them and which are left out, instead of
        the 422 a caller that needs every row in (the bank check, the evals) gets."""
        return (books.trial_balance_shown if shown else books.trial_balance)(store, client_id, start)

    @app.get("/api/clients/{client_id}/years/{start}/materiality", response_model=Optional[Levels])
    def year_materiality(client_id: int, start: dt.date):
        """How much is too little to ask about this year, and what it was worked out from (materiality)."""
        return books.levels_of(store, client_id, start)

    @app.get("/api/clients/{client_id}/years/{start}/vat", response_model=VatFigures)
    def year_vat(client_id: int, start: dt.date, period_start: Optional[dt.date] = None,
                 period_end: Optional[dt.date] = None):
        """The VAT return boxes for a period of the year, as a guide (books.vat_figures)."""
        return books.vat_figures(store, client_id, start, period_start, period_end)

    @app.get("/api/clients/{client_id}/years/{start}/suggestions", response_model=list[Decision])
    def year_suggestions(client_id: int, start: dt.date):
        """The year's suggestions a person can still apply: the review's, and the account changes the rules suggest."""
        books.ledger(store, client_id, start)   # NotFound for a client or a year that isn't there
        return resolutions.waiting_suggestions(store, chat.records, client_id=client_id, year_start=start)

    @app.get("/api/clients/{client_id}/years/{start}/invoices", response_model=list[InvoiceSummary])
    def year_invoices(client_id: int, start: dt.date):
        return books.invoices(store, client_id, start)

    @app.get("/api/clients/{client_id}/years/{start}/bank", response_model=list[BankCheck])
    def year_bank(client_id: int, start: dt.date):
        return books.bank_checks(store, client_id, start)

    @app.get("/api/clients/{client_id}/years/{start}/summary", response_model=YearSummary)
    def year_summary(client_id: int, start: dt.date):
        return books.summary(store, client_id, start)

    @app.post("/api/clients/{client_id}/years/{start}/close", response_model=Client)
    def close_year(client_id: int, start: dt.date):
        client = books.close(store, client_id, start)
        closed = next(c for c in client.closed_years if c.start == start)
        changed(client_id, "year_closed", f"Year to {long_date(closed.end)} closed", year_start=start)
        return client

    @app.post("/api/clients/{client_id}/years/{start}/reopen", response_model=Client)
    def reopen_year(client_id: int, start: dt.date):
        client = books.reopen(store, client_id, start)
        end = next((y.end for y in books.years_of(store, client_id, dt.date.today()) if y.start == start), None)
        changed(client_id, "year_reopened", f"Year to {long_date(end)} reopened" if end else "Year reopened",
                year_start=start)
        return client

    @app.get("/api/clients/{client_id}/opening-balances", response_model=OpeningBalances)
    def opening_balances(client_id: int):
        store.get_client(client_id)
        return store.opening(client_id)

    @app.put("/api/clients/{client_id}/opening-balances", response_model=OpeningBalances)
    def set_opening_balances(client_id: int, opening: OpeningBalances):
        books.set_opening(store, client_id, opening)
        changed(client_id, "opening_balances_changed", "Opening balances changed")
        return store.opening(client_id)

    @app.patch("/api/clients/{client_id}/rows/{row_id}", response_model=Ledger)
    def change_row(client_id: int, row_id: int, patch: RowPatch, after: BackgroundTasks):
        sent = [f for f in RowPatch.model_fields if f in patch.model_fields_set and (f != "revert" or patch.revert)]
        values = set(sent) - {"revert"}
        stored = next((r for r in store.rows(client_id) if r.id == row_id), None)
        before = stored.tx.model_dump(mode="json", include=values) if stored else {}
        result = ledger.change_row(store, client_id, row_id, patch)
        kind = ("row_reverted" if patch.revert else "row_linked" if "link" in sent else
                "row_included" if "include" in sent or "removed" in sent else "rows_apart" if "apart_from" in sent else "row_edited")
        said = f"Row {row_id} changed: {', '.join(sent)}"
        if sent == ["without_document"]:
            said = (f"Row {row_id} booked without a receipt: {patch.without_document}" if patch.without_document
                    else f"Row {row_id} held in Suspense for its receipt or invoice again")
        after.add_task(changed, client_id, kind, said, row_ids=[row_id], before=before,
                after=patch.model_dump(mode="json", include=values), year_start=result.year.start)
        return result

    @app.delete("/api/clients/{client_id}/rows/{row_id}", response_model=Ledger)
    def remove_row(client_id: int, row_id: int, after: BackgroundTasks):
        stored = next((r for r in store.rows(client_id) if r.id == row_id), None)
        before = ({"description": stored.tx.description, "gross": str(stored.tx.gross),
                   "account_code": stored.tx.account_code} if stored else {})
        result = ledger.remove_row(store, client_id, row_id)
        after.add_task(changed, client_id, "row_removed", f"Row {row_id} removed", row_ids=[row_id], before=before,
                year_start=result.year.start)
        return result

    @app.post("/api/clients/{client_id}/uploads", response_model=Ledger, status_code=201)
    def add_manual_rows(client_id: int, upload: ManualUpload, after: BackgroundTasks):
        result = ledger.add_manual(store, client_id, upload)
        n = len(upload.transactions)
        added = max((u.id for u in result.uploads), default=None)   # the upload just added is the newest
        after.add_task(changed, client_id, "row_added", f"{rows_word(n)} added by hand", year_start=result.year.start,
                upload_id=added, row_ids=[r.id for r in result.transactions if r.upload_id == added])
        return result

    @app.patch("/api/clients/{client_id}/uploads/{upload_id}", response_model=Ledger)
    def change_upload(client_id: int, upload_id: int, patch: UploadPatch, after: BackgroundTasks):
        found = next((u for u in store.uploads(client_id) if u["id"] == upload_id), None)
        result = ledger.set_upload_bank(store, client_id, upload_id, patch.bank_account)
        after.add_task(changed, client_id, "upload_bank_changed", f"{found['name'] if found else 'Upload'} moved to {patch.bank_account}",
                upload_id=upload_id, before={"bank_account": found.get("bank_account") if found else None},
                after={"bank_account": patch.bank_account}, year_start=result.year.start)
        return result

    @app.delete("/api/clients/{client_id}/uploads/{upload_id}", response_model=Ledger)
    def remove_upload(client_id: int, upload_id: int, after: BackgroundTasks):
        found = next((u for u in store.uploads(client_id) if u["id"] == upload_id), None)
        result = ledger.remove_upload(store, client_id, upload_id)
        after.add_task(changed, client_id, "upload_removed", f"{found['name'] if found else 'Upload'} removed", upload_id=upload_id,
                year_start=result.year.start)
        return result

    @app.get("/api/clients/{client_id}/uploads/{upload_id}/file")
    def download_original(client_id: int, upload_id: int, show: bool = False):
        """The file an upload was read from, as it was sent; 404 when the upload was pasted text or the file is gone.
        show: for a page to show it in place, which only a PDF or an image is sent for; any other file is a download
        whatever was asked, so a file that could run in the page never does."""
        store.get_client(client_id)
        kept = "The original file wasn't kept for this upload."
        upload = next((u for u in store.uploads(client_id) if u["id"] == upload_id), None)
        if upload is None:
            raise NotFound("That upload was not found.")
        if not upload["sha256"] or not blobs.exists(upload["sha256"]):
            raise NotFound(kept)
        blob = blobs.get(upload["sha256"])
        plain = blob.name.encode("ascii", "replace").decode().replace("?", "_").replace('"', "_")
        kind = (blob.content_type or "").split(";")[0].strip().lower()
        how = "inline" if show and kind in SHOWN_IN_PAGE else "attachment"
        return Response(blob.data, media_type=blob.content_type,
                        headers={"Content-Disposition": f"{how}; filename=\"{plain}\"; "
                                                        f"filename*=UTF-8''{quote(blob.name)}",
                                 "X-Content-Type-Options": "nosniff"})

    def workbook_download(content: bytes, name: str) -> Response:
        """An Excel workbook as a download under its file name."""
        plain = name.encode("ascii", "replace").decode().replace("?", "_")
        return Response(content, media_type=XLSX,
                        headers={"Content-Disposition": f"attachment; filename=\"{plain}\"; "
                                                        f"filename*=UTF-8''{quote(name)}"})

    @app.get("/api/clients/{client_id}/years/{start}/export.xlsx")
    def export_year(client_id: int, start: dt.date):
        """The year's trial balance and transactions as an Excel workbook (archived clients too)."""
        return workbook_download(*books.export(store, client_id, start, dt.date.today()))

    # ─── The accountant chat (design of 2026-11-02) ─────────────────────────────

    def read_chat_file(client: Client, file: ChatFile, year_start: dt.date):
        """Reads a file sent to the chat as /api/analyze reads an upload: checked, kept and read in a job that saves
        its rows to the client, added to the year; a statement's on its bank account, by default the client's first
        current account. Refused (LedgerSyncError) before it is read when it fails its checks, and skipped (SameFile)
        when the same file is already saved for the client or being read for it, as the Documents page skips it: read again, its rows would be booked twice."""
        data = intake.read_limited(io.BytesIO(file.data), settings.max_upload_bytes)
        item = intake.load_upload(file.name, data, settings.max_pdf_pages)
        sha256 = hashlib.sha256(data).hexdigest()
        refuse_saved(client.id, file.name, sha256)
        model_client.ensure_available()
        bank = file.bank_account or ledger.settings_for(client).bank_account
        job = submit_analysis(item, client, file.name, sha256, file.content_type, data, year_start, bank, once=True,
                              settle=False,   # the chat's turn settles once its files are read
                              in_chat=True)   # and a file read in a chat is reviewed by that chat, not in the background
        if job is None:
            raise SameFile(f"Skipped {file.name}: the same file is still being read for this client.")
        return job

    chat = Chat(settings, store, blobs, read=read_chat_file, vision=model_client, model=chat_model)

    def from_our_pages(x_ledgersync: Optional[str]) -> None:
        """Refuses a change any web page could have sent: see /api/analyze."""
        if not x_ledgersync:
            raise RefusedRequest("Changes are taken from the Super Accountant pages only: the X-LedgerSync header "
                                 "is missing.")

    def sent_file(file: UploadFile, bank_account: Optional[str] = None) -> ChatFile:
        """The file as the chat reads it; read now, as the upload is closed once the route returns."""
        return ChatFile(name=file.filename or "file", data=file.file.read(settings.max_upload_bytes + 1),
                        content_type=file.content_type or "application/octet-stream", bank_account=bank_account)

    @app.get("/api/chat/threads", response_model=list[ChatThread])
    def list_threads(client_id: Optional[int] = None):
        """Every chat, or one client's, the most recently used first."""
        return chat.records.threads(client_id)

    @app.post("/api/chat/threads", response_model=ChatThread, status_code=201)
    def new_thread(body: NewThread, x_ledgersync: Optional[str] = Header(None)):
        from_our_pages(x_ledgersync)
        return chat.new_thread(body.client_id, body.year_start)

    @app.get("/api/chat/threads/{thread_id}", response_model=ThreadDetail)
    def get_thread(thread_id: str):
        return chat.detail(chat.thread(thread_id))

    @app.patch("/api/chat/threads/{thread_id}", response_model=ChatThread)
    def rename_thread(thread_id: str, body: ThreadPatch, x_ledgersync: Optional[str] = Header(None)):
        from_our_pages(x_ledgersync)
        chat.thread(thread_id)
        return chat.records.touch_thread(thread_id, title=body.title)

    @app.delete("/api/chat/threads/{thread_id}", status_code=204)
    def delete_thread(thread_id: str, x_ledgersync: Optional[str] = Header(None)):
        from_our_pages(x_ledgersync)
        chat.delete(chat.thread(thread_id))
        return Response(status_code=204)

    @app.post("/api/chat/threads/{thread_id}/messages")
    def send_message(thread_id: str, text: str = Form(""), files: Optional[list[UploadFile]] = File(None),
                     bank_accounts: Optional[list[str]] = Form(None), x_ledgersync: Optional[str] = Header(None)):
        """Streams the turn back as server-sent events (status, step, token, result, error, done). files[i] is a
        statement for bank_accounts[i] ('' or none: the client's first current account). 409 while the chat is
        still working on its last message."""
        from_our_pages(x_ledgersync)
        thread = chat.thread(thread_id)
        client = store.get_client(thread.client_id)
        ledger.require_active(client)
        if not text.strip():
            raise InvalidInput("Write a message to send.")
        codes = bank_accounts or []
        for code in filter(None, codes):
            ledger.check_bank_account(client, code)
        sent = [sent_file(f, (codes[k] if k < len(codes) else "") or None)
                for k, f in enumerate(files or []) if f.filename]
        events = chat.send(thread, text.strip(), sent)
        # no-transform: a compressing proxy, such as the web app's rewrites, would otherwise hold the stream back
        return StreamingResponse((event.sse() for event in events), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"})

    @app.post("/api/chat/threads/{thread_id}/questions/{question_id}/answer", response_model=AnswerResult)
    def answer_question(thread_id: str, question_id: str, answer: Answer,
                        x_ledgersync: Optional[str] = Header(None)):
        from_our_pages(x_ledgersync)
        return chat.answer(chat.thread(thread_id), question_id, answer)

    @app.post("/api/chat/threads/{thread_id}/questions/{question_id}/document", response_model=AnswerResult)
    def question_document(thread_id: str, question_id: str, file: UploadFile = File(...),
                          x_ledgersync: Optional[str] = Header(None)):
        from_our_pages(x_ledgersync)
        return chat.document(chat.thread(thread_id), question_id, sent_file(file))

    @app.post("/api/chat/threads/{thread_id}/stop")
    def stop_thread(thread_id: str, x_ledgersync: Optional[str] = Header(None)):
        """Asks the chat's run to stop before its next model call; stopping is False when nothing runs."""
        from_our_pages(x_ledgersync)
        chat.thread(thread_id)
        return {"stopping": chat.runs.stop(thread_id)}

    @app.get("/api/clients/{client_id}/questions", response_model=list[Question])
    def client_questions(client_id: int):
        """The client's open and waiting questions, of every year, from every chat on it. One of the AI's whose row
        was changed or removed since it was asked is closed first, so it is never listed as still open."""
        store.get_client(client_id)
        try:
            with chat.locks.hold(client_id):
                questions.close_answered(store, chat.records, client_id)
        except Exception:   # listing the questions must not fail because closing a stale one did
            logging.getLogger("ledgersync").exception("Couldn't close the answered questions of client %s", client_id)
        return chat.records.questions(client_id, None)

    @app.get("/api/clients/{client_id}/decisions", response_model=list[Decision])
    def client_decisions(client_id: int, year_start: Optional[dt.date] = None):
        store.get_client(client_id)
        return chat.records.decisions(client_id, year_start)

    # ─── The background AI review ───────────────────────────────────────────────

    @app.get("/api/clients/{client_id}/reviews", response_model=list[ReviewDetail])
    def client_reviews(client_id: int, year_start: Optional[dt.date] = None):
        """The client's background reviews, newest first, each with its decisions and its questions."""
        store.get_client(client_id)
        records = chat.records
        applied = records.applied_suggestions(client_id)
        runs = records.reviews(client_id, year_start=year_start)
        decisions = {d.id: d for d in records.decisions_by_ids(client_id, [i for r in runs for i in r.decision_ids])}
        asked = {q.id: q for q in records.questions_by_ids(client_id, [i for r in runs for i in r.question_ids])}
        found = []
        for run in runs:
            mine = [decisions[i] for i in run.decision_ids if i in decisions]
            found.append(ReviewDetail(**run.model_dump(), decisions=mine,
                                      questions=[asked[i] for i in run.question_ids if i in asked],
                                      applied={d.id: applied[d.id] for d in mine if d.id in applied}))
        return found

    @app.post("/api/clients/{client_id}/reviews/seen")
    def reviews_seen(client_id: int, x_ledgersync: Optional[str] = Header(None)):
        from_our_pages(x_ledgersync)
        store.get_client(client_id)
        return {"marked": chat.records.mark_reviews_seen(client_id)}

    @app.post("/api/clients/{client_id}/reviews/retry")
    def retry_review(client_id: int, x_ledgersync: Optional[str] = Header(None)):
        """Try again: the client's review is due now, whatever it was waiting for. One already running is left to
        finish."""
        from_our_pages(x_ledgersync)
        ledger.require_active(store.get_client(client_id))
        if not chat.records.review_state(client_id).running:
            chat.records.patch_review_state(client_id, due_at=reviews.utcnow().isoformat(timespec="seconds"),
                                            retry_at=None)
        return {"due": True}

    @app.post("/api/clients/{client_id}/decisions/{decision_id}/undo", response_model=Decision)
    def undo_decision(client_id: int, decision_id: str, x_ledgersync: Optional[str] = Header(None)):
        from_our_pages(x_ledgersync)
        store.get_client(client_id)
        return undo.undo_decision(store, chat.records, chat.locks, client_id=client_id, decision_id=decision_id,
                                  wait=settings.review_wait_seconds)

    @app.post("/api/clients/{client_id}/decisions/{decision_id}/apply", response_model=Decision)
    def apply_decision(client_id: int, decision_id: str, x_ledgersync: Optional[str] = Header(None)):
        from_our_pages(x_ledgersync)
        store.get_client(client_id)
        deps = AgentDeps(store=store, records=chat.records, blobs=blobs, vision=model_client, locks=chat.locks)
        return undo.apply_suggestion(store, chat.records, chat.locks, client_id=client_id, decision_id=decision_id,
                                     texts=upload_texts(deps, client_id), wait=settings.review_wait_seconds)

    @app.post("/api/clients/{client_id}/questions/{question_id}/answer", response_model=AnswerResult)
    def answer_client_question(client_id: int, question_id: str, answer: Answer,
                               x_ledgersync: Optional[str] = Header(None)):
        """Answers a question without a chat (a question card on the client's page): what the answer did, as a chat's
        answer says it; the client is made due for a review."""
        from_our_pages(x_ledgersync)
        return chat.answer_outside(client_id, question_id, answer, wait=settings.review_wait_seconds)

    @app.post("/api/clients/{client_id}/questions/{question_id}/document", response_model=AnswerResult)
    def client_question_document(client_id: int, question_id: str, file: UploadFile = File(...),
                                 x_ledgersync: Optional[str] = Header(None)):
        from_our_pages(x_ledgersync)
        client = store.get_client(client_id)
        asked = chat.records.question(question_id)
        if asked is None or asked.client_id != client_id:
            raise NotFound("This question was not found.")
        return chat.answer_with_document(client, asked.year_start, question_id, sent_file(file))

    @app.get("/api/clients/{client_id}/years/{start}/posted-trial-balance", response_model=PostedTrialBalance)
    def posted_trial_balance(client_id: int, start: dt.date):
        store.get_client(client_id)
        unposted = ledger_book.unposted_changes(store, chat.records, client_id, start)
        if unposted and not year_of(client_id, start).closed:
            # Rows saved without the upkeep (before it existed) leave an open year behind: bring it up to date, as
            # a change would. Nothing changed, so none is recorded; it is idempotent.
            try:
                with chat.locks.hold(client_id):   # a change being settled now holds it: nothing is left to do then
                    if ledger_book.unposted_changes(store, chat.records, client_id, start):
                        upkeep.settle(store, chat.records, client_id, start)
            except Exception:
                logging.getLogger("ledgersync.upkeep").exception("Couldn't settle client %s, year %s", client_id, start)
            unposted = ledger_book.unposted_changes(store, chat.records, client_id, start)
        tb = ledger_book.posted_trial_balance(store, chat.records, client_id, start)
        tb.unposted_changes = unposted
        return tb

    if settings.demo:   # otherwise there is no such route
        @app.post("/api/demo/reset")
        def reset_demo(x_ledgersync: Optional[str] = Header(None)):
            """Puts the demo client back as the demo starts, with no chats, decisions or postings."""
            from_our_pages(x_ledgersync)
            return {"client_id": demo.reset(store, chat.records, store.client[f"{store.db_name}_checkpoints"])}

    return app


if __name__ == "__main__":
    import uvicorn

    s = Settings.from_env()
    # A factory, so importing this module opens no database; the API starts (or refuses to) here.
    uvicorn.run("server:create_app", factory=True, host=s.host, port=s.port, reload=s.reload)
