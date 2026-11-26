from testbooks_runner.checks import Outcome
from testbooks_runner.compare import compare


def o(identity, status, phase="after"):
    return Outcome(check="entry", ref=identity, status=status, cases=("C",), stakes="tax", phase=phase,
                   identity=identity)


def ids(lst):
    return sorted(x.identity for x in lst)


def test_compare_new_fixed_still_flipped():
    prev = [o("fixed", "fail"), o("still", "fail"), o("flip", "pass"), o("gone", "fail")]
    cur = [o("fixed", "pass"), o("still", "fail"), o("flip", "fail"), o("new", "fail"), o("fine", "pass")]
    res = compare(cur, prev)
    assert set(res) == {"new", "flipped", "fixed", "still"}
    assert ids(res["new"]) == ["new"]
    assert ids(res["flipped"]) == ["flip"]
    assert ids(res["fixed"]) == ["fixed"]
    assert ids(res["still"]) == ["still"]


def test_compare_reduces_each_identity_to_its_worst_status():
    prev = [o("a", "pass", "before"), o("a", "fail", "after")]
    cur = [o("a", "pass", "before"), o("a", "pass", "after")]
    res = compare(cur, prev)
    assert ids(res["fixed"]) == ["a"] and len(res["fixed"]) == 1
    res = compare(prev, cur)
    assert ids(res["flipped"]) == ["a"] and len(res["flipped"]) == 1 and res["flipped"][0].status == "fail"


def test_compare_with_nothing_before_is_all_new():
    res = compare([o("a", "fail"), o("b", "pass")], [])
    assert ids(res["new"]) == ["a"] and res["fixed"] == res["still"] == res["flipped"] == []


def test_fail_after_a_non_fault_status_is_new_and_pass_after_it_is_in_no_bucket():
    others = ["not_read", "not_attempted", "cant_compare", "explained", "excluded"]
    prev = [o(f"p{s}", s) for s in others]
    res = compare([o(f"p{s}", "fail") for s in others], prev)
    assert ids(res["new"]) == sorted(f"p{s}" for s in others)
    assert res["flipped"] == res["still"] == res["fixed"] == []
    res = compare([o(f"p{s}", "pass") for s in others], prev)
    assert all(v == [] for v in res.values())
