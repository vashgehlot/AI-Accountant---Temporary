"""Kestrel & Finch Digital Ltd: a made-up web agency in Bristol (limited company, VAT registered, 2 directors and
5 staff). Its definition, and the deals of its years."""
from __future__ import annotations

import random
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal as D

from testbooks.dates import (add_months, add_working_days, ct_due, month_end, next_working_day,
                             previous_working_day)
from testbooks.engine.make import deal, doc, gross_line, held_vat, jl, line, m, pay
from testbooks.places import card_town
from testbooks.engine.model import (Asset, Client, Deal, Employee, MoneyAccount, OpenItem, Opening, Owner, Period,
                                    Policies, Query, VatTotals)

NAME = "Kestrel & Finch Digital Ltd"

# Planted cases that live outside any one deal: a statement file's layout (EC-0152), the extra export across the
# year end (EC-0501), and two year-end adjustments (EC-0506 the known accrual, EC-0707 the corporation tax charge).
STEP1_OUTSIDE_DEALS: tuple[str, ...] = ("EC-0152", "EC-0501", "EC-0506", "EC-0707")

# Statement exports the client sends besides the monthly ones: (account, start, end, cases).
EXTRA_EXPORTS = (("hsbc", date(2024, 3, 15), date(2024, 4, 14), ("EC-0501",)),)

# The cases planted in the year to 31 Mar 2024 (build step 1).
STEP1_CASES: tuple[str, ...] = tuple(sorted((
    "EC-0137", "EC-0152", "EC-0208", "EC-0210", "EC-0211", "EC-0225", "EC-0226", "EC-0230", "EC-0244",
    "EC-0301", "EC-0303", "EC-0314", "EC-0316", "EC-0318", "EC-0330", "EC-0331", "EC-0334", "EC-0346",
    "EC-0352", "EC-0363", "EC-0372", "EC-0373", "EC-0375", "EC-0380", "EC-0401", "EC-0418", "EC-0420",
    "EC-0422", "EC-0430", "EC-0435", "EC-0437", "EC-0438", "EC-0501", "EC-0502", "EC-0505", "EC-0506",
    "EC-0512", "EC-0513", "EC-0518", "EC-0519", "EC-0521", "EC-0601", "EC-0602", "EC-0705", "EC-0706",
    "EC-0707", "EC-0708",
)))

_BALANCES = {
    "0030": "9600.00", "0031": "-6400.00", "0040": "4850.00", "0041": "-2910.00",
    "1100": "26400.00", "1103": "6558.46", "1200": "41236.18", "1210": "20000.00", "1240": "-1384.20",
    "1250": "640.00",
    "2100": "-5880.00", "2109": "-2400.00", "2200": "-10560.00", "2201": "1980.00", "2202": "-27100.00",
    "2210": "-5812.36", "2230": "-1067.12", "2250": "-1200.00", "2320": "-14210.00",
    "3000": "-100.00", "3200": "-32240.96",
}


def define() -> Client:
    opening = Opening(
        as_at=date(2023, 3, 31),
        balances={code: D(v) for code, v in sorted(_BALANCES.items())},
        open_items=(
            OpenItem("debtor", "Brightwater Homes Ltd", "KF-0981", date(2023, 3, 1), D("7200.00")),
            OpenItem("debtor", "Northgate Dental Group", "KF-0984", date(2023, 3, 1), D("4800.00")),
            OpenItem("debtor", "Lowther Interiors Ltd", "KF-0990", date(2023, 3, 15), D("8400.00")),
            OpenItem("debtor", "Calder Valley Cycles", "KF-0993", date(2023, 3, 27), D("6000.00")),
            OpenItem("creditor", "Wyvern Freelance Studio", "INV-207", date(2023, 3, 20), D("2400.00")),
            OpenItem("creditor", "Avonside Print Ltd", "4471", date(2023, 3, 24), D("1080.00")),
            OpenItem("creditor", "Cabot Office Supplies", "99812", date(2023, 3, 28), D("600.00")),
            OpenItem("creditor", "Brunel Energy", "BE-55120", date(2023, 3, 15), D("1800.00")),
        ),
        assets=(
            Asset("A01", "3 laptops", "computer", date(2021, 5, 10), D("3600.00")),
            Asset("A02", "4 laptops", "computer", date(2022, 1, 18), D("6000.00")),
            Asset("A03", "Office furniture", "furniture", date(2020, 9, 1), D("4850.00")),
        ),
        vat_brought_in=VatTotals(D("10560.00"), D("1980.00"), D("52800.00"), D("9900.00")),
        true_differences={"2202": D("-312.00")},
        prior_pl={
            "Turnover": D("598400.00"),
            "Other income": D("310.00"),
            "Cost of raw materials and consumables": D("0.00"),
            "Staff costs": D("296120.00"),
            "Depreciation and other amounts written off assets": D("4170.00"),
            "Other charges": D("223630.00"),
            "Tax": D("14210.00"),
        },
        reversals=(
            ("1103", "8204", D("1020.00")),
            ("1103", "7100", D("5538.46")),
            ("2109", "7601", D("2400.00")),
        ),
    )
    return Client(
        id="agency",
        name=NAME,
        kind="ltd",
        address="Unit 4, 22 Harbour Wharf, Bristol BS1 6XX",
        company_number="11873402",
        vat_number="284619331",
        periods=(
            Period(date(2023, 4, 1), date(2024, 3, 31)),
            Period(date(2024, 4, 1), date(2025, 3, 31)),
            Period(date(2025, 4, 1), date(2026, 3, 31)),
            Period(date(2026, 4, 1), date(2026, 10, 31), partial=True),
        ),
        vat_stagger=(2, 5, 8, 11),
        accounts=(
            MoneyAccount("hsbc", "Business current", "Severn Bank", "hsbc_csv", "1200"),
            MoneyAccount("savings", "Business deposit", "Severn Bank", "hsbc_csv", "1210"),
            MoneyAccount("amex", "Business card", "Calder Express", "amex_csv", "1240", statement_day=3),
            MoneyAccount("stripe", "Card payments", "Stripe", "stripe_csv", "1250"),
        ),
        employees=(
            Employee("d1", "Hannah Finch", True, D("12570"), False, "QQ104527A"),
            Employee("d2", "Omar Kestrel", True, D("12570"), False, "QQ218843B"),
            Employee("e1", "Priya Nair", False, D("28000"), True, "QQ335190C"),
            Employee("e2", "Daniel Okoro", False, D("32000"), True, "QQ447261D"),
            Employee("e3", "Megan Whitlow", False, D("36000"), True, "QQ559372A"),
            Employee("e4", "Tom Ashby", False, D("45000"), True, "QQ661483B"),
            Employee("e5", "Leah Morgan", False, D("52000"), True, "QQ773594C"),
        ),
        owners=(
            Owner("finch", "Hannah Finch", D("0.5"), "2250"),
            Owner("kestrel", "Omar Kestrel", D("0.5"), "2251"),
        ),
        policies=Policies(
            basis="accruals",
            capitalise_from=D("500"),
            accrue_from=D("250"),
            depreciation_years={"computer": 3, "furniture": 5},
            accounts_standard="FRS 105",
            pension_ee=D("0.05"),
            pension_er=D("0.03"),
            known_accruals=(("Accountancy fee 2023/24", "7601", D("3000.00"), date(2024, 3, 31)),),
        ),
        opening=opening,
    )


