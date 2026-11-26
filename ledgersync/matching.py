"""Matches bank lines to the open invoices and claims they pay (design of 2026-10-06), sets aside documents read
twice, and pairs card payments with their receipts. Pure functions: the same rows give the same matches, whatever
order they arrived in."""
from __future__ import annotations

import datetime as dt
import re
from collections import Counter
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from itertools import combinations
from typing import Optional, Sequence

from .accounts import (BY_CODE, CARDS, CLEARING, CREDITORS, DEBTORS, DIRECTORS_LOANS, OWNER_CODES, PAYE, STAFF_EXPENSES, SUSPENSE,
                       AccountType)
from .checks import (MATCHING_ISSUES, PAYROLL_OWED, STATEMENT_ISSUES, REFRESHMENTS, account_on_claim, booked, is_fare, issue,
                     long_date, normalise, reclaims_vat, registered_on, vat_implied)
from .models import BusinessSettings, Direction, Issue, OpenItem, Settlement, Transaction
from .payees import processor
from .money import PENNY, ZERO, VatTreatment

WINDOW = dt.timedelta(days=31)   # a payment may be suggested for a document dated within 31 days of it
NEAR_PAYMENT = dt.timedelta(days=7)   # a payment of a document's exact amount this soon after it, to a like name
PART_WINDOW = dt.timedelta(days=120)  # a part payment, an overpayment or a set of documents: at most 120 days after
CONVERT_BEFORE, CONVERT_AFTER = dt.timedelta(days=7), dt.timedelta(days=14)   # a foreign bill's payment, around its date
CARD_DAYS = dt.timedelta(days=3)  # a card payment reaches the bank within a few days of its receipt
CHARGED_BEFORE = dt.timedelta(days=14)   # a card charged at the order: the invoice dated up to a fortnight later
CARD_WORKING_DAYS = 3             # counted in working days: a payment on a Thursday may reach the bank on the Monday


def card_days_apart(a: dt.date, b: dt.date) -> bool:
    """Whether a card payment and its bank line are close enough to be one payment: no more than CARD_WORKING_DAYS
    working days apart (a weekend in between doesn't count)."""
    earlier, later = sorted((a, b))
    if (later - earlier).days > 7:   # 3 working days never span more than a week: no need to count (it is called
        return False                 # for every card line against every receipt)
    working = sum(1 for k in range(1, (later - earlier).days + 1)
                  if (earlier + dt.timedelta(days=k)).weekday() < 5)
    return working <= CARD_WORKING_DAYS
TRANSFER_DAYS = dt.timedelta(days=3)  # money moved between two of the client's accounts arrives within a few days
YEAR = dt.timedelta(days=366)     # records further apart than this are different purchases, whatever else agrees
MAX_SET = 5                      # one payment clears at most five documents from one counterparty

# Words that say nothing about who a business is: legal forms and small linking words, bank-statement
# noise (payment types and their short codes), generic trade words, and place and national words.
# Legal forms other countries use: never part of who was paid ("Amazon Web Services EMEA SARL").
_FOREIGN_LEGAL = {"sarl", "gmbh", "inc", "llc", "corp", "bv", "nv", "sa", "sas", "srl", "ag", "ab", "aps", "oy",
                  "pty", "pte", "kg", "spa", "emea"}
_IGNORED = _FOREIGN_LEGAL | {"ltd", "limited", "plc", "llp", "co", "the", "and", "for", "of", "to", "at", "in", "on",
            "bank", "payment", "payments", "fin", "card", "dd", "so", "bacs", "fps", "ref", "direct", "debit",
            "credit", "faster", "standing", "order", "transfer", "tfr", "deb", "vis", "pos", "bgc", "chq", "atm",
            "int", "services", "solutions", "group", "online", "international", "holdings", "company", "trading",
            "uk", "gb", "london", "british", "national", "royal", "england", "scotland", "wales"}


_LEGAL = {"ltd", "limited", "plc", "llp", "co", "the"} | _FOREIGN_LEGAL   # what initials leave out


def _initials(name: Optional[str]) -> str:
    """NCP for National Car Parks Ltd: the first letters of a name of three words or more."""
    words = [w for w in re.findall(r"[a-z]+", (name or "").lower()) if w not in _LEGAL]
    return "".join(w[0] for w in words) if len(words) >= 3 else ""


def _initial_runs(name: Optional[str]) -> set[str]:
    """The initials of the name's first three words or more: TFL in "Transport for London, Train" as well as TFLT.
    Only from its first word: the initials of words in its middle say nothing (SAP in "Hotel stay at Premier Inn")."""
    words = [w for w in re.findall(r"[a-z]+", (name or "").lower()) if w not in _LEGAL]
    letters = "".join(w[0] for w in words)
    return {letters[:j] for j in range(3, len(letters) + 1)}


def _named_in(name: Optional[str], text: str) -> bool:
    """Every word of the name is a word of the text: EE in "Matt Barnes - EE, mobile phone bill". Too loose to pair
    on, as BT is in BT Sport, but enough to ask whether two records are one."""
    words = [w for w in re.findall(r"[a-z]+", (name or "").lower()) if w not in _LEGAL]
    return bool(words) and set(words) <= set(re.findall(r"[a-z]+", text.lower()))


def _words(name: Optional[str]) -> list[str]:
    return [w for w in re.findall(r"[a-z]+", (name or "").lower()) if w not in _IGNORED]


def _abbreviates(short: str, long: str) -> bool:
    """'mgmt' abbreviates 'management': three letters or more, the same first letter, the rest in order, and either
    the start of the word ('pri', 'print') or ending as it ends. So 'sarl' does not abbreviate 'starling'."""
    if not 3 <= len(short) < len(long) or short[0] != long[0]:
        return False
    if not long.startswith(short) and short[-1] != long[-1]:
        return False
    letters = iter(long)
    return all(ch in letters for ch in short)


def _within(short: list[str], long: list[str]) -> bool:
    """The whole of one name, its words in order, inside the other: "R+R PR" in "R+R PR LTD CL AC"."""
    return any(long[i:i + len(short)] == short for i in range(len(long) - len(short) + 1))


def names_match(a: Optional[str], b: Optional[str]) -> bool:
    """True, after legal forms, bank words, generic trade words and numbers are set aside, when two names are
    the same however short their words ("HML PM Ltd"), when the whole of one, three letters or more, is in the
    other, when they share a word of four or more letters, when a word of one abbreviates a word of the other, or
    when a word of one is the initials of the other or of three or more words in a row of it (NCP, National Car
    Parks; TFL, Transport for London, Train)."""
    wa, wb = _words(a), _words(b)
    runs_a, runs_b = _initial_runs(a), _initial_runs(b)
    if any(w in runs_b for w in wa if len(w) >= 3) or any(w in runs_a for w in wb if len(w) >= 3):
        return True
    if wa and wa == wb:
        return True
    short, long = sorted((wa, wb), key=len)
    if short and sum(map(len, short)) >= 3 and _within(short, long):
        return True
    return (any(w in wb for w in wa if len(w) >= 4)
            or any(_abbreviates(x, y) or _abbreviates(y, x) for x in wa for y in wb))


# What a bank line's reference can add to a payee's name about why it was paid: never part of who was paid.
_REFERENCE = {"expenses", "expense", "claim", "claims", "reimbursement", "refund"}
# Trade words many businesses share: part of a name, but two names sharing only these may be anyone.
_GENERIC = {"print", "printing", "printers", "consulting", "consultancy", "consultants", "design", "designs",
            "media", "marketing", "management", "associates", "partners", "enterprises", "systems", "supplies",
            "office", "studio", "digital", "technology", "technologies", "cabs", "taxis", "cars", "hotel", "hotels",
            "cafe", "restaurant", "shop", "store", "stores", "city", "solicitors", "accountants", "builders"}


def _same_word(x: str, y: str) -> bool:
    """One word, as two names write it: the same, or one abbreviates the other ('mgmt', 'management')."""
    return x == y or _abbreviates(x, y) or _abbreviates(y, x)


def _inside(short: list[str], long: list[str]) -> bool:
    """Every word of the shorter name is a word of the longer, or abbreviates one, or is the initial of one ('M' of
    'Matt'), and at least one word that isn't a trade word many share is found whole or abbreviated."""
    distinctive = False
    for word in short:
        found = [w for w in long if _same_word(word, w)]
        if found:
            distinctive = distinctive or word not in _GENERIC
        elif not (len(word) == 1 and any(w[0] == word for w in long if w not in short)):
            return False   # an initial stands for a word the short name doesn't spell out: M for Matt, not for Marlow
    return distinctive


def _share_a_name(a: Optional[str], b: Optional[str]) -> bool:
    """Whether two names share a word of four letters or more that is a name, not a trade word many businesses
    share: Google in "Google Workspace Ireland" and "Google Cloud EMEA Limited", but not Print in "Acme Print" and
    "Brightline Print"."""
    return any(len(w) >= 4 and w not in _GENERIC for w in set(_words(a)) & set(_words(b)))


def same_payee(a: Optional[str], b: Optional[str]) -> bool:
    """Whether two names are surely the same payee, strictly enough to pay a document automatically. After legal
    forms, bank words, place and national words and the payment's reference are set aside: the names are the
    same ("HML PM Ltd"); or every word of the shorter is in the longer, whole, abbreviated or as an initial, with at
    least one that isn't a trade word many businesses share ("BRIGHTLINE PRI" and "Brightline Print Ltd", "M
    BARNES" and "Matt Barnes", but not "Brightline Print" and "Acme Print Ltd", nor "Leeds Print" and "Leeds City
    Cabs"); or one name is the other's initials (NCP, National Car Parks). names_match, which one shared word
    satisfies, only suggests a document for a person to Link."""
    wa, wb = ([w for w in _words(name) if w not in _REFERENCE] for name in (a, b))
    if not wa or not wb:
        return False
    if wa == wb:
        return True
    if any(len(i) >= 3 and words == [i] for words, i in ((wa, _initials(b)), (wb, _initials(a)))):
        return True
    short, long = sorted((wa, wb), key=len)
    if sum(map(len, short)) < 3:   # "BT" in "BT Sport": too short to tell
        return False
    return _inside(short, long) or (len(short) == len(long) and _inside(long, short))


def same_supplier(a: Optional[str], b: Optional[str]) -> bool:
    """Whether two names are one supplier for comparing how its bills are coded (coding.py): surely the same payee,
    and neither name has a word more than the other. "Vodafone Ltd" and "VODAFONE UK DD" are one; "Vodafone" and
    "Vodafone Insurance Services", or "Amazon" and "Amazon Web Services", are kept apart, since a group's businesses
    sell different things that go to different accounts."""
    wa, wb = ([w for w in _words(name) if w not in _REFERENCE] for name in (a, b))
    return len(wa) == len(wb) and same_payee(a, b)


@dataclass
class _Document:
    """An open invoice, claim or included document: the rows that share its document_ref."""
    ref: str
    kind: str                     # its document type
    direction: str
    account: Optional[str]        # where what is owed is held: 1100, 2100 or 2110
    counterparty: Optional[str]
    description: str
    rows: list[int] = field(default_factory=list)
    total: Decimal = ZERO
    date: Optional[dt.date] = None
    open: Decimal = ZERO
    paid_by: list[Settlement] = field(default_factory=list)
    written_off: Optional[dt.date] = None   # the day a bad debt write-off of it takes effect: no payment after it

    def settlement(self, amount: Decimal) -> Settlement:
        return Settlement(ref=self.ref, amount=amount, date=self.date, description=self.description, kind=self.kind)

    def label(self) -> str:
        when = f", {self.date:%d %b %Y}" if self.date else ""
        return f"{self.description} ({_gbp(self.open)}{when})"


@dataclass
class DocumentStatus:
    """What is still open on a document after every payment matched to it, and the payments."""
    open: Decimal
    paid_by: list[Settlement]


def _brought_forward(items: Sequence[OpenItem]) -> dict[str, _Document]:
    """The invoices unpaid when the first year starts, as open documents with no rows: a customer's on Debtors, a
    supplier's on Creditors, each dated by its item (books dates them the day before the first year starts)."""
    return {f"ob-{item.id}": _Document(ref=f"ob-{item.id}", kind="invoice", direction=item.direction.value,
                                       account=DEBTORS if item.direction == Direction.IN else CREDITORS,
                                       counterparty=item.counterparty,
                                       description=f"Brought forward: {item.number or item.counterparty}",
                                       total=item.amount, date=item.date, open=item.amount)
            for item in items}


def _only_each_other(docs: list[_Document], lines: list[int], agree) -> list[tuple[_Document, int]]:
    """The documents and lines that agree with each other and with nothing else in the two lists."""
    found = [(d, n) for d in docs for n in lines if agree(d, n)]
    by_doc, by_line = Counter(d.ref for d, _ in found), Counter(n for _, n in found)
    return [(d, n) for d, n in found if by_doc[d.ref] == 1 and by_line[n] == 1]


def _gbp(amount: Decimal) -> str:
    return f"£{amount:,.2f}"


def match(rows: list[Transaction], settings: BusinessSettings, read: Optional[list[Optional[Decimal]]] = None,
          apart: Optional[list[set[int]]] = None, open_items: Sequence[OpenItem] = (),
          name_days: Optional[list[Optional[dt.date]]] = None,
          upload_ids: Optional[list[Optional[int]]] = None) -> list[Transaction]:
    """The rows as match_documents matches them."""
    return match_documents(rows, settings, read, apart, open_items, name_days=name_days, upload_ids=upload_ids)[0]


