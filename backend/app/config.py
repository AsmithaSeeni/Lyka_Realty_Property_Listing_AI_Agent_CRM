"""Application configuration (Phase 1 — security & configuration hardening).

Every value comes from an environment variable, optionally loaded from the
repo-root ``.env`` file (``load_dotenv`` never overrides variables that are
already set in the process environment).

Design rules:
- Empty values are treated as "unset" so a blank placeholder line in
  ``.env.example`` can never silently disable a default.
- NVIDIA chat configuration keeps its exact original variable names and
  defaults (``NVIDIA_API_KEY`` / ``NVIDIA_MODEL``) — chat must not change.
- ``OPENAI_*`` settings feed the Phase 3 structured lead-extraction client
  only; they are fully isolated from the NVIDIA chat configuration.
- The active SQLite database is resolved to an ABSOLUTE path
  (``backend/real_estate.db``) so the current working directory can never
  silently select a different file (the repo-root ``real_estate.db`` is
  stale). A different database requires an explicit ``DATABASE_URL``.
"""

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()  # repo-root .env; does not override variables already set


# ---------------------------------------------------------------- helpers

def _env(name: str, default: str = "") -> str:
    """Environment value, or ``default`` when unset/blank."""
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip()


def _bool(name: str, default: bool = False) -> bool:
    value = _env(name, "").lower()
    if value in ("1", "true", "yes", "on"):
        return True
    if value in ("0", "false", "no", "off"):
        return False
    return default


def _int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


def parse_cors(raw: str, app_env: str):
    """Parse ``CORS_ORIGINS`` (comma-separated) into a safe origin list.

    - Empty  → safe local-development defaults (Vite dev server + API).
    - ``*``  → rejected when ``APP_ENV=production`` (credentials are sent
      cross-site, so a wildcard must never reach production); any other
      configured origins are kept. In development ``*`` is allowed but still
      logged as a note by the caller's docs — it is a dev-only convenience.
    - In non-production environments (development/test), local dev origins
      (Vite dev server and API on localhost and 127.0.0.1) are automatically
      merged into the origin list so local development always works smoothly
      even when an external origin (e.g. Vercel) is specified in .env.
    """
    default = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]
    if not raw:
        return list(default)
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    is_prod = (app_env or "").lower() == "production"
    if "*" in origins and is_prod:
        origins = [o for o in origins if o != "*"]
        if not origins:
            return []  # explicit hard failure: configure real origins
    if not is_prod and "*" not in origins:
        for d in default:
            if d not in origins:
                origins.append(d)
    return origins


# ---------------------------------------------------------------- paths

BACKEND_DIR = Path(__file__).resolve().parent.parent  # D:\...\backend
# The ACTIVE database file. Resolved absolutely at import time — running the
# server from any other working directory still uses this exact file.
ACTIVE_DB_FILE = BACKEND_DIR / "real_estate.db"
# The repo-root database is stale legacy data and must never be picked up
# implicitly; only an explicit DATABASE_URL can point the app somewhere else.


def _database_url() -> str:
    explicit = _env("DATABASE_URL", "")
    if not explicit:
        explicit = _env("LYKA_PG_DEV_URL", "")
    if not explicit:
        # If in test mode with TEST_DATABASE_URL, let conftest govern
        test_url = _env("TEST_DATABASE_URL", "")
        if test_url:
            explicit = test_url
        else:
            raise RuntimeError(
                "FATAL: DATABASE_URL is not set. Lyka Realty CRM requires an authoritative "
                "PostgreSQL database connection (e.g., postgresql+psycopg://...)."
            )

    # Normalize standard Postgres schemes to modern psycopg 3 scheme
    if explicit.startswith("postgres://"):
        explicit = "postgresql+psycopg://" + explicit[len("postgres://"):]
    elif explicit.startswith("postgresql://") and not explicit.startswith("postgresql+psycopg://"):
        explicit = "postgresql+psycopg://" + explicit[len("postgresql://"):]

    # Enforce sslmode=require for Render or remote postgres if not specified
    if "render.com" in explicit and "sslmode=" not in explicit:
        separator = "&" if "?" in explicit else "?"
        explicit = f"{explicit}{separator}sslmode=require"

    return explicit


