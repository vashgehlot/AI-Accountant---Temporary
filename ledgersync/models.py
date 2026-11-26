"""API and ledger models. Money is Decimal inside and a string in JSON ("12.50")."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal
from enum import Enum
from typing import Literal, Optional, get_args

from pydantic import BaseModel, Field, computed_field, field_validator

from .accounts import BANK, BY_CODE
from .money import VatTreatment, ZERO, to_money


class Direction(str, Enum):
    IN = "in"      # money into the bank
    OUT = "out"    # money out of the bank


# The kind of document a row comes from. "agent_statement" is a letting or managing agent's statement: what
# it collected and paid for the business, and the net it paid over. "payroll" is a payroll report: the wages the
# business owes for a pay date. The last seven are not transactions: a person ticks Include to book one as an
# invoice. "finance_agreement" is a hire purchase, lease or loan agreement, whose money the bank lines show.
# "other" is what the adapter makes of a type it does not know.
# "journal" is an entry a person makes between two accounts (depreciation, an accrual, a tax charge): money out
# debits its account and credits its contra account, with no VAT and no document.
DocumentType = Literal["receipt", "invoice", "expense_claim", "statement", "agent_statement", "payroll", "journal",
                       "write_off", "quote", "pro_forma", "purchase_order", "remittance_advice", "supplier_statement",
                       "finance_agreement", "other"]
DOCUMENT_TYPES: tuple[str, ...] = get_args(DocumentType)
NOT_TRANSACTIONS = frozenset(DOCUMENT_TYPES[8:])   # after "write_off": quote, pro forma and the rest

# The kind of business a client is: a limited company's owners go through 2250 Director's Loan Account,
# anyone else's through 3260 Drawings and 3010 Capital Introduced.
# Food or drink, by what was bought: a shop's groceries, food or a drink to go (a coffee, a sandwich, a meal deal),
# a sit-down meal, drinks at a pub or bar, or food ordered for a group (platters, a buffet, a hospitality order).
Bought = Literal["groceries", "food_to_go", "meal_out", "drinks_out", "catering"]
BOUGHT = ("groceries", "food_to_go", "meal_out", "drinks_out", "catering")
BusinessType = Literal["limited_company", "sole_trader", "partnership", "llp"]
BUSINESS_TYPES: tuple[str, ...] = get_args(BusinessType)

# The kinds of account money moves through: each of a client's has its own code, from accounts.BANK_SLOTS.
BankAccountKind = Literal["current", "savings", "credit_card", "petty_cash"]


class BankAccount(BaseModel):
    """One of a client's bank accounts or cards: its name, its kind, and its code in the chart ("" until
    ledger.assign_codes gives it the next free one of its kind)."""
    code: str = ""
    name: str
    kind: BankAccountKind

    @field_validator("code", "name", mode="before")
    @classmethod
    def _trimmed(cls, value):
        return "" if value is None else str(value).strip()


class Owner(BaseModel):
    """One of a client's directors, partners or LLP members: their name, their share of the profit in percent (a
    partner's or member's), and their slot among the chart's owners' accounts (accounts.owner_slots; None until
    ledger.assign_owners gives them the next free one)."""
    slot: Optional[int] = None
    name: str
    share: Optional[Decimal] = None

    @field_validator("name", mode="before")
    @classmethod
    def _trimmed(cls, value):
        return "" if value is None else str(value).strip()

    @field_validator("share", mode="before")
    @classmethod
    def _empty_share(cls, value):
        return None if value == "" else value


class Issue(BaseModel):
    code: str
    message: str
    severity: Literal["info", "warning", "error"]
    related: list[int] = Field(default_factory=list)   # the other rows it is about (Show both): places in the rows
                                                       # matched; in a client's ledger, their row ids
    # What it is a problem with: the row that carries it, or that row's whole document (lines that don't reach the
    # document's total, when no one line explains why), which the pages then show against the document.
    about: Literal["row", "document"] = "row"
    # On a total that doesn't add up: the printed total less the lines and what is set aside (positive: short;
    # negative: over). What a person accepts when they say to leave it as it is.
    difference: Optional[Decimal] = None


class BusinessSettings(BaseModel):
    business_name: str = ""
    # The client's capitalisation threshold: equipment that costs less, net of the VAT reclaimed, is a cost, not an
    # asset. None: no policy given, equipment is judged against the client's materiality (small_asset).
    capitalise_from: Optional[Decimal] = None
    vat_registered: bool = True
    vat_from: Optional[dt.date] = None             # the day the VAT registration started: a row dated before it
                                                   # books no VAT; None: registered throughout
    business_type: Optional[BusinessType] = None   # None: not known, as for an analysis without a client
    period_start: Optional[dt.date] = None
    period_end: Optional[dt.date] = None
    books_start: Optional[dt.date] = None      # the first day of the client's first year: a row dated before it is
                                               # already in the opening balances
    bank_account: str = BANK                   # the default bank: a receipt's, and a bank line's without its own
    bank_accounts: tuple[str, ...] = (BANK,)   # the client's bank accounts and cards, by code
    owners: tuple[int, ...] = ()               # the slots of its directors, partners or members, in order; () when
                                               # none are listed: the first owner's accounts (slot 0) are used
    owner_names: tuple[str, ...] = ()          # their names, as the client lists them
    nature_of_business: str = ""               # what the business does, as the firm describes it
    sic_code: str = ""                         # its SIC code, if the firm gave one


class Settlement(BaseModel):
    """A payment applied to a document. On a bank line: a document it pays. On a document's rows: a bank
    line that paid it. In a bank line's candidates: a document it could pay, with what is open on it."""
    ref: str
    amount: Decimal
    date: Optional[dt.date] = None
    description: str = ""
    kind: Optional[str] = None     # the kind of document or line it is (a document_type): what was paid, or what paid


