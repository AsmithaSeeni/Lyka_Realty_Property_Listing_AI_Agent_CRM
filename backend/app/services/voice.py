"""Voice pipeline services: Speech-to-Text, AI response, Text-to-Speech.

Providers/models/keys are read from .env:
  STT_PROVIDER, STT_MODEL, STT_API_KEY   (e.g. groq / whisper-large-v3-turbo)
  TTS_PROVIDER, TTS_MODEL, TTS_VOICE,
  TTS_API_KEY                            (e.g. nvidia / magpie-tts-multilingual / mia)
"""
import os
import logging
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Accept common browser audio extensions
ALLOWED_EXTENSIONS = {".webm", ".mp3", ".wav", ".m4a", ".ogg", ".flac", ".mp4"}

# Provider call budget: the backend runs under a 30s serverless function cap
# (vercel.json maxDuration), so provider HTTP calls get a 25s ceiling — a hung
# provider surfaces as a clean 502 instead of a killed invocation.
_PROVIDER_TIMEOUT_SECONDS = 25.0


def _stt_config():
    provider = os.getenv("STT_PROVIDER", "").lower()
    sarvam_key = os.getenv("SARVAM_API_KEY", "")
    stt_key = os.getenv("STT_API_KEY", "")
    if provider == "sarvam" or (sarvam_key and provider == "sarvam"):
        return (
            "sarvam",
            os.getenv("STT_MODEL", "saaras:v1"),
            sarvam_key or stt_key,
        )
    return (
        provider or "groq",
        os.getenv("STT_MODEL", "whisper-large-v3-turbo"),
        stt_key,
    )


def _tts_config():
    provider = os.getenv("TTS_PROVIDER", "edge-tts").lower()
    sarvam_key = os.getenv("SARVAM_API_KEY", "")
    tts_key = os.getenv("TTS_API_KEY", "")
    if provider in ("edge-tts", "edge", "free", "microsoft"):
        return (
            "edge-tts",
            os.getenv("TTS_MODEL", "edge-tts"),
            os.getenv("TTS_VOICE", "ta-IN-PallaviNeural"),
            "",
        )
    if provider == "sarvam" or (sarvam_key and (not provider or provider == "sarvam")):
        return (
            "sarvam",
            os.getenv("TTS_MODEL", "bulbul:v1"),
            os.getenv("TTS_VOICE", "meera"),
            sarvam_key or tts_key,
        )
    return (
        provider or "edge-tts",
        os.getenv("TTS_MODEL", "edge-tts" if not tts_key else "magpie-tts-multilingual"),
        os.getenv("TTS_VOICE", "ta-IN-PallaviNeural" if not tts_key else "mia"),
        tts_key,
    )


async def transcribe_audio(audio_bytes: bytes, filename: str = "audio.webm",
                           language: Optional[str] = None) -> dict:
    """
    Speech-to-Text. Sends the recorded audio to the configured STT provider.
    Returns {"text": str, "language": str|None} or raises with a friendly error.
    """
    provider, model, api_key = _stt_config()
    if not api_key:
        raise RuntimeError("STT API key is not configured (.env STT_API_KEY or SARVAM_API_KEY)")

    ext = os.path.splitext(filename or "")[1].lower() or ".webm"
    if ext not in ALLOWED_EXTENSIONS:
        ext = ".webm"

    try:
        if provider == "sarvam":
            return await _transcribe_sarvam(api_key, model, audio_bytes, filename, ext, language)
        elif provider == "groq":
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
        data["language"] = {"en": "en", "ta": "ta", "ta-Latn": "ta"}.get(language, language)
    files = {"file": (f"recording{ext}", audio_bytes, "application/octet-stream")}

    async with httpx.AsyncClient(timeout=_PROVIDER_TIMEOUT_SECONDS) as client:
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
        data["language"] = {"en": "en", "ta": "ta", "ta-Latn": "ta"}.get(language, language)
    files = {"file": (f"recording{ext}", audio_bytes, "application/octet-stream")}

    async with httpx.AsyncClient(timeout=_PROVIDER_TIMEOUT_SECONDS) as client:
        resp = await client.post(url, headers=headers, data=data, files=files)
        resp.raise_for_status()
        result = resp.json()
    text = (result.get("text") or "").strip()
    return {"text": text, "language": result.get("language") or language}


