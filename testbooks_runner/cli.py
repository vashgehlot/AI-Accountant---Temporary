"""The command line: plan, run, resume, score, verdicts and clean.

Nothing here spends money without showing the expected cost first and getting a yes (unless --yes). The API
key is never read here: the only values taken from the app's .env are the models' names (the reader's, and the
review and chat's) and the upstream address.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import time
from datetime import date
from pathlib import Path

import pymongo

from . import books, estimate as estimating, orchestrate, report, score, verdicts
from .appserver import StartError, read_env_value
from .orchestrate import RunOptions, resume_run, run_selection
from .runs import RUNS, open_run
from .selection import SelectionError, select_units

REPO = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = "qwen/qwen3.8-27b"
DEFAULT_UPSTREAM = "https://openrouter.ai/api/v1"
DEFAULT_MONGODB = "mongodb://localhost:27017"
INTERRUPTED = 130


def _positive(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a whole number") from None
    if value < 1:
        raise argparse.ArgumentTypeError("must be 1 or more")
    return value


def _day(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a date like 2024-03-31") from None


def _ids(text: str) -> list[str]:
    return [part.strip() for part in text.split(",") if part.strip()]


def _selection_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--client", metavar="NAME")
    p.add_argument("--period", type=_day, metavar="YYYY-MM-DD")
    p.add_argument("--packs", type=_ids, metavar="IDS")
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--all-packs", action="store_true")
    p.add_argument("--repeat", type=_positive, default=1, metavar="K")
    p.add_argument("--pool", type=_positive, default=4, metavar="N")
    p.add_argument("--review", choices=["automatic", "suggest", "off"], default="automatic")
    p.add_argument("--with-next-year", action="store_true")
    p.add_argument("--set", type=Path, default=REPO / "testbooks" / "out", metavar="PATH")
    p.add_argument("--app", type=Path, default=REPO, metavar="PATH")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m testbooks_runner")
    sub = parser.add_subparsers(dest="command", required=True)
    _selection_args(sub.add_parser("plan", help="what a run would read and cost; spends nothing"))
    run = sub.add_parser("run", help="plan, ask, run, score and report")
    _selection_args(run)
    run.add_argument("--replay", type=Path, metavar="RUN")
    run.add_argument("--label")
    run.add_argument("--against", metavar="RUN")
    run.add_argument("--mongodb-uri", default=DEFAULT_MONGODB, metavar="URI")
    run.add_argument("--yes", action="store_true")
    resume = sub.add_parser("resume", help="carry on an interrupted run")
    resume.add_argument("run")
    resume.add_argument("--yes", action="store_true")
    resume.add_argument("--mongodb-uri", default=DEFAULT_MONGODB, metavar="URI")
    scoring = sub.add_parser("score", help="score a saved run again; no app, no model")
    scoring.add_argument("run")
    scoring.add_argument("--against", metavar="RUN")
    scoring.add_argument("--set", type=Path, metavar="PATH")
    imp = sub.add_parser("verdicts", help="take the verdicts from a filled-in differences.xlsx")
    imp.add_argument("xlsx", type=Path)
    clean = sub.add_parser("clean", help="drop the runner's own databases, and old run folders when asked")
    clean.add_argument("--yes", action="store_true")
    clean.add_argument("--folders-older-than", type=_positive, metavar="DAYS")
    clean.add_argument("--mongodb-uri", default=DEFAULT_MONGODB, metavar="URI")
    return parser


# --- the values read from the app's .env ------------------------------------------
def _setting(app_dir: Path, name: str, default: str) -> str:
    """The environment's value for `name`, else that one line of the app's .env, else the default."""
    if os.environ.get(name):
        return os.environ[name]
    return read_env_value(app_dir, name) or default


def _model(app_dir: Path) -> str:
    return _setting(app_dir, "OPENROUTER_MODEL", DEFAULT_MODEL)


def _agent_model(app_dir: Path, reader: str) -> str:
    """The model the app's review and chat run on: OPENROUTER_CHAT_MODEL when it is set, else the reader's."""
    return _setting(app_dir, "OPENROUTER_CHAT_MODEL", "").strip() or reader


# --- planning ---------------------------------------------------------------------
def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", text).strip("-")[:60] or "run"


def _describe(args, units) -> str:
    parts = []
    if args.client:
        parts.append(f"client:{args.client}:{units[0].period.end.isoformat()}")
    if args.packs:
        parts.append("packs:" + ",".join(args.packs))
    if args.smoke:
        parts.append("smoke")
    if args.all_packs:
        parts.append("all-packs")
    return " ".join(parts)


def _plan(args):
    """(units, selection text, expected cost or None, the plan as text). Spends nothing."""
    units = select_units(args.set, client=args.client, period=args.period, packs=args.packs, smoke=args.smoke,
                         all_packs=args.all_packs, repeat=args.repeat)
    loads = [estimating.workload(u, books.load_key(u.key_dir), args.with_next_year) for u in units]
    model = _model(args.app)
    agent = _agent_model(args.app, model)
    measurements = estimating.load_measurements(model, estimating.MEASUREMENTS)
    est = estimating.estimate(loads, measurements=measurements, price=None, pool=args.pool, review=args.review)
    if est.cost is None:  # some figure is not measured: only then are the listed prices needed
        prices = {m: estimating.model_price(m) for m in dict.fromkeys((model, agent))}
        est = estimating.estimate(loads, measurements=measurements, price=prices[model], agent_price=prices[agent],
                                  pool=args.pool, review=args.review)
    plan = estimating.format_plan(loads, est, args.pool, models=(model, agent))
    return units, _describe(args, units), est.cost, plan


# --- what is said after a run ---------------------------------------------------------
def _section(run_dir: Path, title: str) -> list[str]:
    """The lines of one "## " section of the run's report.md, its title first."""
    try:
        lines = (run_dir / "report.md").read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out: list[str] = []
    for line in lines:
        if out and line.startswith("## "):
            break
        if out or line.strip() == f"## {title}":
            out.append(line)
    return [ln for ln in out if ln.strip()]


