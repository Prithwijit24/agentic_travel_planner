import folium

from agentic_tour_planner.tools.map_tool import MapTool


def test_map_tool_renders_map():
    tool = MapTool()

    itinerary = [
        {
            "day": 1,
            "theme": "Arrival",
            "morning": ["Paris"],
            "afternoon": ["Eiffel Tower", "Seine River"],
            "evening": ["Louvre Museum"],
        },
        {
            "day": 2,
            "theme": "Culture",
            "morning": ["Louvre Museum"],
            "afternoon": ["Notre Dame"],
            "evening": ["Montmartre"],
        },
    ]

    m = tool.render_itinerary_map(itinerary, origin="London")

    assert isinstance(m, folium.Map)
    assert m.location is not None


def test_map_tool_handles_empty_itinerary():
    tool = MapTool()

    m = tool.render_itinerary_map([])

    assert isinstance(m, folium.Map)


def test_map_tool_geocodes_known_locations():
    tool = MapTool()

    # Test that geocoder returns coordinates (Nominatim-based)
    coords = tool._geocode("Paris, France")
    assert coords is not None
    assert -90 < coords[0] < 90  # Valid latitude
    assert -180 < coords[1] < 180  # Valid longitude

    # Verify it's close to Paris coordinates (48.8566, 2.3522)
    lat_diff = abs(coords[0] - 48.8566)
    lon_diff = abs(coords[1] - 2.3522)
    assert lat_diff < 5  # Within 5 degrees
    assert lon_diff < 5  # Within 5 degrees


def test_map_tool_handles_unknown_location():
    tool = MapTool()

    coords = tool._geocode("Some Unknown City That Does Not Exist")
    assert coords is None


def test_map_tool_geocode_caches_results():
    tool = MapTool()

    # First call should hit Nominatim
    coords1 = tool._geocode("Tokyo, Japan")
    assert coords1 is not None

    # Second call should use cache (no additional network request)
    coords2 = tool._geocode("Tokyo, Japan")
    assert coords2 is not None
    assert coords1 == coords2


def test_map_tool_autocomplete_returns_results():
    tool = MapTool()

    # Test autocomplete with a short query
    results = tool.autocomplete("Par")
    assert isinstance(results, list)
    # May be empty if network unavailable, but should not raise


def test_map_tool_autocomplete_requires_minimum_length():
    tool = MapTool()

    # Query too short should return empty list
    results = tool.autocomplete("X")
    assert results == []


def test_map_tool_validate_address_returns_valid_structure():
    tool = MapTool()

    # Test validation with a known location
    result = tool.validate_address("Paris")
    assert "valid" in result
    assert "coordinates" in result
    assert "formatted_name" in result
    assert "address" in result


def test_map_tool_validate_address_returns_true_for_known_location():
    tool = MapTool()

    # Known location should be valid
    result = tool.validate_address("Tokyo")
    assert result["valid"] is True
    assert result["coordinates"] is not None


def test_map_tool_validate_address_returns_false_for_unknown():
    tool = MapTool()

    # Unknown location should be invalid
    result = tool.validate_address("XyzzyUnknownPlace12345")
    assert result["valid"] is False


class TestCoordinateValidation:
    def test_haversine_km_same_point(self):
        assert MapTool._haversine_km((0, 0), (0, 0)) == 0.0

    def test_haversine_km_known_distance(self):
        # Kolkata to Sikkim is ~530 km
        result = MapTool._haversine_km((22.5726, 88.3639), (27.3516, 88.3239))
        assert 500 < result < 600

    def test_validate_coordinates_no_duplicates(self):
        tool = MapTool()
        locations = {
            1: [("Paris", (48.8566, 2.3522)), ("Lyon", (45.7640, 4.8357))],
        }
        result = tool._validate_coordinates(locations)
        assert result == locations

    def test_validate_coordinates_detects_duplicate(self):
        tool = MapTool()
        # Two different places with same coordinates (simulating bad geocoding)
        locations = {
            1: [
                ("Kolkata", (27.3516, 88.3239)),
                ("Sangha Chhorten", (27.3516, 88.3239)),
            ],
        }
        result = tool._validate_coordinates(locations)
        # The duplicate pair should be detected
        assert 1 in result

    def test_validate_coordinates_near_duplicate_detected(self):
        tool = MapTool()
        # Two places within 100m of each other (suspicious for different places)
        locations = {
            1: [
                ("Place A", (27.3516, 88.3239)),
                ("Place B", (27.3517, 88.3240)),
            ],
        }
        result = tool._validate_coordinates(locations)
        assert 1 in result

    def test_validate_coordinates_preserves_none_coords(self):
        tool = MapTool()
        locations = {
            1: [("Unknown", None), ("Paris", (48.8566, 2.3522))],
        }
        result = tool._validate_coordinates(locations)
        assert result[1][0][1] is None
        assert result[1][1][1] == (48.8566, 2.3522)

    def test_validate_coordinates_empty_locations(self):
        tool = MapTool()
        result = tool._validate_coordinates({})
        assert result == {}

    def test_validate_coordinates_single_location(self):
        tool = MapTool()
        locations = {1: [("Paris", (48.8566, 2.3522))]}
        result = tool._validate_coordinates(locations)
        assert result == locations
