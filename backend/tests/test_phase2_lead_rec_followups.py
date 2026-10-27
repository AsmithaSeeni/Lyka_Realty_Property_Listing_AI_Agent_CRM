"""Phase 2 — extended Lead model, recommendation history fields, and the
follow_ups table. Uses the shared throwaway app DB (never the live one).
"""

import json
from datetime import datetime

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.database import Agent, FollowUp, Lead, Property, PropertyRecommendation


def test_lead_new_columns_exist_in_schema(db):
    cols = {c["name"] for c in inspect(db.get_bind()).get_columns("leads")}
    for name in [
        "original_enquiry", "budget_min", "budget_max", "budget_currency",
        "amenities", "lead_score", "priority", "score_breakdown",
        "missing_fields", "clarification_questions", "timeline_days",
        "extraction_source",
    ]:
        assert name in cols


def test_lead_old_style_insert_still_works_and_score_stays_null(db):
    """Rows created with only the historical fields must work; score fields
    stay NULL (never fabricated as 0)."""
    lead = Lead(name="Synth Old-Style", phone="+971500000001", status="new")
    db.add(lead)
    db.commit()
    db.refresh(lead)
    assert lead.id is not None
    assert lead.lead_score is None
    assert lead.priority is None
    assert lead.original_enquiry is None
    assert lead.score_breakdown is None
    assert lead.extraction_source is None
    assert lead.timeline_days is None


def test_lead_new_fields_roundtrip(db):
    lead = Lead(
        name="Synth Structured",
        phone="+971500000002",
        status="new",
        original_enquiry="I want a 2BR in Dubai Marina under 3M AED",
        budget_min=2_000_000,
        budget_max=3_000_000,
        budget_currency="AED",
        amenities=json.dumps(["pool", "gym"]),
        lead_score=72,
        priority="high",
        score_breakdown=json.dumps({"budget": 20, "location": 18}),
        missing_fields=json.dumps(["timeline"]),
        clarification_questions=json.dumps(["When are you looking to move?"]),
        timeline_days=60,
        extraction_source="explicit",
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)

    again = db.query(Lead).filter(Lead.id == lead.id).first()
    assert again.budget_min == 2_000_000 and again.budget_max == 3_000_000
    assert again.budget_currency == "AED"
    assert again.lead_score == 72 and again.priority == "high"
    assert json.loads(again.score_breakdown)["budget"] == 20
    assert json.loads(again.missing_fields) == ["timeline"]
    assert json.loads(again.amenities) == ["pool", "gym"]
    assert again.timeline_days == 60
    assert again.extraction_source == "explicit"


