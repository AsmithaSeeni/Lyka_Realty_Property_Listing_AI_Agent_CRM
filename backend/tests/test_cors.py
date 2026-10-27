"""Phase 1 — CORS follows the configured origins (safe local defaults)."""


def test_allowed_origin_is_echoed_with_credentials(client):
    r = client.get(
        "/api/health",
        headers={"Origin": "http://localhost:5173"},
    )
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert r.headers.get("access-control-allow-credentials") == "true"


def test_disallowed_origin_gets_no_cors_header(client):
    r = client.get(
        "/api/health",
        headers={"Origin": "https://evil.example"},
    )
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") is None


def test_configured_origins_used_verbatim(app_module):
    """The middleware was built from settings.CORS_ORIGINS (local defaults)."""
    from app.config import settings

    for origin in settings.CORS_ORIGINS:
        assert origin.startswith("http://") and origin != "*"
    # defaults expected under the test env (CORS_ORIGINS empty)
    assert "http://localhost:5173" in settings.CORS_ORIGINS
