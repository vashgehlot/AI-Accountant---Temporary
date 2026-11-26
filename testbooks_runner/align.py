"""Lines the app's rows up with the key: which row came from which document or statement line."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

from .model import Key, money
from .runs import load_progress
from .setup import statement_account

_VAT_FILE = re.compile(r"^vat-(\d{4}-\d{2}-\d{2})-(\d{4}-\d{2}-\d{2})\.json$")
_NOT_READ = {"refused", "failed"}
_DATE_WINDOW = 3


@dataclass
class Snapshot:
    which: str
    scored_year: str
    ledgers: dict[str, dict] = field(default_factory=dict)
    posted: dict[str, dict] = field(default_factory=dict)
    vat: dict[tuple[str, str], dict] = field(default_factory=dict)
    invoices: list = field(default_factory=list)
    questions: list = field(default_factory=list)
    decisions: list = field(default_factory=list)
    reviews: list = field(default_factory=list)
    accounts: list = field(default_factory=list)
    chat: dict | None = None
    errors: dict[str, dict] = field(default_factory=dict)


def _read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def load_snapshot(unit_dir: Path, which: str) -> Snapshot:
    """Read raw/<which>/ as take_snapshot wrote it. A call that failed shows up in `errors`, not as data."""
    unit_dir = Path(unit_dir)
    folder = unit_dir / "raw" / which
    snap = Snapshot(which=which, scored_year=load_progress(unit_dir).app_year_start or "")
    if not folder.is_dir():
        return snap
    for path in sorted(folder.glob("*.json")):
        name = path.name[: -len(".json")]
        if name.endswith(".error"):
            snap.errors[name[: -len(".error")]] = _read(path)
        elif name.startswith("ledger-"):
            snap.ledgers[name[len("ledger-"):]] = _read(path)
        elif name.startswith("posted-"):
            snap.posted[name[len("posted-"):]] = _read(path)
        elif m := _VAT_FILE.match(path.name):
            snap.vat[(m.group(1), m.group(2))] = _read(path)
        elif name in ("invoices", "questions", "decisions", "reviews", "accounts"):
            setattr(snap, name, _read(path))
        elif name == "chat":
            snap.chat = _read(path)
    return snap


@dataclass(frozen=True)
class Group:
    journals: tuple[str, ...]
    docs: frozenset[str]
    lines: frozenset[str]
    deals: frozenset[str]
    phases: frozenset[str]
    paperless: bool


@dataclass
class Alignment:
    rows_by_doc: dict[str, list[dict]] = field(default_factory=dict)
    line_rows: dict[str, dict] = field(default_factory=dict)
    line_how: dict[str, str] = field(default_factory=dict)
    unpaired: list[dict] = field(default_factory=list)
    posted_by_row: dict[int, list[dict]] = field(default_factory=dict)
    groups: list[Group] = field(default_factory=list)
    not_read: set[str] = field(default_factory=set)
    unknown_files: list[str] = field(default_factory=list)
    row_docs: dict[int, str] = field(default_factory=dict)  # row id -> the document it was read from
    rows_by_id: dict[int, dict] = field(default_factory=dict)  # every row of every year
    upload_files: dict[int, str] = field(default_factory=dict)  # upload id -> file in the unit folder, else its name


def _ids(text: str | None) -> list[str]:
    return [p.strip() for p in (text or "").split(";") if p.strip()]


def _day(text) -> date | None:
    try:
        return date.fromisoformat(str(text)[:10])
    except ValueError:
        return None


def _signed(row: dict) -> Decimal:
    gross = money(str(row.get("gross") or "0"))
    return -gross if row.get("direction") == "out" else gross


def pair_lines(key_lines: list[dict], rows: list[dict], account_codes: dict[str, str | None]) -> tuple[dict, dict, list]:
    """Pair key statement lines with app rows one to one: (line_id -> row, line_id -> how, rows left over).

    A line's account maps to an app code through account_codes; only "statement" rows on that code take part.
    An account whose code is None (a processor's report, which the app reads without a bank account) takes
    whatever rows it is given. Three passes: same amount and date ("exact"), same amount within three days,
    nearest date first ("date"), same date and another amount ("amount").
    """
    def eligible(line: dict, row: dict) -> bool:
        code = account_codes.get(line["account"])
        if code is None:
            return True
        return row.get("document_type") == "statement" and row.get("bank_account") == code

    amounts = {ln["line_id"]: money(ln["amount"]) for ln in key_lines}
    days = {ln["line_id"]: _day(ln["date"]) for ln in key_lines}
    line_rows: dict[str, dict] = {}
    line_how: dict[str, str] = {}
    taken: set[int] = set()  # positions in `rows`

    def run(how: str, candidates) -> None:
        for _, li, ri in sorted(candidates):
            lid = key_lines[li]["line_id"]
            if lid in line_rows or ri in taken:
                continue
            line_rows[lid] = rows[ri]
            line_how[lid] = how
            taken.add(ri)

    def candidates(test):
        for li, ln in enumerate(key_lines):
            for ri, row in enumerate(rows):
                if ln["line_id"] in line_rows or ri in taken or not eligible(ln, row):
                    continue
                rank = test(ln["line_id"], row)
                if rank is not None:
                    yield (rank, li, ri)

    def exact(lid, row):
        return 0 if _signed(row) == amounts[lid] and _day(row.get("date")) == days[lid] else None

    def near(lid, row):
        d, rd = days[lid], _day(row.get("date"))
        if _signed(row) != amounts[lid] or d is None or rd is None:
            return None
        gap = abs((rd - d).days)
        return gap if gap <= _DATE_WINDOW else None

    def same_date(lid, row):
        if days[lid] is None or _day(row.get("date")) != days[lid]:
            return None
        return abs(_signed(row) - amounts[lid])

    run("exact", list(candidates(exact)))
    run("date", list(candidates(near)))
    run("amount", list(candidates(same_date)))
    left = [row for ri, row in enumerate(rows) if ri not in taken
            and any(eligible(ln, row) for ln in key_lines)]
    return line_rows, line_how, left


def groups_of(entries: list[dict]) -> list[Group]:
    """Join the journals that share a document or a statement line. A journal naming neither stands alone."""
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    order: list[str] = []
    refs: dict[str, tuple[set, set, set, set]] = {}
    for e in entries:
        j = e["journal_id"]
        if j not in parent:
            parent[j] = j
            order.append(j)
            refs[j] = (set(), set(), set(), set())
        docs, lines, deals, phases = refs[j]
        docs.update(_ids(e.get("doc_ids")))
        lines.update(_ids(e.get("line_ids")))
        deals.update(_ids(e.get("deal_id")))
        if e.get("phase"):
            phases.add(e["phase"])
    owner: dict[str, str] = {}
    for j in order:
        for tag, ids in (("d", refs[j][0]), ("l", refs[j][1])):
            for ref in ids:
                other = owner.setdefault(f"{tag}:{ref}", j)
                parent[find(j)] = find(other)
    members: dict[str, list[str]] = {}
    for j in order:
        members.setdefault(find(j), []).append(j)
    out = []
    for js in members.values():
        docs = frozenset().union(*(refs[j][0] for j in js))
        lines = frozenset().union(*(refs[j][1] for j in js))
        out.append(Group(journals=tuple(js), docs=docs, lines=lines,
                         deals=frozenset().union(*(refs[j][2] for j in js)),
                         phases=frozenset().union(*(refs[j][3] for j in js)),
                         paperless=not docs and not lines))
    return out


def in_books(row: dict) -> bool:
    """False for a row the app took out of the books: removed by a person, excluded or replaced by a decision, or
    dated before the client's first year (its amount is in the opening balances) without a person's Include tick.

    `include` on its own says nothing: the app sends it on every row, false unless a person ticked Include, and the
    tick only brings in a row that would otherwise be left out.
    """
    if row.get("removed") or row.get("excluded") or row.get("superseded_by"):
        return False
    return bool(row.get("include")) or not row.get("in_opening")


def _not_a_copy(row: dict) -> bool:
    """False for a row the app marked as a copy of another and doesn't book unless a person ticks Include: a line
    two overlapping statements both print (the app books it once, from the statement it read first), or a document
    read twice. Such a row is neither a statement line's own row nor made up."""
    return bool(row.get("include")) or row.get("copy_of") is None


def _all_rows(snap: Snapshot) -> list[dict]:
    rows = []
    for ledger in snap.ledgers.values():
        rows.extend(ledger.get("transactions") or [])
    return rows


def _all_uploads(snap: Snapshot) -> list[dict]:
    seen, out = set(), []
    for ledger in snap.ledgers.values():
        for up in ledger.get("uploads") or []:
            if up.get("id") not in seen:
                seen.add(up.get("id"))
                out.append(up)
    return out


def _split_file(docs: list[dict], rows: list[dict]) -> dict[str, list[dict]]:
    """Give each row of a multi-document file to the document with the same gross, else the nearest date."""
    out: dict[str, list[dict]] = {d["doc_id"]: [] for d in docs}
    for row in rows:
        gross = money(str(row.get("gross") or "0"))
        same = [d for d in docs if d.get("gross") and abs(money(d["gross"])) == gross]
        pool = same or docs
        rd = _day(row.get("date"))

        def gap(d):
            dd = _day(d.get("date"))
            return abs((rd - dd).days) if rd and dd else 10 ** 6
        out[min(pool, key=gap)["doc_id"]].append(row)
    return out


def align(key: Key, snap: Snapshot, uploads: dict[str, dict], profile: dict,
          bank_codes: dict[str, str]) -> Alignment:
    al = Alignment()
    all_rows = _all_rows(snap)
    al.rows_by_id = {r["id"]: r for r in all_rows}
    rows = [r for r in all_rows if in_books(r)]
    by_name: dict[str, int] = {}
    for up in _all_uploads(snap):
        by_name.setdefault(up.get("name"), up.get("id"))

    docs_by_file: dict[str, list[dict]] = {}
    for d in key.documents:
        docs_by_file.setdefault(d["file"], []).append(d)

    al.unknown_files = [f for f in uploads if f not in docs_by_file]

    file_upload: dict[str, int] = {}  # key file -> app upload id
    for f, docs in docs_by_file.items():
        entry = uploads.get(f)
        if entry is not None and entry.get("status") in _NOT_READ:
            al.not_read.update(d["doc_id"] for d in docs)
            continue
        # a file the runner never sent (a chat reply's attachment) is tied by its name
        uid = (entry or {}).get("upload_id")
        if uid is None:
            uid = by_name.get(Path(f).name)
        if entry is None and uid is None:
            al.not_read.update(d["doc_id"] for d in docs)
            continue
        if uid is not None:
            file_upload[f] = uid

    for up in _all_uploads(snap):
        if up.get("id") is not None and up.get("name"):
            al.upload_files[up["id"]] = up["name"]
    for f, entry in uploads.items():  # files the runner sent win over the app's own name
        if (entry or {}).get("upload_id") is not None:
            al.upload_files[entry["upload_id"]] = f
    for f, uid in file_upload.items():
        al.upload_files[uid] = f

    rows_of_upload: dict[int, list[dict]] = {}  # the rows a processor's lines may pair with
    for row in rows:
        if _not_a_copy(row):
            rows_of_upload.setdefault(row.get("upload_id"), []).append(row)

    every_row_of_upload: dict[int, list[dict]] = {}  # removed rows too: the checks read their decisions
    for row in all_rows:
        every_row_of_upload.setdefault(row.get("upload_id"), []).append(row)

    claimed: set[int] = set()  # row ids tied to a known document
    for f, uid in file_upload.items():
        file_rows = every_row_of_upload.get(uid, [])
        docs = docs_by_file[f]
        split = ({docs[0]["doc_id"]: list(file_rows)} if len(docs) == 1 else _split_file(docs, file_rows))
        for doc_id, got in split.items():
            al.rows_by_doc.setdefault(doc_id, []).extend(got)
            for r in got:
                al.row_docs[r["id"]] = doc_id
                claimed.add(r["id"])

    # statement lines
    lines_by_account: dict[str, list[dict]] = {}
    for ln in key.lines:
        lines_by_account.setdefault(ln["account"], []).append(ln)
    bank_lines = [ln for a, lns in lines_by_account.items() if a in bank_codes for ln in lns]
    paired_ids: set[int] = set()
    statement_left: dict[int, dict] = {}

    pool = [r for r in rows if r.get("document_type") == "statement" and _not_a_copy(r)]
    lr, lh, left = pair_lines(bank_lines, pool, bank_codes)
    al.line_rows.update(lr)
    al.line_how.update(lh)
    paired_ids.update(r["id"] for r in lr.values())
    statement_left.update({r["id"]: r for r in pool})

    for account, lns in lines_by_account.items():
        if account in bank_codes:
            continue
        own = [r for f, uid in file_upload.items()
               if any(statement_account(d["doc_id"], profile) == account for d in docs_by_file[f])
               for r in rows_of_upload.get(uid, [])]
        lr, lh, _ = pair_lines(lns, own, {account: None})
        al.line_rows.update(lr)
        al.line_how.update(lh)
        paired_ids.update(r["id"] for r in lr.values())
        statement_left.update({r["id"]: r for r in own})

    # processor statement files' rows count as statement rows even with no key lines
    for f, uid in file_upload.items():
        for d in docs_by_file[f]:
            acct = statement_account(d["doc_id"], profile)
            if acct is not None and acct not in bank_codes:
                statement_left.update({r["id"]: r for r in rows_of_upload.get(uid, [])})

    seen: set[int] = set()
    for r in rows:
        rid = r["id"]
        if rid in seen or not _not_a_copy(r):
            continue
        stray = rid not in claimed
        if (rid in statement_left and rid not in paired_ids) or (stray and rid not in paired_ids):
            seen.add(rid)
            al.unpaired.append(r)

    for entry in (snap.posted or {}).values():
        for j in entry.get("journal") or []:
            al.posted_by_row.setdefault(int(j["transaction"]), []).append(j)

    al.groups = groups_of(key.entries)
    return al


def _cp(text) -> str | None:
    text = (text or "").strip().lower()
    return f"cp:{text}" if text else None


def subjects(row_ids: list[int], al: Alignment, key: Key) -> set[str]:
    """Doc IDs, deal IDs, and "cp:" plus each lower-cased counterparty behind these rows.

    The counterparties are the key's, from the entries the lining up reaches (through a row's document or
    statement line). A row tied to no document and no line brings its own counterparty.
    """
    row_line = {r["id"]: lid for lid, r in al.line_rows.items()}
    out: set[str] = set()
    for rid in row_ids:
        row = al.rows_by_id.get(rid)
        docs, lines = set(), set()
        if rid in al.row_docs:
            docs.add(al.row_docs[rid])
        if rid in row_line:
            lines.add(row_line[rid])
        out.update(docs)
        for e in key.entries:
            if set(_ids(e.get("doc_ids"))) & docs or set(_ids(e.get("line_ids"))) & lines:
                out.update(_ids(e.get("deal_id")))
                if cp := _cp(e.get("counterparty")):
                    out.add(cp)
        for ln in key.lines:
            if ln["line_id"] in lines:
                out.update(_ids(ln.get("deal_id")))
        if not docs and not lines and row and (cp := _cp(row.get("counterparty"))):
            out.add(cp)
    return out


def query_for(question: dict, key: Key, al: Alignment) -> str | None:
    """The key query this app question matches.

    A shared document or deal ID wins. Otherwise a shared counterparty counts only when one of the question's
    rows also has the amount or the date of an entry on the query's deals.
    """
    row_ids = question.get("row_ids") or []
    if not row_ids:
        return None
    subs = subjects(row_ids, al, key)
    rows = [al.rows_by_id[r] for r in row_ids if r in al.rows_by_id]
    grosses = {money(str(r.get("gross") or "0")) for r in rows}
    days = {_day(r.get("date")) for r in rows} - {None}
    direct, by_cp = None, None
    for q in key.queries:
        about = set(_ids(q.get("about")))
        if direct is None and about & subs:
            direct = q["query_id"]
        if by_cp is not None:
            continue
        entries = [e for e in key.entries if about & ({e.get("deal_id")} | set(_ids(e.get("doc_ids"))))]
        cps = {cp for e in entries if (cp := _cp(e.get("counterparty")))}
        if not cps & subs:
            continue
        for e in entries:
            amounts = {money(e.get("debit")), money(e.get("credit"))} - {Decimal("0")}
            if amounts & grosses or _day(e.get("date")) in days:
                by_cp = q["query_id"]
                break
    return direct or by_cp