# --- The deals of its years --------------------------------------------------------------------------------------

HSBC, SAVINGS, AMEX, STRIPE = "hsbc", "savings", "amex", "stripe"
RETAINERS = (("Brightwater Homes Ltd", "6000.00"), ("Northgate Dental Group", "4000.00"))
CARD_CLIENTS = (("Hartley Yoga", "450.00"), ("Moss & Pine Florists", "600.00"), ("Quayside Physio", "750.00"),
                ("Redcliffe Bakehouse", "900.00"))
PROJECT_CLIENTS = ("Calder Valley Cycles", "Fenwick & Rowe Solicitors", "Clifton Climbing Centre",
                   "Harbour Lights Theatre", "Portway Logistics", "Mendip Cheese Co", "Avonmouth Marine Ltd")
PROJECT_WORK = ("Website design and build", "Brand identity project", "SEO and content sprint", "App prototype",
                "Website support and changes")
CAFES = ("Quayside Coffee Co", "The Bread Loft", "Marlowe's Kitchen", "Gantry Deli")
STATIONERS = ("Penhallow Stationers", "Inkwell & Co")
TAXIS = ("Bristol Blue Cars", "Avon Street Taxis")
RAIL = "Westway Rail"
GROCER = "Harbour Fresh Market"   # a made-up supermarket
QUARTER_DAYS = ((3, 25), (6, 24), (9, 29), (12, 25))
# Freelancers, none registered for VAT; the work is spread so none passes the registration threshold.
FREELANCERS = (("Wyvern Freelance Studio", "INV-", 208, "Freelance design and development"),
               ("Kite & Quill Design", "KQ-", 101, "Illustration and design"),
               ("Tobias Lane Development", "TL", 31, "Freelance web development"))


def _months(start: date, until: date):
    d = date(start.year, start.month, 1)
    while d <= until:
        yield d
        d = add_months(d, 1)


def _next_quarter_day(d: date) -> date:
    for month, day in QUARTER_DAYS:
        q = date(d.year, month, day)
        if q > d:
            return q
    return date(d.year + 1, *QUARTER_DAYS[0])


def _card(on: date, merchant: str, lines, account: str, post: date, rng: random.Random, cases=("EC-0401",),
          number: str | None = None, **extra) -> Deal:
    gross = sum(ln.gross for ln in lines)
    descriptor = f"{merchant.upper()} {card_town(merchant)}" + (" GB" if account == HSBC else "")
    receipt = doc("receipt", merchant, "", number or f"{rng.randint(1000, 9999)}-{rng.randint(10, 99)}", on, lines,
                  **extra)
    return deal("card_spend", on, merchant, "bank", lines=lines, docs=[receipt], cases=cases,
                payments=[pay(account, post, -gross, descriptor, "VIS" if account == HSBC else "")])


def _sale(on: date, customer: str, lines, payments=(), covers=None, cases=()) -> Deal:
    invoice = doc("sales_invoice", NAME, customer, "", on, lines, terms="30 days", due=on + timedelta(days=30))
    return deal("sale", on, customer, "debtor", lines=lines, payments=payments, docs=[invoice], covers=covers,
                cases=cases)


def _bill(on: date, supplier: str, number: str, lines, payments=(), covers=None, cases=(), **extra) -> Deal:
    invoice = doc("purchase_invoice", supplier, NAME, number, on, lines, **extra)
    return deal("purchase", on, supplier, "creditor", lines=lines, payments=payments, docs=[invoice],
                covers=covers, cases=cases)


