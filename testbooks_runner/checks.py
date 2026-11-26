"""Scoring checks: each returns Outcomes that say whether the app's books match the key."""
from __future__ import annotations

import hashlib
import json
import posixpath
import re
from dataclasses import dataclass, field, replace
from datetime import date
from decimal import Decimal
from itertools import product

from .align import Alignment, Group, Snapshot, _day, in_books, query_for
from .books import load_catalogue
from .mapping import ChartRow, Unmapped, VatRow, app_code, choices
from .model import Key, Unit, money
from .runs import Progress

STAKES_ORDER = ("tax", "accounts", "presentation", "process")
TB = "tb"  # the trial balance check's name, in its outcomes, refs and identities, and where the headline sums it
CAUSES = ("misread", "booked wrong", "changed by the review", "changed by the chat", "not read",
          "the app never asked", "chat couldn't reach the year", "made up or read twice", "unexplained")

_ZERO = Decimal(0)
_STATEMENT_SPAN = re.compile(r"(\d{8})-(\d{8})$")


@dataclass(frozen=True)
class Outcome:
    check: str
    ref: str
    status: str  # pass, fail, not_attempted, cant_compare, not_read, explained or excluded
    cases: tuple[str, ...]
    stakes: str  # tax, accounts, presentation or process
    phase: str  # before or after
    expected: str = ""
    got: str = ""
    cause: str = ""
    where: str = ""
    amount: Decimal = Decimal(0)
    identity: str = ""
    data: dict = field(default_factory=dict)


def identity(check: str, unit: Unit, *content) -> str:
    """A stable ID for what a key row says, so a verdict survives the key being renumbered."""
    text = json.dumps([check, unit.name, str(unit.period.end), *content])
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def booked(rows: list[dict], al: Alignment) -> bool:
    """True when any row's posted lines aren't all zero."""
    for row in rows:
        for j in al.posted_by_row.get(row["id"], []):
            if money(str(j.get("debit") or "0")) != 0 or money(str(j.get("credit") or "0")) != 0:
                return True
    return False


def _ids(text) -> list[str]:
    return [p.strip() for p in (text or "").split(";") if p.strip()]


def _catalogue(unit: Unit) -> dict[str, dict]:
    return load_catalogue(unit.folder.parent.parent)


def _stakes(case_ids: tuple[str, ...], catalogue: dict[str, dict]) -> str:
    found = [(catalogue.get(c) or {}).get("stakes", "").strip().lower() for c in case_ids]
    found = [s for s in found if s in STAKES_ORDER]
    return min(found, key=STAKES_ORDER.index) if found else "accounts"


def _gross(rows: list[dict]) -> Decimal:
    return sum((abs(money(str(r.get("gross") or "0"))) for r in rows), _ZERO)


def _fmt(value: Decimal) -> str:
    return f"{value:.2f}"


def _is_statement(doc_id: str, profile: dict) -> bool:
    first = doc_id.split("-")[0]
    return any(a["id"] == first for a in profile.get("accounts", []))


def _applied(snap: Snapshot) -> dict:
    return {d.get("id"): d for d in snap.decisions if d.get("status") == "applied"}


def _changed_by(rows: list[dict], snap: Snapshot) -> str:
    applied = _applied(snap)
    chat = review = False
    for row in rows:
        for did in row.get("decision_ids") or []:
            d = applied.get(did)
            if d is None:
                continue
            if d.get("review_id"):
                review = True
            elif d.get("trigger") == "chat" and str(d.get("actor") or "").startswith("agent:"):
                chat = True
    return "changed by the review" if review else "changed by the chat" if chat else ""


def _reply_sent(file: str, key: Key, progress: Progress) -> bool:
    # One sent reply in the folder is enough: the driver attaches every non-reply file in an answer folder to
    # each sent reply from that folder, so the file reached the app and is fair to judge on its rows. The key
    # doesn't yet tie each file to its own query.
    folder = posixpath.dirname(file)
    for q in key.queries:
        af = q.get("answer_file") or ""
        if af and (af == file or posixpath.dirname(af) == folder):
            if (progress.replies.get(q["query_id"]) or {}).get("sent"):
                return True
    return False


