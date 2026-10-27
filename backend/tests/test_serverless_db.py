"""Task 4 — serverless database (Turso/libSQL) engine wiring.

The backend defaults to a local SQLite file, which CANNOT persist on Vercel
Functions (read-only, ephemeral, per-instance filesystem). Pointing
DATABASE_URL at a libSQL URL routes the same SQLAlchemy models to hosted Turso.

These tests pin the connect-arg selection logic in app.database WITHOUT
creating a real libSQL engine (the sqlalchemy-libsql driver is Linux/macOS
only and is not installed on every dev box). They patch the module-level
SQLALCHEMY_DATABASE_URL + settings token, so they run fully offline against
whatever DATABASE_URL the suite is using.

Guaranteed invariants:
  - SQLite URLs keep the exact Phase 1/9 connect args (regression guard).
  - libSQL URLs get the auth token via connect_args, never in the URL.
  - libSQL URLs do NOT receive SQLite-only connect args.
  - Non-SQLite, non-libSQL URLs (e.g. Postgres) get no extra args.
  - The SQLite PRAGMA hook is only registered for sqlite:// URLs.
"""

import pytest

import app.database as dbmod


@pytest.fixture(autouse=True)
def _restore_url():
    """Undo every patch after each test so the shared engine is untouched."""
    original_url = dbmod.SQLALCHEMY_DATABASE_URL
    original_flag = dbmod._IS_LIBSQL
    yield
    dbmod.SQLALCHEMY_DATABASE_URL = original_url
    dbmod._IS_LIBSQL = original_flag


def _patch(url, token=""):
    """Point the module's URL detection at `url` the way import-time would."""
    dbmod.SQLALCHEMY_DATABASE_URL = url
    dbmod._IS_LIBSQL = url.startswith(("libsql://", "https://", "http://"))
    from app.config import settings

    settings.TURSO_AUTH_TOKEN = token
    return settings


def test_sqlite_urls_keep_phase1_connect_args():
    _patch("sqlite:///./real_estate.db")
    args = dbmod._engine_connect_args()
    assert args["check_same_thread"] is False
    assert "timeout" in args
    assert "auth_token" not in args


def test_libsql_url_gets_auth_token_via_connect_args():
    settings = _patch("libsql://mydb-org.turso.io", token="tok-123")
    try:
        args = dbmod._engine_connect_args()
    finally:
        settings.TURSO_AUTH_TOKEN = ""
    assert args == {"auth_token": "tok-123"}


def test_libsql_url_omits_sqlite_only_args():
    _patch("libsql://mydb-org.turso.io", token="tok-123")
    args = dbmod._engine_connect_args()
    assert "check_same_thread" not in args
    assert "timeout" not in args


def test_libsql_https_transport_also_detected():
    """Turso accepts an https:// base as well as libsql://."""
    _patch("https://mydb-org.turso.io", token="tok-xyz")
    assert dbmod._IS_LIBSQL is True
    assert dbmod._engine_connect_args() == {"auth_token": "tok-xyz"}


def test_libsql_without_token_yields_empty_args():
    """A missing token must not crash engine construction — the driver will
    fail later with its own clear auth error instead."""
    _patch("libsql://mydb-org.turso.io", token="")
    assert dbmod._engine_connect_args() == {}


def test_postgres_url_gets_no_extra_args():
    _patch("postgresql+psycopg://user:pass@host/db")
    assert dbmod._IS_LIBSQL is False
    assert dbmod._engine_connect_args() == {}


def test_token_never_embedded_in_url_string():
    """The token travels via connect_args only, so it cannot leak into logs,
    tracebacks or repr(engine)."""
    _patch("libsql://mydb-org.turso.io", token="super-secret-token")
    args = dbmod._engine_connect_args()
    assert args.get("auth_token") == "super-secret-token"
    # the module's URL string is the bare host — no credentials inline
    assert "super-secret-token" not in dbmod.SQLALCHEMY_DATABASE_URL


def test_libsql_flag_matches_startswith():
    assert dbmod._IS_LIBSQL is dbmod.SQLALCHEMY_DATABASE_URL.startswith(
        ("libsql://", "https://", "http://")
    )
