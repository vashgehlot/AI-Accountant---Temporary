"""The document rules: what a purchase needs before it can be booked. Under £50 nothing; from £50 to £250 a
receipt or invoice; over £250 a full VAT invoice. A receipt that shows the supplier's VAT number and the VAT
reclaims it (a simplified VAT invoice, up to £250). A row without what it needs waits in Suspense until the
document is uploaded. Only outgoing purchases and expenses are covered; transfers, tax, loans and money in are not.
Pure and deterministic: a row after checks.normalise and matching.match goes in, a verdict comes out."""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel

from .accounts import ALL_BANK_CODES, BY_CODE, SUSPENSE, Account, AccountType
from .models import BusinessSettings, Direction, JournalLine, Transaction
from .checks import hotel_vat, is_fare
from .money import ZERO, VatTreatment
from .payees import part_payment
from .posting import journal_for, withheld

NO_DOCUMENT_LIMIT = Decimal("50.00")   # below this a purchase needs no document
SIMPLIFIED_LIMIT = Decimal("250.00")   # up to this a receipt will do; above it only a full VAT invoice


class DocumentRule(BaseModel):
    action: Literal["book", "hold"]
    reclaim_vat: bool
    needs: Optional[Literal["receipt_or_invoice", "vat_invoice"]] = None
    reason: str          # one plain sentence, shown on the question card and the decision
    waived: bool = False  # it would be held, but a person booked it without the document (without_document)
    small: bool = False   # a purchase under the limit booked from its line: its VAT is not reclaimed without a document
    confirmed: bool = False   # the VAT is reclaimed only because a person entered or confirmed it (vat_confirmed)
    large_no_vat: bool = False   # a receipt over the simplified limit that shows no VAT: booked whole, and said
    unbacked: bool = False   # a line of an expense claim with no receipt or invoice behind it: booked as the claim
                             # shows it, VAT and all, and the row says the document is still wanted


def _fixed_asset(account: Account) -> bool:
    """Whether the account holds equipment or vehicles the business buys (0030 to 0055): not their depreciation,
    which is outside the scope of VAT, nor Debtors, Prepayments or the banks."""
    return (account.type == AccountType.ASSET and account.code.startswith("00")
            and account.vat != VatTreatment.OUTSIDE_SCOPE)


def _pays_its_document(tx: Transaction) -> bool:
    """Whether the row pays a document that fits it, which was booked, and checked, with the document: one a person
    linked, or one matching paid for exactly what the document owed. A payment of £50 or more that matching took as
    a part payment or an overpayment doesn't: the document's total differs from the payment, so it isn't the
    payment's document, and the payment waits for its own or for a person's Link; unless its own words say it is
    a deposit or a part payment, or the rest of the document was paid since (matching then says so as a note)."""
    if tx.paid_against is None:
        return False
    return (tx.link is not None or tx.gross < NO_DOCUMENT_LIMIT or part_payment(tx.description)
            or not any(i.code in ("part_payment", "overpayment") and i.severity != "info" for i in tx.issues))


def _parked_purchase(tx: Transaction) -> bool:
    """Whether the reader itself parked a line with no document behind it in Suspense because it found no account
    (account_unclear): a purchase whose account is unclear is still a purchase. A line in Suspense for any other
    reason (an unknown code, the bank's own) may be a transfer, so it stays exempt."""
    return (tx.account_code == SUSPENSE and tx.document_type in ("statement", "expense_claim")
            and any(i.code == "account_unclear" for i in tx.issues))


def _covered(tx: Transaction) -> bool:
    """Whether the rules apply: money out on an expense account or a fixed asset (or a purchase the reader parked
    in Suspense, _parked_purchase), not one of the client's own bank accounts, and not a payment of its document
    (_pays_its_document)."""
    account = BY_CODE.get(tx.account_code)
    return (tx.direction == Direction.OUT and account is not None
            and (account.type == AccountType.EXPENSE or _fixed_asset(account) or _parked_purchase(tx))
            and tx.account_code not in ALL_BANK_CODES and not _pays_its_document(tx)
            and not any(i.code == "reversed" for i in tx.issues))   # returned unpaid: the two lines cancel


# How a claim line words mileage in the claimant's own car, whose record is the claim itself.
_MILEAGE = re.compile(r"\bmileage\b|\b\d+\s*miles\b", re.IGNORECASE)


