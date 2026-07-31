"""External intelligence tools."""

from agentic_tour_planner.tools.ai_stack_client import AiStackClient
from agentic_tour_planner.tools.map_tool import MapTool
from agentic_tour_planner.tools.weather import WeatherTool

# Temporary exports - will be removed when obsolete files are deleted
try:
    from agentic_tour_planner.tools.web_search import WebSearchTool
except ImportError:
    WebSearchTool = None

try:
    from agentic_tour_planner.tools.place_intel import lookup_opening_hours
except ImportError:
    lookup_opening_hours = None

__all__ = [
    "AiStackClient",
    "MapTool",
    "WeatherTool",
    "WebSearchTool",
    "lookup_opening_hours",
]