def check_documents(unit: Unit, key: Key, snap: Snapshot, al: Alignment, profile: dict, phase: str,
                    progress: Progress) -> list[Outcome]:
    catalogue = _catalogue(unit)
    out: list[Outcome] = []
    for d in key.documents:
        doc_id, file = d["doc_id"], d["file"]
        if _is_statement(doc_id, profile):
            continue  # judged by its lines
        answer = file.startswith("answers/")
        if answer and phase != "after":
            continue
        cases = tuple(_ids(d.get("cases")))
        wants_book = d.get("treatment") == "book"
        printed = money(d.get("gross") or "0")
        rows = al.rows_by_doc.get(doc_id, [])
        live = [r for r in rows if in_books(r)]
        got_gross = _gross(live)
        is_booked = booked(live, al)

        def make(status, cause="", expected="", got="", amount=_ZERO):
            return Outcome(
                check="document", ref=f"{unit.ref}:document:{doc_id}", status=status, cases=cases,
                stakes=_stakes(cases, catalogue), phase=phase, expected=expected, got=got, cause=cause,
                where=file, amount=amount,
                identity=identity("document", unit, file, d.get("kind"), d.get("issuer"), d.get("number"),
                                  d.get("date"), d.get("gross")))

        expected = f"booked, gross {_fmt(abs(printed))}" if wants_book else "not booked"
        if answer and not _reply_sent(file, key, progress):   # never sent, so in no upload: not a file left unread
            out.append(make("not_read", "the app never asked", expected, "reply never sent"))
            continue
        if doc_id in al.not_read:
            out.append(make("not_read", "not read", expected, "not read"))
            continue
        got = f"booked, gross {_fmt(got_gross)}" if is_booked else "not booked"
        if not wants_book:
            if not is_booked:
                out.append(make("pass", expected=expected, got=got))
                continue
            cause = _changed_by(rows, snap) or "booked wrong"
            out.append(make("fail", cause, expected, got, got_gross))
            continue
        if is_booked and got_gross == abs(printed):
            out.append(make("pass", expected=expected, got=got))
            continue
        if not live:
            cause, amount = "misread", abs(printed)
        elif is_booked:  # booked, but the figures differ from the paper
            cause, amount = "misread", abs(got_gross - abs(printed))
        else:
            cause, amount = _changed_by(rows, snap) or "booked wrong", abs(printed)
        out.append(make("fail", cause, expected, got, amount))
    return out


def _statement_file(line: dict, key: Key) -> tuple[str, str]:
    """(doc_id, file) of the statement document a key line came from, or ("", "")."""
    account = line["account"]
    day = line.get("date") or ""
    docs = [d for d in key.documents if d["doc_id"].split("-")[0] == account]
    for d in docs:
        m = _STATEMENT_SPAN.search(d["doc_id"])
        if m:
            try:
                lo = date(int(m[1][:4]), int(m[1][4:6]), int(m[1][6:])).isoformat()
                hi = date(int(m[2][:4]), int(m[2][4:6]), int(m[2][6:])).isoformat()
            except ValueError:
                continue
            if lo <= day <= hi:
                return d["doc_id"], d["file"]
    return (docs[0]["doc_id"], docs[0]["file"]) if docs else ("", "")


def check_lines(unit: Unit, key: Key, al: Alignment, phase: str = "before") -> list[Outcome]:
    catalogue = _catalogue(unit)
    out: list[Outcome] = []
    for ln in key.lines:
        lid = ln["line_id"]
        cases = tuple(_ids(ln.get("cases")))
        doc_id, file = _statement_file(ln, key)
        amount = money(ln.get("amount") or "0")
        expected = f"{ln['date']} {_fmt(amount)}"
        how = al.line_how.get(lid)
        row = al.line_rows.get(lid)
        status, cause, got, diff = "fail", "misread", "not read", _ZERO
        if how == "exact":
            status, cause, got = "pass", "", expected
        elif row is not None:
            signed = money(str(row.get("gross") or "0"))
            if row.get("direction") == "out":
                signed = -signed
            got = f"{str(row.get('date') or '')[:10]} {_fmt(signed)}"
            diff = abs(signed - amount)
        elif doc_id in al.not_read:
            status, cause = "not_read", "not read"
        out.append(Outcome(
            check="line", ref=f"{unit.ref}:line:{lid}", status=status, cases=cases,
            stakes=_stakes(cases, catalogue), phase=phase, expected=expected, got=got, cause=cause,
            where=f"{file} {lid}".strip(), amount=diff,
            identity=identity("line", unit, ln["account"], ln["date"], ln.get("description"), ln["amount"])))
    return out


def check_extra_rows(unit: Unit, al: Alignment, phase: str = "before") -> list[Outcome]:
    """The rows with nothing in the key to pair with, dated inside the period: a row of another year (a statement
    that runs past the year end, or next year's papers) is no fault of these books."""
    out = []
    for row in al.unpaired:
        day = _day(row.get("date"))
        if day is not None and not unit.period.start <= day <= unit.period.end:
            continue
        gross = money(str(row.get("gross") or "0"))
        desc = row.get("description") or row.get("counterparty") or ""
        file = al.upload_files.get(row.get("upload_id"), "")
        out.append(Outcome(
            check="extra", ref=f"{unit.ref}:extra:{row['id']}", status="fail", cases=(), stakes="accounts",
            phase=phase, expected="no such row", got=f"{str(row.get('date') or '')[:10]} {_fmt(gross)} {desc}".strip(),
            cause="made up or read twice", where=file, amount=abs(gross),
            identity=identity("extra", unit, file, str(row.get("date") or "")[:10], _fmt(gross), desc),
            data={"row_id": row["id"]}))
    return out


_VAT_ACCOUNTS = {"2200", "2201", "2202"}
_PAPER_PHASES = ("books", "answers")
_MAX_COMBINATIONS = 64
_CENT = Decimal("0.01")


def _group_stakes(cases: tuple[str, ...], lines: list[dict], catalogue: dict[str, dict]) -> str:
    """The highest stakes among the cases' catalogue stakes and the key lines' own; "" when none gives one."""
    found = [(catalogue.get(c) or {}).get("stakes", "") for c in cases] + [e.get("stakes") or "" for e in lines]
    found = [f.strip().lower() for f in found if f.strip().lower() in STAKES_ORDER]
    return min(found, key=STAKES_ORDER.index) if found else ""