def match_documents(rows: list[Transaction], settings: BusinessSettings,
                    read: Optional[list[Optional[Decimal]]] = None, apart: Optional[list[set[int]]] = None,
                    open_items: Sequence[OpenItem] = (), left_out: Optional[dict[str, dict[str, Decimal]]] = None,
                    name_days: Optional[list[Optional[dt.date]]] = None,
                    upload_ids: Optional[list[Optional[int]]] = None
                    ) -> tuple[list[Transaction], dict[str, DocumentStatus]]:
    """Which documents each bank line pays and what is still owed on each document, for transactions
    checks.normalise has already prepared. Lines a person linked go first; then lines that pay exactly what
    one document owes, whatever their date, so a bigger payment to the same person is never taken as an
    overpayment of a document another line pays exactly; then the rest, oldest first. So the result does not
    depend on the order the rows arrived in. With a client's saved rows come what a person decided: read, each row's
    amount as it was read before a person changed it (None if unchanged), and apart, for each row, the rows a person
    said are not the same as it, which are never paired with it or asked about. open_items: the invoices unpaid when
    the client's first year started, which a bank line pays as it pays an invoice uploaded. Also each document's
    status, by its ref, brought-forward ones ("ob-{id}") among them. A row a decision left out of the books (excluded,
    or replaced by a split) is matched as if it were not there; left_out, for each document, is what its excluded
    rows amounted to in each direction, so the total printed on the document is not said to be short of them.
    name_days: for each row, the day its upload's file name holds (an expense app's export names the day), or None.
    upload_ids: for each row, the upload it came from, or None: a claim line can be booked from several receipts of one
    upload (_with_claims); without them it is booked from one receipt only."""
    read = read or [None] * len(rows)
    apart = apart or [set() for _ in rows]
    name_days = name_days or [None] * len(rows)
    if any(tx.excluded or tx.superseded_by for tx in rows):
        return _without_left_out(rows, settings, read, apart, open_items, name_days, upload_ids)
    rows = _checked_totals(_with_claims(_without_copies([_cleared(tx) for tx in rows]), settings, apart, name_days,
                                        upload_ids),
                           read, left_out or {})
    rows = _with_till_takings(rows, settings)
    rows = _in_pounds(rows, settings)
    rows = _payroll_summaries(rows, settings, upload_ids)
    rows = _hmrc_references(rows, settings)
    documents = {**_brought_forward(open_items), **_documents(rows)}
    changes: list[dict] = [{} for _ in rows]
    _credit_notes(rows, documents, changes)
    for tx in rows:   # a write-off takes what is still owed once the payments dated before it are matched
        if tx.document_type == "write_off" and booked(tx) and tx.writes_off in documents and tx.date:
            documents[tx.writes_off].written_off = tx.date
    # Both sides of a transfer between the client's own accounts are the transfer's, never a payment of a document.
    transfers = _pair_transfers(rows, settings, changes, apart)
    lines = sorted((n for n, tx in enumerate(rows) if tx.document_type in _PAYMENT_LINES and n not in transfers
                    and booked_line(tx)),
                   key=lambda n: (rows[n].link is None, rows[n].date or dt.date.max, n))
    automatic: dict[int, list[Issue]] = {}   # the lines left to match automatically, with their issues so far
    for n in lines:
        left = _apply_link(n, rows[n], documents, changes[n])
        if left is not None:
            automatic[n] = left
    paid_exactly = True
    while paid_exactly:      # paying one document can leave another line a single exact match
        paid_exactly = False
        for n in list(automatic):
            exact = _exact(rows[n], [d for d in documents.values() if _could_pay(rows[n], d)])
            if len(exact) == 1:
                _pay(n, rows[n], exact, changes[n], automatic[n])
                _note(changes[n], rows[n], automatic.pop(n))
                paid_exactly = True
    # A card payment that a receipt records is that receipt's, not a part payment, a set, an overpayment or a payment
    # to an open account: pair those lines first. Lines that exact amounts or a person's choice decide stay as they are.
    card_lines = [n for n in automatic if rows[n].document_type == "statement"
                  and _outcome(rows[n], documents, settings.owner_names)[0] in ("pay", "none", "open_document")]
    _pair_receipts(rows, changes, card_lines, apart, first_pass_only=True)
    for n in [n for n in automatic if changes[n].get("recorded_by")]:
        _note(changes[n], rows[n], automatic.pop(n))
    for n, found in automatic.items():
        _settle(n, rows[n], documents, changes[n], found, settings.owner_names, settings)
    statement_lines = [n for n in lines if rows[n].document_type == "statement"]
    _pair_receipts(rows, changes, statement_lines, apart)
    _paid_again(rows, changes, statement_lines, apart)
    _off_statement(rows, changes, settings)
    _refunds(rows, changes, documents, statement_lines)
    _reversals(rows, changes, statement_lines)
    _recoveries(rows, settings, _write_offs(rows, documents, changes), documents, changes)
    _settled_since(changes, documents)
    for doc in documents.values():
        for n in doc.rows:
            changes[n].update(owed=doc.open, document_direction=Direction(doc.direction), paid_by=list(doc.paid_by))
    matched = [tx.model_copy(update=change) if change else tx for tx, change in zip(rows, changes)]
    matched = [_with_addressee(_with_payout_report(_with_sale_without_vat(tx, settings)), settings)
               for tx in matched]
    statuses = {ref: DocumentStatus(open=doc.open, paid_by=list(doc.paid_by)) for ref, doc in documents.items()}
    return _without_payroll(matched), statuses


def _without_left_out(rows: list[Transaction], settings: BusinessSettings, read: list[Optional[Decimal]],
                      apart: list[set[int]], open_items: Sequence[OpenItem],
                      name_days: list[Optional[dt.date]], upload_ids: Optional[list[Optional[int]]] = None
                      ) -> tuple[list[Transaction], dict[str, DocumentStatus]]:
    """match_documents on the rows a decision didn't leave out, put back in place among the left-out ones, which
    keep no outputs of a match. The places that matching's issues name are mapped back to places in all the rows."""
    kept = [n for n, tx in enumerate(rows) if not (tx.excluded or tx.superseded_by)]
    place = {n: k for k, n in enumerate(kept)}
    # Only excluded rows: a split's parts keep the document_ref of the row they replace and add up to it, so the
    # replaced row's amount is already among the kept ones.
    left_out: dict[str, dict[str, Decimal]] = {}
    for tx in rows:
        if tx.excluded and not tx.superseded_by:
            by_direction = left_out.setdefault(tx.document_ref, {})
            by_direction[tx.direction.value] = by_direction.get(tx.direction.value, ZERO) + tx.gross
    matched, statuses = match_documents([rows[n] for n in kept], settings, [read[n] for n in kept],
                                        [{place[m] for m in apart[n] if m in place} for n in kept], open_items,
                                        left_out, name_days=[name_days[n] for n in kept],
                                        upload_ids=[upload_ids[n] for n in kept] if upload_ids else None)
    result = [_cleared(tx) for tx in rows]
    for n, tx in zip(kept, matched):
        result[n] = tx.model_copy(update={"issues": [
            i.model_copy(update={"related": [kept[p] for p in i.related]}) if i.code in MATCHING_ISSUES else i
            for i in tx.issues]})
    return result, statuses


_TAKINGS = re.compile(r"\btakings\b|\bz[- ]?read", re.IGNORECASE)
_CASH_BANKED = re.compile(r"\bcash (paid in|banked|deposit\w*|lodg\w*)|\bpaid in at (a |the )?branch|\bcounter credit|"
                          r"\bcash paid\b.*\bbranch", re.IGNORECASE)
TILL = "1230"                      # where takings sit between the till and the bank
TILL_WINDOW = dt.timedelta(days=31)


def _with_till_takings(rows: list[Transaction], settings: BusinessSettings) -> list[Transaction]:
    """For a business that sends its till summaries (Z-readings): those are its sales, cash and card together, and
    the money is in the till, not yet in the bank. So the takings are booked into the till account; and what then
    moves that money is not a second sale. A card processor's report of the sales it collected, and cash paid in at
    the bank, within a month of a till summary, take the money out of the till instead of adding to Sales. A line of
    the summary that only notes cash banked is that movement too. Without a till summary nothing changes."""
    def income(tx: Transaction) -> bool:
        account = BY_CODE.get(tx.account_code)
        return account is not None and account.type == AccountType.INCOME

    def words(tx: Transaction) -> str:
        return f"{tx.description} {tx.counterparty or ''}"

    takings = [tx for tx in rows if tx.document_type == "receipt" and tx.direction == Direction.IN and tx.date
               and booked(tx) and income(tx) and _TAKINGS.search(words(tx))]
    if not takings:
        return rows

    def near(tx: Transaction) -> bool:
        return tx.date is not None and any(abs(tx.date - t.date) <= TILL_WINDOW for t in takings)

    result = []
    for tx in rows:
        money_in = tx.direction == Direction.IN and booked(tx)
        if any(tx is t for t in takings):
            if tx.bank_account is None:   # unless a person said where the money went
                tx = tx.model_copy(update={"contra_account_code": TILL, "issues": tx.issues + [issue(
                    "till_takings", "Till takings: booked into the till (Petty Cash), not the bank. The card payouts "
                                    "and the cash banked then move the money to the bank.", "info")]})
        elif tx.vat_treatment is not None:
            pass   # a person chose how VAT applies to it: a sale of its own, outside the till summaries
        elif money_in and tx.document_type == "agent_statement" and income(tx) and near(tx):
            tx = tx.model_copy(update={"account_code": TILL, "issues": tx.issues + [issue(
                "till_takings", "The till summaries already book these takings as sales: this is the card money "
                                "leaving the till for the processor, not a second sale. If these sales are not in "
                                "the till summaries, edit the row and choose its VAT treatment.", "info")]})
        elif (money_in and tx.document_type == "statement" and (income(tx) or tx.account_code == SUSPENSE)
              and near(tx) and _CASH_BANKED.search(words(tx))):
            tx = tx.model_copy(update={"account_code": TILL, "issues": [
                *(i for i in tx.issues if i.code != "account_unclear"),
                issue("till_takings", "Cash banked from the till: the till summaries already book it as sales, so "
                                      "this moves it from the till to the bank. If it is another sale, edit the row "
                                      "and choose its VAT treatment.", "info")]})
        elif (money_in and tx.document_type == "receipt" and tx.account_code in settings.bank_accounts
              and tx.account_code != TILL and near(tx) and _CASH_BANKED.search(words(tx))):
            # The summary's own note of the cash banked: the same movement, which its bank line pairs with.
            tx = tx.model_copy(update={"account_code": TILL, "issues": [
                *(i for i in tx.issues if i.code != "same_account"),
                issue("till_takings", "Cash banked from the till, as the till summary notes it.", "info")]})
        result.append(tx)
    return result


def _with_sale_without_vat(tx: Transaction, settings: BusinessSettings) -> Transaction:
    """A VAT-registered client's bank line left unpaired, booked to an income account usually charged VAT, with no VAT
    shown and no rate a person chose: the sale may need its invoice, or a rate."""
    account = BY_CODE.get(tx.account_code)
    if (registered_on(settings, tx.date) and tx.document_type == "statement" and tx.direction == Direction.IN
            and account is not None and account.type == AccountType.INCOME and account.vat == VatTreatment.STANDARD
            and tx.vat is None and tx.vat_treatment is None and not tx.pays and tx.recorded_by is None
            and booked(tx) and booked_line(tx)):
        return tx.model_copy(update={"issues": tx.issues + [issue(
            "sale_without_vat", "A sale with no VAT shown: book it from its invoice, or choose its VAT rate.")]})
    return tx


def _with_addressee(tx: Transaction, settings: BusinessSettings) -> Transaction:
    """A company's purchase whose receipt or invoice is addressed to someone else (the director at home): it may be
    their own spending, so a person says. Not for a sole trader or a partnership, whose papers name the owner, nor a
    credit note the company gives a customer (money out on a sales account), which is addressed to the customer."""
    name, to = settings.business_name, tx.addressed_to
    if (settings.business_type != "limited_company" or not name or not to or tx.direction != Direction.OUT
            or tx.document_type not in ("receipt", "invoice") or tx.account_code in DIRECTORS_LOANS
            or (BY_CODE.get(tx.account_code) is not None and BY_CODE[tx.account_code].type == AccountType.INCOME)
            or "addressed_to" in tx.accepted or not booked(tx)
            or same_payee(to, name) or _named_in(name, to)):
        return tx
    return tx.model_copy(update={"issues": tx.issues + [issue(
        "addressed_to", f"Addressed to {to}, not {name}. If it is their own spending, recode it to Director's Loan "
                        "Account; if the business bought it, say it is fine.")]})


def _write_offs(rows: list[Transaction], documents: dict[str, _Document],
                changes: list[dict]) -> list[tuple[int, Transaction]]:
    """Each bad debt written off: its write_off row settles the invoice it writes off (writes_off), so the invoice is
    no longer owed. The write-offs found, by place."""
    found: list[tuple[int, Transaction]] = []
    for n, tx in enumerate(rows):
        doc = documents.get(tx.writes_off or "")
        if tx.document_type != "write_off" or doc is None or not booked(tx):
            continue
        take = min(tx.gross, doc.open)
        doc.open -= take
        doc.paid_by.append(Settlement(ref=tx.document_ref or f"row-{n}", amount=take, date=tx.date,
                                      description=tx.description, kind="write_off"))
        changes[n]["pays"] = [doc.settlement(take)]
        if tx.gross > take:   # paid in part before the write-off: it writes off more than was left
            changes[n]["issues"] = changes[n].get("issues", tx.issues) + [issue(
                "write_off_more_than_owed", f"Writes off {_gbp(tx.gross)}, but only {_gbp(take)} was still owed on "
                                            f"{doc.description} on {long_date(tx.date)}: remove it and answer again "
                                            "to write off what is owed.")]
        found.append((n, tx))
    return found


def _recoveries(rows: list[Transaction], settings: BusinessSettings, written_off: list[tuple[int, Transaction]],
                documents: dict[str, _Document], changes: list[dict]) -> None:
    """After the payments are matched: each bank line in from a customer whose debt was written off, dated after the
    write-off, that pays nothing else, while none of that customer's documents is open, and for no more than is still
    unrecovered, is a recovery (recovers): booked against Bad Debts, with the share of it the write-off claimed back
    as VAT paid over again, not as a sale. The customer is surely the same, or their name is in the line's (an
    administrator pays in the company's name: "Lowther Interiors in Admin"); a name only sharing a word is not."""
    # A customer's write-offs are pooled: a recovery comes out of what is unrecovered on any of them, oldest first.
    pools: list[list[tuple[int, Transaction]]] = []
    for w, off in written_off:
        pool = next((p for p in pools if off.counterparty and p[0][1].counterparty
                     and same_payee(off.counterparty, p[0][1].counterparty)), None)
        if pool is None:
            pools.append([(w, off)])
        else:
            pool.append((w, off))
    for pool in pools:
        pool.sort(key=lambda p: (p[1].date or dt.date.max, p[0]))
        first = pool[0][1]
        left = {w: off.gross for w, off in pool}
        gross = sum((off.gross for _, off in pool), ZERO)
        vat = sum((off.vat_posted or ZERO for _, off in pool), ZERO)
        for n, tx in sorted(enumerate(rows), key=lambda p: (p[1].date or dt.date.max, p[0])):
            change = changes[n]
            if (tx.document_type != "statement" or tx.direction != Direction.IN or tx.link or tx.account_chosen
                    or not booked_line(tx) or change.get("pays") or change.get("recorded_by") or change.get("recovers")
                    or change.get("paid_against") or tx.date is None or first.date is None or tx.date <= first.date
                    or tx.gross > sum(left.values(), ZERO)
                    or not (tx.counterparty and first.counterparty and (same_payee(tx.counterparty, first.counterparty)
                                                                         or _named_in(first.counterparty, tx.counterparty)))
                    or any(d.open > ZERO and d.direction == "in" and d.counterparty
                           and same_payee(first.counterparty, d.counterparty) for d in documents.values())):
                continue
            w, off = next((w, off) for w, off in pool if left[w] > ZERO)
            share = (tx.gross * vat / gross).quantize(PENNY, rounding=ROUND_HALF_UP)
            ref = off.document_ref or f"row-{w}"
            checked = normalise(tx.model_copy(update={"account_code": "8100", "vat": share, "recovers": ref}), settings)
            change.update(account_code="8100", vat=share, vat_posted=checked.vat_posted, net=checked.net, recovers=ref,
                          candidates=[], issues=[i for i in checked.issues if i.code not in MATCHING_ISSUES] + [issue(
                              "bad_debt_recovered", f"Recovers {_gbp(tx.gross)} of the bad debt written off on "
                                                    f"{long_date(off.date)}: booked against Bad Debts, its "
                                                    f"£{share:,.2f} VAT paid over again, not as a sale.", "info")])
            taken = tx.gross
            for k, _ in pool:   # what it recovers, from the oldest write-off on
                part = min(left[k], taken)
                left[k] -= part
                taken -= part


