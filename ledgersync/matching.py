"""Matches bank lines to the open invoices and claims they pay (design of 2026-10-06), sets aside documents read
twice, and pairs card payments with their receipts. Pure functions: the same rows give the same matches, whatever
order they arrived in."""
from __future__ import annotations

import datetime as dt
import re
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal
from itertools import combinations
from typing import Optional

from .accounts import DEBTORS, STAFF_EXPENSES
from .checks import MATCHING_ISSUES, booked, issue, long_date, reclaims_vat
from .models import BusinessSettings, Direction, Issue, Settlement, Transaction
from .money import ZERO

WINDOW = dt.timedelta(days=31)   # a payment pays a document dated at most 31 days before it
CARD_DAYS = dt.timedelta(days=3)  # a card payment reaches the bank within a few days of its receipt
YEAR = dt.timedelta(days=366)     # records further apart than this are different purchases, whatever else agrees
MAX_SET = 5                      # one payment clears at most five documents from one counterparty

# Words that say nothing about who a business is: legal forms and small linking words, bank-statement
# noise (payment types and their short codes), generic trade words, and place and national words.
_IGNORED = {"ltd", "limited", "plc", "llp", "co", "the", "and", "for", "of", "to", "at", "in", "on",
            "bank", "payment", "payments", "fin", "card", "dd", "so", "bacs", "fps", "ref", "direct", "debit",
            "credit", "faster", "standing", "order", "transfer", "tfr", "deb", "vis", "pos", "bgc", "chq", "atm",
            "int", "services", "solutions", "group", "online", "international", "holdings", "company", "trading",
            "uk", "gb", "london", "british", "national", "royal", "england", "scotland", "wales"}


_LEGAL = {"ltd", "limited", "plc", "llp", "co", "the"}   # what initials leave out


def _initials(name: Optional[str]) -> str:
    """NCP for National Car Parks Ltd: the first letters of a name of three words or more."""
    words = [w for w in re.findall(r"[a-z]+", (name or "").lower()) if w not in _LEGAL]
    return "".join(w[0] for w in words) if len(words) >= 3 else ""


def _named_in(name: Optional[str], text: str) -> bool:
    """Every word of the name is a word of the text: EE in "Matt Barnes - EE, mobile phone bill". Too loose to pair
    on, as BT is in BT Sport, but enough to ask whether two records are one."""
    words = [w for w in re.findall(r"[a-z]+", (name or "").lower()) if w not in _LEGAL]
    return bool(words) and set(words) <= set(re.findall(r"[a-z]+", text.lower()))


def _words(name: Optional[str]) -> list[str]:
    return [w for w in re.findall(r"[a-z]+", (name or "").lower()) if w not in _IGNORED]


def _abbreviates(short: str, long: str) -> bool:
    """'mgmt' abbreviates 'management': three letters or more, the same first letter, the rest in order."""
    if not 3 <= len(short) < len(long) or short[0] != long[0]:
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
    when a word of one is the other's initials (NCP, National Car Parks)."""
    wa, wb = _words(a), _words(b)
    if any(w == initials for w, initials in ((w, _initials(b)) for w in wa) if len(w) >= 3) or any(
            w == initials for w, initials in ((w, _initials(a)) for w in wb) if len(w) >= 3):
        return True
    if wa and wa == wb:
        return True
    short, long = sorted((wa, wb), key=len)
    if short and sum(map(len, short)) >= 3 and _within(short, long):
        return True
    return (any(w in wb for w in wa if len(w) >= 4)
            or any(_abbreviates(x, y) or _abbreviates(y, x) for x in wa for y in wb))


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

    def settlement(self, amount: Decimal) -> Settlement:
        return Settlement(ref=self.ref, amount=amount, date=self.date, description=self.description, kind=self.kind)

    def label(self) -> str:
        when = f", {self.date:%d %b %Y}" if self.date else ""
        return f"{self.description} ({_gbp(self.open)}{when})"


def _only_each_other(docs: list[_Document], lines: list[int], agree) -> list[tuple[_Document, int]]:
    """The documents and lines that agree with each other and with nothing else in the two lists."""
    found = [(d, n) for d in docs for n in lines if agree(d, n)]
    by_doc, by_line = Counter(d.ref for d, _ in found), Counter(n for _, n in found)
    return [(d, n) for d, n in found if by_doc[d.ref] == 1 and by_line[n] == 1]


