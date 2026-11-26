"""Temporary (until Phase 4): maps the model's rows onto ledger Transactions. The model picks the
account from the chart and says whether money went in or out; a negative amount still means
money out, whatever the model said."""
from __future__ import annotations

import datetime as dt
import re
import uuid
from collections import Counter
from decimal import Decimal
from typing import Optional

from .accounts import (BY_CODE, CARDS, CLEARING, DEBTORS, LOANS, SUSPENSE, AccountType, owner_code, pays_cards)
from .payees import card_payment, media_business, on_account, personal, processor
from .checks import OWED_TO, issue, normalise
from .models import BOUGHT, DOCUMENT_TYPES, BusinessSettings, Direction, Transaction
from .money import VatTreatment, to_money, vat_in_gross


def parse_date(text) -> Optional[dt.date]:
    """ISO or UK day-first dates; None when absent or unreadable."""
    if not text:
        return None
    raw = str(text).strip()
    for candidate, fmt in ((raw[:10], "%Y-%m-%d"), (raw, "%d/%m/%Y"), (raw, "%d/%m/%y"), (raw, "%d-%m-%Y")):
        try:
            return dt.datetime.strptime(candidate, fmt).date()
        except ValueError:
            continue
    return None


# VAT number prefixes of suppliers outside the UK: EU member states' (and "EU" for the non-Union scheme).
_ABROAD = re.compile(r"^(AT|BE|BG|CY|CZ|DE|DK|EE|EL|ES|FI|FR|HR|HU|IE|IT|LT|LU|LV|MT|NL|PL|PT|RO|SE|SI|SK|EU)[0-9A-Z]")


def _reverse_charge(row: dict, kind: str, vat) -> bool:
    """Whether a purchase is a service from abroad the business accounts for the VAT on: an invoice or receipt that
    charges no VAT, which the reader saw say so, or which prints a VAT number of a supplier outside the UK."""
    if kind not in ("receipt", "invoice") or vat or str(row.get("direction") or "").strip().lower() == "in":
        return False
    said = row.get("reverse_charge")
    said = said.strip().lower() == "true" if isinstance(said, str) else bool(said)
    return said or bool(_ABROAD.match(_vat_number(row) or ""))


def _document_type(row: dict) -> str:
    """The model's document type; one the ledger does not know is left for a person to check."""
    kind = str(row.get("document_type") or "receipt").strip().lower()
    return kind if kind in DOCUMENT_TYPES else "other"


_SAYS_VAT_INVOICE = re.compile(r"\b(?:vat|tax)\s+invoice\b", re.I)
_SAYS_NOT_ONE = re.compile(r"\bnot\s+an?\s+(?:vat|tax)\s+invoice\b", re.I)


def _invoices_as_printed(rows: list[dict], text: str) -> list[dict]:
    """A document read as a receipt that calls itself a VAT invoice or a tax invoice ("Receipt / VAT Invoice", as a
    shop prints for a business customer) is an invoice: it reclaims its VAT whatever its size, and is not asked for
    again. Left as read when it says it is not one."""
    if not _SAYS_VAT_INVOICE.search(text) or _SAYS_NOT_ONE.search(text):
        return rows
    return [dict(row, document_type="invoice") if _document_type(row) == "receipt" else row for row in rows]


def _document_key(row: dict) -> Optional[tuple]:
    """Which document a row belongs to. Rows printed with the same total belong together when they come
    from the same kind of document, with the same counterparty and, except for a claim (whose lines have
    their own dates), the same date. The items of an agent's statement belong together whoever each was
    with and whatever they net to. None for a bank line or a row without a printed total."""
    total, kind = to_money(row.get("document_total")), _document_type(row)
    if not to_money(row.get("amount")) or kind == "statement":
        return None
    if kind == "agent_statement":
        return kind, str(row.get("agent") or "").strip().lower(), row.get("date")
    if not total:
        return None
    who = str(row.get("counterparty") or "").strip().lower()
    return abs(total), kind, who, None if kind == "expense_claim" else row.get("date")


def _documents(rows: list[dict]) -> dict:
    """The rows of each receipt, invoice or claim, keyed by _document_key."""
    documents: dict = {}
    for row in rows:
        key = _document_key(row)
        if key:
            documents.setdefault(key, []).append(row)
    return documents


def _vat_of(part: dict) -> Decimal:
    return abs(to_money(part.get("vat")) or 0)


_RATES = (VatTreatment.STANDARD, VatTreatment.REDUCED)
_ROUNDING = Decimal("0.02")   # invoices round VAT line by line


