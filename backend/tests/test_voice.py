"""Phase 1 — voice endpoints stay customer-usable and abuse-resistant.

No staff login is required for voice (customer-facing by design); instead the
endpoints are rate-limited and size-limited. All external calls are
monkeypatched — these tests never hit NVIDIA/Groq/OpenAI.
"""

import pytest


def test_voice_respond_works_without_any_auth(app_module, client, monkeypatch):
    """Customer-facing voice turn: no cookie/login required (preserved)."""
    import app.main as main_mod

    def fake_chat(request, db=None, http_request=None, response=None, _rl=None):
        assert request.channel == "voice"
        return {
            "response": "Hello, I can help you find a home.",
            "detected_language": "en",
            "properties": [],
            "action": "search",
            "conversation_id": 1,
            "new_conversation": True,
        }

    monkeypatch.setattr(main_mod, "chat", fake_chat)
    r = client.post("/api/voice/respond", json={"message": "hello"})
    assert r.status_code == 200
    body = r.json()
    assert body["response"].startswith("Hello")
    assert body["audio_base64"] is None  # speak=false -> no TTS attempted


def test_voice_respond_oversized_message_422(app_module, client, monkeypatch):
    import app.main as main_mod

    def fail_chat(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("handler must not run for invalid payloads")

    monkeypatch.setattr(main_mod, "chat", fail_chat)
    from app.config import settings

    r = client.post(
        "/api/voice/respond",
        json={"message": "x" * (settings.CHAT_MESSAGE_MAX_CHARS + 1)},
    )
    assert r.status_code == 422


def test_voice_respond_rate_limited(app_module, client, monkeypatch):
    import app.main as main_mod
    from app.config import settings

    monkeypatch.setattr(settings, "VOICE_RATE_LIMIT", 1)
    monkeypatch.setattr(main_mod, "chat", lambda *a, **k: {"response": "ok"})

    assert client.post("/api/voice/respond", json={"message": "a"}).status_code == 200
    r2 = client.post("/api/voice/respond", json={"message": "b"})
    assert r2.status_code == 429
    assert "Retry-After" in r2.headers


def test_transcribe_empty_upload_400(client):
    r = client.post(
        "/api/voice/transcribe",
        files={"file": ("clip.webm", b"", "audio/webm")},
    )
    assert r.status_code == 400


def test_transcribe_upload_too_large_413(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "VOICE_UPLOAD_MAX_BYTES", 10)
    r = client.post(
        "/api/voice/transcribe",
        files={"file": ("clip.webm", b"0123456789ABCDEF", "audio/webm")},
    )
    assert r.status_code == 413


def test_synthesize_success_and_error_mapping(client, monkeypatch):
    import app.services.voice as voice_mod

    async def ok(*args, **kwargs):
        return b"RIFF....WAVE"

    async def runtime_err(*args, **kwargs):
        raise RuntimeError("voice provider not configured")

    async def value_err(*args, **kwargs):
        raise ValueError("unsupported language")

    monkeypatch.setattr(voice_mod, "synthesize_speech", ok)
    r = client.post("/api/voice/synthesize", json={"text": "vanakkam"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("audio/wav")
    assert r.content.startswith(b"RIFF")

    monkeypatch.setattr(voice_mod, "synthesize_speech", runtime_err)
    assert client.post(
        "/api/voice/synthesize", json={"text": "hi"}
    ).status_code == 502

    monkeypatch.setattr(voice_mod, "synthesize_speech", value_err)
    assert client.post(
        "/api/voice/synthesize", json={"text": "hi"}
    ).status_code == 400


def test_synthesize_rate_limited(client, monkeypatch):
    import app.services.voice as voice_mod
    from app.config import settings

    async def ok(*args, **kwargs):
        return b"RIFF"

    monkeypatch.setattr(voice_mod, "synthesize_speech", ok)
    monkeypatch.setattr(settings, "VOICE_RATE_LIMIT", 1)

    assert client.post(
        "/api/voice/synthesize", json={"text": "one"}
    ).status_code == 200
    r2 = client.post("/api/voice/synthesize", json={"text": "two"})
    assert r2.status_code == 429
