from datetime import date
from decimal import Decimal

from testbooks_runner.align import align
from testbooks_runner.checks import (STAKES_ORDER, booked, check_documents, check_extra_rows, check_lines,
                                     identity)
from testbooks_runner.model import Period, Unit
from testbooks_runner.runs import Progress
from testbooks_runner.tests import builders as b

PROFILE = {"accounts": [{"id": "hsbc", "code": "1200", "name": "Current"}]}
CODES = {"hsbc": "1200"}
F1 = "inbox/2023-05-09/2023-04-15_cabot_62874.pdf"
F2 = "inbox/2023-05-09/prior_tb.xlsx"
F3 = "inbox/2023-05-09/hsbc-statement.csv"
ANS = "answers/2024-03-12/2024-02-08_wharf_woi-1.pdf"
CATALOGUE = ("id,category,title,where,expects,stakes,needs_years,layout_unconfirmed,step\n"
             "EC-1,01,A,AG,x,Process,N,N,\nEC-2,01,B,AG,x,Tax,N,N,\nEC-3,01,C,AG,x,Presentation,N,N,\n")


def unit(tmp_path):
    folder = tmp_path / "set" / "clients" / "mini"
    folder.mkdir(parents=True, exist_ok=True)
    (tmp_path / "set" / "catalogue.csv").write_text(CATALOGUE, encoding="utf-8")
    return Unit("mini", "client", folder, Period(date(2023, 4, 1), date(2024, 3, 31)))


def doc(doc_id, file, treatment="book", gross="120.00", **kw):
    d = {"doc_id": doc_id, "file": file, "kind": "purchase_invoice", "issuer": "Cabot", "number": "62874",
         "date": "2023-04-15", "gross": gross, "treatment": treatment, "cases": ""}
    d.update(kw)
    return d


def line(line_id, amount="-300.00", date_="2023-04-20", **kw):
    ln = {"line_id": line_id, "account": "hsbc", "date": date_, "amount": amount,
          "description": "CABOT", "cases": ""}
    ln.update(kw)
    return ln


def run(tmp_path, documents=(), lines=(), rows=(), posted_lines=(), files=None, decisions=(), queries=(),
        replies=None, phase="before", names=None):
    u = unit(tmp_path)
    key = b.key(documents=list(documents), lines=list(lines), queries=list(queries))
    uploads = {f: i for i, f in enumerate(files or [d["file"] for d in documents], start=7)}
    prog_uploads = b.uploads_progress(uploads)
    snap = b.snapshot(rows=rows, posted_lines=posted_lines, decisions=decisions,
                      uploads=[{"id": i, "name": f.split("/")[-1]} for f, i in uploads.items()])
    al = align(key, snap, prog_uploads, PROFILE, CODES)
    progress = Progress(replies=replies or {})
    return u, key, snap, al, progress


def docs_out(tmp_path, phase="before", **kw):
    u, key, snap, al, progress = run(tmp_path, **kw)
    return check_documents(u, key, snap, al, PROFILE, phase, progress), (u, key, snap, al)


def test_document_to_book_that_was_booked_passes(tmp_path):
    out, _ = docs_out(tmp_path, documents=[doc("MN-D1", F1)],
                      rows=[b.row(1, 7, gross="120.00")], posted_lines=[b.posted(1, "5000", debit="120.00")])
    assert [(o.status, o.cause, o.check) for o in out] == [("pass", "", "document")]
    assert out[0].ref == "mini:2024-03-31:document:MN-D1"
    assert out[0].where == F1 and out[0].phase == "before"


def test_evidence_that_was_booked_fails_as_booked_wrong(tmp_path):
    out, _ = docs_out(tmp_path, documents=[doc("MN-D2", F2, treatment="evidence", gross="")],
                      rows=[b.row(1, 7, gross="500.00")], posted_lines=[b.posted(1, "3200", credit="500.00")])
    assert (out[0].status, out[0].cause, out[0].stakes) == ("fail", "booked wrong", "accounts")
    assert out[0].got == "booked, gross 500.00" and out[0].expected == "not booked"


