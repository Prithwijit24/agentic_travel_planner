#!/usr/bin/env python
"""Test script for location services integration.

This script demonstrates:
1. Autocomplete with Google Places API (if available) or Nominatim fallback
2. Address validation
3. OSM-based geocoding with Google Maps API priority
4. Map rendering with day-based coloring

Usage:
    # Without Google Maps API key (uses Nominatim + known cities):
    uv run python test_location_services.py

    # With Google Maps API key (set the env var):
    export google_maps_api_key="YOUR_API_KEY"
    uv run python test_location_services.py
"""

import logging
import sys

# Configure logging to see the geocoding service selection
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    stream=sys.stdout,
)

from agentic_tour_planner.tools.map_tool import MapTool


def test_autocomplete(tool: MapTool) -> None:
    """Test autocomplete functionality."""
    print("\n" + "=" * 60)
    print("AUTOCOMPLETE TEST")
    print("=" * 60)
    
    queries = ["Par", "Tokyo", "New York", "Syd", "Ber"]
    
    for query in queries:
        results = tool.autocomplete(query, limit=5)
        print(f"\nQuery: '{query}'")
        print(f"Found {len(results)} results:")
        for i, result in enumerate(results[:3], 1):
            print(f"  {i}. {result['name']}")
            print(f"     Coordinates: ({result['lat']:.4f}, {result['lon']:.4f})")
            print(f"     Country: {result['country']}")


def test_validation(tool: MapTool) -> None:
    """Test address validation."""
    print("\n" + "=" * 60)
    print("ADDRESS VALIDATION TEST")
    print("=" * 60)
    
    locations = ["Paris", "Tokyo", "Eiffel Tower", "UnknownPlace12345"]
    
    for location in locations:
        result = tool.validate_address(location)
        status = "✓ VALID" if result["valid"] else "✗ INVALID"
        print(f"\n{status}: '{location}'")
        if result["valid"]:
            print(f"  Coordinates: {result['coordinates']}")
            print(f"  Formatted: {result['formatted_name']}")


def test_geocoding(tool: MapTool) -> None:
    """Test geocoding functionality."""
    print("\n" + "=" * 60)
    print("GEOCODING TEST")
    print("=" * 60)
    
    locations = ["Kyoto", "Cairo", "Sydney", "Amazon Rainforest"]
    
    for location in locations:
        coords = tool._geocode(location)
        if coords:
            print(f"✓ {location} -> ({coords[0]:.4f}, {coords[1]:.4f})")
        else:
            print(f"✗ {location} -> Not found")


def test_map_rendering(tool: MapTool) -> None:
    """Test map rendering."""
    print("\n" + "=" * 60)
    print("MAP RENDERING TEST")
    print("=" * 60)
    
    # Create a sample itinerary
    itinerary = [
        {
            "day": 1,
            "theme": "Arrival in Tokyo",
            "morning": ["Tokyo Station"],
            "afternoon": ["Shibuya Crossing", "Harajuku"],
            "evening": ["Shinjuku"],
            "meals": [],
        },
        {
            "day": 2,
            "theme": "Cultural Day",
            "morning": ["Tsukiji Outer Market"],
            "afternoon": ["Asakusa", "Ueno Park"],
            "evening": ["Tokyo Skytree"],
            "meals": [],
        },
        {
            "day": 3,
            "theme": "Day Trip",
            "morning": ["Nikko"],
            "afternoon": ["Tokyo"],
            "evening": [],
            "meals": [],
        },
    ]
    
    # Render the map
    m = tool.render_itinerary_map(itinerary, origin="Tokyo")
    
    print(f"\nMap rendered successfully!")
    print(f"Map type: {type(m).__name__}")
    print(f"Map center: {m.location}")
    
    # Save to HTML
    output_path = "/tmp/travel_map.html"
    m.save(output_path)
    print(f"Map saved to: {output_path}")


def main() -> None:
    """Run all tests."""
    print("=" * 60)
    print("LOCATION SERVICES TEST SUITE")
    print("=" * 60)
    
    # Initialize the tool
    tool = MapTool()
    
    # Run tests
    test_autocomplete(tool)
    test_validation(tool)
    test_geocoding(tool)
    test_map_rendering(tool)
    
    print("\n" + "=" * 60)
    print("ALL TESTS COMPLETED")
    print("=" * 60)


if __name__ == "__main__":
    main()