def _after(run, set_dir: Path, *, guard_note: bool) -> None:
    if not books.signed_off(set_dir):
        print(report.UNREVIEWED)
    for title in ("Cost and time", "Headline"):
        section = _section(run.path, title)
        if section:
            print("\n".join(section))
    if guard_note:
        info = run.read_json("run.json", {}) or {}
        stopped = [u.get("slug") for u in info.get("units") or [] if u.get("status") == "stopped"]
        if stopped:
            spent, estimate = orchestrate.prior_spend(run), info.get("estimate")
            against = f" against an estimate of ${estimate}" if estimate not in (None, "") else ""
            unpriced = score.unpriced_calls(run)
            note = f" ({report.unpriced_note(unpriced, 'the spend')})" if unpriced else ""
            print(f"Stopped by the spending guard: {', '.join(stopped)}. Spent ${spent}{against}{note}. "
                  "Carry on with: python -m testbooks_runner resume " + run.name)
    print(f"Report: {run.path / 'report.md'}")


def _confirmed(yes: bool) -> bool:
    if yes:
        return True
    return _ask("Go ahead? [y/N] ")


def _go_ahead(cost, yes: bool) -> str:
    """"yes", "no", or "refused": an unknown cost means no spending guard, so --yes can't stand in for the answer."""
    if cost is not None:
        return "yes" if _confirmed(yes) else "no"
    if yes:
        print("The cost can't be estimated, so there would be no spending guard. "
              "Run without --yes to confirm.", file=sys.stderr)
        return "refused"
    return "yes" if _ask("Cost unknown, no spending guard - go ahead? [y/N] ") else "no"


def _ask(prompt: str) -> bool:
    try:
        return input(prompt).strip().lower() in ("y", "yes")
    except EOFError:  # no one to answer: that is a no
        return False


# --- commands -------------------------------------------------------------------------
def _cmd_plan(args) -> int:
    print(_plan(args)[3])
    return 0


