"""Phase 2 — property_crud service: validation, the approval-change gate,
delete/list/pagination. Uses the shared throwaway app DB.
"""

import json
import uuid

import pytest

from app.services.property_crud import (
    create_property,
    delete_property,
    get_property,
    list_properties,
    update_property,
)


def _payload(**kw):
    data = dict(
        title="Fictional CRUD Test Apartment",
        description="synthetic CRUD test row",
        purpose="sale",
        price="AED 900,000",          # string price must be normalised
        property_type="Apartment",
        location="CRUDville (test)",
        bedrooms=1,
        bathrooms=1,
        amenities=["Gym", "pool", "gym"],   # exact-string dedup below
        external_ref=f"CRUD-{uuid.uuid4().hex[:10]}",
    )
    data.update(kw)
    return data


def test_create_property_normalises_fields(db):
    prop = create_property(db, _payload())
    assert prop.id is not None
    assert prop.price == 900_000.0            # "AED 900,000" parsed
    assert prop.currency == "AED"
    assert prop.purpose == "sale"
    assert prop.availability == "available"   # safe default
    assert prop.is_approved is False          # never approved by default
    assert prop.is_demo is False
    assert prop.source == "manual"
    assert json.loads(prop.amenities) == ["Gym", "pool"]  # exact-string dedup


def test_create_property_safe_defaults(db):
    prop = create_property(db, dict(
        title="Minimal Row", purpose="rent", price=50_000,
        property_type="studio", location="CRUDville (test)",
        bedrooms=0, bathrooms=1,
    ))
    assert prop.is_approved is False and prop.is_demo is False
    assert prop.external_ref is None
    assert prop.area_unit == "sqft"
    assert json.loads(prop.amenities) == []


@pytest.mark.parametrize("override,fragment", [
    (dict(title=""), "title"),
    (dict(title=None), "title"),
    (dict(location="  "), "location"),
    (dict(property_type=""), "property_type"),
    (dict(purpose="foreclosure"), "purpose"),
    (dict(availability="maybe"), "availability"),
    (dict(price=-5), "price"),
    (dict(price="call us"), "price"),
    (dict(bedrooms=-1), "bedrooms"),
    (dict(bathrooms=0), "bathrooms"),
    (dict(amenities="{not json"), "amenities"),
    (dict(surprise_field=1), "surprise_field"),
])
def test_create_rejects_invalid_input(db, override, fragment):
    with pytest.raises(ValueError) as excinfo:
        create_property(db, _payload(**override))
    assert fragment in str(excinfo.value)


def test_create_rejects_duplicate_external_ref(db):
    ref = f"CRDUP-{uuid.uuid4().hex[:10]}"
    create_property(db, _payload(external_ref=ref))
    with pytest.raises(ValueError) as excinfo:
        create_property(db, _payload(title="Another", external_ref=ref))
    assert "already exists" in str(excinfo.value)


def test_get_property(db):
    prop = create_property(db, _payload())
    assert get_property(db, prop.id).title == "Fictional CRUD Test Apartment"
    with pytest.raises(ValueError):
        get_property(db, 999_999)


def test_update_property_partial(db):
    prop = create_property(db, _payload())
    updated = update_property(db, prop.id, {"title": "Renamed Row", "price": "1,050,000"})
    assert updated.title == "Renamed Row"
    assert updated.price == 1_050_000.0
    assert updated.purpose == "sale"          # untouched


def test_update_approval_requires_explicit_gate(db):
    prop = create_property(db, _payload())
    with pytest.raises(ValueError) as excinfo:
        update_property(db, prop.id, {"is_approved": True})   # no flag → denied
    assert "not permitted" in str(excinfo.value)
    assert get_property(db, prop.id).is_approved is False

    approved = update_property(
        db, prop.id, {"is_approved": True}, allow_approval_change=True
    )
    assert approved.is_approved is True


def test_update_cannot_rewrite_demo_provenance(db):
    prop = create_property(db, _payload())
    with pytest.raises(ValueError) as excinfo:
        update_property(db, prop.id, {"is_demo": True})
    assert "is_demo" in str(excinfo.value)


def test_delete_property(db):
    prop = create_property(db, _payload())
    delete_property(db, prop.id)
    with pytest.raises(ValueError):
        get_property(db, prop.id)


def test_list_properties_filters_and_pagination(db):
    loc = "CRUDlistville (test)"   # own location: shared DB has other rows
    create_property(db, _payload(external_ref="L-1", location=loc, price=900_000))
    create_property(db, _payload(external_ref="L-2", location=loc, purpose="rent",
                                 price=80_000, title="Rentable Row"))
    create_property(db, _payload(external_ref="L-3", location=loc, purpose="lease",
                                 price=95_000, is_approved=True,
                                 title="Leasable Row"))

    rows, total = list_properties(db, location=loc, purpose="sale")
    assert total == 1 and rows[0].external_ref == "L-1"

    rows, total = list_properties(db, location=loc, approved=True)
    assert {r.external_ref for r in rows} == {"L-3"}

    rows, total = list_properties(db, location=loc,
                                  sort="price_asc", limit=2)
    assert total == 3
    assert [r.external_ref for r in rows] == ["L-2", "L-3"]

    rows, total = list_properties(db, location=loc, q="rentable")
    assert total == 1 and rows[0].external_ref == "L-2"

    with pytest.raises(ValueError):
        list_properties(db, sort="chaos")
    with pytest.raises(ValueError):
        list_properties(db, purpose="foreclosure")
