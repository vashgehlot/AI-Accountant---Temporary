"""A client and a person's changes to its rows (design of 2026-10-06), checked before the store saves them: the
client's settings and bank accounts, the client summaries, and the row and upload actions, each returning the
ledger of the year the change was made in, and refused in a closed year. books.py works out a year's ledger and
trial balance."""
from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal
from typing import Iterable, Optional
from weakref import WeakKeyDictionary

from .accounts import (BANK_SLOTS, BY_CODE, CARDS, MAX_OWNERS, OWNER_WORDS, STAFF_EXPENSES, SUSPENSE, AccountType,
                       Owners, choosable, owner_codes, owner_slots, pays_cards)
from .checks import ACCEPTABLE, long_date
from .payees import card_payment
from .errors import ClientArchived, InvalidInput, NotFound, YearClosed
from .models import (BankAccount, BusinessSettings, Client, ClientFields, ClientPatch, ClientSummary, Ledger, Owner,
                     ManualUpload, RowPatch, Transaction)
from .rows import WHOLE_DOCUMENT, StoredRow
from .store_mongo import MongoStore
from .years import year_bounds, year_index


def bank_codes(client: Client) -> tuple[str, ...]:
    """The codes of the client's bank accounts and cards."""
    return tuple(a.code for a in client.bank_accounts)


def settings_for(client: Client) -> BusinessSettings:
    """How a client's rows are booked: its name (whose books), its VAT registration and kind of business, and its
    bank accounts and cards. Its first current account is the default bank (its first account if it has none)."""
    codes = bank_codes(client)
    default = next((a.code for a in client.bank_accounts if a.kind == "current"), codes[0])
    return BusinessSettings(business_name=client.name, vat_registered=client.vat_registered,
                            vat_from=client.vat_from if client.vat_registered else None,
                            business_type=client.business_type, bank_accounts=codes, bank_account=default,
                            owners=owner_slots_of(client), owner_names=tuple(name for _, name in owners_of(client)),
                            books_start=year_bounds(client.first_year_end, 0)[0],
                            capitalise_from=client.capitalise_from, nature_of_business=client.nature_of_business,
                            sic_code=client.sic_code)


def bank_choices(client: Client, upload_bank: Optional[str] = None) -> tuple[str, ...]:
    """The client's bank accounts a row may be coded to, for accounts.choosable: none for a client with one account,
    which keeps the chart's usual offer; for a client with several, all of them (a transfer between two), and when
    reading an upload, all but the upload's own."""
    codes = bank_codes(client)
    if len(codes) == 1:
        return ()
    return tuple(c for c in codes if c != upload_bank)


def owners_of(client: Client) -> Owners:
    """The client's directors, partners or members as accounts.choosable takes them: each one's slot and name."""
    return tuple((o.slot, o.name) for o in client.owners if o.slot is not None)


def owner_slots_of(client: Client) -> tuple[int, ...]:
    return tuple(slot for slot, _ in owners_of(client))


def _choosable_codes(client: Client) -> set[str]:
    """The accounts a row of this client can be coded to."""
    return {a.code for a in choosable(client.business_type, bank_choices(client), owners_of(client))}


def check_bank_account(client: Client, code: str) -> None:
    if code not in bank_codes(client):
        raise InvalidInput(f"Choose one of {client.name}'s bank accounts.")


def paid_personally(client: Client) -> tuple[str, ...]:
    """The accounts for a receipt someone paid themselves: an owner (their director's loan in a company, the capital
    they paid in otherwise), or staff who are to be repaid."""
    capitals = owner_slots(client.business_type)["capital"]
    return (*(capitals[n] for n in owner_slots_of(client) or (0,)), STAFF_EXPENSES)


def require_active(client: Client) -> None:
    if client.archived:
        raise ClientArchived(f"Restore {client.name} to add documents or make changes.")


def ensure_open(client: Client, days: Iterable[Optional[dt.date]], year_start: Optional[dt.date] = None) -> None:
    """Refuses a change to rows of a closed year: rows dated on the days, a day of None counting as year_start (the
    year an undated row waits in), and a day before the first year as the first, which shows it."""
    closed = {c.start for c in client.closed_years}
    if not closed:
        return
    for day in days:
        day = day or year_start
        if day is None:
            continue
        start, end = year_bounds(client.first_year_end, year_index(client.first_year_end, day) or 0)
        if start in closed:
            raise YearClosed(f"The year to {long_date(end)} is closed. Reopen it to change it.")