def test_evidence_or_not_booked_document_left_out_passes(tmp_path):
    out, _ = docs_out(tmp_path, documents=[doc("A", F1, treatment="not_booked"), doc("B", F2, treatment="evidence")])
    assert [o.status for o in out] == ["pass", "pass"]


def test_document_misread_when_gross_differs(tmp_path):
    out, _ = docs_out(tmp_path, documents=[doc("MN-D1", F1)],
                      rows=[b.row(1, 7, gross="102.00")], posted_lines=[b.posted(1, "5000", debit="102.00")])
    o = out[0]
    assert (o.status, o.cause, o.amount) == ("fail", "misread", Decimal("18.00"))
    assert o.expected == "booked, gross 120.00" and o.got == "booked, gross 102.00"


def test_document_with_no_rows_is_misread(tmp_path):
    out, _ = docs_out(tmp_path, documents=[doc("MN-D1", F1)])
    assert (out[0].status, out[0].cause, out[0].got) == ("fail", "misread", "not booked")


def test_unread_file_is_not_read(tmp_path):
    u, key, snap, al, progress = run(tmp_path, documents=[doc("MN-D1", F1)])
    al.not_read.add("MN-D1")
    o = check_documents(u, key, snap, al, PROFILE, "before", progress)[0]
    assert (o.status, o.cause) == ("not_read", "not read")


def answer_setup(tmp_path, replies, phase="after"):
    queries = [{"query_id": "MN-Q2", "answer_file": "answers/2024-03-12/2024-03-12_reply_mn-q2.txt"}]
    return docs_out(tmp_path, phase=phase, documents=[doc("MN-D0003", ANS)], queries=queries, replies=replies,
                    rows=[b.row(1, 7, gross="120.00")], posted_lines=[b.posted(1, "5000", debit="120.00")])


def test_answer_document_never_sent_says_never_asked(tmp_path):
    for replies in ({}, {"MN-Q2": {"sent": False}}):
        out, _ = answer_setup(tmp_path, replies)
        assert (out[0].status, out[0].cause) == ("not_read", "the app never asked")


def test_an_answer_document_never_sent_is_never_asked_though_no_upload_has_it(tmp_path):
    # The agency run: the Wharfside full VAT invoice, a reply's attachment the app never asked for, was in no upload,
    # so it counted among the files the app didn't read.
    u, key, snap, al, progress = run(tmp_path, documents=[doc("MN-D0003", ANS)],
                                     queries=[{"query_id": "MN-Q2",
                                               "answer_file": "answers/2024-03-12/2024-03-12_reply_mn-q2.txt"}])
    al.not_read.add("MN-D0003")
    [o] = check_documents(u, key, snap, al, PROFILE, "after", progress)
    assert (o.status, o.cause) == ("not_read", "the app never asked")


def test_answer_document_sent_is_judged_and_skipped_before(tmp_path):
    out, _ = answer_setup(tmp_path, {"MN-Q2": {"sent": True}})
    assert [o.status for o in out] == ["pass"]
    out, _ = answer_setup(tmp_path, {"MN-Q2": {"sent": True}}, phase="before")
    assert out == []


def test_statements_are_judged_by_their_lines_not_as_documents(tmp_path):
    out, _ = docs_out(tmp_path, documents=[doc("hsbc-statement-20230401-20230430", F3, treatment="evidence"),
                                           doc("MN-D1", F1, treatment="evidence")],
                      rows=[b.row(1, 7, document_type="statement", bank_account="1200")])
    assert [o.ref for o in out] == ["mini:2024-03-31:document:MN-D1"]


def test_removed_row_with_a_review_decision_leaves_nothing_live(tmp_path):
    decisions = [{"id": 9, "status": "applied", "review_id": 3, "actor": "agent:review", "trigger": "review"}]
    out, _ = docs_out(tmp_path, documents=[doc("MN-D1", F1)], decisions=decisions,
                      rows=[b.row(1, 7, gross="120.00", removed=True, decision_ids=[9])])
    # a removed row is out of the books, so nothing is live and "misread" comes first
    assert (out[0].status, out[0].cause) == ("fail", "misread")