def _retainers(start: date, until: date, rng: random.Random) -> list[Deal]:
    out = []
    for service in _months(start, add_months(until, 1)):
        billed = service if service <= date(2024, 3, 1) else date(*add_months(service, -1).timetuple()[:2], 25)
        if billed > until:
            continue
        covers = (service, month_end(service))
        advance = {"EC-0502", "EC-0706"} if billed == date(2024, 3, 25) else set()
        for customer, net in RETAINERS:
            lines = [line(f"Retainer, {service:%B %Y}", "4000", net)]
            gross = lines[0].gross
            paid = next_working_day(billed + timedelta(days=rng.randint(20, 35)))
            amount = gross
            if customer.startswith("Northgate") and service == date(2023, 9, 1):
                paid, amount = date(2023, 10, 10), gross - m("720.00")
            payments = [pay(HSBC, paid, amount, customer.upper(), "CR")] if paid <= until else []
            out.append(_sale(billed, customer, lines, payments, covers, advance))
        for customer, net in CARD_CLIENTS:
            lines = [line(f"Retainer, {service:%B %Y}", "4000", net)]
            gross = lines[0].gross
            charged = billed + timedelta(days=rng.randint(3, 10))
            cases = set(advance)
            if billed == date(2024, 3, 25) and customer in ("Hartley Yoga", "Moss & Pine Florists"):
                charged = date(2024, 3, 28) if customer == "Hartley Yoga" else date(2024, 3, 29)
                cases |= {"EC-0422"}
            text = f"{customer} retainer {service:%b %Y}"
            payments = [pay(STRIPE, charged, gross, text, "charge")] if charged <= until else []
            out.append(_sale(billed, customer, lines, payments, covers, cases))
            if charged <= until:
                fee = m(gross * D("0.015") + D("0.20"))
                fee_line = [line("Stripe fee", "7905", fee, "exempt")]
                out.append(deal("purchase", charged, "Stripe", "bank", lines=fee_line, cases=cases - advance,
                                payments=[pay(STRIPE, charged, -fee, text, "fee")]))
    return out


def _projects(start: date, until: date, rng: random.Random) -> list[Deal]:
    out = []
    for month in _months(start, until):
        for _ in range(rng.randint(2, 4)):
            on = date(month.year, month.month, rng.randint(3, 27))
            customer = rng.choice(PROJECT_CLIENTS)
            lines = [line(rng.choice(PROJECT_WORK), "4010", m(rng.randrange(4000, 18001, 50)))]
            paid = next_working_day(on + timedelta(days=rng.randint(15, 60)))
            payments = [pay(HSBC, paid, lines[0].gross, customer.upper(), "CR")] if paid <= until else []
            if on <= until:
                out.append(_sale(on, customer, lines, payments))
    return out


def _overheads(start: date, until: date, rng: random.Random) -> list[Deal]:
    out = []
    qd = date(2023, 6, 24)
    while qd <= until:
        nxt = _next_quarter_day(qd)
        lines = [line(f"Rent, {qd:%d %b %Y} to {nxt - timedelta(days=1):%d %b %Y}", "7100", "6000.00")]
        out.append(_bill(qd, "Harbourside Estates Ltd", f"HE-{qd:%y%m}", lines,
                         [pay(HSBC, next_working_day(qd), -lines[0].gross, "HARBOURSIDE ESTATES", "SO")],
                         covers=(qd, nxt - timedelta(days=1)), cases={"EC-0352"}, note="Option to tax: VAT charged"))
        qd = nxt
    for bill_day, first in ((date(2023, 7, 9), date(2023, 4, 1)), (date(2023, 10, 9), date(2023, 7, 1)),
                            (date(2024, 1, 9), date(2023, 10, 1)), (date(2024, 4, 9), date(2024, 1, 1))):
        if bill_day > until:
            continue
        lines = [line(f"Electricity, {first:%b} to {add_months(first, 2):%b %Y}", "7200",
                      m(D(rng.randint(150000, 210000)) / 100))]
        paid = next_working_day(bill_day + timedelta(days=14))
        out.append(_bill(bill_day, "Brunel Energy", f"BE-{bill_day:%y%m}9", lines,
                         [pay(HSBC, paid, -lines[0].gross, "BRUNEL ENERGY", "DD")] if paid <= until else [],
                         covers=(first, month_end(add_months(first, 2))),
                         cases={"EC-0505"} if bill_day == date(2024, 4, 9) else ()))
    for month in _months(start, until):
        covers = (month, month_end(month))
        phone = [line(f"Phone and broadband, {month:%B %Y}", "7502", "180.00")]
        out.append(_bill(month, "Northcliffe Telecom", f"NT{month:%y%m}01", phone,
                         [pay(HSBC, next_working_day(date(month.year, month.month, 5)), -phone[0].gross,
                              "NORTHCLIFFE TELECOM", "DD")], covers=covers))
        lease = [line(f"Car lease, {month:%B %Y} (plug-in hybrid, 32 g/km)", "7410", "420.00", "blocked_half",
                      "84.00")]
        out.append(_bill(month, "Avon Vehicle Leasing", f"AVL-{month:%y%m}", lease,
                         [pay(HSBC, next_working_day(month), -lease[0].gross, "AVON VEHICLE LEASING", "DD")],
                         covers=covers, cases={"EC-0334"}))
        if month < date(2024, 2, 1):
            soft = [line(f"Design software, {month:%B %Y}", "7550", "96.00")]
            out.append(deal("card_spend", month, "Lumenhaus Software Ltd", "bank", lines=soft, covers=covers,
                            docs=[doc("purchase_invoice", "Lumenhaus Software Ltd", NAME, f"LS-{month:%y%m}",
                                      month, soft)],
                            payments=[pay(AMEX, month, -soft[0].gross, f"LUMENHAUS SOFTWARE LTD {card_town('Lumenhaus Software Ltd')}")]))
        elif month == date(2024, 2, 1):
            soft = [line("Design software, annual plan 1 Feb 2024 to 31 Jan 2025", "7550", "1440.00")]
            out.append(deal("card_spend", month, "Lumenhaus Software Ltd", "bank", lines=soft,
                            covers=(month, date(2025, 1, 31)), cases={"EC-0225"},
                            docs=[doc("purchase_invoice", "Lumenhaus Software Ltd", NAME, f"LS-{month:%y%m}A",
                                      month, soft)],
                            payments=[pay(AMEX, month, -soft[0].gross, f"LUMENHAUS SOFTWARE LTD {card_town('Lumenhaus Software Ltd')}")]))
        cloud = [line(f"Cloud hosting, {month:%B %Y}", "7550", "250.00", "reverse_charge", "50.00")]
        out.append(deal("card_spend", month, "Corrib Cloud Ltd", "bank", lines=cloud, covers=covers,
                        cases={"EC-0316"},
                        docs=[doc("purchase_invoice", "Corrib Cloud Ltd", NAME, f"CC-{month:%Y%m}", month, cloud,
                                  note="Reverse charge: the customer accounts for the VAT", country="Ireland")],
                        payments=[pay(AMEX, month, -m("250.00"), f"CORRIB CLOUD LTD {card_town('Corrib Cloud Ltd', 'Ireland')}")]))
        on = date(month.year, month.month, 15)
        if on <= until:
            gbp = m(D("49.00") * D(rng.randint(7750, 8050)) / 10000)
            fee = m(gbp * D("0.0275"))
            posted = next_working_day(on + timedelta(days=1))
            usd = [line("Analytics subscription (USD 49.00)", "7550", gbp, "reverse_charge")]
            out.append(deal("card_spend", on, "Tallgrass Metrics Inc.", "bank", lines=usd, covers=covers,
                            cases={"EC-0318"},
                            docs=[doc("purchase_invoice", "Tallgrass Metrics Inc.", NAME, f"TM-{month:%Y%m}", on,
                                      currency="USD", printed={"net": m("49.00"), "vat": m(0), "gross": m("49.00")},
                                      country="United States")],
                            payments=[pay(HSBC, posted, -gbp, "TALLGRASS METRICS INC USD 49.00", "VIS")]))
            out.append(deal("purchase", on, "Severn Bank", "bank", cases={"EC-0318"},
                            lines=[line("Non-sterling transaction fee", "7901", fee, "exempt")],
                            payments=[pay(HSBC, posted, -fee, "NON-STG TRANS FEE", "VIS")]))
    return out


