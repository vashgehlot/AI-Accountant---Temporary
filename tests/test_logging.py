import logging

import pymupdf
import pytest
from fakes import FakeModel

from ledgersync.config import Settings
from ledgersync.intake import Intake
from ledgersync.jobs import Job, JobContext
from ledgersync.pipeline import analyze
from server import create_app


class NullExtractor:
    client = type("Client", (), {"model": "fake-model"})()

    def extract_accounting_data(self, text_input=None, images=None):
        return None


@pytest.fixture
def root_logger():
    """Restores the logging configuration that create_app changes."""
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    saved = {name: logging.getLogger(name).level for name in ("ledgersync",)}
    yield root
    root.handlers = saved_handlers
    root.setLevel(saved_level)
    for name, level in saved.items():
        logging.getLogger(name).setLevel(level)


def test_debug_log_level_never_logs_pdf_text(root_logger, caplog, mongo_store):
    # pytest attaches its own handlers before the test body runs; remove them so create_app
    # configures logging exactly as in a real `python server.py` start.
    root_logger.handlers = []
    create_app(Settings(log_level="DEBUG", warmup=False), model_client=FakeModel(), store=mongo_store)
    root_logger.addHandler(caplog.handler)
    doc = pymupdf.open()
    doc.new_page().insert_text((72, 72), "MRS CLIENT SECRET invoice total 120.00")

    analyze(Intake("pdf", data=doc.tobytes()), NullExtractor(), JobContext(Job(id="t")))

    assert "CLIENT SECRET" not in caplog.text
    assert logging.getLogger("ledgersync").isEnabledFor(logging.DEBUG)   # our own debug logs still flow
