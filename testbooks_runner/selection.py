"""Chooses which clients or packs to run, and which files to send."""
from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

from . import books
from .model import Key, Period, Unit


class SelectionError(Exception):
    pass


def _first_period(folder: Path) -> Period:
    first = books.load_profile(folder)["periods"][0]
    return Period(date.fromisoformat(first["start"]), date.fromisoformat(first["end"]))


def _pack(set_dir: Path, case_id: str) -> Unit:
    found = sorted(p for p in (set_dir / "packs").glob(f"{case_id}-*") if p.is_dir())
    if not found:
        raise SelectionError(f"No pack for {case_id} in {set_dir / 'packs'}")
    return Unit(found[0].name, "pack", found[0], _first_period(found[0]))


def select_units(set_dir: Path, *, client: str | None = None, period: date | None = None,
                 packs: list[str] | None = None, smoke: bool = False, all_packs: bool = False,
                 repeat: int = 1) -> list[Unit]:
    set_dir = Path(set_dir)
    units: list[Unit] = []
    if client is not None:
        folder = set_dir / "clients" / client
        if not (folder / "profile.json").is_file():
            raise SelectionError(f"No client named {client} in {set_dir / 'clients'}")
        first = _first_period(folder)
        if period is not None and period != first.end:
            raise SelectionError("later periods need the earlier years carried forward, "
                                 "which the runner doesn't do yet")
        units.append(Unit(client, "client", folder, first))
    ids = list(packs or [])
    if smoke:
        listing = set_dir / "packs" / "smoke.txt"
        if not listing.is_file():
            raise SelectionError(f"The smoke list {listing} is missing: build the set with one, "
                                 "or name packs with --packs")
        ids += [ln.strip() for ln in listing.read_text(encoding="utf-8").splitlines() if ln.strip()]
    for case_id in ids:
        units.append(_pack(set_dir, case_id))
    if all_packs:
        for folder in sorted(p for p in (set_dir / "packs").glob("*") if p.is_dir()):
            units.append(Unit(folder.name, "pack", folder, _first_period(folder)))
    seen: set[str] = set()
    units = [u for u in units if not (u.name in seen or seen.add(u.name))]
    if not units:
        raise SelectionError("Nothing selected: name a client, or use --packs, --smoke or --all-packs")
    return [replace(u, repeat=r) for u in units for r in range(1, repeat + 1)]


def files_to_send(unit: Unit, key: Key, with_next_year: bool) -> list[tuple[date, list[Path]]]:
    known = {row["file"] for row in key.documents}
    out = []
    for day, files in books.batches(unit.folder):
        kept = [p for p in files
                if with_next_year or p.relative_to(unit.folder).as_posix() in known]
        if kept:
            out.append((day, kept))
    return out
