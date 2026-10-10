"""Pytest fixtures.

Environment variables are configured *before* any app module is imported,
because ``app.config`` reads them at import time. Each test session gets its
own temp SQLite file and output directory, and jobs are processed synchronously
so assertions are deterministic.
"""
import os
import tempfile
from pathlib import Path

import pytest

_TMP = Path(tempfile.mkdtemp(prefix="cert_test_"))
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP / 'test.db'}"
os.environ["CERT_OUTPUT_DIR"] = str(_TMP / "out")
os.environ["CERT_PROCESS_SYNC"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from app.database import init_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _setup_db():
    init_db()
    yield


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def sample_payload():
    return {
        "course_name": "Introduction to Python",
        "issuer": "Acme Academy",
        "issue_date": "2026-10-10",
        "recipients": [
            {"name": "Alice Smith", "email": "alice@example.com"},
            {"name": "Bob Jones", "email": "bob@example.com"},
        ],
    }
