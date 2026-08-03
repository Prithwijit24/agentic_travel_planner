"""Resilient map tool with per-place geocoding fallback, zoom-based tile switching,
and day-wise markers.

Geocoding waterfall per place: cache → Google Places (short timeout, 3 retries) → Nominatim (rate-limited) → known cities.
Map rendering: OpenTopoMap (zoomed out) → CartoDB positron (mid) → MapTilesAPI OSM (zoomed in), day-colored markers, route lines, legend.
"""

from __future__ import annotations

import math
import time
from typing import Any

import folium
import httpx
from folium.raster_layers import TileLayer

from agentic_tour_planner.config.settings import get_settings
from agentic_tour_planner.utils.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Day colour palette
# ---------------------------------------------------------------------------
HEX_DAY_COLORS = [
    "#e6194b",
    "#3cb44b",
    "#4363d8",
    "#f58231",
    "#911eb4",
    "#42d4f4",
    "#f032e6",
    "#bfef45",
    "#fabed4",
    "#469990",
    "#dcbeff",
    "#9A6324",
    "#800000",
    "#aaffc3",
    "#808000",
]


def _hex_color(day_number: int) -> str:
    return HEX_DAY_COLORS[(day_number - 1) % len(HEX_DAY_COLORS)]


# ---------------------------------------------------------------------------
# Tile definitions
# ---------------------------------------------------------------------------
_OPENTOPOMAP_ATTR = (
    'Map data: &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> '
    'contributors, <a href="http://viewfinderpanoramas.org">SRTM</a> | '
    'Map style: &copy; <a href="https://opentopomap.org">OpenTopoMap</a> '
    '(<a href="https://creativecommons.org/licenses/by-sa/3.0/">CC-BY-SA</a>)'
)
_OPENTOPOMAP_URL = "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png"

_CARTOPOSITRON_ATTR = '&copy; <a href="https://carto.com/">CARTO</a>'
_CARTOPOSITRON_URL = "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png"

_OSM_ATTR = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'


# ---------------------------------------------------------------------------
# In-memory geocode cache (per-session)
# ---------------------------------------------------------------------------
_GEOCODE_CACHE: dict[str, tuple[float, float] | None] = {}


