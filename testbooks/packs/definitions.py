"""The first five packs. Each is a tiny limited company with one bank account and one month (June 2024): two
ordinary card lunches, a sales invoice paid in the month, and its case."""
from __future__ import annotations

import random
from datetime import date
from decimal import Decimal as D

from testbooks.engine.make import deal, doc, gross_line, held_vat, line, pay
from testbooks.engine.model import (Client, Deal, MoneyAccount, Opening, Owner, Period, Policies, Query,
                                    VatTotals)

NAME = "Fernbrook Consulting Ltd"
HSBC = "hsbc"
JUNE = Period(date(2024, 6, 1), date(2024, 6, 30), partial=True)
SLUGS = {"EC-0301": "laptop-bought", "EC-0316": "overseas-software", "EC-0330": "client-dinner",
         "EC-0346": "receipt-over-250", "EC-0430": "two-coffees"}


def _define(case_id: str):
    def define() -> Client:
        zero = D("0.00")
        return Client(
            id=case_id, name=NAME, kind="pack", address="3 Mill Lane, Fernbrook, Gloucester GL2 9XX",
            company_number="13550218", vat_number="380156267", periods=(JUNE,), vat_stagger=(),
            accounts=(MoneyAccount(HSBC, "Business current", "Severn Bank", "hsbc_csv", "1200"),),
            employees=(), owners=(Owner("owner", "Sam Carter", D("1"), "2250"),),
            policies=Policies("accruals", D("500"), D("250"), {"computer": 3, "furniture": 5}, "FRS 105", zero, zero),
            opening=Opening(as_at=date(2024, 5, 31), balances={"1200": D("5000.00"), "3200": D("-5000.00")},
                            open_items=(), assets=(), vat_brought_in=VatTotals(zero, zero, zero, zero),
                            true_differences={}, prior_pl={}))
    return define


def _card(on: date, merchant: str, lines, rng: random.Random, cases=(), number=None, **extra) -> Deal:
    gross = sum(ln.gross for ln in lines)
    receipt = doc("receipt", merchant, "", number or f"{rng.randint(1000, 9999)}-{rng.randint(10, 99)}", on, lines,
                  **extra)
    return deal("card_spend", on, merchant, "bank", lines=lines, docs=[receipt], cases=cases,
                payments=[pay(HSBC, on, -gross, f"{merchant.upper()} GLOUCESTER GB", "VIS")])


def _ordinary(rng: random.Random) -> list[Deal]:
    lunch = [gross_line("Lunch while working away", "7406", "12.40")]
    sandwich = [gross_line("Sandwich and coffee", "7406", "8.95")]
    fee = [line("Consultancy, May 2024", "4010", "2500.00")]
    invoice = doc("sales_invoice", NAME, "Ridgeway Garden Centre Ltd", "FC-0412", date(2024, 6, 3), fee,
                  terms="14 days")
    return [_card(date(2024, 6, 11), "The Brunswick Cafe", lunch, rng),
            _card(date(2024, 6, 19), "Kingsholm Deli", sandwich, rng),
            deal("sale", date(2024, 6, 3), "Ridgeway Garden Centre Ltd", "debtor", lines=fee, docs=[invoice],
                 payments=[pay(HSBC, date(2024, 6, 17), "3000.00", "RIDGEWAY GARDEN CENTRE", "CR")])]


def _ec0301(rng):
    laptop = [line("Laptop 14-inch, 32GB", "0030", "1082.50")]
    invoice = doc("purchase_invoice", "Brightcore Computers Ltd", NAME, "BC-31207", date(2024, 6, 6), laptop)
    return [deal("purchase", date(2024, 6, 6), "Brightcore Computers Ltd", "creditor", lines=laptop, docs=[invoice],
                 cases={"EC-0301"},
                 payments=[pay(HSBC, date(2024, 6, 6), "-1299.00", "BRIGHTCORE COMPUTERS", "BP")])]


def _ec0316(rng):
    cloud = [line("Cloud hosting, June 2024", "7550", "250.00", "reverse_charge", "50.00")]
    invoice = doc("purchase_invoice", "Corrib Cloud Ltd", NAME, "CC-202406", date(2024, 6, 1), cloud,
                  note="Reverse charge: the customer accounts for the VAT", country="Ireland")
    return [deal("card_spend", date(2024, 6, 1), "Corrib Cloud Ltd", "bank", lines=cloud, docs=[invoice],
                 cases={"EC-0316"}, covers=(date(2024, 6, 1), date(2024, 6, 30)),
                 payments=[pay(HSBC, date(2024, 6, 3), "-250.00", "CORRIB CLOUD LTD DUBLIN IE", "VIS")])]


def _ec0330(rng):
    dinner = [line("Dinner", "7403", "155.00", "blocked", "31.00")]
    return [_card(date(2024, 6, 13), "Marlowe's Kitchen", dinner, rng, cases={"EC-0330"},
                  handwritten="Client: Brightwater")]


def _ec0346(rng):
    chairs = [line("Two task chairs", "7504", "266.67", vat="53.33")]
    full_invoice = doc("purchase_invoice", "Wharfside Office Interiors", NAME, "WOI-5120", date(2024, 6, 10), chairs,
                       treatment="evidence", reason="The full VAT invoice for the till receipt of the same purchase: "
                                                    "it lets the VAT be reclaimed", issued=date(2024, 6, 14))
    receipt = doc("receipt", "Wharfside Office Interiors", "", "0911-04", date(2024, 6, 10), chairs, simplified=True)
    query = Query("", "Please send the full VAT invoice for the £320.00 chairs from Wharfside Office Interiors on "
                      "10 Jun 2024: a till receipt over £250 isn't enough to reclaim the VAT.",
                  "A till receipt is only a VAT invoice up to £250.", "tax", date(2024, 6, 14),
                  "Here's the invoice they emailed over.", before=held_vat("Two task chairs", "7504", "266.67", "53.33"),
                  answer_doc=full_invoice)
    return [deal("card_spend", date(2024, 6, 10), "Wharfside Office Interiors", "bank", lines=chairs, docs=[receipt],
                 cases={"EC-0346"}, query=query,
                 payments=[pay(HSBC, date(2024, 6, 11), "-320.00", "WHARFSIDE OFFICE INT GB", "VIS")])]


def _ec0430(rng):
    return [_card(date(2024, 6, 12), "Quayside Coffee Co", [gross_line("Flat white and pastry", "7406", "4.50")], rng,
                  cases={"EC-0430"}, number=f"QC-61{n}") for n in (1, 2)]


CASE_DEALS = {"EC-0301": _ec0301, "EC-0316": _ec0316, "EC-0330": _ec0330, "EC-0346": _ec0346, "EC-0430": _ec0430}


def _deals_for(case_id: str):
    def deals(client: Client, until: date, rng: random.Random) -> list[Deal]:
        return _ordinary(rng) + CASE_DEALS[case_id](rng)
    return deals


PACKS = {case: (_define(case), _deals_for(case)) for case in sorted(CASE_DEALS)}
