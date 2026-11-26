"""Builds a small client in the built set's file formats, for tests."""
from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

FIXTURE_PACK = Path(__file__).parent / "fixtures" / "set" / "packs" / "EC-0346-receipt-over-250"


def _csv(path: Path, header: str, rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(header.split(","))
        w.writerows(rows)


def _file(path: Path, data: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data.encode() if isinstance(data, str) else data)


def write_mini_client(set_dir: Path) -> Path:
    c = Path(set_dir) / "clients" / "mini"
    profile = {
        "accounts": [
            {"bank": "Severn Bank", "code": "1200", "id": "hsbc", "layout": "hsbc_csv",
             "name": "Business current", "statement_day": 0},
            {"bank": "Calder Express", "code": "1240", "id": "amex", "layout": "amex_csv",
             "name": "Business card", "statement_day": 3},
            {"bank": "Stripe", "code": "1250", "id": "stripe", "layout": "stripe_csv",
             "name": "Card payments", "statement_day": 0},
        ],
        "address": "1 Mini Street, Bristol BS1 1AA",
        "company_number": "01234567",
        "employees": [],
        "kind": "ltd",
        "name": "Mini Widgets Ltd",
        "note": "Synthetic test data, not a real business",
        "owners": [{"loan_account": "2250", "name": "Ann Mini", "share": "1"}],
        "periods": [
            {"end": "2024-03-31", "partial": False, "start": "2023-04-01"},
            {"end": "2025-03-31", "partial": False, "start": "2024-04-01"},
        ],
        "vat_number": "123456782",
        "vat_quarters_end": [2, 5, 8, 11],
    }
    c.mkdir(parents=True, exist_ok=True)
    (c / "profile.json").write_text(json.dumps(profile, indent=2, sort_keys=True), encoding="utf-8")
    shutil.copy(FIXTURE_PACK / "chart.csv", c / "chart.csv")

    stmt = "inbox/2023-05-09/2023-04-01_hsbc-statement_2023-04-30.csv"
    cabot = "inbox/2023-05-09/2023-04-15_cabot_62874.pdf"
    prior = "inbox/2023-04-12/2023-03-31_prior_tb.xlsx"
    next_year = "inbox/2024-05-08/2024-04-01_cabot_99999.pdf"
    reply1 = "answers/2023-05-16/2023-05-16_reply_mn-q0001.txt"
    reply2 = "answers/2024-03-12/2024-03-12_reply_mn-q0002.txt"
    wharf = "answers/2024-03-12/2024-02-08_wharf_woi-1.pdf"
    _file(c / stmt, "date,description,amount\n")
    _file(c / cabot, b"%PDF-1.4 mini cabot invoice")
    _file(c / prior, b"PK mini prior trial balance")
    _file(c / next_year, b"%PDF-1.4 next year invoice")
    _file(c / reply1, "Re: Is the Streamflix charge personal?\n\nYes, mine.")
    _file(c / reply2, "Re: Please send the full VAT invoice\n\nAttached.")
    _file(c / wharf, b"%PDF-1.4 mini answer invoice")

    k = c / "key" / "2024-03-31"
    _csv(k / "documents.csv",
         "doc_id,file,arrived,kind,issuer,recipient,number,date,currency,net,vat,gross,treatment,reason,cases",
         [["hsbc-statement-20230401-20230430", stmt, "2023-05-09", "bank_statement", "Severn Bank",
           "Mini Widgets Ltd", "01 Apr 2023 to 30 Apr 2023", "2023-04-01", "GBP", "", "", "",
           "evidence", "Business current statement export", ""],
          ["MN-D0001", prior, "2023-04-12", "prior_tb", "Previous accountant", "Mini Widgets Ltd",
           "", "2023-03-31", "GBP", "", "", "", "evidence", "The previous accountant's trial balance", ""],
          ["MN-D0002", cabot, "2023-05-09", "purchase_invoice", "Cabot Office Supplies",
           "Mini Widgets Ltd", "62874", "2023-04-15", "GBP", "100.00", "20.00", "120.00", "book", "", ""],
          ["MN-D0003", wharf, "2024-03-12", "purchase_invoice", "Wharfside Office Interiors",
           "Mini Widgets Ltd", "WOI-1", "2024-02-08", "GBP", "100.00", "20.00", "120.00", "book", "", ""]])
    _csv(k / "opening-balances.csv", "account,name,debit,credit,source",
         [["1100", "Debtors control", "1000.00", "", "The previous accountant's trial balance"],
          ["1200", "Bank current account", "500.00", "", "The previous accountant's trial balance"],
          ["2100", "Creditors control", "", "300.00", "The previous accountant's trial balance"],
          ["3260", "Dividends", "0.00", "0.00", "The previous accountant's trial balance"],
          ["3200", "Profit and loss account", "", "1200.00", "The previous accountant's trial balance"]])
    _csv(k / "debtors.csv", "as_at,counterparty,doc_id,number,date,gross,paid,owed",
         [["2023-04-30", "Calder", "OPENING-INV-1", "INV-1", "2023-03-20", "400.00", "0.00", "400.00"]])
    _csv(k / "creditors.csv", "as_at,counterparty,doc_id,number,date,gross,paid,owed",
         [["2023-04-30", "Cabot Office Supplies", "MN-D0002", "62874", "2023-04-15", "120.00", "0.00",
           "120.00"]])
    entry_head = ("entry_id,journal_id,date,account,account_name,debit,credit,vat_code,vat,counterparty,"
                  "deal_id,doc_ids,line_ids,stakes,also_ok,phase,cases")
    _csv(k / "entries.csv", entry_head,
         [["E00001", "MN-0001", "2023-04-12", "1200", "Bank current account", "600.00", "0.00", "",
           "0.00", "Brightwater", "MN-0001", "", "hsbc-2023-04-0001", "", "", "books", ""],
          ["E00002", "MN-0001", "2023-04-12", "1100", "Debtors control", "0.00", "600.00", "",
           "0.00", "Brightwater", "MN-0001", "", "hsbc-2023-04-0001", "", "", "books", ""],
          ["E00003", "MN-0002", "2023-04-20", "2100", "Creditors control", "300.00", "0.00", "",
           "0.00", "Cabot", "MN-0002", "", "hsbc-2023-04-0002", "", "", "books", ""],
          ["E00004", "MN-0002", "2023-04-20", "1200", "Bank current account", "0.00", "300.00", "",
           "0.00", "Cabot", "MN-0002", "", "hsbc-2023-04-0002", "", "", "books", ""]])
    _csv(k / "queries.csv", "query_id,about,question,why,stakes,answer_file,answer_date,effect",
         [["MN-Q0001", "MN-0009", "Is the Streamflix charge personal?", "Personal spending is the owner's.",
           "tax", reply1, "2023-05-16", "The figures don't change"],
          ["MN-Q0002", "MN-0010;MN-D0003", "Please send the full VAT invoice.", "A receipt is not an invoice.",
           "tax", reply2, "2024-03-12", "VAT is reclaimed from the answer's date"]])
    _csv(k / "statement-lines.csv", "line_id,account,date,type,description,amount,balance,deal_id,cases",
         [["hsbc-2023-04-0001", "hsbc", "2023-04-12", "CR", "BRIGHTWATER", "600.00", "1100.00", "MN-0001", ""],
          ["hsbc-2023-04-0002", "hsbc", "2023-04-20", "DD", "CABOT OFFICE SUPPLIES", "-300.00", "800.00",
           "MN-0002", ""]])
    _csv(k / "vat-returns.csv",
         "period_start,period_end,box1,box2,box3,box4,box5,box6,box7,box8,box9,due,dd",
         [["2023-03-01", "2023-05-31", "0.00", "0.00", "0.00", "0.00", "0.00", "0", "0", "0", "0",
           "2023-07-07", "2023-07-12"],
          ["2023-06-01", "2023-08-31", "0.00", "0.00", "0.00", "0.00", "0.00", "0", "0", "0", "0",
           "2023-10-07", "2023-10-12"]])
    _csv(k / "trial-balance.csv", "account,name,heading,opening,books,before_answers,year_end,final",
         [["1200", "Bank current account", "Current assets", "500.00", "300.00", "800.00", "0.00", "800.00"],
          ["1100", "Debtors control", "Current assets", "1000.00", "-600.00", "400.00", "0.00", "400.00"],
          ["2100", "Creditors control", "Creditors", "-300.00", "300.00", "0.00", "0.00", "0.00"]])
    return c