def _no_vat(tx: Transaction) -> bool:
    """Whether the row's account is one whose bills carry no VAT (business rates, insurance, rent): a bill or a
    demand backs it, and there is no VAT invoice to ask for."""
    account = BY_CODE.get(tx.account_code)
    return (account is not None and account.code != SUSPENSE   # in Suspense: what it is isn't known
            and account.vat in (VatTreatment.OUTSIDE_SCOPE, VatTreatment.EXEMPT))


def _hold(needs: Literal["receipt_or_invoice", "vat_invoice"], reason: str) -> DocumentRule:
    return DocumentRule(action="hold", reclaim_vat=False, needs=needs, reason=reason)


def document_rule(tx: Transaction, settings: BusinessSettings) -> DocumentRule:
    """What to do with one row after checks.normalise and matching.match: book it (reclaiming its VAT or not),
    or hold it in Suspense for the document it needs. A row a person booked without its document (without_document)
    is booked with no VAT reclaimed instead of held. VAT a person entered or confirmed on the row (vat_confirmed) is
    theirs to vouch for: where the rules alone would hold the row or keep its VAT in the cost, it is booked to its
    account and the VAT reclaimed, and the rule says so (confirmed). VAT the account itself can't take (Suspense,
    entertaining, before registration) was never posted, so there is none to reclaim. settings is accepted so the
    rules can follow a client's own settings later; none changes them yet."""
    rule = _rule(tx, settings)
    if tx.vat_confirmed and (tx.vat_posted or ZERO) > 0 and not rule.reclaim_vat:
        return DocumentRule(action="book", reclaim_vat=True, confirmed=True,
                            reason="VAT entered or confirmed by a person: reclaimed on their say.")
    if tx.vat_from_claim and (tx.vat_posted or ZERO) > 0 and not rule.reclaim_vat:
        # The VAT is the expense claim's, the receipt showing none: booked as claimed (matching says an invoice is wanted).
        return DocumentRule(action="book", reclaim_vat=True,
                            reason="VAT as the expense claim shows it: reclaimed, with a VAT invoice still wanted.")
    if hotel_vat(tx, settings) and (tx.vat_posted or ZERO) > 0 and not rule.reclaim_vat:
        # A hotel stay in the UK: its VAT is plain, so it is reclaimed now and the row asks for the property's VAT
        # invoice (the accountant's ruling), rather than booked whole or held in Suspense for it.
        return DocumentRule(action="book", reclaim_vat=True,
                            reason="VAT a hotel stay in the UK carries: reclaimed, with the VAT invoice still wanted.")
    if rule.action == "hold" and tx.without_document:
        return DocumentRule(action="book", reclaim_vat=False, waived=True,
                            reason=f"Booked without a receipt: {tx.without_document}; no VAT reclaimed.")
    return rule