async def synthesize_speech(text: str, voice: Optional[str] = None,
                            language: Optional[str] = None) -> bytes:
    """
    Text-to-Speech. Returns audio bytes (MP3/WAV depending on provider).
    Defaults to free neural female voices (e.g. ta-IN-PallaviNeural).
    """
    provider, model, default_voice, api_key = _tts_config()
    voice = voice or default_voice
    if not text or not text.strip():
        raise ValueError("No text provided for synthesis")

    # If provider requires an API key but none is configured, fall back to free edge-tts
    if provider not in ("edge-tts", "edge", "free", "microsoft") and not api_key:
        logger.info("TTS key not set for '%s', falling back to free Edge-TTS", provider)
        provider = "edge-tts"

    # Trim very long replies for snappier voice responses
    speak_text = text.strip()
    if len(speak_text) > 1200:
        speak_text = speak_text[:1200].rsplit(" ", 1)[0] + "..."

    try:
        if provider in ("edge-tts", "edge", "free", "microsoft"):
            return await _tts_edge(voice, speak_text, language)
        elif provider == "sarvam":
            return await _tts_sarvam(api_key, model, voice, speak_text, language)
        elif provider in ("nvidia", "openai"):
            base = (
                "https://integrate.api.nvidia.com/v1"
                if provider == "nvidia"
                else "https://api.openai.com/v1"
            )
            return await _tts_openai_compatible(base, model, api_key, voice, speak_text, language)
        else:
            return await _tts_edge(voice, speak_text, language)
    except Exception as e:
        logger.warning(
            "Primary TTS provider '%s' failed: %s. Falling back to free Edge-TTS female voice.",
            provider, e
        )
        try:
            return await _tts_edge("ta-IN-PallaviNeural", speak_text, language)
        except Exception as fallback_err:
            logger.error("Edge-TTS fallback also failed: %s", fallback_err)
            raise RuntimeError(f"Speech synthesis failed ({e})") from e


async def _tts_edge(voice: Optional[str], text: str, language: Optional[str] = None) -> bytes:
    """Free Edge-TTS with expressive neural female voice for Tanglish and Indian languages."""
    import edge_tts

    selected_voice = voice
    if not selected_voice or selected_voice.lower() in ("mia", "default", "female", "edge-tts", "none"):
        has_tamil_script = any('\u0B80' <= c <= '\u0BFF' for c in text)
        selected_voice = "ta-IN-PallaviNeural" if has_tamil_script else "en-IN-NeerjaExpressiveNeural"

    # Pre-clean speech text for warm, humanic, non-robotic pronunciation
    import re
    clean_speech = re.sub(r"\bLykAI\b", "Like AI", text)
    clean_speech = re.sub(r"(\d+)BHK\b", r"\1 BHK", clean_speech)
    clean_speech = re.sub(r"[*_#`~>\[\]\(\)]", " ", clean_speech)
    # NOTE: use Python \U0001F600-style escapes — the JS-style \u{...} form
    # raises re.error ("incomplete escape \u") in Python and broke ALL TTS.
    clean_speech = re.sub(r"[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\u2600-\u26FF\u2700-\u27BF]", "", clean_speech)
    clean_speech = re.sub(r"\s+", " ", clean_speech).strip()
    if not clean_speech:
        clean_speech = text

    communicate = edge_tts.Communicate(clean_speech, selected_voice, rate="+2%", pitch="+1Hz")
    chunks = []
    async for chunk in communicate.stream():
        if chunk.get("type") == "audio":
            chunks.append(chunk["data"])
    if not chunks:
        raise RuntimeError(f"Edge-TTS returned no audio data for voice '{selected_voice}'")
    return b"".join(chunks)


async def _tts_sarvam(api_key: str, model: str, voice: str, text: str, language: Optional[str] = None) -> bytes:
    """Sarvam AI Text-to-Speech API (bulbul:v1) with female voice (meera/pavithra/ananya)."""
    import base64
    url = "https://api.sarvam.ai/text-to-speech"
    headers = {
        "api-subscription-key": api_key,
        "Content-Type": "application/json",
    }
    # Default to 'meera' (warm female voice)
    speaker = voice if voice in ("meera", "pavithra", "ananya", "arvind", "amartya") else "meera"
    # Target language code: ta-IN (Tamil) or en-IN (Indian English / Tanglish)
    target_lang = "ta-IN" if language in ("ta", "ta-IN") else "en-IN"
    payload = {
        "inputs": [text],
        "target_language_code": target_lang,
        "speaker": speaker,
        "pitch": 0,
        "pace": 1.0,
        "loudness": 1.5,
        "speech_sample_rate": 22050,
        "enable_preprocessing": True,
        "model": model or "bulbul:v1",
    }
    async with httpx.AsyncClient(timeout=_PROVIDER_TIMEOUT_SECONDS) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        audios = data.get("audios", [])
        if not audios:
            raise RuntimeError("Sarvam TTS returned empty audio response")
        return base64.b64decode(audios[0])


async def _transcribe_sarvam(api_key: str, model: str, audio_bytes: bytes, filename: str, ext: str, language: Optional[str] = None) -> dict:
    """Sarvam AI Speech-to-Text API (saaras:v1)."""
    url = "https://api.sarvam.ai/speech-to-text"
    headers = {"api-subscription-key": api_key}
    files = {"file": (f"recording{ext}", audio_bytes, "application/octet-stream")}
    data = {
        "model": model or "saaras:v1",
        "language_code": "ta-IN" if language in ("ta", "ta-IN") else "unknown",
    }
    async with httpx.AsyncClient(timeout=_PROVIDER_TIMEOUT_SECONDS) as client:
        resp = await client.post(url, headers=headers, data=data, files=files)
        resp.raise_for_status()
        result = resp.json()
        return {"text": (result.get("transcript") or "").strip(), "language": result.get("language_code") or language}


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

    async with httpx.AsyncClient(timeout=_PROVIDER_TIMEOUT_SECONDS) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        return resp.content
