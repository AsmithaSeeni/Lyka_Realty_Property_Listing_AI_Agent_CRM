"""Customer signup -> login regression tests (bug-fix follow-up).

Context: a report claimed a newly registered customer could not log back in
("Invalid user or password"). A full investigation (TestClient repro against a
copy of the live database, real-HTTP repro against an isolated uvicorn instance,
and read-only probes of the running dev server) found the register->login flow
in the CURRENT code to be correct at every layer, and
`test_auth_rbac.py::test_customer_register_login_me_flow` already pins the
basic same-session round-trip.

This module pins the REMAINING contract surfaces that the investigation showed
were not covered, so the flow cannot regress silently:
  - login from a fresh session (forces token rotation + Set-Cookie),
  - session persistence across subsequent requests ("page refresh"),
  - email case/whitespace normalization consistency,
  - generic 401 for wrong password AND unknown email (no user probing),
  - duplicate registration leaves the original account untouched,
  - customer credentials rejected by the AGENT login endpoint,
  - customer session cannot reach agent CRM routes,
  - register/login responses never leak password hashes, tokens or plaintext.

No production code was changed for this report: the current implementation
already satisfies every assertion below.
"""

import pytest
from fastapi.testclient import TestClient

ADMIN_EMAIL = "admin@lykarealty.ae"
PASSWORD = "Synth-Pass-10!"
GENERIC_401 = "Invalid email or password"


def _register(client, email, password=PASSWORD, name="Flow Tester", confirm=None):
    return client.post(
        "/api/customer/register",
        json={
            "email": email,
            "password": password,
            "name": name,
            "confirm_password": confirm if confirm is not None else password,
        },
    )


def _login(client, email, password=PASSWORD):
    return client.post("/api/customer/login", json={"email": email, "password": password})


# ---------------------------------------------------------------- full round-trip

def test_fresh_session_login_after_register(app_module, client):
    """The core reported scenario: sign up, then sign in from a clean session
    (no cookie carried over — forces token rotation and a fresh Set-Cookie)."""
    email = "flow.fresh.session@example.com"

    reg = _register(client, email)
    assert reg.status_code == 200, reg.text
    assert reg.json()["authenticated"] is True

    # A brand-new browser/session: no cookies at all.
    fresh = TestClient(app_module.app)
    login = _login(fresh, email)
    assert login.status_code == 200, login.text
    assert login.json()["authenticated"] is True
    # login must establish the session cookie the frontend relies on
    assert "lyka_customer" in login.headers.get("set-cookie", "")

    # The authenticated customer can reach protected customer endpoints.
    me = fresh.get("/api/customer/me")
    assert me.status_code == 200
    assert me.json() == {"authenticated": True, "email": email, "name": "Flow Tester"}
    saved = fresh.get("/api/customer/saved")
    assert saved.status_code == 200
    assert saved.json()["total"] == 0


def test_session_survives_subsequent_requests(app_module, client):
    """A signed-in customer stays signed in across later requests (page
    refresh does not silently log them out)."""
    email = "flow.refresh.session@example.com"
    assert _register(client, email).status_code == 200

    fresh = TestClient(app_module.app)
    assert _login(fresh, email).status_code == 200
    for _ in range(3):  # simulate revisits/refreshes with the same cookie jar
        me = fresh.get("/api/customer/me")
        assert me.status_code == 200
        assert me.json()["authenticated"] is True
        assert me.json()["email"] == email


# ---------------------------------------------------------------- normalization

def test_email_case_and_whitespace_consistent_between_signup_and_login(app_module, client):
    """Register with mixed case; log in with different case + surrounding
    whitespace — both normalize identically server-side."""
    email = "flow.Mixed.Case@Example.COM"
    assert _register(client, email).status_code == 200
    assert client.get("/api/customer/me").json()["email"] == "flow.mixed.case@example.com"

    fresh = TestClient(app_module.app)
    login = _login(fresh, "  FLOW.mixed.case@example.com  ")
    assert login.status_code == 200, login.text
    assert fresh.get("/api/customer/me").json()["email"] == "flow.mixed.case@example.com"


