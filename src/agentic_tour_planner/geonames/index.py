from __future__ import annotations

import atexit
import pickle
import time
from pathlib import Path
from typing import NamedTuple

import marisa_trie
from rapidfuzz import fuzz

from agentic_tour_planner.config.settings import get_settings
from agentic_tour_planner.geonames.parser import (
    City,
    parse_admin1_codes,
    parse_alternate_names,
    parse_cities1000,
    parse_country_info,
)
from agentic_tour_planner.utils.logging import get_logger

logger = get_logger(__name__)

INDEX_DIR = Path(__file__).resolve().parents[1] / "data" / "ui"


class Suggestion(NamedTuple):
    name: str
    latitude: float
    longitude: float
    country: str
    admin1: str
    population: int


_ID_COUNTER: list[int] = [-1]


def _next_id() -> int:
    _ID_COUNTER[0] -= 1
    return _ID_COUNTER[0]


def _build_index() -> tuple[
    list[City],
    marisa_trie.Trie,
    dict[str, list[int]],
    dict[str, str],
    dict[str, tuple[str, int]],
]:
    t0 = time.time()

    logger.info("Parsing cities1000 ...")
    cities = parse_cities1000()
    logger.info(f"  loaded {len(cities)} cities")

    valid_ids = {c.geonameid for c in cities}

    logger.info("Parsing alternate names (filtered to our cities) ...")
    alt_names = parse_alternate_names(valid_ids)
    logger.info(f"  loaded alt names for {len(alt_names)} cities")

    logger.info("Parsing admin1 codes & country info ...")
    admin1_map = parse_admin1_codes()
    country_data = parse_country_info()
    logger.info(f"  admin1: {len(admin1_map)}, countries: {len(country_data)}")

    logger.info("Adding states (ADM1) as searchable entries ...")
    state_added = 0
    for code, state_name in admin1_map.items():
        dot = code.find(".")
        if dot == -1:
            continue
        cc = code[:dot]
        a1 = code[dot + 1 :]
        country_name = country_data.get(cc, ("", 0))[0]
        cities.append(
            City(
                geonameid=_next_id(),
                name="",
                asciiname=state_name,
                latitude=0.0,
                longitude=0.0,
                country_code=cc,
                admin1_code=a1,
                population=1_000_000,
                feature_code="ADM1",
            )
        )
        state_added += 1
    logger.info(f"  added {state_added} states")

    logger.info("Adding countries (PCLI) as searchable entries ...")
    country_added = 0
    for iso, (country_name, pop) in country_data.items():
        if not country_name:
            continue
        cities.append(
            City(
                geonameid=_next_id(),
                name="",
                asciiname=country_name,
                latitude=0.0,
                longitude=0.0,
                country_code=iso,
                admin1_code="",
                population=pop if pop > 0 else 1_000_000,
                feature_code="PCLI",
            )
        )
        country_added += 1
    logger.info(f"  added {country_added} countries")

    logger.info("Building name → city-index lookup ...")
    name_to_idxs: dict[str, list[int]] = {}
    for idx, city in enumerate(cities):
        _add_name(name_to_idxs, city.name.lower(), idx)
        if city.asciiname.lower() != city.name.lower():
            _add_name(name_to_idxs, city.asciiname.lower(), idx)
        alt_list = alt_names.get(city.geonameid, [])
        for alt in alt_list:
            _add_name(name_to_idxs, alt.lower(), idx)

    logger.info("Building marisa-trie ...")
    trie = marisa_trie.Trie(name_to_idxs.keys())

    elapsed = time.time() - t0
    logger.info(
        f"Index built: {len(cities)} total entries "
        f"({len(cities) - state_added - country_added} cities, "
        f"{state_added} states, {country_added} countries), "
        f"{len(trie):,} trie keys, "
        f"{sum(len(v) for v in name_to_idxs.values()):,} total mappings "
        f"in {elapsed:.1f}s"
    )
    return cities, trie, name_to_idxs, admin1_map, country_data


def _add_name(mapping: dict[str, list[int]], key: str, idx: int) -> None:
    if key in mapping:
        mapping[key].append(idx)
    else:
        mapping[key] = [idx]


