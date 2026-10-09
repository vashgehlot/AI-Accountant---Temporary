"""Makes a transaction ready to post (VAT split, bank account) and lists what a bookkeeper
should look at. Issues never change amounts; error-level issues block the trial balance."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Optional, Sequence

from .accounts import (BY_CODE, CAPITAL, CREDITORS, DEBTORS, DIRECTORS_LOAN, DRAWINGS, HOTELS, STAFF_EXPENSES,
                       Account, AccountType)
from .models import NOT_TRANSACTIONS, BusinessSettings, Direction, Issue, Transaction
from .money import PENNY, ZERO, VatTreatment, vat_in_gross

_NO_VAT = {AccountType.LIABILITY, AccountType.EQUITY}
# Issues matching.match adds; listed here so validating again replaces them instead of adding copies.
MATCHING_ISSUES = {"choose_payment", "part_payment", "overpayment", "possible_payment", "stale_link",
                   "mixed_link", "duplicate_document", "total_mismatch", "claim_vat", "vat_worked_out",
                   "not_vat_invoice", "date_conflict", "date_from_claim", "date_from_bank", "booked_twice",
                   "amount_conflict"}
# Issues statements.check_statement adds to bank lines, and file_dates.check_file_date to a document; derived too,
# so checking again replaces them.
STATEMENT_ISSUES = {"statement_gap", "statement_total", "file_date"}
_DERIVED = {"unknown_account", "same_account", "non_gbp_currency", "vat_not_applicable", "vat_estimated",
            "vat_arithmetic", "vat_rate_mismatch", "date_missing", "date_out_of_period", "unusual_direction",
            "not_booked", "vat_blocked", "director_loan"} | MATCHING_ISSUES | STATEMENT_ISSUES


def issue(code: str, message: str, severity: str = "warning", related: Sequence[int] = ()) -> Issue:
    return Issue(code=code, message=message, severity=severity, related=list(related))


def long_date(date: dt.date) -> str:
    """9 Sep 2026, as messages write a date."""
    return f"{date.day} {date:%b %Y}"


def is_derived(found: Issue) -> bool:
    """An issue the ledger works out afresh on every pass; such issues are never saved."""
    return found.code in _DERIVED


_NOT_TRANSACTION_NAMES = {
    "quote": "a quote", "pro_forma": "a pro forma invoice", "purchase_order": "a purchase order",
    "remittance_advice": "a remittance advice", "supplier_statement": "a supplier's statement of account",
    "other": "a document that is not a transaction",
}


def booked(tx: Transaction) -> bool:
    """A quote, a pro forma or another document that is not a transaction, or a copy of a document already in
    the table, is booked only when a person ticks Include. A card payment is booked from its receipt, which shows
    the VAT, and not again from the bank line; a claim line is booked from its receipt too, and as well only when a
    person ticks Include. (matching.match finds copies and receipts.)"""
    if tx.recorded_by is not None:
        return tx.include
    return tx.include or (tx.document_type not in NOT_TRANSACTIONS and tx.copy_of is None)


def other_side(tx: Transaction, settings: BusinessSettings) -> str:
    """The other side of a posting. A receipt or a bank line moved money through the bank. An invoice,
    a claim or an included document is owed until a bank line pays it: a sale to the customer's account
    (Debtors), anything else to the supplier's (Creditors), and a claim to the employee. What an agent
    collected and paid for the business is held by the agent (Debtors) until it pays over the net."""
    if tx.document_type == "expense_claim":
        return STAFF_EXPENSES
    if tx.document_type == "agent_statement":
        return DEBTORS
    if tx.document_type == "invoice" or tx.document_type in NOT_TRANSACTIONS:
        account = BY_CODE.get(tx.account_code)
        return DEBTORS if account is not None and account.type == AccountType.INCOME else CREDITORS
    return settings.bank_account


def reclaims_vat(tx: Transaction, settings: BusinessSettings) -> bool:
    """Whether VAT on the row is booked when it is shown, as normalise books it: the business is VAT registered,
    VAT applies to the account, and on a cost it can be reclaimed (not on business entertainment or a car)."""
    account = BY_CODE.get(tx.account_code)
    return (settings.vat_registered and account is not None and account.type not in _NO_VAT
            and (account.reclaim_vat or tx.direction == Direction.IN))


def _untaxed_part(vat: Decimal, gross: Decimal) -> Optional[tuple[Decimal, Decimal]]:
    """VAT short of the full 20% on an amount: the part it is 20% VAT on, and the part left with none (a tip, a
    service charge). None when nothing is left over."""
    taxed = vat * 6
    return (taxed, gross - taxed) if gross - taxed > 0 else None


def _mixed_items(account: Optional[Account], vat: Optional[Decimal], gross: Decimal,
                 untaxed: Optional[tuple[Decimal, Decimal]]) -> Issue:
    """One message for a document kept as one row because its one VAT total can't be divided between its items, with
    what its VAT says: a note on a hotel bill, booked to Hotels whole as a hotel bill usually is; elsewhere a
    warning."""
    hotel = account is not None and account.code == HOTELS
    name = account.name if account else "its account"
    text = (f"Kept as one row on {name}." if hotel else
            f"Items of different kinds with one VAT total: kept as one row on {name}. Split it by hand if needed.")
    if untaxed:
        text += f" VAT £{vat} is on £{untaxed[0]}; £{untaxed[1]} has none."
    return issue("mixed_items", text, "info" if hotel else "warning")


def _most_vat(gross: Decimal) -> Decimal:
    """The most VAT a VAT-inclusive amount can hold: a sixth (20% of the net), plus a little
    because invoices round VAT line by line."""
    return vat_in_gross(gross, VatTreatment.STANDARD) + Decimal("0.05") + (gross / 500).quantize(PENNY)


def normalise(tx: Transaction, settings: BusinessSettings) -> Transaction:
    kept = [i for i in tx.issues if i.code not in _DERIVED]   # re-validating must not duplicate
    issues: list[Issue] = []
    account = BY_CODE.get(tx.account_code)
    # The bank and the accounts for what is owed are worked out afresh on every pass, so a row whose
    # account or document type changes moves with it; any other account sent in (petty cash, say) is kept.
    worked_out = {None, settings.bank_account, DEBTORS, CREDITORS, STAFF_EXPENSES}
    contra = other_side(tx, settings) if tx.contra_account_code in worked_out else tx.contra_account_code
    if account is None:
        issues.append(issue("unknown_account", "This account isn't in the chart.", "error"))
    if contra not in BY_CODE:
        issues.append(issue("unknown_account", "Its other account isn't in the chart.", "error"))
    if contra == tx.account_code:
        issues.append(issue("same_account", "Posts to and from the same account.", "error"))
    if tx.currency != "GBP":
        issues.append(issue("non_gbp_currency", f"Convert {tx.currency} to GBP.", "error"))

    # Works from the inputs every time (vat as shown, vat_treatment as chosen) and never writes
    # them back, so a re-coded or corrected row gets its VAT worked out afresh.
    treatment = tx.vat_treatment or (account.vat if account else VatTreatment.OUTSIDE_SCOPE)
    vat = tx.vat
    posted: Optional[Decimal] = vat
    # The reading's own warning that the document's items were kept as one row: said once, with what its VAT says.
    mixed = any(i.code == "mixed_items" for i in kept)
    untaxed: Optional[tuple[Decimal, Decimal]] = None
    if not settings.vat_registered:
        posted = ZERO
    elif account is not None and account.type in _NO_VAT:
        if vat:
            issues.append(issue("vat_not_applicable", f"No VAT on {account.name}; ignored."))
        posted = ZERO
    elif account is not None and not account.reclaim_vat and tx.direction == Direction.OUT:
        # Business entertainment, or a car: the VAT can't be reclaimed, so it stays in the cost.
        if vat:
            issues.append(issue("vat_blocked", f"VAT £{vat} on {account.name} can't be reclaimed: kept in the cost.",
                                "info"))
        posted = ZERO
    elif vat is None and tx.vat_treatment is None:
        posted = ZERO   # VAT is reclaimable only when charged: none shown, none booked
    elif vat is None:   # a person chose the rate: split the VAT out of the gross at that rate
        posted = vat_in_gross(tx.gross, treatment)
        if posted > 0:
            issues.append(issue("vat_estimated", f"£{posted} estimated at the {treatment.value} rate. Check the invoice."))
    elif vat < 0 or vat >= tx.gross or vat > _most_vat(tx.gross):
        issues.append(issue("vat_arithmetic", f"VAT £{vat} is impossible on £{tx.gross}; at 20% it would be "
                                               f"£{vat_in_gross(tx.gross, VatTreatment.STANDARD)}.", "error"))
        posted = None
    elif (treatment in (VatTreatment.STANDARD, VatTreatment.REDUCED) and vat != 0   # 0.00: none charged
          and all(abs(vat - vat_in_gross(tx.gross, rate)) > Decimal("0.02")    # 5% is charged on energy too
                  for rate in (treatment, VatTreatment.REDUCED))):
        untaxed = _untaxed_part(vat, tx.gross) if treatment == VatTreatment.STANDARD else None
        if not mixed:
            issues.append(issue("vat_rate_mismatch", (
                f"£{vat} is 20% VAT on £{untaxed[0]}; £{untaxed[1]} has no VAT (a tip or service charge?)." if untaxed
                else f"£{vat} isn't {treatment.value}-rate VAT on £{tx.gross}."), "info"))
    if mixed:
        kept = [i for i in kept if i.code != "mixed_items"]
        issues.append(_mixed_items(account, vat, tx.gross, untaxed))

    if tx.date is None:
        issues.append(issue("date_missing", "No date. Add one."))
    elif ((settings.period_start and tx.date < settings.period_start)
          or (settings.period_end and tx.date > settings.period_end)):
        issues.append(issue("date_out_of_period", f"{tx.date} is outside the accounting period."))
    if account is not None and tx.direction == Direction.IN and account.type == AccountType.EXPENSE:
        issues.append(issue("unusual_direction", f"Money in on {account.name}: a refund?", "info"))
    if account is not None and tx.direction == Direction.OUT and account.type == AccountType.INCOME:
        issues.append(issue("unusual_direction", f"Money out on {account.name}: a customer refund?", "info"))
    if settings.business_type == "limited_company" and account is not None and tx.account_code in (CAPITAL, DRAWINGS):
        issues.append(issue("director_loan", f"Use Director's Loan Account, not {account.name}, for a limited "
                                             "company."))
    elif settings.business_type not in (None, "limited_company") and tx.account_code == DIRECTORS_LOAN:
        issues.append(issue("director_loan", "Director's Loan Account is for companies only. Use Drawings or "
                                             "Capital Introduced."))
    if tx.document_type in NOT_TRANSACTIONS and not tx.include:   # copies and card payments: matching says so
        issues.append(issue("not_booked", f"Looks like {_NOT_TRANSACTION_NAMES[tx.document_type]}: not booked. "
                                          "Tick Include to book it.", "info"))
    net = tx.gross - posted if posted is not None else None
    return tx.model_copy(update={"vat_posted": posted, "net": net, "contra_account_code": contra,
                                 "issues": kept + issues})
