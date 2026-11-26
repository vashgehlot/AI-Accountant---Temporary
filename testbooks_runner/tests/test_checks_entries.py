from decimal import Decimal
from pathlib import Path

import pytest

from testbooks_runner.align import align
from testbooks_runner.books import load_key
from testbooks_runner.cases import headline
from testbooks_runner.checks import (app_nets, app_vat_label, check_entries, is_vat_transfer, nets_match,
                                     not_attempted, paperless_journals)
from testbooks_runner.mapping import load_chart, load_vat
from testbooks_runner.runs import Progress
from testbooks_runner.tests import builders as b
from testbooks_runner.tests.test_checks_documents import CODES, F1, F3, PROFILE, doc, line, unit

CHART = load_chart()
VAT = load_vat()
D = Decimal


def ent(journal, account, debit="0.00", credit="0.00", doc_ids="D1", phase="books", **kw):
    e = {"entry_id": "E", "journal_id": journal, "date": "2023-04-15", "account": account, "account_name": "",
         "debit": debit, "credit": credit, "vat_code": "", "vat": "", "counterparty": "Cabot", "deal_id": "",
         "doc_ids": doc_ids, "line_ids": "", "stakes": "", "also_ok": "", "phase": phase, "cases": ""}
    e.update(kw)
    return e


def stationery_entries(**kw):
    return [ent("J1", "7504", debit="266.67", vat_code="standard", **kw),
            ent("J1", "9998", debit="53.33", also_ok="7504", **kw),
            ent("J1", "1240", credit="320.00", **kw)]


def go(tmp_path, entries, rows, posted_lines, phase="before", documents=None, queries=(), replies=None,
       decisions=(), chat_year=None, year="2023-04-01"):
    u = unit(tmp_path)
    key = b.key(documents=documents if documents is not None else [doc("D1", F1, gross="320.00")],
                entries=entries, queries=list(queries))
    snap = b.snapshot(rows=rows, posted_lines=posted_lines, decisions=decisions,
                      uploads=[{"id": 7, "name": F1.split("/")[-1]}])
    al = align(key, snap, b.uploads_progress({F1: 7}), PROFILE, CODES)
    progress = Progress(replies=replies or {}, chat_year=chat_year, app_year_start=year)
    return check_entries(u, key, snap, al, CHART, VAT, phase, progress), (u, key)


def test_entry_passes_with_also_ok(tmp_path):
    out, _ = go(tmp_path, stationery_entries(), [b.row(1, 7, gross="320.00", date="2023-04-15")],
                [b.posted(1, "7504", debit="320.00"), b.posted(1, "1240", credit="320.00")])
    (o,) = out
    assert (o.check, o.status, o.ref, o.phase) == ("entry", "pass", "mini:2024-03-31:entry:J1", "before")
    assert o.expected == "7504 266.67 Dr; 9998 53.33 Dr (or 7504); 1240 320.00 Cr; VAT: VAT at 20%"
    assert o.got.startswith("1240 320.00 Cr; 7504 320.00 Dr")
    assert o.where == F1


def test_entry_fails_with_tax_stakes_when_vat_reclaimed_early(tmp_path):
    out, _ = go(tmp_path, stationery_entries(), [b.row(1, 7, gross="320.00", date="2023-04-15")],
                [b.posted(1, "7504", debit="266.67"), b.posted(1, "2201", debit="53.33"),
                 b.posted(1, "1240", credit="320.00")])
    (o,) = out
    assert (o.status, o.stakes, o.cause) == ("fail", "tax", "booked wrong")
    assert o.data["deltas"] == {"2201": "53.33", "9998": "-53.33"}
    assert o.data["dates"] == ["2023-04-15"]
    assert o.amount == D("53.33")


def test_chart_choices_count(tmp_path):
    entries = [ent("J1", "1240", debit="1200.00"), ent("J1", "4010", credit="1200.00")]
    out, _ = go(tmp_path, entries, [b.row(1, 7, gross="1200.00", date="2023-04-15")],
                [b.posted(1, "4000", credit="1200.00"), b.posted(1, "1240", debit="1200.00")])
    assert out[0].status == "pass"