def _save_index(
    cities: list[City],
    trie: marisa_trie.Trie,
    name_to_idxs: dict[str, list[int]],
    admin1_map: dict[str, str],
    country_data: dict[str, tuple[str, int]],
) -> None:
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    pickle_path = INDEX_DIR / "geonames_index.pkl"
    trie_path = INDEX_DIR / "geonames_trie.marisa"

    payload = {
        "cities": cities,
        "name_to_idxs": name_to_idxs,
        "admin1_map": admin1_map,
        "country_data": country_data,
        "version": 3,
    }
    with pickle_path.open("wb") as f:
        pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
    trie.save(str(trie_path))
    logger.info(f"Index saved to {pickle_path} and {trie_path}")


def _load_index() -> (
    tuple[
        list[City],
        marisa_trie.Trie,
        dict[str, list[int]],
        dict[str, str],
        dict[str, tuple[str, int]],
    ]
    | None
):
    pickle_path = INDEX_DIR / "geonames_index.pkl"
    trie_path = INDEX_DIR / "geonames_trie.marisa"
    if not pickle_path.exists() or not trie_path.exists():
        return None

    with pickle_path.open("rb") as f:
        payload = pickle.load(f)  # noqa: S301 -- local self-generated cache index
    if payload.get("version") != 3:
        logger.info("Index version mismatch, rebuilding ...")
        return None
    trie = marisa_trie.Trie()
    trie.load(str(trie_path))
    logger.info(f"Index loaded: {len(payload['cities'])} entries, {len(trie):,} trie keys")
    country_data = payload.get("country_data", {})
    return (
        payload["cities"],
        trie,
        payload["name_to_idxs"],
        payload["admin1_map"],
        country_data,
    )


_INDEX_CACHE: (
    tuple[
        list[City],
        marisa_trie.Trie,
        dict[str, list[int]],
        dict[str, str],
        dict[str, tuple[str, int]],
    ]
    | None
) = None


def _get_index():
    global _INDEX_CACHE
    if _INDEX_CACHE is not None:
        return _INDEX_CACHE
    index = _load_index()
    if index is None:
        logger.info("No cached index found, building from scratch ...")
        index = _build_index()
        _save_index(*index)
    _INDEX_CACHE = index
    return index


def search_places(query: str, limit: int | None = None) -> list[Suggestion]:
    if not query or len(query) < 1:
        return []
    if limit is None:
        limit = get_settings().geonames_suggestion_limit
    q = query.lower().strip()

    cities, trie, name_to_idxs, admin1_map, country_data = _get_index()

    prefix_keys = trie.keys(q)
    if not prefix_keys:
        return []

    candidate_idxs: dict[int, float] = {}
    for key in prefix_keys:
        for idx in name_to_idxs.get(key, []):
            score = fuzz.partial_ratio(q, key)
            if idx in candidate_idxs:
                candidate_idxs[idx] = max(candidate_idxs[idx], score)
            else:
                candidate_idxs[idx] = score

    sorted_idxs = sorted(
        candidate_idxs.items(),
        key=lambda x: (-x[1], -cities[x[0]].population),
    )

    results: list[Suggestion] = []
    seen: set[int] = set()
    for idx, _ in sorted_idxs:
        city = cities[idx]
        if city.geonameid in seen:
            continue
        seen.add(city.geonameid)

        country_name = country_data.get(city.country_code, ("", 0))[0] if city.country_code else ""
        admin1_key = f"{city.country_code}.{city.admin1_code}" if city.admin1_code else ""
        admin1 = admin1_map.get(admin1_key, "")

        parts = [p for p in [city.name, admin1, country_name] if p]
        display_name = ", ".join(parts) if parts else city.asciiname

        results.append(
            Suggestion(
                name=display_name,
                latitude=city.latitude,
                longitude=city.longitude,
                country=country_name,
                admin1=admin1,
                population=city.population,
            )
        )
        if len(results) >= limit:
            break

    return results


@atexit.register
def _atexit_clear_cache():
    global _INDEX_CACHE
    _INDEX_CACHE = None