def _days(store: MongoStore, client: Client, rows: Iterable[StoredRow]) -> list[Optional[dt.date]]:
    """Each row's date, or for an undated row the start of the year it waits in."""
    uploads = {u["id"]: u for u in store.uploads(client.id)}
    days = []
    for row in rows:
        n = None if row.tx.date else _books().year_of_row(client, row, uploads)
        days.append(row.tx.date or (year_bounds(client.first_year_end, n)[0] if n is not None else None))
    return days


# How a message names each kind of bank account.
_KIND_NAMES = {"current": "current", "savings": "savings", "credit_card": "credit card", "petty_cash": "petty cash"}


def check_client(fields: ClientFields) -> None:
    """A client needs a company name and a responsible person, and an email needs an @. It has at least one bank
    account, each with a name of its own, and no more of a kind than the chart has codes for."""
    if not fields.name:
        raise InvalidInput("Enter the company name.")
    if not fields.contact_name:
        raise InvalidInput("Enter the responsible person.")
    if fields.first_year_end is None:
        raise InvalidInput("Enter the client's first year end.")
    if fields.contact_email and "@" not in fields.contact_email:
        raise InvalidInput("Enter a valid email.")
    if not fields.bank_accounts:
        raise InvalidInput("Add at least one bank account.")
    names: set[str] = set()
    for account in fields.bank_accounts:
        if not account.name:
            raise InvalidInput("Name each bank account.")
        if account.name.lower() in names:
            raise InvalidInput(f"Two bank accounts are called {account.name}: give each its own name.")
        names.add(account.name.lower())
    for kind, codes in BANK_SLOTS.items():
        if sum(a.kind == kind for a in fields.bank_accounts) > len(codes):
            raise InvalidInput(f"You can add up to {len(codes)} {_KIND_NAMES[kind]} accounts.")
    check_owners(fields)


def check_owners(fields: ClientFields) -> None:
    """A company lists its directors, a partnership its partners and an LLP its members, up to four, each with a
    name of their own; a sole trader lists none. Partners' and members' shares of the profit, when given, are given
    for each of them and add up to 100%."""
    word = OWNER_WORDS.get(fields.business_type)
    if word is None:
        if fields.owners:
            raise InvalidInput("A sole trader has no directors, partners or members to list.")
        return
    if len(fields.owners) > MAX_OWNERS:
        raise InvalidInput(f"You can list up to {MAX_OWNERS} {word}s.")
    names: set[str] = set()
    for owner in fields.owners:
        if not owner.name:
            raise InvalidInput(f"Name each {word}.")
        if owner.name.lower() in names:
            raise InvalidInput(f"Two {word}s are called {owner.name}: give each their own name.")
        names.add(owner.name.lower())
    if fields.business_type == "limited_company":
        return
    shares = [owner.share for owner in fields.owners]
    if any(share is not None for share in shares):
        if any(share is None or share <= 0 for share in shares):
            raise InvalidInput(f"Give each {word}'s share of the profit, above 0%.")
        if sum(shares) != 100:
            raise InvalidInput(f"The {word}s' shares of the profit add up to {sum(shares):g}%: make them 100%.")


# How each of a client's references is written, spaces aside, and what to say when one isn't.
_REFERENCE_FORMS = {
    "company_number": (re.compile(r"^(\d{8}|[A-Z]{2}\d{6}|[A-Z]\d{7})$"),
                       "A company number has 8 characters, such as 01234567 or SC123456."),
    "utr": (re.compile(r"^\d{10}$"), "A UTR has 10 digits."),
    "vat_number": (re.compile(r"^(GB|XI)?(\d{9}|\d{12})$"), "A VAT number has 9 digits, such as GB 123 4567 89."),
    "paye_reference": (re.compile(r"^\d{3}/[A-Z0-9]{1,10}$"), "A PAYE reference looks like 123/AB456."),
}
YEAR_END_BACK, YEAR_END_AHEAD = 10, 2   # years before and after today a first year end may be
MOST = Decimal("1000000000")            # an amount of a billion pounds or more is a slip of the keys
AHEAD = dt.timedelta(days=366)          # a row typed in is dated within a year from today


