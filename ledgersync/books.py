"""A client's years (design of 2026-10-23): each year's ledger, opening balances and trial balance. Matching runs over
all of a client's rows, whatever their year, so a payment in one year clears an invoice of another, and each bank
statement is checked whole; a year's views then take the rows of that year. A year opens with the balances the year
before closed with, its profit carried into retained earnings or the owners' capital; the first year with the
balances typed in from the client's last accounts, and the invoices unpaid behind its Debtors and Creditors. A year
the accountant closes keeps the balances it closed with, which the next year opens with, until it is reopened."""
from __future__ import annotations

import datetime as dt
from collections import Counter, defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import NamedTuple, Optional

from . import years as yr
from .accounts import (BY_CODE, CREDITORS, DEBTORS, DIRECTORS_LOANS, LOANS, LONG_TERM, PURCHASE_VAT, SALES_VAT,
                       SUSPENSE, AccountType, owner_names, profit_split)
from .checks import FACT_QUESTIONS, booked, issue, long_date, normalise, registered_on
from .coding import usual_accounts, unusual_account_text
from .duplicates import WINDOW, possible_duplicates, renumbered_invoices
from .materiality import Levels, decide, year_levels
from .errors import InvalidInput, InvalidTransactions, NotFound
from .evidence_rules import document_rule, journal_with_rule
from .export import file_name, workbook
from .file_dates import check_file_date, date_in_name
from .ledger import ensure_open, needs_review, owners_of, require_active, settings_for
from .matching import DocumentStatus, match_documents
from .models import (Direction, VatFigures, BankCheck, BusinessSettings, Client, ClosedYear, InvoiceSummary, Ledger, OpeningBalances, OpenItem,
                     SavedRow, StatementCheck, Transaction, TrialBalance, Upload, Year, YearSummary)
from .money import ZERO, VatTreatment, to_money, vat_in_gross
from .posting import journal_for, matched_rows, summarise
from .rows import StoredRow, now_iso
from .statements import signed, check_statement
from .store_mongo import MongoStore

# What books.close stamps a year with when it closes it under the document rules (ClosedYear.rules).
DOCUMENT_RULES = "document_rules"
_PROFIT_AND_LOSS = (AccountType.INCOME.value, AccountType.EXPENSE.value)


def _gbp(amount: Decimal) -> str:
    return f"£{amount:,.2f}" if amount >= 0 else f"-£{-amount:,.2f}"


def _year(client: Client, n: int) -> Year:
    start, end = yr.year_bounds(client.first_year_end, n)
    return Year(start=start, end=end, label=yr.label(end), closed=any(c.start == start for c in client.closed_years))


def year_of_row(client: Client, row: StoredRow, uploads_by_id: dict[int, dict]) -> Optional[int]:
    """The year a row belongs to: the year of its date; with no date, the year its upload was added to (for an upload
    saved without one, the year of the day it was saved). None before the first year starts."""
    day = row.tx.date
    if day is None:
        upload = uploads_by_id.get(row.upload_id) or {}
        day = upload.get("year_start") or (
            dt.date.fromisoformat(upload["created_at"][:10]) if upload.get("created_at") else None)
    return yr.year_index(client.first_year_end, day) if day else None


def _place(client: Client, row: StoredRow, uploads_by_id: dict[int, dict]) -> int:
    """The year a row is shown and booked in: its own, or the first year for a row dated before it, where the period
    check says so."""
    n = year_of_row(client, row, uploads_by_id)
    return 0 if n is None else n


def _decisions(stored: list[StoredRow]) -> tuple[list[Optional[Decimal]], list[set[int]]]:
    """What people decided about a client's rows, for matching them: each row's amount as it was read before a person
    changed it (None if unchanged), and, for each row, the rows they said are not the same as it, both ways, from row
    ids to places in the list. The ledger and the trial balance both match with this, so they book the same rows."""
    read = [to_money(row.original.get("gross")) if row.original else None for row in stored]
    place = {row.id: n for n, row in enumerate(stored)}
    apart: list[set[int]] = [set() for _ in stored]
    for n, row in enumerate(stored):
        for other in (place[i] for i in row.tx.apart_from if i in place):
            apart[n].add(other)
            apart[other].add(n)
    return read, apart


def _typed(opening: OpeningBalances) -> dict[str, Decimal]:
    """The first year's typed opening balances by account, signed with debits positive."""
    balances: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for line in opening.lines:
        balances[line.code] += line.debit - line.credit
    return {code: balance for code, balance in balances.items() if balance != 0}


NOT_ITEMISED = "Not itemised"


def not_itemised(opening: OpeningBalances) -> list[OpenItem]:
    """What Debtors and Creditors open with beyond the unpaid invoices listed: one balance each, brought forward
    without its invoices, which a payment can still be linked to."""
    balances = _typed(opening)
    rest = []
    for direction, code, sign in ((Direction.IN, DEBTORS, 1), (Direction.OUT, CREDITORS, -1)):
        listed = sum((item.amount for item in opening.unpaid if item.direction == direction), ZERO)
        left = sign * balances.get(code, ZERO) - listed
        if left > 0:
            rest.append(OpenItem(id=f"rest-{direction.value}", direction=direction, counterparty=NOT_ITEMISED,
                                 amount=left, number="balance brought forward"))
    return rest


@dataclass
class _Books:
    """Everything a year's views are worked out from: the client, all its rows and uploads, the year each row is in,
    what people decided, its first year's opening balances, and its years."""
    client: Client
    stored: list[StoredRow]
    uploads: list[dict]
    placed: list[int]
    read: list[Optional[Decimal]]
    apart: list[set[int]]
    opening: OpeningBalances
    years: list[Year]

    @property
    def settings(self) -> BusinessSettings:
        return settings_for(self.client)

    def settings_in(self, n: int) -> BusinessSettings:
        """The client's settings with year n as the accounting period, so a row dated outside it says so."""
        return self.settings.model_copy(update={"period_start": self.years[n].start, "period_end": self.years[n].end})

    @property
    def unpaid(self) -> list[OpenItem]:
        """The invoices brought into the first year, dated the day before it starts, as matching dates them."""
        day = self.years[0].start - yr.DAY
        return [item.model_copy(update={"date": day}) for item in [*self.opening.unpaid, *not_itemised(self.opening)]]

    def index(self, year_start: dt.date) -> int:
        n = next((k for k, y in enumerate(self.years) if y.start == year_start), None)
        if n is None:
            raise NotFound("That year was not found.")
        return n

    def rules_apply(self, n: int) -> bool:
        """Whether year n is worked out under the document rules: every open year and every year closed with them.
        A year closed before them stays as it closed (closed is closed)."""
        start = self.years[n].start
        closed = next((c for c in self.client.closed_years if c.start == start), None)
        return closed is None or closed.rules == DOCUMENT_RULES

    def post(self, settings: BusinessSettings, keep: list[bool], opening: dict[str, Decimal], *,
             rules: bool = True, skip_errors: bool = False) -> TrialBalance:
        """The year's trial balance, its rows booked under the document rules as the posted ledger books them (with
        rules False, as a year closed before them is: every row books as posting.journal_for has it)."""
        posted = matched_rows([row.tx for row in self.stored], settings, self.read, self.apart, keep=keep,
                              open_items=self.unpaid, name_days=_name_days(self),
                              upload_ids=[row.upload_id for row in self.stored], skip_errors=skip_errors)
        return summarise([line for n, tx in posted for line in (
            journal_with_rule(tx, n, document_rule(tx, settings)) if rules else journal_for(tx, n))], opening)


