"""UK chart of accounts (Sage 50-style nominal codes). Every transaction posts to one of these,
and the AI picks from this list instead of inventing account names."""
from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Optional

from .money import VatTreatment as V


class AccountType(str, Enum):
    ASSET = "asset"
    LIABILITY = "liability"
    EQUITY = "equity"
    INCOME = "income"
    EXPENSE = "expense"


class Heading(str, Enum):
    """Where an account goes in the profit and loss account or balance sheet: the headings of the Companies Act
    formats (FRS 102 section 1A, FRS 105), which a sole trader's and a partnership's accounts follow too."""
    TURNOVER = "Turnover"
    COST_OF_SALES = "Cost of sales"
    ADMINISTRATIVE = "Administrative expenses"
    OTHER_INCOME = "Other operating income"
    INTEREST_RECEIVABLE = "Interest receivable and similar income"
    INTEREST_PAYABLE = "Interest payable and similar charges"
    TAX = "Tax on profit"
    INTANGIBLE = "Intangible assets"
    TANGIBLE = "Tangible assets"
    INVESTMENTS = "Investments"
    STOCKS = "Stocks"
    DEBTORS = "Debtors"
    CASH = "Cash at bank and in hand"
    CREDITORS_SHORT = "Creditors: amounts falling due within one year"
    CREDITORS_LONG = "Creditors: amounts falling due after more than one year"
    MEMBERS_DEBT = "Loans and other debts due to members"
    CAPITAL = "Capital and reserves"


class TaxTreatment(str, Enum):
    """How an income or cost account counts towards taxable trading profit (SA103, the partnership return, CT600)."""
    ALLOWABLE = "allowable"         # in trading profit as booked
    DISALLOWABLE = "disallowable"   # added back: never deductible (or never taxable) in trading profit
    CHECK = "check"                 # partly disallowable, depending on the facts: private use, the car lease
                                    # restriction, a general bad debt provision
    NON_TRADING = "non_trading"     # outside trading profit: taxed or relieved on its own (interest received, rent,
                                    # dividends received, a gain on selling an asset)


# The SA103F (self-employment, full) boxes a sole trader's, and a partner's, income and costs are entered in, 2025-26.
# A partnership's trading pages use the same headings.
SA103_BOXES: dict[int, str] = {
    15: "Turnover", 16: "Any other business income",
    17: "Cost of goods bought for resale or goods used", 18: "Construction industry - payments to subcontractors",
    19: "Wages, salaries and other staff costs", 20: "Car, van and travel expenses",
    21: "Rent, rates, power and insurance costs", 22: "Repairs and maintenance of property and equipment",
    23: "Phone, fax, stationery and other office costs", 24: "Advertising and business entertainment costs",
    25: "Interest on bank and other loans", 26: "Bank, credit card and other financial charges",
    27: "Irrecoverable debts written off", 28: "Accountancy, legal and other professional fees",
    29: "Depreciation and loss or profit on sale of assets", 30: "Other business expenses",
}


@dataclass(frozen=True)
class Account:
    code: str
    name: str
    type: AccountType
    vat: V              # usual rate, to check VAT a document shows; none is booked when none is shown
    definition: str     # what belongs here, in plain words: the model chooses by it
    reclaim_vat: bool = True   # False: VAT on a purchase here can't be reclaimed, so it stays in the cost
    heading: Optional[Heading] = None      # its place in the accounts; worked out from the code when not given
    tax: Optional[TaxTreatment] = None     # income and costs only: allowable unless given; None on the balance sheet
    sa103: Optional[int] = None            # income and costs only: its SA103F box; worked out from the code when not given

    def __post_init__(self):
        if self.heading is None:
            object.__setattr__(self, "heading", _heading_by_code(self.code, self.type))
        if self.type in (AccountType.INCOME, AccountType.EXPENSE):
            if self.tax is None:
                object.__setattr__(self, "tax", TaxTreatment.ALLOWABLE)
            outside = self.tax == TaxTreatment.NON_TRADING or self.heading == Heading.TAX
            if self.sa103 is None and not outside:
                object.__setattr__(self, "sa103", 16 if self.type == AccountType.INCOME else 30)


