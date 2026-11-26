"""Measures extraction accuracy against a running LedgerSync API, treated as a black box.

  .venv/bin/python server.py                                  # in one terminal
  .venv/bin/python eval/run_eval.py --label my-change         # in another
  .venv/bin/python eval/run_eval.py --label real --private    # anonymised docs in eval/private/

Writes eval/results/<date>-<label>.json (private runs: eval/private/results/, never committed)."""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path
from typing import Optional

from eval_scoring import adapt_rows, expected_rows, score_case, summarise, to_money

EVAL_DIR = Path(__file__).parent
POLL_SECONDS = 0.5
RETRY_SECONDS = 2.0
RETRIES = 5
# The harness or a rate limit stopped these cases, not the model: --resume runs them again.
HARNESS_ERRORS = frozenset({"api_unreachable", "eval_timeout", "job_not_found", "ai_rate_limited"})
# The API takes analyses only with the header the LedgerSync pages send.
PAGES = {"X-LedgerSync": "1"}


class ApiUnreachable(Exception):
    """The API stopped answering (reset, refused or timed out) and did not recover."""


def _call(method, *args, retries: int = RETRIES, **kwargs):
    """One HTTP call, retried when the connection drops: on a busy 8 GB machine the API can
    stall long enough for a connection to be reset."""
    for attempt in range(1, retries + 1):
        try:
            return method(*args, **kwargs)
        except Exception as exc:    # transport failures: reset, refused, timed out
            if attempt == retries:
                raise ApiUnreachable(str(exc)) from exc
            time.sleep(RETRY_SECONDS)


def results_dir(private: bool) -> Path:
    return EVAL_DIR / "private" / "results" if private else EVAL_DIR / "results"


def load_cases(root: Path, pattern: str = "") -> list[dict]:
    cases = []
    for expected_file in sorted(root.glob("*/expected.json")):
        spec = json.loads(expected_file.read_text())
        if pattern in spec["case"]:
            cases.append({**spec, "path": expected_file.parent / spec["input"]})
    return cases


def _error_code(resp) -> str:
    try:
        detail = resp.json().get("detail")
    except ValueError:
        detail = None
    return detail["code"] if isinstance(detail, dict) and "code" in detail else f"http_{resp.status_code}"


def run_document(client, path: Path, timeout: float, client_id: Optional[int] = None,
                 year_start: Optional[str] = None, bank_account: Optional[str] = None,
                 sleep=time.sleep) -> tuple[Optional[dict], Optional[str]]:
    """Sends one document through POST /api/analyze and the job API. .txt goes in as pasted text. With a
    client_id, the API saves the rows it reads to that client, in the year starting year_start, a statement's on
    the client's bank_account (its code)."""
    form = {} if client_id is None else {"client_id": str(client_id)}
    if year_start:
        form["year_start"] = year_start
    if bank_account:
        form["bank_account"] = bank_account
    # The upload is not retried: if it reached the API, a retry would start a second job.
    if path.suffix == ".txt":
        resp = _call(client.post, "/api/analyze", data={"text": path.read_text(encoding="utf-8"), **form},
                     headers=PAGES, retries=1)
    else:
        resp = _call(client.post, "/api/analyze", files={"file": (path.name, path.read_bytes())}, data=form,
                     headers=PAGES, retries=1)
    if resp.status_code != 202:
        return None, _error_code(resp)
    job_id = resp.json()["job_id"]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resp = _call(client.get, f"/api/jobs/{job_id}")
        if resp.status_code != 200:
            return None, _error_code(resp)     # e.g. job_not_found: the API restarted and lost the job
        job = resp.json()
        if job["status"] == "succeeded":
            return job["result"], None
        if job["status"] in ("failed", "cancelled"):
            return None, (job.get("error") or {}).get("code", job["status"])
        sleep(POLL_SECONDS)
    _call(client.delete, f"/api/jobs/{job_id}", retries=1)
    return None, "eval_timeout"


def _trial_balance_ok(client, result: dict) -> Optional[bool]:
    rows = result.get("transactions")
    if not rows:
        return None
    try:
        resp = _call(client.post, "/api/trial-balance", json={"transactions": rows})
    except ApiUnreachable:
        return None
    if resp.status_code == 422 and _error_code(resp) == "transactions_need_fixing":
        return False                             # the rows cannot be posted as they are
    return bool(resp.json().get("is_balanced")) if resp.status_code == 200 else None