def test_recommendation_old_rows_readable_with_null_new_fields(db):
    rec = PropertyRecommendation(
        property_id=999_999,          # dataset-style id (no DB record)
        price="2,000,000",
        property_type="Apartment",
        location="Dubai Marina",
        bedrooms=2,
        bathrooms=2.0,
        area="1,100 sqft",
        highlights="Fictional history row",
        relevance_score=0.42,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    assert rec.id is not None
    assert rec.match_score is None            # no fabricated score for old-style rows
    assert rec.match_reasons is None
    assert rec.match_mismatches is None
    assert rec.property_record_id is None


def test_recommendation_new_fields_and_property_link(db):
    prop = Property(
        title="Fictional Demo - Link Target",
        description="FICTIONAL DEMO LISTING - test target",
        purpose="rent", availability="available",
        price=100_000, currency="AED", property_type="apartment",
        location="Testville Rec", bedrooms=1, bathrooms=1,
        amenities=json.dumps(["Gym"]), is_demo=True, is_approved=True,
        source="demo_seed",
    )
    db.add(prop)
    db.commit()

    rec = PropertyRecommendation(
        property_id=None,
        match_score=81.5,
        match_reasons=json.dumps(["Budget within range", "Marina location"]),
        match_mismatches=json.dumps(["No sea view"]),
        property_record_id=prop.id,
        relevance_score=0.0,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)

    again = db.query(PropertyRecommendation).filter(
        PropertyRecommendation.id == rec.id
    ).first()
    assert again.match_score == 81.5
    assert json.loads(again.match_reasons)[0] == "Budget within range"
    assert json.loads(again.match_mismatches) == ["No sea view"]
    assert again.property_record_id == prop.id
    # logical (service-level) reference resolves
    linked = db.query(Property).filter(
        Property.id == again.property_record_id
    ).first()
    assert linked.title == "Fictional Demo - Link Target"


def test_followup_table_ddl_has_foreign_keys(db):
    import sqlite3
    bind = db.get_bind()
    con = sqlite3.connect(f"file:{bind.url.database}?mode=ro", uri=True)
    try:
        ddl = con.execute(
            "select sql from sqlite_master where name='follow_ups'"
        ).fetchone()[0]
        assert "REFERENCES leads" in ddl
        assert "REFERENCES agents" in ddl
    finally:
        con.close()


def test_followup_persists_with_valid_lead_reference(db):
    lead = Lead(name="Synth Followup Lead", phone="+971500000003", status="new")
    db.add(lead)
    db.commit()

    fu = FollowUp(
        lead_id=lead.id,
        type="call",
        notes="Intro call about Marina shortlist",
        due_at=datetime(2026, 10, 20, 10, 0, 0),
    )
    db.add(fu)
    db.commit()
    db.refresh(fu)

    again = db.query(FollowUp).filter(FollowUp.id == fu.id).first()
    assert again.lead_id == lead.id
    assert again.is_completed is False
    assert again.completed_at is None
    # relationship wiring: lead -> follow_ups
    db.refresh(lead)
    assert any(f.id == fu.id for f in lead.follow_ups)
    assert again.lead.name == "Synth Followup Lead"


def test_followup_assignable_to_seeded_agent(db):
    lead = Lead(name="Synth Agent Lead", phone="+971500000004", status="new")
    db.add(lead)
    db.commit()
    agent = db.query(Agent).filter(
        Agent.email == "admin@lykarealty.ae"
    ).first()
    assert agent is not None, "expected the seeded dev admin agent"

    fu = FollowUp(
        lead_id=lead.id,
        assigned_agent_id=agent.id,
        type="viewing",
        notes="Fictional viewing",
        due_at=datetime(2026, 10, 21, 15, 0, 0),
    )
    db.add(fu)
    db.commit()
    db.refresh(fu)
    assert fu.assigned_agent_id == agent.id
    assert fu.assigned_agent.email == "admin@lykarealty.ae"


def test_followup_completion_flow(db):
    lead = Lead(name="Synth Done Lead", phone="+971500000005", status="new")
    db.add(lead)
    db.commit()
    fu = FollowUp(
        lead_id=lead.id, type="email", notes="sent brochure",
        due_at=datetime(2026, 10, 18, 9, 0, 0),
    )
    db.add(fu)
    db.commit()
    fu.is_completed = True
    fu.completed_at = datetime(2026, 10, 18, 9, 30, 0)
    db.commit()
    again = db.query(FollowUp).filter(FollowUp.id == fu.id).first()
    assert again.is_completed is True and again.completed_at is not None


def test_followup_type_checked(db):
    lead = Lead(name="Synth Check Lead", phone="+971500000006", status="new")
    db.add(lead)
    db.commit()
    with pytest.raises(IntegrityError):
        db.add(FollowUp(
            lead_id=lead.id, type="carrier_pigeon",
            due_at=datetime(2026, 10, 20, 10, 0, 0),
        ))
        db.commit()
    db.rollback()


def test_followup_due_at_required(db):
    lead = Lead(name="Synth Due Lead", phone="+971500000007", status="new")
    db.add(lead)
    db.commit()
    with pytest.raises(IntegrityError):
        db.add(FollowUp(lead_id=lead.id, type="call", due_at=None))
        db.commit()
    db.rollback()


def test_lead_cascade_deletes_followups(db):
    lead = Lead(name="Synth Cascade", phone="+971500000008", status="new")
    db.add(lead)
    db.commit()
    fu = FollowUp(lead_id=lead.id, type="general", notes="x",
                  due_at=datetime(2026, 11, 1, 10, 0, 0))
    db.add(fu)
    db.commit()
    fu_id = fu.id

    db.delete(lead)   # ORM-level cascade removes follow-ups
    db.commit()
    assert db.query(FollowUp).filter(FollowUp.id == fu_id).first() is None
