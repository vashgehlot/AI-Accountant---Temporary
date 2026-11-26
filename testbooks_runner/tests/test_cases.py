from decimal import Decimal

from testbooks_runner.cases import CaseResult, headline, pass_k, roll_up
from testbooks_runner.checks import Outcome

CATALOGUE = {
    "EC-0334": {"id": "EC-0334", "category": "Leases", "title": "Monthly lease", "stakes": "Tax"},
    "EC-0100": {"id": "EC-0100", "category": "Bank", "title": "Bank fees", "stakes": "Accounts"},
    "EC-0200": {"id": "EC-0200", "category": "Look", "title": "Layout", "stakes": "Presentation"},
}


def out(ref="R1", status="pass", cases=("EC-0334",), check="entry", phase="before", **kw):
    return Outcome(check=check, ref=ref, status=status, cases=cases, stakes="tax", phase=phase, **kw)


def one(outcomes, case="EC-0334"):
    return {r.case: r for r in roll_up(outcomes, CATALOGUE)}[case]


def test_one_failure_fails_the_case_and_counts():
    outcomes = [out(ref=f"R{i}", status="fail" if i == 3 else "pass") for i in range(12)]
    r = one(outcomes)
    assert (r.status, r.passed, r.total) == ("fail", 11, 12)
    assert (r.title, r.category, r.stakes) == ("Monthly lease", "Leases", "tax")
    assert len(r.outcomes) == 12


def test_not_attempted_only_when_all_are():
    assert one([out("A", "not_attempted"), out("B", "pass")]).status == "pass"
    assert one([out("A", "not_attempted"), out("B", "not_attempted")]).status == "not_attempted"
    assert one([out("A", "not_attempted"), out("B", "cant_compare")]).status == "cant_compare"
    assert one([out("A", "not_read"), out("B", "pass")]).status == "not_read"
    assert one([out("A", "not_read"), out("B", "fail")]).status == "fail"


def test_explained_and_excluded_ignored():
    r = one([out("A", "explained"), out("B", "excluded"), out("C", "pass")])
    assert (r.status, r.total, r.passed) == ("pass", 1, 1)
    assert roll_up([out("A", "explained")], CATALOGUE) == []


def test_worst_phase_counts_once():
    r = one([out(status="pass", phase="before"), out(status="fail", phase="after")])
    assert (r.status, r.total, r.passed) == ("fail", 1, 0)
    assert [o.phase for o in r.outcomes] == ["after"]


def test_outcome_naming_several_cases_counts_in_each():
    results = roll_up([out(cases=("EC-0334", "EC-0100"))], CATALOGUE)
    assert {r.case for r in results} == {"EC-0334", "EC-0100"}


def test_ordered_by_stakes():
    outcomes = [out(cases=("EC-0200",)), out(cases=("EC-0100",)), out(cases=("EC-0334",))]
    assert [r.case for r in roll_up(outcomes, CATALOGUE)] == ["EC-0334", "EC-0100", "EC-0200"]


def test_headline_figures():
    outcomes = [
        out("E1", "pass"), out("E2", "pass"), out("E3", "fail"),
        out("E4", "not_attempted"), out("E5", "explained"),
        out("D1", "pass", check="document"), out("D2", "not_read", check="document"),
        out("Q1", "pass", check="query"),
        out("Q1", "fail", check="query", phase="after"),
        out("T1", "fail", check="tb", amount=Decimal("10.00")),
        out("T2", "fail", check="tb", amount=Decimal("5.00")),
        out("T3", "explained", check="tb", amount=Decimal("7.00")),
        out("T4", "pass", check="tb", amount=Decimal("9.00")),
        out("T1", "fail", check="tb", phase="after", amount=Decimal("2.5")),
        out("V1", "fail", check="vat", amount=Decimal("3.10")),
        out("V2", "pass", check="vat", amount=Decimal("1")),
        out("F1", "not_read", cause="not read", where="a.pdf"),
        out("F2", "not_read", cause="not read", where="a.pdf"),
        out("F3", "not_read", cause="not read", where="b.pdf"),
        out("F4", "not_read", cause="misread", where="c.pdf"),
    ]
    h = headline(outcomes, roll_up(outcomes, CATALOGUE))
    assert h["entries_right"] == [2, 7]  # E1-E3 plus F1-F4 are entry outcomes: 2 pass of 7
    assert h["documents_right"] == [1, 2]
    assert h["queries_asked"] == [0, 1]
    assert h["tb_difference"] == {"before": "15.00", "after": "2.50"}
    assert h["vat_difference"] == "3.10"
    assert h["files_not_read"] == 2
    assert h["by_stakes"]["tax"]["fail"] == 1
    assert h["by_stakes"]["accounts"]["pass"] == 0


def test_by_stakes_counts_cases():
    outcomes = [out(cases=("EC-0334",), status="pass"), out("B", "fail", cases=("EC-0100",)),
                out("C", "not_attempted", cases=("EC-0200",))]
    h = headline(outcomes, roll_up(outcomes, CATALOGUE))
    assert h["by_stakes"]["tax"]["pass"] == 1
    assert h["by_stakes"]["accounts"]["fail"] == 1
    assert h["by_stakes"]["presentation"]["not_attempted"] == 1


def test_headline_with_nothing():
    h = headline([], [])
    assert h["entries_right"] == [0, 0]
    assert h["tb_difference"] == {"before": "0.00", "after": "0.00"}
    assert h["vat_difference"] == "0.00"


def result(case, status):
    return CaseResult(case, "t", "c", "tax", status, 0, 1, [])


def test_pass_k_and_flaky():
    p, f = result("A", "pass"), result("A", "fail")
    assert pass_k([[p], [p]]) == {"A": "pass"}
    assert pass_k([[p], [f]]) == {"A": "flaky"}
    assert pass_k([[f], [f]]) == {"A": "fail"}


def test_pass_k_mixed_without_both_takes_the_worst():
    p, nr = result("A", "pass"), result("A", "not_read")
    assert pass_k([[p], [nr]]) == {"A": "not_read"}
    assert pass_k([[result("A", "not_attempted")], [result("A", "cant_compare")]]) == {"A": "not_attempted"}
    assert pass_k([[nr], [nr]]) == {"A": "not_read"}


def test_pass_k_missing_case_counts_as_not_read():
    p = result("A", "pass")
    assert pass_k([[p], []]) == {"A": "not_read"}
    assert pass_k([[p, result("B", "pass")], [p]]) == {"A": "pass", "B": "not_read"}
    assert pass_k([[result("A", "fail")], []]) == {"A": "fail"}


def test_vat_box_failing_in_both_phases_counts_once_with_the_after_amount():
    outcomes = [
        out("V1", "fail", check="vat", phase="before", amount=Decimal("8.00")),
        out("V1", "fail", check="vat", phase="after", amount=Decimal("3.00")),
        out("V2", "fail", check="vat", phase="before", amount=Decimal("1.50")),
        out("V3", "fail", check="vat", phase="before", amount=Decimal("4.00")),
        out("V3", "pass", check="vat", phase="after", amount=Decimal("0")),
    ]
    assert headline(outcomes, [])["vat_difference"] == "4.50"
