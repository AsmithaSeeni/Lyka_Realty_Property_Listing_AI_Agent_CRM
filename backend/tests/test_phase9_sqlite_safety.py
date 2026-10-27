"""Phase 9 — SQLite connection safety, integrity enforcement, regression tests.

Everything runs on the throwaway conftest database or on private temporary
engines/databases; `backend\\real_estate.db` is never opened for writing here.

Covers (per the Phase 9 brief):
1. foreign_keys=ON on every newly opened SQLite connection,
2. invalid FK references rejected by the database,
3. legal nullable relationships unaffected (legacy NULL rows, unassigned leads),
4. test/app databases receive the full connection contract,
5. busy-timeout configuration (applied + configurable),
6. WAL verified on a temp database (+ configurability + invalid-value fallback),
7. migrations/init_db compatibility under enforcement (idempotent, twice),
8-10. customer/lead/saved/recommendation workflows, both id spaces, and the
      eligibility + demo-honesty AI guards still behave identically.
"""

import itertools
from datetime import datetime

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import IntegrityError

ADMIN_EMAIL = "admin@lykarealty.ae"
ADMIN_PASS = "Admin@123"

_seq = itertools.count(9100)


def _loc() -> str:
    return f"P9 Loc {next(_seq)}"


def _make_record(db, loc, *, approved=True, availability="available",
                 demo=False, purpose="sale", price=1_400_000):
    from app.database import Property

    prop = Property(
        title=f"P9 Listing {next(_seq)}",
        description=("FICTIONAL DEMO LISTING — synthetic demo data."
                     if demo else "A quiet test listing."),
        purpose=purpose, availability=availability, price=price,
        currency="AED", property_type="villa", location=loc,
        bedrooms=3, bathrooms=2, area=2000.0, area_unit="sqft",
        amenities='["pool"]', highlights="quiet",
        is_approved=approved, is_demo=demo,
        source="demo_seed" if demo else "manual",
    )
    db.add(prop)
    db.commit()
    db.refresh(prop)
    return prop


def _private_engine(tmp_path, name="p9.db"):
    """Engine on a private temp database with the Phase 9 connection contract
    applied — mirrors how the app engine is configured."""
    from app.database import apply_sqlite_pragmas

    url = "sqlite:///" + (tmp_path / name).as_posix()
    eng = create_engine(url, connect_args={"check_same_thread": False})
    event.listen(
        eng, "connect",
        lambda dbapi_conn, _rec: apply_sqlite_pragmas(dbapi_conn),
    )
    return eng


def _pragma(eng, name):
    with eng.connect() as conn:
        return conn.execute(text(f"PRAGMA {name}")).scalar()


# =====================================================================
# 1 + 4. FK enforcement & configuration on every new connection
# =====================================================================

def test_foreign_keys_enforced_on_every_new_app_connection(app_module):
    from app.database import engine, SessionLocal

    # Three fresh DBAPI connections (dispose() empties the pool each time so
    # each iteration truly opens a new underlying connection).
    for _ in range(3):
        conn = engine.connect()
        try:
            assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
        finally:
            conn.close()
            engine.dispose()

    # And the session factory used by fixtures/requests carries the contract.
    session = SessionLocal()
    try:
        assert session.execute(text("PRAGMA foreign_keys")).scalar() == 1
    finally:
        session.close()


def test_test_database_has_full_connection_contract(app_module, db):
    from app import config as config_mod
    from app.database import engine

    assert db.execute(text("PRAGMA foreign_keys")).scalar() == 1
    expected_busy = int(config_mod.settings.SQLITE_BUSY_TIMEOUT_SECONDS * 1000)
    assert db.execute(text("PRAGMA busy_timeout")).scalar() == expected_busy
    # Default journal mode is WAL; the conftest temp database is a normal
    # file, so the mode applies and persists there only.
    assert _pragma(engine, "journal_mode") == "wal"


# =====================================================================
# 2. Invalid foreign keys now fail at the database level
# =====================================================================

