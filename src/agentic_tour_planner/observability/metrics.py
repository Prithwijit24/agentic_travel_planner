from __future__ import annotations

from prometheus_client import Counter, Histogram, generate_latest

REQUEST_COUNT = Counter(
    "tour_planner_requests_total",
    "Count of tour planner requests.",
    labelnames=("endpoint", "provider"),
)
REQUEST_LATENCY = Histogram(
    "tour_planner_request_latency_seconds",
    "Latency of tour planner requests.",
    labelnames=("endpoint",),
)


def export_metrics() -> bytes:
    return generate_latest()