_USUAL_WAY = {DEBTORS: "in", CREDITORS: "out"}   # an invoice to a customer, a bill from a supplier


def _credit_notes(rows: list[Transaction], documents: dict[str, _Document], changes: list[dict]) -> None:
    """Each credit note taken off the invoice it credits, before any payment is matched, so a payment of what is left
    clears that invoice. A credit note is an invoice going the other way on Debtors or Creditors. Its invoice is an
    open one to or from the same payee, dated on or before it, with at least its amount open: the one whose number it
    names, else whose month it names, else the only one. Otherwise it stays open, for a person to link or refund."""
    for credit in sorted((d for d in documents.values() if d.kind == "invoice" and d.account in _USUAL_WAY
                          and d.direction != _USUAL_WAY[d.account] and d.open > ZERO and d.rows),
                         key=lambda d: (d.date or dt.date.max, d.ref)):
        text = " ".join(f"{rows[n].description} {rows[n].document_number or ''}" for n in credit.rows)
        owed = [d for d in documents.values() if d.kind == "invoice" and d.account == credit.account
                and d.direction == _USUAL_WAY[d.account] and d.open >= credit.open and d.counterparty
                and credit.counterparty and same_payee(credit.counterparty, d.counterparty)
                and (d.date is None or credit.date is None or d.date <= credit.date)]

        def number(d: _Document) -> Optional[str]:
            return next((rows[n].document_number for n in d.rows if rows[n].document_number), None)

        for pick in (lambda d: bool(number(d)) and re.search(rf"\b{re.escape(number(d))}\b", text, re.I),
                     lambda d: _same_month(text, d.description), lambda d: True):
            chosen = [d for d in owed if pick(d)]
            if chosen:
                break
        if len(chosen) != 1:
            continue
        invoice, amount = chosen[0], credit.open
        invoice.open -= amount
        credit.open = ZERO
        invoice.paid_by.append(Settlement(ref=credit.ref, amount=amount, date=credit.date,
                                          description=credit.description, kind=credit.kind))
        credit.paid_by.append(Settlement(ref=invoice.ref, amount=amount, date=invoice.date,
                                         description=invoice.description, kind=invoice.kind))
        n = credit.rows[0]
        changes[n]["issues"] = changes[n].get("issues", rows[n].issues) + [issue(
            "credited", f"Takes {_gbp(amount)} off {invoice.description}"
                        f"{f', {invoice.date:%d %b %Y}' if invoice.date else ''}: {_gbp(invoice.open)} is left to "
                        "pay on it.", "info")]


def _refunds(rows: list[Transaction], changes: list[dict], documents: dict[str, _Document], lines: list[int]) -> None:
    """A bank line going the other way from a document overpaid by exactly its amount, to or from the same person, is
    the overpayment refunded: it posts against the account holding what is owed, not as a sale or a cost, and nothing
    is owed either way."""
    for n in lines:
        line, change = rows[n], changes[n]
        if (change.get("pays") or change.get("paid_against") or change.get("recorded_by") or line.link is not None
                or not line.counterparty or line.date is None):
            continue
        over = [d for d in documents.values() if d.open == -line.gross and d.direction != line.direction.value
                and d.date is not None and d.date <= line.date and same_payee(line.counterparty, d.counterparty)]
        if len(over) != 1:
            continue
        doc = over[0]
        doc.open = ZERO
        doc.paid_by.append(Settlement(ref=line.document_ref or f"row-{n}", amount=-line.gross, date=line.date,
                                      description=line.description, kind=line.document_type))
        kept = [i for i in change.get("issues", line.issues) if i.code != "unusual_direction"]
        change.update(paid_against=doc.account, vat_posted=ZERO, net=line.gross, candidates=[], issues=kept + [issue(
            "refund_of_overpayment", f"Refunds the {_gbp(line.gross)} overpaid on {doc.description}: taken off "
                                     f"{BY_CODE[doc.account].name}, not booked as a sale or a cost.", "info")])


RETURNED = dt.timedelta(days=14)   # a payment returned unpaid comes back within days


def _reversals(rows: list[Transaction], changes: list[dict], lines: list[int]) -> None:
    """A bank line in, on a cost account, for exactly what an earlier line to the same payee paid out of the same
    account in the two weeks before (a direct debit returned unpaid, a payment refunded whole): the two cancel, so
    the payment needs no receipt and the cost is nil. Neither line pays or is recorded by a document."""
    def free(n: int) -> bool:
        change = changes[n]
        return not (change.get("pays") or change.get("paid_against") or change.get("recorded_by")
                    or rows[n].link is not None or rows[n].date is None)

    used: set[int] = set()
    for n in lines:
        back = rows[n]
        account = BY_CODE.get(back.account_code)
        if (back.document_type != "statement" or back.direction != Direction.IN or account is None
                or account.type != AccountType.EXPENSE or not free(n)):
            continue
        paid = [k for k in lines if k not in used and free(k) and rows[k].document_type == "statement"
                and rows[k].direction == Direction.OUT and rows[k].gross == back.gross
                and rows[k].account_code == back.account_code
                and rows[k].contra_account_code == back.contra_account_code
                and back.date - RETURNED <= rows[k].date <= back.date
                and names_match(rows[k].counterparty, back.counterparty)]
        if not paid:
            continue
        k = max(paid, key=lambda k: (rows[k].date, k))
        used.add(k)
        changes[k]["issues"] = changes[k].get("issues", rows[k].issues) + [issue(
            "reversed", f"Came back on {long_date(back.date)}: the two lines cancel, so no receipt or invoice is "
                        "needed for this one.", "info", related=[n])]
        changes[n]["issues"] = [i for i in changes[n].get("issues", back.issues) if i.code != "unusual_direction"] + [
            issue("reversed", f"Reverses the payment of {long_date(rows[k].date)}: the two lines cancel.", "info",
                  related=[k])]


def _settled_since(changes: list[dict], documents: dict[str, _Document]) -> None:
    """A part payment whose document has since been paid in full, or an overpayment since refunded, is no longer a
    warning: the line says what it was, as a note."""
    for change in changes:
        found, pays = change.get("issues"), change.get("pays")
        if not found or not pays or any(p.ref not in documents or documents[p.ref].open != ZERO for p in pays):
            continue
        change["issues"] = [
            issue("part_payment", i.message.split(";")[0] + "; the rest has been paid since.", "info")
            if i.code == "part_payment" else
            issue("overpayment", i.message.split(" over")[0] + " over; it has been refunded since.", "info")
            if i.code == "overpayment" else i for i in found]


# HMRC's own payment references, which say what tax a payment is (GOV.UK's bank details pages): corporation tax a
# 17-character reference (the 10-digit UTR, A, five digits, A), PAYE the 13-character accounts office reference.
_HMRC_REFERENCES = ((re.compile(r"\b\d{10}A\d{5}A\b", re.I), "2320", "a corporation tax"),
                    (re.compile(r"\b\d{3}P[A-Z]\d{7}[0-9X]\b", re.I), PAYE, "a PAYE accounts office"))


def _hmrc_references(rows: list[Transaction], settings: BusinessSettings) -> list[Transaction]:
    """The rows, each bank line to or from HMRC that quotes one of its payment references on the account that reference
    is for, whatever the line was read as, and checked again. A line a person coded or linked stays as it is."""
    out = list(rows)
    for n, tx in enumerate(rows):
        text = f"{tx.description or ''} {tx.counterparty or ''}"
        if tx.document_type != "statement" or tx.account_chosen or tx.link or "hmrc" not in text.lower():
            continue
        for pattern, code, what in _HMRC_REFERENCES:
            found = pattern.search(text)
            if found and tx.account_code != code and code in BY_CODE:
                was = BY_CODE.get(tx.account_code)
                checked = normalise(tx.model_copy(update={"account_code": code}), settings)
                out[n] = checked.model_copy(update={"issues": checked.issues + [issue(
                    "hmrc_reference", f"Recoded from {was.name if was else tx.account_code} to {BY_CODE[code].name}: "
                                      f"{found.group(0)} is {what} payment reference.", "info")]})
                break
            if found:
                break
    return out


EMPLOYERS_NI = "7006"
_ALLOWANCE = re.compile(r"employment allowance[^£\d]{0,30}£?\s*(\d[\d,]*\.\d{2})", re.I)


def _payroll_summaries(rows: list[Transaction], settings: BusinessSettings,
                       upload_ids: Optional[list[Optional[int]]]) -> list[Transaction]:
    """The rows, those of an upload whose payroll rows are all owed to HMRC (paye_ni, and no net pay or pension) taken
    as what they are: a summary of what payroll owes HMRC (a P32), which the payroll report books and the bank payment
    clears. Such a file is held on PAYE and NI, where it is not booked (checks.payroll_summary): read onto a wages
    account it would book the wages again. All but one thing on it: the Employment Allowance it claims, which only
    the P32 shows, comes off employer's NI and what is owed to HMRC. A one-row P32 is booked as that allowance when
    it prints it, or when what it says is due is the payroll report's tax and NI for the same pay date less an amount
    no more than that report's employer's NI; a P32 read as several rows, from the row that is the allowance. Rows a
    person changed or ticked Include stay as they are."""
    if not upload_ids:
        return rows
    by_upload: dict[int, list[int]] = {}
    for n, tx in enumerate(rows):
        if tx.document_type == "payroll" and upload_ids[n] is not None:
            by_upload.setdefault(upload_ids[n], []).append(n)
    def to_hmrc(tx: Transaction) -> bool:   # owed to HMRC: said so, or on PAYE and NI with nothing said
        return tx.owed_to == "paye_ni" or (tx.owed_to is None and tx.account_code == PAYE)

    summaries = {u: members for u, members in by_upload.items() if all(to_hmrc(rows[n]) for n in members)}
    reports = [n for u, members in by_upload.items() if u not in summaries for n in members]
    out = list(rows)
    for members in summaries.values():
        for n in members:
            tx = rows[n]
            if tx.account_chosen or tx.include:
                continue
            allowance = (_allowance(tx, [rows[k] for k in reports if rows[k].date == tx.date]) if len(members) == 1
                         else _allowance_line(tx))
            if allowance is not None:
                amount, how = allowance
                checked = normalise(tx.model_copy(update={"account_code": EMPLOYERS_NI, "direction": Direction.IN,
                                                          "gross": amount, "vat": None}), settings)
                out[n] = checked.model_copy(update={"issues": checked.issues + [issue(
                    "employment_allowance", f"Employment Allowance claimed: {_gbp(amount)} off employer's National "
                                            f"Insurance and what is owed to HMRC, as the P32 shows ({how}). The rest of "
                                            "the P32 is what the payroll report books.", "info")]})
            elif tx.account_code != PAYE:
                out[n] = normalise(tx.model_copy(update={"account_code": PAYE}), settings)
    return out


def _allowance_line(row: Transaction) -> Optional[tuple[Decimal, str]]:
    """A P32 read as several rows: the Employment Allowance when one of them is it ("Employment Allowance claimed")."""
    printed = _ALLOWANCE.search(row.description or "")
    if printed:
        amount = Decimal(printed.group(1).replace(",", ""))
        return (amount, "it prints it") if amount > ZERO else None
    if re.search(r"\bemployment allowance\b", row.description or "", re.I) and row.gross > ZERO:
        return row.gross, "a line of its own"
    return None


def _allowance(p32: Transaction, report: list[Transaction]) -> Optional[tuple[Decimal, str]]:
    """The Employment Allowance a P32 claims, and how it is known; None when it claims none or it can't be told."""
    printed = _ALLOWANCE.search(p32.description or "")
    if printed:
        amount = Decimal(printed.group(1).replace(",", ""))
        return (amount, "it prints it") if amount > ZERO else None
    owed = sum((t.gross for t in report if t.owed_to == "paye_ni"), ZERO)
    employers = sum((t.gross for t in report if t.account_code == EMPLOYERS_NI), ZERO)
    less = owed - p32.gross
    if report and ZERO < less <= employers:
        return less, f"what it says is due, {_gbp(p32.gross)}, is the payroll report's {_gbp(owed)} of tax and NI less it"
    return None


