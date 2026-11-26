from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from testbooks_runner.align import align
from testbooks_runner.books import load_key
from testbooks_runner.cases import headline
from testbooks_runner.checks import (Outcome, check_opening, check_queries, check_trial_balance, check_unpaid,
                                     check_vat, extra_questions, paperless_journals, _paperless_nets)
from testbooks_runner.mapping import app_code, load_chart
from testbooks_runner.model import Period, Unit, money
from testbooks_runner.runs import Progress
from testbooks_runner.tests import builders as b
from testbooks_runner.tests.test_checks_documents import CODES, F1, PROFILE, doc, unit

CHART = load_chart()
D = Decimal


def tb(account, before, year_end="0.00", final=None):
    return {"account": account, "name": "", "heading": "", "opening": "0.00", "books": before,
            "before_answers": before, "year_end": year_end, "final": final if final is not None else before}


def ent(journal, account, debit="0.00", credit="0.00", date="2023-05-31", phase="books", **kw):
    e = {"entry_id": "E", "journal_id": journal, "date": date, "account": account, "account_name": "",
         "debit": debit, "credit": credit, "vat_code": "", "vat": "", "counterparty": "", "deal_id": "",
         "doc_ids": "", "line_ids": "", "stakes": "", "also_ok": "", "phase": phase, "cases": ""}
    e.update(kw)
    return e


def entry_fault(deltas, dates=("2023-04-15",), status="fail", phase="before"):
    return Outcome(check="entry", ref="x:entry:J1", status=status, cases=(), stakes="tax", phase=phase,
                   data={"deltas": deltas, "dates": list(dates)})


def lines(**nets):
    """Posted trial balance lines from code=net (debit positive)."""
    return [{"code": c, "debit": str(max(n, D(0))), "credit": str(max(-n, D(0)))}
            for c, n in ((c, D(n)) for c, n in nets.items())]


def by_code(out):
    return {o.ref.rsplit(":", 1)[1]: o for o in out}


def test_tb_pass_explained_fail(tmp_path):
    u = unit(tmp_path)
    key = b.key(trial_balance=[tb("7504", "100.00")])
    fault = entry_fault({"7504": "53.33", "9998": "-53.33"})

    def run(amount, outcomes=()):
        snap = b.snapshot(tb_lines=lines(**{"7504": amount}))
        return by_code(check_trial_balance(u, key, snap, CHART, list(outcomes), "before"))["7504"]

    ok, explained, bad = run("100.00"), run("153.33", [fault]), run("200.00", [fault])
    assert (ok.status, ok.check, ok.phase, ok.ref) == ("pass", "tb", "before", "mini:2024-03-31:tb:7504")
    assert (explained.status, explained.cause) == ("explained", "")
    assert (bad.status, bad.cause, bad.amount) == ("fail", "unexplained", D("46.67"))  # 100.00 less 53.33 explained
    assert bad.data["raw"] == "100.00"
    assert run("200.00").amount == D("100.00")
    assert (bad.expected, bad.got) == ("100.00", "200.00")
    assert ok.identity and ok.identity == bad.identity  # the key row, not the app's figure, names it


def test_tb_not_read_entry_deltas_explain_a_difference(tmp_path):
    u = unit(tmp_path)
    key = b.key(trial_balance=[tb("7504", "100.00")])
    snap = b.snapshot(tb_lines=lines(**{"7504": "0.00"}))
    gone = entry_fault({"7504": "-100.00"}, status="not_read")
    (o,) = [o for o in check_trial_balance(u, key, snap, CHART, [gone], "before") if o.ref.endswith(":7504")]
    assert o.status == "explained"
    # a passing entry, or one from the other phase, explains nothing
    other = entry_fault({"7504": "-100.00"}, phase="after")
    (o,) = check_trial_balance(u, key, snap, CHART, [other], "before")
    assert o.status == "fail"


def test_tb_takes_out_paperless_journals(tmp_path):
    u = unit(tmp_path)
    entries = [ent("VAT-2023-05-31", "2200", debit="26495.32"), ent("VAT-2023-05-31", "2202", credit="26495.32")]
    key = b.key(entries=entries, trial_balance=[tb("2200", "0.00"), tb("2202", "-26495.32")])
    snap = b.snapshot(tb_lines=lines(**{"2200": "-26495.32", "2202": "0"}))
    out = by_code(check_trial_balance(u, key, snap, CHART, [], "before"))
    assert (out["2200"].status, out["2202"].status) == ("pass", "pass")
    assert (out["2200"].stakes, out["2202"].stakes) == ("tax", "tax")


