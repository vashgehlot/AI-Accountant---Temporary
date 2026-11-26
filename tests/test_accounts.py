import json
from pathlib import Path

from ledgersync.accounts import (ALL_BANK_CODES, BANK, BANK_SLOTS, BY_CODE, CHART, LONG_TERM, OWNER_CODES, SA103_BOXES, AccountType,
                                 Heading, TaxTreatment, choosable, heading_for, model_accounts, reserve_for)

FIXTURES = Path(__file__).parent.parent / "eval" / "fixtures"


def test_codes_are_unique_four_digit_strings():
    codes = [a.code for a in CHART]
    assert len(codes) == len(set(codes)) and all(len(c) == 4 and c.isdigit() for c in codes)


def test_every_code_the_eval_expects_exists():
    used = {r["account_code"] for p in FIXTURES.glob("*/expected.json") for r in json.loads(p.read_text())["rows"]}
    assert used and used <= set(BY_CODE)


def test_posting_accounts_have_the_right_types():
    assert BY_CODE["1200"].type == AccountType.ASSET
    assert BY_CODE["2200"].type == BY_CODE["2201"].type == AccountType.LIABILITY
    assert BY_CODE["4000"].type == AccountType.INCOME and BY_CODE["7502"].type == AccountType.EXPENSE


def test_1200_is_the_bank_account():
    # Every payment's other side posts to 1200: renamed "Debtors", a rent payment showed as money owed to us.
    assert (BANK, BY_CODE["1200"].name, BY_CODE["1210"].name) == ("1200", "Bank Current Account", "Bank Deposit Account")
    assert BY_CODE["1210"].type == AccountType.ASSET


def test_debtors_and_creditors_have_their_own_codes():
    assert (BY_CODE["1100"].name, BY_CODE["1100"].type) == ("Debtors", AccountType.ASSET)
    assert (BY_CODE["2100"].name, BY_CODE["2100"].type) == ("Creditors", AccountType.LIABILITY)


def test_a_model_may_choose_any_account_but_the_control_accounts():
    # The ledger splits VAT itself. What is owed (Debtors, Creditors, Expenses Owed to Staff) is picked by the
    # ledger from the document type. So are the accounts only year-end work posts to, and where a year's profit
    # closes, and the CIS tax withheld on an invoice (from the invoice's CIS deduction). The bank, 1200, is offered
    # only to a client with another account, for a transfer between them.
    ledger_only = {"2200", "2201", "1100", "2100", "2110", "0031", "0041", "0051", "0056", "1103", "2109",
                   "3100", "3200", "8000", "8800", "1104", "2215",
                   "0021", "1001", "2105", "7905", "8100",   # stock, deferred income, bad debts: journals only
                   "0002", "0011", "0016", "8002",           # depreciation and amortisation
                   "5200", "5201", "8010", "2301", "2311",   # stock movement, disposals, long-term debt
                   "3101", "3102", "3103"}                   # where the other partners' profit closes
    assert {a.code for a in model_accounts()} == set(BY_CODE) - ledger_only
    # Without a business type (an analysis with no client) a company's own accounts are left out, and so are
    # the bank accounts and cards beyond the first.
    company_only = {"2320", "3000", "3250", "7001"}
    extra_banks = {"1200", "1201", "1202", "1211", "1240", "1241"}
    # Of the owners' accounts, only the first owner's capital and drawings.
    other_owners = OWNER_CODES - {"3010", "3260"}
    assert {a.code for a in choosable()} == (set(BY_CODE) - ledger_only - company_only - extra_banks
                                             - other_owners)


def test_expenses_owed_to_staff_is_a_liability_of_its_own():
    # A claim is owed to the employee, not to a trade supplier, so it stays out of 2100 Creditors.
    assert (BY_CODE["2110"].name, BY_CODE["2110"].type) == ("Expenses Owed to Staff", AccountType.LIABILITY)


def test_every_account_has_a_short_definition():
    # The model is told what belongs in each account; short keeps the prompt within the free plan.
    assert [a.code for a in CHART if not a.definition.strip() or len(a.definition) > 110] == []


def test_vat_on_entertainment_and_cars_is_blocked_but_vans_reclaim_it():
    # UK VAT: business entertainment, and cars not used only for business, can't have their VAT reclaimed.
    assert [code for code, a in BY_CODE.items() if not a.reclaim_vat] == ["0050", "7403"]
    assert (BY_CODE["0050"].name, BY_CODE["0055"].name, BY_CODE["0055"].type) == ("Cars", "Vans", AccountType.ASSET)


def test_a_limited_company_books_its_owners_through_the_directors_loan_account():
    company = {a.code for a in choosable("limited_company")}
    assert "2250" in company and not {"3010", "3260"} & company
    for kind in ("sole_trader", "partnership"):
        others = {a.code for a in choosable(kind)}
        assert {"3010", "3260"} <= others and "2250" not in others
    # An LLP member draws on their current account, which their profit is allocated to.
    llp = {a.code for a in choosable("llp")}
    assert {"3010", "2260"} <= llp and not {"2250", "3260"} & llp
    assert (BY_CODE["2250"].name, BY_CODE["2250"].type) == ("Director's Loan Account", AccountType.LIABILITY)


def test_a_company_is_offered_shares_dividends_and_directors_salaries():
    codes = {a.code for a in choosable("limited_company")}
    assert {"3000", "3250", "7001", "2250", "2320"} <= codes and not {"3010", "3260", "3100", "3200"} & codes