def _in_pounds(rows: list[Transaction], settings: BusinessSettings) -> list[Transaction]:
    """The rows, each document in another currency booked at the pounds its payment took: the one bank or card line
    in pounds, the same way, surely to the same payee, nearest its date (a week before to a fortnight after) and paying
    no document in pounds exactly. Its rows are scaled by that rate and checked again. With no such line, or two as
    near, the document stays as read, for a person to enter the pounds."""
    out = list(rows)
    groups: dict[str, list[int]] = {}
    for n, tx in enumerate(rows):
        if (tx.currency != "GBP" and tx.date and tx.document_type not in ("statement", "payroll", "journal")
                and booked(tx)):
            groups.setdefault(tx.document_ref or f"row-{n}", []).append(n)
    if not groups:
        return out
    pounds = [tx for tx in rows if tx.currency == "GBP" and tx.document_type not in ("statement", "journal")
              and booked(tx)]
    used: set[int] = set()
    for members in sorted(groups.values(), key=lambda m: (rows[m[0]].date, m[0])):
        first = rows[members[0]]
        total = sum((rows[n].gross if rows[n].direction == first.direction else -rows[n].gross for n in members),
                    ZERO)
        if total <= ZERO:
            continue

        def fits(n: int, line: Transaction) -> bool:
            return (n not in used and line.document_type == "statement" and line.currency == "GBP"
                    and line.direction == first.direction and line.date is not None and line.link is None
                    and booked_line(line) and line.counterparty is not None
                    and same_payee(line.counterparty, first.counterparty)
                    and first.date - CONVERT_BEFORE <= line.date <= first.date + CONVERT_AFTER
                    and Decimal("0.2") <= line.gross / total <= 5
                    and not any(d.gross == line.gross and d.counterparty
                                and same_payee(line.counterparty, d.counterparty) for d in pounds))

        near = sorted((abs((line.date - first.date).days), n) for n, line in enumerate(rows) if fits(n, line))
        if not near or (len(near) > 1 and near[0][0] == near[1][0]):
            continue
        k = near[0][1]
        used.add(k)
        line, rate, left = rows[k], rows[k].gross / total, rows[k].gross

        def scaled(value: Optional[Decimal]) -> Optional[Decimal]:
            return None if value is None else (value * rate).quantize(PENNY, rounding=ROUND_HALF_UP)

        for j, n in enumerate(members):
            tx = rows[n]
            sign = 1 if tx.direction == first.direction else -1
            gross = sign * left if j == len(members) - 1 else scaled(tx.gross)
            left -= sign * gross
            converted = normalise(tx.model_copy(update={
                "currency": "GBP", "gross": gross, "vat": scaled(tx.vat), "document_total": scaled(tx.document_total),
                "document_net": scaled(tx.document_net)}), settings)
            if j == 0:
                converted = converted.model_copy(update={"issues": converted.issues + [issue(
                    "converted_currency", f"Read as {tx.currency} {total:,.2f}; booked at the {_gbp(line.gross)} the "
                                          f"bank paid on {line.date:%d %b %Y}. If that payment was for something "
                                          "else, edit the row.", "info")]})
            out[n] = converted
    return out


def _with_payout_report(tx: Transaction) -> Transaction:
    """A payment processor's payout held in Payment Processor Clearing, which no payout report (read as an agent's
    statement) pays yet: the report is needed to book the sales, fees and refunds it is made of."""
    if (tx.document_type == "statement" and tx.direction == Direction.IN and tx.account_code == CLEARING
            and not tx.pays and booked(tx) and booked_line(tx)):
        who = processor(tx.counterparty, tx.description) or "payment processor"
        when = f" for {long_date(tx.date)}" if tx.date else ""
        return tx.model_copy(update={"issues": tx.issues + [issue(
            "payout_report", f"A {who} payout is sales less {who}'s fees and refunds: upload the {who} payout report"
                             f"{when}, so they are booked. Held in Payment Processor Clearing until then.")]})
    return tx


def booked_line(tx: Transaction) -> bool:
    """A bank line or an agent's item that moves money in the books: not one dated before the client's first year,
    which the opening balances already hold, nor a line another statement already has (the statements overlap),
    unless a person ticked Include."""
    return tx.include or not (tx.in_opening or tx.copy_of is not None)


def _pair_transfers(rows: list[Transaction], settings: BusinessSettings, changes: list[dict],
                    apart: list[set[int]]) -> set[int]:
    """The transfers between the client's own accounts with both statements in: a line out of one of its accounts
    coded to another, and a line into that other account coded back to the first, for the same amount and dated within
    a few days, the nearest dates first. The line out books the transfer; the line in is recorded by it and not
    booked, so the money moves once. A line a person linked to documents, or said is not the same as the other, stays
    apart. The places of the lines paired."""
    own = set(settings.bank_accounts)

    def bank(tx: Transaction) -> str:
        return tx.bank_account or settings.bank_account

    lines = [n for n, tx in enumerate(rows) if tx.document_type == "statement" and not tx.link and tx.date
             and booked_line(tx) and tx.account_code in own and bank(tx) in own and tx.account_code != bank(tx)]
    pairs = sorted((abs(rows[a].date - rows[b].date), rows[a].date, a, b) for a in lines for b in lines
                   if rows[a].direction == Direction.OUT and rows[b].direction == Direction.IN
                   and rows[a].account_code == bank(rows[b]) and rows[b].account_code == bank(rows[a])
                   and rows[a].gross == rows[b].gross and abs(rows[a].date - rows[b].date) <= TRANSFER_DAYS
                   and b not in apart[a])
    paired: set[int] = set()
    for _, _, a, b in pairs:
        if a in paired or b in paired:
            continue
        paired |= {a, b}
        out = rows[a]
        changes[b]["recorded_by"] = Settlement(ref=out.document_ref or f"row-{a}", amount=out.gross, date=out.date,
                                               description=out.description, kind=out.document_type)
        changes[b]["issues"] = rows[b].issues + [issue(
            "transfer", f"The other side of {out.description} on {long_date(out.date)}: booked once, from that line.",
            "info", related=[a])]
    return paired | _one_sided_transfers(rows, settings, changes, apart, paired)


def _one_sided_transfers(rows: list[Transaction], settings: BusinessSettings, changes: list[dict],
                         apart: list[set[int]], paired: set[int]) -> set[int]:
    """Transfers only one side of which was coded as one: a line on one of the client's accounts coded to another of
    them (a card's statement showing the payment in from the bank), and on that other account a line the other way,
    for the same amount and within a few days, coded to an account that is none of them (the bank's direct debit to
    the card company read as a cost). That line is recoded to the first line's account and checked again; then the
    two pair as any transfer does. A line a person linked, or said is not the same as the other, stays apart."""
    own = set(settings.bank_accounts)

    def bank(tx: Transaction) -> str:
        return tx.bank_account or settings.bank_account

    def free(n: int) -> bool:
        tx = rows[n]
        return (n not in paired and tx.document_type == "statement" and not tx.link and tx.date is not None
                and booked_line(tx))

    sure = [n for n in range(len(rows)) if free(n) and rows[n].account_code in own and bank(rows[n]) in own
            and rows[n].account_code != bank(rows[n])]
    loose = [n for n in range(len(rows)) if free(n) and rows[n].account_code not in own and bank(rows[n]) in own]
    pairs = sorted((abs(rows[s].date - rows[k].date), rows[s].date, s, k) for s in sure for k in loose
                   if bank(rows[k]) == rows[s].account_code and rows[k].direction != rows[s].direction
                   and rows[k].gross == rows[s].gross and abs(rows[s].date - rows[k].date) <= TRANSFER_DAYS
                   and k not in apart[s])
    found: set[int] = set()
    for _, _, s, k in pairs:
        if s in found or k in found:
            continue
        found |= {s, k}
        was = BY_CODE.get(rows[k].account_code)
        rows[k] = normalise(rows[k].model_copy(update={"account_code": bank(rows[s])}), settings)
        out, into = (k, s) if rows[k].direction == Direction.OUT else (s, k)
        line = rows[out]
        changes[into]["recorded_by"] = Settlement(ref=line.document_ref or f"row-{out}", amount=line.gross,
                                                  date=line.date, description=line.description, kind=line.document_type)
        recoded = (f"Recoded from {was.name if was else 'its account'} to {BY_CODE[bank(rows[s])].name}: it moves "
                   f"money between the client's accounts, as the {BY_CODE[bank(rows[s])].name} statement shows on "
                   f"{long_date(rows[s].date)}.")
        other = f"The other side of {line.description} on {long_date(line.date)}: booked once, from that line."
        if k == out:
            changes[k]["issues"] = rows[k].issues + [issue("transfer", recoded, "info", related=[s])]
            changes[into]["issues"] = rows[into].issues + [issue("transfer", other, "info", related=[out])]
        else:
            changes[k]["issues"] = rows[k].issues + [issue("transfer", f"{recoded} {other}", "info", related=[out])]
    return found


def _without_payroll(rows: list[Transaction]) -> list[Transaction]:
    """A payment on Net Wages, PAYE and NI or Pension Fund whose wages no payroll report books: the report must be
    dated in the payment's month or the one before."""
    months = {(tx.date.year, tx.date.month) for tx in rows if tx.document_type == "payroll" and tx.date}
    result = []
    for tx in rows:
        if tx.document_type == "statement" and tx.date and tx.account_code in PAYROLL_OWED:
            before = (tx.date.year, tx.date.month - 1) if tx.date.month > 1 else (tx.date.year - 1, 12)
            if not months & {(tx.date.year, tx.date.month), before}:
                found = issue("no_payroll", f"No payroll report for {tx.date:%B %Y}: add it so wages are booked in "
                                            "full.")
                tx = tx.model_copy(update={"issues": tx.issues + [found]})
        result.append(tx)
    return result


def _cleared(tx: Transaction) -> Transaction:
    """The row without the outputs of an earlier match."""
    return tx.model_copy(update={"paid_against": None, "pays": [], "candidates": [], "owed": None, "paid_by": [],
                                 "copy_of": None, "recorded_by": None, "claimed_in": None, "vat_found": None,
                                 "date_found": None, "amount_found": None, "documented_by": None,
                                 "recorded_by_refs": [], "left_off_claim": None, "claim_note": None, "recovers": None,
                                 "issues": [i for i in tx.issues if i.code not in MATCHING_ISSUES]})


def _pair_receipts(rows: list[Transaction], changes: list[dict], lines: list[int], apart: list[set[int]],
                   first_pass_only: bool = False) -> None:
    """Each card payment that a receipt records: a bank line nothing else was matched to, for the receipt's total,
    the same way and dated within a few days of it, the nearest receipt first and one from its shop before any
    other. The receipt is booked and the line is not, so the payment counts once and its VAT is the receipt's. A
    person's Link or Unlink on the line keeps them apart, as does saying they are not the same; one receipt records
    one line. With first_pass_only, only the pairs found by amount, date and name (or amount and date alone) are
    made; a receipt already paired is never paired again."""

    def kept_apart(n: int, receipt: _Document) -> bool:
        return any(r in apart[n] for r in receipt.rows)

    receipts = list(_grouped(rows, lambda tx: tx.document_type == "receipt" and (booked(tx) or tx.left_off_claim)
                             and tx.claimed_in is None and tx.date_found is None).values())
    receipts = [r for r in receipts if not any(changes[k].get("paid_by") or changes[k].get("recorded_by")
                                               for k in r.rows)]
    for by_name in (True, False):   # names first; then the amount and the date alone, which a bank's name can't spoil
        for n in lines:   # oldest first
            line, change = rows[n], changes[n]
            if (line.link is not None or line.date is None or change.get("pays") or change.get("candidates")
                    or change.get("recorded_by")):
                continue
            fits = [r for r in receipts if r.total == line.gross and r.date is not None
                    and card_days_apart(line.date, r.date) and r.direction == line.direction.value
                    and (not by_name or names_match(line.counterparty, r.counterparty)) and not kept_apart(n, r)]
            if not fits:
                continue
            receipt = min(fits, key=lambda r: (abs(line.date - r.date), r.date, r.ref))
            receipts.remove(receipt)
            _record(rows, changes, n, receipt)
    if first_pass_only:
        return
    # What is left: a receipt and a bank line that agree on all but the date, and only with each other. A receipt
    # without a date takes the bank's; one with another date asks, the bank's own date being taken as right.
    open_lines = [n for n in lines if rows[n].link is None and rows[n].date is not None
                  and not (changes[n].get("pays") or changes[n].get("candidates") or changes[n].get("recorded_by"))]

    def agrees(receipt: _Document, n: int) -> bool:
        line = rows[n]
        return (receipt.total == line.gross and receipt.direction == line.direction.value
                and same_payee(line.counterparty, receipt.counterparty) and not kept_apart(n, receipt)
                and (receipt.date is None or abs(line.date - receipt.date) <= YEAR))

    settled = _only_each_other(receipts, open_lines, agrees)
    for receipt, n in settled:
        line, first = rows[n], receipt.rows[0]
        if receipt.date is None:
            _record(rows, changes, n, receipt)
            for r in receipt.rows:
                note = issue("date_from_bank", f"No date on the receipt; dated {long_date(line.date)} from the bank.",
                             "info")
                changes[r].update(date=line.date, issues=[i for i in rows[r].issues if i.code != "date_missing"]
                                  + ([note] if r == first else []))
        else:   # the same amount: one payment, booked once; the question is only its date
            _record(rows, changes, n, receipt)
            asks = issue("date_conflict", f"Read as {long_date(receipt.date)}; the bank paid on {long_date(line.date)}.",
                         related=[n])
            changes[first].update(date_found=line.date, issues=rows[first].issues + [asks])
    # Then a receipt and a bank line from the same shop within a few days, left apart because their amounts differ,
    # and only with each other: the receipt was misread, or the payment is another. The receipt asks; the bank's
    # amount is taken as right.

    def differs(receipt: _Document, n: int) -> bool:
        line = rows[n]
        return (len(receipt.rows) == 1 and receipt.date is not None and card_days_apart(line.date, receipt.date)
                and receipt.direction == line.direction.value and names_match(line.counterparty, receipt.counterparty)
                and not kept_apart(n, receipt))

    used, used_lines = {r.ref for r, _ in settled}, {n for _, n in settled}
    for receipt, n in _only_each_other([r for r in receipts if r.ref not in used],
                                       [n for n in open_lines if n not in used_lines], differs):
        line, first = rows[n], receipt.rows[0]
        rate = _subtotal_only(rows[first], receipt, line)
        if rate:   # the receipt was read at its total before VAT: the bank line books the payment, documented by it
            held = Settlement(ref=line.document_ref or f"row-{n}", amount=line.gross, date=line.date,
                              description=line.description, kind=line.document_type)
            for r in receipt.rows:
                changes[r]["recorded_by"] = held
            changes[n]["documented_by"] = receipt.settlement(receipt.total)
            note = issue("subtotal_only", f"The receipt prints {_gbp(receipt.total)} before VAT and no total; the bank "
                                          f"paid {_gbp(line.gross)}, which is {_gbp(receipt.total)} plus VAT at {rate}. "
                                          "Booked from the bank line with no VAT: get a complete copy to reclaim the "
                                          f"{_gbp(line.gross - receipt.total)} VAT.", related=[n])
            changes[first].update(issues=rows[first].issues + [note])
            continue
        asks = issue("amount_conflict", f"Read as {_gbp(receipt.total)}; the bank paid {_gbp(line.gross)}. Not booked "
                                        "until you choose.", related=[n])
        held = Settlement(ref=line.document_ref or f"row-{n}", amount=line.gross, date=line.date,
                          description=line.description, kind=line.document_type)
        for r in receipt.rows:   # the payment counts once meanwhile: the bank line's
            changes[r]["recorded_by"] = held
        changes[first].update(amount_found=line.gross, issues=rows[first].issues + [asks])


_RATES_IN_WORDS = ((Decimal("0.20"), "20%"), (Decimal("0.05"), "5%"))


def _subtotal_only(tx: Transaction, receipt: _Document, line: Transaction) -> Optional[str]:
    """The VAT rate, in words, when a receipt was read at its total before VAT: what it books is the net it prints, and
    the bank paid exactly that plus VAT at 20% or 5% (a receipt cut off before its VAT and total). None otherwise."""
    if tx.document_net is None or tx.document_net != receipt.total:
        return None
    return next((words for rate, words in _RATES_IN_WORDS
                 if abs(receipt.total + (receipt.total * rate).quantize(PENNY) - line.gross) <= PENNY), None)


