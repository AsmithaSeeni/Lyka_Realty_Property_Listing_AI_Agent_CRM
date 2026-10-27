"""Phase 6 — public property browsing, detail pages, and enquiry wiring.

Covers, on the throwaway test database only (never the live DB):
- the new public listing endpoint (`GET /api/properties`): eligibility,
  filters, deterministic pagination, validation errors, demo disclaimers;
- the new public detail endpoint (`GET /api/properties/record/{id}`):
  not-found semantics for unknown/unapproved/unavailable rows, honest
  price periods, no internal fields;
- the legacy dataset endpoints stay byte-for-byte compatible;
- saved properties across both id spaces (dataset default, record encoding);
- chat focus wiring for both spaces, with a faked agent (no network), and
  confirmation that viewing/enquiring creates NO CRM lead.
"""

import itertools

import pytest

from fastapi.testclient import TestClient

ADMIN_EMAIL = "admin@lykarealty.ae"
ADMIN_PASS = "Admin@123"

_seq = itertools.count(1)


def _loc() -> str:
    """Unique location per test — isolates every filtered query."""
    return f"P6 Loc {next(_seq)}"


def _make_record(db, loc, *, approved=True, availability="available",
                 purpose="sale", price=1_500_000, ptype="villa",
                 bedrooms=3, bathrooms=3, area=2000.0,
                 amenities='["pool", "gym"]', highlights="sea view",
                 title=None, description="A quiet test listing.",
                 demo=False, currency="AED"):
    from app.database import Property

    n = next(_seq)
    prop = Property(
        title=title or f"P6 Listing {n}",
        description=description,
        purpose=purpose,
        availability=availability,
        price=price,
        currency=currency,
        property_type=ptype,
        location=loc,
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        area=area,
        area_unit="sqft",
        amenities=amenities,
        highlights=highlights,
        is_approved=approved,
        is_demo=demo,
        source="demo_seed" if demo else "manual",
    )
    db.add(prop)
    db.commit()
    db.refresh(prop)
    return prop


def _register_customer(client, tag: str) -> str:
    email = f"p6.{tag}.{next(_seq)}@example.com"
    password = "Synth-Pass-6!"
    r = client.post(
        "/api/customer/register",
        json={"email": email, "password": password,
              "confirm_password": password, "name": "P6 Synthetic"},
    )
    assert r.status_code == 200, r.text
    return email


# =========================================================================
# PUBLIC LISTING ENDPOINT — eligibility
# =========================================================================

def test_listing_returns_approved_and_available_only(client, db):
    loc = _loc()
    ok1 = _make_record(db, loc, price=1_000_000)
    ok2 = _make_record(db, loc, price=2_000_000)
    _make_record(db, loc, approved=False, price=500_000)      # unapproved
    _make_record(db, loc, availability="sold", price=600_000)      # sold
    _make_record(db, loc, availability="reserved", price=700_000)  # reserved
    _make_record(db, loc, availability="off_market", price=800_000)

    r = client.get("/api/properties", params={"location": loc})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert [p["id"] for p in body["results"]] == [ok1.id, ok2.id]  # price asc


def test_listing_purpose_filters(client, db):
    loc = _loc()
    sale = _make_record(db, loc, purpose="sale", price=1_000_000)
    rent = _make_record(db, loc, purpose="rent", price=90_000)
    lease = _make_record(db, loc, purpose="lease", price=120_000)

    for purpose, expected_id in (("sale", sale.id), ("rent", rent.id),
                                 ("lease", lease.id)):
        r = client.get("/api/properties",
                       params={"location": loc, "purpose": purpose})
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1, f"purpose={purpose} must match exactly one"
        assert body["results"][0]["id"] == expected_id
        assert body["results"][0]["purpose"] == purpose


def test_listing_unknown_purpose_rejected(client):
    assert client.get("/api/properties", params={"purpose": "buy"}).status_code == 422
    assert client.get("/api/properties", params={"purpose": ""}).status_code == 422