def test_tb_after_uses_final_less_year_end(tmp_path):
    u = unit(tmp_path)
    key = b.key(trial_balance=[tb("7504", "100.00", year_end="40.00", final="190.00")])
    snap = b.snapshot(tb_lines=lines(**{"7504": "150.00"}))
    after = check_trial_balance(u, key, snap, CHART, [], "after")
    before = check_trial_balance(u, key, snap, CHART, [], "before")
    assert [(o.status, o.phase) for o in after] == [("pass", "after")]
    assert [(o.status, o.phase) for o in before] == [("fail", "before")]


def test_tb_after_takes_out_answers_journals_too(tmp_path):
    u = unit(tmp_path)
    entries = [ent("ADJ", "7504", debit="10.00", phase="answers"), ent("ADJ", "9998", credit="10.00", phase="answers")]
    key = b.key(entries=entries, trial_balance=[tb("7504", "110.00", final="110.00"), tb("9998", "-10.00")])
    snap = b.snapshot(tb_lines=lines(**{"7504": "100.00", "9998": "0"}))
    out = by_code(check_trial_balance(u, key, snap, CHART, [], "after"))
    assert (out["7504"].status, out["9998"].status) == ("pass", "pass")
    out = by_code(check_trial_balance(u, key, snap, CHART, [], "before"))
    assert out["7504"].status == "fail"


def test_the_headline_sums_a_failing_trial_balance(tmp_path):
    u = unit(tmp_path)
    key = b.key(trial_balance=[tb("7504", "100.00"), tb("7406", "10.00")])
    snap = b.snapshot(tb_lines=lines(**{"7504": "150.00", "7406": "10.00"}))
    out = check_trial_balance(u, key, snap, CHART, [], "before")
    assert {(o.ref.rsplit(":", 1)[1], o.status) for o in out} == {("7504", "fail"), ("7406", "pass")}
    assert headline(out, [])["tb_difference"] == {"before": "50.00", "after": "0.00"}


def test_tb_without_a_posted_trial_balance_cannot_be_compared(tmp_path):
    u = unit(tmp_path)
    snap = b.snapshot()
    snap.posted = {}
    snap.errors = {"posted-2023-04-01": {"status": 500, "code": "boom", "message": "it broke"}}
    (o,) = check_trial_balance(u, b.key(trial_balance=[tb("7504", "1.00")]), snap, CHART, [], "before")
    assert o.status == "cant_compare" and "it broke" in o.got


def test_opening_compared_once(tmp_path):
    u = unit(tmp_path)
    key = b.key(opening=[{"account": "1200", "name": "", "debit": "500.00", "credit": "", "source": ""},
                         {"account": "2100", "name": "", "debit": "", "credit": "500.00", "source": ""}])
    snap = b.snapshot(opening=[{"code": "1200", "debit": "500.00", "credit": "0.00"},
                               {"code": "2100", "debit": "0.00", "credit": "400.00"}])
    out = by_code(check_opening(u, key, snap, CHART))
    assert {o.phase for o in out.values()} == {"before"} and {o.check for o in out.values()} == {"opening"}
    assert out["1200"].status == "pass" and out["1200"].ref == "mini:2024-03-31:opening:1200"
    assert (out["2100"].status, out["2100"].amount) == ("fail", D("100.00"))


QUARTER = {"period_start": "2023-12-01", "period_end": "2024-02-29", "box1": "28872.87", "box2": "0.00",
           "box3": "28872.87", "box4": "4116.09", "box5": "24756.78", "box6": "144364", "box7": "46762",
           "box8": "0", "box9": "0", "due": "", "dd": ""}


def figures(**over):
    f = {"start": "2023-12-01", "end": "2024-02-29", "notes": []}
    f.update({k: v for k, v in QUARTER.items() if k.startswith("box")})
    f.update(over)
    return f


def test_vat_quarter_straddling_the_books_cannot_be_compared(tmp_path):
    u = unit(tmp_path)
    q = dict(QUARTER, period_start="2023-03-01", period_end="2023-05-31")
    snap = b.snapshot(vat={("2023-03-01", "2023-05-31"): figures()})
    out = check_vat(u, b.key(vat_returns=[q]), snap, [])
    assert len(out) == 9 and {o.status for o in out} == {"cant_compare"}
    assert out[0].ref == "mini:2024-03-31:vat:2023-03-01:2023-05-31:box1" and out[0].stakes == "tax"