def _gbp(amount: Decimal) -> str:
    return f"£{amount:,.2f}"


def match(rows: list[Transaction], settings: BusinessSettings, read: Optional[list[Optional[Decimal]]] = None,
          apart: Optional[list[set[int]]] = None) -> list[Transaction]:
    """Which documents each bank line pays and what is still owed on each document, for transactions
    checks.normalise has already prepared. Lines a person linked go first; then lines that pay exactly what
    one document owes, whatever their date, so a bigger payment to the same person is never taken as an
    overpayment of a document another line pays exactly; then the rest, oldest first. So the result does not
    depend on the order the rows arrived in. With a client's saved rows come what a person decided: read, each row's
    amount as it was read before a person changed it (None if unchanged), and apart, for each row, the rows a person
    said are not the same as it, which are never paired with it or asked about."""
    read = read or [None] * len(rows)
    apart = apart or [set() for _ in rows]
    rows = _checked_totals(_with_claims(_without_copies([_cleared(tx) for tx in rows]), settings, apart), read)
    documents = _documents(rows)
    changes: list[dict] = [{} for _ in rows]
    lines = sorted((n for n, tx in enumerate(rows) if tx.document_type in _PAYMENT_LINES),
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
    for n, found in automatic.items():
        _settle(n, rows[n], documents, changes[n], found)
    _pair_receipts(rows, changes, [n for n in lines if rows[n].document_type == "statement"], apart)
    for doc in documents.values():
        for n in doc.rows:
            changes[n].update(owed=doc.open, document_direction=Direction(doc.direction), paid_by=list(doc.paid_by))
    return [tx.model_copy(update=change) if change else tx for tx, change in zip(rows, changes)]


def _cleared(tx: Transaction) -> Transaction:
    """The row without the outputs of an earlier match."""
    return tx.model_copy(update={"paid_against": None, "pays": [], "candidates": [], "owed": None, "paid_by": [],
                                 "copy_of": None, "recorded_by": None, "claimed_in": None, "vat_found": None,
                                 "date_found": None, "amount_found": None,
                                 "issues": [i for i in tx.issues if i.code not in MATCHING_ISSUES]})


def _pair_receipts(rows: list[Transaction], changes: list[dict], lines: list[int], apart: list[set[int]]) -> None:
    """Each card payment that a receipt records: a bank line nothing else was matched to, for the receipt's total,
    the same way and dated within a few days of it, the nearest receipt first and one from its shop before any
    other. The receipt is booked and the line is not, so the payment counts once and its VAT is the receipt's. A
    person's Link or Unlink on the line keeps them apart, as does saying they are not the same; one receipt records
    one line."""

    def kept_apart(n: int, receipt: _Document) -> bool:
        return any(r in apart[n] for r in receipt.rows)

    receipts = list(_grouped(rows, lambda tx: tx.document_type == "receipt" and booked(tx)
                             and tx.claimed_in is None and tx.date_found is None).values())
    for by_name in (True, False):   # names first; then the amount and the date alone, which a bank's name can't spoil
        for n in lines:   # oldest first
            line, change = rows[n], changes[n]
            if (line.link is not None or line.date is None or change.get("pays") or change.get("candidates")
                    or change.get("recorded_by")):
                continue
            fits = [r for r in receipts if r.date is not None and abs(line.date - r.date) <= CARD_DAYS
                    and r.total == line.gross and r.direction == line.direction.value
                    and (not by_name or names_match(line.counterparty, r.counterparty)) and not kept_apart(n, r)]
            if not fits:
                continue
            receipt = min(fits, key=lambda r: (abs(line.date - r.date), r.date, r.ref))
            receipts.remove(receipt)
            _record(rows, changes, n, receipt)
    # What is left: a receipt and a bank line that agree on all but the date, and only with each other. A receipt
    # without a date takes the bank's; one with another date asks, the bank's own date being taken as right.
    open_lines = [n for n in lines if rows[n].link is None and rows[n].date is not None
                  and not (changes[n].get("pays") or changes[n].get("candidates") or changes[n].get("recorded_by"))]

    def agrees(receipt: _Document, n: int) -> bool:
        line = rows[n]
        return (receipt.total == line.gross and receipt.direction == line.direction.value
                and names_match(line.counterparty, receipt.counterparty) and not kept_apart(n, receipt)
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
        return (len(receipt.rows) == 1 and receipt.date is not None and abs(line.date - receipt.date) <= CARD_DAYS
                and receipt.direction == line.direction.value and names_match(line.counterparty, receipt.counterparty)
                and not kept_apart(n, receipt))

    used, used_lines = {r.ref for r, _ in settled}, {n for _, n in settled}
    for receipt, n in _only_each_other([r for r in receipts if r.ref not in used],
                                       [n for n in open_lines if n not in used_lines], differs):
        line, first = rows[n], receipt.rows[0]
        asks = issue("amount_conflict", f"Read as {_gbp(receipt.total)}; the bank paid {_gbp(line.gross)}. Not booked "
                                        "until you choose.", related=[n])
        held = Settlement(ref=line.document_ref or f"row-{n}", amount=line.gross, date=line.date,
                          description=line.description, kind=line.document_type)
        for r in receipt.rows:   # the payment counts once meanwhile: the bank line's
            changes[r]["recorded_by"] = held
        changes[first].update(amount_found=line.gross, issues=rows[first].issues + [asks])


def _record(rows: list[Transaction], changes: list[dict], n: int, receipt: _Document) -> None:
    """Bank line n is the card payment the receipt records: the receipt is booked, paid by it, and the line is not."""
    line = rows[n]
    changes[n]["recorded_by"] = receipt.settlement(receipt.total)
    for r in receipt.rows:
        changes[r]["paid_by"] = [Settlement(ref=line.document_ref or f"row-{n}", amount=line.gross,
                                            date=line.date, description=line.description, kind=line.document_type)]


# Rows that move money and so can pay a document: a bank line, and each item of an agent's statement (the rent it
# collected can pay a sales invoice, a repair it paid the plumber's bill).
_PAYMENT_LINES = frozenset({"statement", "agent_statement"})
# Notes on the VAT a row books: a claim line its receipt books books none, so they say nothing there.
_VAT_NOTES = frozenset({"vat_rate_mismatch", "vat_blocked"})


def _documents(rows: list[Transaction]) -> dict[str, _Document]:
    """The open documents: booked invoices, claims and included documents. A claim still asks for the lines its
    receipts book; an invoice on a claim is owed to the claimant, on the claim, not to its supplier."""
    return _grouped(rows, lambda tx: tx.document_type not in ("receipt", "statement") and tx.claimed_in is None
                    and (booked(tx) or (tx.document_type == "expense_claim" and tx.recorded_by is not None)))


def _with_claims(rows: list[Transaction], settings: BusinessSettings, apart: list[set[int]]) -> list[Transaction]:
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
        own = line.issues if line.include else [i for i in line.issues if i.code not in _VAT_NOTES]
        marked[n] = line.model_copy(update={"recorded_by": document.settlement(document.total), "issues": own + twice})
        found, vat = _claim_vat(line, document, rows, settings)
        if dated:
            kind = _NUMBERED.get(rows[document.rows[0]].document_type, "document")
            found = found + [issue("date_from_claim", f"No date on the {kind}; dated {long_date(dated)} from the "
                                                      "claim.", "info")]
        for k, r in enumerate(document.rows):
            issues = [i for i in rows[r].issues if not dated or i.code != "date_missing"] + (found if k == 0 else [])
            marked[r] = rows[r].model_copy(update={"claimed_in": claim, "contra_account_code": STAFF_EXPENSES,
                                                   "issues": issues, **(vat if k == 0 else {}),
                                                   **({"date": dated} if dated else {})})

    # Those whose names agree first, so two records of the same amount and day pair by name; then the rest on the
    # amount and the date alone: names can differ (a mileage log names no one), but the amount and the date don't.
    for by_name in (True, False):
        pairs = sorted(((abs(d.date - rows[n].date), rows[n].date, n, d.ref, d) for n in lines for d in documents
                        if near(rows[n], d) and (not by_name or named(rows[n], d)) and not kept_apart(n, d)),
                       key=lambda pair: pair[:4])   # the nearest dates first
        for _, _, n, ref, document in pairs:
            if n not in paired_lines and ref not in paired_documents:
                pair(n, document)
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
    # Then a document on one account and a claim line from the same shop within a few days, left apart because their
    # amounts differ, and only with each other: one amount was misread, or only part of a bill is claimed.

    def differs(d: _Document, n: int) -> bool:
        line = rows[n]
        return (len(d.rows) == 1 and d.date is not None and abs(d.date - line.date) <= CARD_DAYS
                and d.direction == line.direction.value and not kept_apart(n, d)
                and (named(line, d) or _named_in(d.counterparty, _shop(line))))

    used, used_lines = {d.ref for d, _ in settled}, {n for _, n in settled}
    for document, n in _only_each_other([d for d in open_documents if d.ref not in used],
                                        [n for n in open_lines if n not in used_lines], differs):
        line = rows[n]
        kind = _NUMBERED.get(document.kind, "document")
        # The purchase counts once meanwhile: the claim line, which is what is owed, is booked and the document waits.
        held = Settlement(ref=line.document_ref or f"row-{n}", amount=line.gross, date=line.date,
                          description=line.description, kind="expense_claim")
        for r in document.rows:
            marked[r] = marked[r].model_copy(update={"recorded_by": held})
        total = (f" The claim's total confirms {_gbp(line.gross)}; {_gbp(document.total)} puts it "
                 f"{_gbp(abs(document.total - line.gross))} out." if line.document_ref in confirmed else "")
        ask("amount_conflict", "amount_found", n, document, line.gross, document.total,
            f"Read as {_gbp(document.total)}; the claim says {_gbp(line.gross)}. Not booked until you choose.",
            f"Its {kind} was read as {_gbp(document.total)}; this line says {_gbp(line.gross)}.{total}")
    return marked


def _shop(line: Transaction) -> str:
    """Where a claim line was spent: its description without the claimant's name, which is on every line of the claim
    (Barnes Plumbing is not where Matt Barnes spent)."""
    claimant = set(re.findall(r"[a-z]+", (line.counterparty or "").lower()))
    return " ".join(w for w in re.findall(r"[A-Za-z0-9&+]+", line.description) if w.lower() not in claimant)


def _claim_name(line: Transaction) -> str:
    return f"{line.counterparty}'s expense claim" if line.counterparty else "the expense claim"


def _claim_vat(line: Transaction, document: _Document, rows: list[Transaction],
               settings: BusinessSettings) -> tuple[list[Issue], dict]:
    """The claim line's VAT that its receipt or invoice does not show, with the change to the document's (first) row.
    Only what the document shows can be reclaimed, so it is a warning; but when the document, on one account,
    prints its total before VAT and that is its total less the claim's VAT, its own prices show the VAT: it is
    booked, or, when the document says it is not a VAT invoice, offered (Book VAT) for once the VAT invoice is in."""
    shown = sum((rows[r].vat or ZERO for r in document.rows), ZERO)
    if not line.vat or shown >= line.vat:
        return [], {}
    first = rows[document.rows[0]]
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
    on_it = f"only {_gbp(shown)}" if shown else "none"
    return [issue("claim_vat", f"The claim shows VAT {_gbp(line.vat)}; the {kind} shows {on_it}. Only the {kind}'s "
                               "VAT is reclaimed.")], {}


# How a message names each kind of document, beyond the numbered ones.
_KIND_WORDS = {"agent_statement": "agent's statement", "quote": "quote", "pro_forma": "pro forma invoice",
               "purchase_order": "purchase order", "remittance_advice": "remittance advice",
               "supplier_statement": "supplier's statement"}


def _checked_totals(rows: list[Transaction], read: list[Optional[Decimal]]) -> list[Transaction]:
    """The rows, each document that doesn't add up to the total printed on it saying so once, with what is missing or
    too much, and pointing at its other rows (Show its lines). It says so on the row that explains it when one does:
    a row a person changed by just that much, or a row of just that much read twice, or the one row of that much;
    otherwise on the first row. Worked out afresh every time, so the warning goes once a line the reading missed is
    added, or a row read twice is removed."""
    marked = list(rows)
    for doc in _grouped(rows, lambda tx: tx.document_type != "statement").values():
        printed = next((rows[n].document_total for n in doc.rows if rows[n].document_total is not None), None)
        claimed_in = rows[doc.rows[0]].claimed_in
        if printed is None or (claimed_in is not None and claimed_in.amount == doc.total):
            continue   # none printed; or on a claim, whose line for it confirms what it books (part of a bill, say)
        first = rows[doc.rows[0]]
        if first.document_type == "agent_statement":
            net = doc.total if doc.direction == "in" else -doc.total
            if net == printed:
                continue
            message = f"Items net to {_gbp(net)}; the statement paid over {_gbp(printed)}."
        else:
            printed = abs(printed)
            if doc.total == printed:
                continue
            kind = "claim" if first.document_type == "expense_claim" else (
                _NUMBERED.get(first.document_type) or _KIND_WORDS.get(first.document_type, "document"))
            word = "line" if first.document_type == "expense_claim" else "row"
            gap = printed - doc.total
            message = (f"{word.capitalize()}s total {_gbp(doc.total)}; the {kind}'s total is {_gbp(printed)}. "
                       + (f"{_gbp(gap)} missing: add the {word}." if gap > 0
                          else f"{_gbp(-gap)} over: remove a duplicate or fix an amount."))
            changed = [n for n in doc.rows if read[n] is not None and rows[n].gross - read[n] == -gap]
            same = [n for n in doc.rows if rows[n].gross == -gap] if gap < 0 else []
            where = doc.rows[0]
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
            # Show its lines: the line it repeats, when it was read twice; otherwise every other line.
            twice = len(changed) != 1 and len(same) == 2 and where == same[1]
            others = [same[0]] if twice else [n for n in doc.rows if n != where]
            at = marked[where]
            marked[where] = at.model_copy(update={"issues": at.issues + [issue("total_mismatch", message,
                                                                               related=others)]})
            continue
        marked[doc.rows[0]] = first.model_copy(update={"issues": first.issues + [issue("total_mismatch", message)]})
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
    """Another open document the same way, and the payment dated on or after it and within 31 days."""
    return (_another(line, doc) and doc.date is not None and line.date is not None
            and doc.date <= line.date <= doc.date + WINDOW)


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
    """The documents from the line's counterparty with exactly the line's amount open on them."""
    return [d for d in docs if line.counterparty and names_match(line.counterparty, d.counterparty)
            and d.open == line.gross]


def _settle(n: int, line: Transaction, documents: dict[str, _Document], change: dict, found: list[Issue]) -> None:
    kind, options = _decide(line, [d for d in documents.values() if _could_pay(line, d)])
    why = "the names do not match"
    if kind == "none":
        early = [d for d in documents.values() if _paid_before(line, d) and d.open == line.gross]
        if early:
            kind, options, why = "suggest", [[d] for d in early], "the payment is dated before the document"
    if kind == "pay":
        _pay(n, line, options[0], change, found)
    elif kind == "choose":
        found.append(issue("choose_payment", f"Could pay: {_choices(options)}. Choose one.", "error"))
        change["candidates"] = [[d.settlement(d.open) for d in option] for option in options]
    elif kind == "suggest":
        found.append(issue("possible_payment", f"May pay {_choices(options)}: same amount, but {why}. Link it if "
                                               "so."))
        change["candidates"] = [[d.settlement(d.open) for d in option] for option in options]
    _note(change, line, found)


def _decide(line: Transaction, docs: list[_Document]) -> tuple[str, list[list[_Document]]]:
    """What to do with a bank line, given the open documents it could pay (same direction, within 31 days):
    pay them, ask a person to choose, suggest them, or nothing. Only documents from the same counterparty
    are ever paid automatically."""
    named = [d for d in docs if line.counterparty and names_match(line.counterparty, d.counterparty)]
    exact = _exact(line, named)
    if exact:
        return ("pay", [exact]) if len(exact) == 1 else ("choose", [[d] for d in exact])
    sets = _sets_adding_up_to(line.gross, named)
    if sets:
        return ("pay", sets) if len(sets) == 1 else ("choose", sets)
    if named:      # a part payment or an overpayment, when only one document can be meant
        return ("pay", [named]) if len(named) == 1 else ("choose", [[d] for d in named])
    same_amount = [d for d in docs if d.open == line.gross]
    return ("suggest", [[d] for d in same_amount]) if same_amount else ("none", [])


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


def _choices(options: list[list[_Document]]) -> str:
    return " or ".join(" + ".join(d.label() for d in option) for option in options)


def _note(change: dict, line: Transaction, found: list[Issue]) -> None:
    if found:
        change["issues"] = line.issues + found
