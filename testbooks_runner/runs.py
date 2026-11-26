"""Run folders and per-unit progress, so an interrupted run can resume without redoing paid work."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from datetime import date
from decimal import Decimal
from pathlib import Path

from testbooks_runner.model import Unit

RUNS = Path(__file__).parent / "runs"


class RunDir:
    def __init__(self, path: Path):
        self.path = Path(path)

    @property
    def name(self) -> str:
        return self.path.name

    def unit_dir(self, unit: Unit) -> Path:
        d = self.path / "units" / unit.slug
        d.mkdir(parents=True, exist_ok=True)
        return d

    def write_json(self, rel: str, data) -> None:
        target = self.path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        try:
            # default=str writes Decimal and date values as strings
            tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=_text), encoding="utf-8")
            os.replace(tmp, target)
        finally:
            tmp.unlink(missing_ok=True)

    def read_json(self, rel: str, default=None):
        target = self.path / rel
        if not target.exists():
            return default
        return json.loads(target.read_text(encoding="utf-8"))


def _text(value):
    if isinstance(value, (Decimal, date)):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def new_run(label: str, root: Path = RUNS, today: date | None = None) -> RunDir:
    base = f"{(today or date.today()).isoformat()}-{label}"
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    n = 1
    while True:
        name = base if n == 1 else f"{base}-{n}"
        try:
            (root / name).mkdir()
            return RunDir(root / name)
        except FileExistsError:
            n += 1


def open_run(name: str, root: Path = RUNS) -> RunDir:
    as_path = Path(name)
    for candidate in (Path(root) / name, as_path):
        if candidate.is_dir():
            return RunDir(candidate)
    raise FileNotFoundError(f"no run folder named {name!r}")


def previous_run(current: RunDir, selection: str, root: Path = RUNS) -> RunDir | None:
    best: tuple[str, RunDir] | None = None
    root = Path(root)
    if not root.is_dir():
        return None
    for d in root.iterdir():
        if not d.is_dir() or d.resolve() == current.path.resolve():
            continue
        run = RunDir(d)
        try:
            info = run.read_json("run.json")
        except ValueError:
            continue
        if not isinstance(info, dict) or info.get("selection") != selection or not info.get("finished"):
            continue
        finished = str(info["finished"])
        if best is None or finished > best[0]:
            best = (finished, run)
    return best[1] if best else None


@dataclass
class Progress:
    client_id: int | None = None
    app_year_start: str | None = None
    bank_codes: dict = field(default_factory=dict)
    opening_done: bool = False
    batches_done: list[str] = field(default_factory=list)
    uploads: dict[str, dict] = field(default_factory=dict)
    before_done: bool = False
    replies: dict[str, dict] = field(default_factory=dict)
    thread_id: str | None = None
    chat_year: str | None = None
    after_done: bool = False
    chat_refusal: dict | None = None
    review_waits: dict[str, str] = field(default_factory=dict)


def load_progress(unit_dir: Path) -> Progress:
    path = Path(unit_dir) / "progress.json"
    if not path.exists():
        return Progress()
    raw = json.loads(path.read_text(encoding="utf-8"))
    known = {f.name for f in fields(Progress)}
    return Progress(**{k: v for k, v in raw.items() if k in known})


def save_progress(unit_dir: Path, p: Progress) -> None:
    RunDir(Path(unit_dir)).write_json("progress.json", asdict(p))
