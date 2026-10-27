"""Phase 4 — deterministic property matching, persistence, and staff endpoints.

Service-level tests run against an ISOLATED temporary SQLite database (own
engine, created per test) so they can never observe or mutate rows created by
other test files — and never the live backend/real_estate.db. Endpoint tests
use the shared throwaway test DB via the standard ``client`` fixture with
shape-based assertions that are independent of leftover rows.
"""

import itertools
import json
import logging
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.ai.lead_extraction import LeadExtractionResult
from app.database import (
    Base,
    Conversation,
    Customer,
    Lead,
    Message,
    Property,
    PropertyRecommendation,
)
from app.services.property_matching import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    WEIGHTS,
    hard_requirement_failures,
    match_properties,
    save_recommendations,
)

_seq = itertools.count(1)

SCORE_URL = "/api/agent/leads/score"
MATCH_URL = "/api/agent/properties/match"


# ------------------------------------------------------------- fixtures/helpers

@pytest.fixture()
def mdb(tmp_path):
    """Isolated temporary database — independent of the shared test DB."""
    engine = create_engine("sqlite:///" + (tmp_path / "match.db").as_posix())
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _prop(mdb, **overrides):
    n = next(_seq)
    fields = dict(
        external_ref=f"P4-TEST-{n:04d}",
        title=f"Phase4 Synthetic Listing {n}",
        description="Synthetic Phase 4 test listing (fictional).",
        purpose="sale",
        availability="available",
        price=1_000_000.0,
        currency="AED",
        property_type="apartment",
        location="Phase4 Testville",
        bedrooms=2,
        bathrooms=2,
        area=900.0,
        amenities='["gym", "balcony"]',
        highlights="fictional: sea view from the balcony",
        is_approved=True,
        is_demo=True,
        source="demo_seed",
    )
    fields.update(overrides)
    prop = Property(**fields)
    mdb.add(prop)
    mdb.commit()
    mdb.refresh(prop)
    return prop


def _lead(**overrides):
    base = dict(
        intent="buy",
        property_type="apartment",
        location="Phase4 Testville",
        bedrooms=2,
        budget_max=2_000_000.0,
        budget_currency="AED",
        amenities=["gym"],
        preferences=["sea view"],
    )
    base.update(overrides)
    return LeadExtractionResult.model_validate(base)


def _ids(result):
    return [r.property_id for r in result.results]


def _notes(match):
    return " ".join(match.mismatches + match.data_gaps)


# ------------------------------------------------------------------ weights

def test_weights_are_exact_and_sum_to_100():
    assert WEIGHTS == {
        "location": 30.0,
        "budget": 25.0,
        "type_bedrooms": 20.0,
        "amenities": 15.0,
        "preferences": 10.0,
    }
    assert abs(sum(WEIGHTS.values()) - 100.0) < 1e-9


# ------------------------------------------------------------- happy matches

def test_approved_available_sale_listing_matches_buy_enquiry(mdb):
    prop = _prop(mdb)
    res = match_properties(mdb, _lead())
    assert _ids(res) == [prop.id]
    m = res.results[0]
    # exact full-match: every component earns its full weight
    assert m.breakdown == {
        "location": 30.0, "budget": 25.0, "type_bedrooms": 20.0,
        "amenities": 15.0, "preferences": 10.0,
    }
    assert m.match_score == 100.0
    assert 0 <= m.match_score <= 100
    assert m.reasons and m.mismatches == [] and m.data_gaps == []
    assert res.candidates_considered == 1 and res.eligible_count == 1
    # only real database fields are reported
    row = mdb.query(Property).filter(Property.id == m.property_id).first()
    assert row is not None
    assert m.title == row.title and m.price == row.price
    assert m.purpose == "sale" and m.is_demo is True