def _heading_by_code(code: str, kind: AccountType) -> Optional[Heading]:
    """The usual heading for a code in the Sage 50 ranges; an account elsewhere says its own."""
    if kind == AccountType.INCOME:
        return Heading.TURNOVER if code < "4900" else Heading.OTHER_INCOME
    if kind == AccountType.EXPENSE:
        return Heading.COST_OF_SALES if code.startswith("5") else Heading.ADMINISTRATIVE
    if kind == AccountType.EQUITY:
        return Heading.CAPITAL
    if kind == AccountType.LIABILITY:
        return Heading.CREDITORS_SHORT
    return (Heading.TANGIBLE if code < "1000" else Heading.STOCKS if code < "1100"
            else Heading.DEBTORS if code < "1200" else Heading.CASH)


_A, _L, _E, _I, _X = (AccountType.ASSET, AccountType.LIABILITY, AccountType.EQUITY,
                      AccountType.INCOME, AccountType.EXPENSE)
_H, _T = Heading, TaxTreatment

CHART: tuple[Account, ...] = (
    Account("0001", "Goodwill", _A, V.OUTSIDE_SCOPE, "What was paid for a business bought, over the value of its assets.",
            heading=_H.INTANGIBLE),
    Account("0002", "Goodwill Amortisation", _A, V.OUTSIDE_SCOPE,
            "Goodwill's value written off over the years (accumulated amortisation).", heading=_H.INTANGIBLE),
    Account("0010", "Freehold Property", _A, V.EXEMPT, "Land and buildings the business owns outright."),
    Account("0011", "Freehold Property Depreciation", _A, V.OUTSIDE_SCOPE,
            "Freehold buildings' value used up over the years (accumulated depreciation)."),
    Account("0015", "Leasehold Improvements", _A, V.STANDARD,
            "Building work and fit-out on premises the business rents, kept for over a year."),
    Account("0016", "Leasehold Improvements Depreciation", _A, V.OUTSIDE_SCOPE,
            "Leasehold improvements' value used up over the years (accumulated depreciation)."),
    Account("0020", "Plant and Machinery", _A, V.STANDARD, "Machinery, tools and heavy equipment kept for over a year."),
    Account("0021", "Plant and Machinery Depreciation", _A, V.OUTSIDE_SCOPE,
            "Plant and machinery's value used up over the years (accumulated depreciation)."),
    Account("0030", "Office Equipment", _A, V.STANDARD, "Computers, printers and other equipment kept for over a year."),
    Account("0031", "Office Equipment Depreciation", _A, V.OUTSIDE_SCOPE,
            "Office equipment's value used up over the years (accumulated depreciation)."),
    Account("0040", "Furniture and Fixtures", _A, V.STANDARD, "Desks, chairs, shelving and fittings for the premises."),
    Account("0041", "Furniture and Fixtures Depreciation", _A, V.OUTSIDE_SCOPE,
            "Furniture and fixtures' value used up over the years (accumulated depreciation)."),
    Account("0050", "Cars", _A, V.STANDARD,
            "Cars bought for the business; VAT on a car can't be reclaimed unless it is used only for business.",
            reclaim_vat=False),
    Account("0051", "Cars Depreciation", _A, V.OUTSIDE_SCOPE,
            "Cars' value used up over the years (accumulated depreciation)."),
    Account("0055", "Vans", _A, V.STANDARD, "Vans and other commercial vehicles bought for the business."),
    Account("0056", "Vans Depreciation", _A, V.OUTSIDE_SCOPE,
            "Vans' value used up over the years (accumulated depreciation)."),
    Account("0060", "Investments", _A, V.OUTSIDE_SCOPE,
            "Shares in other companies, and other investments held for the long term.", heading=_H.INVESTMENTS),
    Account("1001", "Stock", _A, V.OUTSIDE_SCOPE, "Goods held for sale and work in progress, as counted at the year end."),
    Account("1100", "Debtors", _A, V.OUTSIDE_SCOPE, "Money customers owe for invoices the business has sent and not yet been paid."),
    Account("1103", "Prepayments", _A, V.OUTSIDE_SCOPE, "Costs paid in advance that belong to a later period."),
    Account("1104", "CIS Deducted", _A, V.OUTSIDE_SCOPE,
            "CIS tax customers took off the business's invoices and paid to HMRC for it."),
    Account("1200", "Bank Current Account", _A, V.OUTSIDE_SCOPE, "The business's main bank account."),
    Account("1201", "Bank Current Account 2", _A, V.OUTSIDE_SCOPE, "The business's second current account."),
    Account("1202", "Bank Current Account 3", _A, V.OUTSIDE_SCOPE, "The business's third current account."),
    Account("1210", "Bank Deposit Account", _A, V.OUTSIDE_SCOPE, "A savings account; moving money into it is a transfer, not spending."),
    Account("1211", "Bank Deposit Account 2", _A, V.OUTSIDE_SCOPE,
            "A second savings account; moving money into it is a transfer, not spending."),
    Account("1230", "Petty Cash", _A, V.OUTSIDE_SCOPE, "Cash withdrawn to keep for small purchases."),
    Account("1240", "Company Credit Card", _L, V.OUTSIDE_SCOPE,
            "The business's credit card; paying the card off from the bank is a transfer, not spending."),
    Account("1241", "Company Credit Card 2", _L, V.OUTSIDE_SCOPE,
            "The business's second credit card; paying it off from the bank is a transfer."),
    Account("1250", "Payment Processor Clearing", _A, V.OUTSIDE_SCOPE,
            "Payouts from Stripe, PayPal, Square and the like, until their payout report books the sales and fees.",
            heading=_H.DEBTORS),
    Account("2100", "Creditors", _L, V.OUTSIDE_SCOPE, "Money the business owes suppliers for bills it has received and not yet paid."),
    Account("2105", "Deferred Income", _L, V.OUTSIDE_SCOPE, "Income received or invoiced for work to be done in a later period."),
    Account("2109", "Accruals", _L, V.OUTSIDE_SCOPE, "Costs for the period that have not been billed or paid yet."),
    Account("2110", "Expenses Owed to Staff", _L, V.OUTSIDE_SCOPE, "Expense claims approved for staff and not yet reimbursed."),
    Account("2200", "Sales VAT", _L, V.OUTSIDE_SCOPE, "VAT charged to customers."),
    Account("2201", "Purchase VAT", _L, V.OUTSIDE_SCOPE, "VAT paid to suppliers."),
    Account("2202", "VAT Liability", _L, V.OUTSIDE_SCOPE, "VAT paid to, or refunded by, HMRC for VAT returns."),
    Account("2210", "PAYE and National Insurance", _L, V.OUTSIDE_SCOPE, "Employees' income tax and National Insurance paid to HMRC."),
    Account("2215", "CIS Payable", _L, V.OUTSIDE_SCOPE,
            "CIS tax the business took off its subcontractors' invoices, owed to HMRC."),
    Account("2220", "Net Wages", _L, V.OUTSIDE_SCOPE,
            "Net pay owed to staff, from a payroll report; cleared by the bank payments to them."),
    Account("2230", "Pension Fund", _L, V.OUTSIDE_SCOPE, "Pension contributions owed to the pension provider."),
    Account("2250", "Director's Loan Account", _L, V.OUTSIDE_SCOPE,
            "Money a director has lent the company, or taken from it for personal use. Limited companies only."),
    *(Account(f"225{n}", f"Director's Loan Account {n + 1}", _L, V.OUTSIDE_SCOPE,
              f"The loan account of the company's director number {n + 1}. Limited companies only.") for n in (1, 2, 3)),
    *(Account(f"226{n}", "Members' Current Account" + (f" {n + 1}" if n else ""), _L, V.OUTSIDE_SCOPE,
              "What an LLP owes a member: profit allocated to them, less what they have drawn. LLPs only.",
              heading=_H.MEMBERS_DEBT) for n in range(4)),
    Account("2300", "Loans", _L, V.OUTSIDE_SCOPE, "Money borrowed on a business loan, or repaid (not the interest)."),
    Account("2301", "Loans Due After One Year", _L, V.OUTSIDE_SCOPE,
            "The part of the loans not due until after a year from the year end, moved here at the year end.",
            heading=_H.CREDITORS_LONG),
    Account("2310", "Hire Purchase", _L, V.OUTSIDE_SCOPE,
            "What is owed on hire purchase or finance lease agreements, and the repayments (not the interest)."),
    Account("2311", "Hire Purchase Due After One Year", _L, V.OUTSIDE_SCOPE,
            "The part of hire purchase not due until after a year from the year end, moved here at the year end.",
            heading=_H.CREDITORS_LONG),
    Account("2320", "Corporation Tax", _L, V.OUTSIDE_SCOPE,
            "Corporation tax owed to, or paid to, HMRC. Limited companies only."),
    Account("3000", "Ordinary Shares", _E, V.OUTSIDE_SCOPE,
            "Money shareholders paid in for shares in the company. Limited companies only."),
    Account("3010", "Capital Introduced", _E, V.OUTSIDE_SCOPE, "Money the owners put into the business."),
    *(Account(f"301{n}", f"Capital Introduced {n + 1}", _E, V.OUTSIDE_SCOPE,
              f"Money partner or member number {n + 1} put into the business.") for n in (1, 2, 3)),
    Account("3100", "Owner's Capital Account", _E, V.OUTSIDE_SCOPE,
            "The owners' stake in the business, where each year's profit is closed."),
    *(Account(f"310{n}", f"Owner's Capital Account {n + 1}", _E, V.OUTSIDE_SCOPE,
              f"Partner number {n + 1}'s stake in the business, where their share of each year's profit is closed.")
      for n in (1, 2, 3)),
    Account("3200", "Retained Earnings", _E, V.OUTSIDE_SCOPE,
            "Profits kept in the company from earlier years, where each year's profit is closed."),
    Account("3250", "Dividends", _E, V.OUTSIDE_SCOPE,
            "Dividends paid out to the company's shareholders. Limited companies only."),
    Account("3260", "Drawings", _E, V.OUTSIDE_SCOPE, "Money the owner takes out for personal use."),
    *(Account(f"326{n}", f"Drawings {n + 1}", _E, V.OUTSIDE_SCOPE,
              f"Money partner number {n + 1} takes out for personal use.") for n in (1, 2, 3)),
    Account("4000", "Sales", _I, V.STANDARD, "Money from customers for the business's goods or services.", sa103=15),
    Account("4900", "Other Income", _I, V.STANDARD, "Income that is not from sales, rent or bank interest."),
    Account("4902", "Bank Interest Received", _I, V.EXEMPT, "Interest the bank pays on the business's accounts.",
            heading=_H.INTEREST_RECEIVABLE, tax=_T.NON_TRADING),
    Account("4904", "Rent Income", _I, V.EXEMPT,
            "Rent from tenants of property the business lets, paid directly or through a letting agent.",
            tax=_T.NON_TRADING),
    Account("4905", "Dividends Received", _I, V.OUTSIDE_SCOPE,
            "Dividends paid to the business on shares it holds in other companies.",
            heading=_H.INTEREST_RECEIVABLE, tax=_T.NON_TRADING),
    Account("4906", "Grants Received", _I, V.OUTSIDE_SCOPE,
            "Government and other grants paid to the business, such as from a council or Innovate UK."),
    Account("5000", "Purchases", _X, V.STANDARD, "Goods bought to resell or to make products that are sold; not things the business uses.",
            sa103=17),
    Account("5002", "Subcontractor Costs", _X, V.STANDARD,
            "Subcontractors paid to do work the business sells on to its customers.", sa103=18),
    Account("5200", "Opening Stock", _X, V.OUTSIDE_SCOPE, "The stock held at the start of the year, as a cost of the year.",
            sa103=17),
    Account("5201", "Closing Stock", _X, V.OUTSIDE_SCOPE,
            "The stock held at the year end, taken off the year's costs (a credit).", sa103=17),
    Account("6201", "Advertising and Marketing", _X, V.STANDARD,
            "Advertising, marketing, promotions, online ads and sponsorship.", sa103=24),
    Account("7000", "Gross Wages", _X, V.OUTSIDE_SCOPE, "Salaries and wages paid to employees.", sa103=19),
    Account("7001", "Directors' Salaries", _X, V.OUTSIDE_SCOPE, "Salaries paid to the company's directors. Limited companies only.",
            sa103=19),
    Account("7006", "Employer's National Insurance", _X, V.OUTSIDE_SCOPE,
            "National Insurance the employer pays on its staff's wages.", sa103=19),
    Account("7007", "Employer's Pension Contributions", _X, V.OUTSIDE_SCOPE,
            "Pension contributions the employer pays for its staff.", sa103=19),
    Account("7100", "Rent", _X, V.EXEMPT, "Rent for offices or other premises; VAT only if the landlord opted to tax.",
            sa103=21),
    Account("7103", "Business Rates", _X, V.OUTSIDE_SCOPE, "Business rates paid to the local council.", sa103=21),
    Account("7200", "Electricity", _X, V.STANDARD, "Electricity for the premises.", sa103=21),
    Account("7201", "Gas", _X, V.STANDARD, "Gas for the premises.", sa103=21),
    Account("7202", "Water", _X, V.STANDARD, "Water and sewerage charges for the premises.", sa103=21),
    Account("7300", "Fuel and Oil", _X, V.STANDARD, "Fuel for business vehicles.", sa103=20, tax=_T.CHECK),
    Account("7301", "Vehicle Repairs and Servicing", _X, V.STANDARD, "Servicing, MOTs, tyres and repairs for business vehicles.",
            sa103=20, tax=_T.CHECK),
    Account("7302", "Vehicle Licences", _X, V.OUTSIDE_SCOPE, "Vehicle tax for business vehicles.", sa103=20, tax=_T.CHECK),
    Account("7303", "Vehicle Insurance", _X, V.EXEMPT, "Insurance for business vehicles.", sa103=20, tax=_T.CHECK),
    Account("7304", "Vehicle Leasing", _X, V.STANDARD,
            "Lease or contract hire rentals on vehicles; only half the VAT on a car lease can be reclaimed.",
            sa103=20, tax=_T.CHECK),
    Account("7305", "Mileage Allowance", _X, V.OUTSIDE_SCOPE,
            "Mileage paid for business journeys in a person's own vehicle, such as 45p a mile.", sa103=20),
    Account("7400", "Travel", _X, V.STANDARD, "Fares and parking for work travel; rail, bus and air fares are zero-rated.",
            sa103=20),
    Account("7402", "Hotels", _X, V.STANDARD, "Places to stay when travelling for work.", sa103=20),
    Account("7403", "Entertainment", _X, V.STANDARD,
            "Meals and drinks with clients or other guests; VAT can't be reclaimed. Staff only: Staff Welfare.", reclaim_vat=False,
            sa103=24, tax=_T.DISALLOWABLE),
    Account("7406", "Subsistence", _X, V.STANDARD, "Meals, snacks and drinks bought while working, from cafés, restaurants or takeaways.",
            sa103=20),
    Account("7500", "Printing", _X, V.STANDARD, "Printing and copying done by others.", sa103=23),
    Account("7501", "Postage and Carriage", _X, V.STANDARD, "Parcels, couriers and delivery charges; Royal Mail stamps show no VAT.",
            sa103=23),
    Account("7502", "Telephone and Internet", _X, V.STANDARD, "Phone, mobile and broadband services.", sa103=23,
            tax=_T.CHECK),
    Account("7504", "Office Stationery", _X, V.STANDARD, "Paper, pens, ink and other small office supplies.", sa103=23),
    Account("7600", "Legal Fees", _X, V.STANDARD, "Solicitors, legal advice and company filing fees.", sa103=28),
    Account("7601", "Accountancy Fees", _X, V.STANDARD, "Accountants, bookkeeping and audit.", sa103=28),
    Account("7602", "Consultancy Fees", _X, V.STANDARD, "Consultants and contractors working for the business.", sa103=28),
    Account("7603", "Professional Fees", _X, V.STANDARD, "Other professional services, such as surveyors or recruiters.",
            sa103=28),
    Account("7700", "Equipment Hire", _X, V.STANDARD, "Renting or leasing equipment.", sa103=30),
    Account("7800", "Repairs and Renewals", _X, V.STANDARD, "Repairing and maintaining premises or equipment, including tools, hardware and building supplies.",
            sa103=22),
    Account("7801", "Cleaning", _X, V.STANDARD, "Cleaning services and supplies for the premises.", sa103=30),
    Account("7900", "Bank Interest Paid", _X, V.EXEMPT, "Interest charged on overdrafts.",
            heading=_H.INTEREST_PAYABLE, sa103=25),
    Account("7901", "Bank Charges", _X, V.EXEMPT, "Bank account fees and card processing fees.", sa103=26),
    Account("7903", "Loan and Hire Purchase Interest", _X, V.EXEMPT,
            "Interest and finance charges on business loans, hire purchase and finance leases.",
            heading=_H.INTEREST_PAYABLE, sa103=25),
    Account("7905", "Exchange Differences", _X, V.OUTSIDE_SCOPE,
            "Gains and losses from exchange rates when an amount in another currency is paid.", sa103=26),
    Account("8000", "Depreciation", _X, V.OUTSIDE_SCOPE, "The cost of equipment and vehicles used up in the year.",
            sa103=29, tax=_T.DISALLOWABLE),
    Account("8002", "Amortisation", _X, V.OUTSIDE_SCOPE, "Goodwill and other intangible assets written off in the year.",
            sa103=29, tax=_T.CHECK),
    Account("8010", "Profit or Loss on Disposal of Assets", _X, V.OUTSIDE_SCOPE,
            "Sale proceeds of an asset less its value in the books; a profit is a credit.",
            sa103=29, tax=_T.DISALLOWABLE),
    Account("8100", "Bad Debts", _X, V.OUTSIDE_SCOPE, "Money customers owe that will not be paid, written off.",
            sa103=27, tax=_T.CHECK),
    Account("8200", "Donations", _X, V.OUTSIDE_SCOPE, "Gifts to charities.", tax=_T.DISALLOWABLE),
    Account("8201", "Subscriptions and Software", _X, V.STANDARD, "Software, online services, memberships and publications paid for regularly.",
            sa103=23),
    Account("8203", "Training", _X, V.STANDARD, "Courses and professional development."),
    Account("8204", "Insurance", _X, V.EXEMPT, "Business insurance premiums.", sa103=21),
    Account("8205", "Refreshments", _X, V.ZERO, "Tea, coffee, milk, snacks and groceries for the workplace, such as from a supermarket."),
    Account("8206", "Staff Welfare", _X, V.STANDARD, "Staff-only meals, drinks, nights out and parties; gifts, eye tests and other costs of looking after staff.",
            sa103=19),
    Account("8207", "Sundry Expenses", _X, V.STANDARD, "Small business costs that fit no other account."),
    Account("8208", "Use of Home", _X, V.OUTSIDE_SCOPE,
            "A share of the owner's home costs for working from home, or a flat rate allowance for it.", sa103=21),
    Account("8250", "Fines and Penalties", _X, V.OUTSIDE_SCOPE,
            "Parking, speeding and other fines and penalties; not tax-deductible.", tax=_T.DISALLOWABLE),
    Account("8800", "Corporation Tax Charge", _X, V.OUTSIDE_SCOPE,
            "The year's corporation tax as a cost. Limited companies only.", heading=_H.TAX, tax=_T.DISALLOWABLE),
    Account("9998", "Suspense", _L, V.OUTSIDE_SCOPE, "Anything that cannot be placed yet; a person will check it."),
)

