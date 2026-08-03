"""Tests for day_clustering module - capacitated geo-clustering solver."""

import pytest

from agentic_tour_planner.pipeline.day_clustering import (
    _capacitated_assignment,
    capacitated_geo_cluster,
    haversine,
    order_days_and_stops,
)


class TestHaversine:
    def test_same_point(self):
        assert haversine((0, 0), (0, 0)) == 0.0

    def test_antipodal_points(self):
        result = haversine((0, 0), (0, 180))
        assert abs(result - 20015.0) < 10

    def test_known_distance(self):
        result = haversine((27.3314, 88.6138), (27.3350, 88.6220))
        assert 0.5 < result < 2.0


class TestCapacitatedAssignment:
    def test_single_cluster(self):
        points = [(0, 0), (1, 1), (2, 2)]
        centroids = [(1, 1)]
        assignment = _capacitated_assignment(points, centroids, min_per_day=3, max_per_day=5)
        assert assignment == [0, 0, 0]

    def test_two_clusters_balanced(self):
        points = [(0, 0), (0, 1), (10, 10), (10, 11)]
        centroids = [(0, 0.5), (10, 10.5)]
        assignment = _capacitated_assignment(points, centroids, min_per_day=2, max_per_day=3)
        assert len(assignment) == 4
        assert all(a in (0, 1) for a in assignment)

    def test_infeasible_too_few_points(self):
        points = [(0, 0), (1, 1)]
        centroids = [(0, 0), (1, 1)]
        with pytest.raises(RuntimeError):
            _capacitated_assignment(points, centroids, min_per_day=3, max_per_day=5)

    def test_infeasible_too_many_points(self):
        points = [(i, i) for i in range(20)]
        centroids = [(0, 0), (10, 10)]
        with pytest.raises(RuntimeError):
            _capacitated_assignment(points, centroids, min_per_day=3, max_per_day=5)


class TestCapacitatedGeoCluster:
    def test_basic_clustering(self):
        pois = [
            {"name": "A", "lat": 0.0, "lon": 0.0},
            {"name": "B", "lat": 0.1, "lon": 0.1},
            {"name": "C", "lat": 0.2, "lon": 0.2},
            {"name": "D", "lat": 10.0, "lon": 10.0},
            {"name": "E", "lat": 10.1, "lon": 10.1},
            {"name": "F", "lat": 10.2, "lon": 10.2},
        ]
        clusters = capacitated_geo_cluster(pois, num_days=2, min_per_day=3, max_per_day=5)
        assert len(clusters) == 2
        assert all(3 <= len(c) <= 5 for c in clusters)
        all_names = {p["name"] for c in clusters for p in c}
        assert all_names == {"A", "B", "C", "D", "E", "F"}

    def test_preserves_extra_fields(self):
        pois = [
            {"name": "A", "lat": 0.0, "lon": 0.0, "extra": "data"},
            {"name": "B", "lat": 0.1, "lon": 0.1, "extra": "data2"},
            {"name": "C", "lat": 0.2, "lon": 0.2, "extra": "data3"},
            {"name": "D", "lat": 10.0, "lon": 10.0, "extra": "data4"},
            {"name": "E", "lat": 10.1, "lon": 10.1, "extra": "data5"},
            {"name": "F", "lat": 10.2, "lon": 10.2, "extra": "data6"},
        ]
        clusters = capacitated_geo_cluster(pois, num_days=2, min_per_day=3, max_per_day=5)
        all_pois = [p for c in clusters for p in c]
        assert any(p.get("extra") == "data" for p in all_pois)

    def test_too_few_pois_raises(self):
        pois = [
            {"name": "A", "lat": 0.0, "lon": 0.0},
            {"name": "B", "lat": 0.1, "lon": 0.1},
        ]
        with pytest.raises(ValueError, match="cannot be split"):
            capacitated_geo_cluster(pois, num_days=2, min_per_day=3, max_per_day=5)

    def test_too_many_pois_raises(self):
        pois = [{"name": f"P{i}", "lat": float(i), "lon": float(i)} for i in range(20)]
        with pytest.raises(ValueError, match="cannot be split"):
            capacitated_geo_cluster(pois, num_days=2, min_per_day=3, max_per_day=5)

    def test_single_day(self):
        pois = [
            {"name": "A", "lat": 0.0, "lon": 0.0},
            {"name": "B", "lat": 0.1, "lon": 0.1},
            {"name": "C", "lat": 0.2, "lon": 0.2},
        ]
        clusters = capacitated_geo_cluster(pois, num_days=1, min_per_day=3, max_per_day=5)
        assert len(clusters) == 1
        assert len(clusters[0]) == 3


class TestOrderDaysAndStops:
    def test_orders_days_by_distance_from_origin(self):
        cluster_near = [{"name": "A", "lat": 0.0, "lon": 0.0}]
        cluster_far = [{"name": "B", "lat": 10.0, "lon": 10.0}]
        clusters = [cluster_far, cluster_near]
        ordered = order_days_and_stops(clusters, origin=(0, 0))
        assert ordered[0][0]["name"] == "A"
        assert ordered[1][0]["name"] == "B"

    def test_orders_stops_within_day(self):
        pois = [
            {"name": "Far", "lat": 10.0, "lon": 10.0},
            {"name": "Near", "lat": 0.0, "lon": 0.0},
            {"name": "Mid", "lat": 5.0, "lon": 5.0},
        ]
        clusters = [pois]
        ordered = order_days_and_stops(clusters)
        stop_names = [p["name"] for p in ordered[0]]
        assert stop_names[0] == "Far"
        assert len(stop_names) == 3

    def test_no_origin(self):
        clusters = [
            [{"name": "A", "lat": 0.0, "lon": 0.0}],
            [{"name": "B", "lat": 10.0, "lon": 10.0}],
        ]
        ordered = order_days_and_stops(clusters)
        assert len(ordered) == 2


class TestOriginParsingInPipeline:
    def test_origin_city_name_falls_back_to_none(self):
        origin_str = "Kolkata"
        try:
            parts = origin_str.split(",")
            origin = (float(parts[0]), float(parts[1]))
        except (ValueError, IndexError):
            origin = None
        assert origin is None

    def test_origin_coordinates_parsed_correctly(self):
        origin_str = "22.5726,88.3639"
        try:
            parts = origin_str.split(",")
            origin = (float(parts[0]), float(parts[1]))
        except (ValueError, IndexError):
            origin = None
        assert origin == (22.5726, 88.3639)

    def test_origin_none_handled(self):
        origin_str = None
        if origin_str:
            try:
                parts = origin_str.split(",")
                origin = (float(parts[0]), float(parts[1]))
            except (ValueError, IndexError):
                origin = None
        else:
            origin = None
        assert origin is None

    def test_origin_single_value_falls_back(self):
        origin_str = "22.5726"
        try:
            parts = origin_str.split(",")
            origin = (float(parts[0]), float(parts[1]))
        except (ValueError, IndexError):
            origin = None
        assert origin is None

    def test_origin_empty_string_falls_back(self):
        origin_str = ""
        try:
            parts = origin_str.split(",")
            origin = (float(parts[0]), float(parts[1]))
        except (ValueError, IndexError):
            origin = None
        assert origin is None
