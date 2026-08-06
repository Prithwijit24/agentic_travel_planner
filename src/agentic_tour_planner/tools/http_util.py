"""Resilient HTTP helpers for external tool calls.

Transient connection drops (e.g. ``httpx.ServerDisconnected``) from upstream
APIs like Google Places or OpenWeather should be retried rather than aborting
the whole pipeline. These helpers retry only on transport-level errors (not on
HTTP status errors, which callers handle themselves).
"""

from __future__ import annotations

import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)

# Transport-level errors that are safe to retry (connection reset, timeout,
# server disconnected mid-response, etc.). HTTP 4xx/5xx are NOT included.
_RETRYABLE = (httpx.TransportError,)


async def aretry_get(
    client: httpx.AsyncClient, url: str, *, attempts: int = 3, backoff: float = 1.0, **kwargs
) -> httpx.Response:
    """``client.get(url, **kwargs)`` with retries on transport errors (backoff)."""
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            return await client.get(url, **kwargs)
        except _RETRYABLE as exc:
            last_exc = exc
            logger.warning(f"[http] GET {url} transport error (attempt {attempt + 1}/{attempts}): {exc}")
            if attempt < attempts - 1:
                await asyncio.sleep(backoff * (attempt + 1))
    assert last_exc is not None
    raise last_exc