def run_case(client, case: dict, timeout: float) -> dict:
    started = time.monotonic()
    try:
        result, error = run_document(client, case["path"], timeout)
    except ApiUnreachable:
        result, error = None, "api_unreachable"
    latency = round(time.monotonic() - started, 1)
    predicted = adapt_rows(result) if result else []
    return {
        "case": case["case"], "kind": case["kind"], "error": error, "latency_s": latency,
        "model": (result or {}).get("model"),
        "tb_balanced": _trial_balance_ok(client, result) if result else None,
        **score_case(expected_rows(case["rows"]), predicted),
        "predicted_rows": predicted,
    }


def _print_summary(report: dict) -> None:
    head = ("cases", "prec", "recall", "correct", "amount", "date", "dir", "acct", "vat", "type", "exact", "TB ok",
            "p50 s", "p95 s")
    print("\n" + " " * 8 + " ".join(f"{h:>7}" for h in head))
    for name, s in [("all", report["summary"]), *report["by_kind"].items()]:
        f = s["field_accuracy"]
        cells = (s["cases"], s["row_precision"], s["row_recall"], s["correct_rows"], f["amount"], f["date"],
                 f["direction"], f["account"], f["vat"], f["document_type"], s["exact_cases"], s["tb_balanced"], s["latency_p50_s"],
                 s["latency_p95_s"])
        print(f"{name:8}" + " ".join(f"{'n/a' if c is None else c:>7}" for c in cells))
    if report["summary"]["errors"]:
        print("errors:", report["summary"]["errors"])
    if report.get("note"):
        print("conditions:", report["note"])


def _write_report(out_file: Path, results: list[dict], **meta) -> dict:
    results = sorted(results, key=lambda r: r["case"])
    report = {
        "date": date.today().isoformat(), **meta,
        "summary": summarise(results),
        "by_kind": {kind: summarise([r for r in results if r["kind"] == kind])
                    for kind in sorted({r["kind"] for r in results})},
        "cases": results,
    }
    tmp = out_file.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, indent=2, default=str) + "\n")
    tmp.replace(out_file)   # never leave a half-written report behind
    return report


def check_ready(health: dict) -> Optional[str]:
    """None when the API can analyse documents; otherwise why not, so a run does not quietly
    record every case as ai_offline."""
    if health.get("model_available"):
        return None
    return f"The API is up but its AI model is not ready: {health.get('ai_error') or 'unknown reason'}"


def exit_code(report: dict) -> int:
    unfinished = [c["case"] for c in report["cases"] if c.get("error") in HARNESS_ERRORS]
    if unfinished:
        print(f"{len(unfinished)} case(s) did not finish: {', '.join(unfinished)}. Run again with --resume.",
              file=sys.stderr)
        return 1
    return 0


def _rescored(result: dict, rows: list[dict]) -> dict:
    predicted = [{**r, "gross": to_money(r.get("gross")), "vat": to_money(r.get("vat"))}
                 for r in result.get("predicted_rows", [])]
    return {**result, **score_case(expected_rows(rows), predicted), "predicted_rows": predicted}


def rescore(out_file: Path, cases: list[dict]) -> dict:
    """Re-scores a saved report with the current rules and ground truth; no API calls."""
    report = json.loads(out_file.read_text())
    rows = {c["case"]: c["rows"] for c in cases}
    results = [_rescored(r, rows[r["case"]]) if r["case"] in rows else r for r in report["cases"]]
    meta = {k: report[k] for k in ("date", "label", "api", "model", "note", "timeout_s") if k in report}
    return _write_report(out_file, results, **meta)


