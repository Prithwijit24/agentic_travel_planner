from __future__ import annotations

import httpx

from agentic_tour_planner.config.settings import get_settings
from agentic_tour_planner.domain.models import WeatherSnapshot
from agentic_tour_planner.utils.logging import get_logger

logger = get_logger(__name__)


class WeatherTool:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def current_weather(self, destination: str) -> WeatherSnapshot | None:
        logger.debug(f"current_weather called for destination={destination!r}")
        if not self.settings.openweather_api_key:
            logger.debug("openweather_api_key not set, skipping weather lookup")
            return None
        async with httpx.AsyncClient(timeout=self.settings.request_timeout_seconds) as client:
            try:
                logger.info(f"Calling OpenWeatherMap API for destination={destination!r}")
                from agentic_tour_planner.tools.http_util import aretry_get

                response = await aretry_get(
                    client,
                    "https://api.openweathermap.org/data/2.5/weather",
                    params={"q": destination, "appid": self.settings.openweather_api_key, "units": "metric"},
                )
                response.raise_for_status()
                payload = response.json()
                snapshot = WeatherSnapshot(
                    summary=(payload.get("weather") or [{}])[0].get("description", "No summary"),
                    temperature_c=payload.get("main", {}).get("temp"),
                    feels_like_c=payload.get("main", {}).get("feels_like"),
                    humidity_percent=payload.get("main", {}).get("humidity"),
                    wind_speed_kph=(payload.get("wind", {}).get("speed") or 0.0) * 3.6,
                )
                logger.debug(f"Weather for {destination!r}: {snapshot.summary}, {snapshot.temperature_c}C")
                return snapshot
            except httpx.TransportError as e:
                logger.warning(f"OpenWeatherMap transport error for {destination!r}: {e}; skipping weather")
                return None
            except httpx.HTTPStatusError as e:
                logger.warning(f"OpenWeatherMap returned HTTP {e.response.status_code} for {destination!r}")
                if e.response.status_code == 401:
                    logger.error("Invalid OpenWeatherMap API key. Get a free key at https://openweathermap.org/appid")
                return None