def _paid_again(rows: list[Transaction], changes: list[dict], lines: list[int], apart: list[set[int]]) -> None:
    """Each bank line nothing was matched to whose amount, counterparty and date are those of a receipt an expense
    claim line records: the receipt books the purchase, owed to the claimant, and the line books it again. The line
    warns booked_twice, pointing at the receipt and the claim line: if the line paid it, the claim line is the one to
    drop, and the line then pays the receipt. A person's Link or Unlink on the line, or saying they are not the same,
    keeps them apart."""
    receipts = _grouped(rows, lambda tx: tx.document_type == "receipt" and tx.claimed_in is not None and booked(tx))
    claim_lines: dict[str, list[int]] = {}
    for n, tx in enumerate(rows):
        if tx.document_type == "expense_claim" and tx.recorded_by is not None:
            claim_lines.setdefault(tx.recorded_by.ref, []).append(n)
    for n in lines:
        line, change = rows[n], changes[n]
        if line.link is not None or line.date is None or change.get("pays") or change.get("recorded_by"):
            continue
        receipt = next((r for r in receipts.values() if r.total == line.gross and r.date == line.date
                        and r.direction == line.direction.value and names_match(line.counterparty, r.counterparty)
                        and not any(k in apart[n] for k in r.rows)), None)
        if receipt is not None:
            twice = issue("booked_twice", f"Also booked from the expenses sheet's receipt ({receipt.counterparty}, "
                                          f"{_gbp(receipt.total)}, {long_date(receipt.date)}). If this line paid "
                                          "it, drop the expenses sheet line: this line then pays the receipt.",
                          related=receipt.rows + claim_lines.get(receipt.ref, []))
            change["issues"] = change.get("issues", line.issues) + [twice]


COVERED = dt.timedelta(days=35)   # a statement with a line this close either side of a day covers that day


def _off_statement(rows: list[Transaction], changes: list[dict], settings: BusinessSettings) -> None:
    """A receipt is booked as paid from (or into) a bank account or card. When that account's statement has lines
    either side of the receipt's day and none of them is its payment, the account did not pay it: the director's
    own card did, or cash. So it is kept off the bank, in Suspense, and says so, until a person says what paid it
    (Paid from, on the row). With no statement around its day nothing shows either way, and it stays on the bank."""
    days: dict[str, list[dt.date]] = {}
    for tx in rows:
        if tx.document_type == "statement" and tx.date and not tx.in_opening:
            days.setdefault(tx.contra_account_code, []).append(tx.date)
    for r, tx in enumerate(rows):
        change = changes[r]
        contra = change.get("contra_account_code", tx.contra_account_code)
        if (tx.document_type != "receipt" or tx.date is None or not booked(tx) or tx.claimed_in is not None
                or change.get("paid_by") or change.get("recorded_by") or change.get("date_found")
                or contra not in settings.bank_accounts or contra not in days):
            continue
        before = any(tx.date - COVERED <= day <= tx.date for day in days[contra])
        after = any(tx.date + CARD_DAYS <= day <= tx.date + COVERED for day in days[contra])
        if not (before and after):
            continue
        out = tx.direction == Direction.OUT
        said = issue("not_on_statement", (
            f"Not on the {BY_CODE[contra].name} statement, which has lines either side of {long_date(tx.date)}: that "
            f"account did not {'pay' if out else 'receive'} it. Kept off the bank, in Suspense, until you say what "
            f"{'paid it' if out else 'it was paid into'}: Edit the row and choose {'Paid from' if out else 'Paid into'}."))
        change.update(contra_account_code=SUSPENSE, issues=[*change.get("issues", tx.issues), said])


def _record(rows: list[Transaction], changes: list[dict], n: int, receipt: _Document) -> None:
    """Bank line n is the card payment the receipt records: the receipt is booked, paid by it, and the line is not.
    The receipt is paid from the line's account or card, which may not be the default bank."""
    line = rows[n]
    changes[n]["recorded_by"] = receipt.settlement(receipt.total)
    if not line.include:   # it posts nothing, so its account has no effect on the books: nothing to ask
        changes[n]["issues"] = [i for i in changes[n].get("issues", line.issues) if i.code not in ("account_not_recognised", "account_unclear")]
    for r in receipt.rows:
        if rows[r].left_off_claim:   # the business's card paid it after all: an ordinary receipt, not the claimant's
            changes[r]["left_off_claim"] = None
            changes[r]["issues"] = [i for i in changes[r].get("issues", rows[r].issues) if i.code != "not_claimed"]
        changes[r]["paid_by"] = [Settlement(ref=line.document_ref or f"row-{n}", amount=line.gross,
                                            date=line.date, description=line.description, kind=line.document_type)]
        changes[r]["contra_account_code"] = line.contra_account_code


# Rows that move money and so can pay a document: a bank line, and each item of an agent's statement (the rent it
# collected can pay a sales invoice, a repair it paid the plumber's bill).
_PAYMENT_LINES = frozenset({"statement", "agent_statement"})
# Notes on the VAT a row books: a claim line its receipt books books none, so they say nothing there.
_VAT_NOTES = frozenset({"vat_rate_mismatch", "vat_blocked"})
# What a claim line booked from its receipt leaves to the receipt, which books: its VAT notes and the questions its
# account asks (who a meal was for, refreshments claimed back, what a sundry was for).
_RECEIPTS_SAY = _VAT_NOTES | {"meal_check", "meal_decided", "sundry_check", "claim_note", "account_fact", "account_choice"}


def _documents(rows: list[Transaction]) -> dict[str, _Document]:
    """The open documents: booked invoices, claims and included documents. A claim still asks for the lines its
    receipts book; an invoice on a claim is owed to the claimant, on the claim, not to its supplier. A payroll
    report is not one: what it owes is on 2220, 2210 and 2230, which the bank payments clear."""
    return _grouped(rows, lambda tx: tx.document_type not in ("receipt", "statement", "payroll", "journal", "write_off")
                    and tx.claimed_in is None
                    and tx.currency == "GBP"   # nothing in pounds pays an amount in another currency: convert it first
                    and (booked(tx) or (tx.document_type == "expense_claim" and tx.recorded_by is not None)))


def _with_claims(rows: list[Transaction], settings: BusinessSettings, apart: list[set[int]],
                 name_days: Optional[list[Optional[dt.date]]] = None,
                 upload_ids: Optional[list[Optional[int]]] = None) -> list[Transaction]:
    """The rows, each expense claim line that a receipt or invoice also records marked as recorded by it: the same
    amount, the same way and dated within a few days, the nearest document first and one the line names before any
    other. The document is booked, since it shows the VAT that can be reclaimed, and is owed to the
    claimant on the claim's account; the claim line is not booked unless a person ticks Include, which books it as
    well and keeps it paired, so the tick can be undone."""
    documents = _grouped(rows, lambda tx: tx.document_type in ("receipt", "invoice") and booked(tx)).values()
    lines = [n for n, tx in enumerate(rows) if tx.document_type == "expense_claim" and tx.date]

    def named(line: Transaction, d: _Document) -> bool:
        return names_match(d.counterparty, _shop(line))

    def agrees(line: Transaction, d: _Document) -> bool:
        """All but the date: the amount, the way, and the line naming the document's counterparty."""
        return d.total == line.gross and d.direction == line.direction.value and named(line, d)

    def near(line: Transaction, d: _Document) -> bool:
        """The amount, the way, and dated within a few days."""
        return (d.date is not None and abs(d.date - line.date) <= CARD_DAYS and d.total == line.gross
                and d.direction == line.direction.value)

    def kept_apart(n: int, d: _Document) -> bool:
        return any(r in apart[n] for r in d.rows)

    # The claims whose lines add up to the total printed on them: that total confirms each line's amount.
    confirmed = {ref for ref, claim in _grouped(rows, lambda tx: tx.document_type == "expense_claim").items()
                 if (printed := next((rows[n].document_total for n in claim.rows if rows[n].document_total is not None),
                                     None)) is not None and claim.total == abs(printed)}
    marked, paired_lines, paired_documents = list(rows), set(), set()

    def pair(n: int, document: _Document, dated: Optional[dt.date] = None) -> None:
        """Claim line n is recorded by the document, which is owed to the claimant; dated: the document had no date,
        and takes the line's."""
        paired_lines.add(n)
        paired_documents.add(document.ref)
        line = rows[n]
        claim = Settlement(ref=line.document_ref or f"row-{n}", amount=line.gross, date=line.date,
                           kind="expense_claim", description=_claim_name(line))
        twice = []
        if line.include:   # a person ticked it: booked as well as the document, so it counts twice
            twice = [issue("booked_twice", f"Also booked from its {_NUMBERED.get(document.kind, 'document')} "
                                           f"({document.counterparty}, {_gbp(document.total)}, "
                                           f"{long_date(document.date or line.date)}). Untick unless they're separate "
                                           "purchases.", related=document.rows)]
        own = line.issues if line.include else [i for i in line.issues if i.code not in _RECEIPTS_SAY]
        marked[n] = line.model_copy(update={"recorded_by": document.settlement(document.total), "issues": own + twice})
        noted = {r: _noted(rows[r].model_copy(update={"date": dated}) if dated else rows[r], line, settings)
                 for r in document.rows}
        found, vat = _claim_vat(line, document, [noted.get(k, t) for k, t in enumerate(rows)], settings)
        if dated:
            kind = _NUMBERED.get(rows[document.rows[0]].document_type, "document")
            found = found + [issue("date_from_claim", f"No date on the {kind}; dated {long_date(dated)} from the "
                                                      "claim.", "info")]
        for k, r in enumerate(document.rows):
            issues = [i for i in noted[r].issues if not dated or i.code != "date_missing"]
            issues = _with_claim_vat(issues, vat) + found if k == 0 else issues
            marked[r] = noted[r].model_copy(update={"claimed_in": claim, "contra_account_code": STAFF_EXPENSES,
                                                    "issues": issues, **(vat if k == 0 else {})})

    # Those whose names agree first, so two records of the same amount and day pair by name; then the rest on the
    # amount and the date alone: names can differ (a mileage log names no one), but the amount and the date don't.
    for by_name in (True, False):
        pairs = sorted(((abs(d.date - rows[n].date), rows[n].date, n, d.ref, d) for n in lines for d in documents
                        if near(rows[n], d) and (not by_name or named(rows[n], d)) and not kept_apart(n, d)),
                       key=lambda pair: pair[:4])   # the nearest dates first
        for _, _, n, ref, document in pairs:
            if n not in paired_lines and ref not in paired_documents:
                pair(n, document)
    # An undated document whose file name holds a day pairs with the one open claim line of its amount and way on that
    # day, whatever the names say: the claimant's line and the file name agree on the day. Not when two such documents
    # share the day and amount, which would leave the line's document a guess.
    name_days = name_days or [None] * len(rows)
    for document in documents:
        day = name_days[document.rows[0]]
        if document.date is not None or day is None or document.ref in paired_documents:
            continue
        fits = [n for n in lines if n not in paired_lines and rows[n].date == day and rows[n].gross == document.total
                and rows[n].direction.value == document.direction and not kept_apart(n, document)]
        rivals = [d for d in documents if d.ref != document.ref and d.ref not in paired_documents and d.date is None
                  and name_days[d.rows[0]] == day and d.total == document.total]
        if len(fits) == 1 and not rivals:
            pair(fits[0], document, dated=day)
    # What is left: a document and a claim line that agree on all but the date, and only with each other. A document
    # without a date takes the line's; with another date, one of them was misread or mistyped, so both ask, and they
    # stay apart until a person says which date is right.
    open_documents = [d for d in documents if d.ref not in paired_documents]
    open_lines = [n for n in lines if n not in paired_lines]
    settled = _only_each_other(open_documents, open_lines, lambda d, n: agrees(rows[n], d) and not kept_apart(n, d)
                               and (d.date is None or abs(d.date - rows[n].date) <= YEAR))
    def ask(code: str, field: str, n: int, document: _Document, from_line, from_document,
            to_document: str, to_line: str) -> None:
        """The document and claim line n both ask which is right: each holds the other's value (field, for the
        choice), and its question points at the other (Show both)."""
        first = document.rows[0]
        marked[first] = marked[first].model_copy(update={
            field: from_line, "issues": marked[first].issues + [issue(code, to_document, related=[n])]})
        marked[n] = marked[n].model_copy(update={
            field: from_document, "issues": marked[n].issues + [issue(code, to_line, related=document.rows)]})

    for document, n in settled:
        line = rows[n]
        if document.date is None:
            pair(n, document, dated=line.date)
            continue
        pair(n, document)   # the same amount: one purchase, booked once; the question is only its date
        kind = _NUMBERED.get(document.kind, "document")
        ask("date_conflict", "date_found", n, document, line.date, document.date,
            f"Read as {long_date(document.date)}; the claim says {long_date(line.date)}.",
            f"Its {kind} was read as {long_date(document.date)}; this line says {long_date(line.date)}.")
    # Then a claim line for several receipts of one upload (a TfL statement's daily charges, read as a receipt each):
    # the one set of them, of the supplier the line names, that adds up to the line. Two sets that fit pair nothing.
    left_off: set[str] = set()
    if upload_ids:
        _pair_sets(rows, marked, lines, [d for d in documents if d.ref not in paired_documents], paired_lines,
                   paired_documents, left_off, upload_ids, settings, named, kept_apart)

    # Then a document on one account and a claim line from the same shop within a few days, left apart because their
    # amounts differ, and only with each other: one amount was misread, or only part of a bill is claimed.

    def differs(d: _Document, n: int) -> bool:
        line = rows[n]
        return (len(d.rows) == 1 and d.date is not None and abs(d.date - line.date) <= CARD_DAYS
                and d.direction == line.direction.value and not kept_apart(n, d)
                and (named(line, d) or _named_in(d.counterparty, _shop(line))))

    used, used_lines = {d.ref for d, _ in settled}, {n for _, n in settled}
    for document, n in _only_each_other([d for d in open_documents if d.ref not in used | paired_documents | left_off],
                                        [n for n in open_lines if n not in used_lines | paired_lines], differs):
        line = rows[n]
        kind = _NUMBERED.get(document.kind, "document")
        # The purchase counts once meanwhile: the claim line, which is what is owed, is booked and the document waits.
        held = Settlement(ref=line.document_ref or f"row-{n}", amount=line.gross, date=line.date,
                          description=line.description, kind="expense_claim")
        for r in document.rows:
            marked[r] = marked[r].model_copy(update={"recorded_by": held})
        if line.document_ref in confirmed and document.total >= line.gross:
            # The claimant claimed less than the bill, and the claim's printed total confirms the line: the company owes
            # what was claimed, so that is booked, the bill backs it (documented_by), and no one is asked.
            short = _gbp(document.total - line.gross)
            marked[n] = marked[n].model_copy(update={
                "documented_by": document.settlement(document.total),
                "issues": marked[n].issues + [issue("claimed_less", (
                    f"Claimed {_gbp(line.gross)}; its {kind} is {_gbp(document.total)}. The claim's total confirms "
                    f"{_gbp(line.gross)}, so that is booked and the {kind} backs it: {short} not claimed."), "info",
                    related=document.rows)]})
            first = document.rows[0]
            marked[first] = marked[first].model_copy(update={"issues": marked[first].issues + [issue("claimed_less", (
                f"Booked as claimed: {_gbp(line.gross)} of its {_gbp(document.total)}, which the claim's total "
                f"confirms ({short} not claimed)."), "info", related=[n])]})
            continue
        total = (f" The claim's total confirms {_gbp(line.gross)}; {_gbp(document.total)} puts it "
                 f"{_gbp(abs(document.total - line.gross))} out." if line.document_ref in confirmed else "")
        ask("amount_conflict", "amount_found", n, document, line.gross, document.total,
            f"Read as {_gbp(document.total)}; the claim says {_gbp(line.gross)}. Not booked until you choose.",
            f"Its {kind} was read as {_gbp(document.total)}; this line says {_gbp(line.gross)}.{total}")
    return marked


