from datetime import date
from decimal import Decimal as D

from pypdf import PdfReader

from testbooks.books.bank import StatementLine
from testbooks.engine.model import MoneyAccount
from testbooks.render.documents import render_answer, render_doc
from testbooks.render.statements import hsbc_amount, render_statement
from testbooks.tests.test_ledger import W

HSBC = MoneyAccount("hsbc", "Business current", "Severn Bank", "hsbc_csv", "1200")


def pdf_text(path):
    return "".join(p.extract_text() for p in PdfReader(path).pages)


def test_hsbc_amounts():
    assert [hsbc_amount(D(x)) for x in ("-70.00", "1010.00", "276.10", "-80.78")] == ["-70.0", "1010.0", "276.1", "-80.78"]


def test_hsbc_csv_newest_first_and_balances_chain(tmp_path):
    lines = [StatementLine("l1", "hsbc", date(2024, 3, 1), "DD", "NORTHCLIFFE TELECOM", D("-216.00"), D("9784.00")),
             StatementLine("l2", "hsbc", date(2024, 3, 15), "CR", "BRIGHTWATER HOMES", D("7200.00"), D("16984.00"))]
    path = render_statement(HSBC, lines, date(2024, 3, 1), date(2024, 3, 31), tmp_path)
    assert path.name == "2024-03-01_hsbc-statement_2024-03-31.csv"
    rows = path.read_bytes().decode().split("\r\n")
    assert rows[0] == "Date,Type,Description,Amount,Balance"
    assert rows[1] == "15 Mar 2024,CR,BRIGHTWATER HOMES,7200.0,16984.0"
    assert rows[2] == "01 Mar 2024,DD,NORTHCLIFFE TELECOM,-216.0,9784.0"


def test_amex_signs_and_dates(tmp_path):
    amex = MoneyAccount("amex", "Business card", "Calder Express", "amex_csv", "1240", statement_day=3)
    lines = [StatementLine("a1", "amex", date(2024, 3, 5), "", "CORRIB CLOUD LTD", D("-250.00"), D("-250.00")),
             StatementLine("a2", "amex", date(2024, 3, 25), "", "PAYMENT RECEIVED - THANK YOU", D("1384.20"), D("1134.20"))]
    rows = render_statement(amex, lines, date(2024, 3, 4), date(2024, 4, 3), tmp_path).read_text().splitlines()
    assert rows[1].startswith("05/03/2024,CORRIB CLOUD LTD,250.00,")              # a charge prints positive
    assert rows[2].startswith("25/03/2024,PAYMENT RECEIVED - THANK YOU,-1384.20,")  # a payment prints negative


def test_invoice_pdf_prints_its_figures(tmp_path):
    deal = next(d for d in W.deals if "EC-0301" in d.cases)
    doc = next(x for x in deal.docs if x.treatment == "book")
    path = render_doc(doc, deal, W.client, tmp_path)
    text = pdf_text(path)
    assert "£1,082.50" in text and "£216.50" in text and "£1,299.00" in text
    assert PdfReader(path).metadata.subject == "Synthetic test data, not a real document"


def test_every_document_renders_and_prints_its_figures(tmp_path):
    from testbooks.render.documents import money_text
    for deal in W.deals:
        for doc in deal.docs:
            path = render_doc(doc, deal, W.client, tmp_path)
            assert path.exists() and path.stat().st_size > 0
            if path.suffix == ".pdf":
                text = pdf_text(path)
                for key in ("net", "vat", "gross"):
                    if key in doc.printed:
                        assert money_text(doc.printed[key], doc.currency) in text, (doc.id, key)


def test_the_void_invoice_says_so_and_the_answer_brings_the_invoice(tmp_path):
    void = next(x for d in W.deals for x in d.docs if x.kind == "void_invoice")
    deal = next(d for d in W.deals if void in d.docs)
    assert "VOID" in pdf_text(render_doc(void, deal, W.client, tmp_path))
    chairs = next(d for d in W.deals if "EC-0346" in d.cases)
    files = render_answer(chairs.query, chairs, W.client, tmp_path)
    assert [f.suffix for f in files] == [".txt", ".pdf"]
    assert "£53.33" in pdf_text(files[1])
