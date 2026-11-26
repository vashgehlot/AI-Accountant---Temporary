"""What people read after a run: report.md, faults.csv, differences.xlsx and key-corrections.csv."""
from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from .cases import CaseResult
from .checks import STAKES_ORDER, Outcome
from .verdicts import key_corrections

UNREVIEWED = "The key is unreviewed: a difference may be the key's mistake."
NO_CASE = "No catalogue case"
FAULT_COLUMNS = ["identity", "ref", "check", "phase", "status", "cases", "stakes", "cause", "where", "expected",
                 "got", "amount", "verdict"]
XLSX_COLUMNS = ["ID", "Identity", "Cases", "Case title", "Stakes", "Check", "Where", "Key expects", "App did",
                "Cause", "Failed in runs", "Verdict", "What's right", "Who", "Date"]
CORRECTION_COLUMNS = ["ref", "expected", "got", "whats_right", "who"]


@dataclass
class RunSummary:
    run_name: str
    selection: str
    app: dict
    set: dict
    review: str
    calls: int
    replayed: int
    cost: Decimal
    cost_by_part: dict
    estimate: Decimal | None
    seconds: float
    units: list[dict]
    outcomes: list[Outcome]
    cases: list[CaseResult]
    headline: dict
    pass_k: dict | None = None
    changes: dict | None = None
    previous: str | None = None
    extra_questions: list[dict] = field(default_factory=list)
    orphans: list = field(default_factory=list)
    signed_off: bool = False
    unpriced: int = 0  # calls whose cost the provider never gave


def _atomic(path: Path, write) -> None:
    tmp = path.with_name(path.name + ".tmp")
    write(tmp)
    os.replace(tmp, path)


def _pounds(value) -> str:
    text = str(value)
    return f"-£{text[1:]}" if text.startswith("-") else f"£{text}"


def _dollars(value) -> str:
    return f"${Decimal(str(value)):.2f}"


def unpriced_note(n: int, what: str = "the cost shown") -> str:
    """Says that `n` calls had no cost, so `what` is a lower bound."""
    calls = "1 call" if n == 1 else f"{n} calls"
    return f"{calls} had no cost from the provider, so {what} is a lower bound"


def _kind(o: Outcome) -> str:
    return (o.data.get("verdict") or {}).get("verdict", "")


def _items(value) -> list[str]:
    if not value:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v) for v in value]
    return [str(value)]


def _dict_text(d: dict) -> str:
    return ", ".join(f"{k}: {v}" for k, v in d.items() if v not in (None, ""))


def _stakes_of(s: RunSummary) -> dict[str, CaseResult]:
    return {c.case: c for c in s.cases}


def _faults(s: RunSummary) -> list[Outcome]:
    return [o for o in s.outcomes if o.status == "fail"]


def _repeats(group: list[Outcome]) -> str:
    runs = sorted({int(o.data.get("repeat", 1)) for o in group})
    return ", ".join(str(r) for r in runs)


def _order(o: Outcome, s: RunSummary) -> tuple:
    cases = _stakes_of(s)
    stakes = min((cases[c].stakes for c in o.cases if c in cases), key=STAKES_ORDER.index, default=o.stakes)
    return (STAKES_ORDER.index(stakes) if stakes in STAKES_ORDER else len(STAKES_ORDER), o.ref, o.phase)


def _grouped(outcomes: list[Outcome], s: RunSummary) -> list[tuple[str, str, list[Outcome]]]:
    """(stakes, case heading, outcomes), in stakes order, with outcomes that have no case last in their level."""
    cases = _stakes_of(s)
    groups: dict[tuple[str, str], list[Outcome]] = {}
    seen: set[tuple] = set()
    for o in outcomes:
        for case in o.cases or (NO_CASE,):
            key = (o.identity or o.ref, o.check, o.phase, o.got, case)
            if key in seen:
                continue
            seen.add(key)
            stakes = cases[case].stakes if case in cases else o.stakes
            groups.setdefault((stakes, case), []).append(o)

    def sort_key(item):
        (stakes, case), _ = item
        return (STAKES_ORDER.index(stakes) if stakes in STAKES_ORDER else len(STAKES_ORDER), case == NO_CASE, case)

    return [(st, case, sorted(g, key=lambda o: (o.ref, o.phase))) for (st, case), g in sorted(groups.items(), key=sort_key)]


