"""Phase 1 test bootstrap.

CRITICAL ORDER:
1. Add backend/ to sys.path so ``import app...`` works from any CWD.
2. Point DATABASE_URL at a throwaway SQLite file BEFORE any app import —
   app.config reads the environment at import time. This guarantees no test
   can ever read or write the live backend/real_estate.db.
3. Pin deterministic env (the repo .env can never override these because
   load_dotenv() does not replace variables already set in the environment).
"""

import os
import pathlib
import sys
import tempfile

_BACKEND_DIR = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

_TEST_WORKDIR = pathlib.Path(tempfile.mkdtemp(prefix="lyka_phase1_test_"))
_TEST_DB = _TEST_WORKDIR / "test.db"

os.environ["DATABASE_URL"] = "sqlite:///" + _TEST_DB.as_posix()
os.environ["APP_ENV"] = "test"
os.environ["COOKIE_SECURE"] = "false"       # tests run over http
os.environ["CORS_ORIGINS"] = ""             # -> safe local defaults
os.environ["RATE_LIMIT_ENABLED"] = "true"
# Never allow inherited shell settings to skew tests:
os.environ.pop("DEBUG", None)

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def app_module():
    """Import the FastAPI app once per session (tables/seeds go to the temp DB)."""
    import app.main as main_mod

    return main_mod


@pytest.fixture()
def client(app_module):
    """Fresh TestClient per test (isolated cookie jar), safe error raising."""
    from fastapi.testclient import TestClient

    return TestClient(app_module.app, raise_server_exceptions=False)


@pytest.fixture()
def db(app_module):
    """Session bound to the throwaway test database."""
    from app.database import SessionLocal

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _reset_limiter():
    """Rate-limit counters are process-global; isolate them per test."""
    from app.services.ratelimit import limiter

    limiter.reset()
    yield
    limiter.reset()


# ---------------- Phase 10: live-provider tests are opt-in ----------------
# Ordinary runs (`python -m pytest tests -q`) are FULLY OFFLINE: tests marked
# `live` or `live_openai` are skipped unless RUN_LIVE_TESTS=1 is deliberately
# set — even when provider API keys happen to exist in the environment or in
# the repo .env. Missing credentials still produce their own clear skip inside
# the live test modules (a second, independent guard). Every other provider
# interaction in the suite is mocked in-process and runs normally.


def pytest_collection_modifyitems(config, items):
    opt_in = os.environ.get("RUN_LIVE_TESTS", "").strip().lower()
    if opt_in in {"1", "true", "yes"}:
        return
    skip_live = pytest.mark.skip(
        reason="live provider test — set RUN_LIVE_TESTS=1 (and provide the "
               "API key) to run it; default runs are fully offline"
    )
    for item in items:
        if "live" in item.keywords or "live_openai" in item.keywords:
            item.add_marker(skip_live)
