"""Reads the test books' files. Nothing here imports the generator."""
from __future__ import annotations

import csv
import hashlib
import json
from datetime import date
from pathlib import Path

from .model import Key, Unit

_KEY_FILES = {
    "documents": "documents.csv",
    "entries": "entries.csv",
    "lines": "statement-lines.csv",
    "queries": "queries.csv",
    "vat_returns": "vat-returns.csv",
    "trial_balance": "trial-balance.csv",
    "opening": "opening-balances.csv",
    "debtors": "debtors.csv",
    "creditors": "creditors.csv",
}


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return [dict(row) for row in csv.DictReader(fh)]


def load_key(key_dir: Path) -> Key:
    return Key(**{field: _read_csv(Path(key_dir) / name) for field, name in _KEY_FILES.items()})


def load_profile(folder: Path) -> dict:
    """The client's profile, with its accounting policies (policies.json, when the set has one) under "policies"."""
    profile = json.loads((Path(folder) / "profile.json").read_text(encoding="utf-8"))
    policies = Path(folder) / "policies.json"
    if policies.is_file():
        profile["policies"] = json.loads(policies.read_text(encoding="utf-8"))
    return profile


def load_catalogue(set_dir: Path) -> dict[str, dict]:
    return {row["id"]: row for row in _read_csv(Path(set_dir) / "catalogue.csv")}


def _dated_folders(root: Path) -> list[tuple[date, list[Path]]]:
    if not root.is_dir():
        return []
    out = []
    for day in sorted(p for p in root.iterdir() if p.is_dir()):
        out.append((date.fromisoformat(day.name), sorted(p for p in day.iterdir() if p.is_file())))
    return sorted(out, key=lambda item: item[0])


def batches(folder: Path) -> list[tuple[date, list[Path]]]:
    return _dated_folders(Path(folder) / "inbox")


def answer_folders(folder: Path) -> list[tuple[date, list[Path]]]:
    return _dated_folders(Path(folder) / "answers")


def signed_off(set_dir: Path) -> bool:
    return (Path(set_dir) / "review" / "signed-off.txt").is_file()


def key_hash(unit: Unit) -> str:
    digest = hashlib.sha256()
    for path in sorted(unit.key_dir.glob("*.csv"), key=lambda p: p.name):
        digest.update(path.name.encode("utf-8") + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()
