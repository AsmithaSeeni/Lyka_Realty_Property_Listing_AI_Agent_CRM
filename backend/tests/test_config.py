"""Phase 1 — configuration tests.

1. Config loads safely when optional environment variables are missing.
2. DATABASE_URL defaults to the ACTIVE backend DB (absolute, CWD-independent)
   and cannot silently select the stale repo-root database; an alternate DB
   requires an explicit DATABASE_URL.
3. NVIDIA configuration stays independent of the new/OpenAI variables.
4. CORS parsing (defaults, CSV, production wildcard rejection).
5. DEBUG defaults to a safe value (off).

Subprocesses are used so each scenario gets a genuinely fresh import of
``app.config`` (its values are read once at import time).
"""

import json
import os
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = BACKEND_DIR.parent

# Vars whose absence must not break config (the "optional env" scenario).
OPTIONAL_VARS = (
    "OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_BASE_URL",
    "OPENAI_TIMEOUT_SECONDS", "OPENAI_MAX_RETRIES",
    "DATABASE_URL", "APP_ENV", "DEBUG",
    "CORS_ORIGINS", "RATE_LIMIT_ENABLED", "CHAT_RATE_LIMIT", "AUTH_RATE_LIMIT",
    "VOICE_RATE_LIMIT", "RATE_LIMIT_WINDOW_SECONDS", "REQUEST_MAX_BYTES",
    "CHAT_MESSAGE_MAX_CHARS", "SYNTHESIZE_TEXT_MAX_CHARS",
    "VOICE_UPLOAD_MAX_BYTES", "COOKIE_SECURE",
)

_PROBE = (
    "import json; import app.config as c; "
    "s = c.settings; "
    "print(json.dumps({"
    "'debug': s.DEBUG, 'app_env': s.APP_ENV, 'db_url': s.DATABASE_URL, "
    "'nvidia_model': s.NVIDIA_MODEL, 'nvidia_key_len': len(s.NVIDIA_API_KEY), "
    "'openai_key': s.OPENAI_API_KEY, 'openai_model': s.OPENAI_MODEL, "
    "'chat_limit': s.CHAT_RATE_LIMIT, 'auth_limit': s.AUTH_RATE_LIMIT, "
    "'voice_limit': s.VOICE_RATE_LIMIT, 'window': s.RATE_LIMIT_WINDOW_SECONDS, "
    "'origins': s.CORS_ORIGINS, 'cookie_secure': s.COOKIE_SECURE, "
    "'rate_enabled': s.RATE_LIMIT_ENABLED, 'max_msg': s.CHAT_MESSAGE_MAX_CHARS"
    "}))"
)


def _probe(cwd, overrides=None, unset=()):
    env = {k: v for k, v in os.environ.items() if k not in unset}
    env.update(overrides or {})
    env["PYTHONIOENCODING"] = "utf-8"
    # `import app.*` must work regardless of the child process CWD.
    env["PYTHONPATH"] = str(BACKEND_DIR)
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE],
        cwd=str(cwd), env=env, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, f"config import failed: {proc.stderr[-800:]}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_config_loads_with_optional_env_missing(tmp_path):
    """All optional vars removed -> clean import with safe defaults."""
    data = _probe(REPO_DIR, overrides={v: "" for v in OPTIONAL_VARS},
                  unset=OPTIONAL_VARS)
    assert data["debug"] is False, "DEBUG must default OFF (safe default)"
    assert data["app_env"] == "development"
    assert data["rate_enabled"] is True
    assert data["chat_limit"] == 60 and data["auth_limit"] == 15
    assert data["voice_limit"] == 30 and data["window"] == 60
    assert data["max_msg"] == 4000
    assert data["cookie_secure"] is False
    # Phase 3: key stays empty (extraction disabled); model has a safe default.
    assert data["openai_key"] == "" and data["openai_model"] == "gpt-4o-mini"
    assert len(data["origins"]) == 4  # local dev defaults


def test_database_url_defaults_to_active_db_from_any_cwd():
    """Repo-root CWD must NOT select the stale root real_estate.db."""
    for cwd in (REPO_DIR, BACKEND_DIR, BACKEND_DIR / "app"):
        data = _probe(cwd, unset=("DATABASE_URL",))
        url = data["db_url"]
        assert url.startswith("sqlite:///"), url
        assert url.endswith("/backend/real_estate.db"), (
            f"cwd={cwd}: expected backend active DB, got {url}"
        )
        # Absolute path => no './' CWD-relative behaviour at all.
        assert "/./" not in url
    # The resolved file is the real, live database (must exist).
    resolved = Path(data["db_url"].replace("sqlite:///", "", 1))
    assert resolved.exists() and resolved.name == "real_estate.db"


def test_explicit_database_url_is_honoured():
    """A different DB is only ever used via an explicit value."""
    explicit = "sqlite:///D:/explicit/other.db"
    data = _probe(REPO_DIR, overrides={"DATABASE_URL": explicit})
    assert data["db_url"] == explicit


def test_nvidia_config_independent_of_openai():
    """OpenAI vars present/absent never disturb NVIDIA settings."""
    base = {"NVIDIA_API_KEY": "unit-test-dummy-key", "NVIDIA_MODEL": "unit/test-model"}
    for unset in ((), ("OPENAI_API_KEY", "OPENAI_MODEL"),):
        data = _probe(REPO_DIR, overrides=base, unset=unset)
        assert data["nvidia_key_len"] == len("unit-test-dummy-key")
        assert data["nvidia_model"] == "unit/test-model"
        assert isinstance(data["openai_key"], str)  # may be "" — never affects NVIDIA
    # Blank NVIDIA_MODEL in env falls back to the original default model.
    data = _probe(REPO_DIR, overrides={"NVIDIA_MODEL": ""})
    assert data["nvidia_model"] == "nvidia/nemotron-3.5-lightning-30b-a3b"


def test_settings_match_database_module_url():
    """database.py must use exactly settings.DATABASE_URL (no hidden path)."""
    data = _probe(BACKEND_DIR, unset=("DATABASE_URL",))
    proc = subprocess.run(
        [sys.executable, "-c",
         "import app.config as c, app.database as d; "
         "assert d.SQLALCHEMY_DATABASE_URL == c.settings.DATABASE_URL; "
         "print('OK')"],
        cwd=str(BACKEND_DIR),
        env={**os.environ, "DATABASE_URL": "", "PYTHONPATH": str(BACKEND_DIR)},
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr[-800:]
    assert "OK" in proc.stdout
    assert data["db_url"].endswith("/backend/real_estate.db")


# ------------------------- CORS parsing units -------------------------

def test_cors_defaults_for_local_dev():
    from app.config import parse_cors

    origins = parse_cors("", "development")
    assert origins == [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]


def test_cors_csv_parsed():
    from app.config import parse_cors

    origins = parse_cors("https://a.example, https://b.example", "production")
    assert origins == ["https://a.example", "https://b.example"]


def test_cors_wildcard_rejected_in_production():
    from app.config import parse_cors

    assert parse_cors("*", "production") == []
    # wildcard removed but explicit origins kept
    assert parse_cors("*, https://real.example", "production") == [
        "https://real.example"
    ]
    # wildcard tolerated (dev-only convenience) outside production
    assert parse_cors("*", "development") == ["*"]