def _same_fault(o: Outcome) -> tuple:
    return (o.identity or o.ref, o.check, o.phase, o.got)


def _failed_in(s: RunSummary) -> dict[tuple, str]:
    """With repeats, the runs each fault (the same difference, the app doing the same) failed in; else nothing."""
    if not any(int(o.data.get("repeat", 1)) > 1 for o in s.outcomes):
        return {}
    runs: dict[tuple, set[int]] = {}
    for o in _faults(s):
        runs.setdefault(_same_fault(o), set()).add(int(o.data.get("repeat", 1)))
    return {k: ", ".join(str(r) for r in sorted(v)) for k, v in runs.items()}


def _fault_lines(o: Outcome, with_verdict: bool = True, failed_in: dict | None = None) -> list[str]:
    head = f"- `{o.ref}` ({o.check}, {o.phase})"
    if o.where:
        head += f" at {o.where}"
    lines = [head, f"  - Key expects: {o.expected}", f"  - App did: {o.got}"]
    if o.cause:
        lines.append(f"  - Cause: {o.cause}")
    if o.amount:
        lines.append(f"  - Amount: {_pounds(o.amount)}")
    if o.status == "fail" and _same_fault(o) in (failed_in or {}):
        lines.append(f"  - Failed in runs: {failed_in[_same_fault(o)]}")
    if o.data.get("known"):
        lines.append("  - Known fault")
    info = o.data.get("verdict")
    if with_verdict and info:
        lines.append(f"  - Verdict: {_verdict_text(info)}")
    return lines


def _verdict_text(info: dict) -> str:
    text = info.get("verdict", "")
    if info.get("whats_right"):
        text += f"; what's right: {info['whats_right']}"
    who = " ".join(x for x in (info.get("who"), info.get("date")) if x)
    return f"{text} ({who})" if who else text


def _case_heading(case: str, s: RunSummary) -> str:
    result = _stakes_of(s).get(case)
    return f"{case}: {result.title}" if result and result.title else case


def _fault_section(s: RunSummary) -> list[str]:
    faults = _faults(s)
    excluded = [o for o in s.outcomes if o.status == "excluded" and o.data.get("verdict")]
    accepted = [o for o in s.outcomes if o.data.get("accepted") and o.data.get("verdict")]
    if not (faults or excluded or accepted):
        return []
    out = ["## Faults by case", ""]
    last = None
    failed_in = _failed_in(s)
    for stakes, case, group in _grouped(faults, s):
        if stakes != last:
            out += [f"### {stakes.capitalize()}", ""]
            last = stakes
        out += [f"#### {_case_heading(case, s)}", ""]
        for o in group:
            out += _fault_lines(o, failed_in=failed_in)
        out.append("")
    for title, group in (("Left out by a verdict", excluded), ("Accepted by a verdict", accepted)):
        if not group:
            continue
        out += [f"### {title}", ""]
        for stakes, case, items in _grouped(group, s):
            out += [f"#### {_case_heading(case, s)}", ""]
            for o in items:
                out += _fault_lines(o)
            out.append("")
    return out


def _headline_section(s: RunSummary) -> list[str]:
    h = s.headline
    if not h:
        return []
    out = ["## Headline", "", "| Stakes | Passed | Failed | Not read | Not attempted | Can't compare |",
           "|---|---|---|---|---|---|"]
    for stakes in STAKES_ORDER:
        c = (h.get("by_stakes") or {}).get(stakes)
        if c is not None:
            out.append(f"| {stakes} | {c.get('pass', 0)} | {c.get('fail', 0)} | {c.get('not_read', 0)} | "
                       f"{c.get('not_attempted', 0)} | {c.get('cant_compare', 0)} |")
    out.append("")

    def share(label, key):
        if key in h:
            right, total = h[key]
            out.append(f"- {label}: {right} of {total}")

    share("Entries right", "entries_right")
    share("Documents right", "documents_right")
    share("Key's questions asked", "queries_asked")
    if "tb_difference" in h:
        tb = h["tb_difference"]
        out.append(f"- Trial balance difference: {_pounds(tb['before'])} before the replies, "
                   f"{_pounds(tb['after'])} after")
    if "vat_difference" in h:
        out.append(f"- VAT box differences: {_pounds(h['vat_difference'])}")
    if "files_not_read" in h:
        out.append(f"- Files not read: {h['files_not_read']}")
    return out + [""]


