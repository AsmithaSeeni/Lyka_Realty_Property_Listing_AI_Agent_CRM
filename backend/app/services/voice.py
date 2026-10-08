"""Voice pipeline services: Speech-to-Text, AI response, Text-to-Speech.

Providers/models/keys are read from .env:
  STT_PROVIDER, STT_MODEL, STT_API_KEY   (e.g. groq / whisper-large-v3-turbo)
  TTS_PROVIDER, TTS_MODEL, TTS_VOICE,
  TTS_API_KEY                            (e.g. nvidia / magpie-tts-multilingual / mia)
"""
import os
import logging
import tempfile
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Accept common browser audio extensions
ALLOWED_EXTENSIONS = {".webm", ".mp3", ".wav", ".m4a", ".ogg", ".flac", ".mp4"}


def _stt_config():
    return (
        os.getenv("STT_PROVIDER", "groq").lower(),
        os.getenv("STT_MODEL", "whisper-large-v3-turbo"),
        os.getenv("STT_API_KEY", ""),
    )


def _tts_config():
    return (
        os.getenv("TTS_PROVIDER", "nvidia").lower(),
        os.getenv("TTS_MODEL", "magpie-tts-multilingual"),
        os.getenv("TTS_VOICE", "mia"),
        os.getenv("TTS_API_KEY", ""),
    )


async def transcribe_audio(audio_bytes: bytes, filename: str = "audio.webm",
                           language: Optional[str] = None) -> dict:
    """
    Speech-to-Text. Sends the recorded audio to the configured STT provider.
    Returns {"text": str, "language": str|None} or raises with a friendly error.
    """
    provider, model, api_key = _stt_config()
    if not api_key:
        raise RuntimeError("STT API key is not configured (.env STT_API_KEY)")

    ext = os.path.splitext(filename or "")[1].lower() or ".webm"
    if ext not in ALLOWED_EXTENSIONS:
        ext = ".webm"

    try:
        if provider == "groq":
            return await _transcribe_groq(model, api_key, audio_bytes, filename, ext, language)
        elif provider == "openai":
            return await _transcribe_openai_compatible(
                "https://api.openai.com/v1", model, api_key, audio_bytes, filename, ext, language
            )
        elif provider == "nvidia":
            return await _transcribe_openai_compatible(
                "https://integrate.api.nvidia.com/v1", model, api_key, audio_bytes, filename, ext, language
            )
        else:
            raise RuntimeError(f"Unsupported STT provider: {provider}")
    except httpx.HTTPStatusError as e:
        body = e.response.text[:300]
        logger.error("STT HTTP %s: %s", e.response.status_code, body)
        raise RuntimeError(f"Speech-to-text failed ({e.response.status_code})") from e


async def _transcribe_groq(model, api_key, audio_bytes, filename, ext, language):
    url = "https://api.groq.com/openai/v1/audio/transcriptions"
    headers = {"Authorization": f"Bearer {api_key}"}
    data = {"model": model, "response_format": "json"}
    if language:
        # Map friendly codes to whisper language codes
        data["language"] = {"en": "en", "ta": "ta"}.get(language, language)
    files = {"file": (f"recording{ext}", audio_bytes, "application/octet-stream")}

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, headers=headers, data=data, files=files)
        resp.raise_for_status()
        result = resp.json()
    text = (result.get("text") or "").strip()
    return {"text": text, "language": result.get("language") or language}


async def _transcribe_openai_compatible(base_url, model, api_key, audio_bytes, filename, ext, language):
    url = f"{base_url}/audio/transcriptions"
    headers = {"Authorization": f"Bearer {api_key}"}
    data = {"model": model, "response_format": "json"}
    if language:
        data["language"] = {"en": "en", "ta": "ta"}.get(language, language)
    files = {"file": (f"recording{ext}", audio_bytes, "application/octet-stream")}

    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(url, headers=headers, data=data, files=files)
        resp.raise_for_status()
        result = resp.json()
    text = (result.get("text") or "").strip()
    return {"text": text, "language": result.get("language") or language}


async def synthesize_speech(text: str, voice: Optional[str] = None,
                            language: Optional[str] = None) -> bytes:
    """
    Text-to-Speech. Returns audio bytes (WAV/MP3 depending on provider).
    """
    provider, model, default_voice, api_key = _tts_config()
    if not api_key:
        raise RuntimeError("TTS API key is not configured (.env TTS_API_KEY)")
    voice = voice or default_voice
    if not text or not text.strip():
        raise ValueError("No text provided for synthesis")

    # Trim very long replies for snappier voice responses
    speak_text = text.strip()
    if len(speak_text) > 1200:
        speak_text = speak_text[:1200].rsplit(" ", 1)[0] + "..."

    try:
        if provider in ("nvidia", "openai"):
            base = (
                "https://integrate.api.nvidia.com/v1"
                if provider == "nvidia"
                else "https://api.openai.com/v1"
            )
            return await _tts_openai_compatible(base, model, api_key, voice, speak_text, language)
        else:
            raise RuntimeError(f"Unsupported TTS provider: {provider}")
    except httpx.HTTPStatusError as e:
        body = e.response.text[:300]
        logger.error("TTS HTTP %s: %s", e.response.status_code, body)
        raise RuntimeError(f"Speech synthesis failed ({e.response.status_code})") from e


async def _tts_openai_compatible(base_url, model, api_key, voice, text, language):
    url = f"{base_url}/audio/speech"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "voice": voice,
        "input": text,
        "response_format": "wav",
    }
    # Some multilingual models accept a language hint
    if language in ("ta", "ta-Latn", "en"):
        payload["language"] = {"ta-Latn": "ta"}.get(language, language)

    async with httpx.AsyncClient(timeout=90.0) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        return resp.content