def test_changed_by_review_or_chat_when_row_is_live_but_unbooked(tmp_path):
    review = {"id": 9, "status": "applied", "review_id": 3, "actor": "agent:review", "trigger": "review"}
    chat = {"id": 8, "status": "applied", "review_id": None, "actor": "agent:chat", "trigger": "chat"}
    rules = {"id": 7, "status": "applied", "review_id": None, "actor": "rules", "trigger": "upload"}
    pending = {"id": 6, "status": "pending", "review_id": 3, "actor": "agent:review", "trigger": "review"}
    for decs, ids, cause in (([review], [9], "changed by the review"), ([chat], [8], "changed by the chat"),
                             ([rules], [7], "booked wrong"), ([pending], [6], "booked wrong")):
        out, _ = docs_out(tmp_path, documents=[doc("MN-D1", F1)], decisions=decs,
                          rows=[b.row(1, 7, gross="120.00", decision_ids=ids)])
        assert out[0].cause == cause


def test_changed_by_the_review_on_an_unwanted_booking(tmp_path):
    review = {"id": 9, "status": "applied", "review_id": 3, "actor": "agent:review", "trigger": "review"}
    out, _ = docs_out(tmp_path, documents=[doc("E", F2, treatment="evidence", gross="")], decisions=[review],
                      rows=[b.row(1, 7, gross="5.00", decision_ids=[9], removed=True),
                            b.row(2, 7, gross="5.00")],
                      posted_lines=[b.posted(2, "3200", credit="5.00")])
    assert (out[0].status, out[0].cause) == ("fail", "changed by the review")


def test_stakes_come_from_the_highest_capitalised_catalogue_case(tmp_path):
    cases = [("EC-1", "process"), ("EC-1;EC-3", "presentation"), ("EC-1;EC-2;EC-3", "tax"), ("", "accounts"),
             ("EC-9", "accounts")]
    assert STAKES_ORDER[0] == "tax"
    for cs, stakes in cases:
        out, _ = docs_out(tmp_path, documents=[doc("MN-D1", F1, cases=cs)])
        assert out[0].stakes == stakes and out[0].cases == tuple(c for c in cs.split(";") if c)


def lines_out(tmp_path, lines, rows, not_read=()):
    u, key, snap, al, _ = run(tmp_path, documents=[doc("hsbc-statement-20230401-20230430", F3, treatment="evidence")],
                              lines=lines, rows=rows)
    al.not_read.update(not_read)
    return check_lines(u, key, al)


def srow(id, gross, day, direction="out"):
    return b.row(id, 7, document_type="statement", bank_account="1200", gross=gross, date=day, direction=direction)


def test_lines_pass_or_misread_or_missed(tmp_path):
    lines = [line("hsbc-2023-04-0001", "-300.00", "2023-04-20"), line("hsbc-2023-04-0002", "-50.00", "2023-04-21"),
             line("hsbc-2023-04-0003", "-10.00", "2023-04-22")]
    rows = [srow(1, "300.00", "2023-04-20"), srow(2, "50.00", "2023-04-23")]
    out = lines_out(tmp_path, lines, rows)
    assert [(o.status, o.cause) for o in out] == [("pass", ""), ("fail", "misread"), ("fail", "misread")]
    assert out[0].where == f"{F3} hsbc-2023-04-0001" and out[0].check == "line"
    assert out[1].got == "2023-04-23 -50.00" and out[1].ref == "mini:2024-03-31:line:hsbc-2023-04-0002"


def test_line_of_an_unread_statement_is_not_read(tmp_path):
    out = lines_out(tmp_path, [line("hsbc-2023-04-0001")], [], not_read={"hsbc-statement-20230401-20230430"})
    assert (out[0].status, out[0].cause) == ("not_read", "not read")


