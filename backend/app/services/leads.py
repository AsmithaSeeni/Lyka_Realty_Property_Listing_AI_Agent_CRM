"""Lead persistence used by LykAI (the AI concierge) and the agent CRM.

The AI creates/updates leads through `upsert_lead_from_ai()` — a server-side,
authenticated code path inside the backend. Phase 5 adds the STAFF review
workflow (`create_lead` helpers, duplicate detection, deterministic
re-scoring) behind `POST /api/agent/leads`; there is still NO public
endpoint that can create or modify leads.

Critical rules enforced here:
- NEVER create duplicate leads: match existing records by phone OR email
  (case-insensitive) before inserting; possible duplicates are surfaced to
  the agent for an explicit decision, never auto-merged.
- Reuse the existing conversation and link it to the reused lead.
- Update `last_interaction_at` on every customer touch.
- Unknown values stay None in the DB and are surfaced as "Not provided" —
  data is never invented.
- Scores/priorities are ALWAYS recomputed server-side by deterministic
  code (`app.services.lead_scoring`); client-supplied scores are ignored.

Schema round-trips (no migration; documented in README/Phase 5 report):
- Budget period  → canonical token inside the `budget` display text
                   ("per month" / "per year" / "one-time"), parsed back
                   deterministically. Legacy free text yields None (safe).
- Preferences    → JSON array string inside `requirements`; legacy free
                   text yields an empty list (never guessed).
"""

import json
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from app.ai.lead_extraction import (
    INTENTS,
    LeadExtractionResult,
    compute_clarification_questions,
    compute_missing_fields,
)
from app.services.lead_scoring import LeadScoreResult, score_lead
from app.services.followups import follow_up_summary
from app.database import Lead, Conversation, PropertyRecommendation, NOT_PROVIDED


def _norm(value) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


# ---------------------------------------------------------------- codecs

_BUDGET_PERIOD_TOKEN = {"monthly": "per month", "yearly": "per year",
                        "one_time": "one-time"}


def encode_budget_display(
    currency: Optional[str],
    budget_min: Optional[float],
    budget_max: Optional[float],
    period: Optional[str],
) -> Optional[str]:
    """Deterministic `budget` display string with a round-trippable period.

    e.g. "AED 90,000 – 110,000 per year". Returns None when there is
    nothing to show (budget stays NULL → displayed as "Not provided").
    """
    if budget_min is None and budget_max is None and not currency:
        return None
    parts: List[str] = []
    if currency:
        parts.append(str(currency).upper().strip())
    if budget_min is not None and budget_max is not None:
        parts.append(f"{budget_min:,.0f} – {budget_max:,.0f}")
    elif budget_min is not None:
        parts.append(f"{budget_min:,.0f}+")
    elif budget_max is not None:
        parts.append(f"up to {budget_max:,.0f}")
    token = _BUDGET_PERIOD_TOKEN.get(period or "")
    if token:
        parts.append(token)
    return " ".join(parts)


def parse_budget_period(text: Optional[str]) -> Optional[str]:
    """Read back the canonical period token written by Phase 5.

    Only canonical tokens are recognised — legacy free text (e.g. an old
    AI-written budget) yields None, which matching treats as ambiguous
    rather than guessing.
    """
    lowered = (text or "").lower()
    if "per month" in lowered:
        return "monthly"
    if "per year" in lowered:
        return "yearly"
    if "one-time" in lowered:
        return "one_time"
    return None


def encode_preferences(preferences: Optional[Sequence[str]]) -> str:
    """JSON array string stored in the existing `requirements` column."""
    items = [str(p).strip() for p in (preferences or []) if str(p).strip()]
    return json.dumps(items, ensure_ascii=False)


def get_preferences(lead: Lead) -> List[str]:
    """Preferences from `requirements`; legacy free text → empty list."""
    raw = lead.requirements
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return []
    if isinstance(parsed, list):
        return [str(x) for x in parsed if str(x).strip()]
    return []


def get_amenities(lead: Lead) -> List[str]:
    """Amenities JSON list from `amenities`; unreadable → empty list."""
    if not lead.amenities:
        return []
    try:
        parsed = json.loads(lead.amenities)
    except (ValueError, TypeError):
        return []
    if isinstance(parsed, list):
        return [str(x) for x in parsed if str(x).strip()]
    return []


# --------------------------------------------------- lead → extraction input

def lead_to_extraction(lead: Lead) -> LeadExtractionResult:
    """Map stored Lead columns back to the validated extraction contract.

    Used to (re)score and to run property matching for a saved lead. Never
    invents values: absent data maps to None / empty list / "unknown".
    """
    intent = lead.buy_rent if lead.buy_rent in INTENTS else "unknown"
    return LeadExtractionResult.model_validate({
        "original_enquiry": lead.original_enquiry or "",
        "name": lead.name,
        "phone": lead.phone,
        "email": lead.email,
        "intent": intent,
        "property_type": lead.property_type,
        "location": lead.location,
        "bedrooms": lead.bedrooms,
        "bathrooms": lead.bathrooms,
        "budget_min": lead.budget_min,
        "budget_max": lead.budget_max,
        "budget_currency": lead.budget_currency,
        "budget_period": parse_budget_period(lead.budget),
        "amenities": get_amenities(lead),
        "preferences": get_preferences(lead),
        "timeline": lead.timeline,
        "timeline_days": lead.timeline_days,
    })


