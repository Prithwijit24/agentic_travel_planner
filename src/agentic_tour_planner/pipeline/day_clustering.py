"""
day_clustering.py
==================
Deterministic module for splitting a list of geo-tagged POIs into N day-clusters
with a HARD [min_per_day, max_per_day] size constraint, while keeping clusters
geographically coherent. Replaces "ask the LLM nicely" with an actual solver.

Pipeline position:
    LLM (extract POIs + coords) -> [THIS MODULE] -> LLM (write narrative/timing only)

Algorithm:
    1. Capacitated Lloyd's algorithm (alternating optimization):
         a. Assignment step -> solved EXACTLY each iteration via OR-Tools CP-SAT
            as a min-cost balanced assignment problem (this is what actually
            enforces the 3-5 bound; the LLM never gets a chance to violate it).
         b. Update step -> recompute centroids as mean of assigned points.
         c. Repeat until assignment stabilizes (usually 3-6 iterations).
    2. Day ordering -> nearest-neighbor chain over day-centroids, anchored at origin.
    3. Within-day stop ordering -> nearest-neighbor + 2-opt TSP improvement.

Why this fixes the Day1/Day2 bleed:
    The old failure mode was the LLM "borrowing" a geographically distant point
    to satisfy min=3 when a cluster only had 2 natural neighbors. Here, the
    solver picks the borrowed point that minimizes total assignment cost across
    ALL days simultaneously (a global optimum for that iteration), not a local
    guess. It also converges to a self-consistent geographic partition, since
    centroids and assignments are updated jointly.
"""

import math

from ortools.sat.python import cp_model


def haversine(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in km between two (lat, lon) points."""
    lat1, lon1 = map(math.radians, a)
    lat2, lon2 = map(math.radians, b)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def _capacitated_assignment(
    points: list[tuple[float, float]],
    centroids: list[tuple[float, float]],
    min_per_day: int,
    max_per_day: int,
    time_limit_s: float = 5.0,
) -> list[int]:
    """
    Exact min-cost assignment of points -> clusters subject to per-cluster
    size bounds. Solved with CP-SAT (fast + exact at this problem size).
    Returns a list `assignment[i] = cluster_index`.
    """
    n, k = len(points), len(centroids)
    model = cp_model.CpModel()

    x = {(i, j): model.NewBoolVar(f"x_{i}_{j}") for i in range(n) for j in range(k)}

    for i in range(n):
        model.Add(sum(x[i, j] for j in range(k)) == 1)

    for j in range(k):
        model.Add(sum(x[i, j] for i in range(n)) >= min_per_day)
        model.Add(sum(x[i, j] for i in range(n)) <= max_per_day)

    scale = 1000
    cost = {(i, j): int(haversine(points[i], centroids[j]) * scale) for i in range(n) for j in range(k)}
    model.Minimize(sum(cost[i, j] * x[i, j] for i in range(n) for j in range(k)))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_s
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError(
            f"No feasible day assignment exists for n={n} points into k={k} "
            f"days with bounds [{min_per_day},{max_per_day}]. "
            f"Check that min_per_day*k <= n <= max_per_day*k."
        )

    assignment: list[int] = [-1] * n
    for i in range(n):
        for j in range(k):
            if solver.Value(x[i, j]) == 1:
                assignment[i] = j
    return assignment


def capacitated_geo_cluster(
    pois: list[dict],
    num_days: int,
    min_per_day: int = 3,
    max_per_day: int = 5,
    max_iterations: int = 15,
) -> list[list[dict]]:
    """
    Split POIs into `num_days` geographically coherent clusters, each with
    between min_per_day and max_per_day points.

    pois: list of dicts, each MUST have 'lat' and 'lon' keys (any other keys,
          e.g. 'name', pass through untouched).
    Returns: list of length num_days, each element a list of POI dicts.
    """
    n = len(pois)
    if not (min_per_day * num_days <= n <= max_per_day * num_days):
        raise ValueError(
            f"{n} POIs cannot be split into {num_days} days within "
            f"[{min_per_day},{max_per_day}] per day. "
            f"Valid range is [{min_per_day * num_days}, {max_per_day * num_days}] POIs."
        )

    points = [(p["lat"], p["lon"]) for p in pois]

    sorted_idx = sorted(range(n), key=lambda i: (points[i][0] + points[i][1]))
    seed_idx = [sorted_idx[int(i * (n - 1) / max(num_days - 1, 1))] for i in range(num_days)]
    centroids = [points[i] for i in seed_idx]

    assignment: list[int] = []
    for _ in range(max_iterations):
        new_assignment = _capacitated_assignment(points, centroids, min_per_day, max_per_day)
        if new_assignment == assignment:
            break
        assignment = new_assignment
        for j in range(num_days):
            members = [points[i] for i in range(n) if assignment[i] == j]
            if members:
                centroids[j] = (
                    sum(p[0] for p in members) / len(members),
                    sum(p[1] for p in members) / len(members),
                )

    clusters: list[list[dict]] = [[] for _ in range(num_days)]
    for i, j in enumerate(assignment):
        clusters[j].append(pois[i])
    return clusters


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

    clusters = capacitated_geo_cluster(pois, num_days=4, min_per_day=3, max_per_day=5)
    ordered = order_days_and_stops(clusters, origin=(26.7271, 88.3953))

    for d, day in enumerate(ordered, 1):
        names = ", ".join(p["name"] for p in day)
        print(f"Day {d} ({len(day)} stops): {names}")
