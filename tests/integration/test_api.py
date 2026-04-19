from fastapi.testclient import TestClient

from agentic_tour_planner.api.main import app


def test_health_endpoint():
    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_metrics_endpoint_is_available():
    client = TestClient(app)
    response = client.get("/metrics")

    assert response.status_code == 200
    assert "tour_planner_requests_total" in response.text
