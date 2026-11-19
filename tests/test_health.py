def test_health_ok(client):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["ai_configured"] is True
    assert "gemini_api_key" not in resp.text.lower()


def test_unknown_route_returns_json_error(client):
    resp = client.get("/api/v1/nope")
    assert resp.status_code == 404
    assert resp.json()["success"] is False


def test_cors_allows_only_configured_origin(client):
    ok = client.options(
        "/api/v1/projects/evaluate",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"},
    )
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3000"
    bad = client.options(
        "/api/v1/projects/evaluate",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in bad.headers
