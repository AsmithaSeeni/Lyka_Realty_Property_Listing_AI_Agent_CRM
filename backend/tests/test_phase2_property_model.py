"""Phase 2 — Property model, constraints, indexes, DB-backed search,
and defensive price normalisation (plus JSON-dataset search regression).
"""

import json
import pathlib

import pytest
from sqlalchemy.exc import IntegrityError

from app.database import Property
from app.services.property_search import (
    is_verified_purpose,
    parse_price,
    search_properties,
    search_property_records,
)

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
DATASET_JSON = _BACKEND / "UAErealestate.json"  # ships inside the backend/ service root


def _mk(db, **kw):
    defaults = dict(
        title="Test Property",
        description="synthetic test row",
        purpose="sale",
        availability="available",
        price=1_000_000,
        currency="AED",
        property_type="apartment",
        location="Dubai Marina",
        bedrooms=1,
        bathrooms=1,
        amenities=json.dumps(["Gym", "Swimming Pool"]),
        is_approved=True,
        is_demo=True,
    )
    defaults.update(kw)
    prop = Property(**defaults)
    db.add(prop)
    db.commit()
    db.refresh(prop)
    return prop


# ---------------------------------------------------------------- constraints

def test_property_requires_core_fields(db):
    # NOT NULL violations are schema-level; empty-string checks live in the
    # CRUD service (tested in test_phase2_property_crud.py).
    with pytest.raises(IntegrityError):
        _mk(db, title=None)
    db.rollback()
    with pytest.raises(IntegrityError):
        _mk(db, purpose=None)
    db.rollback()


def test_property_unknown_purpose_rejected_by_schema(db):
    with pytest.raises(IntegrityError):
        _mk(db, purpose="unknown")
    db.rollback()
    with pytest.raises(IntegrityError):
        _mk(db, purpose="foreclosure")
    db.rollback()


def test_property_unknown_availability_rejected_by_schema(db):
    with pytest.raises(IntegrityError):
        _mk(db, availability="maybe")
    db.rollback()


def test_property_negative_price_rejected(db):
    with pytest.raises(IntegrityError):
        _mk(db, price=-1)
    db.rollback()


def test_property_negative_bedrooms_rejected(db):
    with pytest.raises(IntegrityError):
        _mk(db, bedrooms=-2)
    db.rollback()


def test_property_external_ref_unique(db):
    _mk(db, external_ref="TEST-REF-1")
    with pytest.raises(IntegrityError):
        _mk(db, external_ref="TEST-REF-1")
    db.rollback()


def test_property_indexes_exist(db):
    from sqlalchemy import text

    rows = db.execute(text(
        "select name from sqlite_master where type='index' "
        "and tbl_name='properties'"
    )).fetchall()
    names = {r[0] for r in rows}
    for expected in [
        "ix_properties_purpose_availability",
        "ix_properties_approved_availability",
        "ix_properties_price",
        "ix_properties_property_type",
        "ix_properties_location_purpose",
    ]:
        assert expected in names


# ------------------------------------------------------- eligibility defaults

def test_sale_and_rent_rows_distinguishable(db):
    loc = "Purposeville (test)"
    sale = _mk(db, purpose="sale", location=loc, external_ref="T-SALE")
    rent = _mk(db, purpose="rent", location=loc, price=120_000,
               external_ref="T-RENT")
    lease = _mk(db, purpose="lease", location=loc, price=150_000,
                external_ref="T-LEASE")

    r_sale = search_property_records(db, purpose="sale", location=loc)
    assert {p.id for p in r_sale["results"]} == {sale.id}
    r_rent = search_property_records(db, purpose="rent", location=loc)
    assert {p.id for p in r_rent["results"]} == {rent.id}
    r_lease = search_property_records(db, purpose="lease", location=loc)
    assert {p.id for p in r_lease["results"]} == {lease.id}


def test_unavailable_properties_excluded_by_default(db):
    loc = "Availville (test)"
    _mk(db, location=loc, external_ref="T-AVAIL")
    _mk(db, location=loc, external_ref="T-RESERVED", availability="reserved")
    _mk(db, location=loc, external_ref="T-SOLD", availability="sold")
    res = search_property_records(db, purpose="sale", location=loc)
    refs = {p.external_ref for p in res["results"]}
    assert refs == {"T-AVAIL"}


