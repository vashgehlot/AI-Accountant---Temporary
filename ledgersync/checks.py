"""Makes a transaction ready to post (VAT split, bank account) and lists what a bookkeeper
should look at. Issues never change amounts; error-level issues block the trial balance."""
from __future__ import annotations

import datetime as dt
import re
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional, Sequence

from .accounts import (ASSET_CANDIDATES, BY_CODE, CAPITALS, CARDS, CLEARING, CREDITORS, DEBTORS, DIRECTORS_LOANS, DIVIDENDS,
                       HALF_VAT_RECLAIMED, HOTELS, SMALL_EQUIPMENT_COST, MEMBERS_CURRENT, OWNER_DRAWINGS, OWNER_WORDS, SHARES, owner_codes, owner_slots,
                       NET_WAGES, PAYE, PENSION, PURCHASE_VAT, SALES_VAT, STAFF_EXPENSES, SUSPENSE, WAGES, Account,
                       AccountType)
from .models import NOT_TRANSACTIONS, BusinessSettings, Direction, Issue, Transaction
from .money import PENNY, ZERO, VatTreatment, vat_in_gross
from .payees import consumer_service, media_business, personal, processor

_NO_VAT = {AccountType.LIABILITY, AccountType.EQUITY}
# Issues matching.match adds; listed here so validating again replaces them instead of adding copies.
MATCHING_ISSUES = {"choose_payment", "paid_oldest", "converted_currency", "credited", "hmrc_reference", "employment_allowance", "bad_debt_recovered", "write_off_more_than_owed", "paid_before_invoice", "claim_paid", "part_payment", "overpayment", "possible_payment", "stale_link",
                   "mixed_link", "duplicate_document", "total_mismatch", "total_accepted", "claim_vat", "vat_worked_out",
                   "not_vat_invoice", "date_conflict", "date_from_claim", "date_from_bank", "booked_twice",
                   "amount_conflict", "open_document", "no_payroll", "transfer", "sale_without_vat",
                   "payout_report", "subtotal_only", "claimed_less", "not_on_statement", "till_takings",
                   "addressed_to", "refund_of_overpayment", "reversed", "not_claimed", "claim_receipts_unclear"}
# Issues statements.check_statement adds to bank lines, and file_dates.check_file_date to a document; derived too,
# so checking again replaces them.
STATEMENT_ISSUES = {"statement_gap", "statement_total", "file_date"}
_DERIVED = {"unknown_account", "same_account", "non_gbp_currency", "vat_not_applicable", "vat_estimated",
            "vat_arithmetic", "vat_rate_mismatch", "date_missing", "date_out_of_period", "unusual_direction",
            "not_booked", "vat_blocked", "vat_half_blocked", "under_capitalisation", "director_loan", "wages_from_bank",
            "payroll_owed_to", "before_first_year", "vat_not_booked", "needs_document", "total_worked_out",
            "cis_deducted", "personal", "for_the_trade", "possible_duplicate", "booked_without_document", "card_credit", "vat_unclaimed",
            "on_account", "no_vat_number", "vat_over_rate", "reverse_charge", "before_vat_registration", "small_asset",
            "meal_check", "meal_recoded", "claim_note", "sundry_check", "account_fact", "account_choice", "left_small", "left_unset", "meal_decided", "small_items_add_up", "future_date", "journal_note", "prepayment", "unusual_account", "asset_check",
            "should_be_asset", "whose_account", "vat_confirmed", "vat_implied", "document_wanted", "hotel_vat"} | MATCHING_ISSUES | STATEMENT_ISSUES
# Warnings that are a matter of judgement: a person who has looked can say one is fine (Transaction.accepted), and it
# is not raised on that row again.
ACCEPTABLE = frozenset({"no_vat_number", "vat_over_rate", "small_asset", "meal_check", "sundry_check", "account_fact", "account_choice", "small_items_add_up", "addressed_to", "future_date",
                        "file_date", "unusual_account", "asset_check", "should_be_asset", "whose_account",
                        "claim_vat", "document_wanted", "hotel_vat"})
# Words that say a cost was paid for time ahead, and the accounts whose bills usually are (insurance).
# Fares that carry no VAT whoever sells them (passenger transport is zero-rated): a ticket seller prints its VAT
# number for its own booking fee, which says nothing about the fare.
_FARES = re.compile(r"\b(train(line)?s?|rail(way|card)?|lner|avanti|gwr|scotrail|eurostar|flights?|airways|airlines?|"
                    r"airfare|air travel|easyjet|ryanair|jet2|tfl|transport for london|underground|tube|oyster|bus|"
                    r"coach|megabus|national express|stagecoach|ferry|tram)\b", re.IGNORECASE)


def is_fare(tx: Transaction) -> bool:
    """Whether the row is a fare, by who was paid and what for: a flight, a train, bus, coach, tram or ferry ticket,
    at home or abroad. Passenger transport is zero-rated, so there is never VAT on it to reclaim."""
    return bool(_FARES.search(f"{tx.counterparty or ''} {tx.description}"))


IMPLIED_LIMIT = Decimal("250.00")   # up to this a receipt needn't print its VAT: its total and the rate give it


def _vat_in_total(tx: Transaction, settings: BusinessSettings) -> bool:
    """Whether a purchase's document shows VAT is in its amount without printing how much: it prints the supplier's
    VAT number, or says VAT is charged or included (vat_stated), and shows no VAT amount. Up to £250 such a receipt is
    a VAT invoice in its own right: its total and the rate give the VAT. Not when the document says it is not a VAT
    invoice, on an account that carries no VAT or can't reclaim it, on a fare (zero-rated), or on a bank line or a
    claim line, which print neither."""
    account = BY_CODE.get(tx.account_code)
    return (tx.direction == Direction.OUT and tx.document_type in ("receipt", "invoice")
            and tx.vat is None and not tx.not_vat_invoice
            and (tx.supplier_vat_number is not None or tx.vat_stated)
            and ZERO < tx.gross <= IMPLIED_LIMIT and tx.currency == "GBP"
            and reclaims_vat(tx, settings) and account is not None
            and account.vat in (VatTreatment.STANDARD, VatTreatment.REDUCED)
            and not is_fare(tx))


def _shows_vat(tx: Transaction) -> str:
    """How a document _vat_in_total holds for shows that VAT is in its amount."""
    return "prints the supplier's VAT number" if tx.supplier_vat_number is not None else "says VAT is included"


