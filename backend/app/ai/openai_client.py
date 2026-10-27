"""OpenAI chat-completions client — Phase 3 structured lead extraction ONLY.

Isolation contract:
- Reads ONLY the ``OPENAI_*`` settings (app.config). It never touches
  NVIDIA_* configuration, prompts or clients — ``app/ai/nvidia_client.py``
  and ``app/ai/agent.py`` remain the untouched customer-facing chat path.
- Uses the already-pinned ``httpx`` dependency (no new runtime deps).

Safety contract:
- Never logs the API key, authorization headers, the customer enquiry, or
  raw provider response bodies (only status codes, lengths, durations).
- Never retries indefinitely: at most ONE bounded retry, and only for
  transient failures (timeout / 429 / 5xx). 401/403 and other 4xx fail
  immediately.
- Never fabricates a successful result: every failure raises
  ``OpenAIClientError`` with a safe, structured code + message.
- The HTTP seam (``_post``) is a module-level function so unit tests can
  mock provider responses without any real network call.
"""

import json
import logging
import time
from typing import Any, Dict

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Backoff between the two bounded attempts (module-level so tests can zero it).
_RETRY_BACKOFF_SECONDS = 0.5

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}

_SAFE_MESSAGES = {
    "missing_config": "Extraction service is not configured",
    "auth_error": "Extraction provider rejected the configured credentials",
    "rate_limited": "Extraction provider is rate limiting requests",
    "timeout": "Extraction request timed out",
    "provider_error": "Extraction provider is unavailable",
    "malformed_response": "Extraction provider returned an unreadable result",
}


class OpenAIClientError(Exception):
    """Controlled, safe-to-surface provider failure.

    ``code`` is machine-readable; ``message`` is user-safe — neither ever
    contains the API key, headers, enquiry text or provider internals.
    """

    def __init__(self, code: str, message: str = ""):
        super().__init__(message or _SAFE_MESSAGES.get(code, "Extraction failed"))
        self.code = code
        self.message = message or _SAFE_MESSAGES.get(code, "Extraction failed")


def _post(url: str, headers: Dict[str, str], json_body: Dict[str, Any],
          timeout: float) -> httpx.Response:
    """HTTP seam — unit tests monkeypatch this; no real calls in normal tests."""
    with httpx.Client(timeout=timeout) as client:
        return client.post(url, headers=headers, json=json_body)


def _parse_chat_json(response: httpx.Response) -> Dict[str, Any]:
    """Extract the JSON object from a chat-completions response, safely."""
    try:
        body = response.json()
        content = body["choices"][0]["message"]["content"]
        parsed = json.loads(content)
    except (ValueError, KeyError, IndexError, TypeError):
        length = 0
        try:
            length = len(response.text or "")
        except Exception:  # pragma: no cover - defensive
            pass
        logger.error("openai: unreadable response payload (http_body_len=%s)", length)
        raise OpenAIClientError("malformed_response")
    if not isinstance(parsed, dict):
        logger.error("openai: response content was JSON but not an object")
        raise OpenAIClientError("malformed_response")
    return parsed


def chat_json(system_prompt: str, user_prompt: str, *,
              max_tokens: int = 1800) -> Dict[str, Any]:
    """One JSON-object chat completion. Raises OpenAIClientError on any failure."""
    api_key = settings.OPENAI_API_KEY
    if not api_key:
        raise OpenAIClientError("missing_config", _SAFE_MESSAGES["missing_config"])

    url = settings.OPENAI_BASE_URL.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",   # never logged
        "Content-Type": "application/json",
    }
    payload = {
        "model": settings.OPENAI_MODEL,
        "temperature": 0,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    timeout = float(max(1, settings.OPENAI_TIMEOUT_SECONDS))
    attempts = 1 + max(0, settings.OPENAI_MAX_RETRIES)  # bounded: <= 2 total
    last_code = "provider_error"

    for attempt in range(1, attempts + 1):
        started = time.monotonic()
        try:
            response = _post(url, headers, payload, timeout)
        except httpx.TimeoutException:
            last_code = "timeout"
            logger.warning("openai: request timed out (attempt %d/%d, %.1fs)",
                           attempt, attempts, time.monotonic() - started)
            if attempt < attempts and _RETRY_BACKOFF_SECONDS:
                time.sleep(_RETRY_BACKOFF_SECONDS)
            continue
        except httpx.HTTPError:
            last_code = "provider_error"
            logger.warning("openai: transport error (attempt %d/%d)",
                           attempt, attempts)
            if attempt < attempts and _RETRY_BACKOFF_SECONDS:
                time.sleep(_RETRY_BACKOFF_SECONDS)
            continue

        status = response.status_code
        if status == 200:
            logger.info("openai: extraction call ok (attempt %d, %.1fs)",
                        attempt, time.monotonic() - started)
            return _parse_chat_json(response)

        if status in (401, 403):
            # Never retry auth failures; never log the key.
            logger.error("openai: auth rejected by provider (HTTP %d)", status)
            raise OpenAIClientError("auth_error")

        if status == 429:
            last_code = "rate_limited"
            logger.warning("openai: provider rate limited (attempt %d/%d)",
                           attempt, attempts)
        elif status >= 500:
            last_code = "provider_error"
            logger.warning("openai: provider error HTTP %d (attempt %d/%d)",
                           status, attempt, attempts)
        else:
            # Other 4xx: request problem, no retry, safe generic error.
            logger.error("openai: request rejected (HTTP %d)", status)
            raise OpenAIClientError("provider_error")

        if attempt < attempts and _RETRY_BACKOFF_SECONDS:
            time.sleep(_RETRY_BACKOFF_SECONDS)

    raise OpenAIClientError(last_code)
