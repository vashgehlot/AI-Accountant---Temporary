"""What a run will read, what it should cost and how long it should take, and the measurements that improve that."""
from __future__ import annotations

import json
import math
import os
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import httpx

from . import driver, selection
from .model import Key, Unit
from .runs import RUNS, load_progress

MEASUREMENTS = RUNS / "measurements.json"
PRICE_URL = "https://openrouter.ai/api/v1/models"

_KINDS = {
    "image": {"jpg", "jpeg", "png", "heic", "heif", "webp", "gif", "tif", "tiff"},
    "sheet": {"csv", "tsv", "xlsx", "xls", "ofx", "qif"},
    "text": {"txt", "eml", "docx"},
}

# Tokens per call and seconds, for a kind never measured.
ROUGH = {
    "pdf": {"in": 7000, "out": 3000, "seconds": 45},
    "image": {"in": 5000, "out": 3000, "seconds": 45},
    "sheet": {"in": 9000, "out": 8000, "seconds": 90},
    "text": {"in": 4000, "out": 2000, "seconds": 30},
    "other": {"in": 6000, "out": 3000, "seconds": 45},
    "review": {"in": 40000, "out": 5000, "seconds": 120},
    "chat": {"in": 40000, "out": 5000, "seconds": 120},
}


def file_kind(path: Path) -> str:
    ext = Path(path).suffix.lower().lstrip(".")
    if ext == "pdf":
        return "pdf"
    for kind, exts in _KINDS.items():
        if ext in exts:
            return kind
    return "other"


def model_price(model: str, *, get=httpx.get) -> dict | None:
    """OpenRouter's listed price per token for the model, or None if it can't be had."""
    try:
        response = get(PRICE_URL, timeout=20)
        response.raise_for_status()
        for entry in response.json()["data"]:
            if entry.get("id") == model:
                pricing = entry["pricing"]
                return {"in": Decimal(str(pricing["prompt"])), "out": Decimal(str(pricing["completion"]))}
    except Exception:
        return None
    return None


@dataclass
class Workload:
    unit: Unit
    files: dict[str, int]  # every read, by kind, attachments included
    batches: list[dict[str, int]]  # inbox batches only: an attachment is read inside its chat turn
    replies: int


def workload(unit: Unit, key: Key, with_next_year: bool) -> Workload:
    batches, files = [], Counter()
    for _day, paths in selection.files_to_send(unit, key, with_next_year):
        kinds = Counter(file_kind(p) for p in paths)
        batches.append(dict(kinds))
        files.update(kinds)
    replies = 0
    for query in key.queries:
        if not query.get("answer_file"):
            continue
        replies += 1
        answer = unit.folder / query["answer_file"]
        if answer.parent.is_dir():
            files.update(file_kind(p) for p in driver.reply_files(answer))
    return Workload(unit, dict(files), batches, replies)


@dataclass
class Estimate:
    cost: Decimal | None
    seconds: float
    rough: bool
    basis: str
    reviews: int = 0
    any_measured: bool = False


