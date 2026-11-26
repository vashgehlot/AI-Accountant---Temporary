import base64
import io
import logging

import pymupdf
import pytest
from PIL import Image

from ledgersync.extractor import TransactionExtractionResult
from ledgersync.intake import Intake
from ledgersync.jobs import Job, JobCancelled, JobContext
from ledgersync.pipeline import analyze, prepare_image


class RecordingExtractor:
    """Records what reaches the model; like Groq, its client reads at most three images per request."""

    def __init__(self):
        self.calls = []
        self.client = type("Client", (), {"model": "fake-model", "max_images": 3})()

    def extract_accounting_data(self, text_input=None, images=None):
        self.calls.append({"text": text_input, "images": images})
        return TransactionExtractionResult(data=[], model="fake-model",
                                           warnings=[f"Row 1 skipped (call {len(self.calls)})."])


def ctx():
    return JobContext(Job(id="test"))


def png():
    buf = io.BytesIO()
    Image.new("RGB", (60, 30), "white").save(buf, "PNG")
    return buf.getvalue()


def photo(size=(3000, 1000), orientation=None):
    buf = io.BytesIO()
    exif = Image.Exif()
    if orientation:
        exif[0x0112] = orientation
    Image.new("RGB", size, "white").save(buf, "JPEG", exif=exif)
    return buf.getvalue()


def text_pdf(text="Invoice total 120.00"):
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), text)
    return doc.tobytes()


def table_pdf(rows, columns=(40, 110, 330, 400, 470)):
    """A table with every cell placed on its own, as Excel and bank exports write their PDFs."""
    doc = pymupdf.open()
    page = doc.new_page()
    for n, cells in enumerate(rows):
        for x, cell in zip(columns, cells):
            page.insert_text((x, 80 + 12 * n), cell, fontsize=9)
    return doc.tobytes()


def scanned_pdf(pages):
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page()
        page.insert_image(page.rect, stream=png())
    return doc.tobytes()


def test_text_goes_straight_to_the_model():
    ex = RecordingExtractor()
    analyze(Intake("text", text="BT 72.00"), ex, ctx())
    assert ex.calls == [{"text": "BT 72.00", "images": None}]


def test_a_pdf_with_a_text_layer_goes_as_text():
    ex = RecordingExtractor()
    analyze(Intake("pdf", data=text_pdf()), ex, ctx())
    assert "Invoice total 120.00" in ex.calls[0]["text"] and ex.calls[0]["images"] is None


def test_a_pdf_table_reaches_the_model_one_row_per_line():
    # Each payment's date, description and amounts must arrive together, not one column after another.
    rows = [("Date", "Particulars", "Debit", "Credit", "Balance"),
            ("06/11/2020", "BANK HILTON LORD Greys", "-", "465.00", "465.00"),
            ("09/11/2020", "Annual Card Fee", "69.00", "-", "396.00"),
            ("11/03/2021", "BANK HILTON LORD Greys", "-", "765.00", "1,161.00")]
    ex = RecordingExtractor()
    analyze(Intake("pdf", data=table_pdf(rows)), ex, ctx())
    lines = [line.split() for line in ex.calls[0]["text"].splitlines()]
    assert ["09/11/2020", "Annual", "Card", "Fee", "69.00", "-", "396.00"] in lines
    assert ["11/03/2021", "BANK", "HILTON", "LORD", "Greys", "-", "765.00", "1,161.00"] in lines


def test_photos_go_to_the_model_as_images():
    ex = RecordingExtractor()
    analyze(Intake("image", data=photo()), ex, ctx())
    assert ex.calls[0]["text"] is None and len(ex.calls[0]["images"]) == 1


def test_a_sideways_phone_photo_is_sent_upright_at_most_2000_pixels_and_as_jpeg():
    # EXIF orientation 6: the phone was turned 90 degrees; the pixels are stored sideways. 2000, not 1200: at 1200 a
    # receipt's small print (its VAT number) was lost.
    sent = Image.open(io.BytesIO(base64.b64decode(prepare_image(photo((3000, 1000), orientation=6)))))
    assert sent.format == "JPEG" and max(sent.size) == 2000 and sent.size[0] < sent.size[1]


def test_a_photo_smaller_than_the_limit_is_not_enlarged():
    sent = Image.open(io.BytesIO(base64.b64decode(prepare_image(photo((800, 600))))))
    assert sent.size == (800, 600)


def test_scanned_pages_go_three_per_request_and_warnings_name_their_pages():
    ex = RecordingExtractor()
    result = analyze(Intake("pdf", data=scanned_pdf(5)), ex, ctx())
    assert [len(c["images"]) for c in ex.calls] == [3, 2]
    assert result.warnings == ["Pages 1-3: Row 1 skipped (call 1).", "Pages 4-5: Row 1 skipped (call 2)."]


def test_a_single_scanned_page_needs_no_page_labels():
    ex = RecordingExtractor()
    result = analyze(Intake("pdf", data=scanned_pdf(1)), ex, ctx())
    assert len(ex.calls) == 1 and result.warnings == ["Row 1 skipped (call 1)."]


def test_cancel_before_model_call_skips_it():
    ex, job = RecordingExtractor(), Job(id="test")
    job.cancel_requested.set()
    with pytest.raises(JobCancelled):
        analyze(Intake("text", text="x"), ex, JobContext(job))
    assert ex.calls == []


def test_document_text_is_never_logged(caplog):
    # Our own code at DEBUG; third-party loggers stay at WARNING, see test_logging.
    caplog.set_level(logging.DEBUG, logger="ledgersync")
    analyze(Intake("pdf", data=text_pdf("MRS CLIENT SECRET 12.50")), RecordingExtractor(), ctx())
    assert "CLIENT SECRET" not in caplog.text


