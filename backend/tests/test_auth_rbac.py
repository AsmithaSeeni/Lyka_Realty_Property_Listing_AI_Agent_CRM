"""Phase 1 — authentication & role-based access keep working.

Uses ONLY synthetic customer data and the throwaway test database
(temp DB from conftest) — never the live database.
"""

import pytest

ADMIN_EMAIL = "admin@lykarealty.ae"
ADMIN_PASS = "Admin@123"
AGENT_EMAIL = "agent@lykarealty.ae"
AGENT_PASS = "Agent@123"

SYNTH_EMAIL = "phase1.synthetic.customer@example.com"
SYNTH_PASS = "SyntheticPw!123"


def _login(client, email, password):
    return client.post(
        "/api/auth/login", json={"username": email, "password": password}
    )


# --------------------------- staff auth ---------------------------

def test_auth_me_requires_session(client):
    assert client.get("/api/auth/me").status_code == 401


def test_staff_login_success_no_password_echo(client):
    r = _login(client, ADMIN_EMAIL, ADMIN_PASS)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["agent"]["email"] == ADMIN_EMAIL
    assert body["token"]  # issued once for API clients
    assert ADMIN_PASS not in r.text  # never echoed back
    # cookie-based session works
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["agent"]["email"] == ADMIN_EMAIL
    # httpOnly session cookie was set
    set_cookie = r.headers.get("set-cookie", "").lower()
    assert "lyka_agent_session" in set_cookie
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie


def test_staff_login_bad_password_generic_401(client):
    r = _login(client, ADMIN_EMAIL, "Totally-Wrong-1")
    assert r.status_code == 401
    assert "detail" in r.json()


# --------------------------- RBAC scoping ---------------------------

@pytest.fixture()
def rbac_setup(db):
    """Two synthetic leads: one assigned to admin, one in the shared pool."""
    from app.database import Agent, Lead

    admin = db.query(Agent).filter(Agent.email == ADMIN_EMAIL).first()
    assert admin is not None and admin.role == "admin"

    assigned = Lead(
        name="P1 Synthetic Assigned", status="new", assigned_agent_id=admin.id
    )
    pool = Lead(name="P1 Synthetic Pool", status="new")
    db.add_all([assigned, pool])
    db.commit()
    db.refresh(assigned)
    db.refresh(pool)
    return {"assigned_id": assigned.id, "pool_id": pool.id}


def test_agent_cannot_read_admin_assigned_lead(client, rbac_setup):
    assert _login(client, AGENT_EMAIL, AGENT_PASS).status_code == 200
    # lead assigned to the ADMIN is invisible to a regular agent
    r = client.get(f"/api/agent/leads/{rbac_setup['assigned_id']}")
    assert r.status_code == 404
    # ...and so is any write attempt
    r2 = client.patch(
        f"/api/agent/leads/{rbac_setup['assigned_id']}",
        json={"status": "contacted"},
    )
    assert r2.status_code == 404


def test_agent_can_see_pool_lead_and_admin_sees_all(client, rbac_setup):
    assert _login(client, AGENT_EMAIL, AGENT_PASS).status_code == 200
    pool = client.get(f"/api/agent/leads/{rbac_setup['pool_id']}")
    assert pool.status_code == 200

    assert _login(client, ADMIN_EMAIL, ADMIN_PASS).status_code == 200  # re-login swaps cookie
    assigned = client.get(f"/api/agent/leads/{rbac_setup['assigned_id']}")
    assert assigned.status_code == 200


def test_invalid_lead_status_rejected(client, rbac_setup):
    assert _login(client, AGENT_EMAIL, AGENT_PASS).status_code == 200
    r = client.patch(
        f"/api/agent/leads/{rbac_setup['pool_id']}", json={"status": "not-a-status"}
    )
    assert r.status_code == 422


def test_customer_cookie_cannot_reach_staff_routes(client, rbac_setup):
    """Customer session must never open /api/agent/*."""
    reg = client.post(
        "/api/customer/register",
        json={
            "email": SYNTH_EMAIL,
            "password": SYNTH_PASS,
            "name": "Phase1 Synthetic",
            "confirm_password": SYNTH_PASS,
        },
    )
    assert reg.status_code == 200, reg.text
    assert SYNTH_PASS not in reg.text

    assert client.get("/api/agent/leads").status_code == 401
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/agent/dashboard").status_code == 401


# --------------------------- customer auth ---------------------------

def test_customer_register_login_me_flow(client):
    email = "phase1.flow.customer@example.com"
    reg = client.post(
        "/api/customer/register",
        json={
            "email": email,
            "password": SYNTH_PASS,
            "name": "Phase1 Synthetic",
            "confirm_password": SYNTH_PASS,
        },
    )
    assert reg.status_code == 200, reg.text

    me = client.get("/api/customer/me")
    assert me.status_code == 200
    assert me.json().get("email") == email

    out = client.post(
        "/api/customer/logout"
    )
    assert out.status_code == 200
    assert client.get("/api/customer/me").json().get("email") in (None, "")

    login = client.post(
        "/api/customer/login", json={"email": email, "password": SYNTH_PASS}
    )
    assert login.status_code == 200
    assert client.get("/api/customer/me").json().get("email") == email


def test_customer_confirm_password_mismatch_422(client):
    r = client.post(
        "/api/customer/register",
        json={
            "email": "phase1.mismatch@example.com",
            "password": SYNTH_PASS,
            "confirm_password": "DifferentPw!999",
        },
    )
    assert r.status_code == 422
    assert "do not match" in r.json()["detail"]


def test_duplicate_customer_register_409(client):
    payload = {
        "email": "phase1.duplicate@example.com",
        "password": SYNTH_PASS,
        "confirm_password": SYNTH_PASS,
    }
    assert client.post("/api/customer/register", json=payload).status_code == 200
    assert client.post("/api/customer/register", json=payload).status_code == 409


def test_staff_email_reserved_for_customers(client):
    r = client.post(
        "/api/customer/register",
        json={
            "email": ADMIN_EMAIL,
            "password": SYNTH_PASS,
            "confirm_password": SYNTH_PASS,
        },
    )
    assert r.status_code == 422
    assert "reserved" in r.json()["detail"].lower()


def test_customer_and_staff_sessions_are_separate(client):
    """Logging into the customer portal must not authenticate staff routes."""
    email = "phase1.separate.customer@example.com"
    assert client.post(
        "/api/customer/register",
        json={
            "email": email,
            "password": SYNTH_PASS,
            "confirm_password": SYNTH_PASS,
        },
    ).status_code == 200
    assert client.get("/api/customer/me").json().get("email") == email
    # customer session is live, but staff routes stay closed
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/agent/dashboard").status_code == 401