BY_CODE: dict[str, Account] = {a.code: a for a in CHART}
BANK, SALES_VAT, PURCHASE_VAT, SUSPENSE = "1200", "2200", "2201", "9998"
DEBTORS, CREDITORS, STAFF_EXPENSES = "1100", "2100", "2110"
SHARES, DIVIDENDS, RETAINED = "3000", "3250", "3200"
NET_WAGES, PAYE, PENSION = "2220", "2210", "2230"
WAGES = frozenset({"7000", "7001"})   # Gross Wages, Directors' Salaries: booked from the payroll report
VAT_LIABILITY = "2202"
CIS_DEDUCTED, CIS_PAYABLE = "1104", "2215"   # the Construction Industry Scheme's tax, withheld from the business or by it
LOANS = "2300"
CLEARING = "1250"   # a payment processor's payouts, until its payout report books what they are made of
HOTELS = "7402"
STOCK_MOVEMENT = ("5200", "5201")   # opening and closing stock, journalled at the year end against 1001 Stock
DISPOSALS = "8010"                  # the profit or loss when a fixed asset is sold or scrapped
# What is borrowed, and the account at the year end for the part of it due after more than one year (the balance
# sheet shows the two apart): repayments are booked to the first, and a year-end journal moves the long-term part.
LONG_TERM: dict[str, str] = {LOANS: "2301", "2310": "2311"}
# The bank accounts and cards a client may have, in the order they are added. Only a client's own are offered.
BANK_SLOTS: dict[str, tuple[str, ...]] = {"current": ("1200", "1201", "1202"), "savings": ("1210", "1211"),
                                          "credit_card": ("1240", "1241"), "petty_cash": ("1230",)}