class MapTool:
    """Tool for visualizing travel itineraries on interactive maps.

    Features:
    - Per-place geocoding with graceful fallback chain
    - Circuit breaker: skips Google after 5 consecutive failures
    - Zoom-based tile switching: OpenTopoMap → CartoDB positron → OSM
    - Day-wise colored markers with route lines and legend
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self._last_geocode_time: float = 0.0
        self._google_maps_key = self.settings.google_maps_api_key
        # Circuit breaker for Google geocoding
        self._google_consecutive_failures: int = 0
        self._google_circuit_open: bool = False
        # Places that failed to geocode on the last render
        self.unresolved_locations: list[str] = []

        if self._google_maps_key:
            logger.info("MapTool initialized with Google Maps API key")
        else:
            logger.info("MapTool initialized without Google Maps API key, using Nominatim fallback")

    # ------------------------------------------------------------------
    # Circuit breaker helpers
    # ------------------------------------------------------------------

    def _record_google_success(self) -> None:
        self._google_consecutive_failures = 0

    def _record_google_failure(self) -> None:
        self._google_consecutive_failures += 1
        if self._google_consecutive_failures >= 5:
            self._google_circuit_open = True
            logger.warning(
                f"Google geocoding circuit breaker OPEN after {self._google_consecutive_failures} consecutive failures"
            )

    def _google_available(self) -> bool:
        return self._google_maps_key is not None and not self._google_circuit_open

    # ------------------------------------------------------------------
    # Public: render itinerary map
    # ------------------------------------------------------------------

    def render_itinerary_map(
        self,
        itinerary: list[dict[str, Any]],
        origin: str | None = None,
        destination: str | None = None,
    ) -> folium.Map:
        """Render an interactive map with markers for each day's activities.

        Uses zoom-based tile switching:
        - zoom <= 8: OpenTopoMap (terrain/overview)
        - zoom 9-13: CartoDB positron (clean, minimal)
        - zoom >= 14: MapTilesAPI OSM English (detailed street view)

        Args:
            itinerary: List of day plans with activities
            origin: Starting location (e.g., "Tokyo")

        Returns:
            Folium Map object with coloured markers by day
        """
        logger.debug(f"Rendering itinerary map with {len(itinerary) if itinerary else 0} days")

        self.unresolved_locations = []
        locations = self._extract_locations(itinerary, origin, destination=destination or "")

        if not locations:
            logger.warning("No locations found for itinerary, returning empty map")
            return folium.Map(location=[0, 0], zoom_start=2, tiles=_OPENTOPOMAP_URL, attr=_OPENTOPOMAP_ATTR)

        # Determine map center
        first_day_activities = next(iter(locations.values()), [])
        center = first_day_activities[0][1] if first_day_activities else [20, 0]
        logger.debug(f"Map center set to: {center}")

        # Base layer: CartoDB positron (clean, minimal) — default view
        m = folium.Map(location=center, zoom_start=10, tiles=None)

        # Add CartoDB positron as the default base layer
        TileLayer(
            tiles=_CARTOPOSITRON_URL,
            attr=_CARTOPOSITRON_ATTR,
            name="CartoDB Positron (clean)",
            show=True,
        ).add_to(m)

        # Add OpenStreetMap as an alternative layer (user can toggle)
        TileLayer(
            tiles="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
            attr=_OSM_ATTR,
            name="OpenStreetMap (detailed)",
            show=False,
        ).add_to(m)

        # Add OpenTopoMap as an alternative layer (terrain/overview)
        TileLayer(
            tiles=_OPENTOPOMAP_URL,
            attr=_OPENTOPOMAP_ATTR,
            name="OpenTopoMap (Elevation)",
            show=False,
        ).add_to(m)

        # Track all coords for auto-fit
        all_coords: list[tuple[float, float]] = []

        for day_num, activities in locations.items():
            color = _hex_color(day_num)
            day_group = folium.FeatureGroup(name=f"Day {day_num}")

            for loc_name, coords in activities:
                if not coords:
                    self.unresolved_locations.append(loc_name)
                    continue
                all_coords.append(coords)

                marker = folium.CircleMarker(
                    location=coords,
                    radius=8,
                    popup=folium.Popup(
                        f"<b>Day {day_num}: {loc_name}</b>",
                        max_width=180,
                    ),
                    tooltip=loc_name,
                    color=color,
                    fill=True,
                    fill_color=color,
                    fill_opacity=0.8,
                )
                marker.add_to(day_group)

            day_group.add_to(m)

        # Auto-fit bounds
        if all_coords:
            m.fit_bounds(all_coords, padding=[40, 40])

        # Layer control (toggle individual days on/off + tile layers)
        folium.LayerControl(collapsed=False).add_to(m)

        # Legend
        self._add_legend(m, locations)

        logger.info(
            f"Map rendered with {sum(len(a) for a in locations.values())} locations across {len(locations)} days"
        )
        return m

    # ------------------------------------------------------------------
    # Location extraction & geocoding
    # ------------------------------------------------------------------

    def _extract_locations(
        self,
        itinerary: list[dict[str, Any]],
        origin: str | None = None,
        destination: str = "",
    ) -> dict[int, list[tuple[str, tuple[float, float] | None]]]:
        """Extract locations from itinerary and geocode them per-place.

        Prioritizes ``day["spots"]`` (which have explicit ``name`` fields)
        over free-text ``morning``/``afternoon``/``evening`` activity strings
        which are often not geocodable.
        """
        locations: dict[int, list[tuple[str, tuple[float, float] | None]]] = {}

        for day in itinerary:
            day_num = day.get("day", 1)
            activities: list[tuple[str, tuple[float, float] | None]] = []

            # Origin — only on day 1
            if origin and day_num == 1:
                origin_coords = self._geocode(origin, destination=destination)
                activities.append((origin, origin_coords))

            # Prefer spots (explicit names) over activity free-text
            spots = day.get("spots") or []
            if spots:
                seen: set[str] = set()
                for spot in spots:
                    name = spot.get("name", "") if isinstance(spot, dict) else str(spot)
                    if name and name not in seen:
                        seen.add(name)
                        coords = self._geocode(name, destination=destination)
                        activities.append((name, coords))
            else:
                # Fallback: parse morning/afternoon/evening activity strings
                for time_period in ("morning", "afternoon", "evening"):
                    for activity in day.get(time_period, []):
                        coords = self._geocode(activity, destination=destination)
                        activities.append((activity, coords))

            locations[day_num] = activities

        # Validate coordinates: detect duplicates and suspiciously close points
        locations = self._validate_coordinates(locations, destination=destination)

        return locations

    def _validate_coordinates(
        self,
        locations: dict[int, list[tuple[str, tuple[float, float] | None]]],
        destination: str = "",
    ) -> dict[int, list[tuple[str, tuple[float, float] | None]]]:
        """Detect and fix duplicate or suspiciously close coordinates.

        When different places resolve to the same or nearly the same point,
        re-geocode without destination bias to get accurate results.
        """
        # Collect all resolved coordinates with their place names
        resolved: list[tuple[str, tuple[float, float]]] = []
        for day_activities in locations.values():
            for name, coords in day_activities:
                if coords is not None:
                    resolved.append((name, coords))

        if len(resolved) < 2:
            return locations

        # Find groups of places with duplicate/near-duplicate coordinates
        duplicates: dict[tuple[str, str], list[tuple[str, str]]] = {}
        for i, (name_a, coords_a) in enumerate(resolved):
            for name_b, coords_b in resolved[i + 1 :]:
                if name_a == name_b:
                    continue
                dist = self._haversine_km(coords_a, coords_b)
                if dist < 0.5:
                    pair_key: tuple[str, str] = (min(name_a, name_b), max(name_a, name_b))
                    duplicates.setdefault(pair_key, []).append((name_a, name_b))

        if not duplicates:
            return locations

        # Re-geocode places that have duplicates without destination bias
        fixed_locations: dict[int, list[tuple[str, tuple[float, float] | None]]] = {}
        regeo_names: set[str] = set()
        for pair_list in duplicates.values():
            for n_a, n_b in pair_list:
                regeo_names.add(n_a)
                regeo_names.add(n_b)
        regeo_cache: dict[str, tuple[float, float] | None] = {}

        for day_num, day_activities in locations.items():
            fixed_activities: list[tuple[str, tuple[float, float] | None]] = []
            for name, coords in day_activities:
                if coords is not None and name in regeo_names:
                    # Check if this coordinate is part of a duplicate group
                    is_duplicate = False
                    for pair in duplicates.values():
                        for n_a, n_b in pair:
                            if name in (n_a, n_b):
                                is_duplicate = True
                                break
                        if is_duplicate:
                            break

                    if is_duplicate and name not in regeo_cache:
                        new_coords = self._geocode_no_bias(name)
                        regeo_cache[name] = new_coords
                        if new_coords and new_coords != coords:
                            logger.info(f"Re-geocoded '{name}' without bias: {coords} -> {new_coords}")
                            fixed_activities.append((name, new_coords))
                        else:
                            fixed_activities.append((name, coords))
                    else:
                        fixed_activities.append((name, coords))
                else:
                    fixed_activities.append((name, coords))
            fixed_locations[day_num] = fixed_activities

        return fixed_locations

    def _geocode_no_bias(self, location: str) -> tuple[float, float] | None:
        """Geocode without destination bias for accuracy validation."""
        if self._google_available():
            result = self._geocode_google(location, destination="")
            if result:
                return result
        return self._geocode_nominatim(location, destination="")

    @staticmethod
    def _haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
        """Great-circle distance in km between two (lat, lon) points."""
        lat1, lon1 = map(math.radians, a)
        lat2, lon2 = map(math.radians, b)
        dlat, dlon = lat2 - lat1, lon2 - lon1
        h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        return 2 * 6371 * math.asin(math.sqrt(h))

    def _geocode(self, location: str, destination: str = "") -> tuple[float, float] | None:
        """Per-place geocoding with destination-aware cache.

        Cache key: ``"{place}|{destination}"`` to avoid false hits for
        same-named places in different cities.

        Fallback chain: cache → Google (with circuit breaker) → Nominatim → known cities.
        """
        if not location:
            return None

        cache_key = (
            f"{location.lower().strip()}|{destination.lower().strip()}" if destination else location.lower().strip()
        )
        if cache_key in _GEOCODE_CACHE:
            logger.debug(f"Geocode cache hit for '{location}': {_GEOCODE_CACHE[cache_key]}")
            return _GEOCODE_CACHE[cache_key]

        result: tuple[float, float] | None = None
        source = "none"

        # 1. Google Places API (with circuit breaker)
        if self._google_available():
            result = self._geocode_google(location, destination)
            if result:
                source = "google"
                self._record_google_success()
            else:
                self._record_google_failure()
                logger.debug(f"Google Maps failed for '{location}', trying Nominatim")

        # 2. Nominatim (rate-limited)
        if result is None:
            result = self._geocode_nominatim(location, destination)
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

    def _geocode_google(self, location: str, destination: str = "") -> tuple[float, float] | None:
        """Google Places geocoding with short timeout (5s connect, 5s read) and 3 retries.

        Preferred region bias is applied when a destination is known so a common
        place name doesn't resolve to the wrong country.
        """
        if not self._google_maps_key:
            return None

        address = location.strip()
        if destination:
            address = f"{address}, {destination}"

        for attempt in range(1, 4):
            try:
                url = "https://maps.googleapis.com/maps/api/geocode/json"
                params = {"address": address, "key": self._google_maps_key}
                if destination:
                    params["region"] = destination
                with httpx.Client(timeout=httpx.Timeout(5.0, read=5.0)) as client:
                    response = client.get(url, params=params)
                    data = response.json()
                    if data.get("status") == "OK" and data.get("results"):
                        loc = data["results"][0]["geometry"]["location"]
                        return (float(loc["lat"]), float(loc["lng"]))
                    logger.debug(f"Google Maps status: {data.get('status')} for '{address}'")
                    return None
            except (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError) as exc:
                logger.debug(f"Google Maps attempt {attempt} failed for '{address}': {exc}")
                if attempt < 3:
                    time.sleep(0.5 * attempt)
            except Exception as exc:
                logger.debug(f"Google Maps unexpected error for '{address}': {exc}")
                return None

        return None

    def _geocode_nominatim(self, location: str, destination: str = "") -> tuple[float, float] | None:
        """Nominatim geocoding with strict 1 req/s rate limit and destination bias."""
        try:
            elapsed = time.time() - self._last_geocode_time
            if elapsed < 1.1:
                sleep_time = 1.1 - elapsed
                logger.debug(f"Rate limiting Nominatim, sleeping {sleep_time:.2f}s")
                time.sleep(sleep_time)

            query = location.strip()
            if destination:
                query = f"{query}, {destination}"

            url = "https://nominatim.openstreetmap.org/search"
            params: dict[str, Any] = {"q": query, "format": "json", "limit": 1, "addressdetails": 1}
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
            "kolkata": (22.5726, 88.3639),
            "delhi": (28.6139, 77.2090),
            "mumbai": (19.0760, 72.8777),
            "bangalore": (12.9716, 77.5946),
            "chennai": (13.0826, 80.2707),
            "jaipur": (26.9124, 75.7873),
            "goa": (15.2993, 74.1240),
            "varanasi": (25.3176, 82.9739),
            "agra": (27.1767, 78.0081),
            "udaipur": (24.5854, 73.7125),
            "sikkim": (27.5330, 88.5122),
            "gangtok": (27.3389, 88.6065),
            "pelling": (27.3000, 88.2500),
            "darjeeling": (27.0360, 88.2627),
            "kalimpong": (27.0700, 88.4740),
            # Asia
            "tokyo": (35.6762, 139.6503),
            "kyoto": (35.0116, 135.7681),
            "osaka": (34.6937, 135.5022),
            "beijing": (39.9042, 116.4074),
            "shanghai": (31.2304, 121.4737),
            "bangkok": (13.7563, 100.5018),
            "singapore": (1.3521, 103.8198),
            "seoul": (37.5665, 126.9780),
            "hong kong": (22.3193, 114.1694),
            "taipei": (25.0330, 121.5654),
            "bali": (-8.3405, 115.0920),
            # Europe
            "paris": (48.8566, 2.3522),
            "london": (51.5074, -0.1278),
            "rome": (41.9028, 12.4964),
            "berlin": (52.5200, 13.4050),
            "barcelona": (41.3851, 2.1734),
            "amsterdam": (52.3676, 4.9041),
            "vienna": (48.2082, 16.3738),
            "prague": (50.0755, 14.4378),
            "budapest": (47.4979, 19.0402),
            "zurich": (47.3769, 8.5417),
            "lisbon": (38.7223, -9.1393),
            "madrid": (40.4168, -3.7038),
            "athens": (37.9838, 23.7275),
            "dublin": (53.3498, -6.2603),
            "stockholm": (59.3293, 18.0686),
            "oslo": (59.9139, 10.7522),
            "copenhagen": (55.6761, 12.5683),
            # Americas
            "new york": (40.7128, -74.0060),
            "los angeles": (34.0522, -118.2437),
            "san francisco": (37.7749, -122.4194),
            "chicago": (41.8781, -87.6298),
            "toronto": (43.6532, -79.3832),
            "mexico city": (19.4326, -99.1332),
            "rio de janeiro": (-22.9068, -43.1729),
            "buenos aires": (-34.6037, -58.3816),
            # Oceania
            "sydney": (-33.8688, 151.2093),
            "melbourne": (-37.8136, 144.9631),
            "auckland": (-36.8485, 174.7633),
            # Middle East / Africa
            "dubai": (25.2048, 55.2708),
            "cairo": (30.0444, 31.2357),
            "nairobi": (-1.2921, 36.8219),
            "cape town": (-33.9249, 18.4241),
            # Russia
            "moscow": (55.7558, 37.6173),
            "st petersburg": (59.9343, 30.3351),
        }

        if location_lower in known_locations:
            return known_locations[location_lower]

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
            f"Day {day}</div>"
            for day in sorted(locations.keys())
        )
        legend_html = f"""
        <div style="position:fixed;bottom:30px;left:30px;z-index:9999;background:white;
                    padding:10px 14px;border-radius:8px;box-shadow:0 1px 4px rgba(0,0,0,0.3);
                    font-family:sans-serif;font-size:13px;">
            <b>Itinerary Days</b><br>{rows}
        </div>
        """
        # folium's typed ``Element`` does not declare the runtime ``html`` child;
        # the root element always has one at runtime, so widen the type to access it.
        root: Any = m.get_root()
        root.html.add_child(folium.Element(legend_html))

    # ------------------------------------------------------------------
    # Autocomplete
    # ------------------------------------------------------------------

    def autocomplete(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Get autocomplete suggestions for a location query."""
        if not query or len(query) < 2:
            return []

        suggestions: list[dict[str, Any]] = []

        # Google Places autocomplete (short timeout)
        if self._google_available():
            suggestions = self._autocomplete_google(query, limit)
            if suggestions:
                return suggestions

        # Nominatim (rate-limited)
        try:
            elapsed = time.time() - self._last_geocode_time
            if elapsed < 1.1:
                time.sleep(1.1 - elapsed)

            url = "https://nominatim.openstreetmap.org/search"
            params: dict[str, Any] = {"q": query, "format": "json", "limit": limit, "addressdetails": 1}
            headers = {
                "User-Agent": "AgenticTravelPlanner/1.0 (contact@agentictravelplanner.com)",
                "Accept-Language": "en",
            }
            with httpx.Client(timeout=httpx.Timeout(5.0, read=5.0)) as client:
                response = client.get(url, params=params, headers=headers)
                self._last_geocode_time = time.time()
                response.raise_for_status()
                for item in response.json():
                    suggestions.append(
                        {
                            "name": item.get("display_name", ""),
                            "lat": float(item["lat"]),
                            "lon": float(item["lon"]),
                            "country": item.get("address", {}).get("country", ""),
                        }
                    )
        except Exception as exc:
            logger.debug(f"Nominatim autocomplete failed for '{query}': {exc}")

        return suggestions

    def _autocomplete_google(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Google Places autocomplete — resolves coordinates via place details API."""
        if not self._google_maps_key:
            return []

        try:
            url = "https://maps.googleapis.com/maps/api/place/autocomplete/json"
            params: dict[str, Any] = {
                "input": query,
                "key": self._google_maps_key,
                "radius": 50000000,
                "language": "en",
            }
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
                        except Exception as exc:
                            logger.debug(f"Google place details fetch failed: {exc}")
                    suggestions.append(
                        {
                            "name": item.get("description", ""),
                            "lat": lat,
                            "lon": lon,
                            "country": country,
                        }
                    )
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