def _presentation(lines: list[dict], chosen: list[str], chart: dict[str, ChartRow]) -> str:
    """Notes where the app's chart can't draw what the key draws: two key accounts sharing one app account, or
    an account the app draws as another (the chart's `also`, like a transfer booked to the other account)."""
    drawn: dict[str, set[str]] = {}
    for e, code in zip(lines, chosen):
        row = chart[e["account"]]
        if code == row.app_code or code in row.also:  # not a code the key itself allows through also_ok
            drawn.setdefault(code, set()).add(e["account"])
    notes = []
    for code, accounts in sorted(drawn.items()):
        names = sorted(accounts)
        if len(names) > 1:
            notes.append(f"key {', '.join(names[:-1])} and {names[-1]} are one app account, {code}")
        elif code != chart[names[0]].app_code:
            notes.append(f"key {names[0]} is drawn as app {code}")
    return "; ".join(notes)


def _journals(key: Key) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for e in key.entries:
        out.setdefault(e["journal_id"], []).append(e)
    return out


def _journal_phase(lines: list[dict]) -> str:
    return next((e["phase"] for e in lines if e.get("phase")), "")


def paperless_journals(key: Key) -> dict[str, list[dict]]:
    """Journal ID to its lines, for `books` and `answers` journals naming no document and no statement line."""
    return {j: lines for j, lines in _journals(key).items()
            if _journal_phase(lines) in _PAPER_PHASES
            and not any(_ids(e.get("doc_ids")) or _ids(e.get("line_ids")) for e in lines)}


def is_vat_transfer(lines: list[dict]) -> bool:
    return bool(lines) and all(e["account"] in _VAT_ACCOUNTS for e in lines)


def app_nets(rows: list[dict], al: Alignment) -> dict[str, Decimal]:
    """App code to debit less credit over the rows' posted lines."""
    nets: dict[str, Decimal] = {}
    for row in rows:
        for j in al.posted_by_row.get(row["id"], []):
            code = str(j.get("code"))
            nets[code] = nets.get(code, _ZERO) + money(str(j.get("debit") or "0")) - money(str(j.get("credit") or "0"))
    return nets


def _deltas(key_nets: dict[str, Decimal], app: dict[str, Decimal]) -> dict[str, Decimal]:
    return {c: app.get(c, _ZERO) - key_nets.get(c, _ZERO) for c in set(app) | set(key_nets)}


def _best_combo(key_lines: list[tuple[str, Decimal, tuple[str, ...]]], app: dict[str, Decimal],
                tolerance: Decimal) -> tuple[bool, dict[str, Decimal], list[str]]:
    """nets_match, also saying which code each key line was matched to."""
    options = [tuple(dict.fromkeys((primary, *opts))) for primary, _, opts in key_lines]
    amounts = [amt for _, amt, _ in key_lines]
    total = 1
    for o in options:
        total *= len(o)
    if total <= _MAX_COMBINATIONS:
        best = None
        for combo in product(*options):
            key_nets: dict[str, Decimal] = {}
            for code, amt in zip(combo, amounts):
                key_nets[code] = key_nets.get(code, _ZERO) + amt
            deltas = _deltas(key_nets, app)
            # fewest non-primary codes breaks a tie, so the primary codes win when several fit equally
            score = (sum(abs(d) for d in deltas.values()),
                     sum(opts.index(c) for c, opts in zip(combo, options)))
            if best is None or score < best[0]:
                best = (score, deltas, list(combo))
        _, deltas, chosen = best
    else:
        residual = dict(app)
        chosen = []
        for opts, amt in zip(options, amounts):
            pick = min(opts, key=lambda c: abs(residual.get(c, _ZERO) - amt) - abs(residual.get(c, _ZERO)))
            residual[pick] = residual.get(pick, _ZERO) - amt
            chosen.append(pick)
        deltas = dict(residual)
    deltas = {c: d for c, d in deltas.items() if d != 0}
    return all(abs(d) <= tolerance for d in deltas.values()), deltas, chosen


def nets_match(key_lines: list[tuple[str, Decimal, tuple[str, ...]]], app: dict[str, Decimal],
               tolerance: Decimal) -> tuple[bool, dict[str, Decimal]]:
    """Try the choices for each key line (all combinations up to 64, then greedily); app less key per code."""
    matched, deltas, _ = _best_combo(key_lines, app, tolerance)
    return matched, deltas


def app_vat_label(row: dict) -> str:
    if row.get("reverse_charge"):
        return "reverse charge"
    if money(str(row.get("vat_posted") or "0")) > 0:
        return f"VAT {row['vat_posted']}"
    if money(str(row.get("vat_not_reclaimed") or "0")) > 0:
        return "VAT not reclaimed: " + str(row.get("vat_not_reclaimed_why") or "")
    return "no VAT"


def _key_line_text(e: dict) -> str:
    debit, credit = money(e.get("debit")), money(e.get("credit"))
    text = f"{e['account']} {_fmt(debit)} Dr" if debit else f"{e['account']} {_fmt(credit)} Cr"
    also = _ids(e.get("also_ok"))
    return text + (f" (or {', '.join(also)})" if also else "")