class StatementCheck(BaseModel):
    """Whether a bank statement's rows agree with the balances it prints: ok, a gap of `difference`, or none
    when it prints no balances to compare."""
    status: Literal["ok", "gap", "none"]
    difference: Optional[Decimal] = None


class Transaction(BaseModel):
    date: Optional[dt.date] = None
    description: str = ""
    direction: Direction
    gross: Decimal
    # Inputs keep what the document (or the user) said; checks.normalise never changes them,
    # so an edited row validated again is worked out afresh (new account, new settings).
    vat: Optional[Decimal] = None                  # VAT shown on the document; None = not shown
    vat_treatment: Optional[VatTreatment] = None   # rate a person picked, to estimate VAT not shown; None = none picked
    # Outputs, recomputed by checks.normalise on every pass:
    vat_posted: Optional[Decimal] = None           # the VAT the ledger books (shown, estimated or none)
    net: Optional[Decimal] = None                  # gross minus vat_posted
    reverse_vat: Optional[Decimal] = None          # reverse-charge VAT the business owes and reclaims on the row
    account_code: str
    contra_account_code: Optional[str] = None      # None = the business's bank account
    bank_account: Optional[str] = None             # an input on a bank line: the account or card its statement is
                                                   # for; None = the business's default bank
    currency: str = "GBP"
    source: str = "text"
    method: Literal["parsed", "llm", "vlm", "user"] = "llm"
    evidence: Optional[str] = None
    # Inputs too: what the row comes from and who it is with (from the model), the reference shared by
    # the rows of one document (from the adapter), and a person's Include tick on a document that is
    # not a transaction. Rows without a type, as older clients send them, are receipts: paid when issued.
    document_type: DocumentType = "receipt"
    counterparty: Optional[str] = None
    document_number: Optional[str] = None          # the invoice, receipt or claim number printed on it
    agent: Optional[str] = None                    # on an agent's statement: the agent, who holds the money
    owed_to: Optional[Literal["net_pay", "paye_ni", "pension"]] = None   # on a payroll report: what the row is owed to
    document_total: Optional[Decimal] = None       # the total printed on its document (an agent's statement: the
                                                   # net paid over), which matching checks its rows against
    document_net: Optional[Decimal] = None         # the total before VAT printed on its document, if it prints one
    not_vat_invoice: bool = False                  # its document says it is not a VAT invoice
    cis_deducted: Optional[Decimal] = None         # on an invoice: Construction Industry Scheme tax taken off it,
                                                   # as printed; gross is the amount due after it
    total_worked_out: bool = False                 # its document has a text layer that prints neither its amount nor
                                                   # its total: the reader worked the figure out (a cut-off receipt)
    document_ref: Optional[str] = None
    include: bool = False
    # Inputs set only by the accountant chat's decisions (never by a person's edit, so not in rows.EDITABLE or
    # RowPatch): a decision can leave a row out of the books, or replace it with another row.
    excluded: bool = False
    # An input a person's Remove sets on a row read from a file, with excluded: the row is out of the books and stays
    # listed, so Put back can book it again. Never set or cleared by the AI.
    removed: bool = False
    superseded_by: Optional[str] = None            # the decision that replaced this row
    decision_ids: list[str] = Field(default_factory=list)   # the decisions that changed this row
    supplier_vat_number: Optional[str] = None      # the VAT number printed on its document, which decides whether
                                                   # the VAT on a receipt can be reclaimed
    addressed_to: Optional[str] = None             # who its receipt or invoice is addressed to, as printed
    accepted: list[str] = Field(default_factory=list)     # warnings a person looked at and said are fine, by
                                                   # code (checks.ACCEPTABLE): not raised on the row again
    reverse_charge: bool = False                   # a service bought from abroad with no VAT charged: the business
                                                   # accounts for the VAT itself, due and reclaimed (boxes 1 and 4)
    abroad: bool = False                           # bought or supplied outside the UK, as the reader saw (a hotel
                                                   # stay abroad): it carries no UK VAT (checks.hotel_vat)
    # The difference between its document's printed total and its lines that a person said to leave as it is (kept
    # on every row of the document): while the difference is this much, the total raises a note, not a warning.
    total_accepted: Optional[Decimal] = None
    apart_from: list[int] = Field(default_factory=list)   # rows a person said are not the same as this one, by row
                                                   # id (Not the same): never paired with it or asked about
    without_document: Optional[str] = None         # a person booked it without the receipt or invoice the document
                                                   # rules want, for this reason: no VAT reclaimed (never the AI)
    # Its receipt or invoice says VAT is charged or included (the word, or a rate) without printing the amount: with
    # the supplier's VAT number, what lets the ledger work the VAT out of the amount (checks.vat_implied).
    vat_stated: bool = False
    # Set by matching, never saved: the row's VAT (vat_posted) is what its expense claim shows, its own receipt or
    # invoice showing none. The claim is the person's record of it, so the document rules reclaim it, and the row
    # says a VAT invoice is still wanted.
    vat_from_claim: bool = False
    # A person entered the row's VAT, or said to reclaim it: the VAT is theirs to vouch for, so the document rules
    # reclaim it whatever the document is (a booking confirmation, a receipt over the limit, a line with no receipt).
    # Set when a person edits the VAT on a page or tells the chat to; never by the reading or the AI's own decision.
    vat_confirmed: bool = False
    # Set by the ledger, never saved: the VAT on the row (vat_posted) that the document rules do not reclaim, because
    # the row is held in Suspense or its document is not a VAT invoice, and why. The books then hold the whole
    # amount with no VAT, so a page shows that, and says where the VAT went.
    vat_not_reclaimed: Optional[Decimal] = None
    # A bad debt (design of 2026-11-24): a write_off row writes off the invoice with this document_ref; a bank line in
    # from that customer afterwards recovers part of it (the write-off's ref), booked against Bad Debts.
    writes_off: Optional[str] = None
    recovers: Optional[str] = None
    vat_not_reclaimed_why: Optional[str] = None
    link: Optional[list[str]] = None               # a person's decision on a bank line: None automatic,
                                                   # [] not a payment of any document, refs: pays these
    # Inputs too, on a bank statement row: the running balance printed on its line and the statement's
    # opening and closing balances, which statements.check_statement compares with the rows.
    balance: Optional[Decimal] = None
    opening_balance: Optional[Decimal] = None
    closing_balance: Optional[Decimal] = None
    # Outputs, recomputed by matching.match on every pass:
    paid_against: Optional[str] = None             # a bank line that pays documents: the account it settles
    pays: list[Settlement] = Field(default_factory=list)              # a bank line: the documents it pays
    candidates: list[list[Settlement]] = Field(default_factory=list)  # a bank line: what it could pay (Link)
    owed: Optional[Decimal] = None                 # a document's row: what is still open on the document
    document_direction: Optional[Direction] = None  # a document's row: which way what it owes goes (in: they owe
                                                   # the business), which the rows of an agent's statement don't share
    paid_by: list[Settlement] = Field(default_factory=list)           # a document's row: what paid it
    in_opening: bool = False                       # dated before the client's first year (checks.normalise): its
                                                   # amount is in the opening balances, so booked only if included
    copy_of: Optional[Settlement] = None           # a document's row: the earlier document it repeats (a
                                                   # reminder, a receipt read twice); not booked unless included
    recorded_by: Optional[Settlement] = None       # a bank line or a claim line: the receipt or invoice for the
                                                   # same payment, booked instead; this row is not booked
    claimed_in: Optional[Settlement] = None        # a receipt or invoice on an expense claim: owed to the claimant
    claim_note: Optional[str] = None               # on such a receipt or invoice: its claim line's words, which may
                                                   # say who a meal or drink was for (set by matching)
    people: Optional[Literal["one", "several"]] = None   # food or drink: how many the receipt's items look to be
                                                   # for (the reader's); None: unclear, or not food or drink
    bought: Optional[Bought] = None                # food or drink: what kind was bought (the reader's), which says
                                                   # as an accountant reads it who it was likely for; None: not said
    alternatives: list[str] = Field(default_factory=list)   # up to two other chart accounts the reader thought it
                                                   # could fairly be on
    presentation: list[Issue] = Field(default_factory=list)   # questions of presentation checks.normalise found:
                                                   # asked or left by the client's materiality (materiality.decide)
    account_chosen: bool = False                   # a person changed the account from what was read (set as rows
                                                   # load): a claim note doesn't recode it
    documented_by: Optional[Settlement] = None     # the document behind a row that books instead of it, with no
                                                   # VAT reclaimed: a claim line's bill for more than was claimed,
                                                   # or a bank line's receipt that prints no total (its subtotal)
    recorded_by_refs: list[str] = Field(default_factory=list)  # a claim line booked from several receipts on one
                                                   # document (a TfL statement's daily charges): each one's ref,
                                                   # oldest first; recorded_by then stands for them all
    left_off_claim: Optional[Settlement] = None    # a receipt on that document the claim leaves out: the claim line;
                                                   # the claimant paid it, so not booked unless included
    vat_found: Optional[Decimal] = None           # a receipt or invoice on a claim: VAT its prices and the claim agree
                                                   # on, not booked because it says it is not a VAT invoice (Book VAT)
    date_found: Optional[dt.date] = None           # a receipt, or a claim line, whose other record (its claim line,
                                                   # receipt or card payment) agrees on all but the date: its date (Use)
    amount_found: Optional[Decimal] = None         # the same, when the two agree on the shop and the day but not the
                                                   # amount: the other record's amount (Use)
    issues: list[Issue] = Field(default_factory=list)

    @field_validator("gross", mode="before")
    @classmethod
    def _positive_pennies(cls, value):
        money = to_money(value)
        if money is None or money <= 0:
            raise ValueError("gross must be a positive amount; direction says whether money went in or out")
        return money

    @field_validator("vat", "vat_posted", "net", "reverse_vat", "owed", "balance", "opening_balance", "closing_balance",
                     "document_total", "document_net", "vat_found", "amount_found", mode="before")
    @classmethod
    def _pennies(cls, value):
        if value is None:
            return None
        money = to_money(value)
        if money is None:
            raise ValueError("not an amount")
        return money

    @field_validator("currency", mode="before")
    @classmethod
    def _currency_code(cls, value):
        code = str(value or "").strip().upper()
        return "GBP" if code in ("", "£") else code

    @computed_field
    @property
    def account_name(self) -> Optional[str]:
        account = BY_CODE.get(self.account_code)
        return account.name if account else None

    @computed_field
    @property
    def contra_account_name(self) -> Optional[str]:
        account = BY_CODE.get(self.contra_account_code or "")
        return account.name if account else None

    @computed_field
    @property
    def paid_against_name(self) -> Optional[str]:
        account = BY_CODE.get(self.paid_against or "")
        return account.name if account else None