def test_unapproved_properties_excluded_by_default(db):
    loc = "Approveville (test)"
    _mk(db, location=loc, external_ref="T-APPROVED", is_approved=True)
    _mk(db, location=loc, external_ref="T-PENDING", is_approved=False)
    res = search_property_records(db, purpose="sale", location=loc)
    refs = {p.external_ref for p in res["results"]}
    assert refs == {"T-APPROVED"}


def test_unknown_purpose_query_rejected_not_guessed(db):
    _mk(db, location="Zedville (test)", external_ref="T-ANY")
    with pytest.raises(ValueError):
        search_property_records(db, purpose="unknown")
    with pytest.raises(ValueError):
        search_property_records(db, purpose="")
    assert is_verified_purpose("SALE") is True
    assert is_verified_purpose("unknown") is False
    assert is_verified_purpose(None) is False
    assert is_verified_purpose(7) is False


def test_no_results_returns_empty_not_invented(db):
    res = search_property_records(db, purpose="sale", location="Voidborough")
    assert res["results"] == [] and res["total"] == 0


def test_search_filters_compose(db):
    _mk(db, location="Business Bay", bedrooms=2, price=2_000_000,
        external_ref="F1", amenities=json.dumps(["Gym", "Balcony"]))
    _mk(db, location="Business Bay", bedrooms=1, price=1_200_000,
        external_ref="F2", amenities=json.dumps(["Gym"]))
    _mk(db, location="Dubai Marina", bedrooms=2, price=1_900_000,
        external_ref="F3", amenities=json.dumps(["Gym", "Balcony"]))

    res = search_property_records(
        db, purpose="sale", location="business bay", min_bedrooms=2,
        max_price=2_500_000, amenities=["balcony"], currency="aed",
    )
    assert {p.external_ref for p in res["results"]} == {"F1"}


def test_string_price_bounds_accept_indian_grouping(db):
    _mk(db, location="Priceville (test)", price=6_500_000, external_ref="P1")
    res = search_property_records(db, purpose="sale",
                                  location="Priceville (test)",
                                  min_price="65,00,000",
                                  max_price="70,00,000")
    assert {p.external_ref for p in res["results"]} == {"P1"}
    with pytest.raises(ValueError):
        search_property_records(db, purpose="sale", min_price="call for price")


def test_pagination_envelope(db):
    loc = "Paginationville (test)"
    for i in range(5):
        _mk(db, location=loc, external_ref=f"PG{i}", price=1_000_000 + i)
    res = search_property_records(db, purpose="sale", location=loc,
                                  limit=2, offset=2)
    assert res["total"] == 5 and len(res["results"]) == 2
    assert [p.price for p in res["results"]] == [1_000_002, 1_000_003]


# ------------------------------------------------------------ price parsing

@pytest.mark.parametrize("raw,expected", [
    ("65,00,000", 6_500_000.0),        # Indian-style grouping
    ("1,250,000", 1_250_000.0),        # western grouping
    ("AED 750,000", 750_000.0),
    ("750,000 AED", 750_000.0),
    ("AED. 900,000", 900_000.0),
    ("USD 1,250,000", 1_250_000.0),
    ("2000000", 2_000_000.0),
    (1_500_000, 1_500_000.0),
    (1_500_000.5, 1_500_000.5),
    (0, 0.0),
    ("AED 1,150,000.75", 1_150_000.75),
])
def test_parse_price_valid(raw, expected):
    assert parse_price(raw) == expected


@pytest.mark.parametrize("raw", [
    None, "", "call for price", "on request", -5, "N/A", "price: AED", ".",
])
def test_parse_price_invalid_returns_none(raw):
    assert parse_price(raw) is None


# ------------------------------------------------- JSON dataset regression

@pytest.mark.skipif(not DATASET_JSON.exists(), reason="dataset json not present")
def test_existing_json_search_behavior_preserved(db):
    out = search_properties(db, location="Dubai Marina", limit=5)
    assert out["total"] > 0
    assert len(out["results"]) <= 5
    row = out["results"][0]
    # unchanged dataset-row contract used by chat + PropertyDetails page
    for key in ("property_id", "price", "location", "property_type"):
        assert key in row