def test_vat_quarter_with_an_error_file_cannot_be_compared(tmp_path):
    u = unit(tmp_path)
    snap = b.snapshot()
    snap.errors = {"vat-2023-12-01-2024-02-29": {"status": 422, "code": "invalid_input", "message": "nope"}}
    out = check_vat(u, b.key(vat_returns=[QUARTER]), snap, [])
    assert {o.status for o in out} == {"cant_compare"} and "nope" in out[0].got
    out = check_vat(u, b.key(vat_returns=[QUARTER]), b.snapshot(), [])  # no file at all
    assert {o.status for o in out} == {"cant_compare"}


def test_vat_pass_with_pound_tolerance_on_boxes_6_to_9(tmp_path):
    u = unit(tmp_path)
    snap = b.snapshot(vat={("2023-12-01", "2024-02-29"): figures(box6="144364.60", box7="46762.40")})
    out = check_vat(u, b.key(vat_returns=[QUARTER]), snap, [])
    assert {o.status for o in out} == {"pass"}
    snap = b.snapshot(vat={("2023-12-01", "2024-02-29"): figures(box6="144366.00", box4="4116.12", box5="24756.75")})
    got = {o.ref.rsplit(":", 1)[1]: o.status for o in check_vat(u, b.key(vat_returns=[QUARTER]), snap, [])}
    assert (got["box6"], got["box4"], got["box5"]) == ("fail", "fail", "fail")


def test_vat_bad_debt_relief_taken_out_of_box_4(tmp_path):
    u = unit(tmp_path)
    entries = [ent("AG-0554", "8100", debit="4000.00", date="2024-01-31"),
               ent("AG-0554", "2201", debit="800.00", date="2024-01-31"),
               ent("AG-0554", "1100", credit="4800.00", date="2024-01-31"),
               ent("VAT-2024-02-29", "2200", debit="28872.87", date="2024-02-29"),
               ent("VAT-2024-02-29", "2202", credit="28872.87", date="2024-02-29")]
    key = b.key(entries=entries, vat_returns=[QUARTER])
    snap = b.snapshot(vat={("2023-12-01", "2024-02-29"): figures(box4="3316.09", box5="25556.78")})
    out = check_vat(u, key, snap, [])
    assert {o.status for o in out} == {"pass"}
    out = by_code(check_vat(u, key, b.snapshot(vat={("2023-12-01", "2024-02-29"): figures()}), []))
    assert (out["box4"].status, out["box4"].expected, out["box5"].expected) == ("fail", "3316.09", "25556.78")


def test_vat_sales_credit_taken_out_of_box_1(tmp_path):
    u = unit(tmp_path)
    entries = [ent("FIX", "2200", credit="100.00", date="2024-01-10"), ent("FIX", "8250", debit="100.00", date="2024-01-10")]
    snap = b.snapshot(vat={("2023-12-01", "2024-02-29"): figures(box1="28772.87", box3="28772.87", box5="24656.78")})
    assert {o.status for o in check_vat(u, b.key(entries=entries, vat_returns=[QUARTER]), snap, [])} == {"pass"}


def test_vat_box_explained_by_entry_faults_in_the_quarter(tmp_path):
    u = unit(tmp_path)
    key = b.key(vat_returns=[QUARTER])
    snap = b.snapshot(vat={("2023-12-01", "2024-02-29"): figures(box4="4169.42", box5="24703.45")})
    inside = entry_fault({"2201": "53.33"}, dates=("2024-01-15",))
    outside = entry_fault({"2201": "53.33"}, dates=("2023-10-15",))
    by_status = lambda outs: {o.ref.rsplit(":", 1)[1]: o.status for o in check_vat(u, key, snap, outs)}  # noqa: E731
    got = by_status([inside])
    assert (got["box4"], got["box5"], got["box1"]) == ("explained", "explained", "pass")
    got = by_status([outside])
    assert (got["box4"], got["box5"]) == ("fail", "fail")
    assert by_status([entry_fault({"2201": "1"}, dates=("2024-01-15",), phase="after")])["box4"] == "fail"
    (bad,) = [o for o in check_vat(u, key, snap, [outside]) if o.ref.endswith("box4")]
    assert (bad.cause, bad.amount) == ("unexplained", D("53.33"))


