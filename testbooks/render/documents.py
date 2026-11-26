"""Plain documents: invoices, receipts, payroll reports, minutes, letters and the previous accountant's papers.

Build step 1 prints them as clean text PDFs (and Excel where a client would send Excel); step 3 adds the real-world
layouts and photo ageing."""
from __future__ import annotations

import random
from decimal import Decimal
from pathlib import Path

from testbooks.books.chart import CHART
from testbooks.engine.model import Client, Deal, Doc, Query
from testbooks.ids import ie_vat_number, vat_number
from testbooks.places import address_of
from testbooks.render.pdf import LEFT, RIGHT, Page, slug, unique
from testbooks.render.sheets import write_xlsx

SYMBOL = {"GBP": "£", "USD": "$", "EUR": "€"}
RATE_TEXT = {"standard": "20%", "reduced": "5%", "zero": "0%", "exempt": "Exempt", "outside": "Outside scope",
             "reverse_charge": "Reverse charge", "blocked": "20%", "blocked_half": "20%", "none": "-"}
NOT_REGISTERED = ("Wyvern Freelance Studio", "Kite & Quill Design", "Tobias Lane Development",
                  "Tallgrass Metrics Inc.", "Bristol Blue Cars", "Avon Street Taxis", "Omar Kestrel", "Shareholders")
XLSX_KINDS = ("prior_tb", "expense_claim")
def money_text(x: Decimal, currency: str = "GBP") -> str:
    sign = "-" if x < 0 else ""
    return f"{sign}{SYMBOL.get(currency, currency + ' ')}{abs(x):,.2f}"


def _their_vat_number(issuer: str) -> str:
    """A made-up issuer's VAT number: valid check digits, the same every build."""
    return vat_number(random.Random(issuer))


def file_name(doc: Doc) -> str:
    ext = "xlsx" if doc.kind in XLSX_KINDS else "pdf"
    return f"{doc.date:%Y-%m-%d}_{slug(doc.issuer)[:30]}_{slug(doc.number)[:30] or 'document'}.{ext}"


def _header(page: Page, doc: Doc, client: Client, title: str):
    own = doc.issuer == client.name
    country = doc.extra.get("country")
    page.text(doc.issuer, 14, bold=True)
    if own:
        page.text(client.address)
        page.text(f"Company number {client.company_number}   VAT number GB {client.vat_number}")
    else:
        page.text(address_of(doc.issuer, country))
        if doc.issuer not in NOT_REGISTERED and country != "United States":
            if country == "Ireland":
                page.text(f"VAT number IE{ie_vat_number(random.Random(doc.issuer))}")
            else:
                page.text(f"VAT number GB {_their_vat_number(doc.issuer)}")
    page.gap()
    page.text(title, 12, bold=True)
    page.text(f"Number: {doc.number}")
    page.text(f"Date: {doc.date:%d %B %Y}")
    if doc.recipient:
        page.text(f"To: {doc.recipient}")
        page.text(client.address if doc.recipient == client.name else address_of(doc.recipient))
    page.gap()


def _lines_table(page: Page, deal: Deal, doc: Doc):
    page.row([(LEFT, "Description"), (-380, "Net"), (-440, "VAT rate"), (-500, "VAT"), (-RIGHT, "Total")], bold=True)
    for ln in doc.extra.get("lines", deal.lines):
        shown_vat = Decimal("0") if ln.vat_code == "reverse_charge" else ln.vat
        page.row([(LEFT, ln.description[:60]), (-380, money_text(ln.net, doc.currency)),
                  (-440, RATE_TEXT[ln.vat_code]), (-500, money_text(shown_vat, doc.currency)),
                  (-RIGHT, money_text(ln.net + shown_vat, doc.currency))])


def _totals(page: Page, doc: Doc):
    page.gap()
    for label, key in (("Net", "net"), ("VAT", "vat"), ("Total", "gross")):
        if key in doc.printed:
            page.row([(-440, label), (-RIGHT, money_text(doc.printed[key], doc.currency))], bold=key == "gross")


def _invoice(page: Page, doc: Doc, deal: Deal, client: Client):
    titles = {"sales_invoice": "VAT INVOICE", "purchase_invoice": "INVOICE", "sales_credit_note": "CREDIT NOTE",
              "void_invoice": "VAT INVOICE"}
    if doc.issuer in NOT_REGISTERED:
        titles["purchase_invoice"] = "INVOICE"
    elif doc.kind == "purchase_invoice":
        titles["purchase_invoice"] = "TAX INVOICE"
    _header(page, doc, client, titles[doc.kind])
    if doc.kind == "void_invoice":
        page.text("This invoice has been cancelled.")
        page.stamp("VOID")
        return
    _lines_table(page, deal, doc)
    _totals(page, doc)
    page.gap()
    for key in ("note", "terms"):
        if doc.extra.get(key):
            page.text(f"{key.capitalize()}: {doc.extra[key]}")
    if doc.extra.get("due"):
        page.text(f"Payment due: {doc.extra['due']:%d %B %Y}")
    if doc.issuer == client.name:
        page.text(f"Pay to: {client.accounts[0].bank}, sort code 40-12-76, account 21039948, ref {doc.number}")