def _books(store: MongoStore, client_id: int, today: Optional[dt.date] = None) -> _Books:
    # One read of the client for everything a calculation needs: each read is a round trip to the database.
    client, stored, listed, opening = store.whole(client_id)
    by_id = {u["id"]: u for u in listed}
    placed = [_place(client, row, by_id) for row in stored]
    latest = max(placed + [yr.year_index(client.first_year_end, today or dt.date.today()) or 0])
    read, apart = _decisions(stored)
    return _Books(client=client, stored=stored, uploads=listed, placed=placed, read=read, apart=apart,
                  opening=opening, years=[_year(client, n) for n in range(latest + 1)])


def years_of(store: MongoStore, client_id: int, today: dt.date) -> list[Year]:
    """The client's years: the first through the latest that holds a row, or holds today, whichever is later; each
    with how many rows it holds, so a page can open the year being worked on."""
    b = _books(store, client_id, today)
    held = Counter(b.placed)
    return [y.model_copy(update={"rows": held.get(n, 0)}) for n, y in enumerate(b.years)]

# What a held row says it needs, by DocumentRule.needs.
HELD = {"receipt_or_invoice": "Held in Suspense: needs its receipt or invoice.",
        "vat_invoice": "Held in Suspense: needs a full VAT invoice."}


def levels_of(store: MongoStore, client_id: int, year_start: dt.date) -> Optional[Levels]:
    """The client's materiality for the year: from its figures, or the firm's (materiality.year_levels)."""
    b = _books(store, client_id, dt.date.today())
    n = b.index(year_start)
    ready, _ = _matched(b, b.settings_in(n))
    return year_levels(ready, b.placed, b.years, n, b.client.materiality)


def _matched(b: _Books, settings: BusinessSettings) -> tuple[list[Transaction], dict[str, DocumentStatus]]:
    """All the client's rows matched together with the invoices brought forward, in the order of b.stored, and what
    is still owed on each document, by its ref."""
    return match_documents([normalise(row.tx, settings) for row in b.stored], settings, b.read, b.apart, b.unpaid,
                           name_days=_name_days(b), upload_ids=[row.upload_id for row in b.stored])


def _name_days(b: _Books) -> list[Optional[dt.date]]:
    """For each stored row, the day its upload's file name holds when the upload is one receipt or invoice (an expense
    app's export, a phone's photo), else None: matching pairs an undated one with the one claim line of that day."""
    names = {u["id"]: u["name"] for u in b.uploads}
    refs: dict[int, set] = defaultdict(set)
    for row in b.stored:
        refs[row.upload_id].add(row.tx.document_ref)
    return [date_in_name(names.get(row.upload_id, "")) if len(refs[row.upload_id]) == 1
            and row.tx.document_type in ("receipt", "invoice") else None for row in b.stored]