def test_extra_row_is_made_up_or_read_twice(tmp_path):
    u, key, snap, al, _ = run(tmp_path, documents=[doc("MN-D1", F1)],
                              rows=[b.row(1, 7, gross="120.00"), b.row(5, 99, gross="9.99", date="2023-05-01")])
    out = check_extra_rows(u, al, "after")
    assert [(o.check, o.status, o.cause, o.stakes, o.phase, o.cases) for o in out] == \
        [("extra", "fail", "made up or read twice", "accounts", "after", ())]
    assert out[0].ref == "mini:2024-03-31:extra:5" and out[0].amount == Decimal("9.99")


def test_only_rows_dated_in_the_period_can_be_made_up(tmp_path):
    rows = [b.row(1, 7, gross="120.00"),
            b.row(5, 99, gross="9.99", date="2024-04-02"),  # next year's, on a statement that runs past the end
            b.row(6, 99, gross="8.88", date="2023-03-30"),  # the year before
            b.row(7, 99, gross="7.77", date="2024-03-31"),  # the last day is in the period
            b.row(8, 99, gross="6.66")]  # undated: nothing places it in another year
    u, key, snap, al, _ = run(tmp_path, documents=[doc("MN-D1", F1)], rows=rows)
    assert [o.data["row_id"] for o in check_extra_rows(u, al)] == [7, 8]


def test_identity_ignores_the_key_numbering(tmp_path):
    u = unit(tmp_path)
    outs = []
    for doc_id in ("MN-D0001", "MN-D0042"):
        o, _ = docs_out(tmp_path, documents=[doc(doc_id, F1)])
        outs.append(o[0])
    assert outs[0].ref != outs[1].ref and outs[0].identity == outs[1].identity and len(outs[0].identity) == 16
    assert identity("document", u, F1, "x") != identity("line", u, F1, "x")


def test_booked_needs_a_nonzero_posted_line(tmp_path):
    u, key, snap, al, _ = run(tmp_path, documents=[], rows=[], posted_lines=[b.posted(1, "5000", debit="0.00"),
                                                                           b.posted(2, "5000", debit="3.00")])
    assert not booked([{"id": 1}], al) and booked([{"id": 1}, {"id": 2}], al) and not booked([], al)


def test_align_fills_upload_files(tmp_path):
    u, key, snap, al, _ = run(tmp_path, documents=[doc("MN-D1", F1)], rows=[b.row(5, 99, gross="9.99")])
    snap.ledgers["2023-04-01"]["uploads"].append({"id": 99, "name": "stray.pdf"})
    al = align(key, snap, b.uploads_progress({F1: 7}), PROFILE, CODES)
    assert al.upload_files == {7: F1, 99: "stray.pdf"}


def extra(tmp_path, gross, upload_id=99, names=(("stray.pdf", 99),)):
    u, key, snap, al, _ = run(tmp_path, documents=[doc("MN-D1", F1)],
                              rows=[b.row(5, upload_id, gross=gross, date="2023-05-01", description="x")])
    snap.ledgers["2023-04-01"]["uploads"] += [{"id": i, "name": n} for n, i in names]
    al = align(key, snap, b.uploads_progress({F1: 7}), PROFILE, CODES)
    return check_extra_rows(u, al)[0]


def test_extra_row_carries_its_file_and_normalises_gross(tmp_path):
    a, c = extra(tmp_path, "9.9"), extra(tmp_path, "9.90")
    assert a.identity == c.identity and a.where == "stray.pdf"
    other = extra(tmp_path, "9.90", names=(("other.pdf", 99),))
    assert other.identity != a.identity


def test_one_sent_reply_in_a_folder_means_the_document_is_judged(tmp_path):
    queries = [{"query_id": "Q1", "answer_file": "answers/2024-03-12/a.txt"},
               {"query_id": "Q2", "answer_file": "answers/2024-03-12/b.txt"}]
    out, _ = docs_out(tmp_path, phase="after", documents=[doc("MN-D0003", ANS)], queries=queries,
                      replies={"Q1": {"sent": True}, "Q2": {"sent": False}},
                      rows=[b.row(1, 7, gross="120.00")], posted_lines=[b.posted(1, "5000", debit="120.00")])
    assert [(o.status, o.cause) for o in out] == [("pass", "")]