def run_all(client, cases: list[dict], out_file: Path, *, label: str, api: str, model: Optional[str],
            timeout: float, resume: bool = False, rerun: bool = False, note: str = "",
            known_cases: Optional[list[dict]] = None, pause: float = 0.0, sleep=time.sleep) -> dict:
    """Runs the cases and saves the report after each one, so an interrupted run keeps what it
    finished. With resume, the saved cases stay (re-scored with the current rules) and only
    missing ones, ones the harness did not finish, or with rerun the selected ones, run again.
    A re-run replaces its old result only once it has finished. `pause` seconds pass between
    documents, for a provider's per-minute rate limit."""
    rows = {c["case"]: c["rows"] for c in (known_cases or cases)}
    results = {}
    if resume and out_file.exists():
        for saved in json.loads(out_file.read_text())["cases"]:
            results[saved["case"]] = _rescored(saved, rows[saved["case"]]) if saved["case"] in rows else saved
    todo = [c for c in cases
            if rerun or c["case"] not in results or results[c["case"]].get("error") in HARNESS_ERRORS]
    meta = {"label": label, "api": api, "model": model, "note": note, "timeout_s": timeout}
    out_file.parent.mkdir(parents=True, exist_ok=True)
    for n, case in enumerate(todo, start=1):
        if n > 1 and pause:
            sleep(pause)
        print(f"[{n}/{len(todo)}] {case['case']} ...", end=" ", flush=True)
        outcome = run_case(client, case, timeout)
        results[case["case"]] = outcome
        print(outcome["error"] or f"{outcome['matched']}/{outcome['expected']} rows matched,"
              f" {outcome['predicted']} predicted", f"({outcome['latency_s']} s)", flush=True)
        _write_report(out_file, list(results.values()), **meta)
    return _write_report(out_file, list(results.values()), **meta)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api", default="http://127.0.0.1:8085")
    parser.add_argument("--label", required=True, help="name for this run, e.g. baseline")
    parser.add_argument("--cases", default="", help="only cases whose id contains this text")
    parser.add_argument("--private", action="store_true", help="run eval/private/ instead of the fixtures")
    parser.add_argument("--timeout", type=float, default=600, help="seconds allowed per document")
    parser.add_argument("--note", default="", help="run conditions to keep with the results, e.g. the Groq plan")
    parser.add_argument("--resume", action="store_true",
                        help="continue today's report for this label: run only missing or unfinished cases")
    parser.add_argument("--rerun", action="store_true", help="with --resume, run the selected cases again")
    parser.add_argument("--overwrite", action="store_true", help="replace today's report for this label")
    parser.add_argument("--rescore", action="store_true", help="re-score today's report for this label; no API calls")
    parser.add_argument("--pause", type=float, default=0, help="seconds between documents, for a rate-limited provider")
    args = parser.parse_args(argv)

    import httpx2

    known = load_cases(EVAL_DIR / ("private" if args.private else "fixtures"))
    cases = [c for c in known if args.cases in c["case"]]
    if not cases:
        print("No cases found.", file=sys.stderr)
        return 1
    out_file = results_dir(args.private) / f"{date.today().isoformat()}-{args.label}.json"
    if args.rescore:
        if not out_file.exists():
            print(f"{out_file} does not exist.", file=sys.stderr)
            return 1
        _print_summary(rescore(out_file, known))
        print(f"\nRe-scored {out_file}")
        return 0
    if out_file.exists() and not (args.resume or args.overwrite):
        print(f"{out_file} already exists. Use --resume to continue it, or --overwrite to replace it.",
              file=sys.stderr)
        return 1
    # A fresh connection per request: if this process stalls for longer than uvicorn's 5 s
    # keep-alive (swapping on an 8 GB Mac), reusing the old socket fails with a reset.
    with httpx2.Client(base_url=args.api, timeout=180,
                       limits=httpx2.Limits(max_keepalive_connections=0)) as client:
        try:
            health = client.get("/api/health").json()
        except Exception:
            print(f"Cannot reach the LedgerSync API at {args.api}. Start it with: .venv/bin/python server.py",
                  file=sys.stderr)
            return 2
        problem = check_ready(health)
        if problem:
            print(problem, file=sys.stderr)
            return 2
        report = run_all(client, cases, out_file, label=args.label, api=args.api, model=health.get("model"),
                         timeout=args.timeout, resume=args.resume, rerun=args.rerun, note=args.note,
                         known_cases=known, pause=args.pause)
    _print_summary(report)
    print(f"\nWrote {out_file}")
    return exit_code(report)


if __name__ == "__main__":
    sys.exit(main())