def _saved_rows(b: _Books, n: Optional[int]) -> tuple[list[SavedRow], dict[int, Optional[StatementCheck]]]:
    """The rows of year n (every row when None), matched over all the client's rows and the invoices brought forward,
    then each upload's bank lines checked whole against the balances its statement prints, and its document's date
    against its file name's; and each upload's statement check."""
    settings = b.settings if n is None else b.settings_in(n)
    ready, _ = _matched(b, settings)
    positions: dict[int, list[int]] = defaultdict(list)
    for k, row in enumerate(b.stored):
        positions[row.upload_id].append(k)
    names = {u["id"]: u["name"] for u in b.uploads}
    # A card's statement prints what is owed on it, so its balances move the other way.
    cards = {a.code for a in b.client.bank_accounts if a.kind == "credit_card"}
    on_card = {u["id"] for u in b.uploads if u["bank_account"] in cards}
    checks: dict[int, Optional[StatementCheck]] = {}
    for upload_id, ks in positions.items():
        checked, checks[upload_id] = check_statement([ready[k] for k in ks], credit_card=upload_id in on_card)
        checked = check_file_date(checked, names.get(upload_id, ""))
        for k, tx in zip(ks, checked):
            ready[k] = tx
    for k, tx in enumerate(ready):
        if booked(tx) and b.rules_apply(b.placed[k]):   # a year closed before the rules holds nothing
            rule = document_rule(tx, settings)
            if rule.action == "hold":
                said = HELD[rule.needs] if settings.vat_registered else HELD["receipt_or_invoice"]
                if tx.paid_against is not None and tx.pays:   # matched, but to a document for another amount
                    said = (f"Held in Suspense: matched to \"{tx.pays[-1].description}\", which is for a different "
                            "amount. Link it to that document if it pays part of it, or upload its own.")
                ready[k] = tx.model_copy(update={"issues": [*tx.issues, issue("needs_document", said, "warning")]})
            elif rule.waived:
                ready[k] = tx.model_copy(update={"issues": [*tx.issues, issue("booked_without_document",
                                                                              rule.reason, "info")]})
            elif rule.small and settings.vat_registered and tx.document_type == "statement":
                # Booked whole from the bank line: said, so VAT a receipt would reclaim is not lost unnoticed.
                account = BY_CODE.get(tx.account_code)
                if account is not None and account.vat == VatTreatment.STANDARD and account.reclaim_vat:
                    most = vat_in_gross(tx.gross, VatTreatment.STANDARD)
                    ready[k] = tx.model_copy(update={"issues": [*tx.issues, issue(
                        "vat_unclaimed", f"No VAT reclaimed: booked from the bank line. Add its receipt or invoice to "
                                         f"reclaim up to £{most:,.2f}.", "info")]})
            if rule.unbacked and "document_wanted" not in tx.accepted:
                vat = tx.vat_posted or ZERO
                ready[k] = ready[k].model_copy(update={"issues": [*ready[k].issues, issue("document_wanted", (
                    f"Booked as the claim shows it, with £{vat:,.2f} VAT reclaimed, but there is no receipt or invoice "
                    "for it. Get a VAT invoice for this." if vat > 0 else
                    "Booked as the claim shows it, but there is no receipt or invoice for it. Get one for this."),
                    "warning")]})
            if rule.large_no_vat:   # said, so VAT a fuller invoice would show is not lost unnoticed
                ready[k] = ready[k].model_copy(update={"issues": [*ready[k].issues, issue(
                    "vat_unclaimed", "No VAT reclaimed: the receipt shows none. If VAT was charged, enter it, or add "
                                     "the VAT invoice.", "info")]})
            if rule.confirmed:   # said, so the VAT reclaimed on a person's word can always be found again
                ready[k] = ready[k].model_copy(update={"issues": [*ready[k].issues, issue(
                    "vat_confirmed", f"VAT £{tx.vat_posted:,.2f} is reclaimed because a person entered or confirmed "
                                     "it; the document itself would not have allowed it. Keep the VAT invoice on "
                                     "file.", "info")]})
            # VAT on the row that the rule keeps out of Purchase VAT (held, or its document isn't a VAT invoice):
            # said on the row, so a page never shows VAT and a net that the trial balance doesn't hold.
            if not rule.reclaim_vat and (tx.vat_posted or ZERO) > ZERO and tx.direction == Direction.OUT:
                ready[k] = ready[k].model_copy(update={"vat_not_reclaimed": tx.vat_posted,
                                                       "vat_not_reclaimed_why": rule.reason})
    # A document dated after the year that holds today: a later year opens for it, so a person checks the date.
    this_year = yr.year_index(b.client.first_year_end, dt.date.today()) or 0
    ahead = b.years[min(this_year, len(b.years) - 1)].end
    for k, tx in enumerate(ready):
        if (tx.date is not None and tx.date > ahead and tx.document_type != "journal" and booked(tx)
                and "future_date" not in tx.accepted):
            ready[k] = tx.model_copy(update={"issues": [*tx.issues, issue(
                "future_date", f"Dated {long_date(tx.date)}, after the year to {long_date(ahead)} that today is in: "
                               "check the date was read right.")]})
    # The same payment from two uploads: said on the later row, about the earlier one, where the AI sees it too.
    same = possible_duplicates(ready, uploads=[row.upload_id for row in b.stored], ids=[row.id for row in b.stored])
    for k, j in enumerate(same):
        if j is not None:
            other = ready[j]
            said = (f'Same amount as "{other.description}" ({names.get(b.stored[j].upload_id, "another upload")}), '
                    f"within {WINDOW.days} days.")
            ready[k] = ready[k].model_copy(update={"issues": [*ready[k].issues,
                                                             issue("possible_duplicate", said, related=[j])]})
    # An invoice under a number already used, for another total: a revised invoice, or a number misread. Said on the
    # later one, so a person or the AI keeps one (R2) or says they are two invoices.
    for k, earlier in enumerate(renumbered_invoices(ready, ids=[row.id for row in b.stored])):
        if earlier is not None:
            other = ready[earlier[0]]
            was = other.document_total or sum((ready[j].gross for j in earlier), ZERO)
            said = (f"Same invoice number ({ready[k].document_number}) as \"{other.description}\""
                    f"{f' of {long_date(other.date)}' if other.date else ''} for {_gbp(was)}. If this one replaces "
                    "it, leave that one out; if they are two invoices, keep both.")
            ready[k] = ready[k].model_copy(update={"issues": [*ready[k].issues,
                                                             issue("possible_duplicate", said, related=earlier)]})
    # A bill on another account than its supplier's other bills went to, in this year or any other: said on the
    # row, and the rules suggest the usual account (resolutions.suggest_account_changes). A closed year's rows count
    # as the supplier's history but are not flagged: they can't be changed.
    open_rows = [not b.years[p].closed and "unusual_account" not in tx.accepted for p, tx in zip(b.placed, ready)]
    for k, usual in enumerate(usual_accounts(ready, flag=open_rows)):
        if usual is not None:
            ready[k] = ready[k].model_copy(update={"issues": [
                *ready[k].issues, issue("unusual_account", unusual_account_text(ready[k], usual),
                                        related=usual.related)]})
    # Presentation questions (Sundry, another account of the same tax, asset or cost, a bill past the year end):
    # asked or left by each year's materiality (materiality.decide).
    levels = {p: year_levels(ready, b.placed, b.years, p, b.client.materiality) for p in set(b.placed)}
    ready = decide(ready, b.placed, levels)
    # The rows each issue is about, from their place in the rows matched to their row ids.
    rows = [SavedRow(**{**tx.model_dump(), "issues": [
                         {**i.model_dump(), "related": [b.stored[p].id for p in i.related]} for i in tx.issues]},
                     id=row.id, upload_id=row.upload_id, edited=row.original is not None, original=row.original)
            for k, (row, tx) in enumerate(zip(b.stored, ready)) if n is None or b.placed[k] == n]
    return rows, checks


def _changed_since_closed(b: _Books, n: int) -> bool:
    """Whether closed year n's balances, worked out now, differ from the ones it closed with: say, a document
    added to a later year changed how one of its rows is matched. True when they can't be worked out."""
    saved = next(c.closing for c in b.client.closed_years if c.start == b.years[n].start)
    try:
        return _balances(_trial_balance(b, n)) != saved
    except InvalidTransactions:
        return True


def _year_now(b: _Books, n: int) -> Year:
    """Year n, a closed one saying whether its rows now work out to other balances than it closed with."""
    year = b.years[n]
    if year.closed:
        year = year.model_copy(update={"changed_since_closed": _changed_since_closed(b, n)})
    return year


def _ledger(b: _Books, n: int) -> Ledger:
    transactions, checks = _saved_rows(b, n)
    held = {row.upload_id for row in transactions}
    start = b.years[n].start
    uploads = [Upload(id=u["id"], name=u["name"], kind=u["kind"], sha256=u["sha256"], model=u["model"],
                      warnings=u["warnings"], created_at=u["created_at"], rows=u["row_count"],
                      statement=checks.get(u["id"]), bank_account=u["bank_account"], year_start=u["year_start"])
               for u in b.uploads if u["id"] in held or u["year_start"] == start]
    return Ledger(client=b.client, year=_year_now(b, n), years=b.years, uploads=uploads, transactions=transactions)