def _suppliers(start: date, until: date, rng: random.Random) -> list[Deal]:
    out = []
    numbers = {name: first for name, _, first, _ in FREELANCERS}
    for month in _months(start, until):
        for _ in range(rng.randint(2, 3)):
            name, prefix, _, work = rng.choice(FREELANCERS)
            on = date(month.year, month.month, rng.randint(1, 28))
            lines = [line(work, "5100", m(D(rng.randrange(150000, 550001, 2500)) / 100), "none")]
            paid = next_working_day(on + timedelta(days=30))
            out.append(_bill(on, name, f"{prefix}{numbers[name]}", lines,
                             [pay(HSBC, paid, -lines[0].gross, name.upper()[:18], "BP")] if paid <= until else [],
                             note="Not registered for VAT"))
            numbers[name] += 1
        for supplier, account, what in (("Avonside Print Ltd", "7500", "Printing"),
                                        ("Cabot Office Supplies", "7504", "Office supplies")):
            for _ in range(rng.randint(0, 2)):
                on = date(month.year, month.month, rng.randint(1, 28))
                lines = [line(what, account, m(D(rng.randint(10000, 120000)) / 100))]
                paid = next_working_day(on + timedelta(days=30))
                out.append(_bill(on, supplier, f"{rng.randint(4500, 99999)}", lines,
                                 [pay(HSBC, paid, -lines[0].gross, supplier.upper()[:18], "BP")] if paid <= until
                                 else []))
    return [d for d in out if d.date <= until]


def _card_spend(start: date, until: date, rng: random.Random) -> list[Deal]:
    out = []
    for month in _months(start, until):
        for _ in range(rng.randint(15, 25)):
            on = date(month.year, month.month, rng.randint(1, month_end(month).day))
            if on > until:
                continue
            kind = rng.choices(("sub", "rail", "taxi", "stat"), weights=(50, 15, 15, 20))[0]
            if kind == "sub":
                merchant = rng.choice(CAFES)
                lines = [gross_line("Food and drink", "7406", m(D(rng.randint(600, 4000)) / 100))]
            elif kind == "rail":
                merchant = RAIL
                lines = [line("Rail fare", "7400", m(D(rng.randint(2000, 18000)) / 100), "zero")]
            elif kind == "taxi":
                merchant = rng.choice(TAXIS)
                lines = [line("Taxi fare", "7400", m(D(rng.randint(1200, 4500)) / 100), "none")]
            else:
                merchant = rng.choice(STATIONERS)
                lines = [gross_line("Stationery", "7504", m(D(rng.randint(1000, 9000)) / 100))]
            account = AMEX if rng.random() < 0.6 else HSBC
            post = next_working_day(on + timedelta(days=rng.randint(0, 2)))
            out.append(_card(on, merchant, lines, account, post, rng))
    return out


