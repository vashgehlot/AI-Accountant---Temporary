"""Ground truth for the accuracy fixtures: synthetic UK documents and the transactions a
bookkeeper would record from each, from the point of view of Northbridge Consulting Ltd.

Account conventions: a supermarket bank line with no item detail is groceries for the workplace
(8205 Refreshments); a café, or a receipt listing a meal, is 7406 Subsistence; a payee that could
be selling anything (a marketplace, a department store) goes to 9998 Suspense for review.

Account codes are provisional Sage 50 UK nominal codes. Phase 3's chart of accounts must
contain every code used here, or this file and the fixtures must be regenerated."""
from __future__ import annotations

import csv
import io
import random
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Callable, Optional

BUSINESS = "Northbridge Consulting Ltd"


@dataclass(frozen=True)
class Tx:
    date: str                   # ISO date
    description: str
    amount: str                 # signed for the business: "-72.00" is money out
    account: str                # provisional Sage 50 nominal code
    vat: Optional[str] = None   # only when the document itself shows the VAT

    @property
    def out(self) -> bool:
        return self.amount.startswith("-")

    @property
    def value(self) -> str:
        return self.amount.lstrip("-")

    @property
    def expected(self) -> dict:
        return {"date": self.date, "direction": "out" if self.out else "in", "gross": self.value,
                "vat": self.vat, "account_code": self.account, "description": self.description}


@dataclass(frozen=True)
class Case:
    id: str
    kind: str                   # text | table | pdf | image
    filename: str
    render: Callable[[], bytes]
    transactions: tuple[Tx, ...]
    document_type: str = "statement"   # the kind of document every row comes from (models.DocumentType)


# ── Renderers ───────────────────────────────────────────────────────────────────

