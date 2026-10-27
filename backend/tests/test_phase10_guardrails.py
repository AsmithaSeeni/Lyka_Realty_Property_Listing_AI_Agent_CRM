"""Phase 10 — guardrail & property-honesty regression tests.

Focused, stable assertions on the guardrails Phase 7/9 rely on: no invented
property facts on zero-match searches, demo honesty markers, CRM authorization
boundaries (customer↔agent, agent↔agent), provider-error paths that cannot
bypass auth, and dataset↔record id-space separation.
"""

import itertools

import pytest

ADMIN_EMAIL = "admin@lykarealty.ae"
ADMIN_PASS = "Admin@123"

_seq = itertools.count(10_100)


def _uniq():
    n = next(_seq)
    return f"+9715{n}", f"p10.lead.{n}@example.com"


def _make_record(db, *, approved=True, demo=False):
    from app.database import Property

    prop = Property(
        title=f"P10 Listing {next(_seq)}",
        description=("FICTIONAL DEMO LISTING — synthetic demo data."
                     if demo else "A quiet test listing."),
        purpose="sale", availability="available", price=1_500_000,
        currency="AED", property_type="villa", location=f"P10 Loc {next(_seq)}",
        bedrooms=3, bathrooms=2, area=2000.0, area_unit="sqft",
        amenities="[]", highlights="quiet",
        is_approved=approved, is_demo=demo,
        source="demo_seed" if demo else "manual",
    )
    db.add(prop)
    db.commit()
    db.refresh(prop)
    return prop