SET_LIMIT = 60          # an upload with more candidate receipts for a claim line than this is not searched for a set
_SUMS_LIMIT = 200_000   # nor one whose sums would take more than this much working out


def _one_set(amounts: list[int], target: int) -> tuple[int, Optional[list[int]]]:
    """How many sets of two or more of the amounts (in pence) add up to target, counted up to 2, and the places of
    the set when there is exactly one. A table of the sums each first so many amounts can reach, with how many ways
    and whether by none, one or more of them; (0, None) when the table would grow too big."""
    tables: list[dict[tuple[int, int], int]] = [{(0, 0): 1}]
    for amount in amounts:
        before, after = tables[-1], dict(tables[-1])
        for (total, size), ways in before.items():
            if total + amount <= target:
                key = (total + amount, min(size + 1, 2))
                after[key] = min(2, after.get(key, 0) + ways)
        if len(after) > _SUMS_LIMIT:
            return 0, None
        tables.append(after)
    found = tables[-1].get((target, 2), 0)
    if found != 1:
        return found, None
    chosen, total, size = [], target, 2
    for i in range(len(amounts), 0, -1):
        if tables[i - 1].get((total, size), 0):   # the one set is among the first i - 1 amounts
            continue
        chosen.append(i - 1)
        total -= amounts[i - 1]
        size = 0 if size == 1 else (1 if size == 2 and not tables[i - 1].get((total, 2), 0) else 2)
    return 1, sorted(chosen)


def _pair_sets(rows: list[Transaction], marked: list[Transaction], lines: list[int], documents: list[_Document],
               paired_lines: set[int], paired_documents: set[str], left_off: set[str],
               upload_ids: list[Optional[int]], settings: BusinessSettings, named, kept_apart) -> None:
    """Each claim line still open that the one set of its supplier's receipts on one upload adds up to: those
    receipts are owed to the claimant on the claim and the line is not booked, as with one receipt; the upload's other
    receipts of that supplier, the way and the days the line could claim, are the claimant's own (not_claimed)."""
    def candidates(n: int) -> dict[int, list[_Document]]:
        line, by_upload = rows[n], {}
        for d in documents:
            upload = upload_ids[d.rows[0]]
            if (d.kind == "receipt" and len(d.rows) == 1 and upload is not None and d.date is not None
                    and d.ref not in card_paid
                    and line.date - COVERED <= d.date <= line.date + CARD_DAYS and d.direction == line.direction.value
                    and named(line, d) and not kept_apart(n, d)):
                by_upload.setdefault(upload, []).append(d)
        return {u: sorted(ds, key=lambda d: (d.date, d.ref)) for u, ds in by_upload.items()}

    # A charge a bank line of the business could have paid (its amount, its way, within a few days) is the business's,
    # whatever adds up: bank matching, later, books it from the bank.
    bank = [k for k, tx in enumerate(rows) if tx.document_type == "statement" and tx.date and tx.link is None
            and booked_line(tx)]
    card_paid = {d.ref for d in documents if d.date is not None and any(
        rows[k].gross == d.total and rows[k].direction.value == d.direction
        and card_days_apart(rows[k].date, d.date) for k in bank)}
    # Every open line's sets first, so which line claims which charges never depends on which was looked at first.
    open_lines = sorted((n for n in lines if n not in paired_lines), key=lambda n: (rows[n].date, n))
    found: dict[int, list[tuple[int, list[_Document], Optional[list[int]]]]] = {}
    for n in open_lines:
        for pool in candidates(n).values():
            pool = [d for d in pool if d.ref not in paired_documents]
            if 2 <= len(pool) <= SET_LIMIT:
                count, places = _one_set([int(d.total * 100) for d in pool], int(rows[n].gross * 100))
                if count:
                    found.setdefault(n, []).append((count, pool, places))
    pools = {n: {d.ref for _, pool, _ in sets for d in pool} for n, sets in found.items()}
    one = {n: [sets[0][1][k] for k in sets[0][2]] for n, sets in found.items() if sum(c for c, _, _ in sets) == 1}
    unclear = {n for n in found if n not in one}
    for n, chosen in one.items():   # two lines that could claim the same charges: which claims which is a guess
        mine = {d.ref for d in chosen}
        rivals = {m for m in found if m != n and (
            mine & {d.ref for d in one[m]} if m in one else mine & pools[m])}
        if rivals:
            unclear |= {n} | rivals
    for n in sorted(unclear):
        _unclear(rows, marked, n, [pool for _, pool, _ in found[n]])
    pairing = [n for n in open_lines if n in one and n not in unclear]
    claimed = {d.ref for n in pairing for d in one[n]}   # every set first: one line's leftover may be another's charge
    for n in pairing:
        pool = next(pool for _, pool, _ in found[n])
        others = [d for d in pool if d.ref not in claimed and d.ref not in paired_documents and d.ref not in left_off]
        _book_set(rows, marked, n, one[n], others, settings)
        paired_lines.add(n)
        paired_documents.update(d.ref for d in one[n])
        left_off.update(d.ref for d in others)


def _unclear(rows: list[Transaction], marked: list[Transaction], n: int, pools: list[list[_Document]]) -> None:
    """Claim line n's charges add up to it in more than one way, or another line could claim the same ones: the line
    and the first charge of each upload say so, and point at each other; all stay booked as they are."""
    line = rows[n]
    supplier = pools[0][0].counterparty or "the supplier"
    claimant = line.counterparty or "the claimant"
    every = [r for pool in pools for d in pool for r in d.rows]
    marked[n] = marked[n].model_copy(update={"issues": marked[n].issues + [issue("claim_receipts_unclear", (
        f"{supplier}'s charges add up to {_gbp(line.gross)} in more than one way, or another claim line could claim "
        "the same ones: can't tell which this line claims."), related=every)]})
    for pool in pools:
        first = pool[0].rows[0]
        marked[first] = marked[first].model_copy(update={"issues": marked[first].issues + [issue(
            "claim_receipts_unclear", (f"Some of these charges add up to {claimant}'s claim line of "
                                       f"{_gbp(line.gross)} in more than one way: can't tell which it claims."),
            related=[n])]})


def _book_set(rows: list[Transaction], marked: list[Transaction], n: int, chosen: list[_Document],
              others: list[_Document], settings: BusinessSettings) -> None:
    """Claim line n is booked from the chosen receipts, which are owed to the claimant on the claim; the others are
    left off it."""
    line = rows[n]
    first, last = chosen[0], chosen[-1]
    total = sum((d.total for d in chosen), ZERO)
    days = (f"{first.date.day} to {long_date(last.date)}" if (first.date.year, first.date.month)
            == (last.date.year, last.date.month) else f"{long_date(first.date)} to {long_date(last.date)}")
    supplier = first.counterparty or "the supplier"
    them = Settlement(ref=first.ref, amount=total, date=last.date, kind="receipt",
                      description=f"{supplier}, {len(chosen)} charges, {days}")
    claim = Settlement(ref=line.document_ref or f"row-{n}", amount=line.gross, date=line.date,
                       kind="expense_claim", description=_claim_name(line))
    twice = [issue("booked_twice", f"Also booked from its {len(chosen)} receipts ({supplier}, {_gbp(total)}, {days}). "
                                   "Untick unless they're separate purchases.",
                   related=[r for d in chosen for r in d.rows])] if line.include else []
    own = line.issues if line.include else [i for i in line.issues if i.code not in _RECEIPTS_SAY]
    marked[n] = line.model_copy(update={"recorded_by": them, "recorded_by_refs": [d.ref for d in chosen],
                                        "issues": own + twice})
    together = _Document(ref=first.ref, kind="receipt", direction=first.direction, account=first.account,
                         counterparty=first.counterparty, description=them.description,
                         rows=[r for d in chosen for r in d.rows], total=total, date=last.date, open=total)
    noted = {r: _noted(rows[r], line, settings) for r in together.rows}
    found, vat = _claim_vat(line, together, [noted.get(k, t) for k, t in enumerate(rows)], settings)
    for k, r in enumerate(together.rows):
        marked[r] = noted[r].model_copy(update={"claimed_in": claim, "contra_account_code": STAFF_EXPENSES,
                                                "issues": (_with_claim_vat(noted[r].issues, vat) + found if k == 0
                                                           else noted[r].issues),
                                                **(vat if k == 0 else {})})
    claimant = line.counterparty or "the claimant"
    said = issue("not_claimed", (
        f"On {supplier}'s statement with {len(chosen)} charges on {claimant}'s claim, but not claimed itself. Not "
        f"booked: {claimant} paid it and hasn't asked for it back. If it was a business expense missed from the "
        "claim, tick Include."), related=[n])
    for d in others:
        for r in d.rows:
            marked[r] = rows[r].model_copy(update={"left_off_claim": claim, "contra_account_code": STAFF_EXPENSES,
                                                   "issues": rows[r].issues + [said]})


def _noted(tx: Transaction, line: Transaction, settings: BusinessSettings) -> Transaction:
    """The receipt or invoice claim line `line` is booked from, with the line's words as its claim note, on the
    account the note names if it names one, checked again so its questions and VAT follow (checks.account_by_note).
    What matching has already said about it is kept: checking drops it."""
    noting = tx.model_copy(update={"claim_note": line.description})
    away = noting.account_code == REFRESHMENTS
    if (account := account_on_claim(noting)) is not None:
        noting = noting.model_copy(update={"account_code": account})
    checked = normalise(noting, settings)
    said = [i for i in tx.issues if i.code in MATCHING_ISSUES or i.code in STATEMENT_ISSUES]
    if away and account is not None and not any(i.code == "claim_note" for i in checked.issues):
        said = [issue("claim_note", "Booked to Subsistence, not Refreshments: bought on an expense claim, so food or "
                                    "drink while working away, not for the workplace.", "info"), *said]
    return checked.model_copy(update={"issues": checked.issues + said})


def _shop(line: Transaction) -> str:
    """Where a claim line was spent: its description without the claimant's name, which is on every line of the claim
    (Barnes Plumbing is not where Matt Barnes spent)."""
    claimant = set(re.findall(r"[a-z]+", (line.counterparty or "").lower()))
    return " ".join(w for w in re.findall(r"[A-Za-z0-9&+]+", line.description) if w.lower() not in claimant)


def _claim_name(line: Transaction) -> str:
    return f"{line.counterparty}'s expense claim" if line.counterparty else "the expense claim"


def _with_claim_vat(issues: list[Issue], vat: dict) -> list[Issue]:
    """A document's issues once its claim line's VAT is booked on it (vat_from_claim): a hotel stay's own 20%
    (checks.hotel_vat) gives way to the claim's figure, which asks for the VAT invoice itself (claim_vat)."""
    return [i for i in issues if i.code != "hotel_vat"] if vat.get("vat_from_claim") else issues


def _claim_vat(line: Transaction, document: _Document, rows: list[Transaction],
               settings: BusinessSettings) -> tuple[list[Issue], dict]:
    """The claim line's VAT that its receipt or invoice does not show, with the change to the document's (first) row.
    Only what the document shows can be reclaimed, so it is a warning; but when the document, on one account,
    prints its total before VAT and that is its total less the claim's VAT, its own prices show the VAT: it is
    booked, or, when the document says it is not a VAT invoice, offered (Book VAT) for once the VAT invoice is in."""
    shown = sum((rows[r].vat or ZERO for r in document.rows), ZERO)
    first = rows[document.rows[0]]
    if not line.vat or shown >= line.vat or not reclaims_vat(first, settings):   # none to reclaim on its account
        return [], {}
    fine = "claim_vat" in first.accepted   # a person looked, and said it is fine as it is booked
    kind = _NUMBERED.get(first.document_type, "document")
    if (len(document.rows) == 1 and first.vat is None and first.document_net is not None
            and document.total - first.document_net == line.vat and reclaims_vat(first, settings)):
        prices = f"{_gbp(first.document_net)} before VAT, {_gbp(document.total)} in all"
        if first.not_vat_invoice:
            offer = issue("not_vat_invoice", f"VAT {_gbp(line.vat)} ({prices}) can't be reclaimed without a VAT "
                                             "invoice. Get it, then Book VAT.")
            return [offer], {"vat_found": line.vat}
        return ([issue("vat_worked_out", f"VAT {_gbp(line.vat)} booked from its prices: {prices}.", "info")],
                {"vat_posted": line.vat, "net": first.gross - line.vat})
    if (len(document.rows) == 1 and vat_implied(first, settings) and first.vat_posted is not None
            and abs(first.vat_posted - line.vat) <= PENNY):
        # A small receipt that prints the VAT number or says VAT is included is a VAT invoice in its own right: its
        # own rate gives the claim's VAT, booked from the receipt as it would be without the claim (its vat_implied).
        return [], {}
    if (len(document.rows) == 1 and first.vat is None and first.vat_treatment is None and line.vat < first.gross
            and reclaims_vat(first, settings) and not is_fare(first)):
        # The document is silent on VAT and the claim shows it: the claim is the person's record of the purchase, so
        # its VAT is booked and reclaimed, and the row says a VAT invoice is still wanted. (A document that shows a
        # VAT figure of its own, even nil, is not silent: below. A fare is zero-rated whatever the claim says.)
        said = [] if fine else [issue("claim_vat", f"VAT {_gbp(line.vat)} booked as the claim shows it; the {kind} "
                                                   "shows none. Get a VAT invoice for this.")]
        return said, {"vat_posted": line.vat, "net": first.gross - line.vat, "vat_from_claim": True}
    if fine:
        return [], {}
    on_it = f"only {_gbp(shown)}" if shown else "none"
    return [issue("claim_vat", f"The claim shows VAT {_gbp(line.vat)}; the {kind} shows {on_it}. Only the {kind}'s "
                               "VAT is reclaimed.")], {}