def test_approved_available_rental_listing_matches_rent_enquiry(mdb):
    prop = _prop(mdb, purpose="rent", price=95_000.0)
    res = match_properties(
        mdb, _lead(intent="rent", budget_max=120_000.0,
                   budget_period="yearly"))
    assert _ids(res) == [prop.id]
    m = res.results[0]
    assert m.breakdown["budget"] == 25.0      # yearly-vs-yearly compared
    assert m.match_score == 100.0
    assert any("yearly rent" in r for r in m.reasons)


def test_lease_enquiry_matches_only_lease_purpose_listing(mdb):
    _prop(mdb, purpose="sale")
    _prop(mdb, purpose="rent", price=90_000.0)
    lease = _prop(mdb, purpose="lease", price=85_000.0)
    res = match_properties(
        mdb, _lead(intent="lease", budget_period="yearly",
                   budget_max=100_000.0))
    assert _ids(res) == [lease.id]


def test_intent_purpose_conflict_is_excluded(mdb):
    sale = _prop(mdb, purpose="sale")
    rent = _prop(mdb, purpose="rent", price=90_000.0)
    # buy enquiry never sees the rent row
    assert _ids(match_properties(mdb, _lead())) == [sale.id]
    # rent enquiry never sees the sale row
    rent_res = match_properties(
        mdb, _lead(intent="rent", budget_period="yearly", budget_max=100_000.0))
    assert rent.id in _ids(rent_res)
    assert sale.id not in _ids(rent_res)
    # the predicate itself defends even without the query's purpose filter
    stub = SimpleNamespace(purpose="rent", is_approved=True,
                           availability="available", bedrooms=2,
                           bathrooms=2, property_type="apartment")
    assert any("conflicts" in f for f in hard_requirement_failures(stub, _lead()))


# --------------------------------------------------------- hard eligibility

def test_unapproved_listing_excluded(mdb):
    ok = _prop(mdb)
    _prop(mdb, is_approved=False)
    res = match_properties(mdb, _lead())
    assert _ids(res) == [ok.id]
    assert res.candidates_considered == 1   # never even enters the pool


def test_unavailable_listings_excluded(mdb):
    ok = _prop(mdb)
    for status in ("reserved", "sold", "rented", "off_market"):
        _prop(mdb, availability=status)
    res = match_properties(mdb, _lead())
    assert _ids(res) == [ok.id]
    assert res.candidates_considered == 1


def test_unknown_purpose_is_excluded_everywhere():
    from app.services.property_search import is_verified_purpose

    assert is_verified_purpose("sale") and is_verified_purpose("lease")
    assert not is_verified_purpose("unknown")
    assert not is_verified_purpose(None)
    # in-depth predicate check with an unknown-purpose record
    stub = SimpleNamespace(purpose="unknown", is_approved=True,
                           availability="available", bedrooms=2,
                           bathrooms=2, property_type="apartment")
    assert any("not verified" in f for f in hard_requirement_failures(stub, _lead()))


def test_db_schema_rejects_unknown_purpose(mdb):
    with pytest.raises(IntegrityError):
        mdb.add(Property(
            title="Bad purpose row", description="", purpose="unknown",
            availability="available", price=1.0, currency="AED",
            property_type="apartment", location="Nowhere", bedrooms=1,
            bathrooms=1, amenities="[]"))
        mdb.commit()
    mdb.rollback()


def test_bedroom_hard_requirement_enforced(mdb):
    _prop(mdb, bedrooms=2)
    res = match_properties(mdb, _lead(bedrooms=4))
    assert res.results == []
    assert res.eligible_count == 0
    assert res.candidates_considered == 1
    assert res.explanation.startswith("No eligible properties")


def test_bathroom_hard_requirement_enforced(mdb):
    _prop(mdb, bathrooms=2)
    res = match_properties(mdb, _lead(bathrooms=3))
    assert res.results == []
    assert "No eligible properties" in res.explanation


def test_property_type_hard_requirement_enforced(mdb):
    _prop(mdb, property_type="apartment")
    res = match_properties(mdb, _lead(property_type="villa"))
    assert res.results == []
    assert "No eligible properties" in res.explanation