ALL_BANK_CODES = frozenset(code for codes in BANK_SLOTS.values() for code in codes)
CARDS = frozenset(BANK_SLOTS["credit_card"])
# Accounts where only half the VAT on a purchase can be reclaimed: a car lease (contract hire) with private use available.
HALF_VAT_RECLAIMED = frozenset({"7304"})
# Equipment under a client's capitalisation threshold is a cost: the account it is booked to instead.
SMALL_EQUIPMENT_COST = {"0020": "7504", "0030": "7504", "0040": "7504"}


# Each owner's own accounts, by their slot (0 to 3): a company's directors, a partnership's partners, an LLP's
# members. Slot 0's are the chart's first, so a client with no owners listed books to them as it always has.
MAX_OWNERS = 4
DIRECTORS_LOANS = ("2250", "2251", "2252", "2253")
MEMBERS_CURRENT = ("2260", "2261", "2262", "2263")    # an LLP member's: profit allocated to them, less drawings
CAPITALS = ("3010", "3011", "3012", "3013")           # capital introduced
OWNERS_CAPITALS = ("3100", "3101", "3102", "3103")    # a partner's (or sole trader's): where their profit share closes
OWNER_DRAWINGS = ("3260", "3261", "3262", "3263")
OWNER_CODES = frozenset({*DIRECTORS_LOANS, *MEMBERS_CURRENT, *CAPITALS, *OWNERS_CAPITALS, *OWNER_DRAWINGS})
OWNER_WORDS = {"limited_company": "director", "partnership": "partner", "llp": "member"}


