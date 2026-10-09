from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from ledgersync.config import Settings
from ledgersync.extractor import TransactionExtractor
from ledgersync.intake import load_upload
from ledgersync.model_client import ModelClient
from ledgersync.pipeline import prepare_image

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


def test_the_model_reads_a_receipt_photo():
    client = live_client()
    photo = (FIXTURES / "img-train-ticket" / "input.png").read_bytes()
    result = TransactionExtractor(client).extract_accounting_data(images=[prepare_image(photo)])
    assert any(abs(abs(t.amount) - 87.50) < 0.01 for t in result.data)