def test_property_type_normalisation_case_and_hyphen(mdb):
    _prop(mdb, property_type="Town-house")
    res = match_properties(
        mdb, _lead(property_type="Town House", bedrooms=2))
    assert len(res.results) == 1
    assert res.results[0].breakdown["type_bedrooms"] == 20.0


# ------------------------------------- missing lead data handled transparently

def test_missing_budget_and_location_score_zero_with_notes(mdb):
    _prop(mdb)
    res = match_properties(
        mdb, _lead(location=None, budget_max=None, budget_currency=None))
    m = res.results[0]
    assert m.breakdown["location"] == 0.0
    assert m.breakdown["budget"] == 0.0
    notes = " ".join(m.mismatches)
    assert "Location: not provided" in notes
    assert "Budget: no amount provided" in notes
    # the other dimensions still earn their points
    assert m.breakdown["type_bedrooms"] == 20.0
    assert m.breakdown["amenities"] == 15.0
    assert m.breakdown["preferences"] == 10.0
    assert m.match_score == 45.0


def test_budget_without_currency_is_never_assumed(mdb):
    _prop(mdb)   # AED
    res = match_properties(mdb, _lead(budget_currency=None))
    m = res.results[0]
    assert m.breakdown["budget"] == 0.0
    assert "currency not provided" in _notes(m)
    assert m.breakdown["location"] == 30.0   # other criteria unaffected


def test_incompatible_currency_produces_no_false_budget_match(mdb):
    _prop(mdb)   # AED listing
    res = match_properties(mdb, _lead(budget_currency="INR"))
    m = res.results[0]
    assert m.breakdown["budget"] == 0.0
    assert "currency mismatch (lead INR vs property AED)" in _notes(m)
    assert m.breakdown["location"] == 30.0   # eligible, but budget never faked


def test_monthly_rent_versus_yearly_property_no_false_match(mdb):
    _prop(mdb, purpose="rent", price=95_000.0)
    res = match_properties(
        mdb, _lead(intent="rent", budget_period="monthly", budget_max=8_000.0))
    m = res.results[0]
    assert m.breakdown["budget"] == 0.0
    notes = _notes(m)
    assert "monthly" in notes and "yearly" in notes
    assert "periods are not converted" in notes


def test_yearly_rent_is_compared_against_yearly_property(mdb):
    _prop(mdb, purpose="rent", price=95_000.0)
    res = match_properties(
        mdb, _lead(intent="rent", budget_period="yearly", budget_max=120_000.0))
    assert res.results[0].breakdown["budget"] == 25.0


def test_unspecified_rent_period_stays_ambiguous(mdb):
    _prop(mdb, purpose="rent", price=95_000.0)
    res = match_properties(mdb, _lead(intent="rent", budget_max=120_000.0))
    m = res.results[0]
    assert m.breakdown["budget"] == 0.0
    assert "period unspecified" in _notes(m)
    assert "never assumed" in _notes(m)


def test_buy_intent_with_monthly_period_is_contradictory(mdb):
    _prop(mdb)   # sale row
    res = match_properties(
        mdb, _lead(budget_period="monthly", budget_max=30_000.0))
    m = res.results[0]
    assert m.breakdown["budget"] == 0.0
    assert "contradictory" in _notes(m)


def test_unknown_intent_still_eligible_but_budget_not_aligned(mdb):
    _prop(mdb, purpose="sale")
    res = match_properties(mdb, _lead(intent="unknown"))
    m = res.results[0]
    assert m.property_id  # no stated intent → no purpose conflict
    assert m.breakdown["budget"] == 0.0
    assert "intent unknown" in _notes(m)


def test_budget_outside_stated_bounds_scores_zero(mdb):
    _prop(mdb, price=3_500_000.0)   # above the lead's max
    res = match_properties(mdb, _lead(budget_max=2_000_000.0))
    m = res.results[0]
    assert m.breakdown["budget"] == 0.0
    assert "exceeds stated max" in _notes(m)