def owner_slots(business_type: Optional[str]) -> dict[str, tuple[str, ...]]:
    """An owner's accounts by what they are for, each by slot: "capital" (money they put in), "drawings" (money they
    take out) and "profit" (where their share of the year's profit closes; none for a company, whose profit closes
    to retained earnings). A director's all go through their loan account; an LLP member draws on their current
    account, which their profit is allocated to (the LLP SORP's automatic division)."""
    if business_type == "limited_company":
        return {"capital": DIRECTORS_LOANS, "drawings": DIRECTORS_LOANS}
    if business_type == "llp":
        return {"capital": CAPITALS, "drawings": MEMBERS_CURRENT, "profit": MEMBERS_CURRENT}
    return {"capital": CAPITALS, "drawings": OWNER_DRAWINGS, "profit": OWNERS_CAPITALS}


def owner_code(business_type: Optional[str], role: str, slots: tuple[int, ...] = ()) -> str:
    """The account for role of the business's first owner (the first of slots; slot 0 when none are listed)."""
    return owner_slots(business_type)[role][slots[0] if slots else 0]


def owner_codes(business_type: Optional[str], slots: tuple[int, ...] = ()) -> frozenset[str]:
    """Every account of the business's owners in slots (slot 0 when none are listed)."""
    return frozenset(codes[n] for codes in owner_slots(business_type).values() for n in (slots or (0,)))


