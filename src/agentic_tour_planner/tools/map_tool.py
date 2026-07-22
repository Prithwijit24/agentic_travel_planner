from __future__ import annotations

import time
from typing import Any

import folium
import httpx
from folium import Marker, PolyLine

from agentic_tour_planner.config.settings import get_settings
from agentic_tour_planner.utils.logging import get_logger

logger = get_logger(__name__)


class MapTool:
    """Tool for visualizing travel itineraries on interactive maps.
    
    Uses Google Maps API for bulk geocoding when available, with Nominatim
    as a fallback for worldwide coverage.
    """

    DAY_COLORS = [
        "#1f77b4",  # Blue
        "#ff7f0e",  # Orange
        "#2ca02c",  # Green
        "#d62728",  # Red
        "#9467bd",  # Purple
        "#8c564b",  # Brown
        "#e377c2",  # Pink
        "#7f7f7f",  # Gray
        "#bcbd22",  # Olive
        "#17becf",  # Cyan
    ]

    def __init__(self) -> None:
        self.settings = get_settings()
        self._geocode_cache: dict[str, tuple[float, float] | None] = {}
        self._last_geocode_time: float = 0.0
        self._google_maps_key = self.settings.google_maps_api_key
        
        if self._google_maps_key:
            logger.info("MapTool initialized with Google Maps API key")
        else:
            logger.info("MapTool initialized without Google Maps API key, using Nominatim fallback")

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
            Folium Map object with colored markers by day
        """
        logger.debug(f"Rendering itinerary map with {len(itinerary) if itinerary else 0} days")
        
        # Extract all locations
        locations = self._extract_locations(itinerary, origin)

        if not locations:
            logger.warning("No locations found for itinerary, returning empty map")
            # Return empty map centered on a default location
            return folium.Map(location=[0, 0], zoom_start=2)

        # Determine map center (first location or average)
        first_day_activities = next(iter(locations.values()), [])
        center = first_day_activities[0][1] if first_day_activities else [20, 0]
        logger.debug(f"Map center set to: {center}")
        m = folium.Map(location=center, zoom_start=5)

        # Color legend
        day_colors = {}
        for day_num in range(1, len(self.DAY_COLORS) + 1):
            day_colors[day_num] = self.DAY_COLORS[day_num - 1]

        # Add markers and lines
        for day_num, activities in locations.items():
            color = day_colors.get(day_num, "#333333")

            for loc_name, coords in activities:
                if coords:
                    marker = Marker(
                        location=coords,
                        popup=folium.Popup(f"{loc_name}<br>Day {day_num}", max_width=150),
                        icon=folium.Icon(color="white", icon_color=color, prefix="fa", icon="map-marker"),
                    )
                    marker.add_to(m)

            # Draw lines between activities of the same day
            if len(activities) > 1:
                coords_list = [c for _, c in activities if c]
                if len(coords_list) > 1:
                    PolyLine(coords_list, color=color, weight=2, opacity=0.7).add_to(m)

        # Add legend
        self._add_legend(m, day_colors, len(locations))

        logger.info(f"Map rendered with {sum(len(a) for a in locations.values())} locations across {len(locations)} days")
        return m

    def _extract_locations(
        self,
        itinerary: list[dict[str, Any]],
        origin: str | None = None,
    ) -> dict[int, list[tuple[str, tuple[float, float] | None]]]:
        """Extract locations from itinerary and geocode them.

        Returns dict mapping day number to list of (name, coordinates) tuples.
        """
        locations: dict[int, list[tuple[str, tuple[float, float] | None]]] = {}

        for day in itinerary:
            day_num = day.get("day", 1)
            activities = []

            # Add origin if provided
            if origin:
                logger.debug(f"Geocoding origin: {origin}")
                origin_coords = self._geocode(origin)
                if origin_coords:
                    activities.append((origin, origin_coords))

            # Extract activities from morning, afternoon, evening
            for time_period in ["morning", "afternoon", "evening"]:
                for activity in day.get(time_period, []):
                    coords = self._geocode(activity)
                    activities.append((activity, coords))

            locations[day_num] = activities

        return locations

    def _geocode(self, location: str) -> tuple[float, float] | None:
        """Geocode a location name to coordinates.
        
        Uses Google Maps API first if available (for bulk usage), then falls back
        to Nominatim (OpenStreetMap) with known cities as final fallback.
        """
        if not location:
            return None

        # Check cache first
        cache_key = location.lower().strip()
        if cache_key in self._geocode_cache:
            logger.debug(f"Geocode cache hit for '{location}': {self._geocode_cache[cache_key]}")
            return self._geocode_cache[cache_key]

        result = None
        source = "none"

        # Try Google Maps API first (for bulk usage with API key)
        if self._google_maps_key:
            logger.debug(f"Attempting Google Maps geocoding for '{location}'")
            result = self._geocode_google(location)
            if result:
                source = "google"
            else:
                logger.debug(f"Google Maps failed for '{location}', trying Nominatim")

        # Fallback to Nominatim if Google Maps failed or no API key
        if result is None:
            logger.debug(f"Attempting Nominatim geocoding for '{location}'")
            result = self._geocode_nominatim(location)
            if result:
                source = "nominatim"
            else:
                logger.debug(f"Nominatim failed for '{location}', trying known cities")

        # Cache the result (even if None)
        self._geocode_cache[cache_key] = result

        # Final fallback to known cities
        if result is None:
            result = self._fallback_geocode(location)
            if result:
                source = "known_cities"
                self._geocode_cache[cache_key] = result

        if result:
            logger.info(f"Geocoded '{location}' -> {result} (source: {source})")
        else:
            logger.warning(f"Failed to geocode '{location}' from all sources")

        return result

    def _geocode_google(self, location: str) -> tuple[float, float] | None:
        """Geocode using Google Maps API (for bulk usage with API key)."""
        if not self._google_maps_key:
            logger.debug("No Google Maps API key available, skipping Google geocoding")
            return None

        try:
            url = "https://maps.googleapis.com/maps/api/geocode/json"
            params = {
                "address": location,
                "key": self._google_maps_key,
            }

            with httpx.Client(timeout=15.0) as client:
                response = client.get(url, params=params)
                response.raise_for_status()
                results = response.json()

                if results.get("status") == "OK" and results.get("results"):
                    loc = results["results"][0]["geometry"]["location"]
                    coords = (float(loc["lat"]), float(loc["lng"]))
                    logger.debug(f"Google Maps API success for '{location}': {coords}")
                    return coords
                else:
                    status = results.get("status", "UNKNOWN")
                    logger.debug(f"Google Maps returned status: {status}")

        except Exception as e:
            logger.debug(f"Google Maps geocoding failed for '{location}': {e}")

        return None

    def _geocode_nominatim(self, location: str) -> tuple[float, float] | None:
        """Geocode using Nominatim (OpenStreetMap) as fallback."""
        try:
            # Respect Nominatim usage policy: 1 second delay between requests
            elapsed = time.time() - self._last_geocode_time
            if elapsed < 1.0:
                sleep_time = 1.0 - elapsed
                logger.debug(f"Rate limiting Nominatim, sleeping {sleep_time:.2f}s")
                time.sleep(sleep_time)

            url = "https://nominatim.openstreetmap.org/search"
            params = {
                "q": location,
                "format": "json",
                "limit": 1,
                "addressdetails": 1,
            }

            headers = {
                "User-Agent": "AgenticTravelPlanner/0.1 (contact@example.com)",
                "Accept-Language": "en",
            }

            with httpx.Client(timeout=15.0) as client:
                response = client.get(url, params=params, headers=headers)
                response.raise_for_status()
                results = response.json()

                if results:
                    lat = float(results[0]["lat"])
                    lon = float(results[0]["lon"])
                    coords = (lat, lon)
                    self._last_geocode_time = time.time()
                    return coords

        except Exception as e:
            logger.debug(f"Nominatim geocoding failed for '{location}': {e}")

        self._last_geocode_time = time.time()
        return None

    def _fallback_geocode(self, location: str) -> tuple[float, float] | None:
        """Fallback geocoder with common world cities."""
        location_lower = location.lower()

        # Extended list of world cities
        known_locations = {
            # Europe
            "paris": (48.8566, 2.3522),
            "london": (51.5074, -0.1278),
            "rome": (41.9028, 12.4964),
            "berlin": (52.5200, 13.4050),
            "amsterdam": (52.3676, 4.9041),
            "vienna": (48.2082, 16.3738),
            "prague": (50.0755, 14.4378),
            "budapest": (47.4979, 19.0402),
            "zurich": (47.3769, 8.5417),
            "stockholm": (59.3293, 18.0686),
            "oslo": (59.9139, 10.7522),
            "copenhagen": (55.6761, 12.5683),
            "helsinki": (60.1699, 24.9384),
            "warsaw": (52.2297, 21.0122),
            "zagreb": (45.8150, 15.9819),
            "sarajevo": (43.8563, 18.4131),
            "tallinn": (59.4370, 24.7536),
            "riga": (56.9496, 24.1052),
            "vilnius": (54.6872, 25.2797),
            "lisbon": (38.7223, -9.1393),
            "madrid": (40.4168, -3.7038),
            "barcelona": (41.3851, 2.1734),
            "porto": (41.1496, -8.6109),
            "athens": (37.9838, 23.7275),
            "dublin": (53.3498, -6.2603),
            "edinburgh": (55.9533, -3.1883),
            "kyiv": (50.4501, 30.5234),
            "bucharest": (44.4268, 26.1025),
            "sofia": (42.6977, 23.3219),
            "belgrade": (44.7866, 20.4489),
            "bansko": (41.9356, 23.5378),
            # Asia
            "tokyo": (35.6762, 139.6503),
            "osaka": (34.6937, 135.5022),
            "kyoto": (35.0116, 135.7681),
            "beijing": (39.9042, 116.4074),
            "shanghai": (31.2304, 121.4737),
            "guangzhou": (23.1296, 113.2644),
            "shenzhen": (22.5431, 114.0579),
            "hong kong": (22.3193, 114.1694),
            "singapore": (1.3521, 103.8198),
            "bangkok": (13.7563, 100.5018),
            "seoul": (37.5665, 126.9780),
            "busan": (35.1796, 129.0756),
            "taipei": (25.0330, 121.5654),
            "manila": (14.5995, 120.9842),
            "jakarta": (-6.2146, 106.8451),
            "kuala lumpur": (3.1390, 101.6869),
            "new delhi": (28.6139, 77.2090),
            "mumbai": (19.0760, 72.8777),
            "bangalore": (12.9716, 77.5946),
            "chennai": (13.0826, 80.2707),
            "kolkata": (22.5726, 88.3639),
            "dhaka": (23.7957, 90.4183),
            "islamabad": (33.6844, 73.0479),
            "karachi": (24.8607, 67.0011),
            "teheran": (35.6892, 51.3801),
            "moscow": (55.7558, 37.6173),
            "st petersburg": (59.9343, 30.3351),
            "novosibirsk": (55.0051, 82.9130),
            "yekaterinburg": (56.8389, 60.6057),
            "nur-sultan": (49.8447, 24.7131),
            "almaty": (43.2567, 76.9446),
            # North America
            "new york": (40.7128, -74.0060),
            "los angeles": (34.0522, -118.2437),
            "san francisco": (37.7749, -122.4194),
            "chicago": (41.8781, -87.6298),
            "toronto": (43.6532, -79.3832),
            "vancouver": (49.2827, -123.1207),
            "montreal": (45.5017, -73.5673),
            "mexico city": (19.4326, -99.1332),
            "sao paulo": (-23.5505, -46.6333),
            "rio de janeiro": (-22.9068, -43.1729),
            "buenos aires": (-34.6037, -58.3816),
            "santiago": (-33.4489, -70.6693),
            "lima": (-12.0464, -77.0428),
            "bogota": (4.6097, -74.0817),
            "caracas": (10.1455, -66.0756),
            "quito": (-0.1807, -78.4678),
            # Oceania
            "sydney": (-33.8688, 151.2093),
            "melbourne": (-37.8136, 144.9631),
            "brisbane": (-27.4698, 153.0251),
            "auckland": (-36.8485, 174.7633),
            "wellington": (-41.2865, 174.7762),
            # Africa
            "cairo": (30.0444, 31.2357),
            "alexandria": (31.2001, 29.9187),
            "lagos": (6.5244, 3.3792),
            "nairobi": (-1.2921, 36.8219),
            "johannesburg": (-26.2041, 28.0473),
            "casablanca": (33.5731, -7.5898),
            "tunis": (36.8065, 10.1815),
            # Middle East
            "dubai": (25.2048, 55.2708),
            "abu dhabi": (24.4539, 54.3773),
            "riyadh": (24.7136, 46.6753),
            "tel aviv": (32.0853, 34.7818),
            "amman": (31.9454, 35.9284),
            "beirut": (33.8547, 35.4277),
        }

        # Check for exact match
        if location_lower in known_locations:
            logger.debug(f"Matched '{location}' to known city: {location_lower}")
            return known_locations[location_lower]

        # Check for partial matches
        for name, coords in known_locations.items():
            if name in location_lower:
                logger.debug(f"Partial match for '{location}' -> {name}")
                return coords

        return None

    def _add_legend(
        self,
        m: folium.Map,
        day_colors: dict[int, str],
        max_days: int,
    ) -> None:
        """Add a color legend to the map."""
        legend_html = """
        <div style="
            position: fixed;
            bottom: 50px;
            left: 50px;
            width: 180px;
            background: white;
            padding: 10px;
            border-radius: 8px;
            box-shadow: 0 0 15px rgba(0,0,0,0.3);
            z-index: 9999;
            font-size: 12px;
        ">
            <b>Legend</b><br>
            <i style="color: #1f77b4;">●</i> Day 1<br>
            """
        for day in range(2, min(max_days + 1, len(self.DAY_COLORS) + 1)):
            color = day_colors.get(day, "#333333")
            legend_html += f'<i style="color: {color};">●</i> Day {day}<br>'

        legend_html += "</div>"
        m.get_root().html.add_child(folium.Element(legend_html))

    def _autocomplete_google(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Get autocomplete suggestions using Google Places API."""
        if not self._google_maps_key:
            logger.debug("No Google Maps API key available, skipping Google autocomplete")
            return []

        try:
            url = "https://maps.googleapis.com/maps/api/place/autocomplete/json"
            params = {
                "input": query,
                "key": self._google_maps_key,
                "radius": 50000000,  # 50,000 km radius (worldwide)
                "language": "en",
                "types": "(cities)",
                "components": "country:US,CA,MX,GB,FR,DE,IT,ES,JP,CN,IN,AU,NZ,BR,RU,KR,SG,MY,TH,ID,PH,VN,SA,AE,IL,TR,PL,NL,BE,NOR,NL,DK,SE,NO,FI,CH,AT,CZ,HU,RO,BG,RS,SK,CY,GR,PT,IE,MT,LI,MC,SM,VA,IS,LU,MT,GR,TR,CY,RO,BG,HR,SI,BA,ME,AL,MK,DK,FY,EE,LV,LT,MT,GR,PT,ES,AD,MC,LI,SM,VA,IS,LU,MT,GR,TR,CY,RO,BG,HR,SI,BA,ME,AL,MK,DK,FY,EE,LV,LT",
            }

            with httpx.Client(timeout=10.0) as client:
                response = client.get(url, params=params)
                response.raise_for_status()
                results = response.json()

                if results.get("status") == "OK":
                    suggestions = []
                    for item in results.get("predictions", [])[:limit]:
                        # Get place details to get location
                        place_id = item["place_id"]
                        details_url = "https://maps.googleapis.com/maps/api/place/details/json"
                        details_params = {
                            "place_id": place_id,
                            "key": self._google_maps_key,
                            "fields": "geometry/location,address_component",
                        }
                        with httpx.Client(timeout=10.0) as details_client:
                            details_resp = details_client.get(details_url, params=details_params)
                            details_resp.raise_for_status()
                            details = details_resp.json()
                        
                        if details.get("status") == "OK" and details.get("result"):
                            loc = details["result"]["geometry"]["location"]
                            country = ""
                            for comp in details["result"].get("address_components", []):
                                if "country" in comp.get("types", []):
                                    country = comp.get("long_name", "")
                                    break
                            
                            suggestions.append({
                                "name": item["description"],
                                "lat": float(loc["lat"]),
                                "lon": float(loc["lng"]),
                                "country": country,
                            })
                    
                    logger.info(f"Google Places autocomplete: found {len(suggestions)} suggestions for '{query}'")
                    return suggestions

        except Exception as e:
            logger.debug(f"Google Places autocomplete failed for '{query}': {e}")

        return []

    def autocomplete(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Get autocomplete suggestions for a location query.

        Uses Google Places API first if available, then falls back to Nominatim,
        and finally to a database of known cities.

        Args:
            query: Partial location name to search
            limit: Maximum number of results to return

        Returns:
            List of dicts with 'name', 'lat', 'lon', 'country' keys
        """
        if not query or len(query) < 2:
            logger.debug(f"Autocomplete query too short: '{query}'")
            return []

        suggestions = []
        query_lower = query.lower()

        # Try Google Places API first (for bulk usage with API key)
        if self._google_maps_key:
            logger.debug(f"Attempting Google Places autocomplete for '{query}'")
            suggestions = self._autocomplete_google(query, limit)
            if suggestions:
                logger.info(f"Google Places autocomplete: {len(suggestions)} results for '{query}'")
                return suggestions
            else:
                logger.debug(f"Google Places autocomplete failed, trying Nominatim")

        # Try Nominatim
        try:
            url = "https://nominatim.openstreetmap.org/search"
            params = {
                "q": query,
                "format": "json",
                "limit": limit,
                "addressdetails": 1,
                "extratags": 1,
            }

            headers = {
                "User-Agent": "AgenticTravelPlanner/0.1 (contact@example.com)",
                "Accept-Language": "en",
            }

            with httpx.Client(timeout=10.0) as client:
                response = client.get(url, params=params, headers=headers)
                response.raise_for_status()
                results = response.json()

                for item in results:
                    suggestions.append({
                        "name": item.get("display_name", ""),
                        "lat": float(item["lat"]),
                        "lon": float(item["lon"]),
                        "country": item.get("address", {}).get("country", ""),
                    })
                if suggestions:
                    logger.info(f"Nominatim autocomplete: {len(suggestions)} results for '{query}'")
                    return suggestions

        except Exception as e:
            logger.debug(f"Nominatim autocomplete failed for '{query}': {e}")
            pass

        # Fallback to known locations when Nominatim fails
        known_locations = {
            # Europe
            "paris": (48.8566, 2.3522, "France"),
            "london": (51.5074, -0.1278, "United Kingdom"),
            "rome": (41.9028, 12.4964, "Italy"),
            "berlin": (52.5200, 13.4050, "Germany"),
            "amsterdam": (52.3676, 4.9041, "Netherlands"),
            "vienna": (48.2082, 16.3738, "Austria"),
            "prague": (50.0755, 14.4378, "Czech Republic"),
            "budapest": (47.4979, 19.0402, "Hungary"),
            "zurich": (47.3769, 8.5417, "Switzerland"),
            "stockholm": (59.3293, 18.0686, "Sweden"),
            "oslo": (59.9139, 10.7522, "Norway"),
            "copenhagen": (55.6761, 12.5683, "Denmark"),
            "helsinki": (60.1699, 24.9384, "Finland"),
            "warsaw": (52.2297, 21.0122, "Poland"),
            "zagreb": (45.8150, 15.9819, "Croatia"),
            "sarajevo": (43.8563, 18.4131, "Bosnia and Herzegovina"),
            "tallinn": (59.4370, 24.7536, "Estonia"),
            "riga": (56.9496, 24.1052, "Latvia"),
            "vilnius": (54.6872, 25.2797, "Lithuania"),
            "lisbon": (38.7223, -9.1393, "Portugal"),
            "madrid": (40.4168, -3.7038, "Spain"),
            "barcelona": (41.3851, 2.1734, "Spain"),
            "porto": (41.1496, -8.6109, "Portugal"),
            "athens": (37.9838, 23.7275, "Greece"),
            "dublin": (53.3498, -6.2603, "Ireland"),
            "edinburgh": (55.9533, -3.1883, "United Kingdom"),
            "kyiv": (50.4501, 30.5234, "Ukraine"),
            "bucharest": (44.4268, 26.1025, "Romania"),
            "sofia": (42.6977, 23.3219, "Bulgaria"),
            "belgrade": (44.7866, 20.4489, "Serbia"),
            "bansko": (41.9356, 23.5378, "Bulgaria"),
            # Asia
            "tokyo": (35.6762, 139.6503, "Japan"),
            "osaka": (34.6937, 135.5022, "Japan"),
            "kyoto": (35.0116, 135.7681, "Japan"),
            "beijing": (39.9042, 116.4074, "China"),
            "shanghai": (31.2304, 121.4737, "China"),
            "guangzhou": (23.1296, 113.2644, "China"),
            "shenzhen": (22.5431, 114.0579, "China"),
            "hong kong": (22.3193, 114.1694, "Hong Kong"),
            "singapore": (1.3521, 103.8198, "Singapore"),
            "bangkok": (13.7563, 100.5018, "Thailand"),
            "seoul": (37.5665, 126.9780, "South Korea"),
            "busan": (35.1796, 129.0756, "South Korea"),
            "taipei": (25.0330, 121.5654, "Taiwan"),
            "manila": (14.5995, 120.9842, "Philippines"),
            "jakarta": (-6.2146, 106.8451, "Indonesia"),
            "kuala lumpur": (3.1390, 101.6869, "Malaysia"),
            "new delhi": (28.6139, 77.2090, "India"),
            "mumbai": (19.0760, 72.8777, "India"),
            "bangalore": (12.9716, 77.5946, "India"),
            "chennai": (13.0826, 80.2707, "India"),
            "kolkata": (22.5726, 88.3639, "India"),
            "dhaka": (23.7957, 90.4183, "Bangladesh"),
            "islamabad": (33.6844, 73.0479, "Pakistan"),
            "karachi": (24.8607, 67.0011, "Pakistan"),
            "teheran": (35.6892, 51.3801, "Iran"),
            "moscow": (55.7558, 37.6173, "Russia"),
            "st petersburg": (59.9343, 30.3351, "Russia"),
            "novosibirsk": (55.0051, 82.9130, "Russia"),
            "yekaterinburg": (56.8389, 60.6057, "Russia"),
            "nur-sultan": (49.8447, 24.7131, "Kazakhstan"),
            "almaty": (43.2567, 76.9446, "Kazakhstan"),
            # North America
            "new york": (40.7128, -74.0060, "United States"),
            "los angeles": (34.0522, -118.2437, "United States"),
            "san francisco": (37.7749, -122.4194, "United States"),
            "chicago": (41.8781, -87.6298, "United States"),
            "toronto": (43.6532, -79.3832, "Canada"),
            "vancouver": (49.2827, -123.1207, "Canada"),
            "montreal": (45.5017, -73.5673, "Canada"),
            "mexico city": (19.4326, -99.1332, "Mexico"),
            "sao paulo": (-23.5505, -46.6333, "Brazil"),
            "rio de janeiro": (-22.9068, -43.1729, "Brazil"),
            "buenos aires": (-34.6037, -58.3816, "Argentina"),
            "santiago": (-33.4489, -70.6693, "Chile"),
            "lima": (-12.0464, -77.0428, "Peru"),
            "bogota": (4.6097, -74.0817, "Colombia"),
            "caracas": (10.1455, -66.0756, "Venezuela"),
            "quito": (-0.1807, -78.4678, "Ecuador"),
            # Oceania
            "sydney": (-33.8688, 151.2093, "Australia"),
            "melbourne": (-37.8136, 144.9631, "Australia"),
            "brisbane": (-27.4698, 153.0251, "Australia"),
            "auckland": (-36.8485, 174.7633, "New Zealand"),
            "wellington": (-41.2865, 174.7762, "New Zealand"),
            # Africa
            "cairo": (30.0444, 31.2357, "Egypt"),
            "alexandria": (31.2001, 29.9187, "Egypt"),
            "lagos": (6.5244, 3.3792, "Nigeria"),
            "nairobi": (-1.2921, 36.8219, "Kenya"),
            "johannesburg": (-26.2041, 28.0473, "South Africa"),
            "casablanca": (33.5731, -7.5898, "Morocco"),
            "tunis": (36.8065, 10.1815, "Tunisia"),
            # Middle East
            "dubai": (25.2048, 55.2708, "United Arab Emirates"),
            "abu dhabi": (24.4539, 54.3773, "United Arab Emirates"),
            "riyadh": (24.7136, 46.6753, "Saudi Arabia"),
            "tel aviv": (32.0853, 34.7818, "Israel"),
            "amman": (31.9454, 35.9284, "Jordan"),
            "beirut": (33.8547, 35.4277, "Lebanon"),
        }

        # Find matching locations
        for name, (lat, lon, country) in known_locations.items():
            # Match if query is a substring of the name, or name contains query
            if (query_lower in name or name in query_lower) and len(suggestions) < limit:
                suggestions.append({
                    "name": name.title(),
                    "lat": lat,
                    "lon": lon,
                    "country": country,
                })

        if suggestions:
            logger.info(f"Known cities autocomplete: {len(suggestions)} results for '{query}'")
        else:
            logger.debug(f"No autocomplete results for '{query}'")

        return suggestions

    def validate_address(self, location: str) -> dict[str, Any]:
        """Validate and get detailed information about a location.

        Args:
            location: Location name or address to validate

        Returns:
            Dict with 'valid', 'coordinates', 'formatted_name', 'address' keys
        """
        logger.debug(f"Validating address: '{location}'")
        
        if not location:
            logger.debug("Empty location provided for validation")
            return {"valid": False, "coordinates": None, "formatted_name": "", "address": {}}

        coords = self._geocode(location)

        if coords:
            logger.info(f"Address validation successful for '{location}': {coords}")
            return {
                "valid": True,
                "coordinates": coords,
                "formatted_name": location,
                "address": {"lat": coords[0], "lon": coords[1]},
            }

        logger.warning(f"Address validation failed for '{location}'")
        return {"valid": False, "coordinates": None, "formatted_name": location, "address": {}}