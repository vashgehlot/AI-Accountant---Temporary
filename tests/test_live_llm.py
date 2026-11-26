from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from ledgersync.config import Settings
from ledgersync.extractor import TransactionExtractor
from ledgersync.intake import load_upload
from ledgersync.model_client import ModelClient
from ledgersync.pipeline import pdf_text, prepare_image

pytestmark = pytest.mark.llm
FIXTURES = Path(__file__).parent.parent / "eval" / "fixtures"
PRIVATE = Path(__file__).parent.parent / "eval" / "private"   # clients' documents: git-ignored


def live_client() -> ModelClient:
    settings = Settings.from_env()   # OpenRouter when OPENROUTER_API_KEY is set, otherwise Groq
    if not settings.api_key:
        pytest.skip("set OPENROUTER_API_KEY or GROQ_API_KEY (e.g. in .env) to run")
    client = ModelClient(settings)
    client.ensure_available()
    return client


def read_claim(text: str, times: int, business: str) -> list[list[float]]:
    """The amounts of each read of a claim for `business`, read `times` times side by side: one read can be lucky."""
    client = live_client()
    reader = TransactionExtractor(client, business_name=business, business_type="limited_company")
    with ThreadPoolExecutor(times) as pool:
        return list(pool.map(lambda _: [t.amount for t in reader.extract_accounting_data(text_input=text).data],
                             range(times)))


def test_every_line_of_an_expense_claim_is_read():
    # Jenny's claim lists 13 lines; the one just above the VATable subtotal (Southgate Bath Car Park, £54.00 on 24/09)
    # was left out in 11 reads of 15, and in 13 of 13 on another host; how often changes from hour to hour, so it is
    # read eight times (2026-10-08).
    path = PRIVATE / "jenny" / "expense-claim-2026-09.xlsx"
    if not path.is_file():
        pytest.skip(f"needs {path.relative_to(PRIVATE.parent.parent)}")
    text = load_upload(path.name, path.read_bytes(), max_pdf_pages=30).text
    for amounts in read_claim(text, times=8, business="Jenny"):   # as the client was named in the app
        assert (len(amounts), round(sum(amounts), 2)) == (13, 1048.52), amounts


def test_a_claim_whose_total_is_wrong_gets_no_line_made_up():
    # Checking the lines against the total must not invent a line to make them agree.
    text = """Sam Patel — Expense Claim, September 2026 · 3 lines
Date,Merchant,Category,Gross,VAT
02/09/2026,Pret A Manger,Subsistence,12.40,
10/09/2026,NCP Bristol,Parking,18.00,3.00
21/09/2026,GWR,Train,29.60,
,,TOTAL CLAIM,75.00,"""
    for amounts in read_claim(text, times=2, business="Acting Office"):
        assert sorted(amounts) == [12.40, 18.00, 29.60], amounts


def test_an_amount_charged_is_not_added_to_the_vat_printed_under_it():
    # Matt's M6 toll receipt prints "Charged Amount £12.00" and "VAT (20%) £2.00": it was read as £14.00.
    path = PRIVATE / "matt" / "M6toll-2026-09-14_14_55_26.jpg"
    if not path.is_file():
        pytest.skip(f"needs {path.relative_to(PRIVATE.parent.parent)}")
    client = live_client()
    reader = TransactionExtractor(client, business_name="Matts", business_type="limited_company")
    photo = prepare_image(path.read_bytes())
    with ThreadPoolExecutor(4) as pool:
        reads = list(pool.map(lambda _: [(t.amount, t.vat) for t in reader.extract_accounting_data(images=[photo]).data],
                              range(4)))
    assert reads == [[(12.0, 2.0)]] * 4, reads


def test_a_suppliers_statement_of_card_payments_is_receipts_not_a_bank_statement():
    # Transport for London's contactless "Payment Statement" for the card Jenny travels on (a charge for each of eight
    # days, £61.50 in all) was read as her bank statement in 4 reads of 4: the 21 receipts dated inside it then looked
    # unpaid by the bank and were kept in Suspense (2026-11-16).
    path = PRIVATE / "jenny" / "Transport_for_London-2026-10-31_00_00_00.pdf"
    if not path.is_file():
        pytest.skip(f"needs {path.relative_to(PRIVATE.parent.parent)}")
    client = live_client()
    reader = TransactionExtractor(client, business_name="jenny", business_type="limited_company")
    text = pdf_text(path.read_bytes())
    with ThreadPoolExecutor(4) as pool:
        reads = list(pool.map(lambda _: sorted((t.date, t.document_type, t.direction, t.amount)
                                               for t in reader.extract_accounting_data(text_input=text).data),
                              range(4)))
    charged = [("2026-10-05", 6.10), ("2026-10-06", 10.50), ("2026-10-07", 10.00), ("2026-10-08", 7.20),
               ("2026-10-10", 6.00), ("2026-10-20", 6.60), ("2026-10-21", 8.90), ("2026-10-27", 6.20)]
    assert reads == [[(day, "receipt", "out", amount) for day, amount in charged]] * 4, reads