def _rates_of(part: dict) -> set[VatTreatment]:
    """The UK rates a part's own VAT fits within a penny or two of rounding: none for a part whose VAT fits no rate."""
    amount = abs(to_money(part.get("amount")))
    return {rate for rate in _RATES if abs(_vat_of(part) - vat_in_gross(amount, rate)) <= _ROUNDING}


def _vat_is_mixed(parts: list[dict]) -> bool:
    """Whether the VAT of one receipt's parts is not divided by account, so the parts can't be told apart by it: a
    part with VAT beside a part with none (the VAT is on only some of the items), or parts whose own VAT fits no
    one rate between them (20% on one, 5% on another). Each part is judged by its own rate, so the order of the
    lines makes no difference. VAT at one rate on each part is per item and divides."""
    bearing = [part for part in parts if _vat_of(part)]
    if not bearing:
        return False
    if len(bearing) < len(parts):
        return True
    fitted = [rates for rates in map(_rates_of, bearing) if rates]   # a part that fits no rate says nothing
    return bool(fitted) and not set.intersection(*fitted)


def _keep_unsplittable_whole(rows: list[dict]) -> list[dict]:
    """A receipt or invoice split by account whose VAT can't be divided between the parts is put back together as
    one row, flagged as mixed items, for the agent to split by the evidence. That is when the parts do not carry the
    VAT printed on it (one VAT total can't be divided without guessing), and when its items are at different VAT
    rates (zero-rated food beside standard-rated goods), whatever the model made of the VAT: it must not divide one
    rate's VAT between accounts. The row has the document's total and VAT as printed, on the account of its biggest
    part with VAT, else its biggest part."""
    merged: dict = {}
    for (total, *_), parts in _documents(rows).items():
        kind = _document_type(parts[0])
        if kind == "agent_statement" or len(parts) < 2:   # each item of a statement carries its own VAT
            continue
        printed_vat = to_money(parts[0].get("document_vat"))
        carried = sum(_vat_of(part) for part in parts)
        adds_up = sum(abs(to_money(part.get("amount"))) for part in parts) == total   # else they are separate receipts
        if adds_up and ((printed_vat and carried != abs(printed_vat))
                        or (kind != "expense_claim" and _vat_is_mixed(parts))):
            bearing = [part for part in parts if _vat_of(part)] or parts
            biggest = max(bearing, key=lambda part: abs(to_money(part.get("amount"))))
            vat = abs(printed_vat) if printed_vat else carried
            merged[id(parts[0])] = dict(biggest, amount=float(total), vat=float(vat), mixed_items=True)
            merged.update({id(part): None for part in parts[1:]})
    return [kept for kept in (merged.get(id(row), row) for row in rows) if kept is not None]


def _printed_total(row: dict) -> Optional[Decimal]:
    """The total printed on the row's document, which matching checks its rows against; an agent's statement's
    is the net it paid over, negative when the business owes the agent."""
    total = to_money(row.get("document_total"))
    return total if total is None or _document_type(row) == "agent_statement" else abs(total)


def _vat_number(row: dict) -> Optional[str]:
    """The supplier's VAT number without spaces, in upper case; None when none is printed."""
    return "".join(str(row.get("supplier_vat_number") or "").split()).upper() or None


_NUMBER = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")


def _numbers_in(text: str) -> set[Decimal]:
    """Every whole number in the text, as written with or without a pound sign or thousands commas: "£1,234.50" is
    1234.50. A figure inside a longer one ("60.00" in "1160.00" or "60.005") is not a number of its own."""
    return {Decimal(found.replace(",", "")) for found in _NUMBER.findall(text)}


def _only_printed_totals(rows: list[dict], text: str) -> list[dict]:
    """A claim's document_total that its text never prints is the model's own sum of the lines, not evidence: it
    becomes None, so the lines are not grouped and matched by it."""
    printed = _numbers_in(text)
    return [dict(row, document_total=None) if _document_type(row) == "expense_claim"
            and to_money(row.get("document_total")) is not None and abs(to_money(row.get("document_total"))) not in printed
            else row for row in rows]


def _printed_vat(row: dict, vat: Optional[Decimal], printed: Optional[set[Decimal]]) -> Optional[Decimal]:
    """The row's VAT when its document prints it, or prints the VAT total it is a share of: VAT the reader worked out
    (20% of a subtotal on a receipt cut off before its VAT) can't be reclaimed, so it is dropped. Kept on a bank line,
    and for a file with no text layer to check against."""
    if vat is None or not vat or printed is None or _document_type(row) == "statement":
        return vat
    total = to_money(row.get("document_vat"))
    return vat if abs(vat) in printed or (total is not None and abs(total) in printed) else None


