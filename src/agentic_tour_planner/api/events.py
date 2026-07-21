from __future__ import annotations

import asyncio
from typing import AsyncIterator

from agentic_tour_planner.domain.models import LogEvent
from agentic_tour_planner.utils.logging import get_logger

logger = get_logger(__name__)

_emitters: dict[str, EventEmitter] = {}


class EventEmitter:
    """Collects log events during pipeline execution for SSE streaming."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[LogEvent] = asyncio.Queue()

    def emit(self, event: LogEvent) -> None:
        self._queue.put_nowait(event)
        logger.debug("EventEmitter.emit event={} message={}", event.event, event.message)

    async def stream(self) -> AsyncIterator[LogEvent]:
        while True:
            event = await self._queue.get()
            yield event
            if event.event == "done":
                break


def register_emitter(request_id: str, emitter: EventEmitter) -> None:
    _emitters[request_id] = emitter
    logger.debug("register_emitter request_id={}", request_id)


def get_emitter(request_id: str) -> EventEmitter | None:
    return _emitters.get(request_id)


def remove_emitter(request_id: str) -> None:
    _emitters.pop(request_id, None)
    logger.debug("remove_emitter request_id={}", request_id)