def ledger(store: MongoStore, client_id: int, year_start: dt.date) -> Ledger:
    """The year's ledger: its rows, matched over all the client's rows, and the uploads holding any of them or added
    to the year. NotFound when year_start isn't the start of one of the client's years."""
    b = _books(store, client_id)
    return _ledger(b, b.index(year_start))


def ledger_of(store: MongoStore, client_id: int, n: Optional[int]) -> Ledger:
    """The ledger of the client's year n, as a change made in it returns; the latest year when n is None, or when a
    change left year n no longer one of the client's years (its last row removed)."""
    b = _books(store, client_id)
    last = len(b.years) - 1
    return _ledger(b, last if n is None else min(n, last))


def all_rows(store: MongoStore, client_id: int) -> list[SavedRow]:
    """Every row of the client, whatever its year, as the year ledgers show them (for the clients page)."""
    return _saved_rows(_books(store, client_id), None)[0]


def _balances(tb: TrialBalance) -> dict[str, Decimal]:
    """A trial balance's balances by account, signed with debits positive."""
    return {line.code: line.debit - line.credit for line in tb.lines}


def _shares(client) -> tuple[tuple[int, Optional[Decimal]], ...]:
    """The client's owners' slots and shares of the profit, as accounts.profit_split takes them."""
    return tuple((o.slot, o.share) for o in client.owners if o.slot is not None)


def _carried(b: _Books, balances: dict[str, Decimal], shares=None) -> dict[str, Decimal]:
    """Balances at a year's end as the next year opens with them: the year's profit closed (accounts.profit_split) to
    a company's retained earnings, or split between the partners' capital accounts or the LLP members' current
    accounts by their shares (a closed year's own, given; the owners' now otherwise)."""
    carried: dict[str, Decimal] = defaultdict(lambda: ZERO)
    profit = ZERO
    for code, balance in balances.items():
        if BY_CODE[code].type.value in _PROFIT_AND_LOSS:
            profit += balance
        else:
            carried[code] += balance
    shares = _shares(b.client) if shares is None else tuple(tuple(s) for s in shares)
    for code, part in profit_split(b.client.business_type, shares, profit).items():
        carried[code] += part
    return {code: balance for code, balance in carried.items() if balance != 0}


def _opening(b: _Books, n: int) -> dict[str, Decimal]:
    """Year n's opening balances by account, signed with debits positive: the first year's typed lines; a later
    year's, the balances the latest closed year before it closed with (the typed lines when none is), and the
    balances of every row of the years between, carried into the year."""
    typed = _typed(b.opening)
    if n == 0:
        return typed
    closed = {c.start: c for c in b.client.closed_years}
    last = next((k for k in range(n - 1, -1, -1) if b.years[k].start in closed), None)
    if last is not None:
        year = closed[b.years[last].start]
        carried = _carried(b, year.closing, year.shares)
        if last == n - 1:
            return carried
    since, base = (-1, typed) if last is None else (last, carried)
    try:
        before = b.post(b.settings, keep=[since < p < n for p in b.placed], opening=base)
    except InvalidTransactions as exc:
        raise InvalidTransactions(f"Fix the earlier years first: {exc.message}", problems=exc.problems) from exc
    return _carried(b, _balances(before))


def opening(store: MongoStore, client_id: int, year_start: dt.date) -> dict[str, Decimal]:
    """The year's opening balances by account, signed with debits positive."""
    b = _books(store, client_id)
    return _opening(b, b.index(year_start))


def trial_balance(store: MongoStore, client_id: int, year_start: dt.date) -> TrialBalance:
    """The year's trial balance: its opening balances plus its own rows, matched with what people decided as the
    ledger is, so it books the rows the ledger books; InvalidTransactions (422) while rows need fixing."""
    b = _books(store, client_id)
    return _trial_balance(b, b.index(year_start))


def trial_balance_shown(store: MongoStore, client_id: int, year_start: dt.date) -> TrialBalance:
    """The year's trial balance for a page to show. While rows of the year need fixing it is still worked out,
    without those rows, and says which are left out (left_out), so one bad row does not hide every figure. The year
    is not ready all the same: trial_balance still refuses, so it can't be closed or its bank checked until they are
    fixed. A problem in an earlier year stops this one too, as its opening balances come from it."""
    b = _books(store, client_id)
    return _shown(b, b.index(year_start))


def _shown(b: _Books, n: int) -> TrialBalance:
    try:
        return _trial_balance(b, n)
    except InvalidTransactions as stopped:
        shown = b.post(b.settings_in(n), keep=[p == n for p in b.placed], opening=_opening(b, n),
                       rules=b.rules_apply(n), skip_errors=True)
        return _owners_named(b, shown).model_copy(update={"left_out": list(stopped.problems)})


def vat_figures(store: MongoStore, client_id: int, year_start: dt.date, start: Optional[dt.date] = None,
                end: Optional[dt.date] = None) -> VatFigures:
    """The VAT return boxes for a period (the year's own when none is given). A VAT quarter often crosses the year end
    (March to May for a year to 31 March): each year's part is worked out from its own rows and the parts added up.
    A part before the books start, or after their last year, is not in them, and the notes say so."""
    b = _books(store, client_id)
    year = b.years[b.index(year_start)]
    start, end = start or year.start, end or year.end
    if start > end:
        raise InvalidInput("Choose a period that ends on or after the day it starts.")
    if year.start <= start and end <= year.end:
        return _vat_in_year(store, client_id, year_start, start, end)
    if end < year.start or start > year.end:
        raise InvalidInput("Choose a period that includes some of this year.")
    notes: list[str] = []
    first, last = b.years[0].start, b.years[-1].end
    before_sales, before_purchases = ZERO, ZERO
    if start < first:
        # The VAT of the part before the books, booked by the previous accountant and not yet returned, is what the
        # opening balances hold on Sales VAT and Purchase VAT; its sales and purchases are not in the books.
        opening = _opening(b, 0) if end >= first else {}
        before_sales, before_purchases = -opening.get(SALES_VAT, ZERO), opening.get(PURCHASE_VAT, ZERO)
        span = f"{long_date(start)} to {long_date(min(end, first - yr.DAY))} is before these books start"
        notes.append(f"{span}: its VAT is the opening balances on Sales VAT ({_gbp(before_sales)}) and Purchase VAT "
                     f"({_gbp(before_purchases)}); add its sales and purchases (boxes 6 and 7) from the previous "
                     "accountant's figures." if before_sales or before_purchases else
                     f"{span}: add those figures from the previous accountant's.")
    if end > last:
        notes.append(f"{long_date(max(start, last + yr.DAY))} to {long_date(end)} is after these books' last year: "
                     "not in these figures.")
    parts = [_vat_in_year(store, client_id, y.start, max(start, y.start), min(end, y.end))
             for y in b.years if max(start, y.start) <= min(end, y.end)]
    for part in parts:
        notes += [note for note in part.notes if note not in notes]
    add = lambda box: sum((getattr(part, box) for part in parts), ZERO)   # noqa: E731
    box1, box4 = add("box1") + before_sales, add("box4") + before_purchases
    return VatFigures(start=start, end=end, box1=box1, box2=add("box2"), box3=box1 + add("box2"), box4=box4,
                      box5=box1 + add("box2") - box4, box6=add("box6"), box7=add("box7"), box8=add("box8"),
                      box9=add("box9"), notes=notes)


