"""Phase 5 — recommendation integration (Phase 4 matching + persistence).

Verifies: only approved+available properties are matched; history rows are
saved through the explicit `save_recommendations()`; repeat requests never
duplicate rows; matching failures roll back cleanly without corrupting the
lead. All data is synthetic, in the throwaway test DB.
"""

import itertools
import json

import pytest

ADMIN_EMAIL = "admin@lykarealty.ae"
ADMIN_PASS = "Admin@123"
AGENT_EMAIL = "agent@lykarealty.ae"
AGENT_PASS = "Agent@123"

LEADS_URL = "/api/agent/leads"
_seq = itertools.count(13001)


def _uniq_phone():
    return f"+9717{next(_seq):07d}"


def _uniq_email():
    return f"p5rec{next(_seq)}@example.com"


def _login(client, email, password):
    r = client.post("/api/auth/login", json={"username": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _hdr(token):
    return {"Authorization": f"Bearer {token}"}


def _make_property(db, loc, *, approved=True, availability="available",
                   price=1_500_000):
    from app.database import Property

    n = next(_seq)
    prop = Property(
        title=f"P5 Rec Villa {n}", description="", purpose="sale",
        availability=availability, price=price, currency="AED",
        property_type="villa", location=loc, bedrooms=4, bathrooms=4,
        area=3000, area_unit="sqft", amenities='["pool"]',
        highlights="private pool garden quiet street",
        is_approved=approved, is_demo=False, source="manual")
    db.add(prop)
    db.commit()
    db.refresh(prop)
    return prop


def _make_lead(client, token, loc, **over):
    body = {
        "name": "P5 Rec Lead", "phone": _uniq_phone(), "email": _uniq_email(),
        "intent": "buy", "property_type": "villa", "location": loc,
        "bedrooms": 3, "bathrooms": 3,
        "budget_min": 1_200_000, "budget_max": 1_800_000,
        "budget_currency": "AED", "budget_period": "one_time",
        "timeline_days": 30, "confirm": True,
    }
    body.update(over)
    r = client.post(LEADS_URL, json=body, headers=_hdr(token))
    assert r.status_code == 200, r.text
    return r.json()["lead"]["id"]


def _run(client, token, lead_id, **body):
    return client.post(f"{LEADS_URL}/{lead_id}/recommendations", json=body,
                       headers=_hdr(token))


@pytest.fixture()
def admin_token(client):
    return _login(client, ADMIN_EMAIL, ADMIN_PASS)


@pytest.fixture()
def agent_token(client):
    return _login(client, AGENT_EMAIL, AGENT_PASS)


# =========================== PERSISTENCE ===========================

def test_recommendations_persist_history_rows(client, agent_token, db):
    from app.database import PropertyRecommendation

    loc = f"P5 Rec Loc {next(_seq)}"
    prop = _make_property(db, loc)
    lead_id = _make_lead(client, agent_token, loc)

    r = _run(client, agent_token, lead_id)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["saved_count"] >= 1
    assert any(m["property_id"] == prop.id for m in out["results"])
    # response carries the recomputed score
    assert out["score"]["total_score"] is not None
    assert {c["criterion"] for c in out["score"]["breakdown"]}

    rows = db.query(PropertyRecommendation).filter(
        PropertyRecommendation.lead_id == lead_id).all()
    assert rows and all(row.property_record_id is not None for row in rows)
    hit = [row for row in rows if row.property_record_id == prop.id][0]
    assert hit.match_score is not None
    assert isinstance(json.loads(hit.match_reasons), list)
    assert isinstance(json.loads(hit.match_mismatches), list)
    assert hit.property_id is None  # never a dataset id


def test_repeat_request_does_not_duplicate(client, agent_token, db):
    from app.database import PropertyRecommendation

    loc = f"P5 Rec Loc {next(_seq)}"
    _make_property(db, loc)
    lead_id = _make_lead(client, agent_token, loc)

    first = _run(client, agent_token, lead_id).json()
    assert first["saved_count"] >= 1
    count_after_first = db.query(PropertyRecommendation).filter(
        PropertyRecommendation.lead_id == lead_id).count()

    again = _run(client, agent_token, lead_id).json()
    assert again["saved_count"] == 0
    assert again["results"]  # history is still shown...
    assert all(m["previously_saved"] for m in again["results"])  # ...flagged
    db.expire_all()
    assert db.query(PropertyRecommendation).filter(
        PropertyRecommendation.lead_id == lead_id).count() == count_after_first


def test_only_approved_and_available_properties_matched(client, agent_token, db):
    loc = f"P5 Rec Loc {next(_seq)}"
    good = _make_property(db, loc, approved=True)
    unapproved = _make_property(db, loc, approved=False)          # twin
    sold = _make_property(db, loc, approved=True,
                          availability="sold")                    # twin
    lead_id = _make_lead(client, agent_token, loc)

    out = _run(client, agent_token, lead_id).json()
    matched = {m["property_id"] for m in out["results"]}
    assert good.id in matched
    assert unapproved.id not in matched    # hard-ruled out
    assert sold.id not in matched          # hard-ruled out


def test_dry_run_saves_nothing_but_refreshes_score(client, agent_token, db):
    from app.database import PropertyRecommendation, Lead

    loc = f"P5 Rec Loc {next(_seq)}"
    _make_property(db, loc)
    lead_id = _make_lead(client, agent_token, loc)

    out = _run(client, agent_token, lead_id, save=False).json()
    assert out["saved_count"] == 0
    assert out["results"]
    assert db.query(PropertyRecommendation).filter(
        PropertyRecommendation.lead_id == lead_id).count() == 0
    # the deterministic score refresh is still persisted
    db.expire_all()
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    assert lead.lead_score is not None


def test_no_eligible_properties_returns_empty_with_explanation(
        client, agent_token, db):
    from app.database import PropertyRecommendation

    loc = f"P5 Nowhere {next(_seq)}"
    # a property type no listing has → type is a HARD rule → nothing eligible
    lead_id = _make_lead(client, agent_token, loc,
                         property_type=f"p5 type {next(_seq)}")
    out = _run(client, agent_token, lead_id).json()
    assert out["results"] == []
    assert out["saved_count"] == 0
    assert out["explanation"]  # never a silent empty list
    assert db.query(PropertyRecommendation).filter(
        PropertyRecommendation.lead_id == lead_id).count() == 0


# =========================== AUTH / FAILURE HANDLING ===========================

def test_recommendations_require_staff_and_scope(client, app_module,
                                                 admin_token, agent_token, db):
    from fastapi.testclient import TestClient

    loc = f"P5 Rec Loc {next(_seq)}"
    _make_property(db, loc)
    admin_id = client.get("/api/auth/me",
                          headers=_hdr(admin_token)).json()["agent"]["id"]
    lead_id = _make_lead(client, admin_token, loc, assigned_agent_id=admin_id)

    # truly anonymous (fresh client — no session cookie at all)
    anon = TestClient(app_module.app, raise_server_exceptions=False)
    assert anon.post(f"{LEADS_URL}/{lead_id}/recommendations",
                     json={}).status_code == 401
    # logged-in agent but out of scope → 404, existence never leaked
    r = client.post(f"{LEADS_URL}/{lead_id}/recommendations", json={},
                    headers=_hdr(agent_token))
    assert r.status_code == 404
    assert _run(client, admin_token, lead_id).status_code == 200  # owner works


def test_unknown_lead_404(client, agent_token):
    assert _run(client, agent_token, 999_999).status_code == 404


def test_matching_failure_rolls_back_score_refresh(client, agent_token, db,
                                                   monkeypatch):
    import app.main as main_mod
    from app.database import Lead

    loc = f"P5 Rec Loc {next(_seq)}"
    _make_property(db, loc)
    lead_id = _make_lead(client, agent_token, loc)

    # sentinel score so a leaked (un-rolled-back) refresh is detectable
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    lead.lead_score = 42.0
    lead.priority = "low"
    db.commit()

    def boom(_db, _extraction, limit=3):
        raise ValueError("no eligible properties (synthetic)")

    monkeypatch.setattr(main_mod, "match_properties", boom)
    r = _run(client, agent_token, lead_id)
    assert r.status_code == 422
    assert "synthetic" in r.json()["detail"]

    db.expire_all()
    lead2 = db.query(Lead).filter(Lead.id == lead_id).first()
    assert lead2.lead_score == 42.0   # score refresh rolled back too
    assert lead2.priority == "low"


def test_persistence_failure_leaves_no_rows_or_score_leak(
        client, agent_token, db, monkeypatch):
    import app.main as main_mod
    from app.database import Lead, PropertyRecommendation

    loc = f"P5 Rec Loc {next(_seq)}"
    _make_property(db, loc)
    lead_id = _make_lead(client, agent_token, loc)
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    lead.lead_score = 42.0
    lead.priority = "low"
    db.commit()
    rows_before = db.query(PropertyRecommendation).filter(
        PropertyRecommendation.lead_id == lead_id).count()

    def boom(_db, _result, *, lead_id=None, conversation_id=None):
        raise RuntimeError("synthetic disk failure")

    monkeypatch.setattr(main_mod, "save_recommendations", boom)
    r = _run(client, agent_token, lead_id)
    assert r.status_code == 500
    assert "synthetic" not in r.text  # internals never leak

    db.expire_all()
    assert db.query(PropertyRecommendation).filter(
        PropertyRecommendation.lead_id == lead_id).count() == rows_before
    lead2 = db.query(Lead).filter(Lead.id == lead_id).first()
    assert lead2.lead_score == 42.0


def test_detail_lists_saved_recommendations(client, agent_token, db):
    loc = f"P5 Rec Loc {next(_seq)}"
    prop = _make_property(db, loc)
    lead_id = _make_lead(client, agent_token, loc)
    _run(client, agent_token, lead_id)

    detail = client.get(f"{LEADS_URL}/{lead_id}",
                        headers=_hdr(agent_token)).json()
    recs = detail["property_recommendations"]
    hit = [r for r in recs if r["property_record_id"] == prop.id]
    assert hit and hit[0]["match_score"] is not None
    assert isinstance(hit[0]["match_reasons"], list)
    assert hit[0]["lead_id"] == lead_id