def _opening_settlements() -> list[Deal]:
    out = []
    for on, customer, number, amount in ((date(2023, 4, 12), "Brightwater Homes Ltd", "KF-0981", "7200.00"),
                                         (date(2023, 4, 18), "Northgate Dental Group", "KF-0984", "4800.00"),
                                         (date(2023, 4, 27), "Lowther Interiors Ltd", "KF-0990", "8400.00"),
                                         (date(2023, 5, 3), "Calder Valley Cycles", "KF-0993", "6000.00")):
        out.append(deal("debtor_receipt", on, customer, "journal",
                        payments=[pay(HSBC, on, amount, f"{customer.upper()} {number}", "CR", "1100")]))
    for on, supplier, number, amount, code in ((date(2023, 4, 5), "Brunel Energy", "BE-55120", "1800.00", "DD"),
                                               (date(2023, 4, 19), "Wyvern Freelance Studio", "INV-207", "2400.00",
                                                "BP"),
                                               (date(2023, 4, 24), "Avonside Print Ltd", "4471", "1080.00", "BP"),
                                               (date(2023, 4, 27), "Cabot Office Supplies", "99812", "600.00",
                                                "BP")):
        out.append(deal("creditor_payment", on, supplier, "journal",
                        payments=[pay(HSBC, on, f"-{amount}", supplier.upper()[:18], code, "2100")]))
    return out