# ---------------------------------------------------------------- rejections

def test_wrong_password_rejected_generically_without_leaks(app_module, client):
    email = "flow.wrong.password@example.com"
    assert _register(client, email).status_code == 200

    fresh = TestClient(app_module.app)
    bad = _login(fresh, email, password="Totally-Wrong-Pw-1!")
    assert bad.status_code == 401
    assert bad.json()["detail"] == GENERIC_401
    # nothing sensitive in the body: no plaintext, no hash material
    assert "Totally-Wrong-Pw-1!" not in bad.text
    assert "$2b$" not in bad.text
    # and no session was established
    assert fresh.get("/api/customer/me").json()["authenticated"] is False


def test_unknown_email_rejected_with_identical_message(app_module, client):
    """No user enumeration: unknown email and wrong password are
    indistinguishable."""
    fresh = TestClient(app_module.app)
    unknown = _login(fresh, "flow.no.such.user@example.com")
    assert unknown.status_code == 401
    assert unknown.json()["detail"] == GENERIC_401


def test_duplicate_registration_leaves_original_account_intact(app_module, client):
    """A duplicate signup (409) must not overwrite or corrupt the original
    account — the ORIGINAL password still works afterwards."""
    email = "flow.duplicate@example.com"
    assert _register(client, email).status_code == 200

    dup = _register(client, email, password="Attacker-Pw-9!", name="Someone Else")
    assert dup.status_code == 409

    fresh = TestClient(app_module.app)
    # original credentials still work; the duplicate's password never took over
    assert _login(fresh, email).status_code == 200
    assert fresh.get("/api/customer/me").json()["name"] == "Flow Tester"
    other = TestClient(app_module.app)
    assert _login(other, email, password="Attacker-Pw-9!").status_code == 401


# ---------------------------------------------------------------- auth-system separation

def test_customer_credentials_rejected_by_agent_login(app_module, client):
    """Customer accounts must never authenticate through the staff endpoint
    (the separate agent auth system stays separate)."""
    email = "flow.not.staff@example.com"
    assert _register(client, email).status_code == 200

    fresh = TestClient(app_module.app)
    r = fresh.post("/api/auth/login", json={"username": email, "password": PASSWORD})
    assert r.status_code == 401
    assert "$2b$" not in r.text and PASSWORD not in r.text
    assert fresh.get("/api/auth/me").status_code == 401
    # and the customer cookie opens no agent CRM surface
    for path in ("/api/agent/leads", "/api/agent/dashboard",
                 "/api/agent/conversations", "/api/agent/follow-ups"):
        assert fresh.get(path).status_code == 401, path


def test_customer_email_reserved_at_staff_login_is_not_confused_with_customer_login(
    app_module, client,
):
    """A staff email cannot register as a customer (reserved), and the agent
    login still governs staff access — the two stores never cross."""
    r = _register(client, ADMIN_EMAIL)
    assert r.status_code == 422
    assert "reserved" in r.json()["detail"].lower()


# ---------------------------------------------------------------- response hygiene

@pytest.mark.parametrize("step", ["register", "login"])
def test_auth_responses_never_leak_hashes_or_tokens(app_module, client, step):
    email = f"flow.hygiene.{step}@example.com"
    fresh = TestClient(app_module.app)
    if step == "login":
        assert _register(client, email).status_code == 200
        r = _login(fresh, email)
    else:
        r = _register(fresh, email)
        assert r.status_code == 200, r.text
    body = r.text
    # bcrypt material and the raw session token must never appear in a body
    assert "$2b$" not in body
    assert PASSWORD not in body
    token = fresh.cookies.get("lyka_customer")
    if step == "login" and token:
        assert token not in body
    # the only credential carrier is the httpOnly cookie
    if r.status_code == 200:
        set_cookie = r.headers.get("set-cookie", "")
        assert "lyka_customer=" in set_cookie
        assert "HttpOnly" in set_cookie