def _login(client, email, password):
    r = client.post("/api/auth/login", json={"username": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


# =====================================================================
# Prompt + deterministic guardrails
# =====================================================================

def test_system_prompt_carries_anti_hallucination_guardrails():
    from app.ai.agent import AIRealEstateAgent

    prompt = AIRealEstateAgent.SYSTEM_PROMPT
    assert "NEVER invent or hallucinate property information" in prompt
    assert "Never make up details about properties, locations, or prices" in prompt


def test_zero_match_search_produces_no_cards():
    """Impossible criteria -> the deterministic search returns None (no
    cards), and the show-gate stays closed without anchor+budget."""
    from app.ai.agent import AIRealEstateAgent

    agent = AIRealEstateAgent()
    assert agent._search_with_criteria(
        location="Nowhereville-Zzz-9999", max_price=500000) is None

    agent.state.requirements = {"location": "Dubai Marina"}  # no budget
    assert agent._should_show_properties() is False
    agent.state.requirements = {"budget": "1000000"}          # no anchor
    assert agent._should_show_properties() is False


def test_auto_search_needs_anchor_and_budget():
    from app.ai.agent import AIRealEstateAgent

    agent = AIRealEstateAgent()
    agent.state.add_message("user", "hello", "en")
    assert agent._auto_search_if_needed() == []   # nothing invented, no cards


def test_demo_focus_context_marks_fictional(db):
    from app.ai.agent import AIRealEstateAgent
    from app.services.property_search import record_focus_dict

    demo = _make_record(db, demo=True)
    real = _make_record(db, demo=False)
    agent = AIRealEstateAgent()
    assert "FICTIONAL DEMO" in agent._context_block(
        focus_property=record_focus_dict(demo))
    assert "FICTIONAL DEMO" not in agent._context_block(
        focus_property=record_focus_dict(real))


# =====================================================================
# Authorization boundaries
# =====================================================================

def test_customer_cookie_cannot_reach_agent_crm(app_module, client):
    email = f"p10.cust.{next(_seq)}@example.com"
    r = client.post("/api/customer/register", json={
        "email": email, "password": "Synth-Pass-10!",
        "confirm_password": "Synth-Pass-10!", "name": "P10 Cust"})
    assert r.status_code == 200
    for path in ("/api/agent/leads", "/api/agent/dashboard",
                 "/api/agent/conversations", "/api/agent/follow-ups"):
        assert client.get(path).status_code == 401, path


def test_agent_cannot_reach_another_agents_lead_or_followup(app_module, client, db):
    from app.database import Agent
    from app.services.auth import create_session

    admin = _login(client, ADMIN_EMAIL, ADMIN_PASS)

    # A second, non-admin agent created directly in the DB (its own session).
    n = next(_seq)
    agent2 = Agent(email=f"p10.agent.{n}@example.com", username=f"p10agent{n}",
                   full_name="P10 Agent", password_hash="x", role="agent",
                   is_active=True)
    db.add(agent2)
    db.commit()
    db.refresh(agent2)
    hdr2 = {"Authorization": f"Bearer {create_session(db, agent2)}"}

    # Lead + follow-up owned by the ADMIN agent (restricted from agent2).
    phone, email = _uniq()
    r = client.post("/api/agent/leads", headers=admin, json={
        "name": "P10 Owned", "phone": phone, "email": email,
        "intent": "buy", "property_type": "villa", "location": "P10 Loc",
        "bedrooms": 3, "bathrooms": 2, "budget_min": 1_000_000,
        "budget_max": 2_000_000, "budget_currency": "AED",
        "budget_period": "one_time", "timeline_days": 30, "confirm": True})
    assert r.status_code == 200, r.text
    lead_id = r.json()["lead"]["id"]
    admin_agent_id = client.get("/api/auth/me", headers=admin).json()["agent"]["id"]
    client.patch(f"/api/agent/leads/{lead_id}",
                 json={"assigned_agent_id": admin_agent_id}, headers=admin)

    fu = client.post(f"/api/agent/leads/{lead_id}/follow-ups", headers=admin,
                     json={"type": "call", "notes": "p10",
                           "due_at": "2030-02-01T10:00:00Z"})
    assert fu.status_code == 200, fu.text
    fu_id = fu.json()["follow_up"]["id"]

    # agent2 (different agent, not assigned) sees nothing — 404, no details.
    r = client.get(f"/api/agent/leads/{lead_id}", headers=hdr2)
    assert r.status_code == 404
    assert "P10 Owned" not in r.text
    r = client.patch(f"/api/agent/follow-ups/{fu_id}",
                     json={"is_completed": True}, headers=hdr2)
    assert r.status_code == 404
    assert "p10" not in r.text
    # and it cannot create follow-ups on that lead either
    r = client.post(f"/api/agent/leads/{lead_id}/follow-ups", headers=hdr2,
                    json={"type": "call", "notes": "nope",
                          "due_at": "2030-02-02T10:00:00Z"})
    assert r.status_code == 404


def test_provider_errors_do_not_bypass_auth(app_module, client, monkeypatch):
    """Authorization is checked BEFORE any provider work: anonymous callers
    get 401 even when the provider is unconfigured; authenticated staff get
    the structured 503 — never a leak of provider internals."""
    from app import config as config_mod

    body = {"enquiry": "P10 auth-before-provider probe"}
    # anonymous -> 401 (auth precedes provider entirely)
    assert client.post("/api/agent/leads/extract", json=body).status_code == 401

    # staff + provider unconfigured -> structured 503, no internals
    monkeypatch.setattr(config_mod.settings, "OPENAI_API_KEY", "")
    staff = _login(client, ADMIN_EMAIL, ADMIN_PASS)
    r = client.post("/api/agent/leads/extract", json=body, headers=staff)
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "not_configured"
    assert "sk-" not in r.text


# =====================================================================
# Id-space separation & saved-property eligibility
# =====================================================================

def test_same_numeric_id_resolves_to_distinct_spaces(app_module, client, db):
    rec = _make_record(db)
    n = rec.id
    assert n <= 25_082  # the dataset contains every id in this range

    dataset = client.get(f"/api/properties/{n}")
    record = client.get(f"/api/properties/record/{n}")
    assert dataset.status_code == 200 and record.status_code == 200

    dj, rj = dataset.json(), record.json()
    assert dj["property_id"] == n            # dataset shape (raw JSON columns)
    assert "no__of__beds" in dj              # dataset uses its own field names
    assert rj["id"] == n                     # record shape
    assert "is_demo" in rj and "price_period" in rj  # record metadata present
    assert "is_approved" not in rj           # governance column never leaks
    assert dj.get("title") != rj.get("title")  # genuinely different rows


def test_unapproved_record_cannot_be_saved(app_module, client, db):
    rec = _make_record(db, approved=False)
    email = f"p10.elig.{next(_seq)}@example.com"
    r = client.post("/api/customer/register", json={
        "email": email, "password": "Synth-Pass-10!",
        "confirm_password": "Synth-Pass-10!", "name": "P10 Elig"})
    assert r.status_code == 200
    # detail hidden, bookmark refused, chat focus resolves to nothing
    assert client.get(f"/api/properties/record/{rec.id}").status_code == 404
    r = client.post("/api/customer/saved",
                    json={"property_id": rec.id, "source": "record"})
    assert r.status_code == 404