def _app_text(nets: dict[str, Decimal]) -> str:
    parts = [f"{c} {_fmt(abs(n))} {'Dr' if n > 0 else 'Cr'}" for c, n in sorted(nets.items()) if n != 0]
    return "; ".join(parts) or "nothing posted"


def _with_vat(text: str, labels: list[str]) -> str:
    labels = list(dict.fromkeys(labels))
    return f"{text}; VAT: {', '.join(labels)}" if labels else text


def _misread(live_doc_rows: list[dict], docs: dict[str, dict], line_rows: dict[str, dict],
             line_how: dict[str, str], line_ids) -> bool:
    """A live row differs from what its document prints, or a statement row isn't an exact match of its line.

    A document's gross is compared as the sum of its live rows (the app may split one document).
    """
    by_doc: dict[str, list[dict]] = {}
    for row in live_doc_rows:
        by_doc.setdefault(row["_doc"], []).append(row)
    for doc_id, rows in by_doc.items():
        d = docs.get(doc_id)
        if d is None:
            continue
        if d.get("gross") and _gross(rows) != abs(money(d["gross"])):
            return True
        if d.get("date") and any(str(r.get("date") or "")[:10] != d["date"][:10] for r in rows):
            return True
        if (d.get("vat") or "").strip() and \
                sum((money(str(r.get("vat") or "0")) for r in rows), _ZERO) != money(d["vat"]):
            return True
    return any(line_how.get(i) not in (None, "exact") for i in line_ids if i in line_rows)


def _removed_line_rows(g: Group, key: Key, al: Alignment) -> list[dict]:
    """Rows the app took out of the books that match a statement line of the group (same file, signed
    amount, date within three days, as the pairing does)."""
    out: dict[int, dict] = {}
    by_line = {ln["line_id"]: ln for ln in key.lines}
    for lid in sorted(g.lines):
        ln = by_line.get(lid)
        if ln is None:
            continue
        _, file = _statement_file(ln, key)
        amount, day = money(ln.get("amount") or "0"), _day(ln.get("date"))
        for row in al.rows_by_id.values():
            if in_books(row) or al.upload_files.get(row.get("upload_id")) != file:
                continue
            signed = money(str(row.get("gross") or "0"))
            if row.get("direction") == "out":
                signed = -signed
            rd = _day(row.get("date"))
            if signed == amount and day and rd and abs((rd - day).days) <= 3:
                out[row["id"]] = row
    return list(out.values())


def _group_query(g: Group, key: Key) -> str | None:
    for q in key.queries:
        if set(_ids(q.get("about"))) & (g.deals | g.docs):
            return q["query_id"]
    return None


def _entry_outcome(unit: Unit, key: Key, g: Group, journals: list[str], by_journal: dict[str, list[dict]],
                   snap: Snapshot, al: Alignment, chart: dict[str, ChartRow], vat_table: dict[str, VatRow],
                   phase: str, progress: Progress, catalogue: dict[str, dict]) -> Outcome:
    lines = [e for j in journals for e in by_journal[j]]
    cases = tuple(sorted({c for e in lines for c in _ids(e.get("cases"))}))
    # one ref for the group in both phases: its first books journal (an answers journal can sort before it)
    books = sorted(j for j in g.journals if _journal_phase(by_journal[j]) == "books")
    ref = f"{unit.ref}:entry:{(books or journals)[0]}"
    ident = identity("entry", unit, sorted((e["date"], e["account"], e.get("debit") or "", e.get("credit") or "",
                                            e.get("counterparty") or "") for e in lines))
    docs = {d["doc_id"]: d for d in key.documents}
    where = ", ".join(sorted({docs[i]["file"] for i in g.docs if i in docs})) or ", ".join(journals)
    vat_labels = [vat_table[e["vat_code"]].label if e.get("vat_code") in vat_table else e["vat_code"]
                  for e in lines if e.get("vat_code")]
    dates = sorted({e["date"] for e in lines})
    expected = "; ".join(_key_line_text(e) for e in lines)
    stakes = _group_stakes(cases, lines, catalogue)
    make = lambda **kw: Outcome(check="entry", ref=ref, cases=cases, phase=phase, where=where,  # noqa: E731
                                identity=ident, **kw)
    try:
        key_lines = [(app_code(chart, e["account"]), money(e.get("debit")) - money(e.get("credit")),
                      choices(chart, e["account"], e.get("also_ok") or "")) for e in lines]
    except Unmapped as miss:
        return make(status="cant_compare", stakes=stakes or "accounts", expected=_with_vat(expected, vat_labels),
                    got=f"no app account for key account {miss.args[0]}", data={"dates": dates})

    rows: dict[int, dict] = {}
    for i in sorted(g.docs):
        for r in al.rows_by_doc.get(i, []):
            rows[r["id"]] = dict(r, _doc=i)
    for i in sorted(g.lines):
        if i in al.line_rows:
            rows.setdefault(al.line_rows[i]["id"], al.line_rows[i])
    for r in _removed_line_rows(g, key, al):
        rows.setdefault(r["id"], r)
    rows_all = list(rows.values())
    live = [r for r in rows_all if in_books(r)]
    app = app_nets(live, al)
    worked_out = any(r.get("vat") is None and money(str(r.get("vat_posted") or "0")) != 0 for r in live)
    matched, deltas, chosen = _best_combo(key_lines, app, _CENT if worked_out else _ZERO)
    got = _with_vat(_app_text(app), [app_vat_label(r) for r in live if booked([r], al)])
    expected = _with_vat(expected, vat_labels)
    data = {"deltas": {c: _fmt(d) for c, d in sorted(deltas.items())}, "dates": dates}
    if matched:
        if note := _presentation(lines, chosen, chart):
            data["presentation"] = note
        return make(status="pass", stakes=stakes or "accounts", expected=expected, got=got, data=data)

    stakes = stakes or ("tax" if any(c in ("2200", "2201") for c in deltas) else "accounts")
    line_docs = {_statement_file(ln, key)[0] for ln in key.lines if ln["line_id"] in g.lines}
    if (g.docs | line_docs) & al.not_read:
        cause = "not read"
    elif _misread([r for r in live if "_doc" in r], docs, al.line_rows, al.line_how, g.lines):
        cause = "misread"
    elif changed := _changed_by(rows_all, snap):
        cause = changed
    else:
        cause = "booked wrong"
        query = _group_query(g, key) if phase == "after" else None
        if query is not None:
            if not (progress.replies.get(query) or {}).get("sent"):
                cause = "the app never asked"
            elif progress.chat_year != progress.app_year_start:
                cause = "chat couldn't reach the year"
    amount = (sum(abs(d) for d in deltas.values()) / 2).quantize(_CENT)
    status = "not_read" if cause == "not read" else "fail"
    return make(status=status, stakes=stakes, expected=expected, got=got, cause=cause, amount=amount, data=data)