def _vat_in_year(store: MongoStore, client_id: int, year_start: dt.date, start: Optional[dt.date] = None,
                 end: Optional[dt.date] = None) -> VatFigures:
    """The VAT return boxes for a period of the year (the whole year when none is given), from the lines the year's
    rows post, each by its row's date: the VAT booked to Sales VAT and Purchase VAT, and the net booked to income
    accounts and to costs and equipment that VAT covers (not wages, rates, fines and the like, which are outside its
    scope). Journals move no supplies and are left out. It is a guide: no VAT scheme is applied, boxes 2, 8 and 9
    are not worked out, and a row held in Suspense or left out for a problem is not in it; the notes say so."""
    b = _books(store, client_id)
    n = b.index(year_start)
    year = b.years[n]
    start, end = start or year.start, end or year.end
    if not (year.start <= start <= end <= year.end):
        raise InvalidInput("Choose a period inside this year.")
    if not b.client.vat_registered:
        raise InvalidInput(f"{b.client.name} is not registered for VAT.")
    tb = trial_balance_shown(store, client_id, year_start)

    settings = b.settings

    def covered(line) -> bool:
        tx = b.stored[line.transaction].tx
        return (tx.document_type != "journal" and tx.date is not None and start <= tx.date <= end
                and registered_on(settings, tx.date))

    def on(codes) -> Decimal:
        return sum((line.debit - line.credit for line in tb.journal if line.code in codes and covered(line)), ZERO)

    sales = {a.code for a in BY_CODE.values() if a.type == AccountType.INCOME and a.vat != VatTreatment.OUTSIDE_SCOPE}
    costs = {a.code for a in BY_CODE.values() if a.vat != VatTreatment.OUTSIDE_SCOPE
             and (a.type == AccountType.EXPENSE or (a.type == AccountType.ASSET and a.code < "1000"))}
    box1, box4 = -on({SALES_VAT}), on({PURCHASE_VAT})
    held = len({line.transaction for line in tb.journal if line.code == SUSPENSE and covered(line)})
    notes = ["A guide worked from the rows booked in the period by their dates. No VAT scheme (flat rate, cash "
             "accounting) is applied, and boxes 2, 8 and 9 are not worked out."]
    if held:
        notes.append(f"{held} row{'' if held == 1 else 's'} in the period {'is' if held == 1 else 'are'} held in "
                     "Suspense for a document, and not in these figures.")
    # The reverse charge on services from abroad: its VAT is in boxes 1 and 4 already, and its value goes in box 6
    # as well as box 7.
    reverse = {line.transaction for line in tb.journal if line.code == SALES_VAT and line.credit and covered(line)
               and b.stored[line.transaction].tx.reverse_charge
               and b.stored[line.transaction].tx.direction == Direction.OUT}
    reverse_net = sum((line.debit - line.credit for line in tb.journal
                       if line.transaction in reverse and line.code in costs), ZERO)
    if reverse:
        charged = sum((line.credit for line in tb.journal if line.transaction in reverse and line.code == SALES_VAT),
                      ZERO)
        notes.append(f"Boxes 1 and 4 each include {_gbp(charged)} reverse-charge VAT on {_gbp(reverse_net)} of "
                     "services from abroad, which is in boxes 6 and 7 too.")
    if settings.vat_from and start < settings.vat_from:
        notes.append(f"Registered for VAT from {long_date(settings.vat_from)}: rows dated before it are not in these "
                     "figures.")
    if tb.left_out:
        notes.append(f"{len(tb.left_out)} row{'' if len(tb.left_out) == 1 else 's'} of the year with a problem to fix "
                     f"{'is' if len(tb.left_out) == 1 else 'are'} left out.")
    return VatFigures(start=start, end=end, box1=box1, box2=ZERO, box3=box1, box4=box4, box5=box1 - box4,
                      box6=-on(sales) + reverse_net, box7=on(costs) - _vat_kept_in_cost(b, tb, costs, covered, settings),
                      box8=ZERO, box9=ZERO, notes=notes)


def _vat_kept_in_cost(b: _Books, tb: TrialBalance, costs: set[str], covered, settings: BusinessSettings) -> Decimal:
    """The VAT on the period's purchases that a rule keeps in the cost (entertainment, a car, the blocked half of a car
    lease): still VAT, so not in box 7, which is purchases excluding VAT whether it is reclaimed or not."""
    rows = {line.transaction for line in tb.journal if line.code in costs and covered(line)}
    kept = ZERO
    for n in rows:
        tx = b.stored[n].tx
        checked = normalise(tx, settings)
        if {i.code for i in checked.issues} & {"vat_blocked", "vat_half_blocked"}:
            kept += (tx.vat or ZERO) - (checked.vat_posted or ZERO)
    return kept


def _trial_balance(b: _Books, n: int) -> TrialBalance:
    return _owners_named(b, b.post(b.settings_in(n), keep=[p == n for p in b.placed], opening=_opening(b, n),
                                   rules=b.rules_apply(n)))


def _owners_named(b: _Books, tb: TrialBalance) -> TrialBalance:
    """The trial balance with each owner's accounts named after them ("Drawings — Ann Lee")."""
    names = owner_names(b.client.business_type, owners_of(b.client))
    if not names:
        return tb

    def named(lines):
        return [line.model_copy(update={"name": f"{BY_CODE[_first_of(line.code)].name} — {names[line.code]}"})
                if line.code in names else line for line in lines]
    return tb.model_copy(update={"lines": named(tb.lines), "opening": named(tb.opening)})


def _first_of(code: str) -> str:
    """The first owner's account of the kind code is (2252 → 2250)."""
    return code[:3] + "0"


