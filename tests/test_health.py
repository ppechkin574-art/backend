def test_health_endpoint_returns_healthy(http):
    resp = http.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "healthy"
    assert "timestamp" in body
