"""Resilient map tool with per-place geocoding fallback and day-wise markers.

Geocoding waterfall per place: cache → Google Places (short timeout, 2 retries) → Nominatim (rate-limited) → known cities.
Map rendering: Folium with CartoDB positron tiles, day-colored markers, route lines, and legend.
"""

from __future__ import annotations

import json
import time
from typing import Any

import folium
import httpx
from folium import Marker, PolyLine

from agentic_tour_planner.config.settings import get_settings
from agentic_tour_planner.utils.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Day colour palette (Folium icon colours + hex for PolyLine / legend)
# ---------------------------------------------------------------------------
FOLIUM_DAY_COLORS = [
    "red", "blue", "green", "purple", "orange", "darkred",
    "cadetblue", "darkgreen", "darkblue", "pink", "darkpurple", "gray",
]

HEX_DAY_COLORS = [
    "#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4",
    "#42d4f4", "#f032e6", "#bfef45", "#fabed4", "#469990",
    "#dcbeff", "#9A6324", "#800000", "#aaffc3", "#808000",
]


def _folium_color(day_number: int) -> str:
    return FOLIUM_DAY_COLORS[(day_number - 1) % len(FOLIUM_DAY_COLORS)]


def _hex_color(day_number: int) -> str:
    return HEX_DAY_COLORS[(day_number - 1) % len(HEX_DAY_COLORS)]


# ---------------------------------------------------------------------------
# Geocode cache (in-memory, per-session — survives across places in one run)
# ---------------------------------------------------------------------------
_GEOCODE_CACHE: dict[str, tuple[float, float] | None] = {}


