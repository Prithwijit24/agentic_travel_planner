from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator

from agentic_tour_planner.domain.models import LogEvent
from agentic_tour_planner.utils.logging import get_logger

logger = get_logger(__name__)

_emitters: dict[str, EventEmitter] = {}
_emitter_deadlines: dict[str, float] = {}


class EventEmitter:
    """Collects log events during pipeline execution for SSE streaming."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[LogEvent] = asyncio.Queue()

    def emit(self, event: LogEvent) -> None:
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            logger.warning("EventEmitter queue full, dropping event={}", event.event)
        logger.debug("EventEmitter.emit event={} message={}", event.event, event.message)

    async def stream(self) -> AsyncIterator[LogEvent]:
        while True:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=PLAN_TIMEOUT_SECONDS)
            except TimeoutError:
                logger.warning("EventEmitter stream timed out")
                break
            yield event
            if event.event == "done":
                break


PLAN_TIMEOUT_SECONDS = 900


def register_emitter(request_id: str, emitter: EventEmitter, ttl_seconds: int = PLAN_TIMEOUT_SECONDS) -> None:
    now = time.monotonic()
    _prune_emitters(now)
    _emitters[request_id] = emitter
    _emitter_deadlines[request_id] = now + ttl_seconds
    logger.debug("register_emitter request_id={} ttl={}s", request_id, ttl_seconds)


def _prune_emitters(now: float) -> None:
    expired = [rid for rid, deadline in _emitter_deadlines.items() if deadline < now]
    for rid in expired:
        _emitters.pop(rid, None)
        _emitter_deadlines.pop(rid, None)
        logger.debug("evict expired emitter request_id={}", rid)


def get_emitter(request_id: str) -> EventEmitter | None:
    _evict_emitters()
    return _emitters.get(request_id)


def _evict_emitters() -> None:
    _prune_emitters(time.monotonic())


def remove_emitter(request_id: str) -> None:
    _emitters.pop(request_id, None)
    _emitter_deadlines.pop(request_id, None)
    logger.debug("remove_emitter request_id={}", request_id)
