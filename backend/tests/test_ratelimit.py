"""Phase 1 — rate limiting.

- Unit: sliding-window logic (limit, window reset, disabled bucket).
- Wiring: every expensive endpoint carries the rate-limit dependency.
- Behaviour: excessive requests get 429 + Retry-After in the normal
  {"detail": ...} error shape (on a cheap, network-free endpoint).
"""

import pytest
from fastapi import HTTPException

from app.config import settings
from app.services.ratelimit import SlidingWindowLimiter, rate_limit


# ------------------------------ unit ------------------------------

def test_limiter_blocks_after_limit_then_recovers():
    t = {"now": 1000.0}
    lim = SlidingWindowLimiter(clock=lambda: t["now"])

    for _ in range(3):
        allowed, retry = lim.hit("k", 3, 60)
        assert allowed is True and retry == 0

    allowed, retry = lim.hit("k", 3, 60)
    assert allowed is False
    assert retry >= 1

    t["now"] += 61  # slide past the window
    allowed, _ = lim.hit("k", 3, 60)
    assert allowed is True


def test_limiter_disabled_when_limit_zero():
    lim = SlidingWindowLimiter(clock=lambda: 0.0)
    for _ in range(100):
        allowed, _ = lim.hit("k", 0, 60)
        assert allowed is True


def test_limiter_keys_are_independent():
    t = {"now": 0.0}
    lim = SlidingWindowLimiter(clock=lambda: t["now"])
    assert lim.hit("a", 1, 60)[0] is True
    assert lim.hit("a", 1, 60)[0] is False
    assert lim.hit("b", 1, 60)[0] is True


def test_unknown_limit_setting_is_rejected_at_wiring_time():
    with pytest.raises(RuntimeError):
        rate_limit("chat", "DOES_NOT_EXIST")


# --------------------------- route wiring ---------------------------

EXPECTED_SETTINGS = {
    "chat": "CHAT_RATE_LIMIT",
    "auth": "AUTH_RATE_LIMIT",
    "voice": "VOICE_RATE_LIMIT",
}

EXPECTED = {
    "/api/chat": "chat",
    "/api/voice/respond": "voice",
    "/api/voice/synthesize": "voice",
    "/api/voice/transcribe": "voice",
    "/api/auth/login": "auth",
    "/api/customer/login": "auth",
    "/api/customer/register": "auth",
}


def test_expensive_routes_carry_rate_limit_dependency(app_module):
    routes = {r.path: r for r in app_module.app.routes if hasattr(r, "path")}
    for path, bucket in EXPECTED.items():
        assert path in routes, f"route missing: {path}"
        deps = [d.call for d in routes[path].dependant.dependencies]
        markers = [(getattr(d, "bucket", None), getattr(d, "limit_setting", None))
                   for d in deps]
        assert (bucket, EXPECTED_SETTINGS[bucket]) in markers, (
            f"{path} is not rate-limited with bucket={bucket} "
            f"(found {markers})"
        )


# --------------------------- live behaviour ---------------------------

def test_auth_endpoint_rate_limited_429_with_retry_after(client, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_RATE_LIMIT", 2)

    payload = {"username": "nobody@lykarealty.ae", "password": "WrongPass!1"}
    r1 = client.post("/api/auth/login", json=payload)
    r2 = client.post("/api/auth/login", json=payload)
    assert r1.status_code == 401 and r2.status_code == 401  # normal failures

    r3 = client.post("/api/auth/login", json=payload)
    assert r3.status_code == 429
    assert "detail" in r3.json()
    assert "Retry-After" in r3.headers
    assert int(r3.headers["Retry-After"]) >= 1


def test_rate_limiting_can_be_disabled(client, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_RATE_LIMIT", 1)
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", False)
    payload = {"username": "nobody@lykarealty.ae", "password": "WrongPass!1"}
    for _ in range(4):
        assert client.post("/api/auth/login", json=payload).status_code == 401


def test_dependency_raises_429_directly(monkeypatch):
    """The dependency itself (what /api/chat uses) enforces the limit."""
    monkeypatch.setattr(settings, "CHAT_RATE_LIMIT", 1)
    dep = rate_limit("chat", "CHAT_RATE_LIMIT")

    class FakeRequest:
        client = type("C", (), {"host": "9.9.9.9"})()

    dep(FakeRequest())  # first hit passes
    with pytest.raises(HTTPException) as exc:
        dep(FakeRequest())
    assert exc.value.status_code == 429
    assert "Retry-After" in exc.value.headers