class TransactionList(BaseModel):
    transactions: list[Transaction]


class AnalysisResult(TransactionList):
    warnings: list[str] = Field(default_factory=list)
    model: Optional[str] = None


class LedgerRequest(BaseModel):
    transactions: list[Transaction]
    settings: BusinessSettings = Field(default_factory=BusinessSettings)


class JournalLine(BaseModel):
    transaction: int     # position in the request
    code: str
    debit: Decimal
    credit: Decimal
    description: str


class TrialBalanceLine(BaseModel):
    code: str
    name: str
    type: str
    heading: str                   # accounts.Heading: where it goes in the profit and loss account or balance sheet
    debit: Decimal
    credit: Decimal


class TrialBalance(BaseModel):
    lines: list[TrialBalanceLine]          # the opening balances plus the movements
    opening: list[TrialBalanceLine] = Field(default_factory=list)   # the opening balances alone
    total_debits: Decimal
    total_credits: Decimal
    is_balanced: bool
    journal: list[JournalLine]
    total_income: Decimal = ZERO
    total_expenses: Decimal = ZERO
    net_profit: Decimal = ZERO
    total_assets: Decimal = ZERO
    total_liabilities: Decimal = ZERO
    # The rows left out of these figures because each has a problem to fix, in words: only on the trial balance a
    # page shows while rows need fixing. Empty when every row is in.
    left_out: list[str] = Field(default_factory=list)