def test_tolerance_only_for_worked_out_vat(tmp_path):
    entries = [ent("J1", "7504", debit="16.67"), ent("J1", "2201", debit="3.33"), ent("J1", "1240", credit="20.00")]
    posted = [b.posted(1, "7504", debit="16.66"), b.posted(1, "2201", debit="3.33"),
              b.posted(1, "1240", credit="20.00")]
    docs = [doc("D1", F1, gross="20.00", vat="3.33")]
    worked = go(tmp_path, entries, [b.row(1, 7, gross="20.00", date="2023-04-15", vat=None, vat_posted="3.33")],
                posted, documents=docs)[0]
    printed = go(tmp_path, entries, [b.row(1, 7, gross="20.00", date="2023-04-15", vat="3.33", vat_posted="3.33")],
                 posted, documents=docs)[0]
    assert worked[0].status == "pass"
    assert printed[0].status == "fail"


def decision(did, trigger="background", **kw):
    d = {"id": did, "status": "applied", "trigger": trigger, "review_id": None, "actor": "rules"}
    d.update(kw)
    return d


WRONG = [b.posted(1, "7504", debit="320.00"), b.posted(1, "7000", credit="320.00")]


def test_causes(tmp_path):
    row = b.row(1, 7, gross="320.00", date="2023-04-15")
    misread = go(tmp_path, stationery_entries(), [dict(row, gross="302.00")], WRONG)[0][0]
    assert (misread.status, misread.cause) == ("fail", "misread")
    reviewed = go(tmp_path, stationery_entries(), [dict(row, decision_ids=["d1"])], WRONG,
                  decisions=[decision("d1", review_id="r1")])[0][0]
    assert reviewed.cause == "changed by the review"
    chatted = go(tmp_path, stationery_entries(), [dict(row, decision_ids=["d1"])], WRONG,
                 decisions=[decision("d1", trigger="chat", actor="agent:x")])[0][0]
    assert chatted.cause == "changed by the chat"
    ruled = go(tmp_path, stationery_entries(), [dict(row, decision_ids=["d1"])], WRONG,
               decisions=[decision("d1")])[0][0]
    assert ruled.cause == "booked wrong"
    assert go(tmp_path, stationery_entries(), [row], WRONG)[0][0].cause == "booked wrong"


def test_misread_ignores_removed_rows_but_their_review_decision_counts(tmp_path):
    live = b.row(1, 7, gross="320.00", date="2023-04-15")
    removed = b.row(2, 7, gross="999.00", date="2023-04-15", removed=True, decision_ids=["d1"])
    o = go(tmp_path, stationery_entries(), [live, removed], WRONG,
           decisions=[decision("d1", review_id="r1")])[0][0]
    assert o.cause == "changed by the review"  # not "misread", though the removed row's gross is off


def test_misread_on_date_and_printed_vat(tmp_path):
    docs = [doc("D1", F1, gross="320.00", vat="53.33")]
    late = go(tmp_path, stationery_entries(), [b.row(1, 7, gross="320.00", date="2023-05-15", vat="53.33")], WRONG,
              documents=docs)[0][0]
    no_vat = go(tmp_path, stationery_entries(), [b.row(1, 7, gross="320.00", date="2023-04-15", vat="1.00")], WRONG,
                documents=docs)[0][0]
    assert (late.cause, no_vat.cause) == ("misread", "misread")


def test_not_read_group_has_that_cause(tmp_path):
    u = unit(tmp_path)
    key = b.key(documents=[doc("D1", F1, gross="320.00")], entries=stationery_entries())
    prog = {F1: {"status": "failed", "upload_id": None}}
    snap = b.snapshot()
    al = align(key, snap, prog, PROFILE, CODES)
    (o,) = check_entries(u, key, snap, al, CHART, VAT, "before", Progress())
    assert (o.status, o.cause) == ("not_read", "not read")


ANSWER_FILE = "answers/2024-03-12/2024-02-08_wharf_woi-1.pdf"


def after_case(tmp_path, replies, chat_year, entries=None, queries=None):
    entries = entries or [ent("J2", "7504", debit="100.00", doc_ids="D2", phase="answers", deal_id="DEAL1"),
                          ent("J2", "1240", credit="100.00", doc_ids="D2", phase="answers", deal_id="DEAL1")]
    queries = queries if queries is not None else [{"query_id": "Q1", "about": "DEAL1", "answer_file": ANSWER_FILE}]
    docs = [doc("D1", F1, gross="320.00"), doc("D2", F1, gross="100.00")]
    return go(tmp_path, stationery_entries() + entries, [b.row(1, 7, gross="320.00", date="2023-04-15")],
              [b.posted(1, "7504", debit="266.67"), b.posted(1, "2201", debit="53.33"),
               b.posted(1, "1240", credit="320.00")], phase="after", documents=docs, queries=queries,
              replies=replies, chat_year=chat_year)[0]


