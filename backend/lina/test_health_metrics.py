"""Health + metrics endpoint tests (FastAPI TestClient, no DB needed)."""
import os
import sys

os.environ["LINA_FORESIGHT_TIMEOUT_SECONDS"] = "0.3"
sys.path.insert(0, "/home/server/LiNa_Discovery/backend/lina")

from fastapi.testclient import TestClient  # noqa: E402

import lina_service  # noqa: E402


def test_health_endpoint():
    client = TestClient(lina_service.app)
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["entity"] == "LINA"
    assert "database_connected" in body and body["database_connected"] is False
    assert "voice_providers" in body
    assert "bridge_available" in body
    assert body["status"] == "degraded"  # no DB in test env


def test_lina_health_endpoint():
    client = TestClient(lina_service.app)
    r = client.get("/lina/health")
    assert r.status_code == 200
    body = r.json()
    assert body["entity"] == "LINA"
    assert "uptime_seconds" in body


def test_metrics_disabled_by_default():
    client = TestClient(lina_service.app)
    r = client.get("/metrics")
    assert r.status_code == 404


def test_metrics_enabled_renders_prometheus():
    lina_service.METRICS_ENABLED = True
    try:
        client = TestClient(lina_service.app)
        # Hit /health first so the request counter is non-zero.
        client.get("/health")
        r = client.get("/metrics")
        assert r.status_code == 200
        assert "text/plain" in r.headers["content-type"]
        assert "lina_requests_total" in r.text
        assert "lina_uptime_seconds" in r.text
        assert "lina_bridge_available" in r.text
        assert "# EOF" in r.text
    finally:
        lina_service.METRICS_ENABLED = False


def test_unknown_route_404():
    client = TestClient(lina_service.app)
    assert client.get("/does-not-exist").status_code == 404