class VatFigures(BaseModel):
    """The nine boxes of a VAT return for a period, worked from the rows booked in it by their dates: a guide to
    check, not a return. Boxes 1 to 5 in pounds and pence; 6 to 9 are entered in whole pounds."""
    start: dt.date
    end: dt.date
    box1: Decimal    # VAT due on sales and other outputs
    box2: Decimal    # VAT due on acquisitions of goods into Northern Ireland from the EU: not worked out, nil
    box3: Decimal    # total VAT due: box 1 plus box 2
    box4: Decimal    # VAT reclaimed on purchases and other inputs
    box5: Decimal    # net VAT: box 3 less box 4 (negative: a repayment)
    box6: Decimal    # total sales and other outputs, excluding VAT
    box7: Decimal    # total purchases and other inputs, excluding VAT
    box8: Decimal    # goods supplied to the EU from Northern Ireland: not worked out, nil
    box9: Decimal    # goods acquired from the EU into Northern Ireland: not worked out, nil
    notes: list[str] = Field(default_factory=list)   # what the figures leave out, in words


class SuspenseItem(BaseModel):
    """A row whose posted lines leave its gross in Suspense, while it waits for the document it needs."""
    row_id: int
    description: str
    gross: Decimal
    needs: Optional[str] = None   # "receipt_or_invoice" or "vat_invoice" while it is still held; None once it isn't