def test_after_phase_checks_only_groups_with_answers_journals_and_names_the_reason(tmp_path):
    out = after_case(tmp_path, {}, None)
    # the books-only group of D1 is left to the "before" check; only the group with an answers journal is judged
    assert [o.ref for o in out] == ["mini:2024-03-31:entry:J2"] and out[0].phase == "after"
    assert out[0].cause == "the app never asked"
    sent = after_case(tmp_path, {"Q1": {"sent": True}}, "2026-04-01")
    assert sent[0].cause == "chat couldn't reach the year"
    plain = after_case(tmp_path, {"Q1": {"sent": True}}, "2023-04-01")
    assert plain[0].cause == "booked wrong"
    unlinked = after_case(tmp_path, {}, None, queries=[])
    assert unlinked[0].cause == "booked wrong"


def test_a_groups_before_and_after_outcomes_share_one_ref(tmp_path):
    # a pack's answer journal, ANSWER-PK-0002, sorts before its books journal, PK-0002
    books = [ent("PK-0002", "7504", debit="266.67"), ent("PK-0002", "9998", debit="53.33"),
             ent("PK-0002", "1240", credit="320.00")]
    answers = [ent("ANSWER-PK-0002", "2201", debit="53.33", phase="answers"),
               ent("ANSWER-PK-0002", "9998", credit="53.33", phase="answers")]
    rows = [b.row(1, 7, gross="320.00", date="2023-04-15")]
    posted = [b.posted(1, "7504", debit="266.67"), b.posted(1, "9998", debit="53.33"),
              b.posted(1, "1240", credit="320.00")]
    before, _ = go(tmp_path, books + answers, rows, posted)
    after, _ = go(tmp_path, books + answers, rows, posted, phase="after")
    assert [o.ref for o in before] == [o.ref for o in after] == ["mini:2024-03-31:entry:PK-0002"]
    assert headline(before + after, [])["entries_right"] == [0, 1]  # one group, counted once, at its worse phase


def test_before_phase_skips_answers_journals(tmp_path):
    entries = [ent("J2", "7504", debit="100.00", doc_ids="D2", phase="answers"),
               ent("J2", "1240", credit="100.00", doc_ids="D2", phase="answers")]
    out, _ = go(tmp_path, stationery_entries() + entries, [], [], documents=[doc("D1", F1), doc("D2", F1)])
    assert [o.ref for o in out] == ["mini:2024-03-31:entry:J1"]


def test_paperless_and_year_end_are_not_attempted(tmp_path):
    entries = (stationery_entries()
               + [ent("VAT-2023-05-31", "2200", debit="5.00", doc_ids=""),
                  ent("VAT-2023-05-31", "2202", credit="5.00", doc_ids=""),
                  ent("AG-0554", "7601", debit="9.00", doc_ids="", phase="answers", cases="EC-2"),
                  ent("AG-0554", "2100", credit="9.00", doc_ids="", phase="answers", cases="EC-2"),
                  ent("YE-01", "8000", debit="50.00", doc_ids="", phase="year_end"),
                  ent("YE-01", "0031", credit="50.00", doc_ids="", phase="year_end"),
                  ent("OPENING", "0030", debit="1.00", doc_ids="", phase="opening")])
    u = unit(tmp_path)
    out = not_attempted(u, b.key(entries=entries))
    got = {o.ref.rsplit(":", 1)[1]: (o.status, o.phase, o.stakes, o.check) for o in out}
    assert got == {"VAT-2023-05-31": ("not_attempted", "before", "accounts", "entry"),
                   "AG-0554": ("not_attempted", "after", "tax", "entry"),
                   "YE-01": ("not_attempted", "after", "accounts", "entry")}
    assert set(paperless_journals(b.key(entries=entries))) == {"VAT-2023-05-31", "AG-0554"}


def test_paperless_groups_are_not_checked_as_entries(tmp_path):
    entries = [ent("VAT-1", "2200", debit="5.00", doc_ids=""), ent("VAT-1", "2202", credit="5.00", doc_ids="")]
    out, _ = go(tmp_path, entries, [], [])
    assert out == []


def test_nets_match_prefers_primary_codes_on_a_tie():
    key_lines = [("7504", D("266.67"), ("7504",)), ("9998", D("53.33"), ("9998", "1200", "1210", "7504"))]
    ok, deltas = nets_match(key_lines, {"7504": D("266.67"), "2201": D("53.33")}, D(0))
    assert not ok
    assert deltas == {"2201": D("53.33"), "9998": D("-53.33")}