# Shown on the side their balance is on: Suspense, and a director's loan the director owes (a debtor of the company).
SIDED = frozenset({SUSPENSE, *DIRECTORS_LOANS})


def heading_for(code: str, balance) -> Heading:
    """Where an account with this balance (a debit positive) goes in the accounts."""
    if code in SIDED:
        return Heading.DEBTORS if balance > 0 else Heading.CREDITORS_SHORT
    return BY_CODE[code].heading


def pays_cards(own: tuple[str, ...], besides: Optional[str] = None) -> Optional[str]:
    """Of a client's own accounts, the one its card is paid off from: its first current account, or failing that its
    first account that is neither a card nor `besides`. None when it has no such account."""
    return next((c for c in own if c in BANK_SLOTS["current"] and c != besides),
                next((c for c in own if c not in CARDS and c != besides), None))
# The VAT accounts, which the trial balance lists last, after every other account.
VAT_ACCOUNTS = frozenset({SALES_VAT, PURCHASE_VAT, VAT_LIABILITY})
# Equipment kept for use, which a person or the AI can move a purchase to (not vehicles: a large payment to a garage
# is far more often a repair), and the cost accounts equipment ends up on by mistake: a large purchase on one of
# these is checked (checks.asset_check). Purchases is left out: stock is bought in large amounts all the time.
FIXED_ASSETS = frozenset({"0020", "0030", "0040"})
ASSET_CANDIDATES = frozenset({"7504", "7800", "7700", "7502"})
# Picked by the ledger, never chosen for a row: the VAT control accounts (the ledger splits VAT itself), the
# accounts for what is owed (from the document type), and the accounts only year-end work posts to (depreciation,
# accruals, prepayments, the tax charge and where profit closes). The bank accounts, 1200 too, are the other side of
# each posting; a row is coded to one only as a transfer from another of the client's own (see choosable).
_LEDGER_ONLY = frozenset({SALES_VAT, PURCHASE_VAT, DEBTORS, CREDITORS, STAFF_EXPENSES, CIS_DEDUCTED, CIS_PAYABLE,
                          "0002", "0011", "0016", "0021", "0031", "0041", "0051", "0056", "1001", "1103", "2105",
                          "2109", *OWNERS_CAPITALS, RETAINED, "7905", "8000", "8100", "8800",
                          *STOCK_MOVEMENT, "8002", DISPOSALS, *LONG_TERM.values()})
