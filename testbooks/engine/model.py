"""What happened to a client: deals (the economic truth), their lines, payments and documents, and the client."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

ZERO = Decimal("0")

VAT_CODES = ("standard", "reduced", "zero", "exempt", "outside", "reverse_charge", "blocked", "blocked_half",
             "none")
DOC_KINDS = ("sales_invoice", "sales_credit_note", "void_invoice", "purchase_invoice", "receipt",
             "order_confirmation", "payroll_summary", "employer_payment_record", "board_minutes", "expense_claim",
             "letter", "prior_accounts", "prior_tb", "client_sheet", "bank_statement")
SETTLES_VIA = ("debtor", "creditor", "bank", "director_loan", "journal", "transfer")


@dataclass(frozen=True)
class Line:
    """One line of what was bought or sold. `vat` is the VAT printed (notional for a reverse charge)."""
    description: str
    account: str
    net: Decimal
    vat_code: str
    vat: Decimal = ZERO
    also_ok: tuple[str, ...] = ()
    stakes: str = "accounts"

    def __post_init__(self):
        if self.vat_code not in VAT_CODES:
            raise ValueError(f"unknown VAT code {self.vat_code}")

    @property
    def gross(self) -> Decimal:
        return self.net if self.vat_code == "reverse_charge" else self.net + self.vat


@dataclass(frozen=True)
class Payment:
    """A line on one of the client's money accounts. `amount` is signed from the client's side: positive is money
    into that account. `against` is the account a journal deal's payment clears."""
    id: str
    account: str
    date: date
    amount: Decimal
    descriptor: str
    type_code: str = ""
    against: str = ""


@dataclass(frozen=True)
class JournalLine:
    account: str
    debit: Decimal = ZERO
    credit: Decimal = ZERO
    description: str = ""


@dataclass(frozen=True)
class Doc:
    """A document the client sends. `printed` holds the figures printed on it (net, vat, gross)."""
    id: str
    kind: str
    issuer: str
    recipient: str
    number: str
    date: date
    currency: str = "GBP"
    treatment: str = "book"
    reason: str = ""
    printed: dict[str, Decimal] = field(default_factory=dict)
    extra: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.kind not in DOC_KINDS:
            raise ValueError(f"unknown document kind {self.kind}")


@dataclass(frozen=True)
class Query:
    """A question an accountant would ask, the client's answer, and (if the books differ before the answer) the
    lines an accountant would book until it comes."""
    id: str
    question: str
    why: str
    stakes: str
    answer_date: date
    answer_text: str
    before: tuple[Line, ...] | None = None
    answer_doc: Doc | None = None


@dataclass(frozen=True)
class Deal:
    id: str
    kind: str
    date: date
    counterparty: str
    settles_via: str
    lines: tuple[Line, ...] = ()
    journal: tuple[JournalLine, ...] = ()
    payments: tuple[Payment, ...] = ()
    docs: tuple[Doc, ...] = ()
    cases: tuple[str, ...] = ()
    query: Query | None = None
    vat_boxes: dict[int, Decimal] = field(default_factory=dict)
    covers: tuple[date, date] | None = None

    def __post_init__(self):
        if self.settles_via not in SETTLES_VIA:
            raise ValueError(f"unknown settlement {self.settles_via}")

    @property
    def gross(self) -> Decimal:
        return sum((line.gross for line in self.lines), ZERO)


@dataclass(frozen=True)
class MoneyAccount:
    id: str
    name: str
    bank: str
    layout: str
    code: str
    statement_day: int = 0


@dataclass(frozen=True)
class Employee:
    id: str
    name: str
    director: bool
    salary: Decimal
    pension: bool
    ni_number: str


@dataclass(frozen=True)
class Owner:
    id: str
    name: str
    share: Decimal
    loan_code: str


@dataclass(frozen=True)
class Policies:
    basis: str
    capitalise_from: Decimal
    accrue_from: Decimal
    depreciation_years: dict[str, int]
    accounts_standard: str
    pension_ee: Decimal
    pension_er: Decimal
    known_accruals: tuple[tuple[str, str, Decimal, date], ...] = ()


@dataclass(frozen=True)
class Asset:
    id: str
    description: str
    cls: str
    bought: date
    cost: Decimal


@dataclass(frozen=True)
class OpenItem:
    kind: str
    counterparty: str
    number: str
    date: date
    gross: Decimal


@dataclass(frozen=True)
class VatTotals:
    output: Decimal
    input: Decimal
    net_sales: Decimal
    net_purchases: Decimal


@dataclass(frozen=True)
class Opening:
    """The position the books start from, as the previous accountant handed it over (debit positive)."""
    as_at: date
    balances: dict[str, Decimal]
    open_items: tuple[OpenItem, ...]
    assets: tuple[Asset, ...]
    vat_brought_in: VatTotals
    true_differences: dict[str, Decimal]
    prior_pl: dict[str, Decimal]
    reversals: tuple[tuple[str, str, Decimal], ...] = ()


@dataclass(frozen=True)
class Period:
    start: date
    end: date
    partial: bool = False


@dataclass(frozen=True)
class Client:
    id: str
    name: str
    kind: str
    address: str
    company_number: str
    vat_number: str
    periods: tuple[Period, ...]
    vat_stagger: tuple[int, ...]
    accounts: tuple[MoneyAccount, ...]
    employees: tuple[Employee, ...]
    owners: tuple[Owner, ...]
    policies: Policies
    opening: Opening

    def account(self, account_id: str) -> MoneyAccount:
        return next(a for a in self.accounts if a.id == account_id)
