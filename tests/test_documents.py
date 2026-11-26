import io

import pytest
from fakes import chat_answer
from test_model_client import OPENROUTER, make_client

from ledgersync import documents
from ledgersync.blobs import MemoryBlobStore
from ledgersync.config import Settings
from ledgersync.documents import PAGE_CHARS, text_of
from ledgersync.errors import ModelUnavailable


class FakeRecords:
    """Stands in for AgentRecords' document-text cache."""

    def __init__(self):
        self.saved = {}

    def document_text(self, sha256):
        entry = self.saved.get(sha256)
        return list(entry[0]) if entry else None

    def save_document_text(self, sha256, pages, method, model):
        self.saved[sha256] = (list(pages), method, model)


class FakeVision:
    model = "vision-model"

    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def transcribe(self, image_b64):
        self.calls.append(image_b64)
        return self.answers.pop(0)


def keep(blobs, name, data):
    """An upload row for bytes kept in the blob store."""
    return {"id": 1, "name": name, "kind": "statement", "sha256": blobs.put(data, name=name, content_type="x")}


def png(color="white"):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), color).save(buf, "PNG")
    return buf.getvalue()


def pdf(*texts):
    import pymupdf
    doc = pymupdf.open()
    for text in texts:
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), text)
    return doc.tobytes()


def test_csv_comes_back_as_is():
    blobs, records = MemoryBlobStore(), FakeRecords()
    upload = keep(blobs, "bank.csv", b"Date,Amount\n2025-01-02,10.00\n")
    assert text_of(upload, blobs, records) == ["Date,Amount\n2025-01-02,10.00"]
    assert records.saved[upload["sha256"]][1:] == ("text", "")


def test_xlsx_as_tab_separated():
    import openpyxl
    book = openpyxl.Workbook()
    book.active.append(["Date", "Amount"])
    book.active.append(["2025-01-02", 10])
    buf = io.BytesIO()
    book.save(buf)
    blobs = MemoryBlobStore()
    pages = text_of(keep(blobs, "bank.xlsx", buf.getvalue()), blobs, FakeRecords())
    assert len(pages) == 1
    assert pages[0].splitlines()[1] == "Date\tAmount"
    assert pages[0].splitlines()[2] == "2025-01-02\t10"


def test_long_text_split_into_12k_pages():
    line = "x" * 99 + "\n"
    blobs = MemoryBlobStore()
    pages = text_of(keep(blobs, "big.txt", (line * 300).encode()), blobs, FakeRecords())
    assert len(pages) == 3 and all(len(p) <= PAGE_CHARS == 12_000 for p in pages)
    assert all(p.endswith("x") for p in pages[:-1])   # broke at a newline, not mid-line
    assert "\n".join(pages).count("x" * 99) == 300


def test_a_line_longer_than_a_page_is_cut_at_the_limit():
    assert documents._split("y" * 25_000) == ["y" * 12_000, "y" * 12_000, "y" * 1_000]


def test_image_uses_vision_once():
    blobs, records, vision = MemoryBlobStore(), FakeRecords(), FakeVision("Receipt total 5.00")
    upload = keep(blobs, "receipt.png", png())
    assert text_of(upload, blobs, records, vision) == ["Receipt total 5.00"]
    assert text_of(upload, blobs, records, vision) == ["Receipt total 5.00"]
    assert len(vision.calls) == 1
    assert records.saved[upload["sha256"]][1:] == ("vision", "vision-model")


def test_text_pdf_needs_no_vision():
    blobs, vision = MemoryBlobStore(), FakeVision()
    pages = text_of(keep(blobs, "s.pdf", pdf("Opening balance 100")), blobs, FakeRecords(), vision)
    assert "Opening balance 100" in pages[0] and vision.calls == []


def test_each_page_of_a_text_pdf_is_its_own_page():
    blobs, vision = MemoryBlobStore(), FakeVision()
    pages = text_of(keep(blobs, "s.pdf", pdf("Page one", "Page two", "Page three")), blobs, FakeRecords(), vision)
    assert len(pages) == 3 and "Page one" in pages[0] and "Page three" in pages[2] and vision.calls == []


def test_scanned_pdf_is_transcribed_page_by_page():
    blobs, records, vision = MemoryBlobStore(), FakeRecords(), FakeVision("page one", "page two")
    upload = keep(blobs, "scan.pdf", pdf("", ""))
    assert text_of(upload, blobs, records, vision) == ["page one", "page two"]
    assert records.saved[upload["sha256"]][1:] == ("vision", "vision-model")


def test_a_cached_text_is_returned_without_reading_the_file():
    records = FakeRecords()
    records.save_document_text("abc", ["cached"], "text", "")
    assert text_of({"id": 1, "name": "a.csv", "sha256": "abc"}, MemoryBlobStore(), records) == ["cached"]


def test_an_upload_without_an_original_has_no_text_and_caches_nothing():
    records = FakeRecords()
    assert text_of({"id": 1, "name": "manual", "kind": "manual", "sha256": ""}, MemoryBlobStore(), records) == []
    assert records.saved == {}


def test_an_image_without_the_vision_model_says_so():
    blobs, records = MemoryBlobStore(), FakeRecords()
    with pytest.raises(ModelUnavailable, match="needs the vision model"):
        text_of(keep(blobs, "r.png", png()), blobs, records)
    assert records.saved == {}


def test_transcribe_asks_for_a_plain_faithful_transcript():
    client, http, _, _ = make_client(chat_answer("Date  Amount\n2025-01-02  10.00"))
    assert client.transcribe("aW1hZ2U=") == "Date  Amount\n2025-01-02  10.00"
    body = http.payload()
    assert "response_format" not in body and body["temperature"] == 0
    content = body["messages"][-1]["content"]
    assert content[1]["image_url"]["url"] == "data:image/jpeg;base64,aW1hZ2U="
    rules = body["messages"][0]["content"].lower()
    assert "exactly as printed" in rules and "no commentary" in rules


def test_transcribe_on_openrouter_keeps_to_the_set_hosts_and_precisions():
    client, http, _, _ = make_client(chat_answer("text"), settings=OPENROUTER)
    client.transcribe("aW1hZ2U=")
    # The same hosts and precisions as chat_json; no require_parameters, as there is no schema to honour.
    assert http.payload()["provider"] == {"order": ["deepinfra/bf16"],
                                          "quantizations": ["bf16", "fp16", "fp32", "fp8"]}


def test_transcribe_leaves_routing_alone_when_none_is_set_and_on_groq():
    client, http, _, _ = make_client(chat_answer("text"), settings=Settings(
        openrouter_api_key="k", openrouter_providers=(), openrouter_quantizations=()))
    client.transcribe("aW1hZ2U=")
    assert "provider" not in http.payload()
    client, http, _, _ = make_client(chat_answer("text"))
    client.transcribe("aW1hZ2U=")
    assert "provider" not in http.payload()