# Accounts that exist for a limited company only (its owners' loan accounts are among the owners' accounts).
_COMPANY_ONLY = frozenset({"2320", SHARES, DIVIDENDS, "7001", "8800"})
# Owners as choosable takes them: each one's slot and name, in the order they are listed.
Owners = tuple[tuple[int, str], ...]


def model_accounts() -> tuple[Account, ...]:
    """Every account a row can be coded to, whatever the kind of business and its bank accounts."""
    return tuple(a for a in CHART if a.code not in _LEDGER_ONLY)


def choosable(business_type: Optional[str] = None, bank_codes: tuple[str, ...] = (),
              owners: Owners = ()) -> tuple[Account, ...]:
    """The accounts offered for one client. A limited company's owners go through their director's loan accounts,
    shares and dividends; a partnership's and LLP's through each partner's or member's own capital and drawings (an
    LLP member's current account); a sole trader's, and anyone's when the kind of business isn't known (an analysis
    without a client), through Drawings and Capital Introduced. Only the owners listed have accounts offered, each
    named after them (the first's alone when none are listed). Of the bank accounts and cards only the client's own
    are offered (petty cash always), 1200 too, for a transfer from another of them; without a client, the first
    deposit account too."""
    hidden = frozenset() if business_type == "limited_company" else _COMPANY_ONLY
    offered_banks = set(bank_codes) if bank_codes else {"1210"}
    hidden = hidden | (ALL_BANK_CODES - offered_banks - {"1230"})
    hidden = hidden | (OWNER_CODES - owner_codes(business_type, tuple(slot for slot, _ in owners)))
    names = owner_names(business_type, owners)
    return tuple(_named(a, names.get(a.code)) for a in model_accounts() if a.code not in hidden)