def _planted(client: Client, rng: random.Random) -> list[Deal]:
    out = []
    out.append(deal("engagement", date(2023, 4, 12), "Redland & Co", "journal", docs=[
        doc("prior_accounts", "Redland & Co Chartered Accountants", NAME, "Accounts to 31 Mar 2023", date(2023, 3, 31),
            treatment="evidence", reason="Last year's accounts: the comparatives"),
        doc("prior_tb", "Redland & Co Chartered Accountants", NAME, "Trial balance at 31 Mar 2023", date(2023, 3, 31),
            treatment="evidence", reason="The opening balances", balances=client.opening.balances),
        doc("client_sheet", "Redland & Co Chartered Accountants", NAME, "Client information", date(2023, 4, 12),
            treatment="evidence", reason="Who the client is")]))
    redland = [line("Accounts and tax return, year to 31 Mar 2023", "7601", "2400.00")]
    out.append(_bill(date(2023, 5, 12), "Redland & Co Chartered Accountants", "RC-3381", redland,
                     [pay(HSBC, next_working_day(date(2023, 6, 11)), -redland[0].gross, "REDLAND AND CO", "BP")]))
    out.append(deal("correction", date(2023, 4, 13), "HMRC", "journal", cases={"EC-0512"},
                    journal=[jl("8250", "312.00"), jl("2202", credit="312.00")],
                    query=Query("", "The VAT direct debit on 13 Apr 2023 was £27,412.00, but the previous accountant's "
                                    "figures showed £27,100.00 owed for the quarter to 28 Feb 2023. We've charged the "
                                    "£312.00 difference to this year. Do you know why it differed?",
                                "The opening balances don't agree with what HMRC collected.", "accounts",
                                date(2023, 5, 16), "Redland & Co say a February invoice was left off their VAT "
                                                  "figure. Fine to correct it this year.")))
    ct_day = ct_due(client.opening.as_at)
    out.append(deal("ct_payment", ct_day, "HMRC", "journal", cases={"EC-0438", "EC-0708"},
                    payments=[pay(HSBC, ct_day, "-13987.00", "HMRC CUMBERNAULD 8126043571A00123A", "BP", "2320")]))
    order = [line("Monitor arm", "7504", "74.99", vat="15.00")]
    out.append(deal("card_spend", date(2023, 6, 19), "Shelfwise Online", "bank", lines=order, cases={"EC-0208"},
                    docs=[doc("order_confirmation", "Shelfwise Online", NAME, "SW-7781204", date(2023, 6, 12),
                              treatment="not_booked", reason="An order confirmation, not a VAT invoice; the VAT "
                                                             "invoice followed", printed={"gross": m("89.99")},
                              note="This is not a VAT invoice"),
                          doc("purchase_invoice", "Shelfwise Online", NAME, "SWI-7781204", date(2023, 6, 19), order)],
                    payments=[pay(AMEX, date(2023, 6, 12), "-89.99", "SHELFWISE ONLINE")]))
    credit = [line("Credit: September 2023 retainer, hours disputed", "4000", "600.00")]
    out.append(deal("sale_credit", date(2023, 10, 6), "Northgate Dental Group", "debtor", lines=credit,
                    cases={"EC-0210"}, docs=[doc("sales_credit_note", NAME, "Northgate Dental Group", "CN-0007",
                                                 date(2023, 10, 6), credit)]))
    out.append(deal("void", date(2023, 11, 14), "Fenwick & Rowe Solicitors", "journal", cases={"EC-0211"},
                    docs=[doc("void_invoice", NAME, "Fenwick & Rowe Solicitors", "", date(2023, 11, 14),
                              treatment="not_booked", reason="Cancelled before it was sent")]))
    rail = [line("Return ticket Bristol to London", "7400", "142.60", "zero"), line("Booking fee", "7400", "1.25",
                                                                                     vat="0.25")]
    out.append(_card(date(2023, 11, 21), RAIL, rail, AMEX, date(2023, 11, 22), rng, cases={"EC-0226", "EC-0401"}))
    for on in (date(2023, 6, 30), date(2023, 9, 29), date(2023, 12, 29), date(2024, 3, 28)):
        out.append(deal("dividend", on, "Shareholders", "journal", cases={"EC-0230"},
                        docs=[doc("board_minutes", NAME, "Shareholders", f"Interim dividend {on:%d %b %Y}", on,
                                  printed={"gross": m("8000.00")}, per_share="£40.00 on 200 shares")],
                        payments=[pay(HSBC, on, "-4000.00", "H FINCH DIVIDEND", "BP", "3260"),
                                  pay(HSBC, on, "-4000.00", "O KESTREL DIVIDEND", "BP", "3260")]))
    laptop = [line("Laptop 14-inch, 32GB", "0030", "1082.50")]
    out.append(_bill(date(2023, 9, 14), "Brightcore Computers Ltd", "BC-20931", laptop,
                     [pay(HSBC, date(2023, 9, 14), "-1299.00", "BRIGHTCORE COMPUTERS", "BP")], cases={"EC-0301"}))
    kit = [line("27-inch monitor", "7504", "480.00"), line("Ergonomic office chair", "0040", "520.00")]
    out.append(_bill(date(2023, 11, 16), "Cabot Office Supplies", "99977", kit,
                     [pay(HSBC, next_working_day(date(2023, 12, 16)), "-1200.00", "CABOT OFFICE SUPP", "BP")],
                     cases={"EC-0303"}))
    cover = [line("Office and liability insurance (premium £1,950.00 + Insurance Premium Tax £234.00)", "8204",
                  "2184.00", "exempt")]
    out.append(_bill(date(2023, 10, 1), "Severnside Insurance Brokers", "SIB-55102", cover,
                     [pay(HSBC, date(2023, 10, 2), "-2184.00", "SEVERNSIDE INSURANCE", "BP")],
                     covers=(date(2023, 10, 1), date(2024, 9, 30)), cases={"EC-0314"}))
    dinner = [line("Dinner", "7403", "155.00", "blocked", "31.00")]
    out.append(_card(date(2023, 10, 17), "Marlowe's Kitchen", dinner, AMEX, date(2023, 10, 18), rng,
                     cases={"EC-0330"}, handwritten="Client: Brightwater"))
    party = [line("Staff Christmas party for 9", "8205", "950.00", vat="190.00")]
    out.append(deal("card_spend", date(2023, 12, 15), "The Granary Rooms", "bank", lines=party, cases={"EC-0331"},
                    docs=[doc("purchase_invoice", "The Granary Rooms", NAME, "GR-1215", date(2023, 12, 15), party)],
                    payments=[pay(HSBC, date(2023, 12, 18), "-1140.00", f"THE GRANARY ROOMS {card_town('The Granary Rooms')} GB", "VIS")]))
    chairs = [line("Two task chairs", "7504", "266.67", vat="53.33")]
    full_invoice = doc("purchase_invoice", "Wharfside Office Interiors", NAME, "WOI-4410", date(2024, 2, 8), chairs,
                       treatment="evidence", reason="The full VAT invoice for the till receipt of the same purchase: "
                                                    "it lets the VAT be reclaimed", issued=date(2024, 3, 12))
    out.append(deal("card_spend", date(2024, 2, 8), "Wharfside Office Interiors", "bank", lines=chairs,
                    cases={"EC-0346"},
                    docs=[doc("receipt", "Wharfside Office Interiors", "", "0832-17", date(2024, 2, 8), chairs,
                              simplified=True)],
                    payments=[pay(AMEX, date(2024, 2, 9), "-320.00", f"WHARFSIDE OFFICE INT {card_town('Wharfside Office Interiors')}")],
                    query=Query("", "Please send the full VAT invoice for the £320.00 chairs from Wharfside Office "
                                    "Interiors on 8 Feb 2024. The till receipt doesn't show the company's name and "
                                    "address, and a purchase over £250 needs a full VAT invoice before the VAT can "
                                    "be reclaimed.",
                                "A till receipt is only a VAT invoice up to £250.", "tax", date(2024, 3, 12),
                                "Here's the invoice they emailed over.",
                                before=held_vat("Two task chairs", "7504", "266.67", "53.33"),
                                answer_doc=full_invoice)))
    for month in _months(date(2023, 4, 1), date(2024, 6, 30)):
        on = date(month.year, month.month, 9)
        stream = [line("Streaming subscription (personal)", "2250", "10.99", "outside")]
        query = None
        if month == date(2023, 4, 1):
            query = Query("", "There's a £10.99 Streamflix subscription on the company card each month. It looks "
                              "personal, so we've put it to Hannah's director's loan account. Is that right?",
                          "Personal spending on a company card is the director's, not the company's.", "tax",
                          date(2023, 5, 16), "Yes, that's my personal one. Sorry!")
        out.append(deal("card_spend", on, "Streamflix", "bank", lines=stream, cases={"EC-0601"}, query=query,
                        payments=[pay(AMEX, on, "-10.99", "STREAMFLIX.COM")]))
    for on, number, printed, ask in (
            (date(2023, 9, 16), "4471-08", [line("Fruit and vegetables", "2250", "18.60", "zero"),
                                             line("Meat and fish", "2250", "31.25", "zero"),
                                             line("Bread and dairy", "2250", "9.40", "zero"),
                                             gross_line("Household cleaning", "2250", "11.40")], True),
            (date(2024, 2, 17), "5102-63", [line("Fruit and vegetables", "2250", "14.85", "zero"),
                                             line("Pasta, rice and tins", "2250", "8.30", "zero"),
                                             gross_line("Wine", "2250", "12.50")], False)):
        # A household shop paid on the company card by mistake: the director's, not the company's (EC-0601).
        gross = sum((ln.gross for ln in printed), D(0))
        shop = [line("Groceries (personal)", "2250", gross, "outside")]
        query = None
        if ask:
            query = Query("", f"There's £{gross:,.2f} at {GROCER} on the company card on {on:%d %b %Y}, a household "
                              "shop. We've put it to Hannah's director's loan account. Is that right?",
                          "Personal spending on a company card is the director's, not the company's.", "tax",
                          date(2023, 10, 17), "Yes, wrong card at the till. Sorry again!")
        out.append(deal("card_spend", on, GROCER, "bank", lines=shop, cases={"EC-0601"}, query=query,
                        docs=[doc("receipt", GROCER, "", number, on, printed)],
                        payments=[pay(AMEX, on, -gross, f"{GROCER.upper()} {card_town(GROCER)}")]))
    claim = [line("Train to London", "7400", "86.40", "zero"), gross_line("Lunch while travelling", "7406", "34.80"),
             gross_line("Car park", "7400", "91.20")]
    out.append(deal("expense_claim", date(2023, 10, 20), "Omar Kestrel", "director_loan", lines=claim,
                    cases={"EC-0602"},
                    docs=[doc("expense_claim", "Omar Kestrel", NAME, "Expenses October 2023", date(2023, 10, 20),
                              claim)] +
                         [doc("receipt", who, "", f"R{i}", date(2023, 10, 18), [ln], treatment="evidence",
                              reason="Backs a line of the expense claim")
                          for i, (who, ln) in enumerate(zip((RAIL, "Gantry Deli", "Temple Gate Car Park"), claim), 1)]))
    out.append(deal("director_repayment", date(2023, 11, 15), "Omar Kestrel", "journal", cases={"EC-0602"},
                    payments=[pay(HSBC, date(2023, 11, 15), "-212.40", "O KESTREL EXPENSES", "BP", "2251")]))
    lowther = [line("Showroom website build", "4010", "4000.00")]
    out.append(_sale(date(2023, 6, 5), "Lowther Interiors Ltd", lowther, cases={"EC-0705", "EC-0363"}))
    out.append(deal("letter", date(2023, 10, 16), "Lowther Interiors Ltd", "journal", cases={"EC-0705"},
                    docs=[doc("letter", "Kingsdown Restructuring LLP", NAME, "Notice of administration",
                              date(2023, 10, 16), treatment="evidence",
                              reason="Lowther Interiors Ltd has gone into administration")]))
    out.append(deal("bad_debt_relief", date(2024, 1, 31), "Lowther Interiors Ltd", "journal",
                    cases={"EC-0705", "EC-0363"}, vat_boxes={4: m("800.00")},
                    journal=[jl("8100", "4000.00"), jl("2201", "800.00"), jl("1100", credit="4800.00")]))
    out.append(deal("bad_debt_recovery", date(2024, 3, 20), "Lowther Interiors Ltd", "journal",
                    cases={"EC-0705", "EC-0363"}, vat_boxes={1: m("200.00")},
                    journal=[jl("1100", "1200.00"), jl("8100", credit="1000.00"), jl("2200", credit="200.00")],
                    payments=[pay(HSBC, date(2024, 3, 20), "1200.00", "LOWTHER INTERIORS IN ADMIN", "CR", "1100")]))
    stationery = [gross_line("Stationery", "7504", "23.40")]
    out.append(_card(date(2024, 2, 29), "Penhallow Stationers", stationery, HSBC, date(2024, 3, 1), rng,
                     cases={"EC-0518", "EC-0401"}))
    for n in (1, 2):
        coffee = [gross_line("Flat white and pastry", "7406", "4.50")]
        out.append(_card(date(2024, 3, 6), "Quayside Coffee Co", coffee, HSBC, date(2024, 3, 7), rng,
                         cases={"EC-0430", "EC-0401"}, number=f"QC-30{n}"))
    return out


