from __future__ import annotations

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentic_tour_planner.domain.models import PlanningResponse

from agentic_tour_planner.domain.models import PlaceImage
from agentic_tour_planner.images.pipeline import resolve_images as _pipeline_resolve
from agentic_tour_planner.utils.logging import get_logger

logger = get_logger(__name__)


def collect_places_for_images(response: PlanningResponse) -> list[dict]:
    """Extract place dicts from a PlanningResponse itinerary for image resolution.

    Returns a list of dicts with 'place_name' and 'image_query' keys,
    suitable for passing to ``resolve_images()``.
    """
    places: list[dict] = []
    seen: set[str] = set()
    for day in response.itinerary:
        for spot in day.spots:
            q = spot.image_query or spot.name
            if q and spot.name not in seen:
                seen.add(spot.name)
                places.append({"place_name": spot.name, "image_query": q})
    return places


async def resolve_images(places: list[dict]) -> list[PlaceImage]:
    """Resolve images for a list of places using the multi-source pipeline.

    Each dict should have 'place_name' and optionally 'image_query'.
    Returns a list of PlaceImage objects compatible with the existing API.
    """
    if not places:
        return []

    results = await _pipeline_resolve(places)

    return [
        PlaceImage(
            place_name=r.place_name,
            image_query="",  # original query not stored in ImageResult
            image_url=r.image_url,
            source=r.source,
            license=r.license,
            attribution=r.attribution,
            clip_score=r.clip_score,
            verified=r.verified,
            width=r.width,
            height=r.height,
        )
        for r in results
    ]