def check_entries(unit: Unit, key: Key, snap: Snapshot, al: Alignment, chart: dict[str, ChartRow],
                  vat_table: dict[str, VatRow], phase: str, progress: Progress) -> list[Outcome]:
    catalogue = _catalogue(unit)
    by_journal = _journals(key)
    out: list[Outcome] = []
    for g in al.groups:
        if g.paperless:
            continue
        if phase == "after":
            if "answers" not in g.phases:
                continue
            wanted = _PAPER_PHASES
        else:
            wanted = ("books",)
        journals = sorted(j for j in g.journals if _journal_phase(by_journal[j]) in wanted)
        if journals:
            out.append(_entry_outcome(unit, key, g, journals, by_journal, snap, al, chart, vat_table, phase,
                                      progress, catalogue))
    return out


def not_attempted(unit: Unit, key: Key) -> list[Outcome]:
    """The journals the app can't make: the accountant's own adjustments, and year-end work."""
    catalogue = _catalogue(unit)
    paperless = paperless_journals(key)
    out: list[Outcome] = []
    for j, lines in sorted(_journals(key).items()):
        jphase = _journal_phase(lines)
        if j in paperless:
            phase = "before" if jphase == "books" else "after"
        elif jphase == "year_end":
            phase = "after"
        else:
            continue
        cases = tuple(sorted({c for e in lines for c in _ids(e.get("cases"))}))
        out.append(Outcome(
            check="entry", ref=f"{unit.ref}:entry:{j}", status="not_attempted", cases=cases,
            stakes=_stakes(cases, catalogue), phase=phase,
            expected="; ".join(_key_line_text(e) for e in lines), got="not attempted", where=j,
            identity=identity("entry", unit, sorted((e["date"], e["account"], e.get("debit") or "",
                                                     e.get("credit") or "", e.get("counterparty") or "")
                                                    for e in lines))))
    return out


# ---- period-level checks: trial balance, opening, VAT, unpaid, queries ----

_PENNY = Decimal("0.01")
_POUND = Decimal(1)
_VAT_CODES = ("2200", "2201", "2202")
_NOT_PASS = ("fail", "not_read", "cant_compare")


def _paper_phases(snap: Snapshot) -> tuple[str, ...]:
    return ("books", "answers") if snap.which == "after" else ("books",)


def _paperless_nets(key: Key, chart: dict[str, ChartRow], phases: tuple[str, ...]) -> dict[str, Decimal]:
    """App code to debit less credit over the paperless journals of these phases."""
    nets: dict[str, Decimal] = {}
    for lines in paperless_journals(key).values():
        if _journal_phase(lines) not in phases:
            continue
        for e in lines:
            try:
                code = app_code(chart, e["account"])
            except Unmapped:
                continue
            nets[code] = nets.get(code, _ZERO) + money(e.get("debit")) - money(e.get("credit"))
    return nets


def _explained_deltas(entry_outcomes: list[Outcome], phase: str) -> dict[str, Decimal]:
    """App code to the sum of the entry faults' deltas (app less key) of this phase."""
    out: dict[str, Decimal] = {}
    for o in entry_outcomes:
        if o.phase != phase or o.status not in _NOT_PASS:
            continue
        for code, text in (o.data.get("deltas") or {}).items():
            out[code] = out.get(code, _ZERO) + money(text)
    return out


