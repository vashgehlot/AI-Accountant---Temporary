import re, subprocess
from pathlib import Path
PKG = Path(__file__).resolve().parents[1]
FORBIDDEN = re.compile(r"^\s*(from|import)\s+(ledgersync|testbooks)(\.|\s|$)", re.M)

def test_runner_imports_neither_app_nor_generator():
    offenders = [p for p in PKG.rglob("*.py") if FORBIDDEN.search(p.read_text())]
    assert offenders == []

def test_runs_folder_is_ignored():
    assert subprocess.run(["git", "check-ignore", "-q", str(PKG / "runs" / "x")], cwd=PKG.parent).returncode == 0

def test_verdicts_file_has_its_header():
    assert (PKG / "verdicts.csv").read_text().splitlines()[0] == "identity,ref,verdict,whats_right,who,date,got"