def check_references(fields: ClientFields) -> None:
    """Each reference that is filled in is written as HMRC or Companies House writes it."""
    for field, (form, message) in _REFERENCE_FORMS.items():
        value = "".join(str(getattr(fields, field) or "").split()).upper()
        if value and not form.match(value):
            raise InvalidInput(message)


def check_year_end(day: dt.date, today: Optional[dt.date] = None) -> None:
    """A first year end within a few years of today: 1990, or 2062, is a slip, and would open years of empty books."""
    today = today or dt.date.today()
    if not today.year - YEAR_END_BACK <= day.year <= today.year + YEAR_END_AHEAD:
        raise InvalidInput(f"Enter a first year end between {today.year - YEAR_END_BACK} and "
                           f"{today.year + YEAR_END_AHEAD}.")


def assign_codes(accounts: list[BankAccount], kept: list[BankAccount]) -> list[BankAccount]:
    """The accounts, each without a code given the next free code of its kind; an account sent with its code keeps
    it. kept: the accounts rows still use, which can't be dropped."""
    for account in accounts:
        if account.code and account.code not in BANK_SLOTS[account.kind]:
            raise InvalidInput(f"{account.code} isn't a code for a {_KIND_NAMES[account.kind]} account.")
    taken = [a.code for a in accounts if a.code]
    if len(taken) != len(set(taken)):
        raise InvalidInput("Two bank accounts have the same code.")
    for account in kept:
        if account.code not in taken:
            raise InvalidInput(f"{account.name} has transactions: move them to another account first.")
    used, coded = set(taken), []
    for account in accounts:
        if not account.code:
            free = next(c for c in BANK_SLOTS[account.kind] if c not in used)   # check_client counted them
            used.add(free)
            account = account.model_copy(update={"code": free})
        coded.append(account)
    return coded


def assign_owners(owners: list[Owner], kept: list[Owner]) -> list[Owner]:
    """The owners, each without a slot given the next free one; an owner sent with their slot keeps it. kept: the
    owners whose accounts rows still use, who can't be dropped."""
    for owner in owners:
        if owner.slot is not None and not 0 <= owner.slot < MAX_OWNERS:
            raise InvalidInput(f"{owner.name} has no accounts of their own in the chart.")
    taken = [o.slot for o in owners if o.slot is not None]
    if len(taken) != len(set(taken)):
        raise InvalidInput("Two owners have the same accounts.")
    for owner in kept:
        if owner.slot not in taken:
            raise InvalidInput(f"{owner.name}'s accounts have transactions: move them to another account first.")
    used, slotted = set(taken), []
    for owner in owners:
        if owner.slot is None:
            free = next(n for n in range(MAX_OWNERS) if n not in used)   # check_owners counted them
            used.add(free)
            owner = owner.model_copy(update={"slot": free})
        slotted.append(owner)
    return slotted


def _owners_in_use(store: MongoStore, client: Client) -> list[Owner]:
    """The client's owners whose accounts rows are coded to."""
    used = {row.tx.account_code for row in store.rows(client.id)}
    return [o for o in client.owners
            if o.slot is not None and owner_codes(client.business_type, (o.slot,)) & used]


def _accounts_in_use(store: MongoStore, client: Client) -> list[BankAccount]:
    """The client's bank accounts that rows are on, or are coded to (a transfer). A row on no account of its own is on
    the default bank."""
    default = settings_for(client).bank_account
    used = {code for row in store.rows(client.id) for code in (row.tx.bank_account or default, row.tx.account_code)}
    return [a for a in client.bank_accounts if a.code in used]


def _check_name_free(store: MongoStore, name: str, besides: Optional[int] = None) -> None:
    """Two clients that are not archived can't share a name: their books would be told apart only by guesswork."""
    wanted = " ".join(name.lower().split())
    for other in store.list_clients():
        if other.id != besides and not other.archived and " ".join(other.name.lower().split()) == wanted:
            raise InvalidInput(f"Another client is already called {other.name}.")