# How a message names each kind of document, beyond the numbered ones.
_KIND_WORDS = {"agent_statement": "agent's statement", "quote": "quote", "pro_forma": "pro forma invoice",
               "purchase_order": "purchase order", "remittance_advice": "remittance advice",
               "supplier_statement": "supplier's statement"}


def _checked_totals(rows: list[Transaction], read: list[Optional[Decimal]],
                    left_out: dict[str, dict[str, Decimal]]) -> list[Transaction]:
    """The rows, each document that doesn't add up to the total printed on it saying so once, with what is missing or
    too much, and pointing at its other rows (Show its lines). It says so on the row that explains it when one does:
    a row a person changed by just that much, or a row of just that much read twice, or the one row of that much;
    otherwise on the first row. Worked out afresh every time, so the warning goes once a line the reading missed is
    added, or a row read twice is removed. left_out is, for each document, the total of its rows a decision left out of
    the books: a document that adds up with them is not short of anything, only a decision has set them aside. A
    difference a person said to leave as it is (total_accepted, on the document's rows) raises a note in place of the
    warning, for as long as the difference is that much."""
    marked = list(rows)
    # A payroll report's rows go into a document for each payee, while the total it prints is its whole gross pay: its
    # pay lines are set against that when it is read (adapter: payroll_total), not each payee's here.
    for doc in _grouped(rows, lambda tx: tx.document_type not in ("statement", "payroll")).values():
        printed = next((rows[n].document_total for n in doc.rows if rows[n].document_total is not None), None)
        claimed_in = rows[doc.rows[0]].claimed_in
        if printed is None or (claimed_in is not None and claimed_in.amount == doc.total):
            continue   # none printed; or on a claim, whose line for it confirms what it books (part of a bill, say)
        first = rows[doc.rows[0]]
        accepted = next((rows[n].total_accepted for n in doc.rows if rows[n].total_accepted is not None), None)

        def left(text: str) -> None:
            marked[doc.rows[0]] = marked[doc.rows[0]].model_copy(update={
                "issues": marked[doc.rows[0]].issues + [issue("total_accepted", text, "info")]})

        if first.document_type == "agent_statement":
            net = doc.total if doc.direction == "in" else -doc.total
            if net == printed:
                continue
            if accepted == printed - net:
                left(f"Items net to {_gbp(net)}, {_gbp(abs(printed - net))} {'under' if printed > net else 'over'} "
                     f"the {_gbp(printed)} the statement paid over.")
                continue
            message = f"Items net to {_gbp(net)}; the statement paid over {_gbp(printed)}."
        else:
            printed = abs(printed)
            # What the document's excluded rows add to its total, signed as the total is: against its direction, less.
            aside = sum((g if d == doc.direction else -g for d, g in left_out.get(first.document_ref, {}).items()),
                        ZERO)
            if doc.total == printed or doc.total + aside == printed:
                continue
            kind = "claim" if first.document_type == "expense_claim" else (
                _NUMBERED.get(first.document_type) or _KIND_WORDS.get(first.document_type, "document"))
            word = "line" if first.document_type == "expense_claim" else "row"
            gap = printed - doc.total - aside   # what the lines, left out ones included, don't reach
            if accepted == gap:
                left(f"{word.capitalize()}s total {_gbp(doc.total)}, {_gbp(abs(gap))} "
                     f"{'under' if gap > 0 else 'over'} the {kind}'s {_gbp(printed)}.")
                continue
            message = (f"{word.capitalize()}s total {_gbp(doc.total)}; the {kind}'s total is {_gbp(printed)}. "
                       + (f"{_gbp(gap)} missing: add the {word}." if gap > 0
                          else f"{_gbp(-gap)} over: remove a duplicate or fix an amount."))
            changed = [n for n in doc.rows if read[n] is not None and rows[n].gross - read[n] == -gap]
            same = [n for n in doc.rows if rows[n].gross == -gap] if gap < 0 else []
            # A row that explains the difference carries it; otherwise it is the document's, not its first row's.
            where, explained = doc.rows[0], True
            if len(changed) == 1:
                where = changed[0]
                message = (f"Changed from {_gbp(read[where])} to {_gbp(rows[where].gross)}; {word}s now total "
                           f"{_gbp(doc.total)}, the {kind}'s total is {_gbp(printed)}. Revert if wrong.")
            elif len(same) == 2 and rows[same[0]].date == rows[same[1]].date:
                where = same[1]
                message = f"Repeats another {word} ({_gbp(-gap)}): read twice? Remove it if so."
            elif len(same) == 1:
                where = same[0]
                message = f"{_gbp(-gap)} over the {kind}'s total, this {word}'s amount. Check it belongs."
            else:
                explained = False
            # Show its lines: the line it repeats, when it was read twice; otherwise every other line.
            twice = len(changed) != 1 and len(same) == 2 and where == same[1]
            others = [same[0]] if twice else [n for n in doc.rows if n != where]
            at = marked[where]
            marked[where] = at.model_copy(update={"issues": at.issues + [issue(
                "total_mismatch", message, related=others, about="row" if explained else "document",
                difference=gap)]})
            continue
        marked[doc.rows[0]] = first.model_copy(update={"issues": first.issues + [issue(
            "total_mismatch", message, about="document", difference=printed - net)]})
    return marked


# The documents that carry a number of their own, which a copy of one repeats, as a message names each.
_NUMBERED = {"receipt": "receipt", "invoice": "invoice", "expense_claim": "expense claim"}


def _number(tx: Transaction) -> str:
    """A document number as printed, whatever its spacing, punctuation or case: "SC 2026 00718" is "SC-2026-00718"."""
    return re.sub(r"[^0-9A-Z]", "", (tx.document_number or "").upper())


def _without_copies(rows: list[Transaction]) -> list[Transaction]:
    """The rows, each row of a document that repeats an earlier one marked as its copy: the same kind of document
    with the same number, from the same counterparty, the same way and for the same total, such as a reminder of
    a bill or a receipt photographed twice (a receipt on the same day too: till numbers start again each day).
    A copy is not booked unless a person ticks Include."""
    numbered = _grouped(rows, lambda tx: tx.document_type in _NUMBERED and bool(_number(tx)))
    originals: list[_Document] = []
    marked = list(rows)
    for doc in sorted(numbered.values(), key=lambda d: (d.date or dt.date.max, d.ref)):
        first = rows[doc.rows[0]]
        original = next((o for o in originals if _repeats(first, doc, rows[o.rows[0]], o)), None)
        if original is None:
            originals.append(doc)
            continue
        found = issue("duplicate_document", f"Same {_NUMBERED[first.document_type]} as {original.label()}, no. "
                                            f"{first.document_number}. Not booked; tick Include if it's another.",
                      "info")
        for n in doc.rows:
            marked[n] = rows[n].model_copy(update={"copy_of": original.settlement(original.total),
                                                   "issues": rows[n].issues + [found]})
    return _without_repeated_lines(_without_unnumbered_copies(marked))


def _without_repeated_lines(rows: list[Transaction]) -> list[Transaction]:
    """The rows, each bank line that repeats an earlier one marked as its copy: the same account, day, amount and way,
    and the same running balance after it. One statement can't print that twice (a line moves the balance), so the
    line is on two statements whose periods overlap, or one statement was added twice. A copy is not booked unless a
    person ticks Include. Lines printed without a balance are left to the possible-duplicate check."""
    seen: dict[tuple, int] = {}
    marked = list(rows)
    for n, tx in enumerate(rows):
        if tx.document_type != "statement" or tx.date is None or tx.balance is None or tx.in_opening:
            continue
        first = seen.setdefault((tx.contra_account_code, tx.date, tx.direction, tx.gross, tx.balance), n)
        if first == n or tx.include:
            continue
        original = rows[first]
        found = issue("duplicate_document", f"Same line as one on another statement of this account "
                                            f"({long_date(tx.date)}, £{tx.gross:,.2f}, same balance after it): the "
                                            "statements overlap. Not booked; tick Include if it's another.", "info")
        marked[n] = tx.model_copy(update={
            "copy_of": Settlement(ref=original.document_ref or f"row-{first}", amount=original.gross,
                                  date=original.date, description=original.description, kind="statement"),
            "issues": tx.issues + [found]})
    return marked


def _lines(doc: _Document, rows: list[Transaction]) -> list[tuple]:
    return sorted((rows[n].date or dt.date.min, rows[n].gross, rows[n].direction.value) for n in doc.rows)


def _without_unnumbered_copies(rows: list[Transaction]) -> list[Transaction]:
    """The rows, each document of several lines and no number that repeats an earlier one line for line marked as
    its copy: the same kind, counterparty, way and total, and the same amount on the same day on every line, such as
    an expenses sheet uploaded again. One receipt like another is left alone: two coffees of one price on one day are
    often two coffees, which the possible-duplicate check asks about. A copy is not booked unless a person ticks
    Include."""
    several = [d for d in _grouped(rows, lambda tx: tx.document_type in _NUMBERED and not _number(tx)
                                   and tx.copy_of is None).values() if len(d.rows) > 1]
    originals: list[_Document] = []
    marked = list(rows)
    for doc in sorted(several, key=lambda d: d.rows[0]):   # the one read first is the original
        first = rows[doc.rows[0]]
        original = next((o for o in originals if rows[o.rows[0]].document_type == first.document_type
                         and o.direction == doc.direction and o.total == doc.total
                         and names_match(o.counterparty, doc.counterparty)
                         and _lines(o, rows) == _lines(doc, rows)), None)
        if original is None:
            originals.append(doc)
            continue
        kind = _NUMBERED[first.document_type]
        found = issue("duplicate_document", f"Same {kind} as {original.label()}, read again: the same "
                                            f"{len(doc.rows)} lines. Not booked; tick Include if it's another.", "info")
        for n in doc.rows:
            marked[n] = rows[n].model_copy(update={"copy_of": original.settlement(original.total),
                                                   "issues": rows[n].issues + [found]})
    return marked


def _repeats(tx: Transaction, doc: _Document, earlier_tx: Transaction, earlier: _Document) -> bool:
    return (tx.document_type == earlier_tx.document_type and _number(tx) == _number(earlier_tx)
            and doc.direction == earlier.direction and doc.total == earlier.total
            and names_match(doc.counterparty, earlier.counterparty)
            and (tx.document_type != "receipt" or doc.date == earlier.date))


def _grouped(rows: list[Transaction], keep) -> dict[str, _Document]:
    """The rows `keep` picks, grouped into documents by document_ref. A claim is dated by its latest dated line.
    An agent's statement is the agent's, and goes the way its net does: in when the agent owes the business."""
    documents: dict[str, _Document] = {}
    for n, tx in enumerate(rows):
        if not keep(tx):
            continue
        ref = tx.document_ref or f"row-{n}"
        who = tx.agent or tx.counterparty
        doc = documents.setdefault(ref, _Document(ref=ref, kind=tx.document_type, direction=tx.direction.value,
                                                  account=tx.contra_account_code, counterparty=who,
                                                  description=f"{tx.agent}'s statement" if tx.agent
                                                  else tx.description))
        doc.rows.append(n)
        doc.total += tx.gross if tx.direction.value == doc.direction else -tx.gross
        if tx.date and (doc.date is None or tx.date > doc.date):
            doc.date = tx.date
        doc.counterparty = doc.counterparty or who
    for doc in documents.values():
        if doc.total < 0:
            doc.direction, doc.total = ("in" if doc.direction == "out" else "out"), -doc.total
        doc.open = doc.total
    return documents


def _another(line: Transaction, doc: _Document) -> bool:
    """Still open, the same direction, and another document: an item of an agent's statement pays a bill or a claim,
    never an agent's statement, which only the bank line of its net pays."""
    return (doc.open > ZERO and doc.direction == line.direction.value and doc.ref != line.document_ref
            and not (line.document_type == "agent_statement" and doc.kind == "agent_statement"))


def _could_pay(line: Transaction, doc: _Document) -> bool:
    """Another open document the same way, and the payment dated on or after it, however long after. A payment of
    exactly what is owed clears the document whenever it comes; other payments also need to be within PART_WINDOW."""
    return (_another(line, doc) and doc.date is not None and line.date is not None
            and doc.date <= line.date and not (doc.written_off and line.date > doc.written_off))


def _recent(line: Transaction, doc: _Document) -> bool:
    """The payment dated within PART_WINDOW of the document it could pay."""
    return line.date <= doc.date + PART_WINDOW


def _paid_before(line: Transaction, doc: _Document) -> bool:
    """Another open document the same way, and the payment dated in the 31 days before it (a card payment or an
    advance). Such a payment is only ever suggested, never matched automatically."""
    return (_another(line, doc) and doc.date is not None and line.date is not None
            and line.date < doc.date <= line.date + WINDOW)


def _apply_link(n: int, line: Transaction, documents: dict[str, _Document], change: dict) -> Optional[list[Issue]]:
    """A person's decision on a bank line. None when it settles the line (Unlink, or Link to documents still in
    the table); otherwise the issues so far, and the line is matched automatically."""
    if line.link == []:                                   # Unlink: an ordinary bank line
        return None
    if line.link is None:
        return []
    linked = [documents[ref] for ref in line.link if ref in documents]
    if len(linked) < len(line.link):
        return [issue("stale_link", "Linked document gone; matched automatically.")]
    found: list[Issue] = []
    if len({d.account for d in linked}) > 1:              # one bank line posts against one account
        found.append(issue("mixed_link", "Linked documents are on different accounts. Link each to its own bank "
                                         "line.", "error"))
    else:
        _pay(n, line, linked, change, found)              # the person's choice, as given
    _note(change, line, found)
    return None


def _exact(line: Transaction, docs: list[_Document]) -> list[_Document]:
    """The documents surely from the line's counterparty (same_payee) with exactly the line's amount open on them."""
    return [d for d in docs if line.counterparty and same_payee(line.counterparty, d.counterparty)
            and d.open == line.gross]


def _to_owner(line: Transaction, owners: Sequence[str]) -> bool:
    """Whether the line pays one of the client's owners: read onto their own account, or parked in Suspense with one
    of them as its payee."""
    return line.account_code in OWNER_CODES or (line.account_code == SUSPENSE and any(
        same_payee(line.counterparty, name) for name in owners))


