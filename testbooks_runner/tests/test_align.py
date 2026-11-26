import json

from testbooks_runner.align import (Group, align, groups_of, in_books, load_snapshot, pair_lines, query_for,
                                    subjects)
from testbooks_runner.runs import Progress, save_progress
from testbooks_runner.tests import builders as b

PROFILE = {"accounts": [{"id": "hsbc", "code": "1200", "name": "Current"},
                        {"id": "stripe", "code": "1250", "name": "Card payments"}]}
CODES = {"hsbc": "1200"}
X = "inbox/2023-05-09/2023-04-15_cabot_62874.pdf"
TWO = "inbox/2023-05-09/two-receipts.jpg"
STMT = "inbox/2023-05-09/hsbc-statement.csv"
SSTMT = "inbox/2023-05-09/stripe-export.csv"


def doc(doc_id, file, **kw):
    d = {"doc_id": doc_id, "file": file, "date": "2023-04-15", "gross": ""}
    d.update(kw)
    return d


def entry(journal, doc_ids="", line_ids="", deal="", cp="", phase="books"):
    return {"journal_id": journal, "doc_ids": doc_ids, "line_ids": line_ids, "deal_id": deal,
            "counterparty": cp, "phase": phase}


def line(line_id, amount, date, account="hsbc", deal=""):
    return {"line_id": line_id, "account": account, "date": date, "amount": amount, "deal_id": deal}


def srow(id, gross, date, direction="out", bank_account="1200", **kw):
    return b.row(id, 1, document_type="statement", bank_account=bank_account, gross=gross, date=date,
                 direction=direction, **kw)


def test_rows_tie_to_their_documents():
    key = b.key(documents=[doc("D1", X)])
    snap = b.snapshot(rows=[b.row(1, 7), b.row(2, 8)], uploads=[{"id": 7, "name": "2023-04-15_cabot_62874.pdf"}])
    al = align(key, snap, b.uploads_progress({X: 7}), PROFILE, CODES)
    assert [r["id"] for r in al.rows_by_doc["D1"]] == [1]
    assert [r["id"] for r in al.unpaired] == [2]  # upload 8 is tied to no key document
    assert al.not_read == set()


def test_rows_in_another_year_still_tie():
    key = b.key(documents=[doc("D1", X)])
    snap = b.snapshot(rows=[], uploads=[])
    snap.ledgers["2024-04-01"] = {"transactions": [b.row(5, 7)], "uploads": []}
    al = align(key, snap, b.uploads_progress({X: 7}), PROFILE, CODES)
    assert [r["id"] for r in al.rows_by_doc["D1"]] == [5]


def test_file_holding_two_documents_is_split_by_gross_then_date():
    key = b.key(documents=[doc("D1", TWO, gross="10.00", date="2023-04-01"),
                           doc("D2", TWO, gross="20.00", date="2023-04-09")])
    rows = [b.row(1, 7, gross="20.00", date="2023-04-01"), b.row(2, 7, gross="99.00", date="2023-04-08")]
    al = align(key, b.snapshot(rows=rows), b.uploads_progress({TWO: 7}), PROFILE, CODES)
    assert [r["id"] for r in al.rows_by_doc["D2"]] == [1, 2]
    assert al.rows_by_doc["D1"] == []


def test_statement_lines_pair_exact_then_by_date_then_by_amount():
    key = b.key(documents=[doc("hsbc-statement-1", STMT)],
                lines=[line("L1", "-504.00", "2023-04-03"), line("L2", "-16.20", "2023-04-03"),
                       line("L3", "-50.00", "2023-04-05")])
    rows = [srow(1, "504.00", "2023-04-03"), srow(2, "16.20", "2023-04-05"), srow(3, "55.00", "2023-04-05")]
    al = align(key, b.snapshot(rows=rows), b.uploads_progress({STMT: 1}), PROFILE, CODES)
    assert al.line_how == {"L1": "exact", "L2": "date", "L3": "amount"}
    assert [al.line_rows[k]["id"] for k in ("L1", "L2", "L3")] == [1, 2, 3]
    assert al.unpaired == []


def test_signs_and_accounts_matter():
    lines = [line("L1", "100.00", "2023-04-03")]
    credit = srow(1, "100.00", "2023-04-03", direction="in")
    debit = srow(2, "100.00", "2023-04-03", direction="out")
    other = srow(3, "100.00", "2023-04-03", direction="in", bank_account="1240")
    receipt = b.row(4, 1, gross="100.00", direction="in", date="2023-04-03", bank_account="1200")
    got, how, left = pair_lines(lines, [debit, other, receipt, credit], CODES)
    assert got["L1"]["id"] == 1 and how == {"L1": "exact"}
    assert [r["id"] for r in left] == [2]  # the wrong-account and non-statement rows take no part