def vat_implied(tx: Transaction, settings: BusinessSettings) -> bool:
    """Whether a purchase's VAT is worked out of its amount at the account's rate with nobody asked: its document gives
    the VAT by its total and rate (_vat_in_total), nobody chose a VAT treatment, and the row doesn't hold items of
    different kinds, which may be at different rates."""
    return (tx.vat_treatment is None and not any(i.code == "mixed_items" for i in tx.issues)
            and _vat_in_total(tx, settings))


def hotel_vat(tx: Transaction, settings: BusinessSettings) -> bool:
    """Whether a hotel stay's VAT is booked and reclaimed before the property's VAT invoice is in, the row asking for
    it (hotel_vat). The accountant's ruling (2026-11-18): "if the VAT is obvious add it, and then you can get the
    invoice"; a stay in the UK carries 20% VAT, and a booking site's receipt or confirmation isn't the property's VAT
    invoice. A receipt for money out on Hotels, in pounds, not abroad, on a day the business is registered, that a
    person hasn't booked without its invoice (without_document), and that either prints no VAT amount (worked out at
    20%; none chosen by a person, and not a VAT invoice already: vat_implied) or prints its VAT on a stay over £250,
    which only the property's full VAT invoice backs. Not the property's own invoice, which prints no VAT only when it
    charged none."""
    if not (tx.direction == Direction.OUT and tx.account_code == HOTELS and tx.document_type == "receipt"
            and tx.currency == "GBP" and not tx.abroad and not tx.reverse_charge and not tx.without_document
            and ZERO < tx.gross and reclaims_vat(tx, settings)):
        return False
    if tx.vat is None:
        return tx.vat_treatment is None and not vat_implied(tx, settings)
    return tx.vat > 0 and tx.gross > IMPLIED_LIMIT


_AHEAD = re.compile(r"\b(annual|yearly|12[- ]months?|per annum|in advance|quarter(ly)? rent)\b", re.IGNORECASE)
_PAID_AHEAD = frozenset({"8204", "7303"})
# Questions whose answer changes the VAT or tax: asked at any amount, and they hold up closing the year (books.close).
FACT_QUESTIONS = frozenset({"meal_check", "account_fact"})
# Presentation questions: found here, asked or left by the client's materiality after matching (materiality.decide).
PRESENTATION = frozenset({"sundry_check", "account_choice", "small_asset", "asset_check", "prepayment"})
SUBSISTENCE, ENTERTAINMENT, STAFF_WELFARE, REFRESHMENTS, SUNDRY = "7406", "7403", "8206", "8205", "8207"
_FOOD_AND_DRINK = frozenset({SUBSISTENCE, ENTERTAINMENT, STAFF_WELFARE, REFRESHMENTS})
# Who a meal or drink was for, in the row's own words: staff alone reclaim its VAT (Staff Welfare), guests block it.
_STAFF = re.compile(r"\b(teams?|staff|employees?|colleagues?|(christmas|xmas|office|works?) (party|do)|away ?day)\b",
                    re.IGNORECASE)
_GUESTS = re.compile(r"\b(clients?|customers?|guests?|prospects?|suppliers?|visitors?)\b", re.IGNORECASE)
# A claim note that says guests were there, not only that a guest word is in it ("lunch at client site" is where).
# Groceries or provisions from a food shop, by what was bought or who sold it: the buyer's own food while working.
# Nobody entertains a client or treats staff with a shop's groceries, so who was there needs no asking.
_PROVISIONS = re.compile(r"\b(grocer(y|ies|s)?|supermarkets?|convenience (store|shop)|food (shop|store|and wine)|"
                         r"provisions|meal deal|tesco|sainsbury'?s|asda|morrisons|aldi|lidl|co-?op|waitrose|spar|"
                         r"budgens|londis|nisa|one stop|iceland|m&s food|marks (&|and) spencer food)\b", re.IGNORECASE)
_WITH_GUESTS = re.compile(r"\b(with|for|and|entertaining|hosting|treating)\b(\W+\w+){0,3}?\W+(clients?|customers?|guests?|"
                          r"prospects?|suppliers?|visitors?)\b", re.IGNORECASE)


# Food or drink for the workplace, in the row's words: "for the office", "office kitchen", "for the team".
_WORKPLACE = re.compile(r"\b(office|kitchen|workplace|studio)\b", re.IGNORECASE)


def _staff_food_unshown(tx: Transaction) -> bool:
    """Whether food or drink the reader put on Refreshments or Staff Welfare has nothing on it (its words, its claim
    note) saying it was for the staff or the workplace: then it is the buyer's own while working, Subsistence. Only
    such a note or remark makes it staff welfare; guests named are the meal check's to ask, and a person's choice of
    account stands."""
    words = f"{tx.description or ''} {tx.claim_note or ''}"
    food = tx.bought is not None or tx.people is not None or _groceries(tx)
    return (tx.direction == Direction.OUT and tx.document_type in ("receipt", "invoice", "expense_claim")
            and tx.account_code in (REFRESHMENTS, STAFF_WELFARE) and food and not tx.account_chosen
            and not (_STAFF.search(words) or _WORKPLACE.search(words) or _GUESTS.search(words)))


def account_by_note(tx: Transaction) -> Optional[str]:
    """The account a receipt's claim note puts a meal or drink on: Staff Welfare when it names staff alone,
    Entertainment when it names any guest; None when the row is not food or drink, or the note names neither."""
    if tx.account_code not in _FOOD_AND_DRINK or not tx.claim_note or tx.account_chosen:
        return None
    if _GUESTS.search(tx.claim_note):   # guests named: Entertainment only when the note says they were there
        return ENTERTAINMENT if _WITH_GUESTS.search(tx.claim_note) else None
    return STAFF_WELFARE if _STAFF.search(tx.claim_note) else None


_TAX_WORDS = {"allowable": "an allowable cost", "disallowable": "not allowed for tax",
              "check": "partly allowed for tax, depending on the facts", "non_trading": "outside trading profit"}
_OWNERS = frozenset({*OWNER_DRAWINGS, *DIRECTORS_LOANS})