class PostedTrialBalance(TrialBalance):
    """The trial balance of the posted ledger: the opening balances plus every entry posted, and the rows posted to
    Suspense. Its journal is the posted entries, each with its row id as its transaction. problems: why the opening
    or what the Suspense items need couldn't be worked out (rows need fixing). unposted_changes: how many rows
    would post something on the next posting (0 unless the route or summary fills it in)."""
    suspense: list[SuspenseItem] = Field(default_factory=list)
    unposted_changes: int = 0
    problems: list[str] = Field(default_factory=list)


class PostResult(BaseModel):
    """What one posting wrote: its batch (None when it wrote nothing), the new lines and the reversals of lines
    posted before, their totals, and why nothing was written when the batch failed its checks."""
    batch_id: Optional[str]
    entries_added: int
    reversals_added: int
    total_debits: Decimal
    total_credits: Decimal
    problems: list[str] = Field(default_factory=list)
    left_out: list[str] = Field(default_factory=list)   # the rows needing a fix, not posted until they are fixed


class ClientFields(BaseModel):
    """What a person enters for a client, trimmed; ledger.check_client says what is missing."""
    name: str
    business_type: BusinessType
    contact_name: str                  # the responsible person: the client's own contact
    first_year_end: Optional[dt.date]  # the end of the first year the client's books are kept for; sent always, and
                                       # check_client refuses it empty
    contact_email: str = ""
    contact_phone: str = ""
    vat_registered: bool = True
    vat_from: Optional[dt.date] = None  # the day the VAT registration started; None: registered throughout
    bank_accounts: list[BankAccount] = Field(
        default_factory=lambda: [BankAccount(code=BANK, name="Bank current account", kind="current")])
    owners: list[Owner] = Field(default_factory=list)   # its directors, partners or members; none for a sole trader
    ai_review: Literal["automatic", "suggest", "off"] = "automatic"   # what the background AI review may do
    materiality: Optional[Decimal] = None   # the firm's overall materiality for the client, in pounds; None: worked
                                            # out from its figures (materiality.year_levels)
    capitalise_from: Optional[Decimal] = None   # its capitalisation threshold, in pounds net; None: no policy
    # The client's references, as its papers print them: kept and shown, used by nothing yet.
    company_number: str = ""           # Companies House number
    utr: str = ""                      # Unique Taxpayer Reference
    vat_number: str = ""               # VAT registration number
    paye_reference: str = ""           # employer's PAYE reference
    # What the business does, as the firm describes it, and its SIC code: what looks personal for one business can be
    # its trade for another (a streaming subscription for a film company).
    nature_of_business: str = ""
    sic_code: str = ""

    @field_validator("name", "contact_name", "contact_email", "contact_phone", "company_number", "utr",
                     "vat_number", "paye_reference", "nature_of_business", "sic_code", mode="before")
    @classmethod
    def _trimmed(cls, value):
        return "" if value is None else str(value).strip()

    @field_validator("first_year_end", "vat_from", mode="before")
    @classmethod
    def _empty_date(cls, value):
        return None if value == "" else value


class ClosedYear(BaseModel):
    """A year the accountant closed: locked until reopened, and its balances at its end by account, signed with
    debits positive, which the next year opens with."""
    start: dt.date
    end: dt.date
    closed_at: str
    closing: dict[str, Decimal]
    # "document_rules" once the year was closed with the document rules applied; None for a year closed before
    # them, which is still worked out without them (closed is closed).
    rules: Optional[str] = None
    # The owners' slots and shares its profit was split by when it closed (accounts.profit_split), so a later change
    # to them leaves it as it was; None for a year closed before they were kept, which is split by today's.
    shares: Optional[list[tuple[int, Optional[Decimal]]]] = None


class Client(ClientFields):
    id: int
    closed_years: list[ClosedYear] = Field(default_factory=list)   # in order, the first year first
    archived: bool = False
    archived_at: Optional[str] = None
    created_at: str
    updated_at: str


class ClientPatch(BaseModel):
    """A change to a client: only the fields sent change; archived true archives it, false restores it."""
    name: Optional[str] = None
    business_type: Optional[BusinessType] = None
    contact_name: Optional[str] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    vat_registered: Optional[bool] = None
    vat_from: Optional[dt.date] = None             # null clears it: registered throughout
    bank_accounts: Optional[list[BankAccount]] = None
    owners: Optional[list[Owner]] = None
    first_year_end: Optional[dt.date] = None
    ai_review: Optional[Literal["automatic", "suggest", "off"]] = None
    materiality: Optional[Decimal] = None          # null clears it: worked out from the client's figures
    capitalise_from: Optional[Decimal] = None      # null clears it: no capitalisation threshold
    company_number: Optional[str] = None
    utr: Optional[str] = None
    vat_number: Optional[str] = None
    paye_reference: Optional[str] = None
    nature_of_business: Optional[str] = None
    sic_code: Optional[str] = None
    archived: Optional[bool] = None

    @field_validator("vat_from", mode="before")
    @classmethod
    def _empty_date(cls, value):
        return None if value == "" else value