def recompute_lead_score(lead: Lead) -> LeadScoreResult:
    """Server-side deterministic (re)score of a Lead row.

    Sets `lead_score`, `priority`, `score_breakdown` and refreshes the
    missing-field / clarification metadata from the CURRENT values.
    Mutates the Lead (the caller commits).
    """
    extraction = lead_to_extraction(lead)
    result = score_lead(extraction)
    lead.lead_score = result.total_score
    lead.priority = result.priority
    lead.score_breakdown = json.dumps(
        [c.model_dump() for c in result.breakdown], ensure_ascii=False)
    missing = compute_missing_fields(extraction)
    questions = compute_clarification_questions(extraction)
    lead.missing_fields = json.dumps(missing, ensure_ascii=False)
    lead.clarification_questions = json.dumps(questions, ensure_ascii=False)
    return result


# ---------------------------------------------------------------- duplicates

def find_duplicate(
    db: Session,
    phone: Optional[str],
    email: Optional[str],
    exclude_lead_id: Optional[int] = None,
) -> Tuple[Optional[Lead], Optional[str]]:
    """Conservative duplicate detection: phone first, then email.

    Name-only similarity never matches (real contact identifiers are the
    only signal). Returns (lead, matched_by) with matched_by one of
    "phone" | "email" | None.
    """
    lead = find_existing_lead(db, phone=phone, email=None,
                              exclude_lead_id=exclude_lead_id)
    if lead is not None:
        return lead, "phone"
    lead = find_existing_lead(db, phone=None, email=email,
                              exclude_lead_id=exclude_lead_id)
    if lead is not None:
        return lead, "email"
    return None, None


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


def _json_or_none(raw):
    """JSON column → Python value; unreadable/absent → None (never guessed)."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def lead_summary(lead: Lead) -> Dict:
    """Row shape for the lead list / dashboard."""
    return {
        "id": lead.id,
        "name": _np(lead.name),
        "phone": _np(lead.phone),
        "email": _np(lead.email),
        "buy_rent": _np(lead.buy_rent),
        "intent": lead.buy_rent if lead.buy_rent in INTENTS else None,
        "location": _np(lead.location),
        "budget": _np(lead.budget),
        "property_type": _np(lead.property_type),
        "bedrooms": lead.bedrooms,
        "bathrooms": lead.bathrooms,
        "status": lead.status or "new",
        # NULL = not scored yet (legacy rows are never fabricated a score)
        "lead_score": lead.lead_score,
        "priority": lead.priority,
        "source": _np(lead.source),
        "assigned_agent_id": lead.assigned_agent_id,
        "assigned_agent_name": lead.assigned_agent.full_name if lead.assigned_agent else None,
        "created_at": _iso(lead.created_at),
        "last_interaction_at": _iso(lead.last_interaction_at or lead.updated_at),
    }


def lead_detail(lead: Lead) -> Dict:
    """Full shape for the lead detail page."""
    follow_ups = sorted(
        (lead.follow_ups or []),
        key=lambda f: (f.due_at or datetime.max, f.id),
    )
    pending = [f for f in follow_ups if not f.is_completed]
    next_follow_up = pending[0] if pending else None
    return {
        **lead_summary(lead),
        "requirements": _np(lead.requirements),
        "investment_purpose": _np(lead.investment_purpose),
        "timeline": _np(lead.timeline),
        "notes": lead.notes or "",
        "updated_at": _iso(lead.updated_at),
        "conversation_ids": [c.id for c in (lead.conversations or [])],
        # ---- Phase 5: structured review fields (stored, never re-extracted)
        "original_enquiry": lead.original_enquiry or "",
        "budget_min": lead.budget_min,
        "budget_max": lead.budget_max,
        "budget_currency": lead.budget_currency,
        "budget_period": parse_budget_period(lead.budget),
        "amenities": get_amenities(lead),
        "preferences": get_preferences(lead),
        "timeline_days": lead.timeline_days,
        "lead_score": lead.lead_score,
        "priority": lead.priority,
        "score_breakdown": _json_or_none(lead.score_breakdown),
        "missing_fields": _json_or_none(lead.missing_fields) or [],
        "clarification_questions": _json_or_none(lead.clarification_questions) or [],
        "extraction_source": lead.extraction_source,
        # ---- Phase 5: follow-ups (from the existing follow_ups table)
        "follow_ups": [follow_up_summary(f) for f in follow_ups],
        "next_follow_up": follow_up_summary(next_follow_up) if next_follow_up else None,
    }