def drow(as_at, who, number, gross, owed, date="2024-01-05", doc_id="D"):
    return {"as_at": as_at, "counterparty": who, "doc_id": doc_id, "number": number, "date": date,
            "gross": gross, "paid": "0.00", "owed": owed}


def inv(who, number, total, owed, kind="sale"):
    return {"ref": "r", "kind": kind, "counterparty": who, "number": number, "date": "2024-01-05",
            "total": total, "paid": "0.00", "owed": owed, "brought_forward": False}


def test_unpaid_matched_by_number_then_counterparty(tmp_path):
    u = unit(tmp_path)
    key = b.key(debtors=[drow("2024-02-29", "Old Ltd", "KF-1", "50.00", "50.00"),  # not the latest as_at
                         drow("2024-03-31", "Brightwater Homes Ltd", "KF-1001", "7200.00", "7200.00"),
                         drow("2024-03-31", "Portway Logistics", "KF-1002", "1000.00", "400.00"),
                         drow("2024-03-31", "Zero Ltd", "KF-1003", "10.00", "0.00")],
                creditors=[drow("2024-03-31", "Wharfside", "W-9", "320.00", "320.00")])
    snap = b.snapshot(invoices=[inv("Brightwater Homes Ltd", "kf-1001", "7200.00", "7200.00"),
                                inv("PORTWAY LOGISTICS", "99", "1000.00", "400.00"),
                                inv("Wharfside", "W-9", "320.00", "300.00", kind="purchase"),
                                inv("Paid Ltd", "P-1", "5.00", "0.00")])
    out = {o.ref.split(":unpaid:")[1].split(":", 1)[1]: o for o in check_unpaid(u, key, snap, False)}
    assert set(out) == {"Brightwater Homes Ltd:KF-1001", "Portway Logistics:KF-1002", "Wharfside:W-9"}
    assert out["Brightwater Homes Ltd:KF-1001"].status == "pass"
    assert out["Portway Logistics:KF-1002"].status == "pass"
    w = out["Wharfside:W-9"]
    assert (w.status, w.cause, w.stakes, w.amount, w.phase) == ("fail", "unexplained", "accounts", D("20.00"), "before")


def test_unpaid_unmatched_rows_fail_either_side(tmp_path):
    u = unit(tmp_path)
    key = b.key(debtors=[drow("2024-03-31", "Missing Ltd", "KF-5", "100.00", "100.00")])
    snap = b.snapshot(invoices=[inv("Extra Ltd", "X-1", "60.00", "60.00")])
    out = {o.ref.split(":unpaid:")[1].split(":", 1)[1]: o for o in check_unpaid(u, key, snap, False)}
    assert (out["Missing Ltd:KF-5"].status, out["Missing Ltd:KF-5"].amount) == ("fail", D("100.00"))
    assert (out["Extra Ltd:X-1"].status, out["Extra Ltd:X-1"].amount) == ("fail", D("60.00"))
    assert {o.cause for o in out.values()} == {"unexplained"}


def test_unpaid_counts_what_was_owed_at_the_year_end_when_the_app_says_it(tmp_path):
    # The app's list says what is owed after every payment, in any year: Mendip's invoice, paid on 2 Apr 2024, showed
    # nothing owed though the key owes it at 31 Mar 2024. The app now also says what was owed at the year's end.
    u = unit(tmp_path)
    key = b.key(debtors=[drow("2024-03-31", "Mendip Cheese Co", "KF-1096", "16380.00", "16380.00")])
    paid_since = {**inv("Mendip Cheese Co", "KF-1096", "16380.00", "0.00"), "owed_at_year_end": "16380.00"}
    (o,) = check_unpaid(u, key, b.snapshot(invoices=[paid_since]), False)
    assert o.status == "pass"


WRITE_OFF = [ent("AG-0554", "8100", debit="4000.00", date="2024-01-31", counterparty="Lowther Interiors Ltd"),
             ent("AG-0554", "2201", debit="800.00", date="2024-01-31", counterparty="Lowther Interiors Ltd"),
             ent("AG-0554", "1100", credit="4800.00", date="2024-01-31", counterparty="Lowther Interiors Ltd")]