def booked_rows(store: MongoStore, client_id: int, year_start: dt.date,
                held: Optional[dict[int, list[str]]] = None) -> list[tuple[int, Transaction]]:
    """The year's booked rows, each with its stored row id, matched exactly as its trial balance matches them;
    InvalidTransactions (422) while any of them needs fixing, as the trial balance raises. With held (a dict) those
    rows are left out instead, and held gets each one's row id with its problems."""
    b = _books(store, client_id)
    n = b.index(year_start)
    found: Optional[list] = [] if held is not None else None
    posted = matched_rows([row.tx for row in b.stored], b.settings_in(n), b.read, b.apart,
                          keep=[p == n for p in b.placed], open_items=b.unpaid, name_days=_name_days(b),
                          upload_ids=[row.upload_id for row in b.stored], skip_errors=held is not None, held=found)
    if held is not None:
        held.update({b.stored[k].id: problems for k, _, problems in found})
    return [(b.stored[k].id, tx) for k, tx in posted]


def _total_and_date(rows: list[Transaction]) -> tuple[Decimal, Optional[dt.date]]:
    """A document's total (its rows' gross, those the other way taken off) and its date, its latest row's."""
    total = sum((tx.gross if tx.direction == rows[0].direction else -tx.gross for tx in rows), ZERO)
    days = [tx.date for tx in rows if tx.date]
    return abs(total), max(days, default=None)


def _invoices(b: _Books, n: int) -> list[InvoiceSummary]:
    ready, statuses = _matched(b, b.settings_in(n))
    start, end = b.years[n].start, b.years[n].end
    refs: dict[str, list[int]] = defaultdict(list)
    for k, tx in enumerate(ready):
        if tx.document_type == "invoice" and booked(tx) and tx.claimed_in is None:
            refs[tx.document_ref or f"row-{k}"].append(k)

    def summary(ref: str, sale: bool, who: Optional[str], number: Optional[str], day: Optional[dt.date],
                total: Decimal, here: bool, credit_note: bool = False) -> Optional[InvoiceSummary]:
        """The invoice if it is dated in the year (here), or was still owed when the year started."""
        status = statuses[ref]
        if not here and total - sum((p.amount for p in status.paid_by if p.date and p.date < start), ZERO) <= 0:
            return None
        by_end = sum((p.amount for p in status.paid_by if p.date is None or p.date <= end), ZERO)
        return InvoiceSummary(ref=ref, kind="sale" if sale else "purchase", counterparty=who, number=number, date=day,
                              total=total, paid=total - status.open, owed=status.open, paid_by=status.paid_by,
                              owed_at_year_end=max(total - by_end, ZERO), brought_forward=not here,
                              credit_note=credit_note)

    found = []
    for ref, ks in refs.items():
        if ref not in statuses:
            continue
        rows = [ready[k] for k in ks]
        total, day = _total_and_date(rows)
        latest = next((k for k in ks if ready[k].date == day), ks[0])
        if b.placed[latest] <= n:
            sale = rows[0].contra_account_code == DEBTORS
            way = (rows[0].document_direction or rows[0].direction).value
            found.append(summary(ref, sale,
                                 next((tx.counterparty for tx in rows if tx.counterparty), None),
                                 next((tx.document_number for tx in rows if tx.document_number), None), day, total,
                                 b.placed[latest] == n, credit_note=way != ("in" if sale else "out")))
    for item in [*b.opening.unpaid, *not_itemised(b.opening)]:
        found.append(summary(f"ob-{item.id}", item.direction.value == "in", item.counterparty, item.number, item.date,
                             item.amount, False))
    return sorted((i for i in found if i), key=lambda i: (i.date is None, i.date or dt.date.min, i.ref))


def invoices(store: MongoStore, client_id: int, year_start: dt.date) -> list[InvoiceSummary]:
    """The year's booked invoices, and the earlier ones and open items still owed when it started, oldest first. Each
    says what has been paid and what is still owed after every payment, in any year, and what was owed at the year's
    end (the year's Debtors and Creditors hold that)."""
    b = _books(store, client_id)
    return _invoices(b, b.index(year_start))


class _Statement(NamedTuple):
    """One upload's lines on a bank account in a year, with the balances it prints: opening before its first line and
    closing after its last, from its printed opening and closing or else from its running balances (None when it
    prints neither)."""
    upload_id: int
    first: dt.date
    last: dt.date
    opening: Optional[Decimal]
    closing: Optional[Decimal]
    balances: frozenset = frozenset()   # every balance it shows: its opening, and the running balance after each line


def _statements(b: _Books, n: int) -> dict[str, list[_Statement]]:
    """Each bank account's statements in year n, by account code, oldest first. A statement that prints no closing
    balance but a running balance on its lines (Starling, Monzo and most CSV exports) closes at its last line's
    balance and opens at its first line's balance less that line."""
    found: dict[str, list[_Statement]] = defaultdict(list)
    kinds = {a.code: a.kind for a in b.client.bank_accounts}
    for upload in b.uploads:
        lines = [k for k, row in enumerate(b.stored) if row.upload_id == upload["id"]
                 and row.tx.document_type == "statement" and row.tx.date and b.placed[k] == n]
        if not lines:
            continue
        account = upload["bank_account"] or b.settings.bank_account
        card = kinds.get(account) == "credit_card"
        lines.sort(key=lambda k: (b.stored[k].tx.date, k))
        txs = [b.stored[k].tx for k in lines]
        closings = [tx.closing_balance for tx in txs if tx.closing_balance is not None]
        openings = [tx.opening_balance for tx in txs if tx.opening_balance is not None]
        closing = closings[-1] if closings else txs[-1].balance
        opening = openings[0] if openings else (txs[0].balance - signed(txs[0], card)
                                                if txs[0].balance is not None else None)
        shown = frozenset(x for x in (opening, *(tx.balance for tx in txs)) if x is not None)
        found[account].append(_Statement(upload["id"], txs[0].date, txs[-1].date, opening, closing, shown))
    for account in found:
        found[account].sort(key=lambda s: (s.first, s.upload_id))
    return found


def _held(b: _Books, tb: TrialBalance, code: str, day: Optional[dt.date], *, before: bool = False) -> Decimal:
    """What the books hold in the account, from its opening and the year's rows up to day (all of them if None;
    only those dated before day with before), as a statement prints it (what a card owes is positive)."""
    def counts(line) -> bool:
        when = b.stored[line.transaction].tx.date or dt.date.max
        return day is None or (when < day if before else when <= day)

    moved = sum((line.debit - line.credit for line in tb.journal if line.code == code and counts(line)), ZERO)
    balance = moved + sum((line.debit - line.credit for line in tb.opening if line.code == code), ZERO)
    return -balance if next(a.kind for a in b.client.bank_accounts if a.code == code) == "credit_card" else balance


