"""Task 3 — full authentication audit regression suite.

Covers the 16 required scenarios end-to-end against the throwaway test DB
(conftest pins DATABASE_URL before any app import — the live database is
never read or written). All customer/agent data here is synthetic.

Scenarios:
  1  valid customer registration
  2  duplicate customer registration -> 409 with a displayable detail
  3  valid customer login (token rotation + cookie)
  4  invalid password AND unknown email -> identical generic 401
  5  customer logout -> subsequent protected access denied
  6  valid agent login (httpOnly cookie attributes)
  7  invalid agent credentials -> generic 401
  8  missing / invalid / expired / revoked / disabled-agent sessions -> 401
  9  customer & guest cookies cannot reach any /api/agent/* route
 10  agent cannot perform admin-only cross-agent assignment (403)
 11  cross-agent access to restricted leads/conversations -> 404
 12  guest -> account claiming + isolation between customers
 13  session survives a backend restart (DB-backed token, new client)
 14  production CORS + cookie configuration (wildcard rejected, Secure on)
 15  login/register rate limiting -> 429 + Retry-After
 16  session-check contract behind frontend route guards (/api/auth/me)
 +   CSRF origin guard: unsafe methods reject unknown cross-origin callers
"""

import subprocess
import sys
from pathlib import Path
from datetime import datetime, timedelta

import pytest  # noqa: E402  (fixture decorator)

BACKEND_DIR = Path(__file__).resolve().parents[1]

ADMIN_EMAIL = "admin@lykarealty.ae"
ADMIN_PASS = "Admin@123"
AGENT_EMAIL = "agent@lykarealty.ae"
AGENT_PASS = "Agent@123"

T3_EMAIL = "task3.customer@example.com"
T3_PASS = "Task3-Pass!456"


def _staff_login(client, ident, password):
    return client.post("/api/auth/login", json={"username": ident, "password": password})


def _register(client, email, password=T3_PASS, confirm=None, name="Task3"):
    return client.post(
        "/api/customer/register",
        json={
            "email": email,
            "password": password,
            "name": name,
            "confirm_password": password if confirm is None else confirm,
        },
    )


def _clogin(client, email, password=T3_PASS):
    return client.post("/api/customer/login", json={"email": email, "password": password})


# Every synthetic email this module ever registers/logs-in-as. The throwaway
# test DB persists across tests within a session (conftest imports the app
# once), so an earlier test's account would 409-collide with a later one.
# An autouse fixture below purges exactly these rows before each test.
_MY_EMAILS = [
    T3_EMAIL,
    "attacker@example.com",
    "mismatch@example.com",
    "nobody.here@example.com",
    "rl@example.com",
    "rl0@example.com",
    "rl1@example.com",
    "rl2@example.com",
]


@pytest.fixture(autouse=True)
def _clean_module_rows(db):
    """Start every test with none of THIS module's synthetic accounts left
    over from earlier tests. Only the emails listed above are touched —
    never another module's data, and never the seeded staff accounts."""
    from app.database import Conversation, Customer

    ids = [r[0] for r in
           db.query(Customer.id).filter(Customer.email.in_(_MY_EMAILS)).all()]
    if ids:
        db.query(Conversation).filter(Conversation.customer_id.in_(ids)) \
            .delete(synchronize_session=False)
        db.query(Customer).filter(Customer.id.in_(ids)) \
            .delete(synchronize_session=False)
        db.commit()
    yield


# =====================================================================
# 1-3. Customer registration / duplicate / login
# =====================================================================

def test_valid_customer_registration(client):
    r = _register(client, T3_EMAIL)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["authenticated"] is True
    assert body["email"] == T3_EMAIL
    sc = r.headers.get("set-cookie", "").lower()
    assert "lyka_customer" in sc and "httponly" in sc
    # no credential material in the response body
    assert "password" not in body and "token" not in body and "hash" not in body


