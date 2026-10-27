"""Health endpoint contract (production reliability audit).

/api/health stays CHEAP (no AI provider calls, no dataset re-parse after the
one-time per-instance load) and always answers HTTP 200 with:
  status            "healthy" (db ok) | "degraded" (db unreachable)
  message           unchanged legacy field
  checks.application "ok"
  checks.database    "ok" | "error"
  checks.property_data.dataset_rows / .db_listings  (ints, >= 0)
  checks.ai_config   provider configuration PRESENCE only (no secrets)
"""


def test_health_reports_dependency_checks(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()

    # Legacy contract preserved (older probes/smoke scripts rely on it).
    assert body["status"] == "healthy"
    assert "LykAI" in body["message"]

    checks = body["checks"]
    assert checks["application"] == "ok"
    assert checks["database"] == "ok"
    assert isinstance(checks["property_data"]["dataset_rows"], int)
    assert checks["property_data"]["dataset_rows"] >= 0
    assert isinstance(checks["property_data"]["db_listings"], int)
    assert checks["property_data"]["db_listings"] >= 0
    assert isinstance(checks["ai_config"]["nvidia_configured"], bool)


def test_health_never_leaks_secrets(client, monkeypatch):
    """Config presence is reported; credential VALUES never are."""
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-SECRETVALUE123456")
    monkeypatch.setenv("STT_API_KEY", "sk-SECRETVALUE123456")
    monkeypatch.setenv("TURSO_AUTH_TOKEN", "tok-SECRETVALUE123456")

    text = client.get("/api/health").text
    assert "nvapi-" not in text
    assert "SECRETVALUE" not in text
    assert "Bearer" not in text