def test_date_pass_takes_nearest_first_and_stops_at_three_days():
    lines = [line("L1", "-10.00", "2023-04-10"), line("L2", "-10.00", "2023-04-11")]
    rows = [srow(1, "10.00", "2023-04-12"), srow(2, "10.00", "2023-04-20")]
    got, how, left = pair_lines(lines, rows, CODES)
    assert got["L2"]["id"] == 1 and how == {"L2": "date"}  # L2 is the nearer line to row 1
    assert [r["id"] for r in left] == [2]


def test_unpaired_rows_are_listed():
    key = b.key(documents=[doc("hsbc-statement-1", STMT)], lines=[line("L1", "-10.00", "2023-04-03")])
    rows = [srow(1, "10.00", "2023-04-03"), srow(2, "77.00", "2023-06-30")]
    al = align(key, b.snapshot(rows=rows), b.uploads_progress({STMT: 1}), PROFILE, CODES)
    assert [r["id"] for r in al.unpaired] == [2]


def test_groups_join_journals_sharing_a_document_or_line():
    gs = groups_of([entry("J1", doc_ids="D8", deal="MN-1"), entry("J1", doc_ids="D8", deal="MN-1"),
                    entry("J2", doc_ids="D8", line_ids="L5", phase="answers"),
                    entry("J3", line_ids="L5"), entry("J4", doc_ids="D9")])
    assert len(gs) == 2
    first = gs[0]
    assert first.journals == ("J1", "J2", "J3")
    assert first.docs == {"D8"} and first.lines == {"L5"} and first.deals == {"MN-1"}
    assert first.phases == {"books", "answers"} and not first.paperless


def test_paperless_journal_is_its_own_group():
    gs = groups_of([entry("VAT-2023-05-31"), entry("J4", doc_ids="D9")])
    assert gs[0] == Group(("VAT-2023-05-31",), frozenset(), frozenset(), frozenset(), frozenset({"books"}), True)
    assert not gs[1].paperless


def test_plural_doc_and_line_lists_split_on_semicolons():
    gs = groups_of([entry("PAY1", doc_ids="D1;D2", line_ids="L1;L2"), entry("J2", doc_ids="D2")])
    assert len(gs) == 1 and gs[0].docs == {"D1", "D2"} and gs[0].lines == {"L1", "L2"}


def jentry(journal, deal, cp, date, debit="0.00", credit="0.00", doc_ids="", line_ids=""):
    e = entry(journal, doc_ids=doc_ids, line_ids=line_ids, deal=deal, cp=cp)
    e.update(date=date, debit=debit, credit=credit)
    return e


def test_query_matched_by_deal_and_by_counterparty():
    key = b.key(documents=[doc("D9", X)],
                entries=[jentry("J9", "MN-0009", "Streamflix", "2023-04-01", debit="9.99", doc_ids="D9")],
                queries=[{"query_id": "MN-Q0001", "about": "MN-0009"},
                         {"query_id": "MN-Q0002", "about": "MN-0010;MN-D0003"}])
    earlier = b.row(1, 7, counterparty="Streamflix", date="2023-04-01")
    later = b.row(2, 8, counterparty="STREAMFLIX", date="2023-08-01", gross="9.99")  # an upload tied to nothing
    snap = b.snapshot(rows=[earlier, later])
    al = align(key, snap, b.uploads_progress({X: 7}), PROFILE, CODES)
    assert {"D9", "MN-0009", "cp:streamflix"} <= subjects([1], al, key)
    assert query_for({"row_ids": [1]}, key, al) == "MN-Q0001"  # same document, so by deal
    assert query_for({"row_ids": [2]}, key, al) == "MN-Q0001"  # a later month: by counterparty and amount
    assert query_for({"row_ids": [99]}, key, al) is None
    assert query_for({"row_ids": []}, key, al) is None