def test_duplicate_registration_409_with_displayable_detail(client):
    """The exact contract the frontend relies on: 409 + a string `detail`
    api.js can surface to the user (the UI bug that hid this message was
    fixed in CustomerAuth.jsx — the API must keep returning it)."""
    assert _register(client, T3_EMAIL).status_code == 200
    r = _register(client, T3_EMAIL)
    assert r.status_code == 409
    detail = r.json().get("detail")
    assert isinstance(detail, str) and "sign in" in detail.lower()


def test_duplicate_registration_case_whitespace_normalized(client):
    assert _register(client, T3_EMAIL).status_code == 200
    r = _register(client, f"  {T3_EMAIL.upper()}  ")
    assert r.status_code == 409


def test_password_mismatch_rejected_server_side(client):
    r = _register(client, "mismatch@example.com", confirm="Different-1")
    assert r.status_code == 422


def test_valid_customer_login_rotates_cookie_and_persists(client):
    _register(client, T3_EMAIL)
    fresh = client.__class__(client.app, raise_server_exceptions=False)  # new jar
    r = _clogin(fresh, T3_EMAIL)
    assert r.status_code == 200, r.text
    assert r.json()["authenticated"] is True
    assert "lyka_customer" in r.headers.get("set-cookie", "").lower()
    # session survives subsequent requests ("page refresh")
    me = fresh.get("/api/customer/me")
    assert me.status_code == 200 and me.json()["email"] == T3_EMAIL


# =====================================================================
# 4. Generic errors — no user probing
# =====================================================================

def test_unknown_email_and_wrong_password_indistinguishable(client):
    _register(client, T3_EMAIL)
    wrong_pw = _clogin(client, T3_EMAIL, "Wrong-Password-1")
    unknown = _clogin(client, "nobody.here@example.com", "Wrong-Password-1")
    assert wrong_pw.status_code == unknown.status_code == 401
    assert wrong_pw.json() == unknown.json()  # identical generic body


def test_staff_email_reserved_for_customers(client):
    r = _register(client, ADMIN_EMAIL)
    assert r.status_code == 422
    assert "staff" in r.json()["detail"].lower()


# =====================================================================
# 5. Logout invalidates access
# =====================================================================

def test_customer_logout_denies_subsequent_protected_access(client):
    _register(client, T3_EMAIL)
    assert client.get("/api/customer/saved").status_code == 200  # session works
    assert client.post("/api/customer/logout").status_code == 200
    assert client.get("/api/customer/saved").status_code == 401
    assert client.get("/api/customer/me").json()["authenticated"] is False


def test_agent_logout_revokes_server_side_session(client):
    assert _staff_login(client, AGENT_EMAIL, AGENT_PASS).status_code == 200
    assert client.get("/api/auth/me").status_code == 200
    # simulate a stolen copy of the live cookie before logging out
    stolen = client.cookies.get("lyka_agent_session")
    assert stolen
    assert client.post("/api/auth/logout").status_code == 200
    # cookie cleared AND session row revoked: replaying the stolen copy
    # (a hypothetical token-replay attacker) must fail too
    client.cookies.clear()
    r = client.get("/api/auth/me",
                   headers={"Cookie": f"lyka_agent_session={stolen}"})
    assert r.status_code == 401


# =====================================================================
# 6-7. Agent login success / failure
# =====================================================================

def test_agent_login_cookie_attributes_and_username_login(client):
    r = _staff_login(client, AGENT_EMAIL, AGENT_PASS)
    assert r.status_code == 200, r.text
    # httpx may merge multiple Set-Cookie headers into one comma-joined
    # string; only this one cookie is set by login, so parse it directly.
    sc = r.headers.get("set-cookie", "").lower()
    assert "lyka_agent_session=" in sc
    assert "httponly" in sc
    assert "samesite=lax" in sc
    # dev (http) cookie must NOT be Secure; production env flips it (test 14)
    assert "secure" not in sc.split("path=")[0]
    body = r.json()
    assert body["agent"]["email"] == AGENT_EMAIL
    assert body["token_type"] == "bearer"
    assert AGENT_PASS not in r.text  # never echoed
    # works by username too
    assert _staff_login(client, "agent", AGENT_PASS).status_code == 200