def _worked_out(row: dict, printed: Optional[set[Decimal]]) -> bool:
    """Whether a document's row has a figure its text doesn't print: neither its amount nor its document's total is
    in the text (a receipt cut off before its total). Never for a bank line, or a file with no text layer."""
    if printed is None or _document_type(row) == "statement":
        return False
    figures = [to_money(row.get(name)) for name in ("amount", "document_total")]
    return not any(abs(f) in printed for f in figures if f is not None)


_CIS = re.compile(r"\bCIS\b|Construction Industry Scheme", re.IGNORECASE)


def _cis(row: dict, gross: Decimal, vat: Optional[Decimal], net: Optional[Decimal], text: Optional[str],
         printed: Optional[set[Decimal]]) -> Optional[Decimal]:
    """The CIS deduction taken off an invoice: as read, or else, when the reader missed it, the gap between its printed
    net (with its VAT) and the amount due, if the text names CIS and prints that gap as a figure. None on anything but
    an invoice."""
    if _document_type(row) != "invoice":
        return None
    read = to_money(row.get("cis_deducted"))
    if read:
        return abs(read)
    if net is None or text is None or printed is None or not _CIS.search(text):
        return None
    gap = abs(net) + abs(vat or 0) - gross
    return gap if gap > 0 and gap in printed else None


_LABOUR = {"5002", "7602"}   # subcontractors and consultants: the lines a CIS deduction is taken from


def _cis_lines(rows: list[dict]) -> dict[int, bool]:
    """Which rows carry their invoice's CIS deduction, by position, and whether the row's amount still has it in. An
    invoice of one row carries its own. On an invoice of several rows a reader repeats the one deduction on each: it
    is kept on one row, the labour line if there is one, and comes off that row when the rows were read before the
    deduction (they add up to the amount due plus it). Rows read with different deductions keep their own."""
    by_document: dict[tuple, list[int]] = {}
    for n, row in enumerate(rows):
        key = _document_key(row)
        if key and to_money(row.get("cis_deducted")):
            by_document.setdefault(key, []).append(n)
    lines = {}
    for key, carrying in by_document.items():
        figures = {abs(to_money(rows[n].get("cis_deducted"))) for n in carrying}
        if len(carrying) == 1 or len(figures) > 1:
            lines.update({n: False for n in carrying})
            continue
        [cis] = figures
        whole = [abs(to_money(r.get("amount"))) for r in rows if _document_key(r) == key]
        total = _printed_total(rows[carrying[0]])
        labour = [n for n in carrying if str(rows[n].get("account") or "")[:4] in _LABOUR]
        lines[(labour or carrying)[0]] = total is not None and sum(whole) == total + cis
    return lines


def _recoded(code: str, row: dict, settings: BusinessSettings) -> str:
    """What a bookkeeper recodes on sight. A payment processor's payout on a bank statement goes to Payment Processor
    Clearing, not to sales: it is sales less the processor's fees and refunds, which its payout report shows. A credit
    on a card statement worded as a payment is the card being paid off: a transfer from the client's bank. Spending
    with a consumer service (a streaming subscription) is the owner's: the Director's Loan Account for a company,
    Drawings for anyone else (left as read when the kind of business isn't known)."""
    account = BY_CODE.get(code)
    if account is None:
        return code
    loose = code == SUSPENSE or account.type in (AccountType.INCOME, AccountType.EXPENSE)
    names = (row.get("counterparty"), row.get("description"))
    owners = code == LOANS and _document_type(row) == "statement"   # a mortgage payment, read as a loan repayment
    if (row.get("direction") == "in" and _document_type(row) == "statement" and loose
            and settings.bank_account in CARDS and card_payment(*names)):
        # Money in on a card statement, worded as a payment: the card paid off from the bank, never a sale.
        return pays_cards(settings.bank_accounts, settings.bank_account) or code
    if row.get("direction") == "in" and _document_type(row) == "statement" and loose and processor(*names):
        return CLEARING
    if (row.get("direction") == "in" and _document_type(row) == "statement" and account.type == AccountType.INCOME
            and on_account(*names)):
        # Paid before it was invoiced: held on the customer's account as a credit, not yet a sale.
        return DEBTORS
    if (row.get("direction") != "in" and (loose or owners) and settings.business_type
            and account.type != AccountType.INCOME and personal(*names, business_type=settings.business_type,
                                                                media=media_business(settings.nature_of_business,
                                                                                     settings.sic_code))):
        return owner_code(settings.business_type, "drawings", settings.owners)
    return code