class MapTool:
    """Tool for visualizing travel itineraries on interactive maps.

    Uses Google Maps API for bulk geocoding when available, with Nominatim
    as a fallback for worldwide coverage.  Every place is resolved
    independently so one failure never kills the whole map.
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self._last_geocode_time: float = 0.0
        self._google_maps_key = self.settings.google_maps_api_key

        if self._google_maps_key:
            logger.info("MapTool initialized with Google Maps API key")
        else:
            logger.info("MapTool initialized without Google Maps API key, using Nominatim fallback")

    # ------------------------------------------------------------------
    # Public: render itinerary map
    # ------------------------------------------------------------------

    def render_itinerary_map(
        self,
        itinerary: list[dict[str, Any]],
        origin: str | None = None,
    ) -> folium.Map:
        """Render an interactive map with markers for each day's activities.

        Args:
            itinerary: List of day plans with activities
            origin: Starting location (e.g., "Tokyo")

        Returns:
            Folium Map object with coloured markers by day
        """
        logger.debug(f"Rendering itinerary map with {len(itinerary) if itinerary else 0} days")

        locations = self._extract_locations(itinerary, origin)

        if not locations:
            logger.warning("No locations found for itinerary, returning empty map")
            return folium.Map(location=[0, 0], zoom_start=2, tiles="CartoDB positron")

        # Determine map center
        first_day_activities = next(iter(locations.values()), [])
        center = first_day_activities[0][1] if first_day_activities else [20, 0]
        logger.debug(f"Map center set to: {center}")

        # CartoDB positron — clean, minimal, free, no key needed
        m = folium.Map(location=center, zoom_start=11, tiles="CartoDB positron")

        # Track all coords for auto-fit
        all_coords: list[tuple[float, float]] = []

        for day_num, activities in locations.items():
            color = _folium_color(day_num)
            day_group = folium.FeatureGroup(name=f"Day {day_num}")
            coords_for_line: list[tuple[float, float]] = []

            for loc_name, coords in activities:
                if not coords:
                    continue
                all_coords.append(coords)
                coords_for_line.append(coords)

                marker = Marker(
                    location=coords,
                    popup=folium.Popup(
                        f"<b>Day {day_num}: {loc_name}</b>",
                        max_width=180,
                    ),
                    tooltip=loc_name,
                    icon=folium.Icon(color=color, icon="info-sign"),
                )
                marker.add_to(day_group)

            # Route line connecting the day's places in visit order
            if len(coords_for_line) > 1:
                PolyLine(coords_for_line, color=_hex_color(day_num), weight=3, opacity=0.7).add_to(day_group)

            day_group.add_to(m)

        # Auto-fit bounds
        if all_coords:
            m.fit_bounds(all_coords, padding=[40, 40])

        # Layer control (toggle individual days on/off)
        folium.LayerControl(collapsed=False).add_to(m)

        # Legend
        self._add_legend(m, locations)

        logger.info(f"Map rendered with {sum(len(a) for a in locations.values())} locations across {len(locations)} days")
        return m

    # ------------------------------------------------------------------
    # Location extraction & geocoding
    # ------------------------------------------------------------------

    def _extract_locations(
        self,
        itinerary: list[dict[str, Any]],
        origin: str | None = None,
    ) -> dict[int, list[tuple[str, tuple[float, float] | None]]]:
        """Extract locations from itinerary and geocode them per-place."""
        locations: dict[int, list[tuple[str, tuple[float, float] | None]]] = {}

        for day in itinerary:
            day_num = day.get("day", 1)
            activities: list[tuple[str, tuple[float, float] | None]] = []

            # Origin
            if origin:
                origin_coords = self._geocode(origin)
                activities.append((origin, origin_coords))

            # Activities from morning / afternoon / evening
            for time_period in ("morning", "afternoon", "evening"):
                for activity in day.get(time_period, []):
                    coords = self._geocode(activity)
                    activities.append((activity, coords))

            locations[day_num] = activities

        return locations

    def _geocode(self, location: str) -> tuple[float, float] | None:
        """Per-place geocoding with cache → Google → Nominatim → known cities.

        One failure never cascades to other places.
        """
        if not location:
            return None

        cache_key = location.lower().strip()
        if cache_key in _GEOCODE_CACHE:
            logger.debug(f"Geocode cache hit for '{location}': {_GEOCODE_CACHE[cache_key]}")
            return _GEOCODE_CACHE[cache_key]

        result: tuple[float, float] | None = None
        source = "none"

        # 1. Google Maps API (short timeout, retries handled by httpx)
        if self._google_maps_key:
            result = self._geocode_google(location)
            if result:
                source = "google"
            else:
                logger.debug(f"Google Maps failed for '{location}', trying Nominatim")

        # 2. Nominatim (rate-limited)
        if result is None:
            result = self._geocode_nominatim(location)
            if result:
                source = "nominatim"

        # 3. Known cities fallback
        if result is None:
            result = self._fallback_geocode(location)
            if result:
                source = "known_cities"

        # Cache even failures so we don't retry within the same session
        _GEOCODE_CACHE[cache_key] = result

        if result:
            logger.info(f"Geocoded '{location}' -> {result} (source: {source})")
        else:
            logger.warning(f"Failed to geocode '{location}' from all sources")

        return result

    def _geocode_google(self, location: str) -> tuple[float, float] | None:
        """Google Places geocoding with short timeout (5s connect, 5s read)."""
        if not self._google_maps_key:
            return None

        for attempt in range(1, 4):
            try:
                url = "https://maps.googleapis.com/maps/api/geocode/json"
                params = {"address": location, "key": self._google_maps_key}
                with httpx.Client(timeout=httpx.Timeout(5.0, read=5.0)) as client:
                    response = client.get(url, params=params)
                    data = response.json()
                    if data.get("status") == "OK" and data.get("results"):
                        loc = data["results"][0]["geometry"]["location"]
                        return (float(loc["lat"]), float(loc["lng"]))
                    # Non-retryable status (ZERO_RESULTS, etc.)
                    logger.debug(f"Google Maps status: {data.get('status')} for '{location}'")
                    return None
            except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as exc:
                logger.debug(f"Google Maps attempt {attempt} failed for '{location}': {exc}")
                if attempt < 3:
                    time.sleep(0.5 * attempt)  # exponential-ish backoff
            except Exception as exc:
                logger.debug(f"Google Maps unexpected error for '{location}': {exc}")
                return None

        return None

    def _geocode_nominatim(self, location: str) -> tuple[float, float] | None:
        """Nominatim geocoding with strict 1 req/s rate limit."""
        try:
            # Enforce Nominatim usage policy: max 1 request/second
            elapsed = time.time() - self._last_geocode_time
            if elapsed < 1.1:
                sleep_time = 1.1 - elapsed
                logger.debug(f"Rate limiting Nominatim, sleeping {sleep_time:.2f}s")
                time.sleep(sleep_time)

            url = "https://nominatim.openstreetmap.org/search"
            params = {"q": location, "format": "json", "limit": 1, "addressdetails": 1}
            headers = {
                "User-Agent": "AgenticTravelPlanner/1.0 (contact@agentictravelplanner.com)",
                "Accept-Language": "en",
            }

            with httpx.Client(timeout=httpx.Timeout(5.0, read=5.0)) as client:
                response = client.get(url, params=params, headers=headers)
                response.raise_for_status()
                results = response.json()
                self._last_geocode_time = time.time()

                if results:
                    lat = float(results[0]["lat"])
                    lon = float(results[0]["lon"])
                    return (lat, lon)

        except Exception as e:
            logger.debug(f"Nominatim geocoding failed for '{location}': {e}")
            self._last_geocode_time = time.time()

        return None

    def _fallback_geocode(self, location: str) -> tuple[float, float] | None:
        """Known cities database for final fallback."""
        location_lower = location.lower()

        known_locations: dict[str, tuple[float, float]] = {
            # India
            "kolkata": (22.5726, 88.3639), "delhi": (28.6139, 77.2090),
            "mumbai": (19.0760, 72.8777), "bangalore": (12.9716, 77.5946),
            "chennai": (13.0826, 80.2707), "jaipur": (26.9124, 75.7873),
            "goa": (15.2993, 74.1240), "varanasi": (25.3176, 82.9739),
            "agra": (27.1767, 78.0081), "udaipur": (24.5854, 73.7125),
            "sikkim": (27.5330, 88.5122), "gangtok": (27.3389, 88.6065),
            "pelling": (27.3000, 88.2500), "darjeeling": (27.0360, 88.2627),
            "kalimpong": (27.0700, 88.4740),
            # Asia
            "tokyo": (35.6762, 139.6503), "kyoto": (35.0116, 135.7681),
            "osaka": (34.6937, 135.5022), "beijing": (39.9042, 116.4074),
            "shanghai": (31.2304, 121.4737), "bangkok": (13.7563, 100.5018),
            "singapore": (1.3521, 103.8198), "seoul": (37.5665, 126.9780),
            "hong kong": (22.3193, 114.1694), "taipei": (25.0330, 121.5654),
            "bali": (-8.3405, 115.0920),
            # Europe
            "paris": (48.8566, 2.3522), "london": (51.5074, -0.1278),
            "rome": (41.9028, 12.4964), "berlin": (52.5200, 13.4050),
            "barcelona": (41.3851, 2.1734), "amsterdam": (52.3676, 4.9041),
            "vienna": (48.2082, 16.3738), "prague": (50.0755, 14.4378),
            "budapest": (47.4979, 19.0402), "zurich": (47.3769, 8.5417),
            "lisbon": (38.7223, -9.1393), "madrid": (40.4168, -3.7038),
            "athens": (37.9838, 23.7275), "dublin": (53.3498, -6.2603),
            "stockholm": (59.3293, 18.0686), "oslo": (59.9139, 10.7522),
            "copenhagen": (55.6761, 12.5683),
            # Americas
            "new york": (40.7128, -74.0060), "los angeles": (34.0522, -118.2437),
            "san francisco": (37.7749, -122.4194), "chicago": (41.8781, -87.6298),
            "toronto": (43.6532, -79.3832), "mexico city": (19.4326, -99.1332),
            "rio de janeiro": (-22.9068, -43.1729), "buenos aires": (-34.6037, -58.3816),
            # Oceania
            "sydney": (-33.8688, 151.2093), "melbourne": (-37.8136, 144.9631),
            "auckland": (-36.8485, 174.7633),
            # Middle East / Africa
            "dubai": (25.2048, 55.2708), "cairo": (30.0444, 31.2357),
            "nairobi": (-1.2921, 36.8219), "cape town": (-33.9249, 18.4241),
            # Russia
            "moscow": (55.7558, 37.6173), "st petersburg": (59.9343, 30.3351),
        }

        # Exact match
        if location_lower in known_locations:
            return known_locations[location_lower]

        # Partial match
        for name, coords in known_locations.items():
            if name in location_lower:
                return coords

        return None

    # ------------------------------------------------------------------
    # Legend
    # ------------------------------------------------------------------

    def _add_legend(self, m: folium.Map, locations: dict[int, list]) -> None:
        """Add a colour legend to the map."""
        rows = "".join(
            f'<div style="margin:2px 0;">'
            f'<span style="display:inline-block;width:12px;height:12px;background:{_hex_color(day)};'
            f'border-radius:50%;margin-right:6px;"></span>'
            f'Day {day}</div>'
            for day in sorted(locations.keys())
        )
        legend_html = f"""
        <div style="position:fixed;bottom:30px;left:30px;z-index:9999;background:white;
                    padding:10px 14px;border-radius:8px;box-shadow:0 1px 4px rgba(0,0,0,0.3);
                    font-family:sans-serif;font-size:13px;">
            <b>Itinerary Days</b><br>{rows}
        </div>
        """
        m.get_root().html.add_child(folium.Element(legend_html))

    # ------------------------------------------------------------------
    # Autocomplete (kept for destination search)
    # ------------------------------------------------------------------

    def autocomplete(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Get autocomplete suggestions for a location query."""
        if not query or len(query) < 2:
            return []

        suggestions: list[dict[str, Any]] = []
        query_lower = query.lower()

        # Google Places autocomplete (short timeout)
        if self._google_maps_key:
            suggestions = self._autocomplete_google(query, limit)
            if suggestions:
                return suggestions

        # Nominatim (rate-limited via _last_geocode_time)
        try:
            elapsed = time.time() - self._last_geocode_time
            if elapsed < 1.1:
                time.sleep(1.1 - elapsed)

            url = "https://nominatim.openstreetmap.org/search"
            params = {"q": query, "format": "json", "limit": limit, "addressdetails": 1}
            headers = {
                "User-Agent": "AgenticTravelPlanner/1.0 (contact@agentictravelplanner.com)",
                "Accept-Language": "en",
            }
            with httpx.Client(timeout=httpx.Timeout(5.0, read=5.0)) as client:
                response = client.get(url, params=params, headers=headers)
                self._last_geocode_time = time.time()
                response.raise_for_status()
                for item in response.json():
                    suggestions.append({
                        "name": item.get("display_name", ""),
                        "lat": float(item["lat"]),
                        "lon": float(item["lon"]),
                        "country": item.get("address", {}).get("country", ""),
                    })
        except Exception as exc:
            logger.debug(f"Nominatim autocomplete failed for '{query}': {exc}")

        return suggestions

    def _autocomplete_google(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Google Places autocomplete — resolves coordinates via place details API."""
        if not self._google_maps_key:
            return []

        try:
            url = "https://maps.googleapis.com/maps/api/place/autocomplete/json"
            params = {"input": query, "key": self._google_maps_key, "radius": 50000000, "language": "en"}
            with httpx.Client(timeout=httpx.Timeout(5.0, read=5.0)) as client:
                response = client.get(url, params=params)
                data = response.json()
                if data.get("status") != "OK":
                    return []

                suggestions = []
                for item in data.get("predictions", [])[:limit]:
                    place_id = item.get("place_id")
                    lat, lon, country = 0.0, 0.0, ""
                    if place_id:
                        try:
                            details_url = "https://maps.googleapis.com/maps/api/place/details/json"
                            details_params = {
                                "place_id": place_id,
                                "key": self._google_maps_key,
                                "fields": "geometry/location,address_component",
                            }
                            dr = client.get(details_url, params=details_params)
                            dd = dr.json()
                            if dd.get("status") == "OK" and dd.get("result"):
                                loc = dd["result"]["geometry"]["location"]
                                lat, lon = float(loc["lat"]), float(loc["lng"])
                                for comp in dd["result"].get("address_components", []):
                                    if "country" in comp.get("types", []):
                                        country = comp.get("long_name", "")
                                        break
                        except Exception:
                            pass  # non-fatal, keep 0,0
                    suggestions.append({
                        "name": item.get("description", ""),
                        "lat": lat,
                        "lon": lon,
                        "country": country,
                    })
                return suggestions

        except Exception as exc:
            logger.debug(f"Google Places autocomplete failed for '{query}': {exc}")
        return []

    def validate_address(self, location: str) -> dict[str, Any]:
        """Validate and get detailed information about a location."""
        if not location:
            return {"valid": False, "coordinates": None, "formatted_name": "", "address": {}}

        coords = self._geocode(location)
        if coords:
            return {
                "valid": True,
                "coordinates": coords,
                "formatted_name": location,
                "address": {"lat": coords[0], "lon": coords[1]},
            }

        return {"valid": False, "coordinates": None, "formatted_name": location, "address": {}}