def test_budget_below_stated_min_scores_zero(mdb):
    _prop(mdb, price=500_000.0)
    res = match_properties(mdb, _lead(budget_min=1_000_000.0,
                                      budget_max=2_000_000.0))
    m = res.results[0]
    assert m.breakdown["budget"] == 0.0
    assert "below stated min" in _notes(m)


# ------------------------------------------------- missing PROPERTY data

def test_missing_property_data_never_reported_as_matched(mdb):
    _prop(mdb, amenities="[]", highlights=None, area=None)
    res = match_properties(mdb, _lead())   # requests gym + "sea view"
    m = res.results[0]
    assert m.breakdown["amenities"] == 0.0
    assert m.breakdown["preferences"] == 0.0
    assert "no highlight data" in " ".join(m.data_gaps)
    assert "not counted as matched" in " ".join(m.data_gaps)
    reasons = " ".join(m.reasons)
    assert "Amenities: matched" not in reasons
    assert "Preferences: matched" not in reasons
    assert m.area is None                  # missing area reported as-is
    assert "not offered" in _notes(m)      # empty amenity list = real (no match)


def test_unreadable_property_amenities_are_a_data_gap(mdb):
    _prop(mdb, amenities="not-json{")
    res = match_properties(mdb, _lead())
    m = res.results[0]
    assert m.breakdown["amenities"] == 0.0
    assert "unreadable" in " ".join(m.data_gaps)


# ------------------------------------------------- weights & partial credit

def test_partial_amenity_and_preference_credit_is_exact(mdb):
    _prop(mdb, amenities='["gym", "pool"]',   # lead wants gym + spa (1 of 2)
          highlights="fictional: sea view only")  # lead wants sea view + pet friendly
    res = match_properties(
        mdb, _lead(amenities=["gym", "spa"],
                   preferences=["sea view", "pet friendly"]))
    m = res.results[0]
    assert m.breakdown["amenities"] == 7.5     # 15 * 1/2
    assert m.breakdown["preferences"] == 5.0   # 10 * 1/2
    assert m.match_score == 30.0 + 25.0 + 20.0 + 7.5 + 5.0
    assert m.match_score == 87.5


def test_component_scores_never_exceed_their_weights(mdb):
    _prop(mdb)
    res = match_properties(mdb, _lead())
    for key, cap in WEIGHTS.items():
        assert res.results[0].breakdown[key] <= cap
    assert res.results[0].match_score <= 100.0


# ------------------------------------------------------------- ordering/limit

def test_stable_ordering_equal_scores_price_then_id(mdb):
    cheap = _prop(mdb, price=1_500_000.0)
    pricey = _prop(mdb, price=2_000_000.0)
    res = match_properties(mdb, _lead(budget_max=2_500_000.0))
    assert _ids(res) == [cheap.id, pricey.id]        # equal score → price ASC
    assert res.results[0].match_score == res.results[1].match_score

    a = _prop(mdb, price=1_800_000.0)
    b = _prop(mdb, price=1_800_000.0)                 # equal price → id ASC
    res2 = match_properties(mdb, _lead(budget_max=2_500_000.0))
    ids = _ids(res2)
    same_price = [i for i in ids if i in (a.id, b.id)]
    assert a.id < b.id
    assert same_price == sorted(same_price)


def test_default_limit_is_three(mdb):
    for _ in range(5):
        _prop(mdb)
    res = match_properties(mdb, _lead())
    assert DEFAULT_LIMIT == 3
    assert len(res.results) == 3
    assert res.eligible_count == 5
    assert "showing top 3" in res.explanation


def test_limit_is_configurable_and_clamped(mdb):
    for _ in range(12):
        _prop(mdb)
    assert len(match_properties(mdb, _lead(), limit=2).results) == 2
    assert len(match_properties(mdb, _lead(), limit=99).results) == MAX_LIMIT == 10
    assert len(match_properties(mdb, _lead(), limit=0).results) == 1