def _app_tb(snap: Snapshot, field_name: str = "lines") -> dict[str, Decimal] | None:
    posted = snap.posted.get(snap.scored_year)
    if posted is None:
        return None
    nets: dict[str, Decimal] = {}
    for ln in posted.get(field_name) or []:
        code = str(ln.get("code"))
        nets[code] = nets.get(code, _ZERO) + money(str(ln.get("debit") or "0")) - money(str(ln.get("credit") or "0"))
    return nets


def _posted_missing(snap: Snapshot) -> str:
    err = snap.errors.get(f"posted-{snap.scored_year}")
    return f"the app's trial balance came back as an error: {err.get('message') or err.get('code')}" \
        if err else "no trial balance in the snapshot"


def _key_balances(rows: list[dict], chart: dict[str, ChartRow], value) -> tuple[dict[str, Decimal], list[str]]:
    """App code to the key's signed balance, and the key accounts the chart table can't map."""
    nets: dict[str, Decimal] = {}
    unmapped: list[str] = []
    for r in rows:
        try:
            code = app_code(chart, r["account"])
        except Unmapped:
            unmapped.append(r["account"])
            continue
        nets[code] = nets.get(code, _ZERO) + value(r)
    return nets, unmapped


def check_trial_balance(unit: Unit, key: Key, snap: Snapshot, chart: dict[str, ChartRow],
                        entry_outcomes: list[Outcome], phase: str) -> list[Outcome]:
    """Each account's balance against the key's, less the journals the app can't make; a difference that an
    entry fault already explains is `explained`, not a fault of its own."""
    if phase == "after":
        def value(r):
            return money(r.get("final")) - money(r.get("year_end"))
    else:
        def value(r):
            return money(r.get("before_answers"))
    key_nets, unmapped = _key_balances(key.trial_balance, chart, value)
    out: list[Outcome] = []

    def make(code, status, expected="", got="", cause="", amount=_ZERO, raw=None):
        return Outcome(
            check=TB, ref=f"{unit.ref}:{TB}:{code}", status=status, cases=(),
            stakes="tax" if code in _VAT_CODES else "accounts", phase=phase, expected=expected, got=got,
            cause=cause, where=f"trial-balance.csv {code}", amount=amount,
            identity=identity(TB, unit, phase, code, _fmt(key_nets.get(code, _ZERO))),
            data={} if raw is None else {"raw": _fmt(raw)})

    for account in unmapped:
        out.append(make(account, "cant_compare", got=f"no app account for key account {account}"))
    app = _app_tb(snap)
    if app is None:
        reason = _posted_missing(snap)
        return out + [make(code, "cant_compare", got=reason) for code in sorted(key_nets)]
    for code, net in _paperless_nets(key, chart, ("books", "answers") if phase == "after" else ("books",)).items():
        key_nets[code] = key_nets.get(code, _ZERO) - net
    explained = _explained_deltas(entry_outcomes, phase)
    for code in sorted(set(key_nets) | {c for c, n in app.items() if n != 0}):
        want, got = key_nets.get(code, _ZERO), app.get(code, _ZERO)
        diff = got - want
        if abs(diff) <= _PENNY:
            out.append(make(code, "pass", _fmt(want), _fmt(got)))
        elif abs(diff - explained.get(code, _ZERO)) <= _PENNY:
            out.append(make(code, "explained", _fmt(want), _fmt(got), amount=abs(diff), raw=diff))
        else:
            # amount is what the entry faults leave unexplained; the signed raw difference is in data["raw"]
            out.append(make(code, "fail", _fmt(want), _fmt(got), "unexplained",
                            abs(diff - explained.get(code, _ZERO)), raw=diff))
    return out


def check_opening(unit: Unit, key: Key, snap: Snapshot, chart: dict[str, ChartRow]) -> list[Outcome]:
    """The opening balances once, before the replies, account by account."""
    key_nets, unmapped = _key_balances(key.opening, chart, lambda r: money(r.get("debit")) - money(r.get("credit")))
    out: list[Outcome] = []

    def make(code, status, expected="", got="", cause="", amount=_ZERO):
        return Outcome(
            check="opening", ref=f"{unit.ref}:opening:{code}", status=status, cases=(), stakes="accounts",
            phase="before", expected=expected, got=got, cause=cause, where=f"opening-balances.csv {code}",
            amount=amount, identity=identity("opening", unit, code, _fmt(key_nets.get(code, _ZERO))))

    for account in unmapped:
        out.append(make(account, "cant_compare", got=f"no app account for key account {account}"))
    app = _app_tb(snap, "opening")
    if app is None:
        reason = _posted_missing(snap)
        return out + [make(code, "cant_compare", got=reason) for code in sorted(key_nets)]
    for code in sorted(set(key_nets) | {c for c, n in app.items() if n != 0}):
        want, got = key_nets.get(code, _ZERO), app.get(code, _ZERO)
        if abs(got - want) <= _PENNY:
            out.append(make(code, "pass", _fmt(want), _fmt(got)))
        else:
            out.append(make(code, "fail", _fmt(want), _fmt(got), "unexplained", abs(got - want)))
    return out