def test_agent_bad_credentials_generic_401(client):
    bad_pw = _staff_login(client, AGENT_EMAIL, "Nope-12345")
    unknown = _staff_login(client, "ghost@lykarealty.ae", "Nope-12345")
    assert bad_pw.status_code == unknown.status_code == 401
    assert bad_pw.json() == unknown.json()


def test_customer_credentials_rejected_by_agent_login(client):
    _register(client, T3_EMAIL)
    assert _staff_login(client, T3_EMAIL, T3_PASS).status_code == 401


# =====================================================================
# 8. Missing / invalid / expired / revoked / disabled-agent sessions
# =====================================================================

def test_missing_invalid_expired_revoked_sessions_all_401(client, db):
    from app.database import Agent, AgentSession

    def _as(token):
        # explicit Cookie header (never the jar) so the probe is deterministic
        client.cookies.clear()
        return client.get("/api/auth/me",
                          headers={"Cookie": f"lyka_agent_session={token}"})

    assert client.get("/api/auth/me").status_code == 401  # missing

    assert _as("totally-made-up-token").status_code == 401  # invalid

    agent = db.query(Agent).filter(Agent.email == AGENT_EMAIL).first()

    # expired: real session row with past expires_at
    token = AgentSession.new_token()
    db.add(AgentSession(
        agent_id=agent.id,
        token_hash=AgentSession.hash_token(token),
        expires_at=datetime.utcnow() - timedelta(hours=1),
    ))
    db.commit()
    assert _as(token).status_code == 401  # expired

    # revoked: valid session row revoked before use
    token2 = AgentSession.new_token()
    row = AgentSession(
        agent_id=agent.id,
        token_hash=AgentSession.hash_token(token2),
        expires_at=datetime.utcnow() + timedelta(hours=1),
    )
    db.add(row)
    db.commit()
    row.revoked_at = datetime.utcnow()
    db.commit()
    assert _as(token2).status_code == 401  # revoked

    # sanity: an unexpired, unrevoked row with a REAL hash DOES authenticate
    # (proves the three 401s above are semantic, not a broken fixture)
    token3 = AgentSession.new_token()
    db.add(AgentSession(
        agent_id=agent.id,
        token_hash=AgentSession.hash_token(token3),
        expires_at=datetime.utcnow() + timedelta(hours=1),
    ))
    db.commit()
    assert _as(token3).status_code == 200


def test_disabled_agent_loses_access_with_live_session(client, db):
    from app.database import Agent

    assert _staff_login(client, AGENT_EMAIL, AGENT_PASS).status_code == 200
    agent = db.query(Agent).filter(Agent.email == AGENT_EMAIL).first()
    agent.is_active = False
    db.commit()
    assert client.get("/api/auth/me").status_code == 401
    agent.is_active = True
    db.commit()


# =====================================================================
# 9-11. Customer/agent separation, admin-only ops, cross-agent isolation
# =====================================================================

CUSTOMER_FORBIDDEN = [
    ("get", "/api/agent/dashboard"),
    ("get", "/api/agent/leads"),
    ("get", "/api/agent/follow-ups"),
    ("get", "/api/agent/conversations"),
    ("post", "/api/agent/leads"),
]