def _alternatives(row: dict, code: str) -> list[str]:
    """The other chart accounts the reader named for the row, by code: not its own, and only real ones."""
    found = [str(a)[:4] for a in row.get("alternatives") or []]
    return list(dict.fromkeys(a for a in found if a in BY_CODE and a != code))[:2]


def to_transactions(rows: list[dict], source: str, settings: BusinessSettings, opening_balance=None,
                    closing_balance=None, agent=None, text: Optional[str] = None) -> list[Transaction]:
    """The model's rows as ledger rows; a bank statement's opening and closing balances, and an agent's statement's
    agent, which the model gives once, go on each of its rows. text is what the file prints, when it has a text layer
    (a spreadsheet, csv or text, a PDF with text): a claim's total it does not print is dropped. None for an image."""
    result = []
    printed = _numbers_in(text) if text is not None else None
    if text is not None:
        rows = _only_printed_totals(_invoices_as_printed(rows, text), text)
    rows = [dict(row, agent=agent) if _document_type(row) == "agent_statement" else row
            for row in _keep_unsplittable_whole(rows)]
    refs = {key: uuid.uuid4().hex[:12] for key in _documents(rows)}   # one reference per document
    cis_lines, alone = _cis_lines(rows), Counter(_document_key(row) for row in rows)
    for position, row in enumerate(rows):
        amount = to_money(row.get("amount"))
        if not amount:
            continue
        issues = []
        key = _document_key(row)
        if row.get("mixed_items"):
            issues.append(issue("mixed_items", "Items at different VAT rates or of different kinds, with one VAT total: kept as one row."))
        said_in = row.get("direction") == "in"
        if said_in and amount < 0:
            issues.append(issue("direction_conflict",
                                "Marked money in, but the amount was negative: booked as money out."))
        code = str(row.get("account") or "")[:4]
        if code not in BY_CODE or code == settings.bank_account:
            issues.append(issue("account_not_recognised", f"'{row.get('account')}' isn't an account: put in "
                                                          "Suspense. Choose one."))
            code = SUSPENSE
        elif code == SUSPENSE:   # the model itself found no account: a purchase, which still needs its document
            issues.append(issue("account_unclear",
                                "Account unclear: put in Suspense. Choose one."))
        recoded = _recoded(code, dict(row, direction="in" if said_in and amount > 0 else "out"), settings)
        if recoded != code:
            issues = [i for i in issues if i.code != "account_unclear"]
            code = recoded
        vat, net = _printed_vat(row, to_money(row.get("vat")), printed), to_money(row.get("document_net"))
        kind = _document_type(row)
        statement = kind == "statement"
        gross = abs(amount)
        if key is None or alone[key] == 1:
            cis = _cis(row, gross, vat, net, text, printed)
            if cis and net is not None and gross == abs(net) + abs(vat or 0):   # read before the deduction: what is due
                gross -= cis
        else:   # one line of a longer invoice: only the line chosen to carry the deduction has it
            cis = _cis(row, gross, vat, net, None, None) if position in cis_lines else None
            if cis and cis_lines[position] and gross > cis:
                gross -= cis
        tx = Transaction(date=parse_date(row.get("date")), description=str(row.get("description") or ""),
                         direction=Direction.IN if said_in and amount > 0 else Direction.OUT,
                         gross=gross, vat=abs(vat) if vat is not None else None,   # sign: direction
                         account_code=code, currency=row.get("currency"), source=source,
                         method="llm", issues=issues, document_type=kind,
                         counterparty=str(row.get("counterparty") or "").strip() or None,
                         document_number=None if statement else str(row.get("document_number") or "").strip() or None,
                         supplier_vat_number=None if statement else _vat_number(row),
                         addressed_to=None if statement else str(row.get("addressed_to") or "").strip() or None,
                         reverse_charge=_reverse_charge(row, kind, vat),
                         abroad=bool(row.get("abroad")),
                         agent=str(row.get("agent") or "").strip() or None,
                         owed_to=row.get("owed_to") if kind == "payroll" and row.get("owed_to") in OWED_TO else None,
                         document_total=_printed_total(row) if key else None,
                         document_net=abs(net) if net is not None and not statement else None,
                         not_vat_invoice=not statement and bool(row.get("not_vat_invoice")),
                         vat_stated=not statement and vat is None and bool(row.get("vat_stated")),
                         total_worked_out=_worked_out(row, printed), cis_deducted=cis,
                         people=row.get("people") if row.get("people") in ("one", "several") else None,
                         bought=row.get("bought") if row.get("bought") in BOUGHT else None,
                         alternatives=_alternatives(row, code),
                         document_ref=refs[key] if key else uuid.uuid4().hex[:12],
                         balance=to_money(row.get("balance")) if statement else None,
                         opening_balance=to_money(opening_balance) if statement else None,
                         closing_balance=to_money(closing_balance) if statement else None)
        result.append(normalise(tx, settings))
    return _with_payroll_total(_with_payroll_people(result, printed, settings, text), settings, printed)