def add_client(store: MongoStore, fields: ClientFields) -> Client:
    check_client(fields)
    check_year_end(fields.first_year_end)
    check_references(fields)
    _check_name_free(store, fields.name)
    return store.create_client(fields.model_copy(update={"bank_accounts": assign_codes(fields.bank_accounts, []),
                                                         "owners": assign_owners(fields.owners, [])}))


def change_client(store: MongoStore, client_id: int, patch: ClientPatch) -> Client:
    """Edits, archives or restores a client; an edited client must still be complete, and keeps the bank accounts its
    rows are on. Once a year is closed, its year end, VAT registration and kind of business stay as they are."""
    client = store.get_client(client_id)
    sent = patch.model_dump(exclude_unset=True)
    changes = {k: v for k, v in sent.items() if k != "archived" and v is not None}
    if client.closed_years and changes.get("first_year_end", client.first_year_end) != client.first_year_end:
        raise InvalidInput("The year end can't change once a year is closed.")
    if changes.get("first_year_end", client.first_year_end) != client.first_year_end and not client.archived:
        check_year_end(changes["first_year_end"])
        # Rows of the books now that the new first year would start after: they would drop out, into the opening
        # balances, with nothing said.
        was, start = year_bounds(client.first_year_end, 0)[0], year_bounds(changes["first_year_end"], 0)[0]
        dropped = sum(1 for row in store.rows(client_id) if row.tx.date and was <= row.tx.date < start)
        if dropped:
            raise InvalidInput(f"{dropped} row{'' if dropped == 1 else 's'} of the books "
                               f"{'is' if dropped == 1 else 'are'} dated before {long_date(start)}, when the first year "
                               "would then start, and would drop out of them. Choose an earlier year end, or remove "
                               "those rows first.")
    if not client.archived and any(field in changes for field in _REFERENCE_FORMS):
        check_references(ClientFields(**{**client.model_dump(include=set(ClientFields.model_fields)), **changes}))
    for field, what in (("vat_registered", "VAT registration"), ("business_type", "business type")):
        if client.closed_years and changes.get(field, getattr(client, field)) != getattr(client, field):
            raise YearClosed(f"Reopen the closed years to change the client's {what}: it changes how they were "
                             "booked.")
    if "vat_from" in sent and sent["vat_from"] != client.vat_from and client.closed_years and min(
            sent["vat_from"] or dt.date.min, client.vat_from or dt.date.min) <= client.closed_years[-1].end:
        raise YearClosed("Reopen the closed years to change when the VAT registration started: it changes how they "
                         "were booked.")
    if changes and not client.archived:
        merged = ClientFields(**{**client.model_dump(include=set(ClientFields.model_fields)), **changes})
        check_client(merged)
        if "name" in changes:
            _check_name_free(store, merged.name, besides=client_id)
        if "bank_accounts" in changes:
            merged.bank_accounts = assign_codes(merged.bank_accounts, _accounts_in_use(store, client))
        if "owners" in changes:
            merged.owners = assign_owners(merged.owners, _owners_in_use(store, client))
        changes = {k: getattr(merged, k) for k in changes}
    if sent.get("archived") is not None:
        changes["archived"] = sent["archived"]
    if "vat_from" in sent and sent["vat_from"] is None:
        changes["vat_from"] = None   # cleared
    if "materiality" in sent and sent["materiality"] is None:
        changes["materiality"] = None   # cleared: worked out from the client's figures
    if "capitalise_from" in sent and sent["capitalise_from"] is None:
        changes["capitalise_from"] = None   # cleared: no capitalisation threshold
    return store.update_client(client_id, changes)


def needs_review(row: Transaction) -> bool:
    """A row with a warning or an error, unless a decision left it out of the books or replaced it with a split: what
    is wrong with it no longer matters, as the agent does not look at it either."""
    if row.excluded or row.superseded_by:
        return False
    return any(found.severity in ("error", "warning") for found in row.issues)


# Each store's clients: (revision, rows, rows to review), as the clients page last worked them out.
_counted: WeakKeyDictionary[MongoStore, dict[int, tuple[int, int, int]]] = WeakKeyDictionary()


def _books():
    """books.py, which builds on this module's settings_for, so it is imported when first used."""
    from . import books
    return books