class ClientSummary(Client):
    rows: int = 0
    to_review: int = 0   # rows with an error or a warning
    ai_unseen: int = 0   # changes and suggestions of background reviews the person hasn't seen


class Upload(BaseModel):
    id: int
    name: str
    kind: str
    sha256: str = ""
    model: str = ""
    warnings: list[str] = Field(default_factory=list)
    created_at: str
    rows: int = 0
    statement: Optional[StatementCheck] = None   # a bank statement's balance check; None for other uploads
    bank_account: Optional[str] = None           # the account or card its statement lines are on; None: the default
    year_start: Optional[dt.date] = None         # the year it was added to, which its undated rows wait in


class UploadPatch(BaseModel):
    """A change to an upload: the bank account or card its statement is for."""
    bank_account: str


class SavedRow(Transaction):
    """A saved row as the pages show it: its id, its upload, and what was read before a person's first edit."""
    id: int
    upload_id: int
    edited: bool = False
    original: Optional[dict] = None


class Year(BaseModel):
    """One of a client's accounting years."""
    start: dt.date
    end: dt.date
    label: str                 # "Year to 31 Mar 2026"
    closed: bool = False
    changed_since_closed: bool = False   # a closed year whose rows now work out to other balances than it closed with
    rows: int = 0                        # how many of the client's rows it holds (books.years_of)


def _money(value) -> Decimal:
    money = to_money(value if value not in (None, "") else "0")
    if money is None:
        raise ValueError("not an amount")
    return money


class OpeningLine(BaseModel):
    """A first year's opening balance on one balance sheet account, from the client's last accounts."""
    code: str
    debit: Decimal = ZERO
    credit: Decimal = ZERO

    @field_validator("debit", "credit", mode="before")
    @classmethod
    def _pennies(cls, value):
        return _money(value)


class OpenItem(BaseModel):
    """An invoice unpaid when the first year starts, behind Debtors (in: a customer owes the client) or Creditors
    (out: the client owes a supplier). A payment in any year can clear it."""
    id: str
    direction: Direction
    counterparty: str
    amount: Decimal
    number: Optional[str] = None
    date: Optional[dt.date] = None

    @field_validator("amount", mode="before")
    @classmethod
    def _pennies(cls, value):
        return _money(value)

    @field_validator("id", "counterparty", mode="before")
    @classmethod
    def _trimmed(cls, value):
        return "" if value is None else str(value).strip()

    @field_validator("number", mode="before")
    @classmethod
    def _trimmed_number(cls, value):
        return None if value is None else (str(value).strip() or None)


class OpeningBalances(BaseModel):
    """A client's first year's opening balances: the amounts and the unpaid invoices behind Debtors and Creditors."""
    lines: list[OpeningLine] = Field(default_factory=list)
    unpaid: list[OpenItem] = Field(default_factory=list)


class Ledger(BaseModel):
    """One of a client's years: its rows, and the uploads that hold them or were added to it."""
    client: Client
    year: Year
    years: list[Year]
    uploads: list[Upload]
    transactions: list[SavedRow]


class InvoiceSummary(BaseModel):
    """One sales or purchase invoice of a year, with what has been paid and what is still owed after every payment
    matched to it, in any year. brought_forward: dated before the year and still owed when it started."""
    ref: str
    kind: Literal["sale", "purchase"]
    counterparty: Optional[str] = None
    number: Optional[str] = None
    date: Optional[dt.date] = None
    total: Decimal
    paid: Decimal
    owed: Decimal
    paid_by: list[Settlement] = Field(default_factory=list)
    owed_at_year_end: Decimal = ZERO   # what was owed on the year's last day: payments after it left out
    brought_forward: bool = False
    credit_note: bool = False   # the money goes the other way: a supplier's credit to the business, or its own to a customer


class BankCheck(BaseModel):
    """A bank account's balance in the books against the closing balance of its latest statement of the year, both
    as the statement prints it (a card's, what is owed on it). difference: books less statement."""
    code: str
    name: str
    kind: BankAccountKind
    books: Decimal
    statement: Optional[Decimal] = None
    statement_date: Optional[dt.date] = None
    difference: Optional[Decimal] = None
    left_out: int = 0   # rows of the year with a problem to fix, which the books figure is worked out without


