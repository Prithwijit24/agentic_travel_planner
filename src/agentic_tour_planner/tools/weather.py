from __future__ import annotations

import httpx

from agentic_tour_planner.config.settings import get_settings
from agentic_tour_planner.domain.models import WeatherSnapshot


class WeatherTool:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def current_weather(self, destination: str) -> WeatherSnapshot | None:
        if not self.settings.openweather_api_key:
            return None
        async with httpx.AsyncClient(timeout=self.settings.request_timeout_seconds) as client:
            response = await client.get(
                "https://api.openweathermap.org/data/2.5/weather",
                params={"q": destination, "appid": self.settings.openweather_api_key, "units": "metric"},
            )
            response.raise_for_status()
        payload = response.json()
        return WeatherSnapshot(
            summary=(payload.get("weather") or [{}])[0].get("description", "No summary"),
            temperature_c=payload.get("main", {}).get("temp"),
            feels_like_c=payload.get("main", {}).get("feels_like"),
            humidity_percent=payload.get("main", {}).get("humidity"),
            wind_speed_kph=(payload.get("wind", {}).get("speed") or 0.0) * 3.6,
        )