def test_nets_match_greedy_beyond_64_combinations():
    key_lines = [("a", D("1.00"), ("a", "b", "c", "d"))] * 4 + [("x", D("-4.00"), ("x",))]
    ok, deltas = nets_match(key_lines, {"a": D("2.00"), "b": D("2.00"), "x": D("-4.00")}, D(0))
    assert ok and deltas == {}


def test_helpers():
    assert is_vat_transfer([{"account": "2200"}, {"account": "2202"}])
    assert not is_vat_transfer([{"account": "2200"}, {"account": "7504"}]) and not is_vat_transfer([])
    assert app_vat_label({"reverse_charge": True, "vat_posted": "1.00"}) == "reverse charge"
    assert app_vat_label({"vat_posted": "3.33"}) == "VAT 3.33"
    assert app_vat_label({"vat_posted": "0.00", "vat_not_reclaimed": "2.00",
                          "vat_not_reclaimed_why": "entertainment"}) == "VAT not reclaimed: entertainment"
    assert app_vat_label({"vat_posted": None}) == "no VAT"
    al = align(b.key(), b.snapshot(posted_lines=[b.posted(1, "5000", debit="10.00"), b.posted(1, "1200", credit="4.00"),
                                                 b.posted(2, "5000", debit="1.00")]), {}, PROFILE, CODES)
    assert app_nets([{"id": 1}], al) == {"5000": D("10.00"), "1200": D("-4.00")}


def test_presentation_note_when_two_key_accounts_share_an_app_account(tmp_path):
    entries = [ent("J1", "1240", debit="1500.00"), ent("J1", "4000", credit="1000.00"),
               ent("J1", "4010", credit="500.00")]
    out, _ = go(tmp_path, entries, [b.row(1, 7, gross="1500.00", date="2023-04-15")],
                [b.posted(1, "4000", credit="1500.00"), b.posted(1, "1240", debit="1500.00")])
    assert out[0].status == "pass"
    assert out[0].data["presentation"] == "key 4000 and 4010 are one app account, 4000"
    plain, _ = go(tmp_path, stationery_entries(), [b.row(1, 7, gross="320.00", date="2023-04-15")],
                  [b.posted(1, "7504", debit="320.00"), b.posted(1, "1240", credit="320.00")])
    assert "presentation" not in plain[0].data


AGENCY = Path(__file__).parents[2] / "testbooks" / "out" / "clients" / "agency" / "key" / "2024-03-31"


@pytest.mark.skipif(not AGENCY.is_dir(), reason="the generated agency key isn't built here")
def test_paperless_journals_in_the_real_agency_key():
    found = set(paperless_journals(load_key(AGENCY)))
    assert {"REVERSAL-1", "REVERSAL-2", "REVERSAL-3", "AG-0031", "AG-0555"} <= found   # the write-off (AG-0554 before the groceries came in, 25 Nov)
    assert len([j for j in found if j.startswith("VAT-")]) == 4


STMT = doc("hsbc-statement-20230401-20230430", F3, treatment="evidence", gross="", date="2023-04-01",
           kind="bank_statement")


def paid_by_bank(tmp_path, posted_lines, row_fields=None, line_fields=None, stmt_status="saved", decisions=(),
                 doc_gross="120.00", doc_row=None, rows_extra=()):
    """A document D1 paid from the bank: one journal over the document and the statement line hsbc-1."""
    entries = [ent("J1", "7504", debit="120.00", line_ids="hsbc-1", vat_code="standard"),
               ent("J1", "1200", credit="120.00", line_ids="hsbc-1")]
    u = unit(tmp_path)
    key = b.key(documents=[doc("D1", F1, gross=doc_gross), STMT], entries=entries,
                lines=[line("hsbc-1", amount="-120.00", date_="2023-04-15", **(line_fields or {}))])
    bank = b.row(2, 8, **{"gross": "120.00", "date": "2023-04-15", "document_type": "statement",
                          "bank_account": "1200", **(row_fields or {})})
    d1 = doc_row or b.row(1, 7, gross="120.00", date="2023-04-15", vat="20.00", vat_posted="20.00")
    snap = b.snapshot(rows=[d1, bank, *rows_extra], posted_lines=posted_lines, decisions=decisions,
                      uploads=[{"id": 7, "name": F1.split("/")[-1]}, {"id": 8, "name": F3.split("/")[-1]}])
    prog = b.uploads_progress({F1: 7, F3: 8})
    if stmt_status != "saved":
        prog[F3] = {"status": stmt_status, "upload_id": None}
    al = align(key, snap, prog, PROFILE, CODES)
    return check_entries(u, key, snap, al, CHART, VAT, "before", Progress(app_year_start="2023-04-01"))


