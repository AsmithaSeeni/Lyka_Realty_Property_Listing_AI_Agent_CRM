"""Turso/libSQL DATABASE_URL normalisation (config → engine contract).

Why these tests exist: the previous suite passed 100% while the production
Turso path was unresolvable, because no test ever asked whether
create_engine() could load the dialect. Verified from the pinned wheel
(``sqlalchemy_libsql-0.2.0-py3-none-any.whl`` → entry_points.txt):

    [sqlalchemy.dialects]
    sqlite.libsql = sqlalchemy_libsql:SQLiteDialect_libsql
    sqlite.aiolibsql = sqlalchemy_libsql:SQLiteDialect_aiolibsql

There is NO top-level ``libsql`` (nor ``https``/``http``) dialect, so a raw
``DATABASE_URL=libsql://<db>.turso.io`` — the exact form the Turso CLI
prints and README/.env.example/docs give operators — crashed create_engine()
at import with "Did not find a dialect named 'libsql'".

Contract now pinned here:
  1. Every documented operator form normalises to a REGISTERED scheme
     (``sqlite+libsql://...``) before the engine sees it.
  2. The normalised form routes to the auth-token connect-args branch —
     it must never receive SQLite-only args (that would drop the token).
  3. The local-SQLite PRAGMA hook is never registered for libSQL remotes.
  4. Local SQLite and explicit non-libSQL URLs are untouched.
"""

import pytest

import app.config as cfg
import app.database as dbmod


# ------------------------------------------------------------------ config

def test_libsql_scheme_normalised_to_registered_dialect(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "libsql://mydb-org.turso.io")
    url = cfg._database_url()
    assert url == "sqlite+libsql://mydb-org.turso.io?secure=true"


def test_libsql_query_string_preserved(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "libsql://mydb-org.turso.io?secure=false")
    assert cfg._database_url() == "sqlite+libsql://mydb-org.turso.io?secure=false"


def test_https_turso_base_normalised_secure(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "https://mydb-org.turso.io")
    assert cfg._database_url() == "sqlite+libsql://mydb-org.turso.io?secure=true"


def test_http_base_normalised_insecure(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "http://127.0.0.1:8080")
    assert cfg._database_url() == "sqlite+libsql://127.0.0.1:8080?secure=false"


def test_empty_url_falls_back_to_local_sqlite(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert cfg._database_url().startswith("sqlite:///")


def test_plain_sqlite_url_untouched(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./custom.db")
    assert cfg._database_url() == "sqlite:///./custom.db"


def test_other_explicit_scheme_untouched(monkeypatch):
    """A deliberately exotic URL is passed through unchanged (create_engine
    fails loudly on it rather than silently rewriting operator intent)."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@host/db")
    assert cfg._database_url() == "postgresql+psycopg://u:p@host/db"


def test_every_documented_form_resolves_to_registered_scheme(monkeypatch):
    """Regression guard for the exact failure this file was written for:
    after normalisation the URL must start with a scheme sqlalchemy-libsql
    registers (`sqlite+libsql`), never a bare unregistered one."""
    for raw in (
        "libsql://mydb-org.turso.io",
        "https://mydb-org.turso.io",
        "http://mydb-org.turso.io",
        "sqlite+libsql://mydb-org.turso.io?secure=true",
    ):
        monkeypatch.setenv("DATABASE_URL", raw)
        url = cfg._database_url()
        assert url.startswith("sqlite+libsql://"), (raw, url)
        assert not url.startswith(("libsql://", "https://", "http://")), (raw, url)


# ------------------------------------------------------------- connect args

@pytest.fixture
def _patch_url(monkeypatch):
    """Point app.database at a URL the way import-time wiring would."""
    original = dbmod.SQLALCHEMY_DATABASE_URL
    from app.config import settings

    token_before = settings.TURSO_AUTH_TOKEN

    def apply(url, token=""):
        monkeypatch.setattr(dbmod, "SQLALCHEMY_DATABASE_URL", url)
        settings.TURSO_AUTH_TOKEN = token

    yield apply
    dbmod.SQLALCHEMY_DATABASE_URL = original
    settings.TURSO_AUTH_TOKEN = token_before


def test_normalised_libsql_gets_auth_token_not_sqlite_args(_patch_url):
    _patch_url("sqlite+libsql://mydb-org.turso.io?secure=true", token="tok-abc")
    assert dbmod._engine_connect_args() == {"auth_token": "tok-abc"}


def test_normalised_libsql_without_token_is_empty(_patch_url):
    _patch_url("sqlite+libsql://mydb-org.turso.io?secure=true", token="")
    assert dbmod._engine_connect_args() == {}


def test_local_sqlite_keeps_phase1_connect_args(_patch_url):
    _patch_url("sqlite:///./real_estate.db")
    args = dbmod._engine_connect_args()
    assert args["check_same_thread"] is False
    assert "timeout" in args
    assert "auth_token" not in args


# ------------------------------------------------------ PRAGMA hook scoping

def test_pragma_hook_condition_excludes_libsql():
    assert dbmod._is_local_sqlite("sqlite:///./real_estate.db") is True
    assert dbmod._is_local_sqlite("sqlite+libsql://mydb-org.turso.io?secure=true") is False
    assert dbmod._is_local_sqlite("sqlite+aiolibsql:///embedded.db") is False
    # raw operator forms (pre-normalisation) are not local files either
    assert dbmod._is_local_sqlite("libsql://mydb-org.turso.io") is False
    assert dbmod._is_local_sqlite("postgresql+psycopg://u:p@host/db") is False


def test_libsql_flag_covers_all_operator_forms():
    for url in (
        "libsql://mydb-org.turso.io",
        "https://mydb-org.turso.io",
        "http://mydb-org.turso.io",
        "sqlite+libsql://mydb-org.turso.io?secure=true",
        "sqlite+aiolibsql:///embedded.db",
    ):
        assert url.startswith(dbmod._LIBSQL_URL_PREFIXES), url
    assert not "sqlite:///./x.db".startswith(dbmod._LIBSQL_URL_PREFIXES)
