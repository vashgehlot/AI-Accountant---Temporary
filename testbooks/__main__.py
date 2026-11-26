"""python -m testbooks build [--out DIR] [--seed N] [--client ID ...] [--packs EC-0301,...] [--until YYYY-MM-DD]
python -m testbooks check CLIENT_DIR [--period-end YYYY-MM-DD]"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from testbooks.build import DEFAULT_UNTIL, build
from testbooks.checks import run_checks


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="testbooks")
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="generate the test books")
    b.add_argument("--out", type=Path, default=Path("testbooks/out"))
    b.add_argument("--seed", type=int, default=7)
    b.add_argument("--client", action="append", default=[])
    b.add_argument("--packs", default="")
    b.add_argument("--until", type=date.fromisoformat, default=DEFAULT_UNTIL)
    c = sub.add_parser("check", help="check a written client or pack folder")
    c.add_argument("client_dir", type=Path)
    c.add_argument("--period-end", type=date.fromisoformat, default=None)
    args = parser.parse_args(argv)
    if args.command == "build":
        packs = [p for p in args.packs.split(",") if p]
        try:
            folders = build(args.out, args.seed, args.client or ["agency"], packs, args.until)
        except RuntimeError as exc:
            print(exc, file=sys.stderr)
            return 1
        for f in folders:
            print(f)
        return 0
    end = args.period_end or date.fromisoformat(sorted(p.name for p in (args.client_dir / "key").iterdir())[0])
    results = run_checks(args.client_dir, end)
    for r in results:
        print(f"{'PASS' if r.ok else 'FAIL'} {r.name}: {r.detail}")
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