class YearSummary(BaseModel):
    """A year at a glance: its rows and those to review, what is unpaid, its bank checks and whether its trial
    balance can be worked out (blocked, with the problems that stop it)."""
    year: Year
    rows: int
    to_review: int
    unpaid_sales: Decimal
    unpaid_purchases: Decimal
    bank: list[BankCheck]
    trial_balance: Literal["balanced", "blocked"]
    problems: list[str] = Field(default_factory=list)
    missing_paperwork: list[str] = Field(default_factory=list)   # statements the books need and don't have, in words
    pointers: list[str] = Field(default_factory=list)   # what an accountant would want to know, in words


class RowPatch(BaseModel):
    """A person's change to a saved row: Link, Include or Not the same, an edit of what was read, or revert. Only
    the fields sent change; ledger.change_row checks them."""
    link: Optional[list[str]] = None
    include: Optional[bool] = None
    apart_from: Optional[list[int]] = None
    date: Optional[dt.date] = None
    description: Optional[str] = None
    counterparty: Optional[str] = None
    direction: Optional[Direction] = None
    gross: Optional[Decimal] = None
    vat: Optional[Decimal] = None
    account_code: Optional[str] = None
    document_type: Optional[DocumentType] = None
    # How VAT applies, as a person says: a rate to work VAT out at when none is shown, or zero-rated, exempt or
    # outside the scope (a reverse charge among them), which book no VAT. null: as the document and account have it.
    vat_treatment: Optional[VatTreatment] = None
    # The currency the amount is now in: "GBP" once a person has converted an amount read in another currency.
    currency: Optional[str] = None
    without_document: Optional[str] = None   # book it without its receipt or invoice, for this reason; null: hold it
    # What paid a receipt (or what it was paid into): one of the client's bank accounts or cards, or the owner or
    # staff who paid it themselves. null: the client's main bank account.
    bank_account: Optional[str] = None
    # A service from abroad with no VAT charged, which the business accounts for itself (the reverse charge).
    reverse_charge: Optional[bool] = None
    accepted: Optional[list[str]] = None     # the warnings a person said are fine, by code (checks.ACCEPTABLE)
    # Reclaim the row's VAT on the person's say (True), or leave it to the document rules again (False). A VAT amount
    # a person sends sets it by itself: ledger.change_row.
    vat_confirmed: Optional[bool] = None
    removed: Optional[bool] = None           # false: Put back a row the person removed (Remove is what sets it)
    # Leave its document's total out by this much (the difference its warning gives); null: ask about it again.
    total_accepted: Optional[Decimal] = None
    revert: bool = False

    @field_validator("without_document")
    @classmethod
    def _reason(cls, value):
        return value.strip() if isinstance(value, str) else value

    @field_validator("gross", "vat", mode="before")
    @classmethod
    def _pennies(cls, value):
        if value is None or value == "":
            return None
        money = to_money(value)
        if money is None:
            raise ValueError("not an amount")
        return money

    @field_validator("description", "counterparty", mode="before")
    @classmethod
    def _trimmed(cls, value):
        return None if value is None else (str(value).strip() or None)


class ManualUpload(BaseModel):
    name: str = "Manual entry"
    kind: Literal["manual"] = "manual"
    transactions: list[Transaction]
    year_start: Optional[dt.date] = None   # the year the rows are added to, which any undated row waits in


# ─── The accountant chat's records ─────────────────────────────────────────────

class Evidence(BaseModel):
    """What a decision rests on: a quote from one of the client's uploads."""
    upload_id: int
    upload_name: str = ""
    quote: str


class DecisionDraft(BaseModel):
    """A decision as its maker states it: what was done to which rows, by which rule, on what evidence. before and
    after hold the changed fields of each row, keyed by str(row_id). AgentRecords.append_decision adds the rest."""
    client_id: int
    thread_id: Optional[str] = None
    year_start: dt.date
    action: str
    rule: str                                  # e.g. "R2 Duplicate: kept the receipt"
    status: Literal["applied", "refused", "suggested"]
    row_ids: list[int] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    reason: str = ""
    before: dict[str, dict] = Field(default_factory=dict)
    after: dict[str, dict] = Field(default_factory=dict)
    actor: str                                 # "agent:<model>", "user" or "rules"
    reverses: Optional[str] = None             # the decision this one undoes
    trigger: Literal["chat", "background"] = "chat"   # who made it: a chat turn or the background review
    review_id: Optional[str] = None            # the review run that made it
    resolution: Optional[dict] = None          # the resolution's JSON, kept for a suggested decision


class Decision(DecisionDraft):
    """A decision as the log keeps it. Each client's decisions form a hash chain: hash is the SHA-256 of
    prev_hash (the previous decision's hash, "" for the first) and this decision's JSON without its hash."""
    id: str
    created_at: str
    prev_hash: str
    hash: str