def _receipt(page: Page, doc: Doc, deal: Deal, client: Client):
    page.text(doc.issuer.upper(), 12, bold=True)
    page.text(address_of(doc.issuer))
    if doc.issuer not in NOT_REGISTERED:
        page.text(f"VAT No. GB {_their_vat_number(doc.issuer)}")
    page.text(f"{doc.date:%d/%m/%Y}   Receipt {doc.number}")
    page.gap()
    lines = doc.extra.get("lines", deal.lines)
    for ln in lines:
        page.row([(LEFT, ln.description[:40]), (-300, money_text(ln.gross, doc.currency))])
    page.gap()
    page.row([(LEFT, "TOTAL"), (-300, money_text(doc.printed["gross"], doc.currency))], bold=True)
    if "net" in doc.printed:
        _vat_summary(page, lines)
        page.text(f"Total net {money_text(doc.printed['net'])}, total VAT {money_text(doc.printed['vat'])}")
    page.text("CARD PAYMENT   **** **** **** 4821   AUTH 0" + doc.number[-5:].replace("-", "").zfill(5))
    if doc.extra.get("simplified"):
        page.text("VAT invoice available on request")
    if doc.extra.get("handwritten"):
        page.gap()
        page.text(f"(written on the receipt) {doc.extra['handwritten']}", 11, bold=True)


def _vat_summary(page: Page, lines):
    """A till's VAT analysis: one line per rate, as the receipt's lines fall."""
    rates: dict[str, list] = {}
    for ln in lines:
        key = {"standard": "VAT 20%", "blocked": "VAT 20%", "blocked_half": "VAT 20%", "reduced": "VAT 5%",
               "zero": "Zero-rated", "exempt": "Exempt"}.get(ln.vat_code, "No VAT charged")
        net, vat = rates.get(key, (Decimal("0"), Decimal("0")))
        rates[key] = (net + ln.net, vat + (ln.vat if ln.vat_code != "reverse_charge" else 0))
    for key, (net, vat) in rates.items():
        page.text(f"{key}: net {money_text(net)}, VAT {money_text(vat)}" if key.startswith("VAT")
                  else f"{key} {money_text(net)}")


def _order_confirmation(page: Page, doc: Doc, deal: Deal, client: Client):
    page.text(doc.issuer, 14, bold=True)
    page.text("Order confirmation", 12, bold=True)
    page.text(f"Order {doc.number}, placed {doc.date:%d %B %Y}")
    page.text(f"Order total: {money_text(doc.printed['gross'])}")
    page.text(doc.extra.get("note", ""))


def _payroll(page: Page, doc: Doc, deal: Deal, client: Client):
    names = {e.id: e.name for e in client.employees}
    page.text(doc.issuer, 14, bold=True)
    page.text(f"Payroll summary for {client.name}", 12, bold=True)
    page.text(f"Pay date {doc.date:%d %B %Y}")
    page.gap()
    cols = (LEFT, -230, -280, -330, -380, -430, -480, -RIGHT)
    page.row(list(zip(cols, ("Employee", "Gross", "Tax", "Ee NI", "Er NI", "Ee pension", "Er pension", "Net pay"))),
             size=8, bold=True)
    for p in doc.extra["payslips"]:
        page.row(list(zip(cols, (names[p.employee_id], money_text(p.gross), money_text(p.tax), money_text(p.ee_ni),
                                 money_text(p.er_ni), money_text(p.ee_pension), money_text(p.er_pension),
                                 money_text(p.net)))), size=8)
    page.gap()
    page.row([(LEFT, "Total gross pay"), (-230, money_text(doc.printed["gross"]))], bold=True)


def _employer_payment(page: Page, doc: Doc, deal: Deal, client: Client):
    page.text(doc.issuer, 14, bold=True)
    page.text("Employer payment record", 12, bold=True)
    page.text(f"Month of pay date {doc.date:%d %B %Y}")
    page.text(f"PAYE income tax and National Insurance: {money_text(doc.extra['paye_before_allowance'])}")
    page.text(f"Employment Allowance claimed: {money_text(doc.extra['ea_used'])}")
    page.text(f"Amount due to HMRC: {money_text(doc.printed['gross'])}", bold=True)
    page.text("Accounts Office reference 120PA00048215")