def what_differs(tx: Transaction, other: Account) -> Optional[str]:
    """What changes the tax or VAT between the row's account and `other`, in plain words, or None when only the
    name differs, or cost against asset with the same tax (a presentation choice, by the client's materiality)."""
    own = BY_CODE.get(tx.account_code)
    if own is None or own.code == other.code:
        return None
    said = []
    profit_and_loss = (AccountType.INCOME, AccountType.EXPENSE)
    if (own.code in _OWNERS) != (other.code in _OWNERS):
        said.append("one is the owner's own, not the business's cost")
    elif {own.type, other.type} == {AccountType.INCOME, AccountType.LIABILITY}:
        said.append("one is income, the other money owed back")
    elif (own.type in profit_and_loss) != (other.type in profit_and_loss) and not (
            {own.type, other.type} == {AccountType.EXPENSE, AccountType.ASSET}
            and (own.code.startswith("00") or other.code.startswith("00"))):
        said.append("one changes the profit, the other doesn't")   # cost or fixed asset: presentation
    if own.tax and other.tax and own.tax != other.tax:
        said.append(f"{own.name} is {_TAX_WORDS[own.tax.value]}, {other.name} {_TAX_WORDS[other.tax.value]}")
    if tx.vat and own.reclaim_vat != other.reclaim_vat:
        keeps = own.name if own.reclaim_vat else other.name
        said.append(f"the VAT can be reclaimed on {keeps} only")
    return "; ".join(said) or None


def _account_facts(tx: Transaction) -> list[str]:
    """The questions the reader's other accounts raise: one per account whose tax or VAT differs from the row's,
    except between meal accounts, where the meal check asks who was there."""
    asked = []
    for code in tx.alternatives:
        other = BY_CODE.get(code)
        if other is None or {code, tx.account_code} <= _FOOD_AND_DRINK:
            continue
        if (difference := what_differs(tx, other)) is not None:
            asked.append(f"Could also be {other.code} {other.name}: {difference}. Which is it?")
    return asked


def _account_choices(tx: Transaction) -> list[str]:
    """The reader's other accounts that change only the name, not the tax or VAT: a presentation choice."""
    said = []
    for code in tx.alternatives:
        other = BY_CODE.get(code)
        if (other is not None and code != tx.account_code and what_differs(tx, other) is None
                and not (code.startswith("00") and tx.account_code in ASSET_CANDIDATES)):   # asset_check asks that
            said.append(f"Could also be {other.code} {other.name}: the tax and VAT are the same either way. Recode it "
                        "if that fits better.")
    return said


def _after_year_end(tx: Transaction, year_end: dt.date) -> Decimal:
    """The part of a year's bill dated tx.date that falls after the year end: gross x the days of its year's cover
    after the year end / 365."""
    if tx.date is None or tx.date > year_end:
        return ZERO
    try:
        ends = tx.date.replace(year=tx.date.year + 1) - dt.timedelta(days=1)
    except ValueError:   # 29 February
        ends = tx.date.replace(year=tx.date.year + 1, day=28)
    days = max(0, (ends - year_end).days)
    return (tx.gross * days / 365).quantize(PENNY)


def account_on_claim(tx: Transaction) -> Optional[str]:
    """The account a receipt on an expense claim goes to: the one its claim note names (account_by_note), else
    Subsistence for Refreshments, which on a claim is a buy while working away, not for the workplace; else None."""
    if (noted := account_by_note(tx)) is not None:
        return noted
    if tx.account_code == REFRESHMENTS and tx.claim_note is not None and not tx.account_chosen:
        return SUBSISTENCE
    return None


def _claim_words(tx: Transaction) -> Optional[str]:
    """The words of the claim a row is on: a receipt's claim note, or a claim line's own description; None when the
    row is not on an expense claim."""
    if tx.claim_note is not None:
        return tx.claim_note
    return tx.description or "" if tx.document_type == "expense_claim" else None


def _who_was_there(tx: Transaction) -> Optional[tuple[str, Optional[Decimal]]]:
    """The question a meal or drink's account raises about who it was for, and what is at stake when nothing points
    to guests (the amount, for materiality.decide to leave it under the trivial level); None when the evidence
    answers it. Who was there decides the VAT (staff only: reclaimed; any guest: blocked) and the tax (entertaining
    is disallowed). The claim note, the row's own words, what was bought and where (a food shop's groceries), or a
    receipt the reader says is one person's answer it, as an accountant reads them; otherwise it is asked."""
    if account_by_note(tx) == tx.account_code:   # the claim said who it was for, and it is booked so
        return None
    words = f"{tx.description or ''} {tx.claim_note or ''}"
    staff, guests = bool(_STAFF.search(words)), bool(_GUESTS.search(words))
    amount = f"£{tx.gross:,.2f}"
    if _groceries(tx) and _company_bought(tx) and not (staff or guests or _WORKPLACE.search(words)):
        # Asked at any amount: an owner's own shopping is theirs, not a cost (user's decision, 25 Nov 2026). Milk and
        # tea "for the studio" say whose they were.
        return (f"Groceries of {amount} paid by the business, not on anyone's expense claim: whose were they? An "
                "owner's own shopping is theirs (a director's loan, or the owner's drawings); for the workplace it is "
                "Refreshments or Staff Welfare (VAT reclaimed); bought on a business trip, Subsistence. Recode it."), None
    choices = ("for staff only it is Staff Welfare (VAT reclaimed); with clients or other guests it is Entertainment "
               "(VAT can't be reclaimed). Recode it if so.")
    if tx.account_code == SUBSISTENCE:
        if guests:
            return (f"A meal of {amount} on Subsistence: with clients or other guests it is entertainment, and its "
                    "VAT can't be reclaimed. Recode it to Entertainment if so."), None
        if staff:
            return (f"A meal of {amount} on Subsistence for staff: a staff-only meal is Staff Welfare. Recode it to "
                    "Staff Welfare if so."), None
        if _own_food(tx) is not None:   # what was bought, or how many it was for, says it was the buyer's own
            return None
        if tx.people == "several":
            return (f"A meal of {amount} on Subsistence, and the receipt looks to be for more than one person: "
                    f"{choices}"), tx.gross
        where = "the claim doesn't say" if _claim_words(tx) is not None else "nothing on it says"
        return f"A meal of {amount} on Subsistence, and {where} who it was for: {choices}", tx.gross
    if tx.account_code == ENTERTAINMENT and not guests:
        said = "says it was for staff" if staff else "doesn't say who was there"
        return (f"{amount} on Entertainment {said}: if only staff were there it is Staff Welfare, and its VAT can be "
                "reclaimed. Recode it to Staff Welfare if so."), None
    if tx.account_code == STAFF_WELFARE:
        if guests:
            return (f"{amount} on Staff Welfare mentions guests: with clients or other guests it is entertainment, and "
                    "its VAT can't be reclaimed. Recode it to Entertainment if so."), None
        if not staff and tx.people is not None:   # food or drink that doesn't say it was for staff
            return (f"{amount} of food or drink on Staff Welfare doesn't say it was for staff only: with clients or "
                    "other guests it is Entertainment (VAT can't be reclaimed). Recode it if so."), tx.gross
    return None


