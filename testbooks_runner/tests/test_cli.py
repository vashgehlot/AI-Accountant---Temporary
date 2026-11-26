import json
import os
import shutil
import time
from decimal import Decimal
from pathlib import Path

import pytest

from testbooks_runner import cli, estimate as estimating, report
from testbooks_runner.appserver import StartError
from testbooks_runner.runs import RunDir

FIX = Path(__file__).parent / "fixtures" / "set"
PACK = "EC-0346-receipt-over-250"


@pytest.fixture(autouse=True)
def calm(monkeypatch, tmp_path):
    """No network, no real run folders, no stray model settings, no measurements. Returns the models priced."""
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    monkeypatch.delenv("OPENROUTER_CHAT_MODEL", raising=False)
    monkeypatch.delenv("OPENROUTER_BASE_URL", raising=False)
    monkeypatch.setattr(cli, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(estimating, "MEASUREMENTS", tmp_path / "runs" / "measurements.json")
    prices = []
    monkeypatch.setattr(estimating, "model_price",
                        lambda model, **kw: prices.append(model) or {"in": Decimal("0.000001"),
                                                                       "out": Decimal("0.000002")})
    return prices


@pytest.fixture
def app(tmp_path):
    folder = tmp_path / "app"
    folder.mkdir()
    return folder


def plan_args(app, *extra):
    return ["--packs", "EC-0346", "--set", str(FIX), "--app", str(app), *extra]


def fake_run(tmp_path, *, units=None, estimate=None):
    """What run_selection leaves behind: a scored run folder."""
    run = RunDir(tmp_path / "runs" / "2026-11-19-x")
    run.path.mkdir(parents=True, exist_ok=True)
    run.write_json("run.json", {"units": units or [{"slug": "u", "status": "done"}], "estimate": estimate,
                                "set": {"path": str(FIX)}})
    (run.path / "report.md").write_text("# x\n\n## Headline\n\n- Entries right: 3 of 4\n\n## Faults\n\n- nope\n",
                                        encoding="utf-8")
    return run


class FakeMongo:
    names: list[str] = []
    dropped: list[str] = []

    def __init__(self, *a, **k):
        pass

    def list_database_names(self):
        return list(self.names)

    def drop_database(self, name):
        self.dropped.append(name)

    def close(self):
        pass


@pytest.fixture
def mongo(monkeypatch):
    class Mongo(FakeMongo):
        names: list[str] = []
        dropped: list[str] = []

    monkeypatch.setattr(cli.pymongo, "MongoClient", Mongo)
    return Mongo


def test_plan_prints_the_estimate(capsys, app):
    assert cli.main(["plan", *plan_args(app)]) == 0
    out = capsys.readouterr().out
    assert "Reads: 6" in out and "Expected cost: $" in out and PACK in out


def test_run_asks_and_stops_on_no(monkeypatch, capsys, app):
    called = []
    monkeypatch.setattr(cli, "run_selection", lambda *a, **k: called.append("run"))
    monkeypatch.setattr("builtins.input", lambda prompt="": (called.append(prompt), "n")[1])
    assert cli.main(["run", *plan_args(app)]) == 0
    assert called == ["Go ahead? [y/N] "]
    assert "Reads: 6" in capsys.readouterr().out


def test_run_prints_the_banner_with_the_summary(monkeypatch, capsys, tmp_path, app):
    made = {}

    def fake(units, options, **kw):
        made.update(units=units, options=options, kw=kw)
        return fake_run(tmp_path)

    monkeypatch.setattr(cli, "run_selection", fake)
    assert cli.main(["run", *plan_args(app), "--yes"]) == 0
    out = capsys.readouterr().out
    assert out.index(report.UNREVIEWED) < out.index("Entries right: 3 of 4")
    assert "nope" not in out
    assert f"Report: {tmp_path / 'runs' / '2026-11-19-x' / 'report.md'}" in out
    assert made["options"].selection == "packs:EC-0346" and made["options"].label == "packs-EC-0346"
    assert made["options"].yes is True and made["options"].set_dir == FIX
    assert made["kw"]["estimate"] is not None


def test_no_banner_when_signed_off(monkeypatch, capsys, tmp_path, app):
    set_dir = tmp_path / "set"
    shutil.copytree(FIX, set_dir)
    (set_dir / "review").mkdir()
    (set_dir / "review" / "signed-off.txt").write_text("ok", encoding="utf-8")
    monkeypatch.setattr(cli, "run_selection", lambda *a, **k: fake_run(tmp_path))
    assert cli.main(["run", "--packs", "EC-0346", "--set", str(set_dir), "--app", str(app), "--yes"]) == 0
    assert report.UNREVIEWED not in capsys.readouterr().out


def test_a_stopped_unit_is_named_with_the_spend(monkeypatch, capsys, tmp_path, app):
    run = fake_run(tmp_path, units=[{"slug": "a", "status": "stopped"}, {"slug": "b", "status": "done"}],
                   estimate="2.00")
    (run.path / "relay").mkdir()
    (run.path / "relay" / "costs.jsonl").write_text('{"seq": 1, "cost": "3.50"}\n', encoding="utf-8")
    monkeypatch.setattr(cli, "run_selection", lambda *a, **k: run)
    cli.main(["run", *plan_args(app), "--yes"])
    out = capsys.readouterr().out
    assert "Stopped by the spending guard: a." in out and "Spent $3.50 against an estimate of $2.00" in out


def test_the_summary_gives_the_cost_and_calls_with_no_cost(monkeypatch, capsys, tmp_path, app):
    run = fake_run(tmp_path, units=[{"slug": "a", "status": "stopped"}], estimate="2.00")
    (run.path / "report.md").write_text(
        "# x\n\n## Cost and time\n\n- Cost: $3.50 (estimate $2.00)\n- 1 call had no cost from the provider, so the "
        "cost shown is a lower bound\n\n## Headline\n\n- Entries right: 3 of 4\n", encoding="utf-8")
    (run.path / "relay").mkdir()
    (run.path / "relay" / "calls.jsonl").write_text(
        '{"seq": 1, "generation_id": "g1"}\n{"seq": 2, "generation_id": "g2"}\n', encoding="utf-8")
    (run.path / "relay" / "costs.jsonl").write_text('{"seq": 1, "cost": "3.50"}\n', encoding="utf-8")
    monkeypatch.setattr(cli, "run_selection", lambda *a, **k: run)
    cli.main(["run", *plan_args(app), "--yes"])
    out = capsys.readouterr().out
    assert "- Cost: $3.50 (estimate $2.00)\n- 1 call had no cost from the provider, so the cost shown is a lower " \
           "bound" in out and "Entries right: 3 of 4" in out
    assert ("Spent $3.50 against an estimate of $2.00 (1 call had no cost from the provider, so the spend is a "
            "lower bound).") in out


def test_selection_error_exits_2_with_its_message(capsys, app):
    assert cli.main(["plan", "--packs", "EC-9999", "--set", str(FIX), "--app", str(app)]) == 2
    assert "EC-9999" in capsys.readouterr().err


def test_nothing_selected_and_bad_arguments_exit_2(capsys, app):
    assert cli.main(["plan", "--set", str(FIX), "--app", str(app)]) == 2
    assert cli.main(["plan", "--pool", "0"]) == 2
    assert cli.main(["plan", "--period", "March"]) == 2
    assert cli.main(["nonsense"]) == 2


def test_a_start_error_exits_2(monkeypatch, capsys, app):
    def refuse(*a, **k):
        raise StartError("No OpenRouter key")

    monkeypatch.setattr(cli, "run_selection", refuse)
    assert cli.main(["run", *plan_args(app), "--yes"]) == 2
    assert "No OpenRouter key" in capsys.readouterr().err


def test_ctrl_c_names_the_run_to_resume(monkeypatch, capsys, tmp_path, app):
    def interrupted(*a, **k):
        (tmp_path / "runs" / "2026-11-19-half").mkdir(parents=True)
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "run_selection", interrupted)
    assert cli.main(["run", *plan_args(app), "--yes"]) == 130
    assert "resume it with: python -m testbooks_runner resume 2026-11-19-half" in capsys.readouterr().out