def test_listing_location_and_type_filters(client, db):
    loc = _loc()
    villa = _make_record(db, loc, ptype="villa")
    _make_record(db, loc, ptype="apartment")

    r = client.get("/api/properties", params={"location": loc.upper(),
                                              "property_type": "Villa"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["results"][0]["id"] == villa.id


def test_listing_price_and_bedroom_filters(client, db):
    loc = _loc()
    cheap = _make_record(db, loc, price=900_000, bedrooms=1)
    mid = _make_record(db, loc, price=1_500_000, bedrooms=3)
    _make_record(db, loc, price=3_000_000, bedrooms=5)

    r = client.get("/api/properties", params={
        "location": loc, "min_price": 800_000, "max_price": 2_000_000,
        "min_bedrooms": 2})
    assert r.status_code == 200
    assert [p["id"] for p in r.json()["results"]] == [mid.id]

    r = client.get("/api/properties", params={"location": loc, "max_price": 1_000_000})
    assert [p["id"] for p in r.json()["results"]] == [cheap.id]


def test_listing_pagination_deterministic(client, db):
    loc = _loc()
    a = _make_record(db, loc, price=100)   # same price pair -> id asc tiebreak
    b = _make_record(db, loc, price=100)
    c = _make_record(db, loc, price=200)
    d = _make_record(db, loc, price=300)

    full = client.get("/api/properties", params={"location": loc, "limit": 10}).json()
    assert [p["id"] for p in full["results"]] == [a.id, b.id, c.id, d.id]

    p1 = client.get("/api/properties",
                    params={"location": loc, "limit": 2, "offset": 0}).json()
    p2 = client.get("/api/properties",
                    params={"location": loc, "limit": 2, "offset": 2}).json()
    assert [p["id"] for p in p1["results"]] == [a.id, b.id]
    assert [p["id"] for p in p2["results"]] == [c.id, d.id]
    assert p1["total"] == p2["total"] == 4


def test_listing_empty_results(client, db):
    r = client.get("/api/properties", params={"location": "P6 Nowhere Ville"})
    assert r.status_code == 200
    assert r.json() == {"results": [], "total": 0, "limit": 24, "offset": 0}


@pytest.mark.parametrize("params", [
    {"limit": 0}, {"limit": 999}, {"limit": "abc"}, {"offset": -1},
    {"min_price": -5}, {"min_bedrooms": -1}, {"max_bedrooms": 99},
    {"location": "x" * 200},
])
def test_listing_invalid_params_422(client, params):
    assert client.get("/api/properties", params=params).status_code == 422


def test_listing_demo_rows_flagged_with_disclaimer(client, db):
    loc = _loc()
    notice = ("FICTIONAL DEMO LISTING — this is synthetic training/demo data, "
              "NOT a real or currently available Lyka Realty property.")
    demo = _make_record(db, loc, demo=True,
                        description=f"{notice} Two-bedroom fictional rental.",
                        title="Fictional Demo - 2BR Test Apartment (Rent)",
                        purpose="rent", price=60_000)

    r = client.get("/api/properties", params={"location": loc})
    row = r.json()["results"][0]
    assert row["id"] == demo.id
    assert row["is_demo"] is True
    assert "FICTIONAL DEMO LISTING" in row["description"]


def test_listing_exposes_no_internal_fields(client, db):
    loc = _loc()
    _make_record(db, loc)
    row = client.get("/api/properties", params={"location": loc}).json()["results"][0]
    for forbidden in ("is_approved", "source", "external_ref",
                      "created_at", "updated_at"):
        assert forbidden not in row, forbidden
    assert set(row) == {
        "id", "title", "description", "purpose", "price", "currency",
        "price_period", "property_type", "location", "bedrooms", "bathrooms",
        "area", "area_unit", "amenities", "highlights", "availability",
        "is_demo",
    }


def test_listing_amenities_parsed(client, db):
    loc = _loc()
    _make_record(db, loc, amenities='["pool", "gym"]')
    row = client.get("/api/properties", params={"location": loc}).json()["results"][0]
    assert row["amenities"] == ["pool", "gym"]


# =========================================================================
# PUBLIC DETAIL ENDPOINT
# =========================================================================

def test_detail_eligible_record_ok(client, db):
    loc = _loc()
    rec = _make_record(db, loc, price=2_500_000)
    r = client.get(f"/api/properties/record/{rec.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == rec.id
    assert body["title"] == rec.title
    assert body["purpose"] == "sale"
    assert body["price"] == 2_500_000
    assert body["currency"] == "AED"
    assert body["availability"] == "available"
    assert body["amenities"] == ["pool", "gym"]


def test_detail_missing_404(client, db):
    assert client.get("/api/properties/record/999999").status_code == 404


def test_detail_unapproved_404(client, db):
    rec = _make_record(db, _loc(), approved=False)
    assert client.get(f"/api/properties/record/{rec.id}").status_code == 404


@pytest.mark.parametrize("availability", ["sold", "rented", "reserved", "off_market"])
def test_detail_unavailable_404(client, db, availability):
    rec = _make_record(db, _loc(), availability=availability)
    assert client.get(f"/api/properties/record/{rec.id}").status_code == 404


def test_detail_optional_fields_nullable(client, db):
    rec = _make_record(db, _loc(), area=None, amenities="[]", highlights=None)
    r = client.get(f"/api/properties/record/{rec.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["area"] is None
    assert body["amenities"] == []
    assert body["highlights"] == ""


def test_detail_price_period_by_purpose(client, db):
    rent = _make_record(db, _loc(), purpose="rent", price=95_000)
    lease = _make_record(db, _loc(), purpose="lease", price=110_000)
    sale = _make_record(db, _loc(), purpose="sale", price=1_900_000)
    assert client.get(f"/api/properties/record/{rent.id}").json()["price_period"] == "per year"
    assert client.get(f"/api/properties/record/{lease.id}").json()["price_period"] == "per year"
    assert client.get(f"/api/properties/record/{sale.id}").json()["price_period"] == "one-time"


def test_detail_demo_disclaimer_visible(client, db):
    notice = "FICTIONAL DEMO LISTING — synthetic demo data, NOT a real property."
    rec = _make_record(db, _loc(), demo=True, description=notice)
    body = client.get(f"/api/properties/record/{rec.id}").json()
    assert body["is_demo"] is True
    assert "FICTIONAL DEMO LISTING" in body["description"]


def test_detail_exposes_no_internal_fields(client, db):
    rec = _make_record(db, _loc())
    body = client.get(f"/api/properties/record/{rec.id}").json()
    for forbidden in ("is_approved", "source", "external_ref",
                      "created_at", "updated_at"):
        assert forbidden not in body, forbidden


# =========================================================================
# LEGACY DATASET ENDPOINTS — preserved byte-for-byte
# =========================================================================

def test_dataset_detail_endpoint_preserved(client):
    """GET /api/properties/{id} still serves the UAE dataset row shape."""
    r = client.get("/api/properties/1")
    assert r.status_code == 200
    body = r.json()
    assert body["property_id"] == 1
    assert "no__of__beds" in body


def test_dataset_search_endpoint_preserved(client):
    """GET /api/properties/search still serves dataset-shaped rows."""
    r = client.get("/api/properties/search",
                   params={"location": "Dubai Marina", "limit": 3})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= len(body["results"]) > 0
    for row in body["results"]:
        assert "property_id" in row and "no__of__beds" in row


# =========================================================================
# SAVED PROPERTIES — both id spaces
# =========================================================================

def test_saved_requires_account(client, db):
    rec = _make_record(db, _loc())
    assert client.get("/api/customer/saved").status_code == 401
    assert client.post("/api/customer/saved",
                       json={"property_id": 1}).status_code == 401


def test_save_record_roundtrip(client, db):
    loc = _loc()
    rec = _make_record(db, loc, price=777_000)
    _register_customer(client, "recround")

    r = client.post("/api/customer/saved",
                    json={"property_id": rec.id, "source": "record"})
    assert r.status_code == 200, r.text
    assert r.json() == {"saved": True, "property_id": rec.id, "source": "record"}

    saved = client.get("/api/customer/saved").json()
    assert saved["total"] == 1
    row = saved["results"][0]
    assert row["source"] == "record"
    assert row["property_id"] == rec.id   # decoded back to the record id
    assert row["price"] == 777_000
    assert "is_approved" not in row

    # idempotent
    client.post("/api/customer/saved", json={"property_id": rec.id, "source": "record"})
    assert client.get("/api/customer/saved").json()["total"] == 1

    r = client.delete(f"/api/customer/saved/{rec.id}?source=record")
    assert r.status_code == 200
    assert client.get("/api/customer/saved").json()["total"] == 0


def test_save_record_stored_in_reserved_range(client, db):
    """Record bookmarks occupy a collision-proof reserved id range."""
    from app.database import SavedProperty
    from app.main import _SAVED_RECORD_ID_BASE

    rec = _make_record(db, _loc())
    _register_customer(client, "recrange")
    client.post("/api/customer/saved", json={"property_id": rec.id, "source": "record"})

    row = db.query(SavedProperty).order_by(SavedProperty.id.desc()).first()
    assert row.property_id == _SAVED_RECORD_ID_BASE + rec.id
    assert row.property_id >= _SAVED_RECORD_ID_BASE


def test_save_dataset_default_unchanged(client, db):
    """Legacy flow (no source field) stores the raw dataset id, as before."""
    from app.database import SavedProperty

    _register_customer(client, "dsdefault")
    r = client.post("/api/customer/saved", json={"property_id": 5})
    assert r.status_code == 200, r.text
    assert r.json() == {"saved": True, "property_id": 5, "source": "dataset"}

    row = db.query(SavedProperty).order_by(SavedProperty.id.desc()).first()
    assert row.property_id == 5  # raw, un-encoded

    saved = client.get("/api/customer/saved").json()
    assert saved["results"][0]["source"] == "dataset"
    assert saved["results"][0]["property_id"] == 5
    assert "no__of__beds" in saved["results"][0]  # dataset shape preserved


def test_save_unapproved_record_404(client, db):
    rec = _make_record(db, _loc(), approved=False)
    _register_customer(client, "unappr")
    r = client.post("/api/customer/saved",
                    json={"property_id": rec.id, "source": "record"})
    assert r.status_code == 404
    assert client.get("/api/customer/saved").json()["total"] == 0


def test_save_unknown_record_404(client, db):
    _register_customer(client, "unknownrec")
    assert client.post("/api/customer/saved",
                       json={"property_id": 999999, "source": "record"}).status_code == 404


def test_unsave_only_touches_target_space(client, db):
    """Dataset id 7 and record id 7 are different bookmarks — unsaving one
    must never delete the other."""
    from app.database import SavedProperty

    rec7 = _make_record(db, _loc())
    assert rec7.id != 7  # otherwise the two-space scenario is meaningless
    _register_customer(client, "spacesep")
    client.post("/api/customer/saved", json={"property_id": 7})               # dataset
    client.post("/api/customer/saved", json={"property_id": rec7.id, "source": "record"})

    client.delete("/api/customer/saved/7")  # default source=dataset
    rows = db.query(SavedProperty).all()
    assert all(r.property_id != 7 for r in rows)
    saved = client.get("/api/customer/saved").json()
    assert saved["total"] == 1 and saved["results"][0]["source"] == "record"

    client.delete(f"/api/customer/saved/{rec7.id}?source=record")
    assert client.get("/api/customer/saved").json()["total"] == 0


def test_saved_isolation_between_customers(app_module, db):
    loc = _loc()
    rec = _make_record(db, loc)

    client_a = TestClient(app_module.app)
    _register_customer(client_a, "isoA")
    client_a.post("/api/customer/saved", json={"property_id": rec.id, "source": "record"})

    client_b = TestClient(app_module.app)
    _register_customer(client_b, "isoB")
    assert client_b.get("/api/customer/saved").json()["total"] == 0

    # A's bookmark is still there
    assert client_a.get("/api/customer/saved").json()["total"] == 1


def test_saved_skips_record_that_became_ineligible(client, db):
    """A bookmark of a record that later became unapproved is skipped, not
    leaked."""
    rec = _make_record(db, _loc())
    _register_customer(client, "skipinelig")
    client.post("/api/customer/saved", json={"property_id": rec.id, "source": "record"})

    rec.is_approved = False
    db.commit()

    saved = client.get("/api/customer/saved").json()
    assert saved["total"] == 0


# =========================================================================
# CHAT ENQUIRY WIRING — faked agent, no network, no CRM writes
# =========================================================================

class _FakeState:
    def __init__(self):
        self.contact = {}
        self.recommended_properties = []

    def add_message(self, *args, **kwargs):
        pass


class _FakeAgent:
    """Minimal stand-in for AIRealEstateAgent — captures the focus listing
    the endpoint resolved, so tests can assert exactly what the LLM would
    have seen, without any NVIDIA call."""

    last_focus = None

    def __init__(self, conversation_id=None):
        self.state = _FakeState()

    def _extract_requirements(self, *args, **kwargs):
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


def test_chat_record_focus_resolved_from_eligible_record(client, db, fake_agent):
    loc = _loc()
    rec = _make_record(db, loc, price=1_234_000)
    r = client.post("/api/chat", json={
        "message": "Tell me more about this property",
        "property_id": rec.id,
        "property_source": "record",
    })
    assert r.status_code == 200, r.text
    focus = fake_agent.last_focus
    assert focus is not None
    # Dataset-shaped keys the NVIDIA agent already understands
    assert focus["property_id"] == rec.id
    assert focus["location"] == loc
    assert focus["price"] == 1_234_000
    assert "no__of__beds" in focus


def test_chat_unapproved_record_resolves_to_no_focus(client, db, fake_agent):
    """An unverified listing can never become chat context — the assistant
    is given no focus at all, so it cannot claim it is available."""
    rec = _make_record(db, _loc(), approved=False)
    r = client.post("/api/chat", json={
        "message": "Is this available?",
        "property_id": rec.id,
        "property_source": "record",
    })
    assert r.status_code == 200
    assert fake_agent.last_focus is None


def test_chat_invalid_property_source_422(client, fake_agent):
    r = client.post("/api/chat", json={
        "message": "hello",
        "property_id": 1,
        "property_source": "alien",
    })
    assert r.status_code == 422


def test_chat_dataset_focus_preserved(client, fake_agent):
    """Legacy ?ref= flow: default source='dataset' still resolves the dataset
    row (id 1) exactly as before."""
    r = client.post("/api/chat", json={"message": "hello", "property_id": 1})
    assert r.status_code == 200
    focus = fake_agent.last_focus
    assert focus is not None
    assert focus["property_id"] == 1
    assert "no__of__beds" in focus  # dataset shape, unchanged


def test_viewing_or_enquiring_creates_no_lead(client, db, fake_agent):
    from app.database import Lead

    loc = _loc()
    rec = _make_record(db, loc)
    before = db.query(Lead).count()

    # browse + detail + chat enquiry
    client.get("/api/properties", params={"location": loc})
    client.get(f"/api/properties/record/{rec.id}")
    r = client.post("/api/chat", json={
        "message": "I want to enquire about listing %s please" % rec.id,
        "property_id": rec.id,
        "property_source": "record",
    })
    assert r.status_code == 200

    db.expire_all()
    assert db.query(Lead).count() == before  # no CRM lead from browsing/enquiry


def test_voice_forwards_property_source(client, app_module, monkeypatch):
    import app.main as main_mod

    captured = {}

    def fake_chat(request, db=None, http_request=None, response=None, _rl=None):
        captured["request"] = request
        return {"response": "ok", "detected_language": "en", "properties": [],
                "action": "continue", "conversation_id": 1, "new_conversation": True}

    monkeypatch.setattr(main_mod, "chat", fake_chat)
    r = client.post("/api/voice/respond", json={
        "message": "hello", "property_id": 42, "property_source": "record"})
    assert r.status_code == 200
    assert captured["request"].property_source == "record"
    assert captured["request"].property_id == 42