def test_counterparty_reached_through_a_paired_line_uses_the_keys_spelling():
    profile = {"accounts": [{"id": "amex", "code": "1240", "name": "Card"}]}
    key = b.key(documents=[doc("amex-statement-1", STMT)],
                lines=[line("amex-2", "-9.99", "2023-05-03", account="amex", deal="AG-0085")],
                entries=[jentry("J1", "AG-0085", "Streamflix", "2023-05-03", credit="9.99",
                                line_ids="amex-2")],
                queries=[{"query_id": "AG-Q0023", "about": "AG-0085"}])
    paired = srow(1, "9.99", "2023-05-03", bank_account="1240", counterparty="STREAMFLIX.COM")
    al = align(key, b.snapshot(rows=[paired]), b.uploads_progress({STMT: 1}), profile, {"amex": "1240"})
    assert "cp:streamflix" in subjects([1], al, key)
    assert "cp:streamflix.com" not in subjects([1], al, key)
    assert query_for({"row_ids": [1]}, key, al) == "AG-Q0023"


def hmrc_key():
    return b.key(
        documents=[doc("D200", X)],
        entries=[jentry("J200", "AG-0200", "HMRC", "2023-05-01", debit="100.00", doc_ids="D200"),
                 jentry("J31", "AG-0031", "HMRC", "2023-04-13", debit="50.00")],
        queries=[{"query_id": "AG-Q0031", "about": "AG-0031"}])


def test_counterparty_alone_does_not_match_a_query():
    key = hmrc_key()
    paye = b.row(1, 7, counterparty="HMRC", date="2023-06-01", gross="300.00")
    al = align(key, b.snapshot(rows=[paye]), b.uploads_progress({X: 7}), PROFILE, CODES)
    assert "cp:hmrc" in subjects([1], al, key)
    assert query_for({"row_ids": [1]}, key, al) is None


def test_counterparty_match_accepted_on_a_shared_date_or_amount():
    key = hmrc_key()
    same_day = b.row(1, 7, counterparty="HMRC", date="2023-04-13", gross="300.00")
    same_sum = b.row(2, 7, counterparty="HMRC", date="2023-06-01", gross="50.00")
    al = align(key, b.snapshot(rows=[same_day, same_sum]), b.uploads_progress({X: 7}), PROFILE, CODES)
    assert query_for({"row_ids": [1]}, key, al) == "AG-Q0031"
    assert query_for({"row_ids": [2]}, key, al) == "AG-Q0031"


def test_rows_out_of_the_books_are_neither_paired_nor_unpaired():
    key = b.key(documents=[doc("hsbc-statement-1", STMT), doc("D1", X)],
                lines=[line("L1", "-10.00", "2023-04-03")])
    gone = [srow(1, "10.00", "2023-04-03", removed=True), srow(2, "10.00", "2023-04-03", excluded=True),
            srow(3, "10.00", "2023-04-03", in_opening=True, include=False),
            srow(4, "10.00", "2023-04-03", superseded_by="d9"), b.row(5, 99, removed=True)]
    live = srow(6, "10.00", "2023-04-03")
    snap = b.snapshot(rows=gone + [live])
    al = align(key, snap, b.uploads_progress({STMT: 1, X: 99}), PROFILE, CODES)
    assert al.line_rows["L1"]["id"] == 6
    assert al.unpaired == []
    assert [r["id"] for r in al.rows_by_doc["D1"]] == [5]  # kept, so a check can read its decisions
    assert set(al.rows_by_id) == {1, 2, 3, 4, 5, 6}


def test_include_alone_does_not_take_a_row_out_of_the_books():
    # the app sends include: false on every row nobody ticked; the tick only brings in a row left out otherwise
    assert in_books(b.api_row(1, 1))
    assert in_books(b.api_row(1, 1, in_opening=True, include=True))
    assert not in_books(b.api_row(1, 1, in_opening=True))
    for gone in ({"removed": True}, {"excluded": True}, {"superseded_by": "d9"}):
        assert not in_books(b.api_row(1, 1, include=True, **gone))


def test_rows_in_the_apis_shape_pair_and_tie():
    key = b.key(documents=[doc("hsbc-statement-1", STMT), doc("D1", X)],
                lines=[line("L1", "-10.00", "2023-04-03"), line("L2", "25.00", "2023-04-04")])
    rows = [b.api_row(1, 1, document_type="statement", bank_account="1200", gross="10.00", date="2023-04-03"),
            b.api_row(2, 1, document_type="statement", bank_account="1200", gross="25.00", date="2023-04-04",
                      direction="in", recorded_by={"ref": "row-9", "amount": "25.00"}),
            b.api_row(3, 7, gross="10.00", date="2023-04-03")]
    al = align(key, b.snapshot(rows=rows), b.uploads_progress({STMT: 1, X: 7}), PROFILE, CODES)
    assert {k: r["id"] for k, r in al.line_rows.items()} == {"L1": 1, "L2": 2}
    assert al.line_how == {"L1": "exact", "L2": "exact"}
    assert [r["id"] for r in al.rows_by_doc["D1"]] == [3] and al.unpaired == []