def _vat_adjusted(key: Key, snap: Snapshot, start: str, end: str, boxes: dict[str, Decimal]) -> dict[str, Decimal]:
    """The key's boxes less the paperless journals dated in the quarter (relief on box 4, a sales-VAT credit on
    box 1), with boxes 3 and 5 worked out again. The transfers into 2202 change no box."""
    boxes = dict(boxes)
    phases = _paper_phases(snap)
    for lines in paperless_journals(key).values():
        if _journal_phase(lines) not in phases or is_vat_transfer(lines):
            continue
        for e in lines:
            if not start <= (e.get("date") or "") <= end:
                continue
            if e["account"] == "2201":
                boxes["box4"] -= money(e.get("debit"))
            elif e["account"] == "2200":
                boxes["box1"] -= money(e.get("credit"))
    boxes["box3"] = boxes["box1"] + boxes["box2"]
    boxes["box5"] = boxes["box3"] - boxes["box4"]
    return boxes


def check_vat(unit: Unit, key: Key, snap: Snapshot, entry_outcomes: list[Outcome]) -> list[Outcome]:
    """Each VAT return box of each quarter wholly inside the period; boxes 1 to 5 to 1p, 6 to 9 to a pound."""
    out: list[Outcome] = []
    phase = snap.which
    faulty = [o for o in entry_outcomes if o.phase == phase and o.status in _NOT_PASS and o.data.get("dates")]
    for q in key.vat_returns:
        start, end = q["period_start"], q["period_end"]
        base = {f"box{i}": money(q.get(f"box{i}")) for i in range(1, 10)}
        inside = unit.period.start.isoformat() <= start and end <= unit.period.end.isoformat()
        figures = snap.vat.get((start, end))
        problem = ""
        if not inside:
            problem = "the quarter isn't wholly inside the books"
        elif figures is None:
            err = snap.errors.get(f"vat-{start}-{end}")
            problem = (f"the app's VAT figures came back as an error: {err.get('message') or err.get('code')}"
                       if err else "no VAT figures in the snapshot")
        want = base if problem else _vat_adjusted(key, snap, start, end, base)
        in_quarter = any(start <= d <= end for o in faulty for d in o.data["dates"])
        for i in range(1, 10):
            box = f"box{i}"
            tolerance = _PENNY if i <= 5 else _POUND
            make = lambda **kw: Outcome(  # noqa: E731
                check="vat", ref=f"{unit.ref}:vat:{start}:{end}:{box}", cases=(), stakes="tax", phase=phase,
                where=f"vat-returns.csv {start} to {end} {box}",
                identity=identity("vat", unit, start, end, box, q.get(box) or ""), **kw)
            if problem:
                out.append(make(status="cant_compare", expected=_fmt(want[box]), got=problem))
                continue
            got = money(str(figures.get(box) or "0"))
            # the app's box 5 is signed (a repayment is negative); the key's follows HMRC and is absolute
            diff = abs(abs(got) - abs(want[box])) if box == "box5" else abs(got - want[box])
            if diff <= tolerance:
                out.append(make(status="pass", expected=_fmt(want[box]), got=_fmt(got)))
            elif in_quarter:
                out.append(make(status="explained", expected=_fmt(want[box]), got=_fmt(got), amount=diff))
            else:
                out.append(make(status="fail", expected=_fmt(want[box]), got=_fmt(got), cause="unexplained",
                                amount=diff))
    return out


def _norm_number(text) -> str:
    return re.sub(r"\s+", "", str(text or "")).upper()


def _write_offs(key: Key, snap: Snapshot) -> list[tuple[str, Decimal]]:
    """(counterparty lower-cased, amount) of each paperless journal line that credits Debtors."""
    phases = _paper_phases(snap)
    out = []
    for lines in paperless_journals(key).values():
        if _journal_phase(lines) not in phases or is_vat_transfer(lines):
            continue
        for e in lines:
            amount = money(e.get("credit")) - money(e.get("debit"))
            if e["account"] == "1100" and amount > 0:
                out.append(((e.get("counterparty") or "").strip().lower(), amount))
    return out


def _owed(inv: dict) -> Decimal:
    """What the app says was owed on the invoice at the year's end; from an app that doesn't say, what is owed now."""
    return money(str(inv.get("owed_at_year_end", inv.get("owed")) or "0"))