def _bank_checks(b: _Books, n: int, tb: TrialBalance) -> list[BankCheck]:
    """Each account's books against its latest statement ending in the year: that statement's last line's date and
    closing balance."""
    statements = _statements(b, n)
    checks = []
    for account in b.client.bank_accounts:
        latest = max((s for s in statements.get(account.code, []) if s.closing is not None),
                     key=lambda s: (s.last, s.upload_id), default=None)
        day, printed = (latest.last, latest.closing) if latest else (None, None)
        books = _held(b, tb, account.code, day)
        checks.append(BankCheck(code=account.code, name=account.name, kind=account.kind, books=books, statement=printed,
                                statement_date=day, difference=None if printed is None else books - printed,
                                left_out=len(tb.left_out)))
    return checks


def _months(start: dt.date, stop: dt.date) -> Optional[str]:
    """The months from start's month up to, not including, stop's month, in words ("April to September 2026",
    "December 2025 to January 2026", "May 2026"); None when there are none."""
    first = start.replace(day=1)
    last = stop.replace(day=1) - yr.DAY
    if last < first:
        return None
    if (first.year, first.month) == (last.year, last.month):
        return f"{first:%B %Y}"
    return f"{first:%B} to {last:%B %Y}" if first.year == last.year else f"{first:%B %Y} to {last:%B %Y}"


def _pointers(tb: TrialBalance) -> list[str]:
    """What an accountant would want pointed out in the year's figures: a director's loan the director owes (a debit
    balance), which s455 taxes if it is still owed nine months after the year end."""
    found = []
    for line in tb.lines:
        owed = line.debit - line.credit
        if line.code in DIRECTORS_LOANS and owed > 0:
            found.append(f"The {line.name} is overdrawn by {_gbp(owed)} (the director owes the company). If it is still "
                         "owed nine months after the year end, s455 tax is due on it"
                         + (", and a loan over £10,000 at any time in the year is a benefit in kind for the P11D."
                            if owed > 10000 else "."))
    # More paid off a loan than the books say was owed: its opening balance is missing, or the repayments hold
    # interest that belongs in the costs.
    loans = sum((line.debit - line.credit for line in tb.lines if line.code in (LOANS, LONG_TERM[LOANS])), ZERO)
    if loans > 0:
        found.append(f"Loans is {_gbp(loans)} in debit: more has been repaid than the books show was borrowed. Enter "
                     "the loan's opening balance, and move the interest in the repayments to Loan and Hire Purchase "
                     "Interest.")
    return found


def _missing_paperwork(b: _Books, n: int, tb: TrialBalance) -> list[str]:
    """The statements the year's books need and don't have, for each of the client's bank accounts and cards (petty
    cash has none): an account with no statement in the year; and a break in the chain, where a statement opens at
    another balance than the books held before it (the first) or the one before it closed at, with the months between
    that no statement covers; and, before a statement that prints no balance, the months with no lines at all."""
    statements = _statements(b, n)
    missing = []
    for account in b.client.bank_accounts:
        if account.kind == "petty_cash":
            continue
        mine = statements.get(account.code, [])
        if not mine:
            missing.append(f"{account.name}: no statement for this year yet.")
            continue
        previous: Optional[_Statement] = None
        for s in mine:
            if s.opening is None:
                # No balance printed, so nothing can show whether lines are missing before it: the months no
                # statement covers are said, for a person to judge.
                since = (previous.last.replace(day=28) + dt.timedelta(days=4) if previous is not None
                         else b.years[n].start)
                months = _months(since, s.first)
                if months:
                    missing.append(f"{account.name}: no statement lines for {months}. The statement from "
                                   f"{long_date(s.first)} prints no balance to check, so add those months' "
                                   "statements if the account was in use.")
                previous = s
                continue
            if previous is None:
                expected, said = _held(b, tb, account.code, s.first, before=True), "the books have {x} then"
                months = _months(b.years[n].start, s.first)
            elif previous.closing is not None:
                expected, said = previous.closing, "the one before closed at {x}"
                months = _months(previous.last.replace(day=28) + dt.timedelta(days=4), s.first)
            else:
                previous = s
                continue
            # A statement that starts inside the one before it opens at a balance that one shows part-way through:
            # the two overlap, and nothing is missing between them.
            overlaps = previous is not None and s.first <= previous.last and s.opening in previous.balances
            if s.opening != expected and not overlaps:
                gap = f"no statements for {months}" if months else "lines are missing before it"
                missing.append(f"{account.name}: {gap}. The statement from {long_date(s.first)} opens at "
                               f"{_gbp(s.opening)}; {said.format(x=_gbp(expected))}.")
            if previous is None or s.last >= previous.last:   # one wholly inside the last is not the latest
                previous = s
    return missing


def bank_checks(store: MongoStore, client_id: int, year_start: dt.date) -> list[BankCheck]:
    """One check for each of the client's bank accounts: its balance in the books, from the opening balances and the
    year's rows up to the date of its latest statement of the year (the year's end with none), against that
    statement's closing balance, both as the statement prints it (what a card owes is positive). While rows of the
    year need fixing, the books are worked out without them, as the trial balance page shows them."""
    b = _books(store, client_id)
    n = b.index(year_start)
    return _bank_checks(b, n, _shown(b, n))


def summary(store: MongoStore, client_id: int, year_start: dt.date) -> YearSummary:
    """The year at a glance. While rows need fixing its trial balance is blocked, with the problems, and there are no
    bank checks, which are worked out from it. What is unpaid is what was owed on the year's invoices when it ended."""
    b = _books(store, client_id)
    n = b.index(year_start)
    rows, _ = _saved_rows(b, n)
    end = b.years[n].end

    def owed_at_end(i: InvoiceSummary) -> Decimal:
        """What was owed on the invoice when the year ended: its total less the payments dated by then."""
        return max(i.total - sum((p.amount for p in i.paid_by if p.date and p.date <= end), ZERO), ZERO)

    owed = _invoices(b, n)
    problems: list[str] = []
    bank: list[BankCheck] = []
    missing: list[str] = []
    pointers: list[str] = []
    try:
        tb = _trial_balance(b, n)
        bank = _bank_checks(b, n, tb)
        missing = _missing_paperwork(b, n, tb)
        pointers = _pointers(tb)
        if not tb.is_balanced:
            problems = [f"The trial balance doesn't balance: debits {_gbp(tb.total_debits)}, credits "
                        f"{_gbp(tb.total_credits)}."]
    except InvalidTransactions as exc:
        problems = exc.problems
        try:   # the bank and the paperwork still show, worked out without the rows that need fixing
            tb = _shown(b, n)
            bank, missing, pointers = _bank_checks(b, n, tb), _missing_paperwork(b, n, tb), _pointers(tb)
        except InvalidTransactions:   # an earlier year's rows need fixing: nothing to work this one out from
            pass
    return YearSummary(year=_year_now(b, n), rows=len(rows), to_review=sum(needs_review(r) for r in rows),
                       unpaid_sales=sum((owed_at_end(i) for i in owed if i.kind == "sale"), ZERO),
                       unpaid_purchases=sum((owed_at_end(i) for i in owed if i.kind == "purchase"), ZERO), bank=bank,
                       trial_balance="blocked" if problems else "balanced", problems=problems,
                       missing_paperwork=missing, pointers=pointers)


