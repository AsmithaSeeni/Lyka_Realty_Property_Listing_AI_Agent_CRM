"""Tests for UAE dataset Turso/SQLite import and database-backed browse."""

import pytest
from app.import_dataset_turso import clean_row, TursoClient
from app.database import Property, SessionLocal
from app.services.property_search import dataset_db_record_dict


def test_clean_row_valid():
    raw = {
        "property_id": 101,
        "price": "1,500,000",
        "property_type": "Apartment",
        "no__of__beds": "2",
        "no_of_baths": 2.0,
        "area": "1,200 sqft",
        "highlights": "Luxury Marina View",
        "location": "Dubai Marina, Dubai",
    }
    cleaned = clean_row(raw)
    assert cleaned is not None
    assert cleaned["external_ref"] == "UAE-101"
    assert cleaned["price"] == 1500000.0
    assert cleaned["property_type"] == "Apartment"
    assert cleaned["bedrooms"] == 2
    assert cleaned["bathrooms"] == 2
    assert cleaned["area"] == 1200.0
    assert cleaned["area_unit"] == "sqft"
    assert cleaned["is_approved"] == 0
    assert cleaned["is_demo"] == 0
    assert cleaned["availability"] == "off_market"
    assert cleaned["source"] == "uae_dataset"


def test_clean_row_studio_and_defaults():
    raw = {
        "property_id": 102,
        "price": "600,000",
        "property_type": "Studio",
        "no__of__beds": "Studio",
        "no_of_baths": None,
        "area": "450 sqft",
        "highlights": "Cozy Studio",
        "location": "JVC, Dubai",
    }
    cleaned = clean_row(raw)
    assert cleaned is not None
    assert cleaned["external_ref"] == "UAE-102"
    assert cleaned["bedrooms"] == 0
    assert cleaned["bathrooms"] == 1  # defaulted safely
    assert cleaned["price"] == 600000.0


def test_clean_row_invalid_rejected():
    # missing location
    assert clean_row({"property_id": 1, "price": "500000", "location": ""}) is None
    # unparseable price
    assert clean_row({"property_id": 2, "price": "Call for price", "location": "Dubai"}) is None
    # missing property_id
    assert clean_row({"price": "500000", "location": "Dubai"}) is None


def test_turso_client_url_normalization():
    client1 = TursoClient("libsql://my-db.turso.io", "test-token")
    assert client1.pipeline_url == "https://my-db.turso.io/v2/pipeline"
    assert client1.headers["Authorization"] == "Bearer test-token"

    client2 = TursoClient("https://my-db-org.turso.io?secure=true", "tok-xyz")
    assert client2.pipeline_url == "https://my-db-org.turso.io/v2/pipeline"

    client3 = TursoClient("sqlite+libsql://another-db.turso.io", "tok-abc")
    assert client3.pipeline_url == "https://another-db.turso.io/v2/pipeline"


def test_dataset_db_record_dict_format():
    prop = Property(
        id=42,
        external_ref="UAE-1234",
        title="Sea View Apartment",
        description="Dataset property description",
        purpose="sale",
        availability="off_market",
        price=2500000.0,
        currency="AED",
        property_type="Apartment",
        location="Downtown Dubai",
        bedrooms=2,
        bathrooms=3,
        area=1400.0,
        area_unit="sqft",
        amenities="[]",
        highlights="Balcony, Full Fountain View",
        is_approved=False,
        is_demo=False,
        source="uae_dataset",
    )
    d = dataset_db_record_dict(prop)
    assert d["id"] == 1234  # parsed from external_ref
    assert d["source"] == "dataset"
    assert d["price"] == 2500000.0
    assert d["currency"] == "AED"
    assert d["purpose"] is None  # honest null
    assert d["availability"] is None  # honest null
    assert d["is_demo"] is False
    assert d["images"] == []


def test_db_backed_dataset_browse_and_detail(client):
    db = SessionLocal()
    try:
        # Seed 2 test dataset rows into DB
        p1 = Property(
            external_ref="UAE-999901",
            title="DB Test Villa",
            description="Dataset test",
            purpose="sale",
            availability="off_market",
            price=3000000.0,
            currency="AED",
            property_type="Villa",
            location="Arabian Ranches, Dubai",
            bedrooms=4,
            bathrooms=4,
            area=3500.0,
            area_unit="sqft",
            amenities="[]",
            highlights="DB Test Villa Highlights",
            is_approved=False,
            is_demo=False,
            source="uae_dataset",
        )
        p2 = Property(
            external_ref="UAE-999902",
            title="DB Test Apartment",
            description="Dataset test",
            purpose="sale",
            availability="off_market",
            price=1200000.0,
            currency="AED",
            property_type="Apartment",
            location="Business Bay, Dubai",
            bedrooms=1,
            bathrooms=2,
            area=850.0,
            area_unit="sqft",
            amenities="[]",
            highlights="DB Test Apartment Highlights",
            is_approved=False,
            is_demo=False,
            source="uae_dataset",
        )
        db.add_all([p1, p2])
        db.commit()

        # Test GET /api/properties/dataset queries DB
        res = client.get("/api/properties/dataset?location=Arabian&limit=10")
        assert res.status_code == 200
        body = res.json()
        assert body["total"] >= 1
        found = [r for r in body["results"] if r["id"] == 999901]
        assert len(found) == 1
        assert found[0]["source"] == "dataset"
        assert found[0]["price"] == 3000000.0
        assert found[0]["purpose"] is None
        assert found[0]["availability"] is None

        # Test GET /api/properties/{property_id} resolves DB row
        det = client.get("/api/properties/999901")
        assert det.status_code == 200
        assert det.json()["property_id"] == 999901
        assert det.json()["property_type"] == "Villa"

        # Test GET /api/properties (verified inventory) excludes unapproved dataset row
        verified = client.get("/api/properties?limit=48")
        assert verified.status_code == 200
        verified_ids = {r["id"] for r in verified.json()["results"]}
        assert p1.id not in verified_ids
        assert p2.id not in verified_ids

    finally:
        # Cleanup test rows
        db.query(Property).filter(
            Property.external_ref.in_(["UAE-999901", "UAE-999902"])
        ).delete(synchronize_session=False)
        db.commit()
        db.close()
