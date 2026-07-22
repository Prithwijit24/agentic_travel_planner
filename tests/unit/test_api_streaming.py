import pytest
from httpx import ASGITransport, AsyncClient

from agentic_tour_planner.api.events import EventEmitter, register_emitter
from agentic_tour_planner.api.main import app
from agentic_tour_planner.domain.models import LogEvent


@pytest.mark.asyncio
async def test_stream_endpoint_returns_events():
    emitter = EventEmitter()
    emitter.emit(LogEvent(event="step", message="Gathering context..."))
    emitter.emit(LogEvent(event="done", message="Complete"))
    register_emitter("test-req-1", emitter)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/plans/stream/test-req-1")

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
