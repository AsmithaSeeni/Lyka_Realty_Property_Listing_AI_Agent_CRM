"""Phase 10 — NVIDIA customer-chat failure-path tests (fully mocked).

The real NVIDIA endpoint can NEVER be reached from this module: an autouse
guard replaces the shared httpx client with one that raises on any call, and
each test installs its own scripted fake. No API key is required.

Scenarios cover the exact behavior `chat_sync` promises: one safe retry for
5xx/connect errors, no retry for 429/read-timeouts/malformed bodies, canned
language-aware fallbacks, no fabrication of property facts, and no secret or
internal-detail leakage into customer-facing text or logs.
"""

import json
import logging

import httpx
import pytest

from app.ai.nvidia_client import NVIDIAClient

URL = "https://integrate.api.nvidia.com/v1/chat/completions"
FAKE_KEY = "nvapi-FAKE-KEY-PHASE10-SENTINEL"

# Distinctive strings that must never surface in customer text or logs.
LEAK_SENTINELS = (FAKE_KEY, "Bearer ", "Authorization")


def _resp(status=200, json_body=None, content=None):
    req = httpx.Request("POST", URL)
    if content is not None:
        return httpx.Response(status, content=content, request=req)
    return httpx.Response(status, json=json_body, request=req)


def _ok(content="Hello! How can I help?", finish="stop"):
    return _resp(200, {"choices": [{"message": {"content": content},
                                    "finish_reason": finish}]})


class _FakeClient:
    """Scripted httpx stand-in. `outcomes` is a list of Response or Exception
    objects; the last one repeats when more calls arrive than scripted."""

    is_closed = False

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def post(self, url, headers=None, json=None):
        assert url == URL, f"unexpected URL {url}"
        self.calls += 1
        outcome = self.outcomes.pop(0) if len(self.outcomes) > 1 else self.outcomes[0]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    """Any unscripted NVIDIA call in this module explodes loudly."""
    import app.ai.nvidia_client as nc

    class _Guard:
        is_closed = False

        def post(self, *a, **k):
            raise AssertionError("real NVIDIA network call attempted in tests")

    monkeypatch.setattr(nc, "_CLIENT", _Guard())
    yield


def _client(monkeypatch, outcomes, key=FAKE_KEY):
    import app.ai.nvidia_client as nc

    fake = _FakeClient(outcomes)
    monkeypatch.setattr(nc, "_CLIENT", fake)
    c = NVIDIAClient()
    monkeypatch.setattr(c, "api_key", key)
    return c, fake


def _assert_no_leaks(text, caplog):
    for sentinel in LEAK_SENTINELS:
        assert sentinel not in text, f"secret {sentinel!r} leaked to customer"
    assert sentinel_free(caplog.text), "secret leaked to logs"


def sentinel_free(log_text: str) -> bool:
    return FAKE_KEY not in log_text and "Bearer nvapi" not in log_text


# ---------------------------------------------------------------- success

def test_successful_reply_cleaned_and_single_call(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger="app.ai.nvidia_client")
    body = (
        "Sure, here's the thinking process: analyze... blah\n\n"
        "**Final answer:** Hello! Which area are you looking at?"
    )
    c, fake = _client(monkeypatch, [_ok(body)])
    out = c.chat_sync("sys", "hi", language="en")
    assert fake.calls == 1
    assert "Which area are you looking at?" in out
    assert "thinking process" not in out          # preamble scrubbed
    _assert_no_leaks(out, caplog)


def test_length_cap_tail_trimmed(monkeypatch):
    c, _ = _client(monkeypatch, [_ok("First sentence here. Second one cut off",
                                     finish="length")])
    out = c.chat_sync("sys", "hi", language="en")
    assert out == "First sentence here."


# ---------------------------------------------------------------- HTTP errors

def test_429_falls_back_without_retry(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger="app.ai.nvidia_client")
    c, fake = _client(monkeypatch, [_resp(429, {"error": "rate limited"})])
    out = c.chat_sync("sys", "hello there", language="en")
    assert fake.calls == 1, "429 must not be retried"
    assert out  # canned fallback
    assert "rate limited" not in out              # provider body never surfaces
    _assert_no_leaks(out, caplog)


