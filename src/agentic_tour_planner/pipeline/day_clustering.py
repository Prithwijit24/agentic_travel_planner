"""
day_clustering.py
=================
Deterministic module for splitting a list of geo-tagged POIs into N day-clusters
that are geographically coherent first, with a SOFT preference for the user's
places-per-day ask.

The user's places-per-day request is honoured as a soft cap (the high end of the
range): clusters never exceed it unless geography forces it (phase 2 below). The
low end is NOT enforced: forcing a minimum count is what caused the old
day-mixing failure mode (a distant place being dragged into a day just to fill
a count). Geographic coherence always wins over counts.

Pipeline position:
    LLM (extract POIs + coords) -> [THIS MODULE] -> LLM (write narrative/timing only)

Algorithm: single-linkage agglomerative clustering (HAC).
    1. Every POI starts as its own cluster.
    2. Phase 1: repeatedly merge the CLOSEST pair of clusters whose combined
       size stays within the soft cap (e.g. <= 5). This forms tight regional
       blobs (Gangtok city, the east-pass excursion, the Pelling monastery
       belt) and honestly leaves genuinely remote POIs (e.g. Yumthang Valley,
       60 km from everything) as their own day.
    3. Phase 2: if more clusters remain than days (sparse geography), merge the
       closest pairs regardless of size until exactly `num_days` remain.
    4. Day ordering -> nearest-neighbor chain over day-centroids, anchored at origin.
    5. Within-day stop ordering -> nearest-neighbor + 2-opt TSP improvement.
"""

import math