def test_empty_eligible_result_is_explained(mdb):
    _prop(mdb, bedrooms=2)      # in the pool, but fails the hard requirement
    res = match_properties(mdb, _lead(bedrooms=5))
    assert res.results == []
    assert res.eligible_count == 0
    assert res.candidates_considered == 1
    assert res.explanation.startswith("No eligible properties")
    assert "invented" in res.explanation


def test_only_approved_database_records_are_returned(mdb):
    keep = _prop(mdb)
    _prop(mdb, is_approved=False)
    res = match_properties(mdb, _lead())
    assert _ids(res) == [keep.id]
    for r in res.results:
        row = mdb.query(Property).filter(Property.id == r.property_id).first()
        assert row is not None and row.is_approved is True
        assert row.availability == "available"


def test_matching_is_read_only(mdb):
    _prop(mdb)
    before = mdb.query(PropertyRecommendation).count()
    match_properties(mdb, _lead())
    assert mdb.query(PropertyRecommendation).count() == before


# --------------------------------------------------------------- persistence

def test_save_recommendations_stores_accurate_refs_and_scores(mdb):
    prop = _prop(mdb, highlights=None)   # creates a foldable data gap
    lead = Lead(name="Phase4 Synthetic Lead", status="new")
    mdb.add(lead)
    mdb.commit()
    mdb.refresh(lead)

    res = match_properties(mdb, _lead())
    assert _ids(res) == [prop.id]

    before = {m: mdb.query(m).count()
              for m in (Customer, Conversation, Message, Lead)}
    ids = save_recommendations(mdb, res, lead_id=lead.id)
    assert len(ids) == len(res.results) == 1

    rec = mdb.query(PropertyRecommendation).filter(
        PropertyRecommendation.id == ids[0]).one()
    m = res.results[0]
    assert rec.property_record_id == prop.id   # REAL properties.id reference
    assert rec.property_id is None             # never a dataset id
    assert rec.lead_id == lead.id
    # highlights=None → preferences gap → 90/100 (data gap never counted as match)
    assert m.match_score == 90.0
    assert rec.match_score == m.match_score
    assert rec.relevance_score == round(m.match_score / 100.0, 4)
    assert json.loads(rec.match_reasons) == m.reasons
    # data gaps folded into the mismatches JSON with a 'data gap:' prefix
    assert json.loads(rec.match_mismatches) == (
        m.mismatches + [f"data gap: {g}" for g in m.data_gaps])
    assert rec.price == "1,000,000 AED"
    assert rec.property_type == prop.property_type
    assert rec.location == prop.location
    # no unrelated rows were touched (no lead/customer/conversation creation)
    after = {m2: mdb.query(m2).count() for m2 in before}
    assert after == before


def test_save_recommendations_rejects_invalid_references(mdb):
    _prop(mdb)
    res = match_properties(mdb, _lead())
    with pytest.raises(ValueError):
        save_recommendations(mdb, res, lead_id=999_999)
    assert mdb.query(PropertyRecommendation).count() == 0      # nothing written
    with pytest.raises(ValueError):
        save_recommendations(mdb, res, conversation_id=999_999)
    assert mdb.query(PropertyRecommendation).count() == 0


def test_save_recommendations_rejects_dangling_property(mdb):
    _prop(mdb)
    res = match_properties(mdb, _lead())
    assert res.results                       # matched while the row existed
    mdb.query(Property).delete()
    mdb.commit()
    with pytest.raises(ValueError):
        save_recommendations(mdb, res)
    assert mdb.query(PropertyRecommendation).count() == 0


# ------------------------------------------------------------- staff endpoints