def _groceries(tx: Transaction) -> bool:
    """Whether the row is groceries from a food shop: as the reader says (bought), or, for a row read before the
    reader said, by the words of the row or the seller's name."""
    if tx.bought is not None:
        return tx.bought == "groceries"
    return bool(_PROVISIONS.search(f"{tx.counterparty or ''} {tx.description or ''}"))


# What a household shop's receipt shows and a lunch's doesn't: cleaning, raw food to cook, drink to take home.
_HOUSEHOLD = re.compile(r"\b(household|cleaning|detergent|toiletr\w*|washing|nappies|pet food|wine|beer|lager|"
                        r"spirits|vegetables|veg|meat|fish|pasta|rice|tins|cereal|eggs|milk)\b", re.IGNORECASE)


def _company_bought(tx: Transaction) -> bool:
    """Whether the company paid for a household shop itself (its card or bank), not someone claiming it back: then
    no claimant says whose it was. A deli's or bakery's food and drink, which the reader also calls groceries, is a
    lunch: the buyer's own while working, as before."""
    return (tx.document_type in ("receipt", "invoice") and tx.claimed_in is None and not tx.claim_note
            and bool(_HOUSEHOLD.search(f"{tx.description or ''}")))


def _own_food(tx: Transaction) -> Optional[str]:
    """Why food or drink was the buyer's own, as an accountant reads what was bought and for how many; None when
    that leaves open whether others had some. Groceries are the buyer's own whoever ate them (nobody entertains with
    a shop's groceries); so is one person's food or drink, and food or a drink to go not said to be for several."""
    if _groceries(tx):
        if _company_bought(tx):   # no claimant: whose they were is asked (_who_was_there)
            return None
        return ("Groceries from a food shop: the claimant's own food while working, on Subsistence. Nobody "
                "entertains clients or treats staff with a shop's groceries.")
    if tx.people == "one":
        return "The receipt is for one person: their own food or drink while working, on Subsistence."
    if tx.bought == "food_to_go" and tx.people != "several":
        return ("Food or a drink to go: the buyer's own while working, on Subsistence, unless something says others "
                "had some.")
    return None


def _meal_decided(tx: Transaction) -> Optional[str]:
    """Why a meal on Subsistence asks nothing about who was there, when what was bought or the receipt settles it."""
    if tx.account_code != SUBSISTENCE or account_by_note(tx) == tx.account_code:
        return None
    return _own_food(tx)


def issue(code: str, message: str, severity: str = "warning", related: Sequence[int] = (), *,
          about: str = "row", difference: Optional[Decimal] = None) -> Issue:
    return Issue(code=code, message=message, severity=severity, related=list(related), about=about,
                 difference=difference)


def long_date(date: dt.date) -> str:
    """9 Sep 2026, as messages write a date."""
    return f"{date.day} {date:%b %Y}"


def is_derived(found: Issue) -> bool:
    """An issue the ledger works out afresh on every pass; such issues are never saved."""
    return found.code in _DERIVED


_NOT_TRANSACTION_NAMES = {
    "quote": "a quote", "pro_forma": "a pro forma invoice", "purchase_order": "a purchase order",
    "remittance_advice": "a remittance advice", "supplier_statement": "a supplier's statement of account",
    "finance_agreement": "a finance or loan agreement",
    "other": "a document that is not a transaction",
}


def booked(tx: Transaction) -> bool:
    """A quote, a pro forma or another document that is not a transaction, or a copy of a document already in
    the table, or a row dated before the client's first year, whose amount is in the opening balances, is booked
    only when a person ticks Include. A card payment is booked from its receipt, which shows
    the VAT, and not again from the bank line; a claim line is booked from its receipt too, and as well only when a
    person ticks Include, as is a receipt its claim leaves off (left_off_claim): the claimant paid it.
    (matching.match finds copies and receipts.) A row a decision excluded or replaced
    is never booked, whatever else is true of it."""
    if tx.excluded or tx.superseded_by:
        return False
    if tx.recorded_by is not None or tx.left_off_claim is not None or tx.in_opening or payroll_summary(tx):
        return tx.include
    return tx.include or (tx.document_type not in NOT_TRANSACTIONS and tx.copy_of is None)


def payroll_summary(tx: Transaction) -> bool:
    """A payroll row on the account that holds what payroll owes (a P32 of what is due to HMRC, say): the payroll
    report books that, and the bank payment clears it, so booking this too would post the account to itself."""
    return tx.document_type == "payroll" and tx.account_code in PAYROLL_OWED


# Where a payroll report's rows are held until the bank pays them, by what each is owed to.
OWED_TO = {"net_pay": NET_WAGES, "paye_ni": PAYE, "pension": PENSION}
PAYROLL_OWED = frozenset(OWED_TO.values())


def other_side(tx: Transaction, settings: BusinessSettings) -> str:
    """The other side of a posting. A receipt or a bank line moved money through the bank: a bank line through the
    account or card its statement is for, anything else through the default bank. An invoice,
    a claim or an included document is owed until a bank line pays it: a sale to the customer's account
    (Debtors), anything else to the supplier's (Creditors), and a claim to the employee. What an agent
    collected and paid for the business is held by the agent (Debtors) until it pays over the net; what a payment
    processor holds (Stripe, PayPal, SumUp) in Payment Processor Clearing, as its payout is: the customers have paid."""
    if tx.document_type == "expense_claim":
        return STAFF_EXPENSES
    if tx.document_type == "write_off":   # what the customer owed comes off Debtors
        return DEBTORS
    if tx.document_type == "agent_statement":
        return CLEARING if processor(tx.agent) else DEBTORS
    if tx.document_type == "payroll":   # never the bank: the bank payment clears what is owed
        return OWED_TO.get(tx.owed_to) or {"7006": PAYE, "7007": PENSION}.get(tx.account_code, NET_WAGES)
    if tx.document_type == "invoice" or tx.document_type in NOT_TRANSACTIONS:
        account = BY_CODE.get(tx.account_code)
        return DEBTORS if account is not None and account.type == AccountType.INCOME else CREDITORS
    return tx.bank_account or settings.bank_account


