import pytest
from agentic_tour_planner.api.events import EventEmitter, register_emitter, get_emitter, remove_emitter
from agentic_tour_planner.domain.models import LogEvent


@pytest.mark.asyncio
async def test_event_emitter_streams_events():
    emitter = EventEmitter()
    emitter.emit(LogEvent(event="step", message="Gathering context..."))
    emitter.emit(LogEvent(event="done", message="Complete"))

    events = []
    async for event in emitter.stream():
        events.append(event)

    assert len(events) == 2
    assert events[0].event == "step"
    assert events[1].event == "done"


@pytest.mark.asyncio
async def test_event_emitter_stops_at_done():
    emitter = EventEmitter()
    emitter.emit(LogEvent(event="step", message="Step 1"))
    emitter.emit(LogEvent(event="debug", message="Details"))
    emitter.emit(LogEvent(event="done", message="Done"))

    events = []
    async for event in emitter.stream():
        events.append(event)

    assert len(events) == 3
    assert events[-1].event == "done"


def test_register_and_get_emitter():
    emitter = EventEmitter()
    register_emitter("req-123", emitter)
    assert get_emitter("req-123") is emitter
    remove_emitter("req-123")
    assert get_emitter("req-123") is None
