"""Runs the client-level test set (eval/jobs/) through a running LedgerSync API, treated as a black box, and scores
each client's first-year trial balance against the one worked out by hand, account by account, to the penny.

  .venv/bin/python server.py                                      # in one terminal; needs MongoDB and a model
  .venv/bin/python eval/run_job_eval.py --label my-change         # in another
  .venv/bin/python eval/run_job_eval.py --label my-change --case ltd-   # only the cases whose folder name contains "ltd-"

For each case it adds the client (client.json), reads every document in documents/ into the client's first year (a
statement goes to the bank account client.json's "statements" names for it, any other file to the client's first
account), and scores the year's trial balance against expected_trial_balance.json. No agent is involved: the
figures are what the documents give. Writes eval/results/<date>-jobs-<label>.json and exits 0 only when every case
matches."""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Optional

import run_eval
from job_scoring import compare, net_by_account

EVAL_DIR = Path(__file__).parent
JOBS_DIR = EVAL_DIR / "jobs"
RESULTS_DIR = EVAL_DIR / "results"
ANALYSIS_TIMEOUT = 600      # seconds allowed to read each document, as run_eval allows


def load_cases(root: Path, pattern: str = "") -> list[Path]:
    """The case folders under root whose name contains pattern, by name."""
    return sorted(p for p in root.iterdir() if p.is_dir() and (p / "client.json").exists() and pattern in p.name)


def _read(case: Path, name: str):
    return json.loads((case / name).read_text())


def _documents(case: Path) -> list[Path]:
    """The case's documents, by name, without hidden files such as .DS_Store."""
    return sorted(p for p in (case / "documents").iterdir() if p.is_file() and not p.name.startswith("."))


def _new_outcome(case: Path) -> dict:
    """A case's result before anything has run. differences stays None until the trial balance is compared."""
    return {"case": case.name, "verdict": None, "error": None, "error_detail": None, "client_id": None,
            "year_start": None, "documents": [], "is_balanced": None, "differences": None, "run_time_s": None}


def _run(client, case: Path, outcome: dict, *, sleep, analysis_timeout: float) -> None:
    fields = _read(case, "client.json")
    statements = fields.pop("statements", {})   # file name -> the name of the bank account it is for
    resp = run_eval._call(client.post, "/api/clients", json=fields, headers=run_eval.PAGES)
    if resp.status_code != 201:
        outcome.update(error="client_not_added", error_detail=run_eval._error_code(resp))
        return
    added = resp.json()
    client_id = outcome["client_id"] = added["id"]
    codes = {account["name"]: account["code"] for account in added["bank_accounts"]}
    unknown = sorted(set(statements.values()) - set(codes))
    if unknown:
        outcome.update(error="unknown_bank_account", error_detail=f"client.json names no such account: {unknown[0]}")
        return
    default = added["bank_accounts"][0]["code"]

    resp = run_eval._call(client.get, f"/api/clients/{client_id}/years")
    if resp.status_code != 200:
        outcome.update(error="years_unavailable", error_detail=run_eval._error_code(resp))
        return
    year_start = outcome["year_start"] = resp.json()[0]["start"]

    for path in _documents(case):
        account = codes[statements[path.name]] if path.name in statements else default
        result, error = run_eval.run_document(client, path, analysis_timeout, client_id=client_id,
                                              year_start=year_start, bank_account=account, sleep=sleep)
        outcome["documents"].append({"name": path.name, "bank_account": account, "error": error,
                                     "rows": len((result or {}).get("transactions") or [])})
    unread = [d["name"] for d in outcome["documents"] if d["error"] or not d["rows"]]
    if unread:   # the books would lack their rows, so the trial balance can't match
        outcome.update(error="analysis_failed", error_detail=f"No rows saved from: {', '.join(unread)}")
        return

    resp = run_eval._call(client.get, f"/api/clients/{client_id}/years/{year_start}/trial-balance")
    if resp.status_code == 422:   # a row needs fixing: the API says which
        message = (resp.json().get("detail") or {}).get("message")
        outcome.update(error="trial_balance_not_built", error_detail=message or run_eval._error_code(resp))
        return
    if resp.status_code != 200:
        outcome.update(error="trial_balance_unavailable", error_detail=run_eval._error_code(resp))
        return
    trial_balance = resp.json()
    expected = {code: Decimal(net) for code, net in _read(case, "expected_trial_balance.json").items()}
    outcome.update(is_balanced=trial_balance["is_balanced"],
                   differences=compare(expected, net_by_account(trial_balance)))


def _verdict_of(outcome: dict) -> str:
    """"match" only when every step worked and the trial balance balances and agrees with the expected one in every
    account; otherwise what went wrong."""
    if outcome["error"]:
        return outcome["error"]
    if outcome["is_balanced"] is not True:
        return "not_balanced"
    return "differences" if outcome["differences"] else "match"