def test_rendering_pdf_pages_waits_for_the_pymupdf_lock():
    import threading
    from ledgersync.intake import PYMUPDF_LOCK
    from ledgersync.pipeline import _pdf_pages
    doc = pymupdf.open()
    doc.new_page()
    pdf, done = doc.tobytes(), threading.Event()
    with PYMUPDF_LOCK:
        threading.Thread(target=lambda: (_pdf_pages(pdf), done.set())).start()
        assert not done.wait(0.3)
    assert done.wait(5)


def test_reading_pdf_text_waits_for_the_pymupdf_lock():
    import threading
    from ledgersync.intake import PYMUPDF_LOCK
    from ledgersync.pipeline import _pdf_text
    pdf, done = text_pdf(), threading.Event()
    with PYMUPDF_LOCK:
        threading.Thread(target=lambda: (_pdf_text(pdf), done.set())).start()
        assert not done.wait(0.3)
    assert done.wait(5)


class StatementExtractor(RecordingExtractor):
    """Reads one batch of pages per call: the first batch prints the opening balance, the second the closing one."""

    def extract_accounting_data(self, text_input=None, images=None):
        self.calls.append({"text": text_input, "images": images})
        first = len(self.calls) == 1
        return TransactionExtractionResult(data=[], model="fake-model", opening_balance=1000.0 if first else None,
                                           closing_balance=None if first else 928.0,
                                           agent="R+R PR Ltd" if first else None)


def test_a_scanned_statements_opening_comes_from_its_first_pages_and_closing_from_its_last():
    result = analyze(Intake("pdf", data=scanned_pdf(5)), StatementExtractor(), ctx())
    assert (result.opening_balance, result.closing_balance) == (1000.0, 928.0)
    assert result.agent == "R+R PR Ltd"   # an agent's statement names its agent once, on its first pages


class HostsExtractor(RecordingExtractor):
    """Each batch of pages is read by the next host in turn."""

    def extract_accounting_data(self, text_input=None, images=None):
        self.calls.append({"text": text_input, "images": images})
        host = ["DeepInfra", "Parasail", "DeepInfra"][len(self.calls) - 1]
        return TransactionExtractionResult(data=[], model=f"fake-model via {host}")


def test_pages_read_by_different_hosts_name_each_host_once():
    result = analyze(Intake("pdf", data=scanned_pdf(7)), HostsExtractor(), ctx())   # pages 1-3, 4-6 and 7
    assert result.model == "fake-model via DeepInfra; fake-model via Parasail"


# ─── Bank and payment exports read in code (design of 2026-11-23) ─────────────

import json as _json  # noqa: E402

from fakes import FakeModel  # noqa: E402

from ledgersync.extractor import TransactionExtractor  # noqa: E402

HSBC_CSV = ("Date,Type,Description,Amount,Balance\n28 Apr 2023,BP,LEAH MORGAN SALARY,-3149.87,8263.46\n"
            "29 Apr 2023,DD,BT GROUP,-72.00,8191.46\n")
STRIPE_CSV = ("automatic_payout_id,automatic_payout_effective_at,balance_transaction_id,created_utc,currency,gross,"
              "fee,net,reporting_category,description,customer_name\n"
              ",,txn_1,2023-04-04 12:00:00,gbp,720.00,11.00,709.00,charge,Retainer Apr 2023,Moss & Pine Florists\n")


def test_a_recognised_csv_is_read_in_code_and_coded():
    fake = FakeModel([_json.dumps({"lines": [
        {"n": 1, "account": "2220", "counterparty": "Leah Morgan", "alternatives": [], "bought": None, "people": None},
        {"n": 2, "account": "7502", "counterparty": "BT", "alternatives": [], "bought": None, "people": None}]})])
    result = analyze(Intake("table", text=HSBC_CSV), TransactionExtractor(fake), ctx(), name="hsbc.csv",
                     account="1200")
    assert len(fake.calls) == 1 and set(fake.calls[0]["schema"]["properties"]) == {"lines"}
    assert [(r.amount, r.account) for r in result.data] == [(3149.87, "2220"), (72.0, "7502")]
    assert result.warnings[0] == "Read in code: 2 lines"


def test_a_processor_export_needs_no_model():
    extractor = RecordingExtractor()
    result = analyze(Intake("table", text=STRIPE_CSV), extractor, ctx(), name="stripe-statement.csv", account="1200")
    assert extractor.calls == [] and len(result.data) == 2 and result.agent == "Stripe"


def test_an_unrecognised_table_is_read_as_today():
    extractor = RecordingExtractor()
    result = analyze(Intake("table", text="Name,Notes\nA,B\n"), extractor, ctx(), name="notes.csv", account="1200")
    assert len(extractor.calls) == 1 and result.warnings[0] == "Columns not recognised: read by the model"


def test_a_card_issuers_export_on_a_bank_account_is_left_to_the_model():
    # A client whose only account is current: an Amex file would be read with the bank's signs.
    extractor = RecordingExtractor()
    analyze(Intake("table", text="Date,Description,Amount\n09/04/2023,STREAMFLIX.COM,10.99\n"), extractor, ctx(),
            name="amex-statement.csv", account="1200")
    assert len(extractor.calls) == 1


def test_an_empty_statement_needs_no_model():
    extractor = RecordingExtractor()
    result = analyze(Intake("table", text="Date,Type,Description,Amount,Balance\n"), extractor, ctx(),
                     name="savings-statement.csv", account="1210")
    assert extractor.calls == [] and result.data == [] and result.warnings == ["Read in code: 0 lines"]