def _pass_k_section(s: RunSummary) -> list[str]:
    if not s.pass_k:
        return []
    titles = _stakes_of(s)
    out = ["## Pass^k", ""]
    for case, status in s.pass_k.items():
        title = titles[case].title if case in titles and titles[case].title else ""
        out.append(f"- {case}{': ' + title if title else ''}: {status}")
    flaky = [c for c, st in s.pass_k.items() if st == "flaky"]
    if flaky:
        out += ["", f"Flaky (right in some runs, wrong in others): {', '.join(flaky)}"]
    return out + [""]


def _changes_section(s: RunSummary) -> list[str]:
    if not s.changes or not any(s.changes.get(b) for b in ("new", "flipped", "fixed", "still")):
        return []
    out = [f"## Changes since {s.previous or 'the previous run'}", ""]
    for bucket, label in (("new", "New faults"), ("flipped", "Flipped (passed before, failing now)"),
                          ("fixed", "Fixed"), ("still", "Still failing")):
        items = s.changes.get(bucket) or []
        if items:
            out += [f"### {label}", ""] + [f"- `{o.ref}` ({o.check}) {o.where}".rstrip() for o in items] + [""]
    return out


def _case_list(s: RunSummary, status: str, title: str) -> list[str]:
    cases = [c for c in s.cases if c.status == status]
    if not cases:
        return []
    return [f"## {title}", ""] + [f"- {c.case}: {c.title} ({c.stakes})" for c in cases] + [""]


def _unit_lines(s: RunSummary, key: str, show) -> list[str]:
    out = []
    for u in s.units:
        for item in _items(u.get(key)):
            out.append(f"- {u.get('slug', '')}: {show(item)}")
    return out


def _sections(s: RunSummary) -> list[str]:
    lines: list[str] = [f"# {s.run_name}", ""]
    if not s.signed_off:
        lines += [f"> **{UNREVIEWED}**", ""]
    ran = [f"- Selection: {s.selection}"]
    for label, d in (("App", s.app), ("Set", s.set)):
        if d:
            ran.append(f"- {label}: {_dict_text(d)}")
    ran += [f"- Unit {u.get('slug') or '?'}: {u.get('status') or 'unknown'}" for u in s.units]
    ran.append(f"- Review: {s.review}")
    ran.append(f"- Replayed reads: {s.replayed} of {s.calls} calls" if s.replayed else "- Replayed reads: none")
    lines += ["## What was run", ""] + ran + [""]
    cost = [f"- Cost: {_dollars(s.cost)}" + (f" (estimate {_dollars(s.estimate)})" if s.estimate is not None else ""),
            f"- Calls: {s.calls}", f"- Time: {s.seconds:.0f} seconds"]
    if s.unpriced:
        cost.insert(1, f"- {unpriced_note(s.unpriced)}")
    cost += [f"- {part}: {_dollars(v)}" for part, v in s.cost_by_part.items()]
    lines += ["## Cost and time", ""] + cost + [""]
    lines += _headline_section(s) + _pass_k_section(s) + _changes_section(s) + _fault_section(s)
    lines += _case_list(s, "not_attempted", "Not attempted") + _case_list(s, "cant_compare", "Can't be compared")
    notes = [o for o in s.outcomes if o.data.get("presentation")]
    if notes:
        lines += ["## Presentation notes", ""] + [f"- `{o.ref}`: {o.data['presentation']}" for o in notes] + [""]
    if s.extra_questions:
        lines += ["## Questions the app asked that the key doesn't", ""]
        lines += [f"- {q if isinstance(q, str) else _dict_text(q)}" for q in s.extra_questions] + [""]
    unsent = _unit_lines(s, "replies_not_sent", str)
    if unsent:
        lines += ["## Replies not sent", ""] + unsent + [""]
    confirmed = _unit_lines(s, "offers_confirmed", str)
    if confirmed:
        lines += ["## Offers confirmed", ""] + confirmed + [""]
    files = _unit_lines(s, "not_read", str) + _unit_lines(s, "refusals", lambda r: f"refused: {r}")
    if files:
        lines += ["## Files not read and refusals", ""] + files + [""]
    chat = []
    for u in s.units:
        if u.get("chat_year") or u.get("app_year") or u.get("asked_back"):
            chat.append(f"- {u.get('slug', '')}: chat year {u.get('chat_year') or '-'}, "
                        f"app year {u.get('app_year') or '-'}")
            chat += [f"  - Asked back: {q}" for q in _items(u.get("asked_back"))]
    if chat:
        lines += ["## The chat", ""] + chat + [""]
    lapsed = [f"- `{v.ref}`: {v.verdict}, {v.whats_right}".rstrip(", ") for v in s.orphans]
    lapsed += [f"- `{o.ref}` ({o.check}): the app's answer changed since it was judged both acceptable"
               for o in s.outcomes if o.data.get("verdict_lapsed")]
    if lapsed:
        lines += ["## Verdicts that no longer match", ""] + lapsed + [""]
    return lines


