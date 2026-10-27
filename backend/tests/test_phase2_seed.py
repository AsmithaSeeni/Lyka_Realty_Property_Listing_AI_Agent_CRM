"""Phase 2 — demo property seeding: fictional, idempotent, well-distributed,
and never touching customer data. Uses dedicated throwaway DBs.
"""

import json

import pytest
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker

from app.database import Agent, Customer, Lead, Property
from app.seed_demo_properties import (
    DEMO_COMMUNITIES,
    DEMO_PROPERTIES,
    seed_demo_properties,
)


@pytest.fixture()
def seed_engine(tmp_path):
    url = f"sqlite:///{(tmp_path / 'seed.db').as_posix()}"
    return create_engine(url, connect_args={"check_same_thread": False})


def _count(engine, model, **filters):
    Session = sessionmaker(bind=engine)
    db = Session()
    try:
        q = db.query(func.count(model.id))
        for key, value in filters.items():
            q = q.filter(getattr(model, key) == value)
        return q.scalar() or 0
    finally:
        db.close()


def test_seed_definition_meets_requirements():
    # module-level sanity: the dataset itself (before any DB) obeys the spec
    assert len(DEMO_PROPERTIES) >= 20
    assert {r["location"] for r in DEMO_PROPERTIES} == set(DEMO_COMMUNITIES)
    purposes = {r["purpose"] for r in DEMO_PROPERTIES}
    assert {"sale", "rent"} <= purposes
    assert all(r["is_demo"] is True for r in DEMO_PROPERTIES)
    assert all(r["currency"] == "AED" and r["price"] > 0 for r in DEMO_PROPERTIES)
    assert all("Fictional Demo" in r["title"] for r in DEMO_PROPERTIES)
    assert all("FICTIONAL DEMO LISTING" in r["description"] for r in DEMO_PROPERTIES)
    refs = [r["external_ref"] for r in DEMO_PROPERTIES]
    assert len(refs) == len(set(refs)), "external_refs must be unique"
    assert all(r["availability"] in
               ("available", "sold", "rented", "reserved", "off_market")
               for r in DEMO_PROPERTIES)


def test_seed_creates_20_plus_across_five_communities(seed_engine):
    summary = seed_demo_properties(engine_=seed_engine)
    assert summary["created"] == len(DEMO_PROPERTIES) >= 20
    assert summary["skipped"] == 0

    rows = _count(seed_engine, Property)
    assert rows == len(DEMO_PROPERTIES)
    for community in DEMO_COMMUNITIES:
        n = _count(seed_engine, Property, location=community)
        assert n >= 4, f"{community} has only {n} demo rows"


def test_seed_records_all_fictional_and_demo_flagged(seed_engine):
    seed_demo_properties(engine_=seed_engine)
    Session = sessionmaker(bind=seed_engine)
    db = Session()
    try:
        rows = db.query(Property).all()
        assert rows
        for row in rows:
            assert row.is_demo is True
            assert row.source == "demo_seed"
            assert "Fictional Demo" in row.title
            assert "FICTIONAL DEMO LISTING" in row.description
            assert row.currency == "AED" and row.price > 0
            amenities = json.loads(row.amenities)
            assert isinstance(amenities, list) and amenities
    finally:
        db.close()


def test_seed_twice_no_duplicates(seed_engine):
    first = seed_demo_properties(engine_=seed_engine)
    second = seed_demo_properties(engine_=seed_engine)
    assert first["created"] == len(DEMO_PROPERTIES)
    assert second["created"] == 0
    assert second["skipped"] == len(DEMO_PROPERTIES)
    assert _count(seed_engine, Property) == len(DEMO_PROPERTIES)
    # external_ref uniqueness holds in the DB itself
    Session = sessionmaker(bind=seed_engine)
    db = Session()
    try:
        refs = [r[0] for r in db.query(Property.external_ref).all()]
        assert len(refs) == len(set(refs))
    finally:
        db.close()


def test_seed_creates_no_customers_leads_or_agents(seed_engine):
    seed_demo_properties(engine_=seed_engine)
    assert _count(seed_engine, Customer) == 0
    assert _count(seed_engine, Lead) == 0
    assert _count(seed_engine, Agent) == 0


def test_seeded_rows_distinguishable_purposes(seed_engine):
    seed_demo_properties(engine_=seed_engine)
    sale = _count(seed_engine, Property, purpose="sale")
    rent = _count(seed_engine, Property, purpose="rent")
    lease = _count(seed_engine, Property, purpose="lease")
    assert sale >= 1 and rent >= 1 and lease >= 1
    assert sale + rent + lease == _count(seed_engine, Property)


def test_reserved_row_excluded_from_eligible_matches(seed_engine):
    seed_demo_properties(engine_=seed_engine)
    from app.services.property_search import search_property_records

    Session = sessionmaker(bind=seed_engine)
    db = Session()
    try:
        # Eligible set: approved + available only.
        eligible = search_property_records(db, purpose="rent", limit=100)
        refs = {p.external_ref for p in eligible["results"]}
        assert "DEMO-JVC-RENT-04" not in refs          # reserved row excluded
        assert eligible["total"] == _count(
            seed_engine, Property, purpose="rent", availability="available",
            is_approved=True,
        )
        # Staff view can still see it explicitly.
        staff = search_property_records(
            db, purpose="rent", availability="reserved", approved_only=False,
        )
        assert {p.external_ref for p in staff["results"]} == {"DEMO-JVC-RENT-04"}
        # A sale query never returns rental rows (and vice versa).
        sale_refs = {p.external_ref for p in
                     search_property_records(db, purpose="sale", limit=100)["results"]}
        assert sale_refs and not (sale_refs & refs)
    finally:
        db.close()


def test_seed_dry_run_writes_nothing(seed_engine):
    summary = seed_demo_properties(engine_=seed_engine, dry_run=True)
    assert summary["dry_run"] is True
    assert summary["created"] == len(DEMO_PROPERTIES)
    assert _count(seed_engine, Property) == 0


def test_seed_table_has_check_constraints_and_indexes(seed_engine):
    seed_demo_properties(engine_=seed_engine)
    import sqlite3
    path = seed_engine.url.database
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        ddl = con.execute(
            "select sql from sqlite_master where name='properties'"
        ).fetchone()[0]
        assert "CHECK" in ddl and "'sale'" in ddl and "'rent'" in ddl and "'lease'" in ddl
        idx = {r[0] for r in con.execute(
            "select name from sqlite_master where type='index'"
        )}
        assert "ix_properties_purpose_availability" in idx
    finally:
        con.close()
