"""Lead persistence used by LykAI (the AI concierge) and the agent CRM.

The AI creates/updates leads through `upsert_lead_from_ai()` — a server-side,
authenticated code path inside the backend. There is intentionally NO public
HTTP endpoint that can create or modify leads.

Critical rules enforced here:
- NEVER create duplicate leads: match existing records by phone OR email
  (case-insensitive) before inserting.
- Reuse the existing conversation and link it to the reused lead.
- Update `last_interaction_at` on every customer touch.
- Unknown values stay None in the DB and are surfaced as "Not provided" —
  data is never invented.
"""

from datetime import datetime
from typing import Dict, Optional, Tuple

from sqlalchemy.orm import Session

from app.database import Lead, Conversation, PropertyRecommendation, NOT_PROVIDED


def _norm(value) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def find_existing_lead(
    db: Session,
    phone: Optional[str] = None,
    email: Optional[str] = None,
    exclude_lead_id: Optional[int] = None,
) -> Optional[Lead]:
    """Locate a lead by real contact identifiers only.

    Phone: exact match (digits-normalised so '+971 52...' == '97152...').
    Email: case-insensitive match.
    """
    q = db.query(Lead)
    if exclude_lead_id:
        q = q.filter(Lead.id != exclude_lead_id)

    if phone:
        digits = "".join(ch for ch in str(phone) if ch.isdigit())
        if digits:
            from sqlalchemy import func as _func
            candidates = q.filter(Lead.phone.isnot(None)).all()
            for lead in candidates:
                lead_digits = "".join(ch for ch in (lead.phone or "") if ch.isdigit())
                if lead_digits and lead_digits == digits:
                    return lead

    if email:
        target = str(email).strip().lower()
        hit = q.filter(Lead.email.isnot(None)).order_by(Lead.id.desc()).all()
        for lead in hit:
            if (lead.email or "").strip().lower() == target:
                return lead
    return None


def upsert_lead_from_ai(
    db: Session,
    lead_data: Dict,
    conversation: Optional[Conversation] = None,
) -> Tuple[Lead, bool]:
    """Create or update a lead from AI-collected data.

    Returns (lead, created). Missing fields are left as None (displayed as
    "Not provided") rather than being guessed.
    """
    phone = _norm(lead_data.get("phone"))
    email = _norm(lead_data.get("email"))
    now = datetime.utcnow()

    lead = find_existing_lead(db, phone=phone, email=email)
    created = lead is None

    if lead is None:
        lead = Lead(source="AI Assistant")
        db.add(lead)

    # Merge only the fields the AI actually learned — never overwrite with None
    for key, value in lead_data.items():
        if value is None or not hasattr(lead, key):
            continue
        if key in ("phone", "email"):
            value = _norm(value)
            if value is None:
                continue
        setattr(lead, key, value)

    lead.last_interaction_at = now
    lead.updated_at = now
    if lead.source is None:  # backfill pre-migration rows
        lead.source = "AI Assistant"

    # Flush first so a brand-new lead already has an id to link against
    db.flush()

    # Link this conversation to the (possibly reused) lead
    if conversation is not None:
        conversation.lead_id = lead.id
        if not conversation.customer_name and _norm(lead_data.get("name")):
            conversation.customer_name = lead_data["name"]
        if not conversation.customer_phone and phone:
            conversation.customer_phone = phone
        if not conversation.customer_email and email:
            conversation.customer_email = email

    db.flush()

    # Backfill: every property recommended in linked conversations belongs
    # to this lead (Lead -> Property Recommendations)
    if conversation is not None:
        (
            db.query(PropertyRecommendation)
            .filter(
                PropertyRecommendation.conversation_id == conversation.id,
                PropertyRecommendation.lead_id.is_(None),
            )
            .update({"lead_id": lead.id}, synchronize_session=False)
        )
    else:
        linked_conv_ids = [c.id for c in (lead.conversations or [])]
        if linked_conv_ids:
            (
                db.query(PropertyRecommendation)
                .filter(
                    PropertyRecommendation.conversation_id.in_(linked_conv_ids),
                    PropertyRecommendation.lead_id.is_(None),
                )
                .update({"lead_id": lead.id}, synchronize_session=False)
            )

    return lead, created


# ---------------------------------------------------------------- serializers

def _np(value) -> str:
    """Unknown -> "Not provided" (never invent data, never show blank)."""
    if value is None:
        return NOT_PROVIDED
    text = str(value).strip()
    return text or NOT_PROVIDED


def _iso(dt) -> Optional[str]:
    return dt.isoformat() if dt else None


def lead_summary(lead: Lead) -> Dict:
    """Row shape for the lead list / dashboard."""
    return {
        "id": lead.id,
        "name": _np(lead.name),
        "phone": _np(lead.phone),
        "email": _np(lead.email),
        "buy_rent": _np(lead.buy_rent),
        "location": _np(lead.location),
        "budget": _np(lead.budget),
        "property_type": _np(lead.property_type),
        "bedrooms": lead.bedrooms,
        "bathrooms": lead.bathrooms,
        "status": lead.status or "new",
        "source": _np(lead.source),
        "assigned_agent_id": lead.assigned_agent_id,
        "assigned_agent_name": lead.assigned_agent.full_name if lead.assigned_agent else None,
        "created_at": _iso(lead.created_at),
        "last_interaction_at": _iso(lead.last_interaction_at or lead.updated_at),
    }


def lead_detail(lead: Lead) -> Dict:
    """Full shape for the lead detail page."""
    return {
        **lead_summary(lead),
        "requirements": _np(lead.requirements),
        "investment_purpose": _np(lead.investment_purpose),
        "timeline": _np(lead.timeline),
        "notes": lead.notes or "",
        "updated_at": _iso(lead.updated_at),
        "conversation_ids": [c.id for c in (lead.conversations or [])],
    }