def _staff_token(client):
    r = client.post("/api/auth/login",
                    json={"username": "admin@lykarealty.ae",
                          "password": "Admin@123"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _staff_headers(client):
    return {"Authorization": f"Bearer {_staff_token(client)}"}


def test_score_and_match_denied_for_anonymous_and_customer(client):
    body = {"intent": "buy"}
    # anonymous
    assert client.post(SCORE_URL, json=body).status_code == 401
    assert client.post(MATCH_URL,
                       json={"extraction": body}).status_code == 401
    # customer session
    client.post("/api/customer/register", json={
        "email": "phase4.endpoint.customer@example.com",
        "password": "SyntheticPw!123",
        "name": "Phase4 Endpoint Customer",
        "confirm_password": "SyntheticPw!123",
    })
    assert client.post(SCORE_URL, json=body).status_code == 401
    assert client.post(MATCH_URL,
                       json={"extraction": body}).status_code == 401


def test_score_endpoint_computes_and_ignores_client_supplied_score(client):
    headers = _staff_headers(client)
    payload = {
        "intent": "buy",
        "location": "Phase4 Endpoint Community",
        "budget_max": 1_000_000,
        "budget_currency": "AED",
        "lead_score": 999,               # never authoritative
        "priority": "high",              # never authoritative
        "score_breakdown": {"budget": 20},
    }
    r = client.post(SCORE_URL, json=payload, headers=headers)
    assert r.status_code == 200, r.text
    score = r.json()["score"]
    assert score["total_score"] == 55     # 20 budget + 20 location + 15 intent
    assert score["priority"] == "medium"
    assert isinstance(score["breakdown"], list)
    assert len(score["breakdown"]) == 6
    assert all(0 <= c["awarded"] <= c["maximum"] for c in score["breakdown"])


def test_score_endpoint_rejects_junk_without_scoring(client):
    headers = _staff_headers(client)
    r = client.post(SCORE_URL, json={"intent": "purchase-now",
                                     "bedrooms": "two"}, headers=headers)
    assert r.status_code == 422


def test_score_and_match_never_call_the_provider(client, monkeypatch):
    import app.ai.openai_client as openai_client

    def boom(*args, **kwargs):
        raise AssertionError("scoring/matching must never call the provider")

    monkeypatch.setattr(openai_client, "chat_json", boom)
    monkeypatch.setattr(openai_client, "_post", boom)
    headers = _staff_headers(client)
    assert client.post(SCORE_URL, json={"intent": "buy"},
                       headers=headers).status_code == 200
    assert client.post(MATCH_URL, json={"extraction": {"intent": "buy"}},
                       headers=headers).status_code == 200


def test_match_endpoint_is_read_only_and_bounded(client, db):
    headers = _staff_headers(client)
    before = db.query(PropertyRecommendation).count()
    r = client.post(MATCH_URL, json={
        "extraction": {"intent": "buy", "bedrooms": 3},
        "limit": 2,
    }, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert {"results", "explanation",
            "candidates_considered", "eligible_count"} <= set(body)
    assert len(body["results"]) <= 2
    for item in body["results"]:
        assert {"property_id", "match_score", "breakdown",
                "reasons", "mismatches"} <= set(item)
        assert 0 <= item["match_score"] <= 100
    db.expire_all()
    assert db.query(PropertyRecommendation).count() == before   # no writes


def test_match_endpoint_validates_limit_and_extraction(client):
    headers = _staff_headers(client)
    assert client.post(MATCH_URL, json={
        "extraction": {"intent": "buy"}, "limit": 50,
    }, headers=headers).status_code == 422
    assert client.post(MATCH_URL, json={
        "extraction": {"intent": "bogus-purpose"},
    }, headers=headers).status_code == 422
    assert client.post(MATCH_URL, json={
        "extraction": {"intent": "buy", "bedrooms": "lots"},
    }, headers=headers).status_code == 422


def test_no_secrets_or_credentials_in_scoring_logs(client, caplog):
    headers = _staff_headers(client)
    with caplog.at_level(logging.DEBUG):
        client.post(SCORE_URL, json={"intent": "buy",
                                     "location": "Nowhere"},
                    headers=headers)
        client.post(MATCH_URL, json={"extraction": {"intent": "buy"}},
                    headers=headers)
    blob = " ".join(rec.getMessage() for rec in caplog.records)
    for secret in ("Admin@123", "Agent@123", "sk-", "nvapi-", "OPENAI_API_KEY"):
        assert secret not in blob