def test_a_sole_trader_is_offered_capital_and_drawings_only():
    codes = {a.code for a in choosable("sole_trader")}
    assert {"3010", "3260"} <= codes and not {"3000", "3250", "7001", "2250", "2320"} & codes


def test_only_the_clients_own_bank_accounts_are_offered():
    codes = {a.code for a in choosable("limited_company", bank_codes=("1200", "1240"))}
    assert {"1200", "1240"} <= codes and not {"1201", "1211", "1241"} & codes
    assert "1230" in codes   # petty cash is always offered


def test_profit_closes_to_retained_earnings_or_the_owners_capital():
    assert reserve_for("limited_company") == "3200" and reserve_for("llp") == "2260"
    assert reserve_for("sole_trader") == reserve_for("partnership") == "3100"


def test_the_bank_slots_are_all_in_the_chart_and_in_the_schema():
    assert ALL_BANK_CODES == {c for codes in BANK_SLOTS.values() for c in codes} and ALL_BANK_CODES <= set(BY_CODE)
    assert BY_CODE["1240"].type == BY_CODE["1241"].type == AccountType.LIABILITY
    assert ALL_BANK_CODES <= {a.code for a in model_accounts()}


def test_the_new_accounts_have_the_codes_names_and_types_the_site_uses():
    expected = {"3000": ("Ordinary Shares", AccountType.EQUITY), "3010": ("Capital Introduced", AccountType.EQUITY),
                "3250": ("Dividends", AccountType.EQUITY), "2220": ("Net Wages", AccountType.LIABILITY),
                "2320": ("Corporation Tax", AccountType.LIABILITY), "8250": ("Fines and Penalties", AccountType.EXPENSE),
                "7006": ("Employer's National Insurance", AccountType.EXPENSE)}
    assert {c: (BY_CODE[c].name, BY_CODE[c].type) for c in expected} == expected


def test_every_account_has_a_heading_and_every_income_and_cost_a_tax_treatment():
    assert [a.code for a in CHART if a.heading is None] == []
    profit_and_loss = [a for a in CHART if a.type in (AccountType.INCOME, AccountType.EXPENSE)]
    assert [a.code for a in profit_and_loss if a.tax is None] == []
    assert [a.code for a in CHART if a not in profit_and_loss and (a.tax or a.sa103)] == []


def test_trading_income_and_costs_have_an_sa103_box_and_the_rest_none():
    # Interest and dividends received, rent and the corporation tax charge are not trading profit.
    boxless = {a.code for a in CHART if a.type in (AccountType.INCOME, AccountType.EXPENSE) and a.sa103 is None}
    assert boxless == {"4902", "4904", "4905", "8800"}
    assert {a.sa103 for a in CHART if a.sa103} <= set(SA103_BOXES)
    assert (BY_CODE["4000"].sa103, BY_CODE["5000"].sa103, BY_CODE["5002"].sa103, BY_CODE["8000"].sa103) == (15, 17, 18, 29)


def test_what_tax_never_allows_is_marked_disallowable():
    disallowable = {a.code for a in CHART if a.tax == TaxTreatment.DISALLOWABLE}
    assert disallowable == {"7403", "8000", "8010", "8200", "8250", "8800"}
    assert {"7300", "7304", "7502", "8100"} <= {a.code for a in CHART if a.tax == TaxTreatment.CHECK}


def test_the_headings_follow_the_companies_act_formats():
    of = lambda code: BY_CODE[code].heading
    assert (of("4000"), of("4904"), of("4902"), of("5201"), of("7403")) == (
        Heading.TURNOVER, Heading.OTHER_INCOME, Heading.INTEREST_RECEIVABLE, Heading.COST_OF_SALES,
        Heading.ADMINISTRATIVE)
    assert (of("7900"), of("7903"), of("8800")) == (Heading.INTEREST_PAYABLE, Heading.INTEREST_PAYABLE, Heading.TAX)
    assert (of("0001"), of("0010"), of("0060"), of("1001"), of("1250"), of("1230")) == (
        Heading.INTANGIBLE, Heading.TANGIBLE, Heading.INVESTMENTS, Heading.STOCKS, Heading.DEBTORS, Heading.CASH)
    # A credit card is owed, though its code is among the banks'.
    assert of("1240") == of("1241") == of("2300") == Heading.CREDITORS_SHORT
    assert {BY_CODE[c].heading for c in LONG_TERM.values()} == {Heading.CREDITORS_LONG}
    assert set(LONG_TERM) == {"2300", "2310"}


def test_suspense_and_the_directors_loan_go_on_the_side_their_balance_is_on():
    assert heading_for("2250", 500) == heading_for("9998", 1) == Heading.DEBTORS
    assert heading_for("2250", -500) == heading_for("9998", -1) == Heading.CREDITORS_SHORT
    assert heading_for("2100", 500) == Heading.CREDITORS_SHORT


def test_the_codes_are_in_order():
    codes = [a.code for a in CHART]
    assert codes == sorted(codes)


def test_staff_only_hospitality_is_staff_welfare_and_entertainment_is_for_guests():
    # A team's drinks were coded to Entertainment, losing their VAT: the definitions must tell them apart.
    welfare, entertainment = BY_CODE["8206"].definition.lower(), BY_CODE["7403"].definition.lower()
    assert "drinks" in welfare and "staff" in welfare
    assert "staff welfare" in entertainment