def test_model_comes_from_the_environment_first(monkeypatch, app, calm):
    (app / ".env").write_text("OPENROUTER_MODEL=from/dotenv\nOPENROUTER_API_KEY=sk-secret\n", encoding="utf-8")
    monkeypatch.setenv("OPENROUTER_MODEL", "from/env")
    cli.main(["plan", *plan_args(app)])
    assert calm == ["from/env"]


def test_model_comes_from_the_dotenv_line_then_the_default(app, calm, capsys):
    (app / ".env").write_text("OPENROUTER_API_KEY=sk-secret\nOPENROUTER_MODEL='from/dotenv' # note\n",
                              encoding="utf-8")
    cli.main(["plan", *plan_args(app)])
    (app / ".env").unlink()
    cli.main(["plan", *plan_args(app)])
    assert calm == ["from/dotenv", "qwen/qwen3.8-27b"]
    assert "sk-secret" not in capsys.readouterr().out


@pytest.fixture
def two_prices(monkeypatch):
    """The reader's model at one price, any other ten times dearer. Returns the models priced."""
    asked = []

    def price(model, **kw):
        asked.append(model)
        scale = 1 if model == "qwen/qwen3.8-27b" else 10
        return {"in": Decimal("0.000001") * scale, "out": Decimal("0.000002") * scale}

    monkeypatch.setattr(estimating, "model_price", price)
    return asked


