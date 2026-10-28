"""Tests for Sarvam AI Bulbul v4 Flash Text-to-Speech integration.

Verifies:
- Successful synthesis with Sarvam Bulbul v4 Flash (Neha voice).
- Proper request payload (model, speaker, target_language_code, sample rate, pace).
- Missing API key produces a clear, safe 502 error without fake audio.
- Upstream Sarvam failure does not break text chat turns.
- Empty or whitespace-only input returns 400 Bad Request.
- Oversized input returns 422 Unprocessable Entity.
- Text cleaning for natural speech synthesis (emojis, markdown, internal notes).
- Modular language separation (Tamil vs English).
All external API calls are mocked — zero live credits consumed.
"""

import base64
import pytest
import httpx
from app.config import settings
import app.services.voice as voice_mod


@pytest.fixture(autouse=True)
def clean_sarvam_env(monkeypatch):
    """Ensure tests run with predictable environment defaults."""
    monkeypatch.setenv("TTS_PROVIDER", "sarvam")
    monkeypatch.setenv("TTS_MODEL", "bulbul:v4-flash")
    monkeypatch.setenv("TTS_VOICE", "neha_mr_narration")
    monkeypatch.setenv("SARVAM_API_KEY", "dummy-sarvam-key-for-testing")


def test_clean_speech_text():
    """Verify pre-cleaning prepares natural text for Bulbul v4 Flash."""
    raw = (
        "[internal note: customer is high net worth] "
        "Welcome to **LykAI**! We have a gorgeous 3BHK villa in Dubai Marina "
        "#luxury #dubai 😊🏖️ for AED 3,500,000."
    )
    cleaned = voice_mod._clean_speech_text(raw)
    assert "[internal" not in cleaned
    assert "😊" not in cleaned
    assert "🏖️" not in cleaned
    assert "**" not in cleaned
    assert "#" not in cleaned
    assert "Like AI" in cleaned
    assert "3 BHK" in cleaned
    assert "Dubai Marina" in cleaned


def test_sarvam_tts_success(client, monkeypatch):
    """Verify successful Bulbul v4 Flash call with Neha voice and correct parameters."""
    captured_payload = {}
    captured_headers = {}

    fake_audio_bytes = b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x80>\x00\x00"
    b64_audio = base64.b64encode(fake_audio_bytes).decode("ascii")

    async def fake_post(self, url, headers=None, json=None, **kwargs):
        captured_payload.update(json or {})
        captured_headers.update(headers or {})
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            json={"audios": [b64_audio], "request_id": "req-12345"},
            headers={"Content-Type": "application/json"},
            request=request,
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    response = client.post(
        "/api/voice/synthesize",
        json={"text": "Hello! Welcome to Lyka Realty Dubai."},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/wav")
    assert response.content == fake_audio_bytes

    # Validate target parameters as required by Sarvam Bulbul v4 Flash
    assert captured_payload["model"] == "bulbul:v4-flash"
    assert captured_payload["speaker"] == "neha_mr_narration"
    assert captured_payload["target_language_code"] == "en-IN"
    assert captured_payload["pace"] == 1.0
    assert captured_payload["speech_sample_rate"] == 24000
    assert captured_payload["enable_preprocessing"] is True
    assert captured_headers["api-subscription-key"] == "dummy-sarvam-key-for-testing"


def test_sarvam_tts_missing_api_key_safe_error(client, monkeypatch):
    """Missing SARVAM_API_KEY must produce a clear, safe 502 without fake audio."""
    monkeypatch.setenv("SARVAM_API_KEY", "")
    monkeypatch.setenv("TTS_API_KEY", "")

    response = client.post(
        "/api/voice/synthesize",
        json={"text": "Hello! Welcome to Lyka Realty."},
    )

    assert response.status_code == 502
    assert "SARVAM_API_KEY" in response.json().get("detail", "")


def test_sarvam_tts_upstream_failure_does_not_break_text_chat(client, monkeypatch):
    """When Sarvam API fails, text chat response must succeed with audio_base64=None."""
    import app.main as main_mod

    def fake_chat(request, db=None, http_request=None, response=None, _rl=None):
        return {
            "response": "Certainly! I have 3 luxury villas in Palm Jumeirah available.",
            "detected_language": "en",
            "reply_language": "en",
            "properties": [],
            "conversation_id": 99,
        }

    async def failing_post(self, url, **kwargs):
        request = httpx.Request("POST", url)
        return httpx.Response(500, text="Internal Server Error at Sarvam", request=request)

    monkeypatch.setattr(main_mod, "chat", fake_chat)
    monkeypatch.setattr(httpx.AsyncClient, "post", failing_post)

    # Customer sends voice request with speak=True
    r = client.post(
        "/api/voice/respond",
        json={"message": "Show me villas in Palm Jumeirah", "speak": True},
    )

    assert r.status_code == 200
    body = r.json()
    # The text response must be intact and helpful
    assert "Palm Jumeirah" in body["response"]
    # Audio synthesis gracefully failed without breaking the conversation
    assert body["audio_base64"] is None
    assert body["audio_format"] is None


def test_sarvam_tts_empty_and_oversized_input(client):
    """Empty text is rejected with 400; oversized text is rejected with 422."""
    # Empty text
    r_empty = client.post("/api/voice/synthesize", json={"text": "   "})
    assert r_empty.status_code == 400

    # Oversized text exceeding SYNTHESIZE_TEXT_MAX_CHARS
    r_oversized = client.post(
        "/api/voice/synthesize",
        json={"text": "x" * (settings.SYNTHESIZE_TEXT_MAX_CHARS + 1)},
    )
    assert r_oversized.status_code == 422


def test_sarvam_tts_tamil_modular_separation(monkeypatch):
    """Tamil text must target ta-IN and modular Tamil voice, never silently sending Tamil to Neha."""
    captured_payload = {}

    async def fake_post(self, url, headers=None, json=None, **kwargs):
        captured_payload.update(json or {})
        request = httpx.Request("POST", url)
        return httpx.Response(
            200,
            json={"audios": [base64.b64encode(b"RIFFtamil").decode("ascii")]},
            request=request,
        )

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    import asyncio
    audio = asyncio.run(
        voice_mod.synthesize_speech("வணக்கம்! Lyka Realtyக்கு வரவேற்கிறோம்.", language="ta")
    )
    assert audio == b"RIFFtamil"
    assert captured_payload["target_language_code"] == "ta-IN"
    assert captured_payload["speaker"] != "neha_mr_narration"
