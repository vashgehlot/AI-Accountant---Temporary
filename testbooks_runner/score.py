"""Score a saved run: align each unit's snapshots, run every check, apply verdicts and write the report.

Nothing here calls the app, the relay or a model, so a run can be scored again after a corrected key, new
verdicts or a runner fix.
"""
from __future__ import annotations

import json
from dataclasses import asdict, replace
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from . import cases, checks, compare, report, verdicts
from .align import align, load_snapshot
from .books import load_catalogue, load_key, load_profile, signed_off
from .checks import Outcome
from .mapping import load_chart, load_vat
from .model import Period, Unit
from .report import RunSummary
from .runs import RunDir, load_progress, previous_run
from .verdicts import VERDICTS_CSV

_NOT_READ = ("refused", "failed")


def _plain(value):
    if isinstance(value, (set, frozenset)):
        return sorted(value, key=str)
    return str(value)  # Decimal, date and anything else the checks left in `data`


def _write_results(unit_dir: Path, outcomes: list[Outcome], extra: list[dict]) -> None:
    data = {"outcomes": [asdict(o) for o in outcomes], "extra_questions": extra}
    # a round trip through json turns Decimal into a string and a tuple into a list
    text = json.dumps(data, indent=2, ensure_ascii=False, default=_plain)
    RunDir(Path(unit_dir)).write_json("results.json", json.loads(text))


def load_results(unit_dir: Path) -> tuple[list[Outcome], list[dict]]:
    path = Path(unit_dir) / "results.json"
    if not path.is_file():
        return [], []
    raw = json.loads(path.read_text(encoding="utf-8"))
    outcomes = []
    for o in raw.get("outcomes") or []:
        o = dict(o)
        o["cases"] = tuple(o.get("cases") or ())
        o["amount"] = Decimal(str(o.get("amount") or "0"))
        o["data"] = dict(o.get("data") or {})
        outcomes.append(Outcome(**o))
    return outcomes, list(raw.get("extra_questions") or [])


def score_unit(unit: Unit, set_dir: Path, unit_dir: Path, chart, vat_table, catalogue,
               sent_next_year: bool) -> tuple[list[Outcome], list[dict]]:
    """Every check on a unit's saved snapshots; writes unit_dir/results.json.

    `set_dir` and `catalogue` are accepted for the caller's convenience: the checks find the catalogue through
    `unit.folder`, which `score_run` builds under `set_dir`.
    """
    unit_dir = Path(unit_dir)
    key = load_key(unit.key_dir)
    profile = load_profile(unit.folder)
    progress = load_progress(unit_dir)
    # "after" counts only once the runner finished writing it
    phases = ["before"] + (["after"] if progress.after_done and (unit_dir / "raw" / "after").is_dir() else [])
    snaps = {p: load_snapshot(unit_dir, p) for p in phases}
    aligned = {p: align(key, snaps[p], progress.uploads, profile, progress.bank_codes) for p in phases}

    out: list[Outcome] = []
    entries: dict[str, list[Outcome]] = {}
    for p in phases:
        snap, al = snaps[p], aligned[p]
        out += checks.check_documents(unit, key, snap, al, profile, p, progress)
        out += checks.check_extra_rows(unit, al, p)
        entries[p] = checks.check_entries(unit, key, snap, al, chart, vat_table, p, progress)
        out += entries[p]
        out += checks.check_trial_balance(unit, key, snap, chart, entries[p], p)
    out += checks.check_lines(unit, key, aligned["before"], "before")
    out += checks.check_opening(unit, key, snaps["before"], chart)
    out += checks.not_attempted(unit, key)
    final = phases[-1]  # the key's VAT returns, debtors and creditors describe the final books
    out += checks.check_vat(unit, key, snaps[final], entries[final])
    out += checks.check_unpaid(unit, key, snaps[final], sent_next_year)
    # a question counts wherever it was seen: the one a reply resolves is gone from the after snapshot
    earlier = [(snaps[p], aligned[p]) for p in phases[:-1]]
    out += checks.check_queries(unit, key, snaps[final], aligned[final], progress, earlier)
    extra = checks.extra_questions(snaps[final], aligned[final], key, earlier)

    out = [replace(o, data={**o.data, "repeat": unit.repeat}) for o in out]
    _write_results(unit_dir, out, extra)
    return out, extra