def _year_of(store: MongoStore, client: Client, row: Optional[StoredRow] = None,
             upload_id: Optional[int] = None) -> Optional[int]:
    """The year a change is made in: the row's year, or the year of an upload's first row, or the year it was added
    to; None when nothing says (the latest year)."""
    uploads = {u["id"]: u for u in store.uploads(client.id)}
    if row is None and upload_id is not None:
        row = next((r for r in store.rows(client.id) if r.upload_id == upload_id), None)
        if row is None:
            added = (uploads.get(upload_id) or {}).get("year_start")
            return year_index(client.first_year_end, added) or 0 if added else None
    if row is None:
        return None
    return _books().year_of_row(client, row, uploads) or 0   # a row before the first year shows in it


def summaries(store: MongoStore, archived: bool = False, records=None) -> list[ClientSummary]:
    """The clients page: each client with how many rows it has, how many need a look and, given the agent's
    records, how many changes the background review made that the person hasn't seen. A client's ledger is
    built again only once its work has changed (its revision moved)."""
    counted = _counted.setdefault(store, {})
    found = []
    for client in store.list_clients(archived):
        revision = store.revision(client.id)   # read before the rows, so a change made meanwhile shows next time
        known = counted.get(client.id)
        if known is None or known[0] != revision:
            rows = _books().all_rows(store, client.id)
            known = counted[client.id] = (revision, len(rows), sum(needs_review(r) for r in rows))
        unseen = records.unseen_background_changes(client.id) if records is not None else 0
        found.append(ClientSummary(**client.model_dump(), rows=known[1], to_review=known[2], ai_unseen=unseen))
    return found


# A field sent as null that can't be left empty, and what to tell the person.
_NEEDED = {"vat_confirmed": "Say whether to reclaim the VAT.", "direction": "Choose money in or out.", "gross": "Enter the amount.", "account_code": "Choose an account.",
           "document_type": "Choose a document type.", "include": "Tick or untick Include.",
           "reverse_charge": "Tick or untick Reverse charge.", "accepted": "Say which warnings are fine."}


def _check_edit(patch: RowPatch, sent: set[str], tx: Transaction, client: Client) -> None:
    for field, message in _NEEDED.items():
        if field in sent and getattr(patch, field) is None:
            raise InvalidInput(message)
    if "description" in sent and not patch.description:
        raise InvalidInput("Enter a description.")
    if "without_document" in sent and patch.without_document is not None and not (
            0 < len(patch.without_document) <= 300):
        raise InvalidInput("Say why it is booked without its receipt or invoice, in up to 300 characters.")
    if "link" in sent and (patch.document_type if "document_type" in sent else tx.document_type) not in (
            "statement", "agent_statement"):
        raise InvalidInput("Only a bank line, or an item of an agent's statement, can be linked to documents.")
    if "account_code" in sent and patch.account_code not in _choosable_codes(client):
        raise InvalidInput(f"This account can't be chosen for {client.name}.")
    if tx.document_type == "journal" and sent - {"date", "description", "gross"}:
        raise InvalidInput("Only a journal's date, description and amount can be changed. Remove it and enter it "
                           "again to change its accounts.")
    if "document_type" in sent and patch.document_type == "journal":
        raise InvalidInput("Add a journal from the Trial balance page.")
    if "bank_account" in sent:
        kind = patch.document_type if "document_type" in sent else tx.document_type
        if kind != "receipt":
            raise InvalidInput("Only a receipt says what paid it: a bank line is on its statement's account, and an "
                               "invoice is owed until a bank line pays it.")
        if patch.bank_account is not None and patch.bank_account not in (*bank_codes(client), *paid_personally(client)):
            raise InvalidInput(f"Choose one of {client.name}'s bank accounts, or who paid it themselves.")
    if "reverse_charge" in sent and patch.reverse_charge and (
            patch.document_type if "document_type" in sent else tx.document_type) not in ("receipt", "invoice"):
        raise InvalidInput("The reverse charge is set on the supplier's invoice or receipt, not on the bank line.")
    if "total_accepted" in sent and patch.total_accepted is not None and not (
            0 < abs(patch.total_accepted) < MOST):
        raise InvalidInput("There is no difference to leave.")
    if "removed" in sent and patch.removed is not False:
        raise InvalidInput("Use Remove to take a row out of the books.")
    if "removed" in sent and not tx.removed:
        raise InvalidInput("This row was not removed.")
    if "accepted" in sent and not set(patch.accepted) <= ACCEPTABLE:
        raise InvalidInput("Only a warning that is a matter of judgement can be marked as fine.")
    if "currency" in sent and patch.currency != "GBP":
        raise InvalidInput("An amount can only be converted to pounds.")
    gross = patch.gross if "gross" in sent else tx.gross
    vat = patch.vat if "vat" in sent else tx.vat
    if "vat_confirmed" in sent and patch.vat_confirmed and not (vat is not None and vat > 0):
        raise InvalidInput("Enter the VAT first: there is none on this row to reclaim.")
    if gross <= 0:
        raise InvalidInput("The amount must be above zero.")
    if gross >= MOST:
        raise InvalidInput("That amount is too large: check it.")
    if "date" in sent and patch.date is not None and patch.date > dt.date.today() + AHEAD:
        raise InvalidInput("That date is more than a year ahead: check the year.")
    if vat is not None and vat < 0:
        raise InvalidInput("VAT can't be negative.")
    if vat is not None and vat >= gross:
        raise InvalidInput("VAT must be below the amount.")


