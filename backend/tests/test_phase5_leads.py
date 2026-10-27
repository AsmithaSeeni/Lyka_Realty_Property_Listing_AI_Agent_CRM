"""Phase 5 — lead CRM workflow: create / update / list / detail.

All data is synthetic and unique-per-test; every request runs against the
throwaway SQLite test database from conftest — never the live DB.
"""

import itertools
import json

import pytest

ADMIN_EMAIL = "admin@lykarealty.ae"
ADMIN_PASS = "Admin@123"
AGENT_EMAIL = "agent@lykarealty.ae"
AGENT_PASS = "Agent@123"

LEADS_URL = "/api/agent/leads"
_seq = itertools.count(9001)


def _uniq_phone():
    return f"+9715{next(_seq):07d}"


def _uniq_email(tag="a"):
    return f"p5lead{next(_seq)}.{tag}@example.com"


def _uniq_location():
    return f"P5 Loc {next(_seq)}"


def _login(client, email, password):
    r = client.post("/api/auth/login", json={"username": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _hdr(token):
    return {"Authorization": f"Bearer {token}"}


def lead_body(**over):
    body = {
        "name": "P5 Test Lead",
        "phone": _uniq_phone(),
        "email": _uniq_email(),
        "intent": "buy",
        "property_type": "villa",
        "location": _uniq_location(),
        "bedrooms": 3,
        "bathrooms": 4,
        "budget_min": 2_000_000,
        "budget_max": 2_600_000,
        "budget_currency": "AED",
        "budget_period": "one_time",
        "amenities": ["parking", "gym"],
        "preferences": ["private pool", "garden"],
        "timeline": "within 1 month",
        "timeline_days": 30,
        "original_enquiry": "P5 synthetic enquiry — 3BR villa",
        "confirm": True,
    }
    body.update(over)
    return body


def create_lead(client, token, **over):
    r = client.post(LEADS_URL, json=lead_body(**over), headers=_hdr(token))
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture()
def admin_token(client):
    return _login(client, ADMIN_EMAIL, ADMIN_PASS)


@pytest.fixture()
def agent_token(client):
    return _login(client, AGENT_EMAIL, AGENT_PASS)


@pytest.fixture()
def other_agent(db):
    """A second (non-admin) agent for cross-agent isolation tests."""
    from app.database import Agent
    from app.services.auth import hash_password

    n = next(_seq)
    password = f"OtherPw!{n}"
    a = Agent(email=f"p5.other{n}@lykarealty.ae", username=f"p5.other{n}",
              full_name=f"P5 Other {n}",
              password_hash=hash_password(password), role="agent")
    db.add(a)
    db.commit()
    db.refresh(a)
    return {"agent": a, "password": password}


# =========================== CREATE ===========================

def test_create_requires_staff(client):
    assert client.post(LEADS_URL, json=lead_body()).status_code == 401


def test_create_requires_explicit_confirmation(client, agent_token):
    r = client.post(LEADS_URL, json=lead_body(confirm=False), headers=_hdr(agent_token))
    assert r.status_code == 422
    assert "confirmation" in r.json()["detail"].lower()


def test_create_computes_score_server_side(client, agent_token, db):
    from app.services.lead_scoring import classify_priority, score_lead

    body = lead_body()
    out = create_lead(client, agent_token, **body)
    lead = out["lead"]

    expected = score_lead(body)  # deterministic scorer, same input
    assert lead["lead_score"] == expected.total_score
    assert lead["priority"] == expected.priority == classify_priority(expected.total_score)
    assert out["score"]["total_score"] == expected.total_score
    assert [c["criterion"] for c in out["score"]["breakdown"]] == [
        c.criterion for c in expected.breakdown]
    # stored columns (not just the response payload)
    from app.database import Lead
    db.expire_all()
    row = db.query(Lead).filter(Lead.id == lead["id"]).first()
    assert row.lead_score == expected.total_score
    assert row.priority == expected.priority
    assert json.loads(row.score_breakdown)


def test_create_ignores_client_supplied_score(client, agent_token):
    spoofed = lead_body(lead_score=999, priority="critical", score=1)
    out = create_lead(client, agent_token, **spoofed)
    lead = out["lead"]
    assert lead["lead_score"] != 999
    assert lead["priority"] in ("high", "medium", "low")


@pytest.mark.parametrize("bad", [
    {"phone": "not a phone"},
    {"email": "no-at-sign"},
    {"bedrooms": -2},
    {"bedrooms": "two"},
    {"budget_min": -5},
    {"status": "banana"},
    {"intent": "maybe"},
    {"timeline_days": 0},
    {"budget_currency": "AE"},
    {"location": "x" * 200},
])
def test_create_invalid_fields_rejected(client, agent_token, bad):
    r = client.post(LEADS_URL, json=lead_body(**bad), headers=_hdr(agent_token))
    assert r.status_code == 422, f"expected 422 for {bad}: {r.text}"


def test_create_budget_min_greater_than_max_rejected(client, agent_token):
    r = client.post(LEADS_URL, json=lead_body(budget_min=3_000_000, budget_max=1_000),
                    headers=_hdr(agent_token))
    assert r.status_code == 422


# =========================== DUPLICATES ===========================

def test_duplicate_phone_returns_conflict(client, agent_token):
    first = create_lead(client, agent_token)
    dup_phone = first["lead"]["phone"]
    r = client.post(LEADS_URL, json=lead_body(phone=dup_phone,
                                              email=_uniq_email("other")),
                    headers=_hdr(agent_token))
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert detail["code"] == "duplicate_lead"
    assert detail["matched_by"] == "phone"
    assert detail["lead_id"] == first["lead"]["id"]
    assert detail["in_scope"] is True


def test_duplicate_email_returns_conflict(client, agent_token):
    first = create_lead(client, agent_token)
    r = client.post(LEADS_URL, json=lead_body(phone=_uniq_phone(),
                                              email=first["lead"]["email"].upper()),
                    headers=_hdr(agent_token))
    assert r.status_code == 409
    assert r.json()["detail"]["matched_by"] == "email"


def test_duplicate_override_creates_separate_lead_without_overwriting(
        client, agent_token, db):
    from app.database import Lead

    first = create_lead(client, agent_token, name="Original Person")
    r = client.post(LEADS_URL, json=lead_body(
        phone=first["lead"]["phone"], email=first["lead"]["email"],
        name="Original Person", duplicate_override=True,
        location="Completely Other Area"),
        headers=_hdr(agent_token))
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["duplicate"]["lead_id"] == first["lead"]["id"]
    assert out["lead"]["id"] != first["lead"]["id"]

    db.expire_all()
    original = db.query(Lead).filter(Lead.id == first["lead"]["id"]).first()
    # the pre-existing lead's requirements were NOT touched
    assert original.location == first["lead"]["location"]
    assert original.name == "Original Person"


def test_name_only_similarity_never_merges(client, agent_token, db):
    from app.database import Lead

    a = create_lead(client, agent_token, name="Same Name Person")
    before = db.query(Lead).filter(Lead.name == "Same Name Person").count()
    b = create_lead(client, agent_token, name="Same Name Person")  # new phone/email
    assert b["lead"]["id"] != a["lead"]["id"]
    db.expire_all()
    assert db.query(Lead).filter(Lead.name == "Same Name Person").count() == before + 1


# =========================== REFERENCES / TRANSACTION ===========================

def test_create_unknown_customer_reference_rejected(client, agent_token):
    r = client.post(LEADS_URL, json=lead_body(customer_id=999_999),
                    headers=_hdr(agent_token))
    assert r.status_code == 422
    assert "customer" in r.json()["detail"].lower()


def test_create_unknown_conversation_reference_rejected(client, agent_token):
    r = client.post(LEADS_URL, json=lead_body(conversation_id=999_999),
                    headers=_hdr(agent_token))
    assert r.status_code == 404


def test_create_links_conversation_and_customer(client, agent_token, db):
    from app.database import Customer, Conversation, PropertyRecommendation

    customer = Customer(email=_uniq_email("cust"), name="P5 Cust",
                        token_hash=f"p5-cust-token-{next(_seq)}",
                        password_hash=None)
    db.add(customer)
    db.flush()
    conv = Conversation(customer_name="P5 Cust", customer_id=customer.id)
    db.add(conv)
    db.flush()
    db.add(PropertyRecommendation(conversation_id=conv.id, property_id=1,
                                  price="1,000,000 AED", property_type="villa",
                                  location="Nowhere", bedrooms=3, bathrooms=3))
    db.commit()
    out = create_lead(client, agent_token, conversation_id=conv.id,
                      customer_id=customer.id)
    lead_id = out["lead"]["id"]

    db.expire_all()
    conv2 = db.query(Conversation).filter(Conversation.id == conv.id).first()
    assert conv2.lead_id == lead_id
    assert conv2.customer_id == customer.id
    adopted = db.query(PropertyRecommendation).filter(
        PropertyRecommendation.conversation_id == conv.id).all()
    assert all(r.lead_id == lead_id for r in adopted)
    detail = client.get(f"{LEADS_URL}/{lead_id}", headers=_hdr(agent_token)).json()
    assert detail["customer_account"]["id"] == customer.id
    assert detail["conversations"][0]["id"] == conv.id


def test_create_conversation_already_linked_conflict(client, agent_token, db):
    from app.database import Conversation

    first = create_lead(client, agent_token)
    conv = Conversation(customer_name="P5 Linked")
    db.add(conv)
    db.commit()
    # link via PATCH, then a second create against the same conversation
    r = client.patch(f"{LEADS_URL}/{first['lead']['id']}",
                     json={"conversation_id": conv.id}, headers=_hdr(agent_token))
    assert r.status_code == 200, r.text
    r2 = client.post(LEADS_URL, json=lead_body(conversation_id=conv.id),
                     headers=_hdr(agent_token))
    assert r2.status_code == 409
    assert r2.json()["detail"]["code"] == "conversation_linked"


def test_create_transaction_rollback_leaves_no_partial_rows(
        client, agent_token, db, monkeypatch):
    from app.database import Conversation, Lead
    import app.main as main_mod

    conv = Conversation(customer_name="P5 Rollback")
    db.add(conv)
    db.commit()
    conv_id = conv.id
    before = db.query(Lead).count()

    def boom(_lead):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(main_mod, "recompute_lead_score", boom)
    r = client.post(LEADS_URL, json=lead_body(conversation_id=conv_id),
                    headers=_hdr(agent_token))
    assert r.status_code == 500
    assert "synthetic" not in r.text  # no internal detail leakage

    db.expire_all()
    assert db.query(Lead).count() == before          # no partial lead row
    conv2 = db.query(Conversation).filter(Conversation.id == conv_id).first()
    assert conv2.lead_id is None                     # link rolled back too


def test_create_assignment_rules(client, agent_token, admin_token, other_agent):
    me = client.get("/api/auth/me", headers=_hdr(agent_token)).json()["agent"]["id"]
    # agent may assign to self
    out = create_lead(client, agent_token, assigned_agent_id=me)
    assert out["lead"]["assigned_agent_id"] == me
    # agent may NOT assign to another agent
    r = client.post(LEADS_URL, json=lead_body(assigned_agent_id=other_agent["agent"].id),
                    headers=_hdr(agent_token))
    assert r.status_code == 403
    # admin may assign to any active agent
    out = create_lead(client, admin_token, assigned_agent_id=other_agent["agent"].id)
    assert out["lead"]["assigned_agent_id"] == other_agent["agent"].id


# =========================== UPDATE ===========================

def test_patch_partial_update_preserves_unrelated_fields(client, agent_token):
    created = create_lead(client, agent_token)
    lead_id = created["lead"]["id"]
    r = client.patch(f"{LEADS_URL}/{lead_id}",
                     json={"notes": "P5 note only"}, headers=_hdr(agent_token))
    assert r.status_code == 200, r.text
    lead = r.json()["lead"]
    assert lead["notes"] == "P5 note only"
    assert lead["name"] == created["lead"]["name"]
    assert lead["location"] == created["lead"]["location"]
    assert lead["bedrooms"] == created["lead"]["bedrooms"]
    assert lead["budget_min"] == created["lead"]["budget_min"]


def test_patch_recalculates_score_after_requirement_change(client, agent_token):
    from app.services.lead_scoring import score_lead

    # sparse lead → low score
    sparse = create_lead(client, agent_token, intent="unknown", location=None,
                         property_type=None, bedrooms=None, bathrooms=None,
                         budget_min=None, budget_max=None, budget_currency=None,
                         budget_period=None, amenities=[], preferences=[],
                         timeline=None, timeline_days=None, original_enquiry="")
    lead_id = sparse["lead"]["id"]
    old_score = sparse["lead"]["lead_score"]
    assert sparse["lead"]["priority"] in ("high", "medium", "low")

    r = client.patch(f"{LEADS_URL}/{lead_id}", json={
        "buy_rent": "rent", "location": "Downtown Dubai",
        "property_type": "apartment",
        "bedrooms": 2, "bathrooms": 2, "budget_min": 80_000, "budget_max": 110_000,
        "budget_currency": "aed", "budget_period": "yearly",
        "amenities": ["pool"], "preferences": ["high floor"],
        "timeline_days": 21, "timeline": "3 weeks",
    }, headers=_hdr(agent_token))
    assert r.status_code == 200, r.text
    out = r.json()
    new_score = out["lead"]["lead_score"]
    assert new_score > old_score
    assert out["score"]["total_score"] == new_score
    # currency normalised + period round-trip through the budget text
    assert out["lead"]["budget_currency"] == "AED"
    assert out["lead"]["budget_period"] == "yearly"
    assert "per year" in out["lead"]["budget"]
    assert out["lead"]["preferences"] == ["high floor"]


def test_patch_rejects_client_score_fields(client, agent_token):
    created = create_lead(client, agent_token)
    r = client.patch(f"{LEADS_URL}/{created['lead']['id']}",
                     json={"lead_score": 999}, headers=_hdr(agent_token))
    assert r.status_code == 422  # extra="forbid" — no score field exists


def test_patch_invalid_status_and_intent_rejected(client, agent_token):
    created = create_lead(client, agent_token)
    lead_id = created["lead"]["id"]
    assert client.patch(f"{LEADS_URL}/{lead_id}", json={"status": "banana"},
                        headers=_hdr(agent_token)).status_code == 422
    assert client.patch(f"{LEADS_URL}/{lead_id}", json={"buy_rent": "maybe"},
                        headers=_hdr(agent_token)).status_code == 422


def test_patch_status_change_works(client, agent_token):
    created = create_lead(client, agent_token)
    r = client.patch(f"{LEADS_URL}/{created['lead']['id']}",
                     json={"status": "contacted"}, headers=_hdr(agent_token))
    assert r.status_code == 200
    assert r.json()["lead"]["status"] == "contacted"


def test_patch_preferences_roundtrip_and_legacy_text(client, agent_token, db):
    from app.database import Lead

    created = create_lead(client, agent_token)
    lead_id = created["lead"]["id"]
    r = client.patch(f"{LEADS_URL}/{lead_id}",
                     json={"preferences": ["corner unit", "balcony"]},
                     headers=_hdr(agent_token))
    assert r.status_code == 200
    assert r.json()["lead"]["preferences"] == ["corner unit", "balcony"]

    # legacy free-text requirements → preferences are simply absent (never guessed)
    legacy = Lead(name="P5 Legacy Text", requirements="wants something nice")
    db.add(legacy)
    db.commit()
    db.refresh(legacy)
    assert legacy.requirements == "wants something nice"
    r2 = client.patch(f"{LEADS_URL}/{legacy.id}",
                      json={"notes": "touched"}, headers=_hdr(agent_token))
    assert r2.status_code == 200
    assert r2.json()["lead"]["preferences"] == []


def test_patch_out_of_scope_lead_is_404(client, admin_token, other_agent):
    other = other_agent["agent"]
    # lead assigned to the ADMIN → invisible to a random agent
    admin_id = client.get("/api/auth/me", headers=_hdr(admin_token)).json()["agent"]["id"]
    out = create_lead(client, admin_token, assigned_agent_id=admin_id)
    other_token = _login(client, other.email, other_agent["password"])
    lead_id = out["lead"]["id"]
    r = client.patch(f"{LEADS_URL}/{lead_id}", json={"notes": "hijack"},
                     headers=_hdr(other_token))
    assert r.status_code == 404
    assert client.get(f"{LEADS_URL}/{lead_id}",
                      headers=_hdr(other_token)).status_code == 404


def test_patch_unknown_customer_conversation_refs_rejected(client, agent_token):
    created = create_lead(client, agent_token)
    lead_id = created["lead"]["id"]
    r = client.patch(f"{LEADS_URL}/{lead_id}",
                     json={"conversation_id": 999_999},
                     headers=_hdr(agent_token))
    assert r.status_code == 404


def test_patch_conversation_unlink(client, agent_token, db):
    from app.database import Conversation

    conv = Conversation(customer_name="P5 Unlink")
    db.add(conv)
    db.commit()
    created = create_lead(client, agent_token, conversation_id=conv.id)
    lead_id = created["lead"]["id"]
    r = client.patch(f"{LEADS_URL}/{lead_id}", json={"conversation_id": None},
                     headers=_hdr(agent_token))
    assert r.status_code == 200
    db.expire_all()
    conv2 = db.query(Conversation).filter(Conversation.id == conv.id).first()
    assert conv2.lead_id is None


# =========================== LIST / DETAIL ===========================

def test_list_pagination_and_stable_order(client, agent_token):
    loc = _uniq_location()
    ids = [create_lead(client, agent_token, location=loc)["lead"]["id"]
           for _ in range(5)]

    page1 = client.get(LEADS_URL, params={"location": loc, "limit": 2, "offset": 0},
                       headers=_hdr(agent_token)).json()
    page2 = client.get(LEADS_URL, params={"location": loc, "limit": 2, "offset": 2},
                       headers=_hdr(agent_token)).json()
    page3 = client.get(LEADS_URL, params={"location": loc, "limit": 2, "offset": 4},
                       headers=_hdr(agent_token)).json()
    assert page1["total"] == page2["total"] == page3["total"] == 5
    got = [r["id"] for p in (page1, page2, page3) for r in p["results"]]
    assert sorted(got) == sorted(ids)
    assert len(set(got)) == 5  # no duplicates across pages → stable order


def test_list_filters(client, agent_token):
    loc = _uniq_location()
    a = create_lead(client, agent_token, location=loc, intent="buy")
    b = create_lead(client, agent_token, location=loc, intent="rent",
                    status="contacted")
    c = create_lead(client, agent_token, location=loc, intent="unknown",
                    property_type="studio")

    def q(**params):
        params["location"] = loc
        return client.get(LEADS_URL, params=params, headers=_hdr(agent_token)).json()

    assert [r["id"] for r in q(status="new")["results"]]  # a & c default new
    ids_new = {r["id"] for r in q(status="new")["results"]}
    assert a["lead"]["id"] in ids_new and b["lead"]["id"] not in ids_new
    assert [r["id"] for r in q(intent="rent")["results"]] == [b["lead"]["id"]]
    assert [r["id"] for r in q(property_type="studio")["results"]] == [c["lead"]["id"]]
    assert q(priority="unscored")["total"] == 0  # all scored on create
    assert q(follow_up="overdue")["total"] == 0  # none scheduled yet
    assert q(status="closed_won")["total"] == 0


def test_list_search_by_contact_fields(client, agent_token):
    created = create_lead(client, agent_token, name="P5 Searchable Human")
    lead = created["lead"]
    by_name = client.get(LEADS_URL, params={"q": "Searchable Human"},
                         headers=_hdr(agent_token)).json()
    assert lead["id"] in [r["id"] for r in by_name["results"]]
    by_email = client.get(LEADS_URL, params={"q": lead["email"]},
                          headers=_hdr(agent_token)).json()
    assert lead["id"] in [r["id"] for r in by_email["results"]]
    by_phone = client.get(LEADS_URL, params={"q": lead["phone"]},
                          headers=_hdr(agent_token)).json()
    assert lead["id"] in [r["id"] for r in by_phone["results"]]


def test_list_invalid_params_rejected(client, agent_token):
    bad_params = [{"limit": 0}, {"limit": 5000}, {"offset": -1},
                  {"sort": "random"}, {"status": "nope"}, {"priority": "urgent"},
                  {"follow_up": "someday"}, {"intent": "maybe"}]
    for params in bad_params:
        r = client.get(LEADS_URL, params=params, headers=_hdr(agent_token))
        assert r.status_code == 422, f"expected 422 for {params}: {r.text}"


def test_list_empty_result(client, agent_token):
    out = client.get(LEADS_URL, params={"q": "p5-absolutely-nothing-9999"},
                     headers=_hdr(agent_token)).json()
    assert out == {"total": 0, "results": []}


def test_detail_includes_review_fields_and_followups(client, agent_token):
    created = create_lead(client, agent_token)
    lead_id = created["lead"]["id"]
    client.post(f"{LEADS_URL}/{lead_id}/follow-ups",
                json={"type": "call", "due_at": "2030-01-02T10:00:00Z",
                      "notes": "first touch"},
                headers=_hdr(agent_token))
    r = client.get(f"{LEADS_URL}/{lead_id}", headers=_hdr(agent_token))
    assert r.status_code == 200
    detail = r.json()
    lead = detail["lead"]
    assert lead["original_enquiry"] == "P5 synthetic enquiry — 3BR villa"
    assert lead["budget_min"] == 2_000_000 and lead["budget_max"] == 2_600_000
    assert lead["budget_period"] == "one_time"
    assert lead["amenities"] == ["parking", "gym"]
    assert lead["preferences"] == ["private pool", "garden"]
    assert lead["timeline_days"] == 30
    assert isinstance(lead["score_breakdown"], list) and lead["score_breakdown"]
    assert "clarification_questions" in lead
    assert lead["follow_ups"] and lead["follow_ups"][0]["type"] == "call"
    assert lead["next_follow_up"]["id"] == lead["follow_ups"][0]["id"]
    assert isinstance(detail["property_recommendations"], list)


def test_detail_missing_lead_404(client, agent_token):
    assert client.get(f"{LEADS_URL}/999999",
                      headers=_hdr(agent_token)).status_code == 404


def test_agent_cannot_list_other_agents_leads(client, admin_token, other_agent,
                                              db):
    from app.database import Agent
    from app.services.auth import hash_password

    other = other_agent["agent"]
    # admin creates a lead assigned to other_agent → visible to them, but
    # a brand-new stranger agent must never see it
    mine = create_lead(client, admin_token, assigned_agent_id=other.id)
    other_token = _login(client, other.email, other_agent["password"])
    other_ids = {r["id"] for r in client.get(
        LEADS_URL, params={"limit": 500}, headers=_hdr(other_token))
        .json()["results"]}
    assert mine["lead"]["id"] in other_ids

    n = next(_seq)
    stranger = Agent(email=f"p5.stranger{n}@lykarealty.ae",
                     username=f"p5.stranger{n}", full_name=f"P5 S {n}",
                     password_hash=hash_password(f"StrPw!{n}"), role="agent")
    db.add(stranger)
    db.commit()
    str_token = _login(client, stranger.email, f"StrPw!{n}")
    str_ids = {r["id"] for r in client.get(
        LEADS_URL, params={"limit": 500}, headers=_hdr(str_token))
        .json()["results"]}
    assert mine["lead"]["id"] not in str_ids