def _outcome(line: Transaction, documents: dict[str, _Document],
             owners: Sequence[str] = ()) -> tuple[str, list[list[_Document]], str]:
    """What _settle does with an automatic line: its kind (pay, choose, suggest, open_document or none), the
    documents it concerns, and why a suggestion or open_document was not a match. Owners: the client's owners' names."""
    kind, options = _decide(line, [d for d in documents.values() if _could_pay(line, d)])
    why = "the names do not match"
    if kind in ("none", "suggest") and line.direction == Direction.OUT and _to_owner(line, owners):
        # A payment to a director or partner (_to_owner) for exactly what one expense claim that names no claimant
        # owes: the claim's payment (its claimant is often only in the file's name).
        claims = [d for d in documents.values() if _could_pay(line, d) and d.kind == "expense_claim"
                  and not d.counterparty and d.open == line.gross]
        if len(claims) == 1:
            return "claim_paid", [claims], ""
    account = BY_CODE.get(line.account_code)
    owed_elsewhere = account is not None and line.account_code != SUSPENSE and account.type in (
        AccountType.LIABILITY, AccountType.EQUITY)   # tax, wages, a loan, the owner: never a supplier's bill
    if (kind == "pay" and owed_elsewhere and line.account_code != CREDITORS
            and sum((d.open for d in options[0]), ZERO) != line.gross):
        # A dividend, wages or a loan repayment to someone with a small bill open is not a part payment or an
        # overpayment of that bill: only its exact amount pays it, and anything else is for a person to link.
        kind, options, why = "open_document", [[d] for d in options[0]], (
            f"the amount differs and the line is on {account.name}")
    if kind == "none" and not owed_elsewhere:
        early = [d for d in documents.values() if _paid_before(line, d) and d.open == line.gross]
        sure = [d for d in early if line.bank_account in CARDS and line.counterparty and d.counterparty
                and same_payee(line.counterparty, d.counterparty) and d.date - line.date <= CHARGED_BEFORE]
        if len(early) == 1 and sure:
            # A card charged at the order, the invoice dated days later (an online shop's): the invoice's payment.
            kind, options, why = "early", [sure], ""
        elif early:
            kind, options, why = "suggest", [[d] for d in early], "the payment is dated before the document"
    if kind == "none":     # never silent: someone this line is paid to or from has an open document
        open_documents = [d for d in documents.values() if _another(line, d) and line.date and line.counterparty
                          and names_match(line.counterparty, d.counterparty)]
        if owed_elsewhere and line.account_code != CREDITORS:
            # Wages to S Marlow are not M Marlow's mileage claim: a line on tax, wages or a loan is only offered a
            # document of its amount, or one surely from the same person.
            open_documents = [d for d in open_documents if d.open == line.gross
                              or same_payee(line.counterparty, d.counterparty)]
        if open_documents:
            kind, options = "open_document", [[d] for d in open_documents]
            why = _why_not_matched(line, open_documents)
    if kind == "none":     # a balance brought forward without its invoices: early payments may be of it
        rest = [d for d in documents.values() if d.ref.startswith("ob-rest-") and _another(line, d) and line.date
                and d.date and line.date <= d.date + PART_WINDOW and line.gross <= d.open
                and BY_CODE.get(line.account_code) is not None
                and BY_CODE[line.account_code].type in (AccountType.INCOME, AccountType.EXPENSE)]
        if rest:
            kind, options = "open_document", [[d] for d in rest]
            why = "its invoices were not listed in the opening balances"
    return kind, options, why


def _settle(n: int, line: Transaction, documents: dict[str, _Document], change: dict, found: list[Issue],
            owners: Sequence[str] = (), settings: Optional[BusinessSettings] = None) -> None:
    kind, options, why = _outcome(line, documents, owners)
    if kind == "pay":
        _pay(n, line, options[0], change, found)
    elif kind == "claim_paid":
        # Paying the claim is its account: one the reader could not find no longer needs asking.
        line = line.model_copy(update={"issues": [i for i in line.issues if i.code != "account_unclear"]})
        change["issues"] = line.issues
        _pay(n, line, options[0], change, found)
        found.append(issue("claim_paid", f"Pays the expense claim of {long_date(options[0][0].date)} "
                                         f"({_gbp(line.gross)}): the claim names no claimant, and this payment to "
                                         f"{line.counterparty or 'them'} is exactly its total.", "info"))
    elif kind == "early":
        _pay(n, line, options[0], change, found)
        doc = options[0][0]
        found.append(issue("paid_before_invoice", f"Pays {doc.description} ({_gbp(line.gross)}), dated "
                                                  f"{long_date(doc.date)}: the card was charged before the invoice "
                                                  "was dated, as at an order.", "info"))
    elif kind == "oldest":
        paid = options[0][0].label()   # as it was open, before this payment
        _pay(n, line, options[0], change, found)
        found.append(issue("paid_oldest", f"Paid the oldest of {len(options)} open items of {_gbp(line.gross)}: "
                                          f"{paid}. If it was for another, Link that one."))
    elif kind == "choose":
        found.append(issue("choose_payment", f"Could pay: {_choices(options)}. Choose one.", "error"))
        change["candidates"] = [[d.settlement(d.open) for d in option] for option in options]
    elif kind == "open_document":
        if settings is not None and _on_account(line, options):
            # Money from a customer who owes more on an invoice it doesn't match is their payment on account, not a
            # sale with no VAT: Debtors stays as the customer owes it, and the invoice open until a person links it.
            checked = normalise(line.model_copy(update={"account_code": DEBTORS}), settings)
            change.update(account_code=DEBTORS, vat=checked.vat, vat_posted=checked.vat_posted, net=checked.net)
            line = line.model_copy(update={"issues": [i for i in checked.issues
                                                      if i.code not in ("on_account", "sale_without_vat")]})
            change["issues"] = line.issues
            found.append(issue("open_document", f"May pay {_choices(options)}: not matched because {why}. Held on "
                                                "Debtors as the customer's payment on account, not booked as a sale. "
                                                "Link it to the invoice it pays part of."))
        else:
            found.append(issue("open_document", f"May pay {_choices(options)}: not matched because {why}. Link it "
                                                "if so."))
        change["candidates"] = [[d.settlement(d.open) for d in option] for option in options]
    elif kind == "suggest":
        found.append(issue("possible_payment", f"May pay {_choices(options)}: same amount, but {why}. Link it if "
                                               "so."))
        change["candidates"] = [[d.settlement(d.open) for d in option] for option in options]
    _note(change, line, found)


def _on_account(line: Transaction, options: list[list[_Document]]) -> bool:
    """Whether a bank receipt the reader put on a sales account is a customer's payment on account: money in from a
    customer surely named (or their name in the line's, as an administrator's is), who owes more than it on an
    invoice it could not be matched to. A receipt of more than any of them owes may be a new sale, and stays."""
    account = BY_CODE.get(line.account_code)
    docs = [d for option in options for d in option]
    return (line.document_type == "statement" and line.direction == Direction.IN and not line.account_chosen
            and not line.link and account is not None and account.type == AccountType.INCOME and bool(docs)
            and all(d.direction == "in" and d.account == DEBTORS and d.counterparty and line.counterparty
                    and (same_payee(line.counterparty, d.counterparty) or _named_in(d.counterparty, line.counterparty))
                    for d in docs)
            and any(line.gross < d.open for d in docs))


def _why_not_matched(line: Transaction, docs: list[_Document]) -> str:
    """Why a line to someone with these open documents pays none of them: the first reason that applies."""
    if not any(d.open == line.gross for d in docs):
        return "the amount differs"
    if line.date and any(d.date and line.date > d.date + PART_WINDOW for d in docs):
        return "it is more than 120 days after the document"
    return "the payment is dated before the document"


def _decide(line: Transaction, docs: list[_Document]) -> tuple[str, list[list[_Document]]]:
    """What to do with a bank line, given the open documents it could pay (same direction, dated on or before it):
    pay them, ask a person to choose, suggest them, or nothing. Only documents surely from the same counterparty
    (same_payee) are ever paid automatically, and only those within 120 days unless they owe exactly what the line
    pays. A document whose name only resembles the line's is suggested (_outcome), for a person to Link."""
    named = [d for d in docs if line.counterparty and same_payee(line.counterparty, d.counterparty)]
    # A payment processor's or agent's statements only (Stripe's balance export saves a document a charge): it pays
    # out what it holds, oldest first, so a payout pays the oldest of them that add up to it. Never part of one: a
    # payout that is not a run of them is of what it held before (the year's opening balance), or one a person links.
    held = named and all(d.kind == "agent_statement" for d in named)
    if held:
        run = _oldest_adding_up_to(line.gross, named)
        if run:
            return "pay", [run]
    exact = _exact(line, named)
    if len(exact) == 1:
        return "pay", [exact]
    if exact:
        # Several owe exactly this, as when a customer pays the same each month: the one whose month the line names,
        # else the oldest, as an accountant allocates a payment. Asking held every later payment back as well.
        meant = [d for d in exact if _same_month(line.description, d.description)]
        if len(meant) == 1:
            return "pay", [meant]
        return "oldest", [[d] for d in sorted(exact, key=lambda d: (d.date or dt.date.max, d.ref))]
    named = [d for d in named if _recent(line, d)]
    docs = [d for d in docs if line.date <= d.date + WINDOW]
    sets = _sets_adding_up_to(line.gross, named)
    if sets:
        return ("pay", sets) if len(sets) == 1 else ("choose", sets)
    if named and not held:      # a part payment or an overpayment, when only one document can be meant
        return ("pay", [named]) if len(named) == 1 else ("choose", [[d] for d in named])
    same_amount = [d for d in docs if d.open == line.gross]
    # One document for exactly this amount, dated in the week before, whose name shares a name (not just a trade
    # word) with the line's ("Google Workspace Ireland", "Google Cloud EMEA Limited"): amount, day and name agree.
    if (len(same_amount) == 1 and line.date <= same_amount[0].date + NEAR_PAYMENT
            and _share_a_name(line.counterparty, same_amount[0].counterparty)):
        return "pay", [same_amount]
    return ("suggest", [[d] for d in same_amount]) if same_amount else ("none", [])


_MONTH = re.compile(r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|(may)|june?|july?|aug(?:ust)?|"
                    r"sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?,?\s*('?\d{4}|'?\d{2}\b)?",
                    re.IGNORECASE)
_MONTH_NUMBERS = {name: n for n, name in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), start=1)}


def _months(text: Optional[str]) -> set[tuple[int, Optional[int]]]:
    """The months a text names, with the year beside each if any: "retainer Jun 2023" is (6, 2023). "May" counts
    only with a year beside it, as it is also a word."""
    found = set()
    for m in _MONTH.finditer(text or ""):
        year = m.group(3).lstrip("'") if m.group(3) else None
        if m.group(2) and not year:
            continue
        found.add((_MONTH_NUMBERS[m.group(1)[:3].lower()],
                   None if year is None else int(year) + (2000 if len(year) == 2 else 0)))
    return found


def _same_month(line_text: Optional[str], document_text: Optional[str]) -> bool:
    """Whether a bank line names the month a document is for, the year agreeing where both print one."""
    return any(m == m2 and (y is None or y2 is None or y == y2)
               for m, y in _months(line_text) for m2, y2 in _months(document_text))


def _oldest_adding_up_to(amount: Decimal, docs: list[_Document]) -> list[_Document]:
    """The oldest documents, in order, whose open amounts add up to exactly the amount; none if no run of them does."""
    run, total = [], ZERO
    for d in sorted(docs, key=lambda d: (d.date or dt.date.max, d.ref)):
        run.append(d)
        total += d.open
        if total >= amount:
            break
    return run if total == amount else []


def _sets_adding_up_to(amount: Decimal, docs: list[_Document]) -> list[list[_Document]]:
    """Sets of two to five documents owed on the same account (a bank line posts against one account)
    whose open amounts add up to the payment, oldest documents first; stops once it has found more than
    five, since a person has to choose anyway."""
    found: list[list[_Document]] = []
    for account in sorted({d.account or "" for d in docs}):
        oldest = sorted((d for d in docs if (d.account or "") == account), key=lambda d: (d.date, d.ref))[:20]
        for size in range(2, MAX_SET + 1):
            for chosen in combinations(oldest, size):
                if sum((d.open for d in chosen), ZERO) == amount:
                    found.append(list(chosen))
                    if len(found) > 5:
                        return found
    return found


def _pay(n: int, line: Transaction, docs: list[_Document], change: dict, found: list[Issue]) -> None:
    """Applies the bank line to documents, oldest first: each takes what is open on it and the last takes
    the rest, so a part payment or an overpayment shows on it. The line then posts against the account
    holding what was owed, with no VAT: the VAT was booked with the document."""
    docs = sorted(docs, key=lambda d: (d.date or dt.date.max, d.ref))
    owed_before, left, pays = sum((d.open for d in docs), ZERO), line.gross, []
    for k, doc in enumerate(docs):
        take = left if k == len(docs) - 1 else min(doc.open, left)
        doc.open, left = doc.open - take, left - take
        pays.append(doc.settlement(take))
        doc.paid_by.append(Settlement(ref=line.document_ref or f"row-{n}", amount=take, date=line.date,
                                      description=f"{line.agent}'s statement" if line.agent else line.description,
                                      kind=line.document_type))
    still_owed = owed_before - line.gross
    if still_owed > ZERO:
        found.append(issue("part_payment", f"Paid {_gbp(line.gross)} of {_gbp(owed_before)}; {_gbp(still_owed)} "
                                           "still owed."))
    elif still_owed < ZERO:
        found.append(issue("overpayment", _overpaid(line, docs[-1], -still_owed)))
    change.update(paid_against=docs[0].account, pays=pays, vat_posted=ZERO, net=line.gross)


def _overpaid(line: Transaction, doc: _Document, excess: Decimal) -> str:
    whom = {DEBTORS: "the customer", STAFF_EXPENSES: "the employee"}.get(doc.account, "the supplier")
    if line.direction == Direction.IN:
        return f"Received {_gbp(excess)} over. You owe {whom} {_gbp(excess)}."
    return f"Paid {_gbp(excess)} over. {whom[0].upper()}{whom[1:]} owes you {_gbp(excess)}."


CHOICES_SAID = 3   # a message names this many of what a line may pay; Link lists them all


def _choices(options: list[list[_Document]]) -> str:
    said = " or ".join(" + ".join(d.label() for d in option) for option in options[:CHOICES_SAID])
    return said if len(options) <= CHOICES_SAID else f"{said}, or {len(options) - CHOICES_SAID} more"


def _note(change: dict, line: Transaction, found: list[Issue]) -> None:
    if found:
        change["issues"] = line.issues + found