def _write_faults_csv(path: Path, s: RunSummary) -> None:
    def write(tmp):
        with tmp.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh, lineterminator="\n")
            w.writerow(FAULT_COLUMNS)
            for o in _faults(s):
                w.writerow([o.identity, o.ref, o.check, o.phase, o.status, ";".join(o.cases), o.stakes, o.cause,
                            o.where, o.expected, o.got, o.amount, _kind(o)])
    _atomic(path, write)


def _write_xlsx(path: Path, s: RunSummary) -> None:
    import openpyxl
    from openpyxl.styles import Font

    by_id: dict[str, list[Outcome]] = {}
    for o in s.outcomes:
        if o.status == "fail" or (o.status == "excluded" and o.data.get("verdict")):
            by_id.setdefault(o.identity or o.ref, []).append(o)
    cases = _stakes_of(s)
    rows = []
    for ident, group in by_id.items():
        fails = [o for o in group if o.status == "fail"]
        first = next((o for o in fails if o.phase == "after"), (fails or group)[0])
        info = next((o.data["verdict"] for o in group if o.data.get("verdict")), {})
        titles = "; ".join(cases[c].title for c in first.cases if c in cases and cases[c].title)
        rows.append((_order(first, s), [first.ref, ident, ", ".join(first.cases), titles, first.stakes, first.check,
                                        first.where, first.expected, first.got, first.cause, _repeats(fails),
                                        info.get("verdict", ""), info.get("whats_right", ""), info.get("who", ""),
                                        info.get("date", "")]))
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Differences"
    ws.append(XLSX_COLUMNS)
    for _, row in sorted(rows, key=lambda r: r[0]):
        ws.append(row)
    ws.column_dimensions["B"].hidden = True
    ws.freeze_panes = "A2"
    if not s.signed_off:  # a sheet of its own, so `verdicts` still reads "Differences" from its first row
        readme = wb.create_sheet("Read me")
        readme["A1"] = UNREVIEWED
        readme["A1"].font = Font(bold=True)
        readme.column_dimensions["A"].width = len(UNREVIEWED) + 2
    _atomic(path, wb.save)


def _write_corrections(path: Path, s: RunSummary) -> None:
    def write(tmp):
        with tmp.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=CORRECTION_COLUMNS, lineterminator="\n")
            w.writeheader()
            w.writerows(key_corrections(s.outcomes))
    _atomic(path, write)


def write_all(run_dir: Path, s: RunSummary) -> None:
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    _atomic(run_dir / "report.md", lambda tmp: tmp.write_text("\n".join(_sections(s)).rstrip() + "\n",
                                                              encoding="utf-8"))
    _write_faults_csv(run_dir / "faults.csv", s)
    _write_xlsx(run_dir / "differences.xlsx", s)
    _write_corrections(run_dir / "key-corrections.csv", s)