class Settings:
    # ---------------- NVIDIA chat (existing — names/defaults unchanged)
    NVIDIA_API_KEY: str = _env("NVIDIA_API_KEY", "")
    NVIDIA_MODEL: str = _env("NVIDIA_MODEL", "nvidia/nemotron-3.5-lightning-30b-a3b")
    # Stronger multilingual model for Tamil-script/Tanglish/mixed customer
    # turns (2026-10: measured ~11s natural spoken Tamil with thinking off;
    # the 30B lightning model's Tamil read as code-mixed machine output).
    NVIDIA_MODEL_TAMIL: str = _env(
        "NVIDIA_MODEL_TAMIL", "nvidia/nemotron-3-super-120b-a12b"
    )

    # ---------------- TTS settings (existing)
    TTS_PROVIDER: str = _env("TTS_PROVIDER", "sarvam")
    TTS_MODEL: str = _env("TTS_MODEL", "bulbul:v4-flash")
    TTS_VOICE: str = _env("TTS_VOICE", "aparna_en_edtech")
    TTS_API_KEY: str = _env("TTS_API_KEY", "")

    # ---------------- STT settings (existing)
    STT_PROVIDER: str = _env("STT_PROVIDER", "sarvam")
    STT_MODEL: str = _env("STT_MODEL", "saaras:v1")
    STT_API_KEY: str = _env("STT_API_KEY", "")

    # ---------------- OpenAI (Phase 3 — structured lead extraction ONLY)
    # Completely separate from the NVIDIA chat configuration above. Used only
    # by the staff-invoked extraction workflow; customer chat never calls it.
    OPENAI_API_KEY: str = _env("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = _env("OPENAI_MODEL", "gpt-4o-mini")
    OPENAI_BASE_URL: str = _env("OPENAI_BASE_URL", "https://api.openai.com/v1")
    OPENAI_TIMEOUT_SECONDS: int = _int("OPENAI_TIMEOUT_SECONDS", 30)
    # Bounded retry: 0 or 1 (never more) — only for transient failures
    # (timeout / 429 / 5xx). Clamped defensively.
    OPENAI_MAX_RETRIES: int = max(0, min(1, _int("OPENAI_MAX_RETRIES", 1)))

    # ---------------- Application / environment
    APP_ENV: str = _env("APP_ENV", "development")
    # Safe default: DEBUG is OFF unless explicitly enabled. (The previous
    # hard-coded True is gone; nothing in the app read the old value.)
    DEBUG: bool = _bool("DEBUG", False)
    DATABASE_URL: str = _database_url()
    TEST_DATABASE_URL: Optional[str] = _env("TEST_DATABASE_URL", None)

    # ---------------- CORS
    CORS_ORIGINS: list = parse_cors(_env("CORS_ORIGINS", ""), APP_ENV)

    # ---------------- Rate limiting (per application process — in-memory)
    # NOT a distributed/production rate limiter: counters live in this
    # process only and reset on restart. See README “Security model”.
    RATE_LIMIT_ENABLED: bool = _bool("RATE_LIMIT_ENABLED", True)
    RATE_LIMIT_WINDOW_SECONDS: int = _int("RATE_LIMIT_WINDOW_SECONDS", 60)
    CHAT_RATE_LIMIT: int = _int("CHAT_RATE_LIMIT", 60)     # /api/chat per IP/window
    AUTH_RATE_LIMIT: int = _int("AUTH_RATE_LIMIT", 15)      # login/register per IP/window
    VOICE_RATE_LIMIT: int = _int("VOICE_RATE_LIMIT", 30)    # /api/voice/* per IP/window

    # ---------------- Request-size / input-length limits
    REQUEST_MAX_BYTES: int = _int("REQUEST_MAX_BYTES", 5 * 1024 * 1024)
    VOICE_UPLOAD_MAX_BYTES: int = _int("VOICE_UPLOAD_MAX_BYTES", 5 * 1024 * 1024)
    CHAT_MESSAGE_MAX_CHARS: int = _int("CHAT_MESSAGE_MAX_CHARS", 4000)
    SYNTHESIZE_TEXT_MAX_CHARS: int = _int("SYNTHESIZE_TEXT_MAX_CHARS", 5000)

    # ---------------- SQLite connection safety (Phase 9)
    # Applied to EVERY new SQLite connection via a SQLAlchemy "connect" hook
    # in app.database (see apply_sqlite_pragmas). SQLite-only: connections for
    # any other dialect are left untouched.
    # - Busy timeout: how long a writer waits for a locked database before
    #   raising "database is locked". Seconds (sqlite3 connect `timeout`).
    SQLITE_BUSY_TIMEOUT_SECONDS: float = max(
        0.0, _float("SQLITE_BUSY_TIMEOUT_SECONDS", 5.0)
    )
    # - Journal mode: "wal" (default) lets readers proceed while a writer
    #   commits — SQLite's per-database-file switch. `synchronous` is left at
    #   FULL (SQLite's durable default), so WAL does NOT weaken durability.
    #   Values outside the allowlist are ignored by the hook (SQLite keeps
    #   its default rollback-journal mode). The mode persists in the DB file
    #   once set; tests only ever set it on temporary databases.
    SQLITE_JOURNAL_MODE: str = _env("SQLITE_JOURNAL_MODE", "wal")

    # ---------------- Cookies
    # httpOnly + SameSite=Lax are set in code; Secure flips on automatically
    # for production (HTTPS) and can be forced with COOKIE_SECURE=true.
    COOKIE_SECURE: bool = _bool("COOKIE_SECURE", APP_ENV.lower() == "production")

    # ---------------- Account lockout (global auth, Phase 6)
    # After N CONSECUTIVE failed sign-ins on one existing account, lock it for
    # M minutes. Counters reset on a successful login. A locked account gets
    # the same generic error as a wrong password (no lock-detection oracle).
    # This brakes targeted password-spraying; the per-IP auth rate limit
    # already damps request volume. Set LOGIN_LOCKOUT_THRESHOLD=0 to disable.
    LOGIN_LOCKOUT_THRESHOLD: int = _int("LOGIN_LOCKOUT_THRESHOLD", 8)
    LOGIN_LOCKOUT_MINUTES: int = _int("LOGIN_LOCKOUT_MINUTES", 15)

    # ---------------- Serverless database (Turso / libSQL)
    # Only read when DATABASE_URL is a libSQL URL. Kept OUT of the URL string
    # so the token can never appear in logs, tracebacks or repr(engine).
    # Never commit this value; set it in the deployment environment only.
    TURSO_AUTH_TOKEN: str = _env("TURSO_AUTH_TOKEN", "")


settings = Settings()
