"""Tests for day_clustering module - agglomerative geo-clustering solver."""

import pytest

from agentic_tour_planner.pipeline.day_clustering import (
    balanced_geo_cluster,
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


class TestBalancedGeoCluster:
    def test_basic_clustering_no_forced_counts(self):
        pois = [
            {"name": "A", "lat": 0.0, "lon": 0.0},
            {"name": "B", "lat": 0.1, "lon": 0.1},
            {"name": "C", "lat": 0.2, "lon": 0.2},
            {"name": "D", "lat": 10.0, "lon": 10.0},
            {"name": "E", "lat": 10.1, "lon": 10.1},
            {"name": "F", "lat": 10.2, "lon": 10.2},
        ]
        clusters = balanced_geo_cluster(pois, num_days=2, target_range=(3, 5))
        assert len(clusters) == 2
        all_names = {p["name"] for c in clusters for p in c}
        assert all_names == {"A", "B", "C", "D", "E", "F"}
        # Natural 3-and-3 split; counts are not coerced to a bound.
        assert sorted(len(c) for c in clusters) == [3, 3]

    def test_preserves_extra_fields(self):
        pois = [
            {"name": "A", "lat": 0.0, "lon": 0.0, "extra": "data"},
            {"name": "B", "lat": 0.1, "lon": 0.1, "extra": "data2"},
            {"name": "C", "lat": 0.2, "lon": 0.2, "extra": "data3"},
            {"name": "D", "lat": 10.0, "lon": 10.0, "extra": "data4"},
            {"name": "E", "lat": 10.1, "lon": 10.1, "extra": "data5"},
            {"name": "F", "lat": 10.2, "lon": 10.2, "extra": "data6"},
        ]
        clusters = balanced_geo_cluster(pois, num_days=2, target_range=(3, 5))
        all_pois = [p for c in clusters for p in c]
        assert any(p.get("extra") == "data" for p in all_pois)

    def test_too_few_pois_raises(self):
        pois = [
            {"name": "A", "lat": 0.0, "lon": 0.0},
            {"name": "B", "lat": 0.1, "lon": 0.1},
        ]
        with pytest.raises(ValueError, match="need at least one POI per day"):
            balanced_geo_cluster(pois, num_days=3, target_range=(3, 5))

    def test_single_day(self):
        pois = [
            {"name": "A", "lat": 0.0, "lon": 0.0},
            {"name": "B", "lat": 0.1, "lon": 0.1},
            {"name": "C", "lat": 0.2, "lon": 0.2},
        ]
        clusters = balanced_geo_cluster(pois, num_days=1, target_range=(3, 5))
        assert len(clusters) == 1
        assert len(clusters[0]) == 3

    def test_geographic_purity_beats_counts(self):
        """A remote POI stays its own day rather than being dragged into a
        region just to fill a count (the old day-mixing failure mode)."""
        pois = [
            {"name": "City A", "lat": 0.0, "lon": 0.0},
            {"name": "City B", "lat": 0.1, "lon": 0.1},
            {"name": "City C", "lat": 0.2, "lon": 0.2},
            {"name": "Remote", "lat": 10.0, "lon": 10.0},
        ]
        clusters = balanced_geo_cluster(pois, num_days=2, target_range=(3, 5))
        assert [len(c) for c in clusters] == [3, 1]
        remote_day = next(c for c in clusters if "Remote" in {p["name"] for p in c})
        assert len(remote_day) == 1

    def test_soft_cap_respects_user_range(self):
        """A tight blob larger than the cap high-end is split, not overloaded."""
        pois = [{"name": f"City {i}", "lat": 0.0 + i * 0.01, "lon": 0.0} for i in range(7)]
        clusters = balanced_geo_cluster(pois, num_days=2, target_range=(3, 5))
        assert len(clusters) == 2
        assert max(len(c) for c in clusters) <= 5

    def test_sikkim_repro_geographic_purity(self):
        """The user's Sikkim repro (12 POIs / 4 days): every day must be a
        single geographic region - Gangtok city together (incl. Tashi), the
        east-pass excursion separate, the remote north separate, and all West
        monasteries together. No east-west-north-south mixing."""
        pois = [
            {"name": "Enchey Monastery", "lat": 27.3359368, "lon": 88.6191659},
            {"name": "MG Marg", "lat": 27.3253821, "lon": 88.61189},
            {"name": "Hanuman Tok", "lat": 27.3478348, "lon": 88.628696},
            {"name": "Tsomgo Lake (Changu Lake)", "lat": 27.3741667, "lon": 88.7619444},
            {"name": "Nathula Pass", "lat": 27.3865684, "lon": 88.8308731},
            {"name": "Yumthang Valley (Valley of Flowers)", "lat": 27.8267952, "lon": 88.6958087},
            {"name": "Ralang Monastery", "lat": 27.3284964, "lon": 88.3352477},
            {"name": "Pemayangtse Monastery", "lat": 27.3052201, "lon": 88.2515852},
            {"name": "Rabdentse Ruins", "lat": 27.301403, "lon": 88.2566223},
            {"name": "Tashi Viewpoint", "lat": 27.3706406, "lon": 88.616133},
            {"name": "Khecheopalri Lake", "lat": 27.349221, "lon": 88.1882768},
            {"name": "Dubdi Monastery", "lat": 27.3665529, "lon": 88.2299922},
        ]
        clusters = balanced_geo_cluster(pois, num_days=4, target_range=(3, 5))

        def day_of(name: str) -> int:
            for i, c in enumerate(clusters):
                if name in {p["name"] for p in c}:
                    return i
            raise AssertionError(f"{name} not assigned")

        # Gangtok city stays together - Tashi is a Gangtok viewpoint, NOT a
        # west-monastery day.
        gangtok = {"Enchey Monastery", "MG Marg", "Hanuman Tok", "Tashi Viewpoint"}
        gangtok_days = {day_of(n) for n in gangtok}
        assert len(gangtok_days) == 1
        # East-pass excursion together and without the far-north valley.
        assert day_of("Tsomgo Lake (Changu Lake)") == day_of("Nathula Pass")
        assert day_of("Yumthang Valley (Valley of Flowers)") != day_of("Tsomgo Lake (Changu Lake)")
        # West monasteries together, without any Gangtok place.
        west = {"Ralang Monastery", "Pemayangtse Monastery", "Rabdentse Ruins", "Khecheopalri Lake", "Dubdi Monastery"}
        west_days = {day_of(n) for n in west}
        assert len(west_days) == 1
        assert not (gangtok_days & west_days)
        # Every POI lands in exactly one day.
        assigned = [p["name"] for c in clusters for p in c]
        assert sorted(assigned) == sorted(p["name"] for p in pois)

    def test_andaman_islands_separated(self):
        """Andaman: island geography must be preserved - Port Blair sites stay
        together, Havelock beaches together, Neil and Baratang not merged into
        them."""
        pois = [
            {"name": "Cellular Jail", "lat": 11.6740, "lon": 92.7460},
            {"name": "Ross Island", "lat": 11.6730, "lon": 92.7640},
            {"name": "Chidiya Tapu", "lat": 11.4890, "lon": 92.6110},
            {"name": "Radhanagar Beach", "lat": 12.0060, "lon": 92.9770},
            {"name": "Laxmanpur Beach", "lat": 11.9830, "lon": 92.9580},
            {"name": "Bharatpur Beach", "lat": 11.8360, "lon": 93.0390},
            {"name": "Limestone Cave Baratang", "lat": 12.2400, "lon": 92.8030},
            {"name": "Wandoor Beach", "lat": 11.5850, "lon": 92.6130},
        ]
        clusters = balanced_geo_cluster(pois, num_days=4, target_range=(3, 5))

        def day_of(name: str) -> int:
            for i, c in enumerate(clusters):
                if name in {p["name"] for p in c}:
                    return i
            raise AssertionError(f"{name} not assigned")

        assert day_of("Cellular Jail") == day_of("Ross Island")
        assert day_of("Radhanagar Beach") == day_of("Laxmanpur Beach")
        assert day_of("Chidiya Tapu") == day_of("Wandoor Beach")
        assert day_of("Limestone Cave Baratang") not in (
            day_of("Radhanagar Beach"),
            day_of("Chidiya Tapu"),
        )
        assigned = [p["name"] for c in clusters for p in c]
        assert sorted(assigned) == sorted(p["name"] for p in pois)

    def test_kyoto_city_regions(self):
        """Kyoto: east/higashiyama sights grouped apart from northwest sights."""
        pois = [
            {"name": "Kiyomizu-dera", "lat": 34.9949, "lon": 135.7850},
            {"name": "Gion District", "lat": 35.0037, "lon": 135.7788},
            {"name": "Fushimi Inari", "lat": 34.9671, "lon": 135.7727},
            {"name": "Kinkaku-ji", "lat": 35.0394, "lon": 135.7292},
            {"name": "Arashiyama Bamboo Grove", "lat": 35.0172, "lon": 135.6717},
            {"name": "Nijo Castle", "lat": 35.0142, "lon": 135.7481},
            {"name": "Nishiki Market", "lat": 35.0051, "lon": 135.7649},
            {"name": "Philosopher's Path", "lat": 35.0252, "lon": 135.7984},
        ]
        clusters = balanced_geo_cluster(pois, num_days=3, target_range=(3, 5))

        def day_of(name: str) -> int:
            for i, c in enumerate(clusters):
                if name in {p["name"] for p in c}:
                    return i
            raise AssertionError(f"{name} not assigned")

        assert day_of("Kiyomizu-dera") == day_of("Gion District")
        assert day_of("Kinkaku-ji") == day_of("Arashiyama Bamboo Grove")
        assert day_of("Kinkaku-ji") != day_of("Kiyomizu-dera")
        assigned = [p["name"] for c in clusters for p in c]
        assert sorted(assigned) == sorted(p["name"] for p in pois)

    def test_phase_two_merges_sparse_geography(self):
        """With fewer natural regions than days, the closest pairs merge to hit
        exactly num_days (soft cap is not an iron law)."""
        pois = [
            {"name": "A", "lat": 0.0, "lon": 0.0},
            {"name": "B", "lat": 0.1, "lon": 0.1},
            {"name": "C", "lat": 10.0, "lon": 10.0},
        ]
        clusters = balanced_geo_cluster(pois, num_days=2, target_range=(3, 5))
        assert len(clusters) == 2


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
