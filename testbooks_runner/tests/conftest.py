"""Keeps every test off the runner's real files: the run folders and measurements under runs/, and verdicts.csv."""
import pytest

from testbooks_runner.runs import RUNS
from testbooks_runner.verdicts import VERDICTS_CSV


def _real_files():
    """What is in runs/ (each file with its modified time) and when verdicts.csv was last written."""
    found = {}
    if RUNS.is_dir():
        for p in RUNS.iterdir():
            found[p.name] = p.stat().st_mtime_ns if p.is_file() else "folder"
    return found, VERDICTS_CSV.stat().st_mtime_ns if VERDICTS_CSV.exists() else None


@pytest.fixture(autouse=True)
def _real_files_untouched():
    before = _real_files()
    yield
    assert _real_files() == before, ("the test wrote to testbooks_runner/runs/ or testbooks_runner/verdicts.csv: "
                                     "give it paths under tmp_path")