def _minutes(page: Page, doc: Doc, deal: Deal, client: Client):
    page.text(client.name, 14, bold=True)
    page.text("Minutes of a meeting of the directors", 12, bold=True)
    page.text(f"Held on {doc.date:%d %B %Y}. Present: " + ", ".join(o.name for o in client.owners))
    page.text(f"It was resolved to pay an interim dividend of {doc.extra.get('per_share', '')},")
    page.text(f"{money_text(doc.printed['gross'])} in total, to the shareholders on the register today.")
    page.text("Signed: Hannah Finch, Director")


def _letter(page: Page, doc: Doc, deal: Deal, client: Client):
    page.text(doc.issuer, 14, bold=True)
    page.text(f"{doc.date:%d %B %Y}")
    page.text(f"To the creditors of {deal.counterparty}")
    page.gap()
    page.text(doc.number, 12, bold=True)
    page.text(f"{deal.counterparty} entered administration on {doc.date:%d %B %Y}. Creditors should submit their")
    page.text("claims to the administrators. A first distribution to unsecured creditors is expected in 2024.")


def _prior_accounts(page: Page, doc: Doc, deal: Deal, client: Client):
    page.text(client.name, 14, bold=True)
    page.text("Accounts for the year ended 31 March 2023 (micro-entity, FRS 105)", 12, bold=True)
    page.text(f"Prepared by {doc.issuer}")
    page.gap()
    page.text("Profit and loss account", bold=True)
    for heading, amount in client.opening.prior_pl.items():
        page.row([(LEFT, heading), (-RIGHT, money_text(amount))])
    page.gap()
    page.text("Balance sheet at 31 March 2023: see the trial balance sent with these accounts.")


def _client_sheet(page: Page, doc: Doc, deal: Deal, client: Client):
    page.text("Client information", 14, bold=True)
    for label, value in (("Name", client.name), ("Address", client.address),
                         ("Company number", client.company_number), ("VAT number", f"GB {client.vat_number}"),
                         ("Year end", f"{client.periods[0].end:%d %B}"),
                         ("VAT quarters end", ", ".join(f"{m:02d}" for m in client.vat_stagger)),
                         ("Directors", ", ".join(o.name for o in client.owners)),
                         ("Bank accounts", ", ".join(f"{a.bank} {a.name}" for a in client.accounts))):
        page.row([(LEFT, label), (180, value)])


PDF_WRITERS = {"sales_invoice": _invoice, "purchase_invoice": _invoice, "sales_credit_note": _invoice,
               "void_invoice": _invoice, "receipt": _receipt, "order_confirmation": _order_confirmation,
               "payroll_summary": _payroll, "employer_payment_record": _employer_payment,
               "board_minutes": _minutes, "letter": _letter, "prior_accounts": _prior_accounts,
               "client_sheet": _client_sheet}


def _xlsx(doc: Doc, deal: Deal, client: Client, path: Path) -> Path:
    if doc.kind == "prior_tb":
        rows = [["Code", "Account", "Debit", "Credit"]]
        for code, amount in sorted(doc.extra["balances"].items()):
            rows.append([code, CHART[code].name, float(amount) if amount > 0 else None,
                         float(-amount) if amount < 0 else None])
        return write_xlsx(path, {"Trial balance 31.03.23": rows})
    rows = [["Date", "Description", "Amount"]]
    for ln in deal.lines:
        rows.append([doc.date.strftime("%d/%m/%Y"), ln.description, float(ln.gross)])
    rows.append(["", "Total", float(doc.printed["gross"])])
    return write_xlsx(path, {"Claim": rows})


def render_doc(doc: Doc, deal: Deal, client: Client, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = unique(out_dir / file_name(doc))
    if doc.kind in XLSX_KINDS:
        return _xlsx(doc, deal, client, path)
    page = Page(path, f"{doc.kind.replace('_', ' ')} {doc.number}", doc.issuer)
    PDF_WRITERS[doc.kind](page, doc, deal, client)
    return page.save()


def render_answer(query: Query, deal: Deal, client: Client, out_dir: Path) -> list[Path]:
    """The client's reply as a text file, and any document it brings."""
    out_dir.mkdir(parents=True, exist_ok=True)
    reply = unique(out_dir / f"{query.answer_date:%Y-%m-%d}_reply_{slug(query.id)}.txt")
    reply.write_text(f"Re: {query.question}\n\n{query.answer_text}\n", encoding="utf-8")
    files = [reply]
    if query.answer_doc is not None:
        files.append(render_doc(query.answer_doc, deal, client, out_dir))
    return files
