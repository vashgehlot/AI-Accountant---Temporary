"""People's verdicts on differences, kept by what the key row says (Outcome.identity), not by its number."""
from __future__ import annotations

import csv
import os
from dataclasses import asdict, dataclass, fields, replace
from datetime import date, datetime
from pathlib import Path

from .checks import Outcome

VERDICTS_CSV = Path(__file__).parent / "verdicts.csv"
KINDS = ("app wrong", "key wrong", "both acceptable", "runner wrong")


@dataclass(frozen=True)
class Verdict:
    identity: str
    ref: str
    verdict: str
    whats_right: str = ""
    who: str = ""
    date: str = ""
    got: str = ""


_FIELDS = [f.name for f in fields(Verdict)]


def load(path: Path = VERDICTS_CSV) -> dict[str, Verdict]:
    path = Path(path)
    if not path.exists():
        return {}
    with path.open(newline="", encoding="utf-8-sig") as fh:
        rows = [Verdict(**{k: (row.get(k) or "") for k in _FIELDS}) for row in csv.DictReader(fh)]
    return {v.identity: v for v in rows}


def save(v: dict[str, Verdict], path: Path = VERDICTS_CSV) -> None:
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=_FIELDS, lineterminator="\n")
        writer.writeheader()
        for item in sorted(v.values(), key=lambda x: x.ref):
            writer.writerow(asdict(item))
    os.replace(tmp, path)


def apply(outcomes: list[Outcome], v: dict[str, Verdict]) -> list[Outcome]:
    result = []
    for o in outcomes:
        verdict = v.get(o.identity) if o.identity else None
        if verdict is None:
            result.append(o)
            continue
        data = dict(o.data)
        data["verdict"] = {"verdict": verdict.verdict, "whats_right": verdict.whats_right, "who": verdict.who,
                           "date": verdict.date}
        status = o.status
        if verdict.verdict == "app wrong":
            data["known"] = True
        elif verdict.verdict in ("key wrong", "runner wrong"):
            status = "excluded"
        elif verdict.verdict == "both acceptable":
            if o.got == verdict.got:
                status = "pass"
                data["accepted"] = True
            else:
                data["verdict_lapsed"] = True
        result.append(replace(o, status=status, data=data))
    return result


def orphans(v: dict[str, Verdict], outcomes: list[Outcome]) -> list[Verdict]:
    seen = {o.identity for o in outcomes}
    return [x for x in v.values() if x.identity not in seen]


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value).strip()


def import_xlsx(xlsx: Path, path: Path = VERDICTS_CSV) -> int:
    import openpyxl

    wb = openpyxl.load_workbook(xlsx, read_only=True, data_only=True)
    try:
        ws = wb["Differences"] if "Differences" in wb.sheetnames else wb.active
        rows = ws.iter_rows(values_only=True)
        header = [_text(c) for c in next(rows, ())]
        col = {name: i for i, name in enumerate(header)}
        for need in ("Identity", "Verdict"):
            if need not in col:
                raise ValueError(f"the spreadsheet has no {need} column")

        def cell(row, name):
            i = col.get(name)
            return _text(row[i]) if i is not None and i < len(row) else ""

        found = []
        for number, row in enumerate(rows, start=2):
            raw = cell(row, "Verdict")
            if not raw:
                continue
            kind = raw.lower()
            if kind not in KINDS:
                raise ValueError(f"row {number}: unknown verdict {raw!r}; use one of {', '.join(KINDS)}")
            identity = cell(row, "Identity")
            if not identity:
                raise ValueError(f"row {number}: the verdict has no identity")
            found.append(Verdict(identity, cell(row, "ID"), kind, cell(row, "What's right"), cell(row, "Who"),
                                 cell(row, "Date"), cell(row, "App did")))
    finally:
        wb.close()
    current = load(path)
    for item in found:
        current[item.identity] = item
    save(current, path)
    return len(found)


def key_corrections(outcomes: list[Outcome]) -> list[dict]:
    """One entry per key row (identity): its "after" outcome when there is one, else the first."""
    chosen: dict[str, Outcome] = {}
    for o in outcomes:
        info = o.data.get("verdict")
        if not (info and info.get("verdict") == "key wrong"):
            continue
        key = o.identity or o.ref
        if key not in chosen or (o.phase == "after" and chosen[key].phase != "after"):
            chosen[key] = o
    return [{"ref": o.ref, "expected": o.expected, "got": o.got,
             "whats_right": o.data["verdict"].get("whats_right", ""), "who": o.data["verdict"].get("who", "")}
            for o in chosen.values()]
