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
# it collected and paid for the business, and the net it paid over. The last six are not transactions: a person
# ticks Include to book one as an invoice. "other" is what the adapter makes of a type it does not know.
DocumentType = Literal["receipt", "invoice", "expense_claim", "statement", "agent_statement", "quote", "pro_forma",
                       "purchase_order", "remittance_advice", "supplier_statement", "other"]
DOCUMENT_TYPES: tuple[str, ...] = get_args(DocumentType)
NOT_TRANSACTIONS = frozenset(DOCUMENT_TYPES[5:])

# The kind of business a client is: a limited company's owners go through 2250 Director's Loan Account,
# anyone else's through 3260 Drawings and 3000 Capital Introduced.
BusinessType = Literal["limited_company", "sole_trader", "partnership", "llp"]
BUSINESS_TYPES: tuple[str, ...] = get_args(BusinessType)


class Issue(BaseModel):
    code: str
    message: str
    severity: Literal["info", "warning", "error"]
    related: list[int] = Field(default_factory=list)   # the other rows it is about (Show both): places in the rows
                                                       # matched; in a client's ledger, their row ids


class BusinessSettings(BaseModel):
    business_name: str = ""
    vat_registered: bool = True
    business_type: Optional[BusinessType] = None   # None: not known, as for an analysis without a client
    period_start: Optional[dt.date] = None
    period_end: Optional[dt.date] = None
    bank_account: str = BANK


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
    account_code: str
    contra_account_code: Optional[str] = None      # None = the business's bank account
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
    document_total: Optional[Decimal] = None       # the total printed on its document (an agent's statement: the
                                                   # net paid over), which matching checks its rows against
    document_net: Optional[Decimal] = None         # the total before VAT printed on its document, if it prints one
    not_vat_invoice: bool = False                  # its document says it is not a VAT invoice
    document_ref: Optional[str] = None
    include: bool = False
    apart_from: list[int] = Field(default_factory=list)   # rows a person said are not the same as this one, by row
                                                   # id (Not the same): never paired with it or asked about
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
    copy_of: Optional[Settlement] = None           # a document's row: the earlier document it repeats (a
                                                   # reminder, a receipt read twice); not booked unless included
    recorded_by: Optional[Settlement] = None       # a bank line or a claim line: the receipt or invoice for the
                                                   # same payment, booked instead; this row is not booked
    claimed_in: Optional[Settlement] = None        # a receipt or invoice on an expense claim: owed to the claimant
    vat_found: Optional[Decimal] = None            # a receipt or invoice on a claim: VAT its prices and the claim agree
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

    @field_validator("vat", "vat_posted", "net", "owed", "balance", "opening_balance", "closing_balance",
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
    debit: Decimal
    credit: Decimal


class TrialBalance(BaseModel):
    lines: list[TrialBalanceLine]
    total_debits: Decimal
    total_credits: Decimal
    is_balanced: bool
    journal: list[JournalLine]
    total_income: Decimal = ZERO
    total_expenses: Decimal = ZERO
    net_profit: Decimal = ZERO
    total_assets: Decimal = ZERO
    total_liabilities: Decimal = ZERO


class ClientFields(BaseModel):
    """What a person enters for a client, trimmed; ledger.check_client says what is missing."""
    name: str
    business_type: BusinessType
    contact_name: str                  # the responsible person: the client's own contact
    contact_email: str = ""
    contact_phone: str = ""
    vat_registered: bool = True

    @field_validator("name", "contact_name", "contact_email", "contact_phone", mode="before")
    @classmethod
    def _trimmed(cls, value):
        return "" if value is None else str(value).strip()


class Client(ClientFields):
    id: int
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
    archived: Optional[bool] = None


class ClientSummary(Client):
    rows: int = 0
    to_review: int = 0   # rows with an error or a warning


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


class SavedRow(Transaction):
    """A saved row as the pages show it: its id, its upload, and what was read before a person's first edit."""
    id: int
    upload_id: int
    edited: bool = False
    original: Optional[dict] = None


class Ledger(BaseModel):
    client: Client
    uploads: list[Upload]
    transactions: list[SavedRow]


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
    revert: bool = False

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