def _dec(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


_SAME = object()


def estimate(workloads, *, measurements: dict | None, price: dict | None, pool: int, review: str,
             parallel: int = 5, agent_price=_SAME) -> Estimate:
    """`price` is the reader model's listed price; `agent_price` is the listed price of the model the app's review
    and chat run on (OPENROUTER_CHAT_MODEL when it is set), the reader's unless given. None means not known."""
    measured = measurements or {}
    state = {"rough": False, "unknown": False, "measured": False}

    def figures(name: str) -> tuple[Decimal | None, float]:
        """(cost per call or turn, seconds) from the measurements, else from ROUGH and the price."""
        agent = name in ("review", "chat")
        if agent:
            found = measured.get(name)
        else:
            found = (measured.get("kinds") or {}).get(name)
        if found:
            state["measured"] = True
            return _dec(found["cost"]), float(found["seconds"])
        state["rough"] = True
        rough = ROUGH[name]
        listed = agent_price if agent and agent_price is not _SAME else price
        if listed is None:
            return None, float(rough["seconds"])
        return rough["in"] * _dec(listed["in"]) + rough["out"] * _dec(listed["out"]), float(rough["seconds"])

    reviewing = review != "off"
    cost, reviews, loads = Decimal(0), 0, []

    def add(count: int, name: str) -> float:
        nonlocal cost
        per_cost, seconds = figures(name)
        if per_cost is None:
            state["unknown"] = True
        else:
            cost += per_cost * count
        return seconds

    for wl in workloads:
        for kind, count in wl.files.items():
            add(count, kind)
        seconds = 0.0
        for batch in wl.batches:
            if not batch:
                continue
            slowest = max(figures(kind)[1] for kind in batch)
            seconds += math.ceil(sum(batch.values()) / parallel) * slowest
            if reviewing:
                reviews += 1
                seconds += figures("review")[1]
        if reviewing and wl.batches:
            add(sum(1 for b in wl.batches if b), "review")
        if wl.replies:
            add(wl.replies, "chat")
            seconds += wl.replies * figures("chat")[1]
        loads.append(seconds)
    copies = [0.0] * max(1, pool)
    for seconds in sorted(loads, reverse=True):
        copies[copies.index(min(copies))] += seconds
    basis = ("rough: some figures are guesses by kind of file" if state["rough"]
             else "measured by earlier runs")
    return Estimate(None if state["unknown"] else cost, max(copies), state["rough"], basis, reviews, state["measured"])


def _money(value: Decimal) -> str:
    return f"${value:.2f}" if value >= 1 else f"${value:.4f}"


def format_plan(workloads, est: Estimate, pool: int, models: tuple[str, str] | None = None) -> str:
    """The plan as text; `models` is (the reader's model, the review and chat's model), named in it when given."""
    total: Counter = Counter()
    for wl in workloads:
        total.update(wl.files)
    kinds = ", ".join(f"{k} {n}" for k, n in sorted(total.items()))
    lines = [
        "Units: " + ", ".join(wl.unit.name for wl in workloads),
        f"Files: {sum(total.values())} ({kinds})",
        f"Reads: {sum(total.values())}; reviews: about {est.reviews}; "
        f"chat turns: up to {sum(wl.replies for wl in workloads)}",
    ]
    if est.cost is None:
        cost = "Expected cost: cost unknown (no measurements and no listed price for the model)"
    else:
        cost = f"Expected cost: {_money(est.cost)}"
    if est.rough:
        cost += (" (rough: some figures not measured yet)" if est.any_measured
                 else " (rough: no runs measured yet)")
    lines.append(cost)
    if models:
        reader, agent = models
        lines.append(f"Models priced: reading, review and chat at {reader}" if reader == agent
                     else f"Models priced: reading at {reader}, review and chat at {agent}")
    minutes = round(est.seconds / 60)
    lines.append(f"Expected time: about {minutes // 60} h {minutes % 60} min with {pool} copies")
    return "\n".join(lines)


# --- measurements ------------------------------------------------------------
def _jsonl(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _text(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _merge(old: dict | None, cost: Decimal, seconds: float, n: int) -> dict:
    if old and old.get("n"):
        total = old["n"] + n
        cost = (_dec(old["cost"]) * old["n"] + cost * n) / total
        seconds = (float(old["seconds"]) * old["n"] + seconds * n) / total
        n = total
    return {"cost": _text(cost), "seconds": float(seconds), "n": n}


def load_measurements(model: str | None, path: Path = MEASUREMENTS) -> dict | None:
    """The saved figures, unless they are missing, unreadable or for a different model than `model`."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    if model and data.get("model") and data["model"] != model:
        return None
    return data


def update_measurements(run_dir: Path, path: Path = MEASUREMENTS) -> dict:
    """Fold a finished run's relay records into the measurements file and return what it now holds."""
    run_dir = Path(run_dir)
    calls = _jsonl(run_dir / "relay" / "calls.jsonl")
    costs = {}
    for row in _jsonl(run_dir / "relay" / "costs.jsonl"):
        if row.get("cost") is not None:
            costs[row["seq"]] = Decimal(str(row["cost"]))
    # replayed calls cost nothing and took no time; unpriced ones tell us nothing
    live = [c for c in calls if not c.get("replayed") and c["seq"] in costs]

    kind_cost: dict[str, Decimal] = {}
    kind_seconds: dict[str, float] = {}
    kind_n: Counter = Counter()
    part_cost: Counter = Counter()
    part_seconds: Counter = Counter()
    review_ids: set = set()
    replies_sent = 0
    for unit_dir in sorted((run_dir / "units").glob("*")):
        progress = load_progress(unit_dir)
        mine = [c for c in live if c.get("unit") == unit_dir.name]
        shares: dict[str, Decimal] = {}
        for call in (c for c in mine if c.get("part") == "reader"):
            covering = [rel for rel, job in progress.uploads.items()
                        if job.get("submitted") is not None and job.get("finished") is not None
                        and job["submitted"] <= call["started"] <= job["finished"]]
            for rel in covering:
                shares[rel] = shares.get(rel, Decimal(0)) + costs[call["seq"]] / len(covering)
        for rel, share in shares.items():
            job = progress.uploads[rel]
            kind = file_kind(Path(rel))
            kind_cost[kind] = kind_cost.get(kind, Decimal(0)) + share
            kind_seconds[kind] = kind_seconds.get(kind, 0.0) + (job["finished"] - job["submitted"])
            kind_n[kind] += 1
        for call in mine:
            if call.get("part") in ("review", "chat"):
                part_cost[call["part"]] += costs[call["seq"]]
                part_seconds[call["part"]] += call.get("seconds") or 0.0
        replies_sent += sum(1 for r in progress.replies.values() if r.get("sent"))
        for reviews_file in sorted(unit_dir.glob("raw/*/reviews.json")):
            try:
                rows = json.loads(reviews_file.read_text(encoding="utf-8"))
            except ValueError:
                continue
            review_ids.update((unit_dir.name, r.get("id")) for r in rows
                              if isinstance(r, dict) and r.get("status") in ("done", "failed"))

    existing: dict = {}
    if Path(path).is_file():
        try:
            loaded = json.loads(Path(path).read_text(encoding="utf-8"))
            existing = loaded if isinstance(loaded, dict) else {}
        except ValueError:
            existing = {}
    info = {}
    info_path = run_dir / "run.json"
    if info_path.is_file():
        try:
            info = json.loads(info_path.read_text(encoding="utf-8"))
        except ValueError:
            info = {}
    model = (info.get("app") or {}).get("model") if isinstance(info, dict) else None
    if model and existing.get("model") and existing["model"] != model:
        existing = {}  # figures for another model say nothing about this one
    out = {"model": model or existing.get("model"), "kinds": dict(existing.get("kinds") or {})}
    for part in ("review", "chat"):
        if part in existing:
            out[part] = existing[part]
    for kind, n in kind_n.items():
        out["kinds"][kind] = _merge(out["kinds"].get(kind), kind_cost[kind] / n, kind_seconds[kind] / n, n)
    for part, n in (("review", len(review_ids)), ("chat", replies_sent)):
        if n and part in part_cost:
            out[part] = _merge(out.get(part), part_cost[part] / n, part_seconds[part] / n, n)

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(json.dumps(out, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return out