# EC-0346 roughly: 5 pdfs and a sheet read for $0.09, 5 reviews and a chat turn of 40,000 tokens in, 5,000 out
CHEAP, DEAR = "Expected cost: $0.3900", "Expected cost: $3.09"


def test_review_and_chat_priced_at_the_chat_model_from_the_environment(monkeypatch, app, capsys, two_prices):
    (app / ".env").write_text("OPENROUTER_CHAT_MODEL=from/dotenv\n", encoding="utf-8")
    monkeypatch.setenv("OPENROUTER_CHAT_MODEL", "from/env")
    cli.main(["plan", *plan_args(app)])
    out = capsys.readouterr().out
    assert two_prices == ["qwen/qwen3.8-27b", "from/env"] and DEAR in out
    assert "Models priced: reading at qwen/qwen3.8-27b, review and chat at from/env" in out


def test_review_and_chat_priced_at_the_chat_model_from_the_dotenv_line(app, capsys, two_prices):
    (app / ".env").write_text("OPENROUTER_API_KEY=sk-x\nOPENROUTER_CHAT_MODEL='from/dotenv'\n", encoding="utf-8")
    cli.main(["plan", *plan_args(app)])
    out = capsys.readouterr().out
    assert two_prices == ["qwen/qwen3.8-27b", "from/dotenv"] and DEAR in out
    assert "Models priced: reading at qwen/qwen3.8-27b, review and chat at from/dotenv" in out


def test_review_and_chat_priced_at_the_reader_model_with_no_chat_model(app, capsys, two_prices):
    (app / ".env").write_text("OPENROUTER_API_KEY=sk-x\nOPENROUTER_CHAT_MODEL=\n", encoding="utf-8")
    cli.main(["plan", *plan_args(app)])
    out = capsys.readouterr().out
    assert two_prices == ["qwen/qwen3.8-27b"] and CHEAP in out
    assert "Models priced: reading, review and chat at qwen/qwen3.8-27b" in out


def test_upstream_comes_from_the_environment_then_dotenv_then_default(monkeypatch, tmp_path, app):
    seen = []
    monkeypatch.setattr(cli, "run_selection",
                        lambda units, options, **kw: (seen.append(options.upstream), fake_run(tmp_path))[1])
    cli.main(["run", *plan_args(app), "--yes"])
    (app / ".env").write_text("OPENROUTER_API_KEY=sk-secret\nOPENROUTER_BASE_URL=http://dotenv/v1\n",
                              encoding="utf-8")
    cli.main(["run", *plan_args(app), "--yes"])
    monkeypatch.setenv("OPENROUTER_BASE_URL", "http://env/v1")
    cli.main(["run", *plan_args(app), "--yes"])
    assert seen == ["https://openrouter.ai/api/v1", "http://dotenv/v1", "http://env/v1"]


def test_the_key_is_never_printed(monkeypatch, capsys, tmp_path, app):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-topsecret")
    (app / ".env").write_text("OPENROUTER_API_KEY=sk-or-v1-fromdotenv\n", encoding="utf-8")
    monkeypatch.setattr(cli, "run_selection", lambda *a, **k: fake_run(tmp_path))
    cli.main(["plan", *plan_args(app)])
    cli.main(["run", *plan_args(app), "--yes"])
    seen = capsys.readouterr()
    assert "topsecret" not in seen.out + seen.err and "fromdotenv" not in seen.out + seen.err


