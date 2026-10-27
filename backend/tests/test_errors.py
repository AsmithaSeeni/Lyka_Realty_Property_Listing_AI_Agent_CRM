"""Phase 1 — global error handling must never leak internals.

An unexpected exception returns the standard {"detail": ...} 500 envelope:
no stack traces, no exception text (which could contain data), no file paths.
The traceback is logged server-side only.
"""

import pytest
from starlette.routing import Route


CANARY = "SECRET_CANARY_VALUE_98765"


def _boom():
    raise RuntimeError(f"exploded with {CANARY}")


@pytest.fixture()
def boom_route(app_module):
    route = Route("/api/_p1_boom", _boom, methods=["GET"])
    app_module.app.router.routes.append(route)
    try:
        yield route
    finally:
        app_module.app.router.routes.remove(route)


def test_unhandled_error_returns_safe_json(client, boom_route):
    r = client.get("/api/_p1_boom")
    assert r.status_code == 500
    assert r.headers["content-type"].startswith("application/json")
    assert r.json() == {"detail": "Internal server error"}

    text = r.text
    assert CANARY not in text                 # exception text not exposed
    assert "Traceback" not in text            # no stack trace
    assert "RuntimeError" not in text         # no exception class names
    assert ".py" not in text                  # no source file paths


def test_http_errors_keep_normal_shape(client):
    r = client.get("/api/nonexistent-route-p1")
    assert r.status_code == 404
    assert "detail" in r.json()


def test_validation_errors_keep_normal_shape(client):
    r = client.post("/api/customer/login", json={"email": "not-an-object"})
    assert r.status_code == 422
    assert "detail" in r.json()