def test_invalid_conversation_customer_reference_fails(app_module, db):
    from app.database import Conversation

    db.add(Conversation(customer_name="P9 Ghost", customer_id=987_654_321))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_invalid_followup_references_fail(app_module, db):
    from app.database import FollowUp

    db.add(FollowUp(lead_id=987_654_321, type="call", notes="x",
                    due_at=datetime(2031, 1, 5, 10, 0, 0)))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_invalid_saved_property_customer_reference_fails(app_module, db):
    from app.database import SavedProperty

    db.add(SavedProperty(customer_id=987_654_321, property_id=1))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_invalid_recommendation_lead_reference_fails(app_module, db):
    from app.database import PropertyRecommendation

    db.add(PropertyRecommendation(
        conversation_id=None, lead_id=987_654_321, property_id=1,
        price="100", property_type="villa", location="P9",
        bedrooms=1, bathrooms=1.0, area="", highlights="",
    ))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


# =====================================================================
# 3. Legal nullable relationships keep working
# =====================================================================

def test_nullable_relationships_remain_legal(app_module, db):
    from app.database import Conversation, Lead, PropertyRecommendation

    # Legacy-shape conversation: no customer (pre-migration rows look like this)
    conv = Conversation(customer_name="P9 Legacy")
    db.add(conv)
    # Unassigned lead
    lead = Lead(name="P9 Unassigned", phone="+971509990009", status="new")
    db.add(lead)
    db.commit()
    db.refresh(conv)
    db.refresh(lead)
    assert conv.customer_id is None
    assert lead.assigned_agent_id is None

    # Recommendation tied to a conversation but not to a lead (chat-era shape)
    rec = PropertyRecommendation(
        conversation_id=conv.id, lead_id=None, property_id=4242,
        price="500", property_type="studio", location="P9",
        bedrooms=0, bathrooms=1.0, area="", highlights="",
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    assert rec.id is not None


# =====================================================================
# 5 + 6. Busy timeout and WAL — applied, configurable, validated
# =====================================================================

def test_busy_timeout_applied_and_configurable(app_module, tmp_path, monkeypatch):
    from app import config as config_mod

    eng = _private_engine(tmp_path, "busy.db")
    try:
        assert _pragma(eng, "busy_timeout") == int(
            config_mod.settings.SQLITE_BUSY_TIMEOUT_SECONDS * 1000)
    finally:
        eng.dispose()

    monkeypatch.setattr(config_mod.settings, "SQLITE_BUSY_TIMEOUT_SECONDS", 2.5)
    eng2 = _private_engine(tmp_path, "busy2.db")
    try:
        assert _pragma(eng2, "busy_timeout") == 2500
    finally:
        eng2.dispose()


def test_wal_applied_on_temp_database(app_module, tmp_path):
    eng = _private_engine(tmp_path, "wal.db")
    try:
        assert _pragma(eng, "journal_mode") == "wal"
        # and it persists for subsequently opened connections of the file
        assert _pragma(eng, "journal_mode") == "wal"
    finally:
        eng.dispose()


def test_journal_mode_configurable_and_invalid_values_ignored(
        app_module, tmp_path, monkeypatch):
    from app import config as config_mod

    monkeypatch.setattr(config_mod.settings, "SQLITE_JOURNAL_MODE", "delete")
    eng = _private_engine(tmp_path, "del.db")
    try:
        assert _pragma(eng, "journal_mode") == "delete"
    finally:
        eng.dispose()

    # Unknown values must NOT be executed — SQLite keeps its default.
    monkeypatch.setattr(config_mod.settings, "SQLITE_JOURNAL_MODE", "bogus;drop")
    eng2 = _private_engine(tmp_path, "bogus.db")
    try:
        assert _pragma(eng2, "journal_mode") == "delete"
    finally:
        eng2.dispose()


def test_durable_synchronous_untouched(app_module, db):
    """Phase 9 must not weaken durability: synchronous stays FULL (2)."""
    assert db.execute(text("PRAGMA synchronous")).scalar() == 2


# =====================================================================
# 7. Migrations + startup init remain compatible under enforcement
# =====================================================================

def test_migrations_idempotent_under_fk_enforcement(tmp_path):
    from app.database import Base, _run_migrations, _ensure_indexes

    eng = _private_engine(tmp_path, "mig.db")
    try:
        for run in (1, 2):  # twice — must stay idempotent with FK ON
            Base.metadata.create_all(bind=eng)
            _run_migrations(target_engine=eng)
            _ensure_indexes(target_engine=eng)
            assert _pragma(eng, "foreign_keys") == 1, f"run {run}"
        # schema is referentially clean after migrating under enforcement
        with eng.connect() as conn:
            assert conn.execute(text("PRAGMA foreign_key_check")).fetchall() == []
    finally:
        eng.dispose()


# =====================================================================
# 8-10. Workflows + both id spaces + AI guards under enforcement
# =====================================================================

class _FakeState:
    def __init__(self):
        self.contact = {}
        self.recommended_properties = []

    def add_message(self, *args, **kwargs):
        pass


class _FakeAgent:
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
            "response": "P9 fake reply.",
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


def test_workflows_both_spaces_and_guards_under_enforcement(
        app_module, client, db, fake_agent):
    from app.ai.agent import AIRealEstateAgent
    from app.database import Lead
    from app.services.property_search import record_focus_dict

    leads_before = db.query(Lead).count()
    loc = _loc()
    demo = _make_record(db, loc, demo=True)
    unapproved = _make_record(db, loc, approved=False)

    # --- public eligibility unchanged (approved+available only) ---
    listing = client.get("/api/properties", params={"location": loc}).json()
    assert listing["total"] == 1 and listing["results"][0]["id"] == demo.id
    assert client.get(f"/api/properties/record/{demo.id}").status_code == 200
    assert client.get(f"/api/properties/record/{unapproved.id}").status_code == 404

    # --- chat focus + AI demo-honesty guard unchanged ---
    chat = client.post("/api/chat", json={
        "message": "Tell me about this listing",
        "property_id": demo.id, "property_source": "record"})
    assert chat.status_code == 200
    assert fake_agent.last_focus["property_id"] == demo.id
    ctx = AIRealEstateAgent()._context_block(
        focus_property=record_focus_dict(demo))
    assert "FICTIONAL DEMO" in ctx

    # --- customer save/unsave in BOTH id spaces under FK enforcement ---
    email = f"p9.{next(_seq)}@example.com"
    r = client.post("/api/customer/register", json={
        "email": email, "password": "Synth-Pass-9!",
        "confirm_password": "Synth-Pass-9!", "name": "P9 Synthetic"})
    assert r.status_code == 200, r.text

    assert client.post("/api/customer/saved", json={
        "property_id": demo.id, "source": "record"}).status_code == 200
    assert client.post("/api/customer/saved", json={
        "property_id": 1, "source": "dataset"}).status_code == 200
    saved = client.get("/api/customer/saved").json()
    assert saved["total"] == 2
    assert {row["source"] for row in saved["results"]} == {"record", "dataset"}

    assert client.delete(
        f"/api/customer/saved/{demo.id}?source=record").status_code == 200
    assert client.delete(
        "/api/customer/saved/1?source=dataset").status_code == 200
    assert client.get("/api/customer/saved").json()["total"] == 0

    # --- lead workflow (valid-FK path) under enforcement ---
    staff = client.post("/api/auth/login", json={
        "username": ADMIN_EMAIL, "password": ADMIN_PASS})
    assert staff.status_code == 200
    hdr = {"Authorization": f"Bearer {staff.json()['token']}"}
    n = next(_seq)
    lead = client.post("/api/agent/leads", headers=hdr, json={
        "name": "P9 Lead", "phone": f"+9715{n}", "email": f"p9.lead.{n}@example.com",
        "intent": "buy", "property_type": "villa", "location": loc,
        "bedrooms": 3, "bathrooms": 2, "budget_min": 1_000_000,
        "budget_max": 2_000_000, "budget_currency": "AED",
        "budget_period": "one_time", "timeline_days": 30, "confirm": True})
    assert lead.status_code == 200, lead.text
    assert client.get("/api/agent/dashboard", headers=hdr).status_code == 200

    # browsing/chat/CRM activity created no leads by itself
    db.expire_all()
    assert db.query(Lead).count() == leads_before + 1
