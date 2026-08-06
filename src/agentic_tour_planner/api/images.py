from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agentic_tour_planner.domain.models import PlanningResponse

from agentic_tour_planner.domain.models import PlaceImage
from agentic_tour_planner.images.pipeline import resolve_images as _pipeline_resolve
from agentic_tour_planner.utils.logging import get_logger

logger = get_logger(__name__)

# Deterministic place-type hint for search queries. When the LLM's
# `image_query` is missing, appending the place's type anchors the search to
# the physical landmark (e.g. "Hanuman Tok temple, Gangtok") instead of letting
# an ambiguous name return generic animal/deity/object photos.
_PLACE_TYPE_MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("temple", ("temple", "mandir", "hanuman", "shiva", "durga", "krishna", "sri ", "mata")),
    ("monastery", ("monastery", "gompa", "lama", "pemayangtse", "rumtek")),
    ("church", ("church", "cathedral", "basilica")),
    ("mosque", ("mosque", "masjid", "dargah")),
    ("fort", ("fort", "castle", "citadel", "ruins")),
    ("palace", ("palace", "maharaja", "haveli")),
    ("museum", ("museum", "gallery")),
    ("waterfall", ("waterfall", "falls", "ghat")),
    ("lake", ("lake", "tarn")),
    ("beach", ("beach", "cove")),
    ("valley", ("valley", "meadow")),
    ("viewpoint", ("viewpoint", "view point", "tok", "top", "hill", "peak", "pass", "ridge")),
    ("park", ("park", "sanctuary", "reserve", "garden")),
    ("market", ("market", "bazaar", "marg", "street", "square")),
    ("lighthouse", ("lighthouse",)),
    ("cave", ("cave",)),
    ("island", ("island",)),
    ("bridge", ("bridge",)),
)


def _place_type_hint(name: str) -> str:
    """Infer the place's physical type from its name ("" when unknown)."""
    n = (name or "").lower()
    for place_type, markers in _PLACE_TYPE_MARKERS:
        if any(m in n for m in markers):
            return place_type
    return ""


def collect_places_for_images(response: PlanningResponse, destination: str = "") -> list[dict]:
    """Extract place dicts from a PlanningResponse itinerary for image resolution.

    Returns a list of dicts with 'place_name' and 'image_query' keys,
    suitable for passing to ``resolve_images()``.

    The destination is appended to each image query so searches resolve to the
    correct region (e.g. 'Zero Point, Gangtok') instead of a same-named place
    elsewhere. When the LLM's own ``image_query`` is absent, a deterministic
    place-type hint is appended (e.g. 'Hanuman Tok temple, Gangtok') so the
    query targets the physical landmark rather than whatever the name evokes.
    """
    dest_suffix = destination.strip()
    places: list[dict] = []
    seen: set[str] = set()
    for day in response.itinerary:
        for spot in day.spots:
            q = spot.image_query or spot.name
            if q and spot.name not in seen:
                seen.add(spot.name)
                if dest_suffix and dest_suffix.lower() not in q.lower():
                    q = f"{q}, {dest_suffix}"
                place_type = _place_type_hint(q)
                if place_type and place_type not in q.lower():
                    q = f"{q} {place_type}"
                places.append({"place_name": spot.name, "image_query": q, "place_type": place_type})
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