def _unit_from(entry: dict, set_dir: Path) -> Unit:
    kind = entry["kind"]
    folder = Path(set_dir) / ("packs" if kind == "pack" else "clients") / entry["name"]
    period = Period(date.fromisoformat(entry["period_start"]), date.fromisoformat(entry["period_end"]))
    return Unit(entry["name"], kind, folder, period, int(entry.get("repeat") or 1))


def _jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _unpriced(calls: list[dict], costs: list[dict]) -> int:
    priced = {row.get("seq") for row in costs if row.get("cost") is not None}
    return sum(1 for c in calls if c.get("generation_id") and not c.get("replayed") and c.get("seq") not in priced)


def unpriced_calls(run: RunDir) -> int:
    """Calls the provider answered (each carries a generation id) whose cost never came back from its lookup, so
    the run's cost is a lower bound. A replayed call cost nothing."""
    return _unpriced(_jsonl(run.path / "relay" / "calls.jsonl"), _jsonl(run.path / "relay" / "costs.jsonl"))


def _cost(run: RunDir, relay_totals: dict | None) -> tuple[Decimal, int, int, dict, int]:
    """(cost, calls, replayed calls, cost by part, calls with no cost)."""
    if relay_totals is not None:
        by_part = {k: Decimal(str(v)) for k, v in (relay_totals.get("by_part") or {}).items()}
        return (Decimal(str(relay_totals.get("cost") or "0")), int(relay_totals.get("calls") or 0),
                int(relay_totals.get("replayed") or 0), by_part, int(relay_totals.get("unpriced") or 0))
    calls = _jsonl(run.path / "relay" / "calls.jsonl")
    costs = _jsonl(run.path / "relay" / "costs.jsonl")
    part_of = {c.get("seq"): c.get("part") or "reader" for c in calls}
    total, by_part = Decimal(0), {}
    for row in costs:
        if row.get("cost") is None:
            continue
        value = Decimal(str(row["cost"]))
        total += value
        part = part_of.get(row.get("seq"), "reader")
        by_part[part] = by_part.get(part, Decimal(0)) + value
    return total, len(calls), sum(1 for c in calls if c.get("replayed")), by_part, _unpriced(calls, costs)


def _seconds(info: dict) -> float:
    start, end = info.get("started"), info.get("finished")
    if start is None or end is None:
        return 0.0
    try:
        if isinstance(start, (int, float)) and isinstance(end, (int, float)):
            return float(end) - float(start)
        return (datetime.fromisoformat(str(end)) - datetime.fromisoformat(str(start))).total_seconds()
    except ValueError:
        return 0.0


def _offer_text(item: dict) -> str:
    """One answer the runner confirmed for the client: the question, what was confirmed, and any refusal."""
    answer = item.get("answer") or {}
    what = ("; ".join(f"{l.get('account')} £{l.get('amount')}" for l in answer.get("lines") or [])
            if answer.get("kind") == "split" else f"write off on {answer.get('date') or 'the default date'}")
    return f"{item.get('question_id')}: {what}" + (f" (refused: {item['refused']})" if item.get("refused") else "")


def _question_text(q) -> str:
    if isinstance(q, dict):
        return str(q.get("text") or q.get("question") or q.get("title") or q)
    return str(q)


def _unit_summary(entry: dict, unit_dir: Path) -> dict:
    progress = load_progress(unit_dir)
    uploads = progress.uploads or {}
    return {
        "slug": entry.get("slug", ""), "status": entry.get("status", ""),
        "chat_year": progress.chat_year, "app_year": progress.app_year_start,
        "refusals": [{"file": f, "code": (u.get("error") or {}).get("code"),
                      "message": (u.get("error") or {}).get("message")}
                     for f, u in uploads.items() if u.get("status") == "refused"],
        "not_read": [f for f, u in uploads.items() if u.get("status") in _NOT_READ],
        "replies_not_sent": [qid for qid, r in progress.replies.items() if not r.get("sent")],
        "asked_back": [_question_text(q) for r in progress.replies.values() for q in r.get("asked_back") or []],
        "offers_confirmed": [_offer_text(c) for r in progress.replies.values() for c in r.get("confirmed") or []],
    }


