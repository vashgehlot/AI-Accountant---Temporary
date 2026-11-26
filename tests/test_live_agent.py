"""The accountant chat on the real model: one model, OPENROUTER_MODEL, reads the files and runs the turn through
OpenRouter. Marked llm, so it runs only with `pytest -m llm`: it spends OpenRouter credit, so ask before running it.
It needs OPENROUTER_API_KEY and the MongoDB test cluster."""
import dataclasses
import json
import mimetypes
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_chat_api import events_of

from ledgersync import ledger
from ledgersync.config import Settings
from ledgersync.models import ClientFields
from server import create_app

# llm only, never mongo too: `pytest -m mongo` would then select it and spend credit.
pytestmark = pytest.mark.llm

CASES = Path(__file__).parent.parent / "eval" / "agent_cases"


def documents(case: Path) -> list[Path]:
    """The case's files, without their .rows.json or hidden files."""
    return sorted(p for p in (case / "documents").iterdir()
                  if p.is_file() and not p.name.startswith(".") and not p.name.endswith(".rows.json"))


def test_clean_month(mongo_store):
    settings = dataclasses.replace(Settings.from_env(), warmup=False)
    if not settings.openrouter_api_key:
        pytest.skip("set OPENROUTER_API_KEY (e.g. in .env) to run")
    case = CASES / "clean-month"
    client_id = ledger.add_client(mongo_store, ClientFields.model_validate(
        json.loads((case / "client.json").read_text()))).id
    files = [("files", (p.name, p.read_bytes(), mimetypes.guess_type(p.name)[0] or "application/octet-stream"))
             for p in documents(case)]

    with TestClient(create_app(settings, store=mongo_store), headers={"X-LedgerSync": "1"}) as api:
        thread = api.post("/api/chat/threads", json={"client_id": client_id}).json()
        sent = api.post(f"/api/chat/threads/{thread['id']}/messages", data={"text": "Review these documents."},
                        files=files)

    assert sent.status_code == 200, sent.text
    events = events_of(sent.text)
    assert [data for kind, data in events if kind == "error"] == []
    assert [data for kind, data in events if kind == "step" and data["state"] == "failed"] == []
    [result] = [data for kind, data in events if kind == "result"]
    assert result["questions"] == []
    assert result["trial_balance"]["is_balanced"] and result["trial_balance"]["suspense"] == []