def haversine(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in km between two (lat, lon) points."""
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def _single_link_distance(points: list[tuple[float, float]], a: set[int], b: set[int]) -> float:
    """Distance between two clusters = min pairwise great-circle distance."""
    return min(haversine(points[i], points[j]) for i in a for j in b)


def _closest_pair(
    points: list[tuple[float, float]],
    clusters: list[set[int]],
    cap: int | None,
) -> tuple[int, int, float] | None:
    """Find the closest pair of clusters; skip pairs exceeding ``cap``.

    Returns (a, b, distance) with a < b, or None when no pair is mergeable
    under the cap.
    """
    best: tuple[int, int, float] | None = None
    for a in range(len(clusters)):
        for b in range(a + 1, len(clusters)):
            if cap is not None and len(clusters[a]) + len(clusters[b]) > cap:
                continue
            d = _single_link_distance(points, clusters[a], clusters[b])
            if best is None or d < best[2]:
                best = (a, b, d)
    return best


def balanced_geo_cluster(
    pois: list[dict],
    num_days: int,
    target_range: tuple[int, int] | None = None,
) -> list[list[dict]]:
    """
    Split POIs into `num_days` geographically coherent clusters.

    ``target_range`` (e.g. (3, 5)) is the user's places-per-day preference. Its
    high end acts as a soft cap during agglomeration; its low end is ignored —
    a day is never padded with a distant place to reach a minimum (the old
    day-mixing failure mode).

    pois: list of dicts, each MUST have 'lat' and 'lon' keys (any other keys,
          e.g. 'name', pass through untouched).
    Returns: list of length num_days, each element a list of POI dicts.
    """
    n = len(pois)
    if n < num_days:
        raise ValueError(f"{n} POIs cannot be split into {num_days} days (need at least one POI per day).")

    points: list[tuple[float, float]] = []
    for p in pois:
        if "lat" not in p or "lon" not in p:
            raise ValueError(
                f"POI {p.get('name', 'unknown')} is missing 'lat' or 'lon' key. "
                f"All POIs must have both 'lat' and 'lon' keys."
            )
        points.append((p["lat"], p["lon"]))

    cap = target_range[1] if target_range is not None else None

    # Phase 1: agglomerate the closest pairs, never exceeding the soft cap.
    clusters: list[set[int]] = [{i} for i in range(n)]
    while len(clusters) > num_days:
        pair = _closest_pair(points, clusters, cap)
        if pair is None:
            break
        a, b, _ = pair
        clusters[a] |= clusters[b]
        del clusters[b]

    # Phase 2: geography too sparse for the cap — merge closest pairs until
    # exactly num_days remain (the cap is soft after all).
    while len(clusters) > num_days:
        pair = _closest_pair(points, clusters, cap=None)
        if pair is None:
            break
        a, b, _ = pair
        clusters[a] |= clusters[b]
        del clusters[b]

    # Stable output order: smallest member index first within a day; days keep
    # the merge order (the caller may re-order days narratively).
    return [[pois[i] for i in sorted(c)] for c in clusters]


def _tsp_order(points: list[tuple[float, float]]) -> list[int]:
    """Nearest-neighbor construction + 2-opt improvement. Returns index order."""
    n = len(points)
    if n <= 2:
        return list(range(n))

    unvisited = set(range(1, n))
    order = [0]
    while unvisited:
        last = order[-1]
        nxt = min(unvisited, key=lambda i: haversine(points[last], points[i]))
        order.append(nxt)
        unvisited.remove(nxt)

    def tour_len(o):
        return sum(haversine(points[o[i]], points[o[i + 1]]) for i in range(len(o) - 1))

    improved = True
    while improved:
        improved = False
        for i in range(1, n - 1):
            for j in range(i + 1, n):
                new_order = order[:i] + order[i : j + 1][::-1] + order[j + 1 :]
                if tour_len(new_order) < tour_len(order) - 1e-9:
                    order = new_order
                    improved = True
    return order


def order_days_and_stops(
    clusters: list[list[dict]],
    origin: tuple[float, float] | None = None,
) -> list[list[dict]]:
    """
    1. Orders the days themselves into a sensible travel sequence
       (nearest-neighbor chain of day-centroids, anchored at `origin` if given).
    2. Orders stops within each day via TSP (nearest-neighbor + 2-opt).
    """
    centroids = []
    for c in clusters:
        lat = sum(p["lat"] for p in c) / len(c)
        lon = sum(p["lon"] for p in c) / len(c)
        centroids.append((lat, lon))

    day_idx = list(range(len(clusters)))
    if origin:
        day_idx.sort(key=lambda j: haversine(origin, centroids[j]))
        ordered = [day_idx[0]]
        remaining = set(day_idx[1:])
        while remaining:
            last = ordered[-1]
            nxt = min(remaining, key=lambda j: haversine(centroids[last], centroids[j]))
            ordered.append(nxt)
            remaining.remove(nxt)
        day_idx = ordered

    result = []
    for j in day_idx:
        day_points = [(p["lat"], p["lon"]) for p in clusters[j]]
        stop_order = _tsp_order(day_points)
        result.append([clusters[j][i] for i in stop_order])
    return result


if __name__ == "__main__":
    pois = [
        {"name": "MG Marg", "lat": 27.3314, "lon": 88.6138},
        {"name": "Ganesh Tok", "lat": 27.3350, "lon": 88.6220},
        {"name": "Tashi View Point", "lat": 27.3475, "lon": 88.6280},
        {"name": "Rumtek Monastery", "lat": 27.2857, "lon": 88.5615},
        {"name": "Khecheopalri Lake", "lat": 27.3617, "lon": 88.2130},
        {"name": "Pelling Skywalk", "lat": 27.3010, "lon": 88.2170},
        {"name": "Rabdentse Ruins", "lat": 27.2990, "lon": 88.2200},
        {"name": "Ravangla Buddha Park", "lat": 27.3050, "lon": 88.3630},
        {"name": "Temi Tea Garden", "lat": 27.2650, "lon": 88.3800},
        {"name": "Gyalshing Market", "lat": 27.2850, "lon": 88.2600},
        {"name": "Namchi Char Dham", "lat": 27.1650, "lon": 88.3500},
        {"name": "Solophok Chardham", "lat": 27.1600, "lon": 88.3450},
    ]

    clusters = balanced_geo_cluster(pois, num_days=4, target_range=(3, 5))
    ordered = order_days_and_stops(clusters, origin=(26.7271, 88.3953))

    for d, day in enumerate(ordered, 1):
        names = ", ".join(p["name"] for p in day)
        print(f"Day {d} ({len(day)} stops): {names}")