def export(store: MongoStore, client_id: int, year_start: dt.date, day: dt.date) -> tuple[bytes, str]:
    """The year's workbook and its file name; while rows need fixing, the trial balance sheet says what."""
    built = ledger(store, client_id, year_start)
    try:
        balance = trial_balance(store, client_id, year_start)
    except InvalidTransactions as exc:
        balance = exc.problems
    return workbook(built, balance, day), file_name(built.client.name, day)


def check_opening(opening: OpeningBalances) -> None:
    """Opening balances go on balance sheet accounts and balance. The unpaid invoices listed are part of Debtors and
    Creditors, so a payment of each can clear it; they can't add up to more. What is not listed is brought forward
    as one balance (not_itemised), for when only the total is known."""
    for line in opening.lines:
        account = BY_CODE.get(line.code)
        if account is None:
            raise InvalidInput(f"{line.code} isn't an account in the chart.")
        if account.type.value in _PROFIT_AND_LOSS:
            raise InvalidInput(f"Opening balances take balance sheet accounts only: {account.code} {account.name} is "
                               "income or a cost.")
        if line.debit < 0 or line.credit < 0:
            raise InvalidInput("Opening amounts can't be negative.")
    debits = sum((line.debit for line in opening.lines), ZERO)
    credits = sum((line.credit for line in opening.lines), ZERO)
    if debits != credits:
        raise InvalidInput(f"Opening debits {_gbp(debits)} and credits {_gbp(credits)} must be the same.")
    ids: set[str] = set()
    for item in opening.unpaid:
        if not item.id or item.id in ids:
            raise InvalidInput("Give each unpaid invoice an id of its own.")
        ids.add(item.id)
        if not item.counterparty:
            raise InvalidInput("Name the customer or supplier of each unpaid invoice.")
        if item.amount <= 0:
            raise InvalidInput("Enter the amount still owed on each unpaid invoice.")
    balances = _typed(opening)
    for direction, code, sign, text in (("in", DEBTORS, 1, "The unpaid invoices from customers add up to {x}, "
                                                         "more than Debtors, which is {y}."),
                                        ("out", CREDITORS, -1, "The unpaid bills from suppliers add up to {x}, "
                                                               "more than Creditors, which is {y}.")):
        owed = sum((item.amount for item in opening.unpaid if item.direction.value == direction), ZERO)
        balance = sign * balances.get(code, ZERO)
        if owed > balance:   # less is allowed: the rest is brought forward as one balance, not itemised
            raise InvalidInput(text.format(x=_gbp(owed), y=_gbp(balance)))


def set_opening(store: MongoStore, client_id: int, opening: OpeningBalances) -> Client:
    """Saves the client's first year's opening balances once they make sense, while the first year is open."""
    client = store.get_client(client_id)
    require_active(client)
    ensure_open(client, [yr.year_bounds(client.first_year_end, 0)[0]])
    check_opening(opening)
    store.set_opening(client_id, opening)
    return store.get_client(client_id)


def close(store: MongoStore, client_id: int, year_start: dt.date) -> Client:
    """Closes the year, after the ones before it, once its trial balance balances: it is locked until reopened,
    and keeps the balances it closed with for the next year to open with."""
    b = _books(store, client_id)
    require_active(b.client)
    n = b.index(year_start)
    year = b.years[n]
    if year.closed:
        raise InvalidInput(f"The year to {long_date(year.end)} is already closed.")
    still_open = next((y for y in b.years[:n] if not y.closed), None)
    if still_open is not None:
        raise InvalidInput(f"Close the year to {long_date(still_open.end)} first.")
    try:
        tb = _trial_balance(b, n)
    except InvalidTransactions as exc:
        count = len(exc.problems)
        raise InvalidInput(f"{count} row{'' if count == 1 else 's'} of the year {'has' if count == 1 else 'have'} a "
                           f"problem to fix before it can be closed: {exc.problems[0]}"
                           f"{'' if count == 1 else f' (and {count - 1} more)'}") from exc
    if not tb.is_balanced:
        raise InvalidInput("The trial balance must balance before the year is closed.")
    # A question whose answer changes the VAT or tax (who was at a meal, which account) holds the year until a
    # person answers it or accepts the row as it is; presentation questions don't.
    ready, _ = _matched(b, b.settings_in(n))
    open_facts = [i.message for tx, p in zip(ready, b.placed) if p == n and booked(tx)
                  for i in tx.issues if i.code in FACT_QUESTIONS]
    if open_facts:
        count = len(open_facts)
        raise InvalidInput(f"{count} question{'' if count == 1 else 's'} that change{'s' if count == 1 else ''} the "
                           f"tax {'is' if count == 1 else 'are'} still open: answer {'it' if count == 1 else 'them'} "
                           f"or accept the row{'' if count == 1 else 's'} before the year is closed. {open_facts[0]}"
                           f"{'' if count == 1 else f' (and {count - 1} more)'}")
    return store.close_year(client_id, ClosedYear(start=year.start, end=year.end, closed_at=now_iso(),
                                                  closing=_balances(tb),
                                                  rules=DOCUMENT_RULES, shares=list(_shares(b.client))))


def reopen(store: MongoStore, client_id: int, year_start: dt.date) -> Client:
    """Reopens the latest closed year, so it can be changed; the next year opens from its rows again."""
    b = _books(store, client_id)
    require_active(b.client)
    year = b.years[b.index(year_start)]
    if not year.closed:
        raise InvalidInput(f"The year to {long_date(year.end)} is open.")
    latest = b.client.closed_years[-1]
    if latest.start != year_start:
        raise InvalidInput(f"Reopen the year to {long_date(latest.end)} first.")
    return store.reopen_year(client_id, year_start)