def test_5xx_retried_once_then_fallback(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG, logger="app.ai.nvidia_client")
    c, fake = _client(monkeypatch, [_resp(500, content=b"boom")])
    out = c.chat_sync("sys", "hello there", language="en")
    assert fake.calls == 2, "5xx gets exactly one retry"
    assert out and "boom" not in out
    _assert_no_leaks(out, caplog)


def test_connect_error_retried_then_fallback(monkeypatch):
    c, fake = _client(monkeypatch, [httpx.ConnectError("connection refused")])
    out = c.chat_sync("sys", "hello there", language="en")
    assert fake.calls == 2
    assert out


def test_connect_timeout_retried_then_fallback(monkeypatch):
    c, fake = _client(monkeypatch, [httpx.ConnectTimeout("timed out")])
    out = c.chat_sync("sys", "hello there", language="en")
    assert fake.calls == 2
    assert out


def test_read_timeout_falls_back_without_retry(monkeypatch):
    """Read timeouts are deliberately NOT retried (slow path; documented)."""
    c, fake = _client(monkeypatch, [httpx.ReadTimeout("slow")])
    out = c.chat_sync("sys", "hello there", language="en")
    assert fake.calls == 1
    assert out


# ---------------------------------------------------------------- malformed bodies

def test_invalid_json_body_falls_back(monkeypatch):
    c, _ = _client(monkeypatch, [_resp(200, content=b"not-json{{{")])
    out = c.chat_sync("sys", "hello there", language="en")
    assert out


def test_empty_choices_falls_back(monkeypatch):
    c, _ = _client(monkeypatch, [_resp(200, {"choices": []})])
    out = c.chat_sync("sys", "hello there", language="en")
    assert out


def test_missing_choices_key_falls_back(monkeypatch):
    c, _ = _client(monkeypatch, [_resp(200, {"id": "x"})])
    out = c.chat_sync("sys", "hello there", language="en")
    assert out


@pytest.mark.parametrize("content", ["", "   ", "\n\n"])
def test_empty_or_whitespace_reply_falls_back(monkeypatch, content):
    """Phase 10 fix: a blank provider reply is a failure, never an empty
    customer-facing bubble."""
    c, _ = _client(monkeypatch, [_ok(content)])
    out = c.chat_sync("sys", "hello there", language="en")
    assert out and out.strip()


# ---------------------------------------------------------------- key handling

def test_missing_key_falls_back_with_zero_calls(monkeypatch):
    c, fake = _client(monkeypatch, [_ok("should not be used")], key="")
    out = c.chat_sync("sys", "hello there", language="en")
    assert fake.calls == 0
    assert out


# ---------------------------------------------------------------- honesty & language

def test_fallback_never_fabricates_property_facts(monkeypatch):
    """Canned fallbacks make no availability claims and quote no prices."""
    c, _ = _client(monkeypatch, [_resp(500, content=b"boom")])
    for msg in ("hello", "thanks a lot", "bye for now", "show me a villa"):
        out = c.chat_sync("sys", msg, language="en")
        assert "AED" not in out
        assert "available" not in out.lower()
        assert not any(ch.isdigit() for ch in out), "fallback quotes no numbers"


@pytest.mark.parametrize("lang", ["ta", "mixed", "ta-Latn"])
def test_tamil_family_fallbacks_use_tamil_canned(monkeypatch, lang):
    """ta / mixed / ta-Latn (Phase 10 fix) all get the Tamil canned reply."""
    c, _ = _client(monkeypatch, [_resp(500, content=b"boom")])
    out = c.chat_sync("sys", "hello", language=lang)
    tamil_chars = sum(1 for ch in out if "ீ" <= ch <= "௿")
    assert tamil_chars > 20


@pytest.mark.parametrize("lang", ["en", "auto"])
def test_english_fallback_unchanged(monkeypatch, lang):
    c, _ = _client(monkeypatch, [_resp(500, content=b"boom")])
    out = c.chat_sync("sys", "hello", language=lang)
    assert "LykAI" in out
    assert not any("ீ" <= ch <= "௿" for ch in out)


def test_thinking_contract_locked():
    c = NVIDIAClient()
    assert c.should_think("en") is False
    assert c.should_think("ta-Latn") is False
    assert c.should_think("ta") is True
    assert c.should_think("mixed") is True
