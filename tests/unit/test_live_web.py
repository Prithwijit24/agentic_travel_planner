from __future__ import annotations

import asyncio
from datetime import date, timedelta
from pathlib import Path

import pytest

from agentic_tour_planner.domain.models import PlanningRequest
from agentic_tour_planner.services.live_web_collector import LiveWebCollector
from agentic_tour_planner.tools.search_provider import (
    SearchHit,
    SearchProvider,
    parse_duration,
    parse_published,
)


def test_parse_duration_variants():
    assert parse_duration("20:15") == 20 * 60 + 15
    assert parse_duration("1:02:03") == 3600 + 120 + 3
    assert parse_duration("PT1H2M3S") == 3600 + 120 + 3
    assert parse_duration("20 min") == 1200
    assert parse_duration(1300) == 1300
    assert parse_duration(None) is None


def test_parse_published_variants():
    today = date.today()
    assert parse_published("2024-01-15") == "2024-01-15"
    assert parse_published("2 years ago") == (today - timedelta(days=730)).isoformat()
    assert parse_published("not a date") is None


def test_search_cascade_serpapi_to_ddgs():
    sp = SearchProvider()

    async def fake_serpapi(q, k, n):
        raise RuntimeError("serpapi down")

    async def fake_tavily(q, k, n):
        return []

    async def fake_ddgs(q, k, n):
        return [SearchHit(title="D", url="https://d.example", snippet="s", kind=k, source="ddgs")]

    sp._search_serpapi = fake_serpapi
    sp._search_tavily = fake_tavily
    sp._search_ddgs = fake_ddgs

    hits = asyncio.run(sp.search("kyoto blogs", kind="web", max_results=3))
    assert len(hits) == 1
    assert hits[0].source == "ddgs"


def test_collector_builds_brief_and_filters_videos():
    class FakeLLM:
        async def complete_text(self, prompt, system_prompt=None, role="translator", provider_override=None):
            return "translated: " + prompt[-20:]

        async def extract_json(self, prompt, system_prompt, role="worker", provider_override=None):
            return {
                "path_instructions": "Take the JR line between sites.",
                "fair_charges": "Entry ~¥500.",
                "transport_availability": "Buses run every 15 min.",
                "place_reviews": "Fushimi Inari loved by all.",
                "daywise_guide": "Day1 east, Day2 west.",
            }

    class FakeSearch:
        async def search(self, query, kind="web", max_results=5):
            if kind == "video":
                return [
                    SearchHit(title="Old clip", url="https://yt.old", snippet="x", kind="video",
                              duration_seconds=600, published_date="2010-01-01", source="serpapi"),
                    SearchHit(title="Good talk", url="https://yt.new", snippet="y", kind="video",
                              duration_seconds=1500, published_date=date.today().isoformat(), source="serpapi"),
                ]
            return [
                SearchHit(title="Blog A", url="https://blog.a", snippet="z", kind="web", source="serpapi"),
            ]

    class FakeConnectors:
        async def fetch_youtube_transcript(self, url):
            return type("D", (), {"content": "regional transcript text"})()

        async def fetch_web_document(self, url, source_id, title, source_type="web", crawl_backend=None):
            return type("D", (), {"content": "blog text"})()

    collector = LiveWebCollector(FakeLLM(), search=FakeSearch())
    collector.connectors = FakeConnectors()

    req = PlanningRequest(
        destination="Kyoto", trip_length_days=3, interests=["temples"],
        budget_level="midrange", travel_month="October", include_live_data=True,
    )
    brief = asyncio.run(collector.collect(req, provider_override="openrouter"))

    assert brief.path_instructions
    assert brief.fair_charges
    assert brief.transport_availability
    assert brief.place_reviews
    assert brief.daywise_guide
    # Old/short video must be filtered out; only the recent long one is kept.
    video_urls = [s.url for s in brief.sources if s.kind == "video"]
    assert video_urls == ["https://yt.new"]
    assert any(s.kind == "web" for s in brief.sources)


# ----------------------------------------------------------- audio/video fetch
def test_transcribe_audio_via_groq(tmp_path, monkeypatch):
    audio = tmp_path / "a.webm"
    audio.write_bytes(b"data")

    class FakeResp:
        text = "hello world"

    class FakeTranslations:
        def create(self, *a, **k):
            return FakeResp()

    class FakeAudio:
        translations = FakeTranslations()

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        audio = FakeAudio()

    monkeypatch.setattr("groq.Groq", FakeClient)
    collector = LiveWebCollector(_FakeLLM())
    assert collector._transcribe_audio(str(audio)) == "hello world"


def test_transcribe_audio_too_large(tmp_path):
    audio = tmp_path / "big.webm"
    audio.write_bytes(b"x" * (25 * 1024 * 1024))
    collector = LiveWebCollector(_FakeLLM())
    assert collector._transcribe_audio(str(audio)) is None


def test_download_audio_reuses_existing(tmp_path, monkeypatch):
    collector = LiveWebCollector(_FakeLLM())
    monkeypatch.setattr(type(collector), "media_root", tmp_path)
    vid_dir = tmp_path / "abc"
    vid_dir.mkdir()
    (vid_dir / "audio_abc.webm").write_bytes(b"x")
    path = asyncio.run(collector._download_audio("https://youtu.be/abc"))
    assert path.endswith("audio_abc.webm")


def test_download_audio_runs_ytdlp(tmp_path, monkeypatch):
    collector = LiveWebCollector(_FakeLLM())
    monkeypatch.setattr(type(collector), "media_root", tmp_path)
    captured: dict = {}

    class FakeYDL:
        def __init__(self, opts):
            captured["opts"] = opts

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download):
            p = Path(captured["opts"]["outtmpl"] % {"id": "vid1", "ext": "webm"})
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"audio")
            return {"requested_downloads": [{"filepath": str(p)}]}

    monkeypatch.setattr("yt_dlp.YoutubeDL", FakeYDL)
    path = asyncio.run(collector._download_audio("https://youtube.com/watch?v=vid1"))
    assert path and Path(path).exists()


def test_fetch_transcript_falls_back_to_groq(monkeypatch):
    class FakeConnectors:
        async def fetch_youtube_transcript(self, url):
            raise RuntimeError("blocked")

    collector = LiveWebCollector(_FakeLLM())
    collector.connectors = FakeConnectors()
    monkeypatch.setattr(collector, "_transcribe_audio", lambda p: "groq transcript")
    out = asyncio.run(
        collector._fetch_transcript(
            SearchHit(title="v", url="https://youtube.com/watch?v=x", kind="video", snippet=""),
            "audio.webm",
        )
    )
    assert out == "groq transcript"


class _FakeLLM:
    async def complete_text(self, prompt, system_prompt=None, role="translator", provider_override=None):
        return "translated"

    async def extract_json(self, prompt, system_prompt=None, role="worker", provider_override=None):
        return {}