SAVINGS_MOVES = ((date(2023, 4, 1), "-5000.00"), (date(2023, 7, 1), "-5000.00"), (date(2023, 12, 1), "10000.00"),
                 (date(2024, 5, 1), "-5000.00"))


def _savings(start: date, until: date) -> list[Deal]:
    """Money moved between the current and deposit accounts on the 2nd working day of a month: put by in quiet
    months, brought back before the December quarter's VAT and the corporation tax."""
    out = []
    for month, amount in SAVINGS_MOVES:
        on = add_working_days(month - timedelta(days=1), 2)
        if start <= on <= until:
            into_current = m(amount) > 0
            out.append(deal("transfer", on, "Business deposit", "transfer", cases={"EC-0418"}, payments=[
                pay(HSBC, on, amount, "TRF FROM BUSINESS DEPOSIT" if into_current else "TRF TO BUSINESS DEPOSIT",
                    "TRF"),
                pay(SAVINGS, on, -m(amount), "TRF TO BUSINESS CURRENT" if into_current else
                    "TRF FROM BUSINESS CURRENT", "TRF")]))
    return out


def _interest(opening: D, deals: list[Deal], until: date) -> list[Deal]:
    out = []
    balance = opening
    moved = sorted((p.date, p.amount) for d in deals for p in d.payments if p.account == SAVINGS)
    for year, month in ((2023, 6), (2023, 9), (2023, 12), (2024, 3), (2024, 6)):
        on = previous_working_day(month_end(date(year, month, 1)))
        if on > until:
            continue
        held = balance + sum((a for d, a in moved if d <= on), D(0)) + sum((x.payments[0].amount for x in out), D(0))
        amount = m(held * D("0.015") * 91 / 365)
        out.append(deal("interest", on, "Severn Bank", "bank", cases={"EC-0435"},
                        lines=[line("Deposit interest", "4906", amount, "exempt")],
                        payments=[pay(SAVINGS, on, amount, "INTEREST PAID", "CR")]))
    return out