def change_row(store: MongoStore, client_id: int, row_id: int, patch: RowPatch) -> Ledger:
    """Saves a person's change to a row once it makes sense, and returns the ledger worked out again."""
    client = store.get_client(client_id)
    require_active(client)
    rows = store.rows(client_id)
    row = next((r for r in rows if r.id == row_id), None)
    if row is None:
        raise NotFound("This row was not found.")
    if "apart_from" in patch.model_fields_set and (
            patch.apart_from is None or not set(patch.apart_from) <= {r.id for r in rows} - {row_id}):
        raise InvalidInput("Not the same can only name other rows of this client.")
    # A revert, or a change to the whole document, changes the other rows of its document too.
    whole = patch.revert or bool(patch.model_fields_set & WHOLE_DOCUMENT)
    changed = [r for r in rows if r.id == row_id or (whole and row.tx.document_ref
                                                    and r.tx.document_ref == row.tx.document_ref)]
    days = _days(store, client, changed) + [dt.date.fromisoformat(r.original["date"]) for r in changed
                                             if patch.revert and r.original and r.original.get("date")]
    ensure_open(client, days + ([patch.date] if patch.date else []))
    if patch.revert:
        store.patch_row(client_id, row_id, {}, revert=True)
    else:
        sent = patch.model_fields_set - {"revert"}
        _check_edit(patch, sent, row.tx, client)
        values = patch.model_dump(mode="json", include=sent)
        if "vat" in sent and "vat_confirmed" not in sent:
            # VAT a person enters is theirs to vouch for, so it is reclaimed; clearing it takes that back.
            values["vat_confirmed"] = patch.vat is not None and patch.vat > 0
        if "removed" in sent:
            values["excluded"] = False   # Put back: the row a person removed is in the books again
        store.patch_row(client_id, row_id, values)
    return _books().ledger_of(store, client_id, _year_of(store, client, row))