ChangeKind = Literal["upload_read", "upload_removed", "upload_bank_changed", "row_edited", "row_added",
                     "row_removed", "row_linked", "row_included", "rows_apart", "row_reverted", "client_changed",
                     "opening_balances_changed", "question_answered", "decision", "year_reopened", "year_closed",
                     "decision_undone", "decision_applied", "question_closed", "question_offered"]


class ChangeDraft(BaseModel):
    """One change to a client's books, as its maker states it. AgentRecords.add_change adds the rest."""
    client_id: int
    year_start: Optional[dt.date] = None       # None: the whole client, or a year the caller doesn't know
    actor: str                                 # "user", "rules" or "agent:<model>" ("import" on changes a folder import made)
    kind: ChangeKind
    row_ids: list[int] = Field(default_factory=list)
    upload_id: Optional[int] = None
    before: dict = Field(default_factory=dict)
    after: dict = Field(default_factory=dict)
    summary: str                               # one line, plain English: "Row 25 changed: account 8201 → 2250"
    in_chat: bool = False                      # made by a chat turn, which says so itself


class Change(ChangeDraft):
    """A change as the record keeps it."""
    id: str
    seq: int                                   # time.time_ns() when added; orders changes
    created_at: str                            # rows.now_iso()


class QuestionDraft(BaseModel):
    """A question for the person, as the rules or the agent state it; a new question is open."""
    client_id: int
    year_start: dt.date
    row_ids: list[int] = Field(default_factory=list)
    kind: Literal["date", "receipt_or_invoice", "vat_invoice", "payout_report", "payroll_report", "opening_prepayments",
                  "opening_accruals", "opening_vat", "bad_debt", "other"]
    text: str                                  # "When was this taxi?"
    why: str                                   # "£50 or more, so I need ..."
    source: Literal["rules", "agent"]


class OfferSource(BaseModel):
    """Where part of an offered answer comes from: the person's words in the chat (said), a quote from one of the
    client's documents (document, for the line or date it backs, with any working), or the question itself (its
    amount, or the write-off date it defaults to)."""
    model_config = {"populate_by_name": True}
    kind: Literal["said", "document", "question"]
    quote: str = ""
    upload_id: Optional[int] = None
    upload_name: str = ""
    for_: Optional[str] = Field(None, alias="for")   # "line:<n>" (from 1) or "date"
    working: str = ""                                 # how a figure was worked out: "£6,000.00 for 91 days, 84 next year"


class Offer(BaseModel):
    """An answer to a books question the agent filled in from what the person said, for them to change or confirm
    on the question's card: nothing is booked until they do."""
    answer: dict                                      # a SplitAnswer or WriteOffAnswer, as JSON
    sources: list[OfferSource]
    reason: str
    thread_id: str
    offered_at: str
    offered_by: str


class Question(QuestionDraft):
    """A question as kept: open until answered, waiting when the person has no answer yet ("I don't have it",
    "Not sure"), resolved once answered. offer: an answer filled in for the person to confirm."""
    id: str
    status: Literal["open", "waiting", "resolved"]
    answer: Optional[str] = None
    created_at: str
    resolved_at: Optional[str] = None
    offer: Optional[Offer] = None


class ChatThread(BaseModel):
    """One conversation with the accountant, about one client's year."""
    id: str
    client_id: int
    year_start: dt.date
    title: str
    created_at: str
    updated_at: str


# ─── The background review's records ───────────────────────────────────────────

class ReviewRun(BaseModel):
    """One run of the background AI review over what changed in a client's year."""
    id: str
    client_id: int
    year_start: dt.date
    status: Literal["running", "done", "failed", "limited", "off"]
    started_at: str
    finished_at: Optional[str] = None
    trigger_summary: str                       # "after 3 files were added"
    from_seq: int                              # the changes it looked at: after from_seq, up to to_seq
    to_seq: int
    decision_ids: list[str] = Field(default_factory=list)
    question_ids: list[str] = Field(default_factory=list)
    looked_at: list[int] = Field(default_factory=list)   # the row ids the run was pointed at
    issues_seen: list[str] = Field(default_factory=list)  # the issues it was shown, as "row:code:digest" keys
    summary: str = ""
    error: Optional[str] = None
    seen: bool = False                         # the person has opened the review's results


class ReviewState(BaseModel):
    """Where a client's background review stands: the last change it has looked at, when the next run is due, and
    whether one is running or waits to retry."""
    client_id: int
    last_seq: int = 0
    due_at: Optional[str] = None
    running: bool = False
    retry_at: Optional[str] = None
    left_over: list[str] = Field(default_factory=list)   # years (ISO starts) whose last run had more issues to show


class ReviewDetail(ReviewRun):
    """A run with the decisions it made and the questions it asked. A suggestion the person applied has applied_as,
    the id of the decision that applied it."""
    decisions: list[Decision] = Field(default_factory=list)
    questions: list[Question] = Field(default_factory=list)
    applied: dict[str, str] = Field(default_factory=dict)   # suggestion id -> the applied decision's id