def run_case(client, case: Path, *, sleep=time.sleep, clock=time.monotonic,
             analysis_timeout: float = ANALYSIS_TIMEOUT) -> dict:
    """Adds the case's client, reads its documents into the client's first year and scores that year's trial
    balance."""
    outcome = _new_outcome(case)
    started = clock()
    try:
        _run(client, case, outcome, sleep=sleep, analysis_timeout=analysis_timeout)
    except run_eval.ApiUnreachable as exc:
        outcome.update(error="api_unreachable", error_detail=str(exc))
    outcome["verdict"] = _verdict_of(outcome)
    outcome["run_time_s"] = round(clock() - started, 1)
    return outcome


def _write_report(out_file: Path, results: list[dict], **meta) -> dict:
    matched = [r["verdict"] == "match" for r in results]
    report = {"date": date.today().isoformat(), **meta,
              "summary": {"cases": len(results), "matched": sum(matched),
                          "failed": [r["case"] for r, ok in zip(results, matched) if not ok]},
              "cases": results}
    tmp = out_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, indent=2) + "\n")
    tmp.replace(out_file)   # never leave a half-written report behind
    return report


def _describe(outcome: dict) -> str:
    """A case's result in words, for the console."""
    verdict = outcome["verdict"]
    if verdict == "match":
        return "matches"
    if verdict == "not_balanced":
        return "trial balance does not balance"
    if verdict == "differences":
        return f"{len(outcome['differences'])} account(s) differ"
    return verdict + (f": {outcome['error_detail']}" if outcome["error_detail"] else "")


def run_all(client, cases: list[Path], out_file: Path, *, label: str, api: str, model: Optional[str] = None,
            sleep=time.sleep, clock=time.monotonic) -> dict:
    """Runs the cases one after another and saves the report after each, so an interrupted run keeps what it
    finished."""
    out_file.parent.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    meta = {"label": label, "api": api, "model": model}
    for n, case in enumerate(cases, start=1):
        print(f"[{n}/{len(cases)}] {case.name} ...", end=" ", flush=True)
        outcome = run_case(client, case, sleep=sleep, clock=clock)
        results.append(outcome)
        print(_describe(outcome), f"({outcome['run_time_s']} s)", flush=True)
        _write_report(out_file, results, **meta)
    return _write_report(out_file, results, **meta)


def exit_code(report: dict) -> int:
    """0 only when there were cases and every one matched."""
    return 0 if report["cases"] and all(c["verdict"] == "match" for c in report["cases"]) else 1


def _print_summary(report: dict) -> None:
    print(f"\n{report['summary']['matched']} of {report['summary']['cases']} case(s) match.")
    for case in report["cases"]:
        print(f"  {case['case']}: {_describe(case)}; {case['run_time_s']} s")
        for diff in case["differences"] or []:
            print(f"      {diff['code']}: expected {diff['expected']}, got {diff['actual']} ({diff['difference']})")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default="http://127.0.0.1:8085")
    parser.add_argument("--label", required=True, help="name for this run, e.g. accounting-site")
    parser.add_argument("--case", default="", help="only cases whose folder name contains this text")
    parser.add_argument("--overwrite", action="store_true", help="replace today's report for this label")
    args = parser.parse_args(argv)

    import httpx2

    cases = load_cases(JOBS_DIR, args.case)
    if not cases:
        print("No cases found.", file=sys.stderr)
        return 1
    out_file = RESULTS_DIR / f"{date.today().isoformat()}-jobs-{args.label}.json"
    if out_file.exists() and not args.overwrite:
        print(f"{out_file} already exists. Use --overwrite to replace it, or another --label.", file=sys.stderr)
        return 1
    # A fresh connection per request, as run_eval makes them: a long poll must not reuse a socket the API closed.
    with httpx2.Client(base_url=args.api, timeout=180,
                       limits=httpx2.Limits(max_keepalive_connections=0)) as client:
        try:
            health = run_eval._call(client.get, "/api/health", retries=1).json()
        except run_eval.ApiUnreachable:
            print(f"Cannot reach the LedgerSync API at {args.api}. Start it with: .venv/bin/python server.py",
                  file=sys.stderr)
            return 2
        problem = run_eval.check_ready(health)
        if problem:
            print(problem, file=sys.stderr)
            return 2
        report = run_all(client, cases, out_file, label=args.label, api=args.api, model=health.get("model"))
    _print_summary(report)
    print(f"\nWrote {out_file}")
    return exit_code(report)


if __name__ == "__main__":
    sys.exit(main())
