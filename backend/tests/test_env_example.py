"""Phase 1 — secrets hygiene.

- .env.example holds placeholders ONLY (no credential values).
- Required variables for current + planned phases are documented.
- .env stays ignored/untracked by Git.
- .gitignore covers .env and database files.
"""

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

SECRET_VALUE_PATTERNS = re.compile(
    r"nvapi-[0-9A-Za-z]{8,}"          # NVIDIA
    r"|sk-[0-9A-Za-z]{20,}"           # OpenAI-style
    r"|AKIA[0-9A-Z]{16}"              # AWS
    r"|ghp_[0-9A-Za-z]{30,}"          # GitHub
    r"|AIza[0-9A-Za-z_-]{30,}"        # Google
)

REQUIRED_KEYS = {
    # runtime
    "APP_ENV", "DEBUG",
    # existing NVIDIA chat
    "NVIDIA_API_KEY", "NVIDIA_MODEL",
    # planned OpenAI extraction phase
    "OPENAI_API_KEY", "OPENAI_MODEL",
    # voice
    "STT_PROVIDER", "STT_API_KEY", "STT_MODEL",
    "TTS_PROVIDER", "TTS_API_KEY", "TTS_MODEL", "TTS_VOICE",
    "SARVAM_API_KEY",
    # database
    "DATABASE_URL",
    # seeding
    "SEED_ADMIN_EMAIL", "SEED_ADMIN_USERNAME", "SEED_ADMIN_NAME",
    "SEED_ADMIN_PASSWORD", "SEED_AGENT_EMAIL", "SEED_AGENT_USERNAME",
    "SEED_AGENT_NAME", "SEED_AGENT_PASSWORD",
    # security settings
    "CORS_ORIGINS", "RATE_LIMIT_ENABLED", "RATE_LIMIT_WINDOW_SECONDS",
    "CHAT_RATE_LIMIT", "AUTH_RATE_LIMIT", "VOICE_RATE_LIMIT",
    "REQUEST_MAX_BYTES", "VOICE_UPLOAD_MAX_BYTES",
    "CHAT_MESSAGE_MAX_CHARS", "SYNTHESIZE_TEXT_MAX_CHARS",
    "COOKIE_SECURE",
}

SECRET_KEYS = {
    "NVIDIA_API_KEY", "OPENAI_API_KEY", "STT_API_KEY", "TTS_API_KEY",
    "SARVAM_API_KEY",
    "SEED_ADMIN_PASSWORD", "SEED_AGENT_PASSWORD",
}


def _parse_env_example():
    entries = {}
    for raw in (REPO / ".env.example").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        assert "=" in line, f"malformed line in .env.example: {line!r}"
        key, _, value = line.partition("=")
        entries[key.strip()] = value.strip()
    return entries


def test_env_example_all_required_keys_present():
    entries = _parse_env_example()
    missing = REQUIRED_KEYS - set(entries)
    assert not missing, f".env.example missing keys: {sorted(missing)}"


def test_env_example_secret_keys_are_empty_placeholders():
    entries = _parse_env_example()
    for key in SECRET_KEYS:
        assert key in entries, f"missing {key}"
        assert entries[key] == "", f"{key} must be a placeholder, not a value"


def test_env_example_contains_no_secret_looking_values():
    text = (REPO / ".env.example").read_text(encoding="utf-8")
    match = SECRET_VALUE_PATTERNS.search(text)
    assert match is None, "a secret-looking value is present in .env.example"


def test_env_is_gitignored_and_untracked():
    ignore = (REPO / ".gitignore").read_text(encoding="utf-8")
    lines = [ln.strip() for ln in ignore.splitlines()]
    assert ".env" in lines, ".env must be in .gitignore"
    assert any(ln.startswith("*.db") for ln in lines), "*.db must be ignored"

    # and git agrees it is neither tracked nor ignored-with-force
    tracked = subprocess.run(
        ["git", "ls-files", ".env"],
        cwd=str(REPO), capture_output=True, text=True, timeout=30,
    )
    assert tracked.stdout.strip() == "", ".env must not be tracked by git"

    check = subprocess.run(
        ["git", "check-ignore", "-q", ".env"],
        cwd=str(REPO), capture_output=True, timeout=30,
    )
    assert check.returncode == 0, ".env must be ignored by git"


def test_database_files_not_tracked():
    tracked = subprocess.run(
        ["git", "ls-files", "*.db", "*.sqlite", "*.sqlite3"],
        cwd=str(REPO), capture_output=True, text=True, timeout=30,
    )
    assert tracked.stdout.strip() == "", (
        f"database files are tracked: {tracked.stdout}"
    )