def registered_on(settings: BusinessSettings, day: Optional[dt.date]) -> bool:
    """Whether the business was VAT registered on the day: registered, and the day not before its registration
    started (vat_from). A row with no date goes by the registration alone."""
    return settings.vat_registered and not (settings.vat_from and day and day < settings.vat_from)


def reclaims_vat(tx: Transaction, settings: BusinessSettings) -> bool:
    """Whether VAT on the row is booked when it is shown, as normalise books it: the business is VAT registered on
    its day, VAT applies to the account, and on a cost it can be reclaimed (not on business entertainment or a car)."""
    account = BY_CODE.get(tx.account_code)
    return (registered_on(settings, tx.date) and account is not None and account.type not in _NO_VAT
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


def most_vat(gross: Decimal) -> Decimal:
    """The most VAT a VAT-inclusive amount can hold: a sixth (20% of the net), plus a little
    because invoices round VAT line by line."""
    return vat_in_gross(gross, VatTreatment.STANDARD) + Decimal("0.05") + (gross / 500).quantize(PENNY)


# Exempt accounts whose supplier may still charge VAT: a landlord who opted to tax.
_MAY_OPT_TO_TAX = frozenset({"7100", "4904"})


def _carries_no_vat(account: Optional[Account]) -> bool:
    """Whether what is booked to the account is never charged VAT: zero-rated or outside the scope of VAT, or exempt
    (insurance, whose total adds Insurance Premium Tax, not VAT; bank charges), except rent."""
    return account is not None and (account.vat in (VatTreatment.ZERO, VatTreatment.OUTSIDE_SCOPE)
                                    or (account.vat == VatTreatment.EXEMPT and account.code not in _MAY_OPT_TO_TAX))


def _vat_not_booked(tx: Transaction, settings: BusinessSettings) -> Optional[Issue]:
    """A row read with no VAT whose document prints a total and a net that differ by VAT it could hold (above
    nothing, at most a sixth of the total): the reading missed the VAT line, so none is booked until it is added. Not
    on an account that carries no VAT (the difference is another tax). When the document doesn't print its total
    (total_worked_out), the VAT isn't shown either: it says so, and that a complete copy is needed."""
    if (tx.document_total is None or tx.document_net is None or not reclaims_vat(tx, settings)
            or _carries_no_vat(BY_CODE.get(tx.account_code))):
        return None
    shown = tx.document_total - tx.document_net
    if not ZERO < shown <= most_vat(tx.document_total):
        return None
    kind = tx.document_type.replace("_", " ")
    if tx.total_worked_out:
        return issue("vat_not_booked", f"The {kind} doesn't print its total: £{tx.document_total:,.2f} was worked out "
                                       f"from what it does print. Get a complete copy to reclaim the £{shown:,.2f} VAT.")
    return issue("vat_not_booked", f"The {kind} shows £{shown:,.2f} VAT; none is booked.")


_TREATMENT_WORDS = {VatTreatment.ZERO: "zero-rated", VatTreatment.EXEMPT: "exempt",
                    VatTreatment.OUTSIDE_SCOPE: "outside the scope of VAT"}


def normalise(tx: Transaction, settings: BusinessSettings) -> Transaction:
    kept = [i for i in tx.issues if i.code not in _DERIVED]   # re-validating must not duplicate
    issues: list[Issue] = []
    if _staff_food_unshown(tx):
        was = BY_CODE[tx.account_code].name
        tx = tx.model_copy(update={"account_code": SUBSISTENCE})
        issues.append(issue("meal_recoded", f"Booked to Subsistence, not {was}: nothing on it says it was for the "
                                            "staff. If it was, change the account.", "info"))
    elif tx.account_code == SUBSISTENCE and not tx.account_chosen:   # checked again (matching does): still so
        issues += [i for i in tx.issues if i.code == "meal_recoded"]
    account = BY_CODE.get(tx.account_code)
    # The client's banks and the accounts for what is owed are worked out afresh on every pass, so a row whose
    # account, document type or bank account changes moves with it; any other account sent in is kept.
    worked_out = {None, settings.bank_account, *settings.bank_accounts, DEBTORS, CREDITORS, STAFF_EXPENSES}
    if tx.document_type == "receipt":
        worked_out.add(SUSPENSE)   # where matching parks a receipt its bank's statement doesn't show: looked at again
    # A payroll row is held on 2220, 2210 or 2230 until the bank pays it, by what it is owed to, whatever contra was
    # saved; with no owed_to the account guesses, and says so on every pass.
    payroll = tx.document_type == "payroll"
    payroll_default = payroll and tx.owed_to is None
    journal = tx.document_type == "journal"   # both its accounts are the person's, whatever they are
    contra = (tx.contra_account_code if journal else
              other_side(tx, settings) if payroll or tx.contra_account_code in worked_out
              else tx.contra_account_code)
    if payroll_default:
        issues.append(issue("payroll_owed_to", f"Check what this payroll line is owed to: booked to "
                                               f"{BY_CODE[contra].name} for now."))
    if account is None:
        issues.append(issue("unknown_account", "This account isn't in the chart.", "error"))
    if contra not in BY_CODE:
        issues.append(issue("unknown_account", "Its other account isn't in the chart.", "error"))
    if contra == tx.account_code and not (payroll_summary(tx) and not tx.include):
        issues.append(issue("same_account", "Posts to and from the same account.", "error"))
    if tx.currency != "GBP":
        issues.append(issue("non_gbp_currency", f"Read as {tx.currency} {tx.gross:,.2f}. Edit the row and enter the "
                                                "amount in pounds, as the bank or card statement shows it. On goods "
                                                "from abroad the VAT is import VAT, on the import VAT statement and "
                                                "not on this invoice.", "error"))

    # Works from the inputs every time (vat as shown, vat_treatment as chosen) and never writes
    # them back, so a re-coded or corrected row gets its VAT worked out afresh.
    treatment = tx.vat_treatment or (account.vat if account else VatTreatment.OUTSIDE_SCOPE)
    vat = tx.vat
    posted: Optional[Decimal] = vat
    # The reading's own warning that the document's items were kept as one row: said once, with what its VAT says.
    mixed = any(i.code == "mixed_items" for i in kept)
    untaxed: Optional[tuple[Decimal, Decimal]] = None
    registered = registered_on(settings, tx.date)
    if tx.document_type == "write_off" or tx.recovers:
        # A bad debt's VAT: the relief a write-off claims back, or the share of it a recovery pays over again. Only a
        # client registered for VAT when it happened paid that VAT over, so only one has it to claim.
        posted = (vat or ZERO) if registered else ZERO
    elif not registered or journal:
        if vat and settings.vat_registered and not journal:
            issues.append(issue("before_vat_registration", (
                f"Dated before the VAT registration started on {long_date(settings.vat_from)}: its £{vat:,.2f} VAT is "
                "not booked. VAT on goods still held, and on services of the six months before, can be reclaimed on "
                "the first return: add it by journal if so."), "info"))
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
    elif tx.vat_treatment in (VatTreatment.ZERO, VatTreatment.EXEMPT, VatTreatment.OUTSIDE_SCOPE):
        # A person said no VAT applies (zero-rated, exempt, or outside the scope, as a reverse charge is): none booked.
        if vat:
            issues.append(issue("vat_not_applicable", f"Marked {_TREATMENT_WORDS[tx.vat_treatment]}: the £{vat} VAT "
                                                      "shown is not booked.", "info"))
        posted = ZERO
    elif vat is None and tx.vat_treatment is None:
        posted = ZERO   # VAT is reclaimable only when charged: none shown, none booked
        missed = _vat_not_booked(tx, settings)
        if missed:
            issues.append(missed)
        elif vat_implied(tx, settings):
            # The document shows VAT is in the amount (a VAT number, or it says so) but not how much: worked out.
            posted = vat_in_gross(tx.gross, treatment)
            issues.append(issue("vat_implied", (
                f"VAT £{posted:,.2f} worked out at the {treatment.value} rate: the {tx.document_type} {_shows_vat(tx)} "
                "but not the VAT amount. If part of it carries no VAT, enter the VAT it does carry."), "info"))
        elif hotel_vat(tx, settings):
            # A hotel stay in the UK whose receipt isn't the property's VAT invoice: the VAT is plain, so it is booked
            # now and the VAT invoice asked for (the accountant's ruling).
            posted = vat_in_gross(tx.gross, treatment)
            why = ("the receipt says VAT is included but isn't a VAT invoice" if tx.vat_stated
                   else "a hotel stay in the UK carries VAT, but the receipt isn't a VAT invoice")
            issues.append(issue("hotel_vat", f"VAT £{posted:,.2f} booked at 20%: {why}. Get the VAT invoice from the "
                                             "property."))
    elif vat is None:   # a person chose the rate: split the VAT out of the gross at that rate
        posted = vat_in_gross(tx.gross, treatment)
        if posted > 0 and _vat_in_total(tx, settings):
            # A VAT invoice up to £250 with no VAT amount: the total and the rate the person chose give its VAT, so
            # their choice is the answer, not an estimate to check against the document again.
            issues.append(issue("vat_implied", (
                f"VAT £{posted:,.2f} worked out at the {treatment.value} rate you chose: the {tx.document_type} "
                f"{_shows_vat(tx)} but not the VAT amount."), "info"))
        elif posted > 0:
            issues.append(issue("vat_estimated", f"£{posted} estimated at the {treatment.value} rate. Check the invoice."))
    elif most_vat(tx.gross) < vat <= tx.gross / 5:
        # More than 20% of the net paid, yet no more than a fifth of what was paid: a voucher or a promotion taken off
        # after the VAT. The VAT the document shows is the VAT charged, so it is booked, and said.
        issues.append(issue("vat_over_rate", f"VAT £{vat:,.2f} is more than 20% of the £{tx.gross - vat:,.2f} left of "
                                              f"£{tx.gross:,.2f}: a voucher or promotion taken off after VAT? Booked "
                                              "as the document shows it. Check it against the document."))
    elif vat < 0 or vat >= tx.gross or vat > most_vat(tx.gross):
        issues.append(issue("vat_arithmetic", f"VAT £{vat:,.2f} is impossible on £{tx.gross:,.2f}; at 20% it would be "
                                               f"£{vat_in_gross(tx.gross, VatTreatment.STANDARD):,.2f}.", "error"))
        posted = None
    elif (treatment in (VatTreatment.STANDARD, VatTreatment.REDUCED) and vat != 0   # 0.00: none charged
          and all(abs(vat - vat_in_gross(tx.gross, rate)) > Decimal("0.02")    # 5% is charged on energy too
                  for rate in (treatment, VatTreatment.REDUCED))):
        untaxed = _untaxed_part(vat, tx.gross) if treatment == VatTreatment.STANDARD else None
        if not mixed:
            issues.append(issue("vat_rate_mismatch", (
                f"£{vat} is 20% VAT on £{untaxed[0]}; £{untaxed[1]} has no VAT (zero-rated or exempt items, a tip or a "
                "service charge?)." if untaxed
                else f"£{vat} isn't {treatment.value}-rate VAT on £{tx.gross}."), "info"))
    if (posted and account is not None and account.code in HALF_VAT_RECLAIMED and tx.direction == Direction.OUT
            and tx.vat_treatment is None):
        # A car lease: only half its VAT can be reclaimed; the other half stays in the cost. A van's can all be.
        half = (posted / 2).quantize(PENNY, rounding=ROUND_HALF_UP)
        issues.append(issue("vat_half_blocked", f"Half the £{posted:,.2f} VAT reclaimed (£{half:,.2f}), as on a car lease: "
                                                "the rest stays in the cost. If it is a van or another commercial "
                                                "vehicle, all of it can be: choose its VAT rate.", "info"))
        posted = half
    if vat and posted and hotel_vat(tx, settings):
        # A UK hotel stay over £250 whose receipt prints its VAT: booked now, the property's full VAT invoice asked for.
        issues.append(issue("hotel_vat", f"VAT £{posted:,.2f} booked as the receipt shows it, but a stay over £250 needs "
                                         "the property's full VAT invoice. Get the VAT invoice from the property."))
    if mixed:
        kept = [i for i in kept if i.code != "mixed_items"]
        issues.append(_mixed_items(account, vat, tx.gross, untaxed))
    if tx.total_worked_out and not any(i.code == "vat_not_booked" for i in issues):
        issues.append(issue("total_worked_out", f"The {tx.document_type.replace('_', ' ')} doesn't print "
                                                f"£{tx.gross:,.2f}: it was worked out from what it does print. Check it "
                                                "against the document."))

    in_opening = bool(settings.books_start and tx.date and tx.date < settings.books_start)
    if tx.date is None:
        issues.append(issue("date_missing", "This row has no date: add one, so it can be placed in a year."))
    elif in_opening:
        if not tx.include:
            issues.append(issue("before_first_year", "Dated before the first year: already in the opening balances, "
                                                     "so not booked. Tick Include to book it."))
    elif ((settings.period_start and tx.date < settings.period_start)
          or (settings.period_end and tx.date > settings.period_end)):
        issues.append(issue("date_out_of_period", f"{tx.date} is outside the accounting period."))
    document = tx.document_type == "invoice"
    if journal:
        pass   # a journal's sides are debit and credit, not money in or out
    elif account is not None and tx.direction == Direction.IN and account.type == AccountType.EXPENSE:
        issues.append(issue("unusual_direction", (
            f"A supplier's credit note: it takes the amount off {account.name}. Check that is the account its "
            "invoice is on." if document else f"Money in on {account.name}: a refund?"), "info"))
    if not journal and account is not None and tx.direction == Direction.OUT and account.type == AccountType.INCOME:
        issues.append(issue("unusual_direction", (
            f"A credit note to a customer: it takes the amount off {account.name}." if document
            else f"Money out on {account.name}: a customer refund?"), "info"))
    if (settings.business_type == "limited_company" and account is not None
            and tx.account_code in (*CAPITALS, *OWNER_DRAWINGS, *MEMBERS_CURRENT)):
        issues.append(issue("director_loan", f"Use Director's Loan Account, not {account.name}, for a limited "
                                             "company."))
    elif (settings.business_type not in (None, "limited_company") and account is not None
          and tx.account_code in (*DIRECTORS_LOANS, SHARES, DIVIDENDS)):
        issues.append(issue("director_loan", f"{account.name} is for companies only. Use Drawings or "
                                             "Capital Introduced."))
    elif (len(settings.owners) > 1 and account is not None and tx.method != "user"
          and tx.account_code in owner_codes(settings.business_type, settings.owners)
          and "whose_account" not in tx.accepted):
        # Read from a document, it went to the first owner's account: the papers seldom say which of them it was.
        word = OWNER_WORDS[settings.business_type]
        issues.append(issue("whose_account", f"This business has {len(settings.owners)} {word}s: booked to "
                                             f"{account.name}. Check whose it is, and recode it if it is another "
                                             f"{word}'s."))
    drawn = owner_slots(settings.business_type)["drawings"]
    service = (personal(tx.counterparty, tx.description, business_type=settings.business_type)
               if tx.account_code in (*DIRECTORS_LOANS, *OWNER_DRAWINGS, *drawn) else None)
    if service and tx.direction == Direction.OUT and account is not None:
        issues.append(issue("personal", f"{service} looks like personal spending: booked to the {account.name}. "
                                        "Recode it if it was for the business.", "info"))
    elif (tx.direction == Direction.OUT and account is not None and account.type == AccountType.EXPENSE
          and media_business(settings.nature_of_business, settings.sic_code)
          and (for_work := consumer_service(tx.counterparty, tx.description))):
        what = settings.nature_of_business or f"SIC {settings.sic_code}"
        issues.append(issue("for_the_trade", f"{for_work} kept as a business cost on {account.name}: the business is "
                                             f"{what}, so it may be for its work. If it is someone's own, recode it "
                                             "to their account.", "info"))
    if (tx.document_type == "statement" and tx.direction == Direction.IN and tx.bank_account in CARDS
            and account is not None and account.type == AccountType.INCOME):
        issues.append(issue("card_credit", f"Money in on a card is a payment to the card or a refund, not a sale: "
                                           f"booked to {account.name}. Recode it to the bank account that paid the "
                                           "card, or to the cost refunded."))
    if tx.document_type == "statement" and tx.direction == Direction.IN and tx.account_code == DEBTORS and not tx.pays:
        issues.append(issue("on_account", "A payment on account: held on Debtors as a credit to the customer until its "
                                          "invoice is added. Link it to the invoice then, or recode it to Sales if "
                                          "there will be none.", "info"))
    if tx.document_type == "statement" and tx.account_code in WAGES:
        issues.append(issue("wages_from_bank", "Book wages from the payroll report: code net pay to 2220 Net Wages."))
    if payroll_summary(tx) and not tx.include:
        issues.append(issue("not_booked", f"A summary of what is already owed on {account.name}: not booked. The "
                                          "payroll report books it and the bank payment clears it. Tick Include to "
                                          "book it.", "info"))
    if tx.document_type in NOT_TRANSACTIONS and not tx.include:   # copies and card payments: matching says so
        issues.append(issue("not_booked", (
            "A finance or loan agreement: not booked. The money it lent and its repayments are booked from the bank "
            "lines, on the loan or hire purchase account; add what it financed, and its interest, by journal."
            if tx.document_type == "finance_agreement" else
            f"Looks like {_NOT_TRANSACTION_NAMES[tx.document_type]}: not booked. Tick Include to book it."), "info"))
    purchase = (not journal and tx.direction == Direction.OUT and tx.document_type in ("receipt", "invoice")
                and account is not None)
    if (purchase and tx.document_type == "invoice" and posted and tx.supplier_vat_number is None
            and tx.method != "user" and not tx.not_vat_invoice and tx.vat_treatment is None):
        issues.append(issue("no_vat_number", f"No VAT registration number was read on this invoice, and without one "
                                             f"it is not a valid VAT invoice: check it before the £{posted:,.2f} VAT "
                                             "is reclaimed. If it shows none, set its VAT to none in Edit, or ask the "
                                             "supplier for a VAT invoice."))
    reverse: Optional[Decimal] = None
    if tx.reverse_charge and purchase and registered and account.type not in _NO_VAT:
        if posted:
            issues.append(issue("reverse_charge", f"Marked as a reverse charge, but the document charges £{posted:,.2f} "
                                                  "VAT: booked as charged. Untick Reverse charge in Edit, or take the "
                                                  "VAT off the row."))
        elif posted is not None and account.reclaim_vat and tx.vat_treatment not in (
                VatTreatment.ZERO, VatTreatment.EXEMPT) and account.vat == VatTreatment.STANDARD:
            reverse = (tx.gross / 5).quantize(PENNY)
            issues.append(issue("reverse_charge", f"Reverse charge: a service from abroad with no VAT charged. "
                                                  f"£{reverse:,.2f} VAT is added to box 1 and reclaimed in box 4, so "
                                                  "nothing is paid. If these are goods, untick Reverse charge in "
                                                  "Edit: import VAT is on the import VAT statement.", "info"))
    small = SMALL_EQUIPMENT_COST.get(account.code) if account is not None else None
    if (purchase and small and settings.capitalise_from and not tx.account_chosen and posted is not None
            and tx.gross - posted < settings.capitalise_from):
        # Under the client's capitalisation policy: a cost, as its accounts treat it, not equipment kept as an asset.
        cost = BY_CODE[small]
        issues.append(issue("under_capitalisation", f"£{tx.gross - posted:,.2f} net is under this client's "
                                                    f"£{settings.capitalise_from:,.0f} capitalisation threshold: booked "
                                                    f"to {cost.name} as a cost, not kept as {account.name}. Change the "
                                                    "account to keep it as an asset.", "info"))
        account = cost
    whole = max(tx.gross, tx.document_total or ZERO)   # the purchase it is part of
    if (purchase and account.type == AccountType.ASSET and account.code.startswith("00") and not settings.capitalise_from
            and account.vat != VatTreatment.OUTSIDE_SCOPE):   # with a capitalisation policy, the policy decides
        issues.append(issue("small_asset", f"£{tx.gross:,.2f} is small to keep as {account.name} for this client: "
                                           "write it off as a cost. Recode it to the cost account of its kind, unless "
                                           "it is part of a bigger purchase.", difference=whole))
    if (purchase and not mixed and tx.account_code in ASSET_CANDIDATES and tx.currency == "GBP"
            and any(a.startswith("00") for a in tx.alternatives)):   # the reader thought it could be equipment kept
        # An amount in another currency isn't pounds yet: it is checked once a person has converted it.
        issues.append(issue("asset_check", f"£{tx.gross:,.2f} on {account.code} {account.name} may be equipment to "
                                           "keep as an asset.", "info", difference=tx.gross))   # by its own line
    if (not journal and tx.direction == Direction.OUT and tx.document_type in ("receipt", "invoice", "expense_claim")
            and tx.account_code in _FOOD_AND_DRINK):
        if (asked := _who_was_there(tx)) is not None:
            issues.append(issue("meal_check", asked[0], difference=asked[1]))
        elif (why := _meal_decided(tx)) is not None:
            issues.append(issue("meal_decided", why, "info"))
    if not journal and tx.document_type != "statement":
        issues.extend(issue("account_fact", asked) for asked in _account_facts(tx))
    if not journal and tx.direction == Direction.OUT and tx.document_type in ("receipt", "invoice", "expense_claim"):
        if account is not None and account_by_note(tx) == tx.account_code:
            issues.append(issue("claim_note", f"Booked to {account.name}: the claim says “{tx.claim_note}”.", "info"))
        if tx.account_code == SUNDRY:
            issues.append(issue("sundry_check", f"£{tx.gross:,.2f} on Sundry Expenses, the account for what fits no "
                                                "other: what was it for? Recode it if another account fits.",
                                difference=tx.gross))
    if not journal and tx.document_type != "statement":
        issues.extend(issue("account_choice", asked, difference=tx.gross) for asked in _account_choices(tx))
    if journal:   # a journal is the person's own entry: it books, and says what it leaves out of step
        sides = {tx.account_code, contra}
        if sides & set(settings.bank_accounts):
            issues.append(issue("journal_note", "A journal on a bank account: the bank only agrees with its statement "
                                                "if no statement line shows the same money.", "info"))
        if sides & {SALES_VAT, PURCHASE_VAT}:
            issues.append(issue("journal_note", "A journal on a VAT account is not in the VAT figures, which are "
                                                "worked from documents: adjust the return for it by hand.", "info"))
        if sides & {DEBTORS, CREDITORS}:
            issues.append(issue("journal_note", "A journal on Debtors or Creditors is not on the Invoices page, so "
                                                "the account and the unpaid list differ by it.", "info"))
    elif (tx.direction == Direction.OUT and account is not None and account.type == AccountType.EXPENSE
          and tx.document_type in ("receipt", "invoice") and settings.period_end is not None
          and (_AHEAD.search(tx.description) or tx.account_code in _PAID_AHEAD)
          and (after := _after_year_end(tx, settings.period_end)) > 0):
        issues.append(issue("prepayment", f"May cover time after the year end ({long_date(settings.period_end)}): "
                                          f"£{after:,.2f} of it, if it is a year's cover from its date. If so, carry "
                                          "that part forward with a journal to 1103 Prepayments.", "info",
                            difference=after))
    issues = [i for i in issues if i.code not in tx.accepted]
    presentation = [i for i in issues if i.code in PRESENTATION]
    issues = [i for i in issues if i.code not in PRESENTATION]
    net = tx.gross - posted if posted is not None else None
    cis = tx.cis_deducted if tx.cis_deducted and tx.document_type != "statement" else None
    if cis is not None and net is not None:
        net += cis   # the sale or cost is the amount due plus the tax the contractor withheld for HMRC
        issues.append(issue("cis_deducted", (
            f"CIS £{cis:,.2f} taken off by the customer: booked to CIS Deducted, so the sale is £{net:,.2f}."
            if tx.direction == Direction.IN else
            f"CIS £{cis:,.2f} taken off for HMRC: booked to CIS Payable, so the cost is £{net:,.2f}."), "info"))
    return tx.model_copy(update={"vat_posted": posted, "net": net, "reverse_vat": reverse, "presentation": presentation,
                                 "contra_account_code": contra, "account_code": account.code if account else tx.account_code,
                                 "in_opening": in_opening, "issues": kept + issues})