def check_unpaid(unit: Unit, key: Key, snap: Snapshot, sent_next_year: bool) -> list[Outcome]:
    """What is still owed at the period's end, key against the app's invoices, one to one."""
    phase = snap.which
    end = unit.period.end.isoformat()
    write_offs = _write_offs(key, snap)
    out: list[Outcome] = []
    for kind, rows in (("sale", key.debtors), ("purchase", key.creditors)):
        side = "debtor" if kind == "sale" else "creditor"
        dates = sorted({r["as_at"] for r in rows if r["as_at"] <= end})
        owed_rows = [r for r in rows if dates and r["as_at"] == dates[-1] and money(r.get("owed")) > 0]
        invoices = [i for i in snap.invoices if i.get("kind") == kind and _owed(i) > 0]
        if kind == "sale":
            for who, amount in write_offs:
                for inv in invoices:
                    if (inv.get("counterparty") or "").strip().lower() == who and \
                            _owed(inv) == amount:
                        invoices.remove(inv)
                        break
        pairs: list[tuple[dict, dict]] = []
        for r in list(owed_rows):
            n = _norm_number(r.get("number"))
            hit = next((i for i in invoices if n and _norm_number(i.get("number")) == n), None)
            if hit is not None:
                pairs.append((r, hit))
                owed_rows.remove(r)
                invoices.remove(hit)
        for r in list(owed_rows):
            who = (r.get("counterparty") or "").strip().lower()
            hit = next((i for i in invoices if (i.get("counterparty") or "").strip().lower() == who
                        and money(str(i.get("total") or "0")) == money(r.get("gross"))), None)
            if hit is not None:
                pairs.append((r, hit))
                owed_rows.remove(r)
                invoices.remove(hit)

        def make(who, number, ident, **kw):
            return Outcome(check="unpaid", ref=f"{unit.ref}:unpaid:{side}:{who}:{number}", cases=(), stakes="accounts",
                           phase=phase, where=("debtors.csv" if kind == "sale" else "creditors.csv"),
                           identity=identity("unpaid", unit, kind, *ident), **kw)

        for r, inv in pairs:
            want, got = money(r.get("owed")), _owed(inv)
            ok = abs(want - got) <= _PENNY
            out.append(make(r["counterparty"], r["number"], (r["counterparty"], r["number"], r["date"], r["gross"]),
                            status="pass" if ok else "fail", expected=f"owed {_fmt(want)}", got=f"owed {_fmt(got)}",
                            cause="" if ok else "unexplained", amount=_ZERO if ok else abs(want - got)))
        for r in owed_rows:
            out.append(make(r["counterparty"], r["number"], (r["counterparty"], r["number"], r["date"], r["gross"]),
                            status="fail", expected=f"owed {_fmt(money(r.get('owed')))}", got="not owed",
                            cause="unexplained", amount=money(r.get("owed"))))
        for inv in invoices:
            owed = _owed(inv)
            out.append(make(inv.get("counterparty") or "", inv.get("number") or "",
                            ("app", inv.get("counterparty") or "", _norm_number(inv.get("number")),
                             str(inv.get("date") or "")[:10], _fmt(money(str(inv.get("total") or "0")))),
                            status="fail", expected="not owed", got=f"owed {_fmt(owed)}", cause="unexplained",
                            amount=owed))
    if sent_next_year:
        out = [replace(o, status="cant_compare", cause="",
                       got=f"{o.got} (the chat was sent next year's papers)") for o in out]
    return out


def _app_questions(snap: Snapshot) -> list[dict]:
    qs = list(snap.questions or [])
    for review in snap.reviews or []:
        qs.extend(review.get("questions") or [])
    return qs


def check_queries(unit: Unit, key: Key, snap: Snapshot, al: Alignment, progress: Progress,
                  earlier: list[tuple[Snapshot, Alignment]] = ()) -> list[Outcome]:
    """Whether the app asked each of the key's questions, scored once, on `snap` (the final snapshot).

    Asked means a matching question in the question list or a review's in `snap` or an `earlier` snapshot (each
    lined up with its own alignment), a question the chat asked back, or a reply the runner sent, which it sends only
    under a question the app asked. The app lists only open and waiting questions, so a question the reply resolved
    is gone from the after snapshot.
    """
    asked: set[str] = set()
    for s, a in [(snap, al), *earlier]:
        asked |= {qid for q in _app_questions(s) if (qid := query_for(q, key, a)) is not None}
    back = [q for rec in progress.replies.values() for q in rec.get("asked_back") or []]
    asked |= {qid for q in back if (qid := query_for(q, key, al)) is not None}
    asked |= {qid for qid, rec in progress.replies.items() if (rec or {}).get("sent")}
    out = []
    for q in key.queries:
        about = set(_ids(q.get("about")))
        cases = tuple(sorted({c for e in key.entries
                              if about & ({e.get("deal_id")} | set(_ids(e.get("doc_ids"))))
                              for c in _ids(e.get("cases"))}))
        stakes = (q.get("stakes") or "").strip().lower()
        ok = q["query_id"] in asked
        out.append(Outcome(
            check="query", ref=f"{unit.ref}:query:{q['query_id']}", status="pass" if ok else "fail", cases=cases,
            stakes=stakes if stakes in STAKES_ORDER else "accounts", phase=snap.which,
            expected=q.get("question") or "", got="asked" if ok else "never asked",
            cause="" if ok else "the app never asked", where=q.get("answer_file") or "queries.csv",
            identity=identity("query", unit, q.get("question") or "")))
    return out


def extra_questions(snap: Snapshot, al: Alignment, key: Key,
                    earlier: list[tuple[Snapshot, Alignment]] = ()) -> list[dict]:
    """The app's questions, in `snap` or an `earlier` snapshot, that match none of the key's queries in any snapshot
    they are in, each once (as `snap` has it, if it does), kept for a verdict."""
    found: dict = {}  # question id (or the question itself, with none) -> [question, matched a query]
    for s, a in [(snap, al), *earlier]:
        for q in _app_questions(s):
            k = q.get("id") if q.get("id") is not None else id(q)
            matched = query_for(q, key, a) is not None
            if k in found:
                found[k][1] = found[k][1] or matched
            else:
                found[k] = [q, matched]
    return [q for q, matched in found.values() if not matched]