def _cmd_run(args) -> int:
    units, selection, cost, text = _plan(args)
    print(text)
    go = _go_ahead(cost, args.yes)
    if go != "yes":
        if go == "no":
            print("Stopped; nothing was spent.")
        return 2 if go == "refused" else 0
    options = RunOptions(
        set_dir=args.set, app_dir=args.app, mongodb_uri=args.mongodb_uri, pool=args.pool, review=args.review,
        replay=args.replay, with_next_year=args.with_next_year, yes=args.yes, label=args.label or _slug(selection),
        against=args.against, upstream=_setting(args.app, "OPENROUTER_BASE_URL", DEFAULT_UPSTREAM),
        selection=selection)
    before = set(os.listdir(RUNS)) if RUNS.is_dir() else set()
    try:
        run = run_selection(units, options, runs_root=RUNS, estimate=cost)
    except KeyboardInterrupt:
        made = sorted(set(os.listdir(RUNS)) - before) if RUNS.is_dir() else []
        print("Interrupted.")
        if made:
            print(f"resume it with: python -m testbooks_runner resume {made[-1]}")
        return INTERRUPTED
    _after(run, args.set, guard_note=True)
    return 0


def _cmd_resume(args) -> int:
    run = open_run(args.run, RUNS)
    info = run.read_json("run.json", {}) or {}
    left = [u.get("slug") for u in info.get("units") or [] if u.get("status") != "done"]
    estimate = info.get("estimate")
    print(f"Resuming {run.name}: units left: {', '.join(left) or 'none'}. "
          f"Spent so far ${orchestrate.prior_spend(run)}"
          + (f" against an estimate of ${estimate}." if estimate not in (None, "") else "."))
    recorded = info.get("estimate")
    go = _go_ahead(None if recorded in (None, "") else recorded, args.yes)
    if go != "yes":
        if go == "no":
            print("Stopped; nothing was spent.")
        return 2 if go == "refused" else 0
    # the run's own recorded settings win (resume_run): these stand in only where an old run.json lacks them
    options = RunOptions(set_dir=REPO / "testbooks" / "out", app_dir=REPO, mongodb_uri=args.mongodb_uri,
                         yes=args.yes)
    try:
        resume_run(run, options)
    except KeyboardInterrupt:
        print("Interrupted.")
        print(f"resume it with: python -m testbooks_runner resume {run.name}")
        return INTERRUPTED
    info = run.read_json("run.json", {}) or {}
    _after(run, Path((info.get("set") or {}).get("path") or options.set_dir), guard_note=True)
    return 0


def _cmd_score(args) -> int:
    run = open_run(args.run, RUNS)
    info = run.read_json("run.json", {}) or {}
    set_dir = args.set or Path((info.get("set") or {}).get("path") or REPO / "testbooks" / "out")
    against = open_run(args.against, RUNS) if args.against else None
    score.score_run(run, set_dir, against=against)
    _after(run, set_dir, guard_note=False)
    return 0


def _cmd_verdicts(args) -> int:
    count = verdicts.import_xlsx(args.xlsx)
    print(f"Imported {count} verdicts into {verdicts.VERDICTS_CSV}")
    return 0


def _old_folders(days: int) -> list[Path]:
    cutoff = time.time() - days * 86400
    if not RUNS.is_dir():
        return []
    return sorted(p for p in RUNS.iterdir() if p.is_dir() and p.stat().st_mtime < cutoff)


def _cmd_clean(args) -> int:
    client = pymongo.MongoClient(args.mongodb_uri, serverSelectionTimeoutMS=5000)
    try:
        try:
            names = sorted(n for n in client.list_database_names() if n.startswith("tbrun_"))
        except Exception as exc:
            raise StartError(f"Cannot reach MongoDB at {args.mongodb_uri}: {type(exc).__name__}") from exc
        folders = _old_folders(args.folders_older_than) if args.folders_older_than else []
        if not names and not folders:
            print("Nothing to clean.")
            return 0
        if names:
            print("Databases to drop: " + ", ".join(names))
        if folders:
            print("Run folders to delete: " + ", ".join(p.name for p in folders))
        if not args.yes and not _ask("Go ahead? [y/N] "):
            print("Nothing was dropped.")
            return 0
        for name in names:
            client.drop_database(name)
        for folder in folders:
            shutil.rmtree(folder)
        print(f"Dropped {len(names)} databases and deleted {len(folders)} run folders.")
        return 0
    finally:
        client.close()


_COMMANDS = {"plan": _cmd_plan, "run": _cmd_run, "resume": _cmd_resume, "score": _cmd_score,
             "verdicts": _cmd_verdicts, "clean": _cmd_clean}


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exit_:
        return exit_.code if isinstance(exit_.code, int) else 2
    try:
        return _COMMANDS[args.command](args)
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return INTERRUPTED
    except (SelectionError, StartError, FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