GOOD = [b.posted(1, "7504", debit="120.00"), b.posted(2, "1200", credit="120.00")]
WRONG_ACCT = [b.posted(1, "8207", debit="120.00"), b.posted(2, "1200", credit="120.00")]


def test_statement_group_read_exactly_is_booked_wrong_not_misread(tmp_path):
    assert paid_by_bank(tmp_path, GOOD)[0].status == "pass"
    (o,) = paid_by_bank(tmp_path, WRONG_ACCT)
    assert (o.status, o.cause) == ("fail", "booked wrong")


def test_statement_row_with_the_wrong_date_is_misread(tmp_path):
    (o,) = paid_by_bank(tmp_path, WRONG_ACCT, row_fields={"date": "2023-04-17"})
    assert o.cause == "misread"


def test_document_split_into_rows_is_not_misread_but_a_wrong_total_is(tmp_path):
    halves = [b.row(1, 7, gross="70.00", date="2023-04-15", vat="20.00"),
              b.row(3, 7, gross="50.00", date="2023-04-15")]
    (ok,) = paid_by_bank(tmp_path, WRONG_ACCT, doc_row=halves[0], rows_extra=[halves[1]])
    assert ok.cause == "booked wrong"
    (bad,) = paid_by_bank(tmp_path, WRONG_ACCT, doc_row=b.row(1, 7, gross="70.00", date="2023-04-15", vat="20.00"))
    assert bad.cause == "misread"


def test_unread_statement_makes_a_line_group_not_read(tmp_path):
    (o,) = paid_by_bank(tmp_path, [], stmt_status="failed")
    assert (o.status, o.cause) == ("not_read", "not read")


def test_bank_row_removed_by_the_review_gives_changed_by_the_review(tmp_path):
    (o,) = paid_by_bank(tmp_path, [b.posted(1, "7504", debit="120.00")],
                        row_fields={"removed": True, "decision_ids": ["d1"]},
                        decisions=[decision("d1", review_id="r1")])
    assert (o.status, o.cause) == ("fail", "changed by the review")


def test_transfer_passes_through_the_charts_also_with_a_presentation_note(tmp_path):
    u = unit(tmp_path)
    entries = [ent("J1", "1210", debit="500.00", doc_ids="", line_ids="hsbc-1"),
               ent("J1", "1290", credit="500.00", doc_ids="", line_ids="hsbc-1")]
    key = b.key(documents=[STMT], entries=entries, lines=[line("hsbc-1", amount="-500.00", date_="2023-04-15")])
    bank = b.row(2, 8, gross="500.00", date="2023-04-15", document_type="statement", bank_account="1200")
    snap = b.snapshot(rows=[bank], posted_lines=[],  # the app booked the transfer on the other account's row
                      uploads=[{"id": 8, "name": F3.split("/")[-1]}])
    al = align(key, snap, b.uploads_progress({F3: 8}), PROFILE, CODES)
    (o,) = check_entries(u, key, snap, al, CHART, VAT, "before", Progress())
    assert o.status == "pass"
    assert o.data["presentation"] == "key 1210 and 1290 are one app account, 1210"


def test_stakes_come_from_cases_and_key_line_stakes_before_the_tax_rule(tmp_path):
    posted_wrong = [b.posted(1, "7504", debit="266.67"), b.posted(1, "2201", debit="53.33"),
                    b.posted(1, "1240", credit="320.00")]
    row = [b.row(1, 7, gross="320.00", date="2023-04-15")]
    on_line = go(tmp_path, stationery_entries(stakes="presentation"), row, posted_wrong)[0][0]
    assert on_line.stakes == "presentation"  # a delta on 2201 doesn't override the key's own stakes
    entries = stationery_entries(stakes="process")
    entries[0]["cases"] = "EC-2"  # the catalogue says Tax
    mixed = go(tmp_path, entries, row, posted_wrong)[0][0]
    assert mixed.stakes == "tax"
    entries = stationery_entries(stakes="accounts")
    entries[0]["cases"] = "EC-3"  # Presentation; the line's accounts is higher
    assert go(tmp_path, entries, row, posted_wrong)[0][0].stakes == "accounts"
