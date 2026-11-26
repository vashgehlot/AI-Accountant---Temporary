"""Roll Outcomes up into catalogue cases, the report's headline and each case's Pass^k."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .checks import STAKES_ORDER, TB, Outcome

# Worst first: fail, then not_read, then pass, then not_attempted, then cant_compare.
PRIORITY = ("fail", "not_read", "pass", "not_attempted", "cant_compare")
_IGNORED = ("explained", "excluded")
_CENT = Decimal("0.01")


@dataclass
class CaseResult:
    case: str
    title: str
    category: str
    stakes: str
    status: str
    passed: int
    total: int
    outcomes: list[Outcome]


def _worst(statuses) -> str:
    return min(statuses, key=PRIORITY.index)


def _worst_per_ref(outcomes) -> list[Outcome]:
    """One outcome per (check, ref), the worst across phases; explained and excluded are dropped."""
    best: dict[tuple[str, str], Outcome] = {}
    for o in outcomes:
        if o.status in _IGNORED or o.status not in PRIORITY:
            continue
        key = (o.check, o.ref)
        if key not in best or PRIORITY.index(o.status) < PRIORITY.index(best[key].status):
            best[key] = o
    return list(best.values())


def _case_status(statuses: list[str]) -> str:
    for status in ("fail", "not_read", "pass"):
        if status in statuses:
            return status
    return "not_attempted" if all(s == "not_attempted" for s in statuses) else "cant_compare"


def roll_up(outcomes: list[Outcome], catalogue: dict[str, dict]) -> list[CaseResult]:
    by_case: dict[str, list[Outcome]] = {}
    for o in outcomes:
        for case in o.cases:
            by_case.setdefault(case, []).append(o)
    results = []
    for case, group in by_case.items():
        counted = _worst_per_ref(group)
        if not counted:
            continue
        row = catalogue.get(case) or {}
        stakes = (row.get("stakes") or "").strip().lower()
        if stakes not in STAKES_ORDER:
            stakes = min((o.stakes for o in counted if o.stakes in STAKES_ORDER),
                         key=STAKES_ORDER.index, default="accounts")
        results.append(CaseResult(
            case=case, title=row.get("title", ""), category=row.get("category", ""), stakes=stakes,
            status=_case_status([o.status for o in counted]),
            passed=sum(o.status == "pass" for o in counted), total=len(counted), outcomes=counted))
    return sorted(results, key=lambda r: (STAKES_ORDER.index(r.stakes), r.case))


def _share(outcomes: list[Outcome], check: str) -> list[int]:
    counted = [o for o in _worst_per_ref(o for o in outcomes if o.check == check)
               if o.status in ("pass", "fail", "not_read")]
    return [sum(o.status == "pass" for o in counted), len(counted)]


def _money(outcomes, check: str, phase: str | None = None) -> str:
    total = sum((o.amount for o in outcomes
                 if o.check == check and o.status == "fail" and (phase is None or o.phase == phase)),
                Decimal(0))
    return str(total.quantize(_CENT))


def _vat_difference(outcomes: list[Outcome]) -> str:
    """Each VAT box once, as the books end up: its after outcome if there is one, else its before."""
    final: dict[str, Outcome] = {}
    for o in outcomes:
        if o.check == "vat" and (o.ref not in final or o.phase == "after"):
            final[o.ref] = o
    total = sum((o.amount for o in final.values() if o.status == "fail"), Decimal(0))
    return str(total.quantize(_CENT))


def headline(outcomes: list[Outcome], case_results: list[CaseResult]) -> dict:
    by_stakes = {s: {status: 0 for status in PRIORITY} for s in STAKES_ORDER}
    for r in case_results:
        by_stakes[r.stakes][r.status] += 1
    return {
        "by_stakes": by_stakes,
        "entries_right": _share(outcomes, "entry"),
        "documents_right": _share(outcomes, "document"),
        "queries_asked": _share(outcomes, "query"),
        "tb_difference": {p: _money(outcomes, TB, p) for p in ("before", "after")},
        "vat_difference": _vat_difference(outcomes),
        "files_not_read": len({o.where for o in outcomes
                               if o.status == "not_read" and o.cause == "not read" and o.where}),
    }


def pass_k(results_by_repeat: list[list[CaseResult]]) -> dict[str, str]:
    statuses: dict[str, list[str]] = {}
    for repeat in results_by_repeat:
        statuses.update({r.case: [] for r in repeat if r.case not in statuses})
    for case, found in statuses.items():
        for repeat in results_by_repeat:
            match = next((r.status for r in repeat if r.case == case), "not_read")
            found.append(match)
    out = {}
    for case, found in statuses.items():
        if len(set(found)) == 1:
            out[case] = found[0]
        elif "pass" in found and "fail" in found:
            out[case] = "flaky"
        else:
            out[case] = _worst(found)
    return dict(sorted(out.items()))