_OWN_PAY = {"7000", "7001"}   # an employee's own pay, tax and pension: not the employer's NI or pension


def _with_payroll_total(rows: list[Transaction], settings: BusinessSettings,
                        figures: Optional[set[Decimal]] = None) -> list[Transaction]:
    """A payroll report's pay, tax and pension lines (_OWN_PAY) add up to the total gross pay it prints (their
    document_total): when they don't, a figure was read or added up wrong (the model adds several people's net pay into
    one line), and the first of them says so. When they do, that total confirms the lines the model added up from each
    person's figures, so none is worked out. With no document_total, a figure the report prints (figures) that the
    lines add up to confirms them the same way."""
    pay = [n for n, tx in enumerate(rows) if tx.document_type == "payroll" and tx.account_code in _OWN_PAY]
    totals = {rows[n].document_total for n in pay}
    gross = sum((rows[n].gross for n in pay), Decimal("0.00"))
    if pay and totals == {None} and figures and gross in figures:
        return _confirmed(rows, pay, settings)
    if not pay or len(totals) != 1 or None in totals:
        return rows
    printed = totals.pop()
    if gross == printed:
        return _confirmed(rows, pay, settings)
    first = rows[pay[0]]
    said = issue("payroll_total", f"The pay, tax and pension lines add up to £{gross:,.2f}; the payroll report's total "
                                  f"gross pay is £{printed:,.2f}. Check each amount against the report.")
    checked = list(rows)
    checked[pay[0]] = normalise(first.model_copy(update={"issues": first.issues + [said]}), settings)
    return checked


def _confirmed(rows: list[Transaction], pay: list[int], settings: BusinessSettings) -> list[Transaction]:
    """The pay lines, their sum confirmed by the report's printed total: none is a worked-out figure to check."""
    checked = list(rows)
    for n in pay:
        if rows[n].total_worked_out:
            checked[n] = normalise(rows[n].model_copy(update={"total_worked_out": False}), settings)
    return checked


def _with_payroll_people(rows: list[Transaction], printed: Optional[set], settings: BusinessSettings,
                         text: Optional[str] = None) -> list[Transaction]:
    """A payroll report read from text: each person's net pay, tax and pension lines add up to their gross pay, which
    the report prints. A person whose lines add up to a figure it doesn't print was read wrong (pay moved between
    people leaves the totals right), and their first line says so. Checked only when the lines name two people or
    more and the report's text is to hand. A person is a payee the report names with net pay of their own: not
    several people in one line ("Hannah Finch, Omar Kestrel"), HMRC or a pension provider."""
    if printed is None:
        return rows
    named = " ".join((text or "").lower().split())
    people: dict[str, list[int]] = {}
    for n, tx in enumerate(rows):
        if tx.document_type == "payroll" and tx.account_code in _OWN_PAY and tx.counterparty:
            people.setdefault(tx.counterparty.strip().lower(), []).append(n)
    if len(people) < 2:   # one payee: the report's own totals check them
        return rows
    people = {who: places for who, places in people.items()
              if " ".join(who.split()) in named and any(rows[n].owed_to == "net_pay" for n in places)}
    checked = list(rows)
    for places in people.values():
        gross = sum((rows[n].gross for n in places), Decimal("0.00"))
        if gross not in printed:
            first = rows[places[0]]
            said = issue("payroll_person", f"{first.counterparty}'s pay, tax and pension lines add up to £{gross:,.2f}, "
                                           "which the payroll report doesn't print as anyone's gross pay. Check the "
                                           "amounts against the report: the totals can agree while a person's are wrong.")
            checked[places[0]] = normalise(first.model_copy(update={"issues": first.issues + [said]}), settings)
    return checked