LATER = "inbox/2024-04-19/hsbc-later-statement.csv"
COPY = {"ref": "row-2", "amount": "10.00", "kind": "statement"}


def test_a_line_two_overlapping_statements_print_pairs_with_the_row_the_app_booked():
    key = b.key(documents=[doc("hsbc-statement-1", STMT), doc("hsbc-statement-2", LATER)],
                lines=[line("L1", "-10.00", "2023-04-03")])

    def stmt(id, upload, date="2023-04-03", **kw):
        return b.api_row(id, upload, document_type="statement", bank_account="1200", gross="10.00", date=date,
                         balance="90.00", **kw)

    # the later statement's copy comes first in the ledger, but the app books the line from the earlier one
    rows = [stmt(1, 2, copy_of=COPY), stmt(2, 1), stmt(3, 2, copy_of=COPY, include=True, date="2023-04-09")]
    al = align(key, b.snapshot(rows=rows), b.uploads_progress({STMT: 1, LATER: 2}), PROFILE, CODES)
    assert al.line_rows["L1"]["id"] == 2 and al.line_how == {"L1": "exact"}
    assert [r["id"] for r in al.unpaired] == [3]  # a copy someone ticked Include is booked, so it can be extra
    assert [r["id"] for r in al.rows_by_doc["hsbc-statement-2"]] == [1, 3]


def test_a_processor_line_pairs_with_its_files_row_not_a_copy():
    key = b.key(documents=[doc("stripe-export-1", SSTMT)], lines=[line("S1", "50.00", "2023-04-03", account="stripe")])
    rows = [b.api_row(i, 3, document_type="agent_statement", direction="in", gross="50.00", date="2023-04-03",
                      copy_of=COPY if i == 1 else None) for i in (1, 2)]
    al = align(key, b.snapshot(rows=rows), b.uploads_progress({SSTMT: 3}), PROFILE, CODES)
    assert al.line_rows["S1"]["id"] == 2 and al.unpaired == []


def test_chat_attached_upload_ties_to_its_answer_document_by_name():
    answer = "answers/2024-03-12/2024-02-08_wharf_woi-1.pdf"
    key = b.key(documents=[doc("MN-D0003", answer)])
    snap = b.snapshot(rows=[b.row(1, 12)], uploads=[{"id": 12, "name": "2024-02-08_wharf_woi-1.pdf"}])
    al = align(key, snap, {}, PROFILE, CODES)  # the runner sent nothing for it
    assert [r["id"] for r in al.rows_by_doc["MN-D0003"]] == [1]
    assert al.unpaired == [] and al.not_read == set()


def test_unknown_file_is_listed_not_fatal():
    key = b.key(documents=[doc("D1", X)])
    ups = b.uploads_progress({X: 7, "inbox/old/gone.pdf": 9})
    al = align(key, b.snapshot(rows=[b.row(1, 7), b.row(2, 9)]), ups, PROFILE, CODES)
    assert al.unknown_files == ["inbox/old/gone.pdf"]
    assert [r["id"] for r in al.unpaired] == [2]


def test_same_file_and_missing_upload_id_tie_by_name_in_any_year():
    key = b.key(documents=[doc("D1", X), doc("D2", TWO)])
    snap = b.snapshot(rows=[], uploads=[])
    snap.ledgers["2024-04-01"] = {"transactions": [b.row(5, 7), b.row(6, 8)],
                                  "uploads": [{"id": 7, "name": "2023-04-15_cabot_62874.pdf"},
                                              {"id": 8, "name": "two-receipts.jpg"}]}
    ups = {X: {"status": "same file", "upload_id": None}, TWO: {"status": "saved", "upload_id": None}}
    al = align(key, snap, ups, PROFILE, CODES)
    assert [r["id"] for r in al.rows_by_doc["D1"]] == [5]
    assert [r["id"] for r in al.rows_by_doc["D2"]] == [6]
    assert al.not_read == set()