def _named(account: Account, owner: Optional[str]) -> Account:
    """An owner's account as it is offered: named after them, its definition the first owner's said of them."""
    if owner is None:
        return account
    first = next(BY_CODE[codes[0]] for codes in (DIRECTORS_LOANS, MEMBERS_CURRENT, CAPITALS, OWNERS_CAPITALS,
                                                  OWNER_DRAWINGS) if account.code in codes)
    return replace(account, name=f"{first.name} — {owner}", definition=f"{owner}'s: {first.definition}")


def owner_names(business_type: Optional[str], owners: Owners) -> dict[str, str]:
    """The owners' names by the codes of their accounts."""
    return {codes[slot]: name for slot, name in owners for codes in owner_slots(business_type).values() if name}


def reserve_for(business_type: str) -> str:
    """Where a year's profit closes when the business lists no owners: retained earnings for a company, the first
    member's current account for an LLP (its profit is allocated to its members), the owner's capital otherwise."""
    return RETAINED if business_type == "limited_company" else owner_code(business_type, "profit")


def profit_split(business_type: str, shares: tuple[tuple[int, Optional[Decimal]], ...], profit: Decimal
                 ) -> dict[str, Decimal]:
    """A year's profit (or loss) as it closes, by account: a company's to retained earnings; a partnership's and an
    LLP's to each partner's or member's own account by their share in percent (shares: each owner's slot and
    share), the pennies left by rounding to the first. Without shares given they share equally, as the Partnership
    Act 1890 and the LLP default rules have it; with no owners listed, all goes to the first owner's account."""
    if business_type == "limited_company" or not shares:
        return {reserve_for(business_type): profit}
    if any(share is None for _, share in shares):
        shares = tuple((slot, Decimal(100) / len(shares)) for slot, _ in shares)
    codes = owner_slots(business_type)["profit"]
    split = {codes[slot]: (profit * share / 100).quantize(Decimal("0.01"), ROUND_HALF_UP) for slot, share in shares[1:]}
    first = codes[shares[0][0]]
    return {first: profit - sum(split.values(), Decimal("0.00")), **split}