def test_a_receipt_photos_small_vat_number_is_read():
    # Southgate car park prints "V.A.T No. 870 487 106" in small type at the foot of a long receipt: at 1200 pixels it
    # was missed in 8 reads of 8, so its VAT was left in the cost; at 2000 it was read in about 22 of 23 (2026-11-16).
    # So one read in four may miss it; at 1200, none would get it.
    path = PRIVATE / "jenny" / "Southgate_Bath_Car_Park-2026-10-08_20_30_00.jpg"
    if not path.is_file():
        pytest.skip(f"needs {path.relative_to(PRIVATE.parent.parent)}")
    reader = TransactionExtractor(live_client(), business_name="Jenny", business_type="limited_company")
    photo = prepare_image(path.read_bytes())
    with ThreadPoolExecutor(4) as pool:
        reads = list(pool.map(lambda _: [(t.amount, t.vat, "".join(c for c in t.supplier_vat_number or "" if c.isdigit()))
                                         for t in reader.extract_accounting_data(images=[photo]).data], range(4)))
    assert reads.count([(72.0, 12.0, "870487106")]) >= 3, reads


def test_a_shops_till_receipt_is_money_out_though_it_prints_sale():
    # Victoria Food & Groceries' till receipt names no customer and prints "Sale" above its one item: the app read it
    # as money in, and so did 1 read of 28 before the instructions said which way a shop's receipt goes (2026-11-16).
    # One read can be lucky, so it is read eight times.
    path = PRIVATE / "jenny" / "Victoria_Food___Groceries-2026-10-08_11_59_41.jpg"
    if not path.is_file():
        pytest.skip(f"needs {path.relative_to(PRIVATE.parent.parent)}")
    client = live_client()
    reader = TransactionExtractor(client, business_name="jenny", business_type="limited_company")
    photo = prepare_image(path.read_bytes())
    with ThreadPoolExecutor(8) as pool:
        reads = list(pool.map(lambda _: [(t.direction, t.amount)
                                         for t in reader.extract_accounting_data(images=[photo]).data], range(8)))
    assert reads == [[("out", 3.99)]] * 8, reads


def test_the_model_reads_a_receipt_photo():
    client = live_client()
    photo = (FIXTURES / "img-train-ticket" / "input.png").read_bytes()
    result = TransactionExtractor(client).extract_accounting_data(images=[prepare_image(photo)])
    assert any(abs(abs(t.amount) - 87.50) < 0.01 for t in result.data)


def _people(name: str, times: int = 4) -> list:
    path = PRIVATE / "jenny" / name
    if not path.is_file():
        pytest.skip(f"needs {path.relative_to(PRIVATE.parent.parent)}")
    reader = TransactionExtractor(live_client(), business_name="Jenny", business_type="limited_company")
    photo = prepare_image(path.read_bytes())
    with ThreadPoolExecutor(times) as pool:
        return list(pool.map(lambda _: [t.people for t in reader.extract_accounting_data(images=[photo]).data],
                             range(times)))


def test_people_a_group_order_of_pastries_and_drinks_is_for_several():
    # ExCeL, 8 Oct: fruit salad, pastries, tea, coffee: coffees for the team at DAS, booked as Jenny's lunch (2026-11-17).
    reads = _people("ExCel_London_Hospitality-2026-10-08_08_59_00.jpg")
    assert sum(r == ["several"] for r in reads) >= 3, reads


def test_people_one_sandwich_is_for_one():
    reads = _people("Bagel_Factory-2026-10-07_14_43_07.jpg")
    assert sum(r == ["one"] for r in reads) >= 3, reads


def _bought(case: str, times: int = 4) -> list:
    """What the reader says was bought on a public fixture's receipt, read `times` times (generic receipts, not a
    client's: the field must hold for any business)."""
    reader = TransactionExtractor(live_client(), business_name="Northbridge Consulting", business_type="limited_company")
    photo = prepare_image((FIXTURES / case / "input.png").read_bytes())
    with ThreadPoolExecutor(times) as pool:
        return list(pool.map(lambda _: [t.bought for t in reader.extract_accounting_data(images=[photo]).data],
                             range(times)))


def test_bought_goes_by_the_items_not_the_shop():
    # Milk, bread and bananas from Sainsbury's are groceries; a meal deal, coffee and sandwich from Tesco are food to
    # go, though Tesco is a supermarket.
    groceries = _bought("img-supermarket-mixed-vat")
    assert sum(bool(r) and all(b == "groceries" for b in r) for r in groceries) >= 3, groceries
    to_go = _bought("img-tesco-receipt")
    assert sum(r == ["food_to_go"] for r in to_go) >= 3, to_go


def test_bought_a_cafe_receipt_is_food_out_not_groceries():
    reads = _bought("img-cafe-receipt-vat")
    assert sum(r and r[0] in ("food_to_go", "meal_out") for r in reads) >= 3, reads
