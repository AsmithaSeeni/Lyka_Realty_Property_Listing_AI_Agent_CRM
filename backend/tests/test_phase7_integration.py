"""Phase 7 — end-to-end integration & regression tests.

Covers the full customer journey (browse → detail → chat focus → save →
return) and the full agent CRM workflow (dashboard → lead → status →
follow-up → recommendations → idempotency → persistence → RBAC) on the
throwaway test database, plus regression tests for the two confirmed
Phase 7 defects:

1. record-space chat focus leaking into the dataset-keyed recommendation
   list (wrong cards persisted + id-space collisions);
2. fictional demo listings presented by the assistant without the honesty
   marker (now rendered in the deterministic context block).

All provider calls are faked or bypassed — no test touches the network.
"""

import itertools

import pytest
from fastapi.testclient import TestClient

ADMIN_EMAIL = "admin@lykarealty.ae"
ADMIN_PASS = "Admin@123"
AGENT_EMAIL = "agent@lykarealty.ae"
AGENT_PASS = "Agent@123"
LEADS_URL = "/api/agent/leads"

_seq = itertools.count(7001)


def _loc() -> str:
    return f"P7 Loc {next(_seq)}"


def _make_record(db, loc, *, approved=True, availability="available",
                 purpose="sale", price=1_500_000, ptype="villa",
                 bedrooms=3, bathrooms=3, demo=False, title=None):
    from app.database import Property

    prop = Property(
        title=title or f"P7 Listing {next(_seq)}",
        description=("FICTIONAL DEMO LISTING — synthetic demo data. "
                     "A quiet test listing." if demo else "A quiet test listing."),
        purpose=purpose, availability=availability, price=price,
        currency="AED", property_type=ptype, location=loc,
        bedrooms=bedrooms, bathrooms=bathrooms, area=2000.0, area_unit="sqft",
        amenities='["pool"]', highlights="sea view",
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


def _register(client, tag):
    email = f"p7.{tag}.{next(_seq)}@example.com"
    password = "Synth-Pass-7!"
    r = client.post("/api/customer/register", json={
        "email": email, "password": password,
        "confirm_password": password, "name": "P7 Synthetic"})
    assert r.status_code == 200, r.text
    return email


def _uniq():
    n = next(_seq)
    return f"+9715{n}", f"p7.lead.{n}@example.com"


def _lead_body(loc, **over):
    phone, email = _uniq()
    body = {
        "name": "P7 Lead", "phone": phone, "email": email,
        "intent": "buy", "property_type": "villa", "location": loc,
        "bedrooms": 3, "bathrooms": 3,
        "budget_min": 1_000_000, "budget_max": 2_000_000,
        "budget_currency": "AED", "budget_period": "one_time",
        "timeline_days": 30, "confirm": True,
    }
    body.update(over)
    return body


class _FakeState:
    def __init__(self):
        self.contact = {}
        self.recommended_properties = []

    def add_message(self, *args, **kwargs):
        pass


class _FakeAgent:
    """Minimal NVIDIA-agent stand-in (no network anywhere)."""

    last_focus = None

    def __init__(self, conversation_id=None):
        self.state = _FakeState()

    def _extract_requirements(self, *a, **k):
        pass

    def _should_collect_lead(self):
        return False

    def get_lead_data(self):
        return {}

    def respond(self, user_message, focus_property=None):
        _FakeAgent.last_focus = focus_property
        return {
            "response": "Hello from the fake agent.",
            "action": "continue",
            "properties": [],
            "detected_language": "en",
            "language_style": "en",
        }


@pytest.fixture()
def fake_agent(app_module, monkeypatch):
    import app.main as main_mod

    _FakeAgent.last_focus = None
    monkeypatch.setattr(main_mod, "AIRealEstateAgent", _FakeAgent)
    return _FakeAgent


# =====================================================================
# DEFECT 1 REGRESSION — record focus must never become a dataset card
# =====================================================================

def test_record_focus_never_enters_recommended_list(db):
    """A 'cheaper ones' refinement with a record-space focus open must return
    only dataset cards and keep the shared list record-free (the refinement
    path runs deterministically, before any LLM call)."""
    from app.ai.agent import AIRealEstateAgent
    from app.services.property_search import record_focus_dict

    rec = _make_record(db, _loc(), price=900_000)
    agent = AIRealEstateAgent()
    # Prior history activates the deterministic refinement path (no LLM).
    agent.state.add_message("assistant", "Welcome! Looking to buy?", "en")
    agent.state.requirements = {"location": "Dubai Marina", "budget": "1000000"}

    focus = record_focus_dict(rec)
    assert focus["source"] == "record"

    result = agent.respond("show me something cheaper", focus_property=focus)
    assert result is not None, "refinement must resolve deterministically"
    cards = result.get("properties", [])
    assert cards, "refinement should return dataset cards"
    for card in cards:
        assert card.get("source") != "record", "record-space dict leaked into cards"
    # The shared recommendation list holds dataset rows only.
    assert all(p.get("source") != "record"
               for p in agent.state.recommended_properties)


def test_dataset_focus_prepend_behavior_preserved(db):
    """The legacy dataset-focus behavior (joining the shared list so it can
    be referenced as 'the first property') is unchanged."""
    from app.ai.agent import AIRealEstateAgent
    from app.services.property_search import get_property_by_id

    dataset_row = get_property_by_id(1)
    assert dataset_row is not None  # dataset present in the test environment
    assert dataset_row.get("source") != "record"

    agent = AIRealEstateAgent()
    agent.state.add_message("assistant", "Welcome!", "en")
    agent.state.requirements = {"location": "Dubai Marina", "budget": "1000000"}
    agent.respond("show me something cheaper", focus_property=dataset_row)
    # The dataset focus is allowed into the visible list (legacy contract).
    assert any(p.get("property_id") == 1 for p in agent.state.recommended_properties)


# =====================================================================
# DEFECT 2 REGRESSION — demo honesty marker in the focus context
# =====================================================================

def test_context_block_marks_demo_focus_as_fictional(db):
    from app.ai.agent import AIRealEstateAgent
    from app.services.property_search import record_focus_dict, get_property_by_id

    demo = _make_record(db, _loc(), demo=True)
    real = _make_record(db, _loc(), demo=False)
    agent = AIRealEstateAgent()

    ctx_demo = agent._context_block(focus_property=record_focus_dict(demo))
    assert "FICTIONAL DEMO" in ctx_demo

    ctx_real = agent._context_block(focus_property=record_focus_dict(real))
    assert "FICTIONAL DEMO" not in ctx_real

    # Dataset focus rows carry no is_demo key — unchanged.
    ctx_ds = agent._context_block(focus_property=get_property_by_id(1))
    assert "FICTIONAL DEMO" not in ctx_ds


def test_record_focus_dict_carries_source_and_demo(db):
    from app.services.property_search import record_focus_dict

    demo = _make_record(db, _loc(), demo=True)
    f = record_focus_dict(demo)
    assert f["source"] == "record"
    assert f["is_demo"] is True
    assert f["property_id"] == demo.id


# =====================================================================
# DEFECT 1 REGRESSION (API level) — chat persistence guard
# =====================================================================

class _CardFakeAgent(_FakeAgent):
    """Returns one dataset card AND one record-marked card, to prove the
    chat persistence layer never writes record-space rows."""

    def respond(self, user_message, focus_property=None):
        return {
            "response": "ok",
            "action": "continue",
            "detected_language": "en",
            "language_style": "en",
            "properties": [
                {"property_id": 1, "price": "100", "property_type": "villa",
                 "location": "Dubai Marina", "no__of__beds": "2",
                 "no_of_baths": 2, "area": "1000", "highlights": ""},
                {"property_id": 987654, "source": "record", "price": 200,
                 "property_type": "studio", "location": "P7 Ghost",
                 "no__of__beds": "1", "no_of_baths": 1, "area": 500,
                 "highlights": ""},
            ],
        }


def test_chat_never_persists_record_marked_cards(app_module, client, monkeypatch):
    from app.database import PropertyRecommendation, SessionLocal
    import app.main as main_mod

    monkeypatch.setattr(main_mod, "AIRealEstateAgent", _CardFakeAgent)
    r = client.post("/api/chat", json={"message": "show me properties"})
    assert r.status_code == 200, r.text
    conv_id = r.json()["conversation_id"]

    db = SessionLocal()
    try:
        ids = [rec.property_id for rec in
               db.query(PropertyRecommendation)
               .filter(PropertyRecommendation.conversation_id == conv_id).all()]
    finally:
        db.close()
    assert 1 in ids                # dataset card persisted (legacy)
    assert 987654 not in ids       # record-marked card never persisted


# =====================================================================
# CUSTOMER JOURNEY — browse → detail → chat focus → save → return
# =====================================================================

def test_customer_journey_full(app_module, client, db, fake_agent):
    from app.database import Lead

    leads_before = db.query(Lead).count()
    loc = _loc()
    rec = _make_record(db, loc, price=1_200_000, demo=True)

    # 1-2. browse + detail (public, no auth)
    listing = client.get("/api/properties", params={"location": loc})
    assert listing.status_code == 200 and listing.json()["total"] == 1
    detail = client.get(f"/api/properties/record/{rec.id}")
    assert detail.status_code == 200
    assert detail.json()["is_demo"] is True

    # 3-4. Ask LykAI with the listing as focus
    chat = client.post("/api/chat", json={
        "message": "Tell me more about this property",
        "property_id": rec.id, "property_source": "record"})
    assert chat.status_code == 200
    conv_id = chat.json()["conversation_id"]
    assert fake_agent.last_focus is not None
    assert fake_agent.last_focus["property_id"] == rec.id

    # 5-6. sign in (account feature) + save
    _register(client, "journey")
    save = client.post("/api/customer/saved",
                       json={"property_id": rec.id, "source": "record"})
    assert save.status_code == 200
    saved = client.get("/api/customer/saved").json()
    assert saved["total"] == 1 and saved["results"][0]["source"] == "record"

    # 7. return: property still loadable, conversation intact, then unsave
    assert client.get(f"/api/properties/record/{rec.id}").status_code == 200
    convs = client.get("/api/conversations").json()
    items = convs if isinstance(convs, list) else convs.get("results", [])
    assert conv_id in [c["id"] for c in items]

    assert client.delete(f"/api/customer/saved/{rec.id}?source=record").status_code == 200
    assert client.get("/api/customer/saved").json()["total"] == 0

    # browsing/chating never created a CRM lead
    db.expire_all()
    assert db.query(Lead).count() == leads_before


def test_customer_isolation_journey(app_module, db, fake_agent):
    from app.database import Lead

    leads_before = db.query(Lead).count()
    loc = _loc()
    rec = _make_record(db, loc)

    a = TestClient(app_module.app)
    _register(a, "isoA")
    a.post("/api/customer/saved", json={"property_id": rec.id, "source": "record"})
    conv = a.post("/api/chat", json={
        "message": "hello", "property_id": rec.id, "property_source": "record"})
    conv_id = conv.json()["conversation_id"]

    b = TestClient(app_module.app)
    _register(b, "isoB")
    assert b.get("/api/customer/saved").json()["total"] == 0
    assert b.get(f"/api/conversations/{conv_id}").status_code == 404
    b_convs = b.get("/api/conversations").json()
    b_ids = [c["id"] for c in (b_convs if isinstance(b_convs, list)
                               else b_convs.get("results", []))]
    assert conv_id not in b_ids

    db.expire_all()
    assert db.query(Lead).count() == leads_before


def test_guest_chat_is_claimed_on_register(app_module, db, fake_agent):
    """Registering on the same browser claims the guest's conversation."""
    loc = _loc()
    rec = _make_record(db, loc)

    c = TestClient(app_module.app)  # fresh guest
    # guests can chat but cannot save (account feature)
    assert c.get("/api/customer/saved").status_code == 401
    conv = c.post("/api/chat", json={
        "message": "hello", "property_id": rec.id, "property_source": "record"})
    conv_id = conv.json()["conversation_id"]

    _register(c, "claimed")
    saved_after = c.get("/api/customer/saved")
    assert saved_after.status_code == 200 and saved_after.json()["total"] == 0
    convs = c.get("/api/conversations").json()
    ids = [x["id"] for x in (convs if isinstance(convs, list)
                             else convs.get("results", []))]
    assert conv_id in ids


# =====================================================================
# AGENT CRM WORKFLOW — full journey with RBAC + idempotency
# =====================================================================

def test_agent_crm_full_workflow(app_module, client, db):
    from app.database import Lead, FollowUp, PropertyRecommendation

    loc = _loc()
    _make_record(db, loc, price=1_500_000, ptype="villa", bedrooms=3)
    _make_record(db, loc, price=1_800_000, ptype="villa", bedrooms=4)

    admin = _login(client, ADMIN_EMAIL, ADMIN_PASS)

    # ---- create lead (explicit confirmation) ----
    first_body = _lead_body(loc)
    r = client.post(LEADS_URL, json=first_body, headers=admin)
    assert r.status_code == 200, r.text
    lead_id = r.json()["lead"]["id"]

    dash = client.get("/api/agent/dashboard", headers=admin).json()
    assert dash["counts"]["total"] >= 1

    # ---- invalid handling ----
    assert client.get(f"{LEADS_URL}/999999", headers=admin).status_code == 404
    assert client.patch(f"{LEADS_URL}/{lead_id}",
                        json={"status": "not-a-status"},
                        headers=admin).status_code == 422
    bad = _lead_body(loc)
    bad["confirm"] = False
    assert client.post(LEADS_URL, json=bad, headers=admin).status_code == 422

    # duplicate phone → 409, never a silent merge (name differs entirely)
    dup = client.post(LEADS_URL, json=dict(
        first_body, name="Completely Different Name"), headers=admin)
    assert dup.status_code == 409
    conflict = dup.json()["detail"]
    assert conflict["code"] == "duplicate_lead"
    assert conflict["matched_by"] == "phone"
    assert conflict.get("lead_id") == lead_id

    # ---- status update ----
    r = client.patch(f"{LEADS_URL}/{lead_id}",
                     json={"status": "contacted"}, headers=admin)
    assert r.status_code == 200
    assert r.json()["lead"]["status"] == "contacted"

    # ---- follow-up create + list ----
    fu = client.post(f"{LEADS_URL}/{lead_id}/follow-ups", headers=admin, json={
        "type": "call", "notes": "P7 integration call",
        "due_at": "2030-01-15T10:00:00Z"})
    assert fu.status_code == 200, fu.text
    fus = client.get(f"{LEADS_URL}/{lead_id}/follow-ups", headers=admin).json()
    assert len(fus["results"]) >= 1

    # ---- recommendations: run twice, no duplicate saved rows ----
    run1 = client.post(f"{LEADS_URL}/{lead_id}/recommendations",
                       json={"limit": 3, "save": True}, headers=admin)
    assert run1.status_code == 200, run1.text
    db.expire_all()
    saved_after_1 = (db.query(PropertyRecommendation)
                     .filter(PropertyRecommendation.lead_id == lead_id).count())
    assert saved_after_1 >= 1

    run2 = client.post(f"{LEADS_URL}/{lead_id}/recommendations",
                       json={"limit": 3, "save": True}, headers=admin)
    assert run2.status_code == 200
    db.expire_all()
    saved_after_2 = (db.query(PropertyRecommendation)
                     .filter(PropertyRecommendation.lead_id == lead_id).count())
    assert saved_after_2 == saved_after_1, "repeat run must not duplicate history"

    # ---- reopen: everything persisted ----
    detail = client.get(f"{LEADS_URL}/{lead_id}", headers=admin).json()
    assert detail["lead"]["status"] == "contacted"
    assert len(detail["property_recommendations"]) >= 1
    assert any(rec["match_score"] is not None
               for rec in detail["property_recommendations"])

    # ---- RBAC: seeded agent sees unassigned leads, not admin-assigned ones ----
    agent = _login(client, AGENT_EMAIL, AGENT_PASS)
    listed = client.get(LEADS_URL, headers=agent).json()
    ids = [x["id"] for x in listed.get("results", [])]
    assert lead_id in ids, "unassigned lead must be in the agent pickup pool"

    r = client.patch(f"{LEADS_URL}/{lead_id}",
                     json={"status": "qualified"}, headers=agent)
    assert r.status_code == 200
    assert r.json()["lead"]["status"] == "qualified"

    # assign to the admin agent -> the seeded agent loses access (404, no leak)
    admin_agent_id = client.get("/api/auth/me", headers=admin).json()["agent"]["id"]
    client.patch(f"{LEADS_URL}/{lead_id}",
                 json={"assigned_agent_id": admin_agent_id}, headers=admin)
    r = client.get(f"{LEADS_URL}/{lead_id}", headers=agent)
    assert r.status_code == 404
    assert "P7 Lead" not in r.text  # no lead details leaked

    # admin retains access
    assert client.get(f"{LEADS_URL}/{lead_id}", headers=admin).status_code == 200

    # unauthenticated → 401 (fresh client: the shared jar still holds the
    # staff session cookie from the logins above — cookie auth is real)
    assert TestClient(app_module.app).get(f"{LEADS_URL}/{lead_id}").status_code == 401

    # ---- DB consistency ----
    assert db.query(FollowUp).filter(FollowUp.lead_id == lead_id).count() >= 1
    db.expire_all()
    assert db.query(Lead).filter(Lead.phone == first_body["phone"]).count() == 1


def test_dashboard_counts_agree_with_db(client, db):
    from app.database import Lead

    loc = _loc()
    admin = _login(client, ADMIN_EMAIL, ADMIN_PASS)
    made = []
    for _ in range(3):
        r = client.post(LEADS_URL, json=_lead_body(loc), headers=admin)
        assert r.status_code == 200, r.text
        made.append(r.json()["lead"]["id"])
    client.patch(f"{LEADS_URL}/{made[1]}", json={"status": "contacted"}, headers=admin)
    client.patch(f"{LEADS_URL}/{made[2]}", json={"status": "qualified"}, headers=admin)

    endpoint = client.get("/api/agent/dashboard", headers=admin).json()

    db.expire_all()
    db_status = {}
    for (status,) in db.query(Lead.status).all():
        db_status[status] = db_status.get(status, 0) + 1

    # Admin scope = all leads; every status bucket must agree exactly.
    for status, count in db_status.items():
        assert endpoint["counts"].get(status, 0) == count, status
    assert endpoint["counts"]["total"] == sum(db_status.values())
    assert endpoint["counts"]["new"] >= 1
    assert endpoint["counts"]["contacted"] >= 1
    assert endpoint["counts"]["qualified"] >= 1


# =====================================================================
# EARLIER-PHASE REGRESSION GUARDS (spot checks)
# =====================================================================

def test_earlier_phase_endpoints_still_work(client, db):
    """Dataset search/detail, health, auth separation — quick regression."""
    assert client.get("/api/health").status_code == 200
    ds = client.get("/api/properties/search",
                    params={"location": "Dubai Marina", "limit": 2})
    assert ds.status_code == 200 and ds.json()["total"] > 0
    assert client.get("/api/properties/1").json()["property_id"] == 1
    # staff routes stay closed to anonymous callers
    assert client.get("/api/agent/leads").status_code == 401
    assert client.get("/api/agent/dashboard").status_code == 401