def test_unpaid_write_off_taken_out(tmp_path):
    u = unit(tmp_path)
    snap = b.snapshot(invoices=[inv("lowther interiors ltd", "KF-77", "4800.00", "4800.00")])
    assert check_unpaid(u, b.key(entries=WRITE_OFF), snap, False) == []
    (o,) = check_unpaid(u, b.key(), snap, False)  # no journal: the app's invoice is a fault
    assert o.status == "fail"


def test_unpaid_cannot_be_compared_after_next_year_papers(tmp_path):
    u = unit(tmp_path)
    key = b.key(debtors=[drow("2024-03-31", "A", "N-1", "10.00", "10.00")])
    snap = b.snapshot(invoices=[inv("B", "N-2", "5.00", "5.00")])
    out = check_unpaid(u, key, snap, True)
    assert len(out) == 2 and {o.status for o in out} == {"cant_compare"}


def query_setup(tmp_path, questions=(), reviews=(), replies=None):
    u = unit(tmp_path)
    queries = [{"query_id": "Q1", "about": "D1", "question": "Is it right?", "why": "", "stakes": "Tax",
                "answer_file": "answers/x.txt", "answer_date": "", "effect": ""},
               {"query_id": "Q2", "about": "D9", "question": "Other?", "why": "", "stakes": "", "answer_file": "",
                "answer_date": "", "effect": ""}]
    entries = [ent("J1", "7504", debit="1.00", doc_ids="D1", cases="EC-2")]
    key = b.key(documents=[doc("D1", F1, gross="320.00")], entries=entries, queries=queries)
    snap = b.snapshot(rows=[b.row(1, 7, gross="320.00", date="2023-04-15")], questions=list(questions),
                      reviews=list(reviews), uploads=[{"id": 7, "name": F1.split("/")[-1]}])
    al = align(key, snap, b.uploads_progress({F1: 7}), PROFILE, CODES)
    return u, key, snap, al, Progress(replies=replies or {})


QUESTION = {"id": 5, "text": "Is it right?", "row_ids": [1], "status": "open"}


def test_queries_asked_or_never_asked(tmp_path):
    u, key, snap, al, progress = query_setup(tmp_path, questions=[QUESTION])
    out = {o.ref.rsplit(":", 1)[1]: o for o in check_queries(u, key, snap, al, progress)}
    assert (out["Q1"].status, out["Q1"].phase, out["Q1"].ref) == ("pass", "before", "mini:2024-03-31:query:Q1")
    q2 = out["Q2"]
    assert (q2.status, q2.cause, q2.stakes) == ("fail", "the app never asked", "accounts")
    u, key, snap, al, progress = query_setup(tmp_path)
    out = {o.ref.rsplit(":", 1)[1]: o for o in check_queries(u, key, snap, al, progress)}
    assert (out["Q1"].status, out["Q1"].cause, out["Q1"].stakes) == ("fail", "the app never asked", "tax")
    assert out["Q1"].cases == ("EC-2",)


def test_query_asked_only_in_a_review_or_the_chat_counts(tmp_path):
    resolved = dict(QUESTION, status="resolved")
    u, key, snap, al, progress = query_setup(tmp_path, reviews=[{"id": 1, "questions": [resolved]}])
    assert {o.ref[-2:]: o.status for o in check_queries(u, key, snap, al, progress)}["Q1"] == "pass"
    replies = {"Q0": {"sent": True, "asked_back": [QUESTION]}}
    u, key, snap, al, progress = query_setup(tmp_path, replies=replies)
    assert {o.ref[-2:]: o.status for o in check_queries(u, key, snap, al, progress)}["Q1"] == "pass"
    snap.which = "after"
    assert {o.phase for o in check_queries(u, key, snap, al, progress)} == {"after"}


def test_a_question_the_reply_resolved_still_counts_as_asked(tmp_path):
    u, key, before, al_before, progress = query_setup(tmp_path, questions=[QUESTION])
    *_, after, al_after, _ = query_setup(tmp_path)  # the app lists only open and waiting questions
    after.which = "after"
    out = {o.ref.rsplit(":", 1)[1]: o for o in check_queries(u, key, after, al_after, progress,
                                                            [(before, al_before)])}
    assert (out["Q1"].status, out["Q1"].phase, out["Q2"].status) == ("pass", "after", "fail")
    assert {o.ref[-2:]: o.status for o in check_queries(u, key, after, al_after, progress)}["Q1"] == "fail"
    assert extra_questions(after, al_after, key, [(before, al_before)]) == []