def add_manual(store: MongoStore, client_id: int, upload: ManualUpload) -> Ledger:
    client = store.get_client(client_id)
    require_active(client)
    if not upload.transactions:
        raise InvalidInput("Add at least one row.")
    # As in an edit: only an account of the chart this kind of business uses, so a row can always be booked.
    journals = [tx for tx in upload.transactions if tx.document_type == "journal"]
    for tx in journals:   # between any two accounts of the chart, on a day, for an amount
        if tx.account_code not in BY_CODE or tx.contra_account_code not in BY_CODE:
            raise InvalidInput("Choose the account to debit and the account to credit.")
        if tx.account_code == tx.contra_account_code:
            raise InvalidInput("A journal debits one account and credits another.")
        if tx.date is None or tx.gross <= 0:
            raise InvalidInput("A journal needs a date and an amount above zero.")
    if any(tx.gross >= MOST for tx in upload.transactions):
        raise InvalidInput("That amount is too large: check it.")
    if any(tx.date is not None and tx.date > dt.date.today() + AHEAD for tx in upload.transactions):
        raise InvalidInput("That date is more than a year ahead: check the year.")
    if any(tx.account_code not in _choosable_codes(client) for tx in upload.transactions
           if tx.document_type not in ("journal", "write_off")):   # a bad debt goes to 8100, offered for no row
        raise InvalidInput(f"This account can't be chosen for {client.name}.")
    if any(tx.bank_account is not None and tx.bank_account not in bank_codes(client) for tx in upload.transactions):
        raise InvalidInput(f"Choose one of {client.name}'s bank accounts.")
    if upload.year_start is not None and all(y.start != upload.year_start
                                             for y in _books().years_of(store, client_id, dt.date.today())):
        raise NotFound("That year was not found.")
    # A dated row goes by its date; an undated one waits in the year it was added to (today's, when none is said).
    ensure_open(client, [tx.date for tx in upload.transactions], upload.year_start or dt.date.today())
    # Only a decision of the agent excludes or supersedes a row, so a row sent by hand arrives without those marks.
    fresh = [tx.model_copy(update={"excluded": False, "removed": False, "superseded_by": None, "decision_ids": [],
                                   **({"vat": None, "vat_treatment": None, "bank_account": None}
                                      if tx.document_type == "journal" else {})})
             for tx in upload.transactions]
    added = store.add_upload(client_id, upload.name.strip() or "Manual entry", upload.kind, fresh,
                             year_start=upload.year_start)
    return _books().ledger_of(store, client_id, _year_of(store, client, upload_id=added))


def _ensure_upload_open(store: MongoStore, client: Client, upload_id: int) -> None:
    """Refuses a change to an upload with rows in a closed year."""
    ensure_open(client, _days(store, client, (r for r in store.rows(client.id) if r.upload_id == upload_id)))


def set_upload_bank(store: MongoStore, client_id: int, upload_id: int, bank_account: str) -> Ledger:
    """Puts an upload's statement on another of the client's bank accounts or cards, with its lines."""
    client = store.get_client(client_id)
    require_active(client)
    check_bank_account(client, bank_account)
    _ensure_upload_open(store, client, upload_id)
    lines = [r for r in store.rows(client_id) if r.upload_id == upload_id and r.tx.document_type == "statement"]
    was = next((r.tx.bank_account for r in lines if r.tx.bank_account), None)
    store.set_upload_bank(client_id, upload_id, bank_account)
    if bank_account in CARDS:
        # Read as another account's statement, a payment to the card looked like money from a customer. On the card
        # it is the card paid off: a transfer from the account the statement was on, or the one cards are paid from.
        codes = bank_codes(client)
        paid_from = was if was and was not in CARDS and was != bank_account else pays_cards(codes, bank_account)
        for r in lines:
            account = BY_CODE.get(r.tx.account_code)
            loose = r.tx.account_code == SUSPENSE or (account is not None and account.type == AccountType.INCOME)
            if (paid_from and r.original is None and r.tx.direction.value == "in" and loose
                    and card_payment(r.tx.counterparty, r.tx.description)):
                store.patch_row(client_id, r.id, {"account_code": paid_from})
    return _books().ledger_of(store, client_id, _year_of(store, client, upload_id=upload_id))


def remove_upload(store: MongoStore, client_id: int, upload_id: int) -> Ledger:
    client = store.get_client(client_id)
    require_active(client)
    _ensure_upload_open(store, client, upload_id)
    year = _year_of(store, client, upload_id=upload_id)
    store.delete_upload(client_id, upload_id)
    return _books().ledger_of(store, client_id, year)


def remove_row(store: MongoStore, client_id: int, row_id: int) -> Ledger:
    """Takes one row a person no longer wants out of the books, and returns its year's ledger worked out again
    without it. A row read from a file is set aside (removed): it stays listed, its document still accounts for it,
    and Put back books it again. A row typed in by hand is deleted."""
    client = store.get_client(client_id)
    require_active(client)
    row = next((r for r in store.rows(client_id) if r.id == row_id), None)
    if row is None:
        raise NotFound("This row was not found.")
    ensure_open(client, _days(store, client, [row]))
    by_hand = any(u["id"] == row.upload_id and u["kind"] == "manual" for u in store.uploads(client_id))
    if by_hand:
        store.delete_row(client_id, row_id)
    else:
        store.patch_row(client_id, row_id, {"excluded": True, "removed": True})
    return _books().ledger_of(store, client_id, _year_of(store, client, row))