def _amex_payoffs(opening: D, deals: list[Deal], start: date, until: date) -> list[Deal]:
    out = []
    charges = [(p.date, p.amount) for d in deals for p in d.payments if p.account == AMEX]
    for month in _months(start, until):
        statement = date(month.year, month.month, 3)
        owed = -(opening + sum((a for d, a in charges if d <= statement), D(0)) +
                 sum((x.payments[1].amount for x in out if x.payments[1].date <= statement), D(0)))
        on = next_working_day(date(month.year, month.month, 25))
        if owed > 0 and on <= until:
            out.append(deal("transfer", on, "Calder Express", "transfer", cases={"EC-0420"}, payments=[
                pay(HSBC, on, -owed, "CALDER EXPRESS", "DD"),
                pay(AMEX, on, owed, "PAYMENT RECEIVED - THANK YOU")]))
    return out


def _stripe_payouts(opening: D, deals: list[Deal], start: date, until: date) -> list[Deal]:
    out = []
    moves = sorted((p.date, p.amount) for d in deals for p in d.payments if p.account == STRIPE)
    tuesday = start + timedelta(days=(1 - start.weekday()) % 7)
    last_cutoff = None
    while tuesday <= until:
        cutoff = tuesday - timedelta(days=4)
        amount = sum((a for d, a in moves if d <= cutoff and (last_cutoff is None or d > last_cutoff)), D(0))
        if last_cutoff is None:
            amount += opening
        last_cutoff = cutoff
        on = next_working_day(tuesday)
        if amount > 0:
            cases = {"EC-0422", "EC-0519"} if on == date(2024, 4, 2) else set()
            out.append(deal("transfer", on, "Stripe", "transfer", cases=cases, payments=[
                pay(STRIPE, on, -amount, "Payout to Severn Bank", "payout"),
                pay(HSBC, on, amount, "STRIPE PAYMENTS UK", "CR")]))
        tuesday += timedelta(days=7)
    return out


def _bank_charges(deals: list[Deal], start: date, until: date) -> list[Deal]:
    out = []
    for month in _months(start, until):
        on = next_working_day(month)
        before = add_months(month, -1)
        count = sum(1 for d in deals for p in d.payments
                    if p.account == HSBC and p.amount < 0 and p.type_code in ("BP", "DD", "SO", "TRF")
                    and (p.date.year, p.date.month) == (before.year, before.month)) or 22
        fee = m(D("8.50") + D("0.35") * count)
        out.append(deal("purchase", on, "Severn Bank", "bank", cases={"EC-0437"},
                        lines=[line(f"Account charges for {before:%B %Y}", "7901", fee, "exempt")],
                        payments=[pay(HSBC, on, -fee, "SERVICE CHARGES", "DR")]))
    return out


def _number_sales(deals: list[Deal]) -> list[Deal]:
    """Sales invoices (and the cancelled one) take the next numbers from KF-0994, in date order."""
    order = sorted((d.date, i) for i, d in enumerate(deals)
                   if any(x.kind in ("sales_invoice", "void_invoice") for x in d.docs))
    out = list(deals)
    for n, (_, i) in enumerate(order, 994):
        d = out[i]
        docs = tuple(replace(x, number=f"KF-{n:04d}") if x.kind in ("sales_invoice", "void_invoice") else x
                     for x in d.docs)
        out[i] = replace(d, docs=docs)
    return out


def _march_2024_touches(deals: list[Deal]) -> list[Deal]:
    """EC-0137: two supplier payments in March 2024 whose references Excel turned into 1.23457E+15.
    EC-0513: every VAT-bearing deal in March 2024, whose VAT is still owed at the year end."""
    out, mangled = [], 0
    for d in deals:
        if d.settles_via == "creditor" and mangled < 2 and any(
                p.type_code == "BP" and p.date.year == 2024 and p.date.month == 3 for p in d.payments):
            d = replace(d, cases=tuple(sorted(set(d.cases) | {"EC-0137"})), payments=tuple(
                replace(p, descriptor=f"{p.descriptor} 1.23457E+15") for p in d.payments))
            mangled += 1
        if date(2024, 3, 1) <= d.date <= date(2024, 3, 31) and any(ln.vat for ln in d.lines):
            d = replace(d, cases=tuple(sorted(set(d.cases) | {"EC-0513"})))
        out.append(d)
    return out


def deals(client: Client, until: date, rng: random.Random) -> list[Deal]:
    start = client.periods[0].start
    trading = (_opening_settlements() + _retainers(start, until, rng) + _projects(start, until, rng) +
               _overheads(start, until, rng) + _suppliers(start, until, rng) + _card_spend(start, until, rng) +
               _planted(client, rng) + _savings(start, until))
    trading = [d for d in trading if d.date <= until]
    balances = client.opening.balances
    trading += _amex_payoffs(balances["1240"], trading, start, until)
    trading += _stripe_payouts(balances["1250"], trading, start, until)
    trading += _interest(balances["1210"], trading, until)
    return _march_2024_touches(_number_sales(trading))


def late_deals(client: Client, deals: list[Deal], until: date) -> list[Deal]:
    """Deals that depend on everything else: the bank's charges count every electronic payment of the month before,
    wages, PAYE, pension and VAT included, which the simulator adds after the trading deals."""
    return _bank_charges(deals, client.periods[0].start, until)