def _rule(tx: Transaction, settings: BusinessSettings) -> DocumentRule:
    if not _covered(tx):
        return DocumentRule(action="book", reclaim_vat=True, reason="No document is needed for this kind of row.")
    if tx.document_type == "statement" and tx.documented_by is not None:
        return DocumentRule(action="book", reclaim_vat=False,
                            reason="Its receipt prints no total: booked from the bank line, with no VAT reclaimed.")
    if tx.document_type == "expense_claim" and tx.documented_by is not None:
        return DocumentRule(action="book", reclaim_vat=False,
                            reason="Booked as claimed, less than its bill, which backs it: VAT kept in the cost.")
    if tx.document_type == "expense_claim" and _MILEAGE.search(tx.description):
        return DocumentRule(action="book", reclaim_vat=False,
                            reason="A mileage claim is its own record: no receipt is needed.")
    if tx.document_type == "expense_claim":
        # A claim line with no receipt or invoice behind it. The claim is the person's own record of the expense,
        # so it is booked as it shows it, its VAT reclaimed; from £50, or with VAT on it, the row says the receipt or
        # the VAT invoice is still wanted (books._saved_rows).
        return DocumentRule(action="book", reclaim_vat=True,
                            unbacked=tx.gross >= NO_DOCUMENT_LIMIT or (tx.vat_posted or ZERO) > 0,
                            reason="Booked as the expense claim shows it: no receipt or invoice for it yet.")
    if tx.document_type == "statement":   # a bank line with no document behind it
        if tx.gross < NO_DOCUMENT_LIMIT:
            return DocumentRule(action="book", reclaim_vat=False, small=True,
                                reason="Small purchase: booked from the line without a receipt; no VAT reclaimed.")
        if tx.gross > SIMPLIFIED_LIMIT and not _no_vat(tx) and not is_fare(tx):   # a fare has no VAT: a receipt will do
            return _hold("vat_invoice", "No receipt or invoice, and a purchase this size needs a full VAT "
                                        "invoice: held in Suspense until it is uploaded.")
        return _hold("receipt_or_invoice", "No receipt or invoice: held in Suspense until one is uploaded.")
    if tx.document_type == "receipt":
        if tx.gross > SIMPLIFIED_LIMIT and not _no_vat(tx):
            if is_fare(tx):
                # A flight or a train ticket is zero-rated, at home or abroad: no VAT invoice exists to wait for.
                # Booked whole; any VAT on the row is not reclaimed unless a person vouches for it (document_rule).
                return DocumentRule(action="book", reclaim_vat=False,
                                    reason="A fare is zero-rated: booked whole, with no VAT to reclaim.")
            if not (tx.vat_posted or ZERO) > 0:
                # A VAT invoice is wanted to reclaim VAT. A receipt that shows none (a flight, a hotel booked through
                # an agent) has none to reclaim, and is the record of the cost: booked whole to its account.
                return DocumentRule(action="book", reclaim_vat=False, large_no_vat=True,
                                    reason="Receipt shows no VAT: booked whole, with nothing to reclaim.")
            return _hold("vat_invoice", "Only a receipt, but this needs a full VAT invoice: held in Suspense "
                                        "until it is uploaded.")
        if tx.not_vat_invoice:
            return DocumentRule(action="book", reclaim_vat=False, reason="Not a VAT invoice: VAT kept in the cost.")
        if not (tx.vat_posted or ZERO) > 0:
            return DocumentRule(action="book", reclaim_vat=False, reason="Receipt shows no VAT: nothing to reclaim.")
        if tx.vat is None and tx.supplier_vat_number is None and not tx.vat_stated:
            # VAT the receipt shows no sign of (a rate a person chose): kept in the cost.
            return DocumentRule(action="book", reclaim_vat=False,
                                reason="Receipt shows no VAT and no VAT number: VAT kept in the cost.")
        # VAT the receipt prints is reclaimed, with or without the supplier's VAT number, and estimated VAT (an Amazon
        # order summary's) counts as printed: the accountant's ruling.
        return DocumentRule(action="book", reclaim_vat=True, reason="Receipt shows the VAT: VAT reclaimed.")
    if tx.document_type == "invoice":
        if tx.not_vat_invoice:
            return DocumentRule(action="book", reclaim_vat=False, reason="Not a VAT invoice: VAT kept in the cost.")
        return DocumentRule(action="book", reclaim_vat=True, reason="Invoice: VAT reclaimed.")
    # Any other kind of row (a payroll line, an agent's statement) has no rule of its own: booked as normalise left it.
    return DocumentRule(action="book", reclaim_vat=True, reason="No document is needed for this kind of row.")


def journal_with_rule(tx: Transaction, index: int, rule: DocumentRule) -> list[JournalLine]:
    """Journal lines for one row after the rule: as posting.journal_for when it books and reclaims, the whole
    gross on the account (no VAT leg) when it books without, and the gross against Suspense when it is held.
    The row is not changed."""
    if rule.action == "book" and rule.reclaim_vat:
        return journal_for(tx, index)
    if rule.action == "book":   # the VAT stays in the cost
        # The cost is what is due plus any CIS the business withheld from it, which is owed to HMRC instead.
        return journal_for(tx.model_copy(update={"vat_posted": ZERO, "net": tx.gross + withheld(tx)}), index)
    out = tx.direction == Direction.OUT   # money out: Suspense takes the debit, the contra the credit
    lines = [JournalLine(transaction=index, code=SUSPENSE, description=tx.description,
                         debit=tx.gross if out else ZERO, credit=ZERO if out else tx.gross),
             JournalLine(transaction=index, code=tx.contra_account_code, description=tx.description,
                         debit=ZERO if out else tx.gross, credit=tx.gross if out else ZERO)]
    debits, credits = sum(l.debit for l in lines), sum(l.credit for l in lines)
    if debits != credits:   # one gross either side; this guards the invariant
        raise AssertionError(f"transaction {index} does not balance: {debits} != {credits}")
    return lines