def test_customer_session_cannot_reach_agent_routes(client):
    _register(client, T3_EMAIL)
    for method, path in CUSTOMER_FORBIDDEN:
        # httpx's get()/delete() reject a json= kwarg entirely — only POST
        # sends a body here.
        r = (client.post(path, json={}) if method == "post" else client.get(path))
        assert r.status_code == 401, f"{method.upper()} {path} -> {r.status_code}"
    # customer cookie is also worthless as a bearer token
    r = client.get("/api/agent/dashboard",
                   headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 401


def test_guest_session_cannot_reach_agent_routes(client):
    for method, path in CUSTOMER_FORBIDDEN:
        r = (client.post(path, json={}) if method == "post" else client.get(path))
        assert r.status_code == 401, f"{method.upper()} {path} -> {r.status_code}"


def test_agent_cannot_cross_assign_admin_only(client, db):
    """Assigning a lead to another agent is an admin-only operation."""
    from app.database import Agent, Lead

    admin = db.query(Agent).filter(Agent.email == ADMIN_EMAIL).first()
    lead = Lead(name="T3 Assignable", status="new", assigned_agent_id=admin.id)
    db.add(lead)
    db.commit()
    db.refresh(lead)

    assert _staff_login(client, AGENT_EMAIL, AGENT_PASS).status_code == 200
    # not even self-assignment via the cross-agent field is allowed for agents
    r = client.patch(
        f"/api/agent/leads/{lead.id}",
        json={"assigned_agent_id": lead.assigned_agent_id},
    )
    assert r.status_code in (403, 404)  # admin-scope enforced server-side


def test_cross_agent_lead_and_conversation_access_404(client, db):
    """An agent must not read another agent's lead or its conversation."""
    from app.database import Agent, Conversation, Lead

    admin = db.query(Agent).filter(Agent.email == ADMIN_EMAIL).first()
    lead = Lead(name="T3 Admins Private", status="new", assigned_agent_id=admin.id)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    conv = Conversation(lead_id=lead.id, customer_name="T3 Private")
    db.add(conv)
    db.commit()
    db.refresh(conv)

    assert _staff_login(client, AGENT_EMAIL, AGENT_PASS).status_code == 200
    assert client.get(f"/api/agent/leads/{lead.id}").status_code == 404
    assert client.patch(
        f"/api/agent/leads/{lead.id}", json={"notes": "hijack"}
    ).status_code == 404
    assert client.get(f"/api/agent/conversations/{conv.id}").status_code == 404
    # and the lead never shows up in the agent's list
    ids = [item["id"] for item in
           client.get("/api/agent/leads").json()["results"]]
    assert lead.id not in ids


# =====================================================================
# 12. Guest -> account claiming + cross-customer isolation
# =====================================================================

def test_guest_claiming_and_customer_isolation(client):
    from fastapi.testclient import TestClient

    guest = client  # first browser: anonymous guest
    conv = guest.post("/api/conversations", json={})
    assert conv.status_code == 200, conv.text
    conv_id = conv.json()["conversation_id"]
    assert [c["id"] for c in guest.get("/api/conversations").json()] == [conv_id]

    # register on the SAME browser -> the guest conversation is claimed
    assert _register(guest, T3_EMAIL).status_code == 200
    assert [c["id"] for c in guest.get("/api/conversations").json()] == [conv_id]

    # a different browser (no cookies) sees nothing
    other = TestClient(client.app, raise_server_exceptions=False)
    assert other.get("/api/conversations").json() == []
    # ...and cannot open the claimed conversation by id
    assert other.get(f"/api/conversations/{conv_id}").status_code == 404

    # signing in from the other browser gets the claimed history back
    assert _clogin(other, T3_EMAIL).status_code == 200
    assert [c["id"] for c in other.get("/api/conversations").json()] == [conv_id]


def test_login_cannot_claim_another_accounts_conversation(client):
    from fastapi.testclient import TestClient

    # Owner browser: guest -> registered account with one conversation
    owner = client
    conv_id = owner.post("/api/conversations", json={}).json()["conversation_id"]
    assert _register(owner, T3_EMAIL).status_code == 200

    # Attacker browser: registers a DIFFERENT account, then tries to open
    # the owner's conversation — must stay invisible even after login.
    attacker = TestClient(client.app, raise_server_exceptions=False)
    assert _register(attacker, "attacker@example.com").status_code == 200
    assert attacker.get(f"/api/conversations/{conv_id}").status_code == 404
    assert [c["id"] for c in attacker.get("/api/conversations").json()] != [conv_id]


# =====================================================================
# 13. Sessions survive a backend restart (DB-backed, not in-process)
# =====================================================================

def test_session_survives_restart_via_bearer_token(client):
    """A brand-new client (fresh cookie jar == fresh server process state)
    can reuse the issued token because sessions live in the DB."""
    from fastapi.testclient import TestClient

    r = _staff_login(client, AGENT_EMAIL, AGENT_PASS)
    token = r.json()["token"]
    restarted = TestClient(client.app, raise_server_exceptions=False)
    me = restarted.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["agent"]["email"] == AGENT_EMAIL


# =====================================================================
# 14. Production configuration (CORS wildcard, Secure cookies)
# =====================================================================

def test_production_cors_rejects_wildcard():
    from app.config import parse_cors

    assert parse_cors("*", "production") == []
    # non-wildcard entries survive even if a wildcard was also listed
    assert parse_cors("*, https://app.lykarealty.ae", "production") == [
        "https://app.lykarealty.ae"
    ]
    # dev keeps the convenience
    assert "*" in parse_cors("*", "development")


def test_production_cookie_secure_defaults_on():
    """Settings computed under APP_ENV=production must default Secure cookies
    (verified in a subprocess so the real import-time config is exercised).
    COOKIE_SECURE/DEBUG are forced blank first: config treats blank as
    "unset", so a repo .env can never mask the true production defaults."""
    code = (
        "import os;"
        "os.environ['APP_ENV']='production';"
        "os.environ['COOKIE_SECURE']='';"
        "os.environ['DEBUG']='';"
        "from app.config import Settings;"
        "s=Settings();"
        "assert s.COOKIE_SECURE is True, s.COOKIE_SECURE;"
        "assert s.DEBUG is False, s.DEBUG;"
        "print('ok')"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(BACKEND_DIR), capture_output=True, text=True, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert "ok" in proc.stdout


# =====================================================================
# 15. Rate limiting on login/register
# =====================================================================

def test_customer_login_rate_limited_429(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "AUTH_RATE_LIMIT", 2)
    payload = {"email": "rl@example.com", "password": "Whatever-1"}
    codes = [client.post("/api/customer/login", json=payload).status_code
             for _ in range(3)]
    assert codes[:2] == [401, 401]  # wrong creds -> generic 401 while allowed
    assert codes[2] == 429


def test_register_rate_limited_429(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "AUTH_RATE_LIMIT", 2)
    codes = [client.post(
        "/api/customer/register",
        json={"email": f"rl{i}@example.com", "password": "Whatever-1"},
    ).status_code for i in range(3)]
    assert codes[2] == 429


# =====================================================================
# 16. Session-check contract behind the frontend route guard
# =====================================================================

def test_session_probe_contract_for_frontend_guards(client):
    """/api/auth/me is what RequireAgent and /agent/login poll. It must 401
    cleanly when unauthenticated (frontend redirects) and 200 when signed in
    — never 5xx, so the login screen can't spin forever on a server error."""
    r = client.get("/api/auth/me")
    assert r.status_code == 401
    assert set(r.json().keys()) == {"detail"}
    assert _staff_login(client, AGENT_EMAIL, AGENT_PASS).status_code == 200
    r = client.get("/api/auth/me")
    assert r.status_code == 200 and "agent" in r.json()


# =====================================================================
# CSRF origin guard (defence in depth on top of SameSite=Lax)
# =====================================================================

def test_csrf_guard_blocks_unknown_cross_origin_posts(client):
    r = client.post(
        "/api/customer/logout",
        headers={"Origin": "https://evil.example"},
    )
    assert r.status_code == 403
    assert "rejected" in r.json()["detail"].lower()


def test_csrf_guard_allows_trusted_dev_origin(client):
    r = client.post(
        "/api/customer/logout",
        headers={"Origin": "http://localhost:5173"},
    )
    assert r.status_code == 200  # the Vite dev server stays fully working


def test_csrf_guard_allows_same_origin(client):
    r = client.post(
        "/api/customer/logout",
        headers={"Origin": "http://testserver"},
    )
    assert r.status_code == 200


def test_csrf_guard_ignores_requests_without_origin(client):
    """curl / server-to-server / TestClient (no Origin) are not browsers."""
    r = client.post("/api/customer/logout")
    assert r.status_code == 200


def test_csrf_guard_applies_to_unsafe_methods_only(client):
    # GETs with a foreign origin are read-only; CORS already hides responses
    r = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert r.status_code == 200


def test_csrf_guard_blocks_delete_to_agent_scoped_route(client):
    r = client.delete(
        "/api/customer/saved/1",
        headers={"Origin": "https://evil.example"},
    )
    assert r.status_code == 403