def test_not_read_covers_refused_failed_and_absent_but_not_no_rows():
    files = {f"f{i}.pdf": doc(f"D{i}", f"f{i}.pdf") for i in range(5)}
    key = b.key(documents=list(files.values()))
    ups = {"f0.pdf": {"status": "refused"}, "f1.pdf": {"status": "failed"},
           "f2.pdf": {"status": "no rows", "upload_id": None}, "f3.pdf": {"status": "same file"}}
    al = align(key, b.snapshot(), ups, PROFILE, CODES)
    assert al.not_read == {"D0", "D1", "D4"}


def test_processor_lines_pair_with_rows_from_their_own_file():
    key = b.key(documents=[doc("stripe-export-1", SSTMT), doc("hsbc-statement-1", STMT)],
                lines=[line("S1", "50.00", "2023-04-03", account="stripe"),
                       line("S2", "30.00", "2023-04-04", account="stripe")])
    stripe_rows = [b.row(1, 3, document_type="agent_statement", direction="in", gross="50.00",
                         date="2023-04-03", bank_account=None),
                   b.row(2, 3, document_type="agent_statement", direction="in", gross="31.00",
                         date="2023-04-04", bank_account=None),
                   b.row(3, 3, document_type="agent_statement", direction="in", gross="9.00",
                         date="2023-05-04", bank_account=None)]
    elsewhere = b.row(4, 1, document_type="statement", direction="in", gross="30.00",
                      date="2023-04-04", bank_account="1200")
    ups = b.uploads_progress({SSTMT: 3, STMT: 1})
    al = align(key, b.snapshot(rows=stripe_rows + [elsewhere]), ups, PROFILE, CODES)
    assert al.line_how == {"S1": "exact", "S2": "amount"}
    assert al.line_rows["S2"]["id"] == 2
    assert [r["id"] for r in al.unpaired] == [3, 4]  # the extra processor row, and a bank row with no line


def test_posted_lines_group_by_row():
    snap = b.snapshot(rows=[b.row(1, 7)], posted_lines=[b.posted(1, "7500", debit="10"),
                                                        b.posted(1, "1200", credit="10"),
                                                        b.posted(2, "1200", credit="5")])
    al = align(b.key(), snap, {}, PROFILE, CODES)
    assert [j["code"] for j in al.posted_by_row[1]] == ["7500", "1200"]
    assert list(al.posted_by_row) == [1, 2]


def test_load_snapshot_reads_what_take_snapshot_writes(tmp_path):
    save_progress(tmp_path, Progress(client_id=1, app_year_start="2023-04-01"))
    raw = tmp_path / "raw" / "before"
    raw.mkdir(parents=True)

    def w(name, data):
        (raw / name).write_text(json.dumps(data), encoding="utf-8")

    w("ledger-2023-04-01.json", {"transactions": [{"id": 1}], "uploads": []})
    w("ledger-2024-04-01.json", {"transactions": [{"id": 2}], "uploads": []})
    w("posted-2023-04-01.json", {"journal": [], "lines": []})
    w("vat-2023-06-01-2023-08-31.json", {"box1": "1.00"})
    w("invoices.json", [{"ref": "a"}])
    w("questions.json", [{"id": "q"}])
    w("decisions.json", [])
    w("reviews.json", [{"id": 3}])
    w("accounts.json", [{"code": "1200"}])
    w("chat.json", {"messages": []})
    w("summary.error.json", {"status": 500, "code": "boom", "message": "x"})
    w("tb-shown.json", {})
    (raw / "export.xlsx").write_bytes(b"PK")
    snap = load_snapshot(tmp_path, "before")
    assert snap.which == "before" and snap.scored_year == "2023-04-01"
    assert set(snap.ledgers) == {"2023-04-01", "2024-04-01"} and set(snap.posted) == {"2023-04-01"}
    assert snap.vat == {("2023-06-01", "2023-08-31"): {"box1": "1.00"}}
    assert snap.invoices == [{"ref": "a"}] and snap.questions == [{"id": "q"}]
    assert snap.reviews == [{"id": 3}] and snap.accounts == [{"code": "1200"}] and snap.decisions == []
    assert snap.chat == {"messages": []}
    assert snap.errors == {"summary": {"status": 500, "code": "boom", "message": "x"}}


def test_load_snapshot_of_a_missing_folder_is_empty(tmp_path):
    save_progress(tmp_path, Progress(app_year_start="2023-04-01"))
    snap = load_snapshot(tmp_path, "after")
    assert snap.ledgers == {} and snap.chat is None and snap.scored_year == "2023-04-01"

