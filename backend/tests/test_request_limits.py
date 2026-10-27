"""Phase 1 — request-size and input-length limits.

All checks run before any business logic, so no LLM/network call happens for
invalid payloads (asserted via a monkeypatched chat that would fail loudly).
"""

import pytest

from app.config import settings


def test_oversized_chat_message_rejected_422(client, monkeypatch):
    monkeypatch.setattr(settings, "CHAT_RATE_LIMIT", 0)  # isolate: no 429 here
    body = {"message": "x" * (settings.CHAT_MESSAGE_MAX_CHARS + 1)}
    r = client.post("/api/chat", json=body)
    assert r.status_code == 422
    assert "detail" in r.json()


def test_empty_chat_message_rejected(client):
    r = client.post("/api/chat", json={"message": ""})
    assert r.status_code == 422


def test_wrong_type_chat_message_rejected(client):
    r = client.post("/api/chat", json={"message": 12345})
    assert r.status_code == 422


def test_body_larger_than_content_limit_rejected_413(client, monkeypatch):
    monkeypatch.setattr(settings, "REQUEST_MAX_BYTES", 512)
    r = client.post("/api/chat", json={"message": "y" * 2000})
    assert r.status_code == 413
    assert r.json() == {"detail": "Request body too large"}


def test_size_guard_does_not_affect_get(client):
    monkeypatch_limit = settings.REQUEST_MAX_BYTES
    try:
        settings.REQUEST_MAX_BYTES = 1  # any GET must still work
        r = client.get("/api/health")
        assert r.status_code == 200
    finally:
        settings.REQUEST_MAX_BYTES = monkeypatch_limit


def test_oversized_synthesize_text_rejected(client):
    body = {"text": "z" * (settings.SYNTHESIZE_TEXT_MAX_CHARS + 1)}
    r = client.post("/api/voice/synthesize", json=body)
    assert r.status_code == 422


def test_chat_request_model_enforces_bounds():
    """Normal messages pass; over-long/empty fail at the schema level."""
    import pytest
    from pydantic import ValidationError

    from app.main import ChatRequest

    req = ChatRequest(message="hello there")
    assert req.message == "hello there"

    with pytest.raises(ValidationError):
        ChatRequest(message="x" * (settings.CHAT_MESSAGE_MAX_CHARS + 1))
    with pytest.raises(ValidationError):
        ChatRequest(message="")