def _uk(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{d}/{m}/{y}"


def _text(body: str) -> Callable[[], bytes]:
    return lambda: body.strip().encode("utf-8") + b"\n"


def _csv(rows: list[list[str]], encoding: str = "utf-8") -> bytes:
    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows(rows)
    return buf.getvalue().encode(encoding)


def _receipt_png(lines: list[str], rotate: float = 0.0, noise: bool = False) -> bytes:
    from PIL import Image, ImageDraw, ImageFont
    # Pillow's built-in font draws a box for anything beyond plain ASCII (it has no "£"),
    # which would quietly corrupt the fixture, so refuse instead.
    for line in lines:
        missing = sorted({ch for ch in line if not 32 <= ord(ch) < 127})
        if missing:
            raise ValueError(f"cannot draw {''.join(missing)!r} in receipt line {line!r}")
    font = ImageFont.load_default(size=22)
    img = Image.new("L", (600, 40 + 32 * len(lines)), 255)
    draw = ImageDraw.Draw(img)
    for n, line in enumerate(lines):
        draw.text((28, 20 + 32 * n), line, fill=0, font=font)
    if noise:
        rng = random.Random(7)
        pixels = img.load()
        for _ in range(img.width * img.height // 40):
            pixels[rng.randrange(img.width), rng.randrange(img.height)] = rng.randrange(150, 256)
    if rotate:
        img = img.rotate(rotate, expand=True, fillcolor=255, resample=Image.BICUBIC)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _text_pdf(lines: list[str]) -> bytes:
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page()
    for n, line in enumerate(lines):
        page.insert_text((48, 64 + 15 * n), line, fontname="cour", fontsize=9)
    return doc.tobytes()


def _placed_pdf(items: list[tuple[float, float, str]]) -> bytes:
    """Text placed at (x, y), like an accounting package's invoice: columns far apart come out of
    text extraction as separate blocks, so labels and their values are no longer on one line."""
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page()
    for x, y, text in items:
        page.insert_text((x, y), text, fontname="helv", fontsize=9)
    return doc.tobytes()


def _scanned_pdf(lines: list[str]) -> bytes:
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_image(page.rect, stream=_receipt_png(lines, rotate=0.8, noise=True))
    return doc.tobytes()


def _statement_csv(txs: tuple[Tx, ...], opening: str) -> bytes:
    rows, balance = [["Date", "Description", "Amount", "Balance"]], Decimal(opening)
    for tx in txs:
        balance += Decimal(tx.amount)
        rows.append([_uk(tx.date), tx.description, tx.amount, f"{balance:.2f}"])
    return _csv(rows)


def _barclays_export(entries) -> bytes:
    rows = [["Number", "Date", "Account", "Amount", "Subcategory", "Memo"]]
    rows += [["", _uk(tx.date), "20-32-06 13576543", tx.amount, sub, tx.description] for tx, sub in entries]
    return _csv(rows)


def _hsbc(txs: tuple[Tx, ...]) -> bytes:        # HSBC exports have no header row
    return _csv([[_uk(tx.date), tx.description, tx.amount] for tx in txs])


def _lloyds(entries, opening: str) -> bytes:
    rows = [["Transaction Date", "Transaction Type", "Sort Code", "Account Number", "Transaction Description",
             "Debit Amount", "Credit Amount", "Balance"]]
    balance = Decimal(opening)
    for tx, type_ in entries:
        balance += Decimal(tx.amount)
        rows.append([_uk(tx.date), type_, "'30-94-57", "12345678", tx.description,
                     tx.value if tx.out else "", "" if tx.out else tx.value, f"{balance:.2f}"])
    return _csv(rows)


def _monzo(entries) -> bytes:
    rows = [["Transaction ID", "Date", "Time", "Type", "Name", "Emoji", "Category", "Amount", "Currency",
             "Local amount", "Local currency", "Notes and #tags", "Address", "Receipt", "Description",
             "Category split"]]
    for n, (tx, time_, type_, name, category) in enumerate(entries, start=1):
        rows.append([f"tx_0000A{n}", _uk(tx.date), time_, type_, name, "", category, tx.amount, "GBP",
                     tx.amount, "GBP", "", "", "", tx.description, ""])
    return _csv(rows)


def _starling(entries, opening: str) -> bytes:
    rows = [["Date", "Counter Party", "Reference", "Type", "Amount (GBP)", "Balance (GBP)", "Spending Category", "Notes"],
            ["01/09/2026", "Opening Balance", "", "", "0.00", f"{Decimal(opening):.2f}", "", ""]]
    balance = Decimal(opening)
    for tx, party, reference, type_, category in entries:
        balance += Decimal(tx.amount)
        rows.append([_uk(tx.date), party, reference, type_, tx.amount, f"{balance:.2f}", category, ""])
    return _csv(rows)


def _preamble_cp1252(txs: tuple[Tx, ...], opening: str) -> bytes:
    rows = [["Account Name:", BUSINESS], ["Account Number:", "43018822"],
            ["Statement Period:", "01/09/2026 - 30/09/2026"], [], ["Date", "Details", "Amount", "Balance"]]
    balance = Decimal(opening)
    for tx in txs:
        balance += Decimal(tx.amount)
        value = Decimal(tx.value)
        rows.append([_uk(tx.date), tx.description, f"(£{value:,.2f})" if tx.out else f"£{value:,.2f}",
                     f"£{balance:,.2f}"])
    return _csv(rows, encoding="cp1252")


def _utf16_tsv(txs: tuple[Tx, ...]) -> bytes:  # Excel "Unicode Text": UTF-16 with BOM, tab-separated
    lines = ["Date\tDescription\tPaid out\tPaid in"]
    lines += [f"{_uk(tx.date)}\t{tx.description}\t{tx.value if tx.out else ''}\t{'' if tx.out else tx.value}"
              for tx in txs]
    return ("\n".join(lines) + "\n").encode("utf-16")


def _xlsx(sheets: dict) -> bytes:
    from openpyxl import Workbook
    wb = Workbook()
    wb.remove(wb.active)
    for title, txs in sheets.items():
        ws = wb.create_sheet(title)
        ws.append(["Date", "Description", "Paid out", "Paid in"])
        for tx in txs:
            ws.append([date.fromisoformat(tx.date), tx.description,
                       float(tx.value) if tx.out else None, None if tx.out else float(tx.value)])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── Documents ───────────────────────────────────────────────────────────────────

TESCO = """TESCO EXPRESS
123 High Street London
VAT No: GB 220 4302 31
0345 677 9031
03/09/2026 14:22
Meal Deal 3.50
Coffee 2.80
Sandwich 6.20
TOTAL 12.50
CASH 20.00
CHANGE 7.50"""

CAFE = ["THE DAILY GRIND CAFE", "14 Station Road, Leeds", "VAT Reg No 318 4471 92", "12/09/2026 09:41",
        "Flat White        3.40", "Almond Croissant  2.95", "Bottled Water     1.15", "SUBTOTAL          7.50",
        "VAT @ 20%         1.25", "TOTAL             7.50", "CARD              7.50"]

FUEL = ["SHELL WESTWAY", "Pump 4   Unleaded", "45.20 L @ 151.3p/L", "16/09/2026 18:05", "FUEL TOTAL      68.39",
        "VAT 20%         11.40", "TOTAL GBP       68.39", "PAID BY VISA"]

TRAIN = ["TRAINLINE", "E-TICKET RECEIPT", "Order date 17/09/2026", "London Euston to Manchester Piccadilly",
         "Standard Anytime Return x1", "Ticket price 87.50", "Booking fee 0.00", "Total paid GBP 87.50"]

MIXED_VAT = ["SAINSBURY'S LOCAL", "Kings Road, Chelsea", "VAT No 660 4548 36", "18/09/2026 12:31",
             "Semi skimmed milk 2pt   1.45 *", "Wholemeal bread         1.35 *", "Bananas                 0.95 *",
             "Kitchen roll            2.40 A", "Washing up liquid       1.80 A", "TOTAL                   7.95",
             "VISA                    7.95", "VAT SUMMARY", "A 20%   NET 3.50   VAT 0.70",
             "* 0%    NET 3.75   VAT 0.00"]

PURCHASE_INVOICE = [
    "Clearway Office Supplies Ltd", "Unit 5, Riverside Park, Bristol BS1 4XE",
    "VAT Registration No: GB 293 7718 05", "", "INVOICE", "Invoice number: CW-20931", "Invoice date: 08/09/2026",
    f"Bill to: {BUSINESS}", "", "A4 copier paper (10 reams)           45.00",
    "Toner cartridge HP 410X             165.00", "Desk organisers x4                   40.00", "",
    "Net amount                          250.00", "VAT at 20%                           50.00",
    "Total due                           300.00",
]

# Already paid, in the layout of an accounting package's invoice (columns, a totals block, payment
# instructions): a real invoice laid out like this came back with no transactions.
PAID_INVOICE = [
    (48, 90, "TAX INVOICE"),
    (60, 115, BUSINESS), (60, 127, "42 Canal Street"), (60, 139, "Manchester"), (60, 151, "M1 3HU"),
    (330, 90, "Invoice Date"), (330, 102, "14 Sep 2026"), (330, 120, "Invoice Number"), (330, 132, "BL-5582"),
    (330, 150, "Reference"), (330, 162, "Northbridge - laptop - Quote #0417"),
    (330, 180, "VAT Number"), (330, 192, "318446071"),
    (455, 90, "Brightline IT Supplies Ltd"), (455, 102, "8 Kings Road"), (455, 114, "Reading"),
    (455, 126, "RG1 3AA"),
    (48, 240, "Description"), (300, 240, "Quantity"), (360, 240, "Unit Price"), (440, 240, "VAT"),
    (500, 240, "Amount GBP"),
    (48, 258, "Dell Latitude 5450 laptop with 3 Year ProSupport"), (300, 258, "1.00"), (360, 258, "1,050.00"),
    (440, 258, "20%"), (500, 258, "1,050.00"),
    (400, 300, "Subtotal"), (500, 300, "1,050.00"),
    (380, 318, "TOTAL VAT 20%"), (500, 318, "210.00"),
    (400, 336, "TOTAL GBP"), (500, 336, "1,260.00"),
    (380, 354, "Less Amount Paid"), (500, 354, "1,260.00"),
    (380, 372, "AMOUNT DUE GBP"), (500, 372, "0.00"),
    (48, 420, "Due Date: 28 Sep 2026"),
    (48, 434, "Please follow the link to set up payment via Direct Debit: https://pay.example.com/BL5582"),
    (48, 458, "If you wish to pay by BACS, our bank details are as follows:"),
    (48, 472, "Account: 00000000"), (48, 484, "Sort: 00-00-00"),
]

SALES_INVOICE = [
    BUSINESS, "42 Canal Street, Manchester M1 3HU", "VAT Registration No: GB 405 1170 22", "", "INVOICE",
    "Invoice number: NB-0117", "Invoice date: 30/09/2026", "Bill to: Harbour & Lane Architects LLP", "",
    "Strategy consultancy, September 2026    2,000.00", "",
    "Net amount                              2,000.00", "VAT at 20%                                400.00",
    "Total due                               2,400.00",
]

ACCOUNTANT_INVOICE = [
    "Hartley & Co Chartered Accountants", "9 Market Place, York YO1 8SS", "VAT Reg: GB 551 2208 19",
    "INVOICE 2026-311", "Date: 25/09/2026", f"To: {BUSINESS}", "Management accounts   450.00",
    "VAT @ 20%              90.00", "TOTAL                 540.00",
]

STATEMENT = [
    f"{BUSINESS} - Business Current Account", "Sort code 20-45-77   Account 43018822",
    "Statement period 01/09/2026 to 30/09/2026", "",
    "Date        Description                  Money out    Money in     Balance",
    "01/09/2026  Opening balance                                        8,420.15",
    "03/09/2026  BRITISH GAS BUSINESS             86.40                 8,333.75",
    "05/09/2026  LANDMARK PROPERTIES RENT      1,250.00                 7,083.75",
    "09/09/2026  HARBOUR & LANE ARCHITECTS                 3,600.00    10,683.75",
    "20/09/2026  BARCLAYS BANK CHARGES             8.50                10,675.25",
    "28/09/2026  OCTOPUS ENERGY                  142.18                10,533.07",
]

# ── Transactions ────────────────────────────────────────────────────────────────

T_TESCO = (Tx("2026-09-03", "Tesco Express", "-12.50", "7406"),)
T_PROBE_CSV = (Tx("2026-09-01", "BT BUSINESS BROADBAND", "-72.00", "7502"),
               Tx("2026-09-02", "ACME LTD BACS", "3600.00", "4000"),
               Tx("2026-09-04", "SAINSBURYS", "-24.50", "8205"))
T_BARCLAYS = ((Tx("2026-09-02", "VODAFONE LTD", "-45.99", "7502"), "Direct Debit"),
              (Tx("2026-09-10", "STAPLES UK", "-32.40", "7504"), "Card Purchase"),
              (Tx("2026-09-13", "BRIGHTWELL LTD", "950.00", "4000"), "Bank Credit"),
              (Tx("2026-09-18", "ROYAL MAIL", "-15.60", "7501"), "Card Purchase"),
              (Tx("2026-09-22", "PREMIER INN", "-89.00", "7402"), "Card Purchase"),
              (Tx("2026-09-27", "HMRC VAT", "-1210.33", "2202"), "Direct Debit"))
T_HSBC = (Tx("2026-09-03", "BRITISH GAS", "-86.40", "7201"), Tx("2026-09-11", "EE LIMITED", "-28.00", "7502"),
          Tx("2026-09-15", "NORTHWIND TRADING PAYMENT", "1800.00", "4000"),
          Tx("2026-09-24", "HMRC PAYE", "-2140.37", "2210"))
T_LLOYDS = ((Tx("2026-09-04", "SCREWFIX DIRECT", "-54.00", "7800"), "DEB"),
            (Tx("2026-09-08", "QUAYSIDE MEDIA LTD", "2750.00", "4000"), "FPI"),
            (Tx("2026-09-12", "TFL TRAVEL CH", "-12.80", "7400"), "DEB"),
            (Tx("2026-09-19", "XERO UK LTD", "-33.00", "8201"), "DD"))
T_MONZO = ((Tx("2026-09-05", "PRET A MANGER LONDON", "-6.45", "7406"), "09:12:44", "Card payment", "Pret A Manger", "Eating out"),
           (Tx("2026-09-09", "OAKRIDGE DESIGN INV 2026-14", "1450.00", "4000"), "14:03:10", "Faster payment", "Oakridge Design Ltd", "Income"),
           (Tx("2026-09-21", "UBER *TRIP", "-18.20", "7400"), "11:47:02", "Card payment", "Uber", "Transport"),
           (Tx("2026-09-26", "GOOGLE WORKSPACE", "-11.50", "8201"), "08:00:00", "Direct Debit", "Google Workspace", "Bills"))
T_STARLING = ((Tx("2026-09-03", "WeWork Desk rental September", "-295.00", "7100"), "WeWork", "Desk rental September", "DIRECT DEBIT", "BILLS_AND_SERVICES"),
              (Tx("2026-09-07", "Hartley & Co Invoice 2026-288", "-360.00", "7601"), "Hartley & Co", "Invoice 2026-288", "FASTER PAYMENT", "GENERAL"),
              (Tx("2026-09-15", "Brightwell Ltd INV NB-0112", "2100.00", "4000"), "Brightwell Ltd", "INV NB-0112", "FASTER PAYMENT", "INCOME"),
              (Tx("2026-09-23", "Avanti West Coast Rail", "-64.30", "7400"), "Avanti West Coast", "Rail", "CARD", "TRANSPORT"))
T_PREAMBLE = (Tx("2026-09-02", "ADOBE SYSTEMS", "-19.97", "8201"),
              Tx("2026-09-06", "CLIENT PAYMENT - FIELDHOUSE LTD", "1200.00", "4000"),
              Tx("2026-09-14", "COSTA COFFEE", "-8.40", "7406"),
              Tx("2026-09-29", "BARCLAYCARD COMMERCIAL FEES", "-12.00", "7901"))
T_TSV = (Tx("2026-09-03", "VIKING DIRECT STATIONERY", "-23.99", "7504"),
         Tx("2026-09-10", "KINGSTON CATERING LTD", "640.00", "4000"),
         Tx("2026-09-18", "DVLA VEHICLE TAX", "-190.00", "7302"))
T_XLSX = {"Sep 2026": (Tx("2026-09-04", "SAGE SUBSCRIPTION", "-26.40", "8201"),
                       Tx("2026-09-17", "RIVERSIDE DENTAL", "980.00", "4000"),
                       Tx("2026-09-25", "HISCOX INSURANCE", "-41.25", "8204")),
          "Oct 2026": (Tx("2026-10-02", "BT BUSINESS BROADBAND", "-72.00", "7502"),
                       Tx("2026-10-09", "RIVERSIDE DENTAL", "980.00", "4000"),
                       Tx("2026-10-20", "ROYAL MAIL", "-7.85", "7501"))}
T_PASTED_CSV = (Tx("2026-09-08", "MICROSOFT 365 BUSINESS", "-9.60", "8201"),
                Tx("2026-09-11", "ADOBE CREATIVE CLOUD", "-19.97", "8201"),
                Tx("2026-09-12", "CLIENT PAYMENT BRIGHTWELL LTD", "1250.00", "4000"),
                Tx("2026-09-14", "DIRECT LINE BUSINESS INSURANCE", "-38.12", "8204"))
_PAYEES = (("TESCO STORES", "-", "8205"), ("SHELL", "-", "7300"), ("AMAZON MARKETPLACE", "-", "9998"),
           ("CLIENT RECEIPT", "+", "4000"), ("UBER", "-", "7400"), ("VODAFONE", "-", "7502"),
           ("ROYAL MAIL", "-", "7501"), ("PRET A MANGER", "-", "7406"))


def _long_statement() -> tuple[Tx, ...]:
    rng = random.Random(2026)
    txs = []
    for n in range(60):
        name, sign, account = _PAYEES[n % len(_PAYEES)]
        pence = rng.randrange(150, 9000) if sign == "-" else rng.randrange(40000, 250000)
        txs.append(Tx(f"2026-09-{1 + n // 2:02d}", f"{name} {n + 1:03d}",
                      f"{'-' if sign == '-' else ''}{pence // 100}.{pence % 100:02d}", account))
    return tuple(txs)


T_LONG = _long_statement()

# Held out for account choice (added 2026-09-29): payees used nowhere else in these fixtures, with
# accounts set by standard UK bookkeeping before the prompt's account definitions were written.
T_UNSEEN = (Tx("2026-09-01", "KNIGHT FRANK RENT SEP", "-1850.00", "7100"),
            Tx("2026-09-02", "HALCYON STUDIOS LTD INV 2051", "4200.00", "4000"),
            Tx("2026-09-03", "WICKES", "-64.20", "7800"),
            Tx("2026-09-04", "CAFFE NERO", "-6.85", "7406"),
            Tx("2026-09-05", "RYMAN", "-23.97", "7504"),
            Tx("2026-09-08", "LNER", "-118.40", "7400"),
            Tx("2026-09-09", "ESSO", "-58.12", "7300"),
            Tx("2026-09-10", "PARCELFORCE", "-17.95", "7501"),
            Tx("2026-09-11", "O2 UK", "-36.00", "7502"),
            Tx("2026-09-12", "DROPBOX", "-15.99", "8201"),
            Tx("2026-09-15", "TRAVELODGE", "-72.50", "7402"),
            Tx("2026-09-16", "ADDISON LEE", "-34.60", "7400"),
            Tx("2026-09-17", "WAITROSE", "-18.35", "8205"),
            Tx("2026-09-18", "EBAY", "-42.99", "9998"),
            Tx("2026-09-19", "JOHN LEWIS", "-129.00", "9998"),
            Tx("2026-09-22", "HISCOX", "-48.75", "8204"),
            Tx("2026-09-24", "GOOGLE ADS", "-150.00", "9998"),   # no advertising account in the chart
            Tx("2026-09-25", "J MORGAN SALARY", "-2310.00", "7000"),
            Tx("2026-09-29", "MONTHLY ACCOUNT FEE", "-8.50", "7901"),
            Tx("2026-09-30", "GROSS INTEREST", "1.26", "4900"))

# Held out a second time (added 2026-09-29, before the third wording of the account rule, once
# T_UNSEEN had been used to choose between wordings). Payees used nowhere else. Some lines name
# what was bought from a seller of almost anything (the item decides); two such sellers appear with
# no detail (Suspense); two costs have no account in the chart (Suspense).
T_UNSEEN_MIXED = (Tx("2026-10-01", "ONBUY.COM - A4 COPIER PAPER", "-32.40", "7504"),
                  Tx("2026-10-01", "BRIGHTWATER DESIGN LTD INV 3107", "3150.00", "4000"),
                  Tx("2026-10-02", "TRAVIS PERKINS", "-86.30", "7800"),
                  Tx("2026-10-03", "GREGGS", "-5.60", "7406"),
                  Tx("2026-10-05", "GUMTREE - SECOND-HAND OFFICE DESK", "-120.00", "0040"),
                  Tx("2026-10-06", "PLUSNET", "-30.00", "7502"),
                  Tx("2026-10-07", "ETSY", "-24.50", "9998"),
                  Tx("2026-10-08", "ARGOS - LAPTOP FOR NEW STARTER", "-549.00", "0030"),
                  Tx("2026-10-09", "IBIS LONDON", "-94.00", "7402"),
                  Tx("2026-10-12", "LINKEDIN ADS", "-200.00", "9998"),                 # no advertising account
                  Tx("2026-10-13", "MORRISONS", "-21.75", "8205"),
                  Tx("2026-10-14", "MARKS & SPENCER - SANDWICHES FOR CLIENT MEETING", "-38.20", "7403"),
                  Tx("2026-10-15", "CANVA", "-10.99", "8201"),
                  Tx("2026-10-16", "NCP CAR PARKS", "-18.00", "7400"),
                  Tx("2026-10-19", "SELFRIDGES", "-210.00", "9998"),
                  Tx("2026-10-20", "DPD UK", "-12.49", "7501"),
                  Tx("2026-10-21", "COSTCO - MILK AND COFFEE FOR THE OFFICE", "-46.80", "8205"),
                  Tx("2026-10-22", "BP CONNECT", "-61.05", "7300"),
                  Tx("2026-10-26", "CAMDEN COUNCIL PENALTY CHARGE", "-65.00", "9998"),  # a fine: no account
                  Tx("2026-10-28", "OFFICE DEPOT", "-27.99", "7504"))

PRO_FORMA = ["Brightline IT Supplies Ltd", "8 Kings Road, Reading RG1 3AA", "PRO FORMA INVOICE",
             "Pro forma number: PF-0921", "Date: 22/09/2026", "To: Northbridge Consulting Ltd",
             "Dell 24in monitor x2                300.00", "VAT at 20%                           60.00",
             "Total payable in advance            360.00", "This is not a VAT invoice."]

SUPPLIER_STATEMENT = ["Clearway Office Supplies Ltd", "STATEMENT OF ACCOUNT", "Customer: Northbridge Consulting Ltd",
                      "Statement date: 30/09/2026", "08/09/2026  Invoice CW-20931            300.00",
                      "Balance due                           300.00"]

CASES: tuple[Case, ...] = (
    # Typed or pasted text (Quick Paste)
    Case("text-tesco-receipt", "text", "input.txt", _text(TESCO), T_TESCO, document_type="receipt"),
    Case("text-hmrc-vat-payment", "text", "input.txt", _text("HMRC VAT settlement payment 1450.00 paid 07/09/2026"),
         (Tx("2026-09-07", "HMRC VAT settlement payment", "-1450.00", "2202"),)),
    Case("text-supplier-refund", "text", "input.txt",
         _text("Refund from Amazon for returned printer 89.99 received 05/09/2026"),
         (Tx("2026-09-05", "Refund from Amazon for returned printer", "89.99", "0030"),)),
    Case("text-paye", "text", "input.txt",
         _text("Paid HMRC PAYE and National Insurance for August: £2,140.37 on 19/09/2026"),
         (Tx("2026-09-19", "HMRC PAYE and National Insurance", "-2140.37", "2210"),)),
    Case("text-savings-transfer", "text", "input.txt",
         _text("Moved £5,000.00 from the current account to the business savings account on 15/09/2026"),
         (Tx("2026-09-15", "Transfer to business savings account", "-5000.00", "1210"),)),
    Case("text-notes", "text", "input.txt", _text(
        "02/09/2026 Consulting services sold to ACME Corp for £2,400.00\n"
        "01/09/2026 BT Business Broadband monthly bill £72.00\n"
        "10/09/2026 Office chair from IKEA £149.99"),
         (Tx("2026-09-02", "Consulting services sold to ACME Corp", "2400.00", "4000"),
          Tx("2026-09-01", "BT Business Broadband monthly bill", "-72.00", "7502"),
          Tx("2026-09-10", "Office chair from IKEA", "-149.99", "0040"))),
    Case("text-pasted-csv", "text", "input.txt", lambda: _statement_csv(T_PASTED_CSV, "5000.00"), T_PASTED_CSV),
    # Photos of receipts
    Case("img-tesco-receipt", "image", "input.png", lambda: _receipt_png(TESCO.splitlines()), T_TESCO, document_type="receipt"),
    Case("img-cafe-receipt-vat", "image", "input.png", lambda: _receipt_png(CAFE),
         (Tx("2026-09-12", "The Daily Grind Cafe", "-7.50", "7406", vat="1.25"),), document_type="receipt"),
    Case("img-fuel-receipt-rotated", "image", "input.png", lambda: _receipt_png(FUEL, rotate=2.0, noise=True),
         (Tx("2026-09-16", "Shell Westway fuel", "-68.39", "7300", vat="11.40"),), document_type="receipt"),
    Case("img-train-ticket", "image", "input.png", lambda: _receipt_png(TRAIN),
         (Tx("2026-09-17", "Trainline London Euston to Manchester Piccadilly", "-87.50", "7400"),), document_type="receipt"),
    # Zero-rated food plus standard-rated household goods: only 0.70 of the 7.95 is VAT. The VAT summary divides by
    # rate, not by account, so the reader keeps it whole (mixed_items) for the agent to split.
    Case("img-supermarket-mixed-vat", "image", "input.png", lambda: _receipt_png(MIXED_VAT),
         (Tx("2026-09-18", "Sainsbury's Local", "-7.95", "7801", vat="0.70"),), document_type="receipt"),
    # Two kinds of expense and no VAT shown: one row per account.
    Case("text-expense-note-mixed", "text", "input.txt",
         _text("Expenses 12/09/2026\nBreakfast £18.00\nTaxi to client £32.00\nTotal £50.00"),
         (Tx("2026-09-12", "Breakfast", "-18.00", "7406"), Tx("2026-09-12", "Taxi to client", "-32.00", "7400")), document_type="expense_claim"),
    # Two kinds of item but one VAT total that cannot be divided: one row, on the biggest item's account.
    Case("text-mixed-receipt-one-vat", "text", "input.txt",
         _text("WHSMITH\nKings Cross Station\nVAT No 238 5548 36\n15/09/2026 08:12\nCoffee to go     3.00\n"
               "A4 notebook      9.00\nVAT              2.00\nTOTAL           12.00\nCARD            12.00"),
         (Tx("2026-09-15", "WHSmith", "-12.00", "7504", vat="2.00"),), document_type="receipt"),
    # PDFs
    Case("pdf-purchase-invoice", "pdf", "input.pdf", lambda: _text_pdf(PURCHASE_INVOICE),
         (Tx("2026-09-08", "Clearway Office Supplies Ltd", "-300.00", "7504", vat="50.00"),), document_type="invoice"),
    Case("pdf-paid-invoice", "pdf", "input.pdf", lambda: _placed_pdf(PAID_INVOICE),
         (Tx("2026-09-14", "Brightline IT Supplies Ltd", "-1260.00", "0030", vat="210.00"),), document_type="invoice"),
    Case("pdf-sales-invoice", "pdf", "input.pdf", lambda: _text_pdf(SALES_INVOICE),
         (Tx("2026-09-30", "Harbour & Lane Architects LLP", "2400.00", "4000", vat="400.00"),),
         document_type="invoice"),
    Case("pdf-scanned-invoice", "pdf", "input.pdf", lambda: _scanned_pdf(ACCOUNTANT_INVOICE),
         (Tx("2026-09-25", "Hartley & Co Chartered Accountants", "-540.00", "7601", vat="90.00"),), document_type="invoice"),
    Case("pdf-bank-statement", "pdf", "input.pdf", lambda: _text_pdf(STATEMENT),
         (Tx("2026-09-03", "BRITISH GAS BUSINESS", "-86.40", "7201"),
          Tx("2026-09-05", "LANDMARK PROPERTIES RENT", "-1250.00", "7100"),
          Tx("2026-09-09", "HARBOUR & LANE ARCHITECTS", "3600.00", "4000"),
          Tx("2026-09-20", "BARCLAYS BANK CHARGES", "-8.50", "7901"),
          Tx("2026-09-28", "OCTOPUS ENERGY", "-142.18", "7200"))),
    # Documents that are not transactions: their amounts are listed for a person to check, not booked.
    Case("pdf-pro-forma", "pdf", "input.pdf", lambda: _text_pdf(PRO_FORMA),
         (Tx("2026-09-22", "Brightline IT Supplies Ltd", "-360.00", "0030", vat="60.00"),), document_type="pro_forma"),
    Case("pdf-supplier-statement", "pdf", "input.pdf", lambda: _text_pdf(SUPPLIER_STATEMENT),
         (Tx("2026-09-08", "Clearway Office Supplies Ltd", "-300.00", "7504"),), document_type="supplier_statement"),
    # Bank exports
    Case("csv-barclays-probe", "table", "input.csv", lambda: _statement_csv(T_PROBE_CSV, "1306.56"), T_PROBE_CSV),
    Case("csv-barclays-export", "table", "input.csv", lambda: _barclays_export(T_BARCLAYS),
         tuple(tx for tx, _ in T_BARCLAYS)),
    Case("csv-hsbc-no-header", "table", "input.csv", lambda: _hsbc(T_HSBC), T_HSBC),
    Case("csv-lloyds-debit-credit", "table", "input.csv", lambda: _lloyds(T_LLOYDS, "6174.33"),
         tuple(tx for tx, _ in T_LLOYDS)),
    Case("csv-monzo", "table", "input.csv", lambda: _monzo(T_MONZO), tuple(entry[0] for entry in T_MONZO)),
    Case("csv-starling", "table", "input.csv", lambda: _starling(T_STARLING, "3200.00"),
         tuple(entry[0] for entry in T_STARLING)),
    Case("csv-preamble-cp1252-brackets", "table", "input.csv", lambda: _preamble_cp1252(T_PREAMBLE, "5000.00"),
         T_PREAMBLE),
    Case("tsv-utf16-unicode-text", "table", "input.tsv", lambda: _utf16_tsv(T_TSV), T_TSV),
    Case("xlsx-two-months", "table", "input.xlsx", lambda: _xlsx(T_XLSX), T_XLSX["Sep 2026"] + T_XLSX["Oct 2026"]),
    Case("csv-long-statement-60-rows", "table", "input.csv", lambda: _statement_csv(T_LONG, "20000.00"), T_LONG),
    Case("csv-unseen-payees", "table", "input.csv", lambda: _statement_csv(T_UNSEEN, "12000.00"), T_UNSEEN),
    Case("csv-unseen-mixed", "table", "input.csv", lambda: _statement_csv(T_UNSEEN_MIXED, "9000.00"),
         T_UNSEEN_MIXED),
)