def test_measurements_of_another_model_are_ignored(monkeypatch, app, capsys, calm):
    figures = {"cost": "0.01", "seconds": 5, "n": 3}
    estimating.MEASUREMENTS.parent.mkdir(parents=True)
    estimating.MEASUREMENTS.write_text(json.dumps({"model": "other/model", "kinds": {"pdf": figures},
                                                   "review": figures, "chat": figures}), encoding="utf-8")
    monkeypatch.setenv("OPENROUTER_MODEL", "mine/model")
    cli.main(["plan", *plan_args(app)])
    assert "rough: no runs measured yet" in capsys.readouterr().out and calm == ["mine/model"]


def test_the_price_is_not_fetched_when_everything_is_measured(app, capsys, calm):
    figures = {"cost": "0.01", "seconds": 5, "n": 3}
    kinds = {k: figures for k in ("pdf", "image", "sheet", "text", "other")}
    estimating.MEASUREMENTS.parent.mkdir(parents=True)
    estimating.MEASUREMENTS.write_text(json.dumps({"model": "qwen/qwen3.8-27b", "kinds": kinds,
                                                   "review": figures, "chat": figures}), encoding="utf-8")
    cli.main(["plan", *plan_args(app)])
    out = capsys.readouterr().out
    assert calm == [] and "Expected cost: $" in out and "rough" not in out


def test_clean_only_drops_runner_databases(mongo):
    mongo.names = ["ledgersync", "tbrun_a_1", "tbrun_a_1_checkpoints", "other"]
    assert cli.main(["clean", "--yes"]) == 0
    assert mongo.dropped == ["tbrun_a_1", "tbrun_a_1_checkpoints"]


def test_clean_asks_first_and_no_drops_nothing(monkeypatch, capsys, mongo):
    mongo.names = ["tbrun_a_1"]
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    assert cli.main(["clean"]) == 0
    assert mongo.dropped == [] and "tbrun_a_1" in capsys.readouterr().out


def test_clean_deletes_only_old_run_folders(tmp_path, mongo):
    root = tmp_path / "runs"
    old, new = root / "old", root / "new"
    old.mkdir(parents=True)
    new.mkdir()
    (root / "measurements.json").write_text("{}", encoding="utf-8")
    long_ago = time.time() - 40 * 86400
    os.utime(old, (long_ago, long_ago))
    os.utime(root / "measurements.json", (long_ago, long_ago))
    assert cli.main(["clean", "--yes", "--folders-older-than", "30"]) == 0
    assert not old.exists() and new.exists() and (root / "measurements.json").exists()


def test_verdicts_imports(monkeypatch, tmp_path, capsys):
    got = []
    monkeypatch.setattr(cli.verdicts, "import_xlsx", lambda xlsx: got.append(xlsx) or 2)
    assert cli.main(["verdicts", str(tmp_path / "d.xlsx")]) == 0
    assert got == [tmp_path / "d.xlsx"] and "Imported 2" in capsys.readouterr().out


def test_score_defaults_to_the_set_in_run_json(monkeypatch, capsys, tmp_path):
    run = fake_run(tmp_path)
    seen = {}
    monkeypatch.setattr(cli.score, "score_run", lambda r, set_dir, **kw: seen.update(set=set_dir, **kw))
    assert cli.main(["score", run.name]) == 0
    assert seen["set"] == FIX and seen["against"] is None
    out = capsys.readouterr().out
    assert report.UNREVIEWED in out and "Entries right" in out
    other = tmp_path / "elsewhere"
    assert cli.main(["score", run.name, "--set", str(other), "--against", run.name]) == 0
    assert seen["set"] == other and seen["against"].name == run.name


def test_score_of_a_missing_run_exits_2(capsys):
    assert cli.main(["score", "nope"]) == 2
    assert "nope" in capsys.readouterr().err


def test_resume_asks_then_resumes_with_its_own_settings(monkeypatch, capsys, tmp_path, app):
    run = fake_run(tmp_path, units=[{"slug": "a", "status": "stopped"}], estimate="2.00")
    got = []
    monkeypatch.setattr(cli, "resume_run", lambda r, options, **kw: got.append((r.name, options.yes)))
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")
    assert cli.main(["resume", run.name]) == 0
    assert got == [] and "units left: a" in capsys.readouterr().out
    assert cli.main(["resume", run.name, "--yes"]) == 0
    assert got == [(run.name, True)]
    assert "Report:" in capsys.readouterr().out


