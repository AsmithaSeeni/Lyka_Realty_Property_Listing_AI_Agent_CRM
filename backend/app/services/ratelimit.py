"""Lightweight in-memory rate limiting (Phase 1).

Scope and honest limitations:
- Counters live in THIS process only: limits are **per application process**,
  reset on restart, and are NOT shared between workers. This is a basic
  abuse-damping measure, not a distributed production rate limiter — for
  multi-worker/production deployments put a real limiter in front (API
  gateway, reverse proxy, or a Redis-backed limiter).
- Keys are ``bucket:client-ip``. Only direct client IPs are trusted (no
  ``X-Forwarded-For`` spoofing surface) unless a proxy is explicitly used.
- Sliding-window algorithm: at most ``limit`` requests per ``window``
  seconds per key. ``limit <= 0`` disables a bucket (documented escape hatch).

Responses use the API's normal error shape ``{"detail": ...}`` with
``Retry-After`` so existing frontend error handling keeps working.
"""

import threading
import time
from collections import defaultdict, deque
from typing import Callable, Dict, Tuple

from fastapi import HTTPException, Request

from app.config import settings


class SlidingWindowLimiter:
    """Thread-safe sliding-window counter keyed by arbitrary strings."""

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._events: Dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window: int) -> Tuple[bool, int]:
        """Record a hit. Returns (allowed, retry_after_seconds).

        ``retry_after`` is only meaningful when ``allowed`` is False.
        ``limit <= 0`` means the bucket is disabled (always allowed).
        """
        if limit <= 0 or window <= 0:
            return True, 0
        now = self._clock()
        with self._lock:
            q = self._events[key]
            cutoff = now - window
            while q and q[0] <= cutoff:
                q.popleft()
            if len(q) >= limit:
                retry_after = int(window - (now - q[0])) + 1
                return False, max(retry_after, 1)
            q.append(now)
            return True, 0

    def reset(self, key: str = None) -> None:
        """Clear all counters (or one key). Used by tests."""
        with self._lock:
            if key is None:
                self._events.clear()
            else:
                self._events.pop(key, None)


# Process-wide limiter instance shared by every rate-limited route.
limiter = SlidingWindowLimiter()


def rate_limit(bucket: str, limit_setting: str) -> Callable:
    """FastAPI dependency factory.

    Args:
        bucket: label for the counter group (e.g. "chat", "auth", "voice").
        limit_setting: name of the ``Settings`` attribute holding the limit,
            resolved at request time so tests/operators can tune it without
            rebuilding routes.

    Usage in a route signature::

        def handler(..., _rl: None = Depends(rate_limit("chat", "CHAT_RATE_LIMIT"))):
    """
    if not hasattr(settings, limit_setting):
        raise RuntimeError(f"Unknown rate-limit setting: {limit_setting}")

    def dependency(request: Request) -> None:
        if not settings.RATE_LIMIT_ENABLED:
            return
        limit = getattr(settings, limit_setting)
        window = settings.RATE_LIMIT_WINDOW_SECONDS
        ip = request.client.host if request.client else "unknown"
        allowed, retry_after = limiter.hit(f"{bucket}:{ip}", limit, window)
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="Too many requests. Please slow down and try again shortly.",
                headers={"Retry-After": str(retry_after)},
            )

    # Marker used by tests to verify a route is actually wired up.
    dependency.bucket = bucket          # type: ignore[attr-defined]
    dependency.limit_setting = limit_setting  # type: ignore[attr-defined]
    return dependency