def _previous_outcomes(prev: RunDir, v: dict) -> list[Outcome]:
    found: list[Outcome] = []
    for entry in (prev.read_json("run.json", {}) or {}).get("units") or []:
        found += load_results(prev.path / "units" / entry.get("slug", ""))[0]
    return verdicts.apply(found, v)


def score_run(run: RunDir, set_dir: Path, *, verdicts_path: Path = VERDICTS_CSV, against: RunDir | None = None,
              relay_totals: dict | None = None) -> RunSummary:
    set_dir = Path(set_dir)
    info = run.read_json("run.json", {}) or {}
    chart, vat_table, catalogue = load_chart(), load_vat(), load_catalogue(set_dir)

    outcomes: list[Outcome] = []
    extra_all: list[dict] = []
    scored: list[Unit] = []
    summaries: list[dict] = []
    for entry in info.get("units") or []:
        slug = entry.get("slug", "") if isinstance(entry, dict) else ""
        summary = {"slug": slug, "status": entry.get("status", "") if isinstance(entry, dict) else ""}
        summaries.append(summary)
        try:  # a renamed pack, an unreadable key or progress file, or a bad entry must not stop the others
            unit = _unit_from(entry, set_dir)
            unit_dir = run.path / "units" / (slug or unit.slug)
            summary.update(_unit_summary(entry, unit_dir))
            if not (unit_dir / "raw" / "before").is_dir():
                continue
            next_year = bool(entry.get("with_next_year", info.get("with_next_year")))
            got, extra = score_unit(unit, set_dir, unit_dir, chart, vat_table, catalogue, next_year)
        except Exception as exc:
            summary["run_status"] = summary["status"]
            summary["status"] = f"not scored: {type(exc).__name__}: {exc}"
            continue
        outcomes += got
        extra_all += [{**q, "unit": slug or unit.slug} if isinstance(q, dict) else q for q in extra]
        scored.append(unit)

    v = verdicts.load(verdicts_path)
    outcomes = verdicts.apply(outcomes, v)
    prefixes = tuple(u.ref + ":" for u in scored)
    lapsed = [x for x in verdicts.orphans(v, outcomes) if x.ref.startswith(prefixes)] if prefixes else []

    results = cases.roll_up(outcomes, catalogue)
    head = cases.headline(outcomes, results)
    repeats = sorted({u.repeat for u in scored})
    pass_k = None
    if any(r > 1 for r in repeats):
        pass_k = cases.pass_k([cases.roll_up([o for o in outcomes if o.data.get("repeat") == r], catalogue)
                               for r in repeats])

    selection = info.get("selection") or ""
    prev = against or previous_run(run, selection, root=run.path.parent)
    before = _previous_outcomes(prev, v) if prev is not None else []
    if not before:  # an earlier run that was never scored has nothing to compare with
        prev = None
    changes = compare.compare(outcomes, before) if prev is not None else None

    cost, calls, replayed, by_part, unpriced = _cost(run, relay_totals)
    estimate = info.get("estimate")
    is_signed = signed_off(set_dir)
    summary = RunSummary(
        run_name=run.name, selection=selection, app=dict(info.get("app") or {}),
        set={**(info.get("set") or {}), "signed_off": is_signed}, review=info.get("review") or "off",
        calls=calls, replayed=replayed, cost=cost, cost_by_part=by_part, unpriced=unpriced,
        estimate=Decimal(str(estimate)) if estimate not in (None, "") else None, seconds=_seconds(info),
        units=summaries, outcomes=outcomes, cases=results, headline=head, pass_k=pass_k, changes=changes,
        previous=prev.name if prev is not None else None, extra_questions=extra_all, orphans=lapsed,
        signed_off=is_signed)
    report.write_all(run.path, summary)
    info = run.read_json("run.json", {}) or {}
    info["scored"] = datetime.now().isoformat(timespec="seconds")
    run.write_json("run.json", info)
    return summary