def test_resume_takes_no_app_the_run_keeps_its_own(capsys, tmp_path):
    run = fake_run(tmp_path, estimate="2.00")
    assert cli.main(["resume", run.name, "--app", str(tmp_path)]) == 2
    assert "--app" in capsys.readouterr().err


def test_resume_ctrl_c_exits_130(monkeypatch, capsys, tmp_path, app):
    run = fake_run(tmp_path, estimate="2.00")

    def stop(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "resume_run", stop)
    assert cli.main(["resume", run.name, "--yes"]) == 130
    assert f"resume {run.name}" in capsys.readouterr().out


def test_defaults_are_the_repo_root_not_the_working_directory():
    args = cli._parser().parse_args(["plan", "--smoke"])
    assert args.app == Path(cli.__file__).resolve().parents[1]
    assert args.set == args.app / "testbooks" / "out" and args.pool == 4 and args.review == "automatic"


@pytest.fixture
def no_price(monkeypatch):
    monkeypatch.setattr(estimating, "model_price", lambda model, **kw: None)


def test_unknown_cost_with_yes_is_refused(monkeypatch, capsys, app, no_price):
    called = []
    monkeypatch.setattr(cli, "run_selection", lambda *a, **k: called.append(1))
    assert cli.main(["run", *plan_args(app), "--yes"]) == 2
    err = capsys.readouterr().err
    assert called == [] and "can't be estimated" in err and "no spending guard" in err


def test_unknown_cost_asks_a_distinct_question(monkeypatch, tmp_path, app, no_price):
    prompts, got = [], []
    monkeypatch.setattr("builtins.input", lambda prompt="": (prompts.append(prompt), "n")[1])
    monkeypatch.setattr(cli, "run_selection", lambda *a, **k: got.append(k["estimate"]) or fake_run(tmp_path))
    assert cli.main(["run", *plan_args(app)]) == 0
    assert prompts == ["Cost unknown, no spending guard - go ahead? [y/N] "] and got == []
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")
    assert cli.main(["run", *plan_args(app)]) == 0
    assert got == [None]


def test_a_closed_stdin_is_a_no(monkeypatch, capsys, app, mongo):
    def closed(prompt=""):
        raise EOFError

    monkeypatch.setattr("builtins.input", closed)
    called = []
    monkeypatch.setattr(cli, "run_selection", lambda *a, **k: called.append(1))
    assert cli.main(["run", *plan_args(app)]) == 0
    mongo.names = ["tbrun_a_1"]
    assert cli.main(["clean"]) == 0
    assert called == [] and mongo.dropped == []


def test_read_env_value_reads_one_value_and_refuses_secrets(app):
    from testbooks_runner.appserver import read_env_value
    (app / ".env").write_text("OPENROUTER_API_KEY=sk-x\nOPENROUTER_MODEL=a/b\nMODEL_TOKEN=t\n", encoding="utf-8")
    assert read_env_value(app, "OPENROUTER_MODEL") == "a/b" and read_env_value(app, "OPENROUTER_BASE_URL") is None
    for name in ("OPENROUTER_API_KEY", "MODEL_TOKEN", "DB_PASSWORD", "client_secret"):
        with pytest.raises(ValueError):
            read_env_value(app, name)


def test_resume_of_an_unknown_cost_run_is_refused_under_yes(monkeypatch, capsys, tmp_path, app):
    run = fake_run(tmp_path, units=[{"slug": "a", "status": "stopped"}], estimate=None)
    got = []
    monkeypatch.setattr(cli, "resume_run", lambda r, options, **kw: got.append(1))
    assert cli.main(["resume", run.name, "--yes"]) == 2
    err = capsys.readouterr().err
    assert got == [] and "can't be estimated" in err and "no spending guard" in err


def test_resume_of_an_unknown_cost_run_asks_the_distinct_question(monkeypatch, tmp_path, app):
    run = fake_run(tmp_path, units=[{"slug": "a", "status": "stopped"}], estimate=None)
    prompts, got = [], []
    monkeypatch.setattr(cli, "resume_run", lambda r, options, **kw: got.append(1))
    monkeypatch.setattr("builtins.input", lambda prompt="": (prompts.append(prompt), "n")[1])
    assert cli.main(["resume", run.name]) == 0
    assert prompts == ["Cost unknown, no spending guard - go ahead? [y/N] "] and got == []
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")
    assert cli.main(["resume", run.name]) == 0
    assert got == [1]