def test_a_sent_reply_means_its_query_was_asked(tmp_path):
    for sent, status in ((True, "pass"), (False, "fail")):
        u, key, snap, al, progress = query_setup(tmp_path, replies={"Q1": {"sent": sent, "question_id": 5}})
        assert {o.ref[-2:]: o.status for o in check_queries(u, key, snap, al, progress)}["Q1"] == status


def test_extra_questions_from_both_snapshots_each_once(tmp_path):
    stray = {"id": 6, "text": "Why?", "row_ids": [], "status": "open"}
    gone = {"id": 8, "text": "And that?", "row_ids": [], "status": "open"}
    u, key, before, al_before, _ = query_setup(tmp_path, questions=[stray, gone])
    *_, after, al_after, _ = query_setup(tmp_path, questions=[dict(stray, status="waiting")])
    assert extra_questions(after, al_after, key, [(before, al_before)]) == [dict(stray, status="waiting"), gone]


def test_extra_questions_listed(tmp_path):
    stray = {"id": 6, "text": "Why?", "row_ids": [], "status": "open"}
    review_stray = {"id": 7, "text": "And this?", "row_ids": [], "status": "resolved"}
    u, key, snap, al, progress = query_setup(tmp_path, questions=[QUESTION, stray],
                                             reviews=[{"id": 1, "questions": [review_stray, stray]}])
    assert extra_questions(snap, al, key) == [stray, review_stray]


AGENCY = Path(__file__).resolve().parents[2] / "testbooks" / "out" / "clients" / "agency" / "key" / "2024-03-31"


@pytest.mark.skipif(not AGENCY.is_dir(), reason="the agency's key isn't built here")
def test_real_agency_before_answers_balance_passes_every_account():
    u = Unit("agency", "client", AGENCY.parents[1], Period(date(2023, 4, 1), date(2024, 3, 31)))
    key = load_key(AGENCY)
    nets: dict[str, Decimal] = {}
    for r in key.trial_balance:
        code = app_code(CHART, r["account"])
        nets[code] = nets.get(code, D(0)) + money(r["before_answers"])
    for code, net in _paperless_nets(key, CHART, ("books",)).items():
        nets[code] = nets.get(code, D(0)) - net
    assert len(paperless_journals(key)) == 9
    snap = b.snapshot(tb_lines=lines(**nets))
    out = check_trial_balance(u, key, snap, CHART, [], "before")
    assert out and {o.status for o in out} == {"pass"}
    opening = [{"code": app_code(CHART, r["account"]), "debit": r["debit"] or "0", "credit": r["credit"] or "0"}
               for r in key.opening]
    out = check_opening(u, key, b.snapshot(opening=opening), CHART)
    assert out and {o.status for o in out} == {"pass"}


def test_vat_box_5_repayment_compared_by_absolute_value(tmp_path):
    u = unit(tmp_path)
    q = dict(QUARTER, box1="100.00", box3="100.00", box4="220.00", box5="120.00")
    snap = b.snapshot(vat={("2023-12-01", "2024-02-29"): figures(box1="100.00", box3="100.00", box4="220.00",
                                                                 box5="-120.00")})
    assert {o.status for o in check_vat(u, b.key(vat_returns=[q]), snap, [])} == {"pass"}
    snap.vat[("2023-12-01", "2024-02-29")]["box5"] = "-130.00"
    got = {o.ref.rsplit(":", 1)[1]: o.status for o in check_vat(u, b.key(vat_returns=[q]), snap, [])}
    assert got["box5"] == "fail"


def test_unpaid_refs_carry_the_side(tmp_path):
    u = unit(tmp_path)
    key = b.key(debtors=[drow("2024-03-31", "Same Ltd", "N-1", "10.00", "10.00")],
                creditors=[drow("2024-03-31", "Same Ltd", "N-1", "10.00", "10.00")])
    snap = b.snapshot(invoices=[inv("Other", "O-1", "5.00", "5.00", kind="purchase"),
                                inv("Another", "A-1", "5.00", "5.00")])
    refs = sorted(o.ref.split(":unpaid:")[1] for o in check_unpaid(u, key, snap, False))
    assert refs == ["creditor:Other:O-1", "creditor:Same Ltd:N-1", "debtor:Another:A-1", "debtor:Same Ltd:N-1"]
