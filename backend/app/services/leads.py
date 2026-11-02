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
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from app.ai.lead_extraction import (
    INTENTS,
    LeadExtractionResult,
    compute_clarification_questions,
    compute_missing_fields,
)
from app.services.lead_scoring import LeadScoreResult, score_lead
from app.services.followups import follow_up_summary
from app.services.lead_temperature import apply_temperature, parse_rationale
from app.database import (
    Agent,
    AuditLog,
    Lead,
    Conversation,
    PropertyRecommendation,
    FollowUp,
    Appointment,
    Offer,
    Deal,
    NOT_PROVIDED,
)


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


# ------------------------------------------------ lifecycle & transitions

LEAD_STATUSES = (
    "new",
    "contact_pending",
    "contacted",
    "qualified",
    "viewing",
    "negotiation",
    "closed_won",
    "closed_lost",
    "nurturing",
)

STATUS_ALIASES = {
    "viewing_scheduled": "viewing",
    "won": "closed_won",
    "lost": "closed_lost",
}

TERMINAL_LEAD_STATUSES = frozenset({"closed_won", "closed_lost"})

ACTIVE_LEAD_STATUSES = frozenset(set(LEAD_STATUSES) - TERMINAL_LEAD_STATUSES)

ALLOWED_STATUS_TRANSITIONS = {
    "new": {
        "new", "contact_pending", "contacted", "qualified",
        "viewing", "negotiation", "nurturing", "closed_lost",
    },
    "contact_pending": {
        "new", "contact_pending", "contacted", "qualified",
        "viewing", "negotiation", "nurturing", "closed_lost",
    },
    "contacted": {
        "new", "contact_pending", "contacted", "qualified",
        "viewing", "negotiation", "nurturing", "closed_won", "closed_lost",
    },
    "qualified": {
        "contact_pending", "contacted", "qualified",
        "viewing", "negotiation", "nurturing", "closed_won", "closed_lost",
    },
    "viewing": {
        "contacted", "qualified", "viewing",
        "negotiation", "nurturing", "closed_won", "closed_lost",
    },
    "negotiation": {
        "contacted", "qualified", "viewing",
        "negotiation", "nurturing", "closed_won", "closed_lost",
    },
    "nurturing": {
        "new", "contact_pending", "contacted", "qualified",
        "viewing", "negotiation", "nurturing", "closed_lost",
    },
    "closed_won": {"closed_won"},
    "closed_lost": {"closed_lost"},
}


def normalize_lead_status(raw: Optional[str]) -> Optional[str]:
    """Normalize status string (supporting explicit stage aliases)."""
    if raw is None:
        return None
    key = str(raw).strip().lower()
    key = STATUS_ALIASES.get(key, key)
    return key if key in LEAD_STATUSES else None


def allowed_next_statuses(current_status: Optional[str]) -> List[str]:
    """Ordered list of valid next statuses without forced reopen."""
    curr = normalize_lead_status(current_status) or "new"
    allowed = ALLOWED_STATUS_TRANSITIONS.get(curr, set(LEAD_STATUSES))
    return [s for s in LEAD_STATUSES if s in allowed]


def validate_status_transition(
    current_status: Optional[str],
    target_status: str,
    *,
    reopen: bool = False,
) -> str:
    """Validate a lead status transition.

    - Rejects unknown statuses.
    - Blocks transitions out of terminal stages (`closed_won`, `closed_lost`)
      unless `reopen=True` is explicitly passed.
    - Blocks jumping directly from `new`, `contact_pending`, or `nurturing`
      to `closed_won` without qualification/contact.
    """
    target = normalize_lead_status(target_status)
    if target is None:
        raise ValueError(
            f"Invalid status {target_status!r}. Allowed: {', '.join(LEAD_STATUSES)}"
        )
    current = normalize_lead_status(current_status) or "new"
    if current == target:
        return target

    if current in TERMINAL_LEAD_STATUSES:
        if not reopen:
            raise ValueError(
                f"Lead is in terminal status '{current}'; explicit reopen "
                f"(reopen=true) is required to transition to '{target}'"
            )
        if target in TERMINAL_LEAD_STATUSES:
            raise ValueError(
                "Reopening a closed lead must transition to an active pipeline stage"
            )
        return target

    allowed = ALLOWED_STATUS_TRANSITIONS.get(current, set())
    if target not in allowed:
        raise ValueError(
            f"Invalid status transition from '{current}' to '{target}'. "
            f"Allowed from '{current}': {', '.join(allowed_next_statuses(current))}"
        )
    return target


# ------------------------------------------- preferences & qualification

QUALIFICATION_META_KEYS = (
    "preferred_language",
    "emirate",
    "financing_type",
    "preferred_viewing_time",
    "qualification_status",
    "next_action",
    "field_provenance",
    "idempotency_key",
)

VALID_FINANCING_TYPES = ("cash", "mortgage", "payment_plan", "undecided")
VALID_USAGE_INTENTS = ("investment", "personal_use", "self_use", "holiday_home", "undecided")
VALID_QUALIFICATION_STATUSES = ("unqualified", "partially_qualified", "qualified", "disqualified")


def encode_preferences(
    preferences: Optional[Sequence[str]],
    qualification_meta: Optional[Dict[str, Any]] = None,
) -> str:
    """JSON string stored in the existing `requirements` column.

    Backward compatible:
    - When `qualification_meta` is empty/None, stores a plain JSON array
      `["pool", "sea view"]` identical to Phase 5.
    - When `qualification_meta` carries structured UAE qualification fields,
      stores `{"preferences": [...], "qualification": {...}}`.
    """
    items = [str(p).strip() for p in (preferences or []) if str(p).strip()]
    clean_meta = {}
    if isinstance(qualification_meta, dict):
        for k, v in qualification_meta.items():
            if k in QUALIFICATION_META_KEYS and v not in (None, "", {}, []):
                clean_meta[k] = v
    if not clean_meta:
        return json.dumps(items, ensure_ascii=False)
    return json.dumps(
        {"preferences": items, "qualification": clean_meta},
        ensure_ascii=False,
    )


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
    if isinstance(parsed, dict):
        prefs = parsed.get("preferences") or []
        if isinstance(prefs, list):
            return [str(x) for x in prefs if str(x).strip()]
    return []


def get_qualification_meta(lead: Lead) -> Dict[str, Any]:
    """Structured UAE qualification metadata stored alongside preferences."""
    raw = lead.requirements
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    if isinstance(parsed, dict):
        q = parsed.get("qualification")
        if isinstance(q, dict):
            return dict(q)
    return {}


def qualification_completeness(lead: Lead) -> Dict[str, Any]:
    """Compute deterministic UAE real-estate qualification completeness.

    Distinguishes confirmed customer information from inferred/AI-suggested
    fields and reports exactly which qualification fields remain unknown.
    """
    meta = get_qualification_meta(lead)
    prov = meta.get("field_provenance") if isinstance(meta.get("field_provenance"), dict) else {}

    checklist = {
        "name": bool(_norm(lead.name)),
        "contact": bool(_norm(lead.phone) or _norm(lead.email)),
        "intent": bool(lead.buy_rent in ("buy", "rent", "lease")),
        "location": bool(_norm(lead.location) or _norm(meta.get("emirate"))),
        "property_type": bool(_norm(lead.property_type)),
        "bedrooms": lead.bedrooms is not None,
        "budget": (lead.budget_min is not None or lead.budget_max is not None or bool(_norm(lead.budget))),
        "timeline": (lead.timeline_days is not None or bool(_norm(lead.timeline))),
        "investment_purpose": bool(_norm(lead.investment_purpose)),
        "financing_type": bool(_norm(meta.get("financing_type"))),
    }

    total_count = len(checklist)
    completed_count = sum(1 for ok in checklist.values() if ok)
    pct = int(round((completed_count / total_count) * 100)) if total_count else 0

    missing_items = [field for field, ok in checklist.items() if not ok]

    confirmed_fields: List[str] = []
    inferred_fields: List[str] = []
    default_source = (lead.extraction_source or "").strip().lower()

    for field, present in checklist.items():
        if not present:
            continue
        field_prov = str(prov.get(field) or "").strip().lower()
        if field_prov in ("inferred", "ai_suggested"):
            inferred_fields.append(field)
        elif field_prov in ("explicit", "confirmed"):
            confirmed_fields.append(field)
        elif default_source in ("inferred", "chat_regex"):
            inferred_fields.append(field)
        else:
            confirmed_fields.append(field)

    explicit_status = meta.get("qualification_status")
    if explicit_status in VALID_QUALIFICATION_STATUSES:
        q_status = explicit_status
    elif lead.status in ("qualified", "viewing", "negotiation", "closed_won"):
        q_status = "qualified"
    elif pct >= 70:
        q_status = "qualified"
    elif pct >= 40:
        q_status = "partially_qualified"
    else:
        q_status = "unqualified"

    return {
        "completeness_pct": pct,
        "completed_count": completed_count,
        "total_count": total_count,
        "status": q_status,
        "confirmed_fields": confirmed_fields,
        "inferred_fields": inferred_fields,
        "missing_fields": missing_items,
        "checklist": checklist,
    }


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


def find_all_duplicates(
    db: Session,
    phone: Optional[str] = None,
    email: Optional[str] = None,
    exclude_lead_id: Optional[int] = None,
) -> List[Tuple[Lead, str]]:
    """Return all existing leads matching normalized phone or email.

    Never matches on customer name alone. Returns list of (Lead, matched_by).
    """
    q = db.query(Lead)
    if exclude_lead_id:
        q = q.filter(Lead.id != exclude_lead_id)

    matches: Dict[int, Tuple[Lead, str]] = {}
    if phone:
        digits = "".join(ch for ch in str(phone) if ch.isdigit())
        if digits:
            for cand in q.filter(Lead.phone.isnot(None)).order_by(Lead.id.desc()).all():
                cand_digits = "".join(ch for ch in (cand.phone or "") if ch.isdigit())
                if cand_digits and cand_digits == digits:
                    matches[cand.id] = (cand, "phone")

    if email:
        target = str(email).strip().lower()
        if target:
            for cand in q.filter(Lead.email.isnot(None)).order_by(Lead.id.desc()).all():
                if (cand.email or "").strip().lower() == target and cand.id not in matches:
                    matches[cand.id] = (cand, "email")

    return list(matches.values())


def find_lead_by_idempotency_key(db: Session, key: Optional[str]) -> Optional[Lead]:
    """Locate an already-created lead carrying the given idempotency_key."""
    norm_key = _norm(key)
    if not norm_key:
        return None
    needle = f'%"idempotency_key": "{norm_key}"%'
    candidates = db.query(Lead).filter(Lead.requirements.like(needle)).all()
    for cand in candidates:
        meta = get_qualification_meta(cand)
        if meta.get("idempotency_key") == norm_key:
            return cand
    return None


# -------------------------------------------- assignment & round-robin

_ROUND_ROBIN_LOCK = threading.Lock()


def list_eligible_sales_agents(db: Session) -> List[Agent]:
    """Return active sales agents eligible for lead assignment.

    Only active accounts (`is_active=True`) with primary role `'agent'`
    (sales_agent) are included in the sales round-robin rotation; suspended
    or inactive accounts are strictly excluded.
    """
    return (
        db.query(Agent)
        .filter(Agent.is_active.is_(True), Agent.role == "agent")
        .order_by(Agent.id.asc())
        .all()
    )


def assign_lead_round_robin(db: Session, lead: Lead) -> Agent:
    """Concurrency-safe circular round-robin assignment across active sales agents.

    Uses an in-process mutex + row-level `FOR UPDATE` locking on the eligible
    agents query, then inspects the most recent round-robin assignment in
    `AuditLog` (or last assigned lead) to advance deterministically to the
    next active sales agent in ID order.
    """
    with _ROUND_ROBIN_LOCK:
        eligible = (
            db.query(Agent)
            .filter(Agent.is_active.is_(True), Agent.role == "agent")
            .order_by(Agent.id.asc())
            .with_for_update()
            .all()
        )
        if not eligible:
            raise ValueError("No active sales agents available for round-robin assignment")

        eligible_ids = [a.id for a in eligible]

        last_rr_audit = (
            db.query(AuditLog)
            .filter(AuditLog.event == "lead.assigned.round_robin")
            .order_by(AuditLog.id.desc())
            .first()
        )
        last_agent_id: Optional[int] = None
        if last_rr_audit and last_rr_audit.detail:
            for part in last_rr_audit.detail.split(";"):
                part = part.strip()
                if part.startswith("to="):
                    val = part.split("=", 1)[1].strip()
                    if val.isdigit():
                        last_agent_id = int(val)
                        break

        if last_agent_id is None:
            last_assigned_lead = (
                db.query(Lead)
                .filter(
                    Lead.assigned_agent_id.in_(eligible_ids),
                    Lead.id != (lead.id or 0),
                )
                .order_by(Lead.updated_at.desc(), Lead.id.desc())
                .first()
            )
            if last_assigned_lead is not None:
                last_agent_id = last_assigned_lead.assigned_agent_id

        if last_agent_id is None:
            chosen = eligible[0]
        else:
            higher = [a for a in eligible if a.id > last_agent_id]
            chosen = higher[0] if higher else eligible[0]

        lead.assigned_agent_id = chosen.id
        lead.updated_at = datetime.utcnow()
        db.add(lead)
        db.flush()
        return chosen


def merge_duplicate_leads(
    db: Session,
    *,
    target: Lead,
    source: Lead,
    actor_label: str = "staff",
    reason: Optional[str] = None,
) -> Lead:
    """Authorized transactional merge of `source` duplicate lead into `target`.

    - Never overwrites non-empty confirmed fields on `target`.
    - Fills missing qualification/contact fields on `target` from `source`.
    - Appends `source` enquiry and notes into `target.notes` with explicit
      provenance so no enquiry text or staff notes are lost.
    - Re-parents conversations, follow-ups, and deduplicated property
      recommendations from `source` to `target`.
    - Re-parents audit history for `source` to `target` and deletes `source`.
    """
    if target.id == source.id:
        raise ValueError("Cannot merge a lead into itself")

    for col in (
        "name", "phone", "email", "buy_rent", "location", "budget",
        "property_type", "bedrooms", "bathrooms", "investment_purpose",
        "timeline", "timeline_days", "original_enquiry", "budget_min",
        "budget_max", "budget_currency", "assigned_agent_id",
        "summary", "last_customer_message", "temperature",
        "temperature_rationale", "temperature_source", "temperature_updated_at",
    ):
        t_val = getattr(target, col, None)
        s_val = getattr(source, col, None)
        if (t_val in (None, "") or (col == "buy_rent" and t_val == "unknown")) and s_val not in (None, ""):
            setattr(target, col, s_val)

    # Merge amenities (preserve order, deduplicate)
    merged_amenities = list(dict.fromkeys(get_amenities(target) + get_amenities(source)))
    if merged_amenities:
        target.amenities = json.dumps(merged_amenities, ensure_ascii=False)

    # Merge preferences & qualification metadata
    merged_prefs = list(dict.fromkeys(get_preferences(target) + get_preferences(source)))
    t_meta = get_qualification_meta(target)
    s_meta = get_qualification_meta(source)
    merged_meta = dict(s_meta)
    merged_meta.update({k: v for k, v in t_meta.items() if v not in (None, "", {}, [])})
    if merged_prefs or merged_meta:
        target.requirements = encode_preferences(merged_prefs, merged_meta)

    # Preserve source enquiry & notes in target.notes
    merge_notes_parts: List[str] = []
    if _norm(target.notes):
        merge_notes_parts.append(str(target.notes).strip())
    source_bits: List[str] = [f"[Merged from Lead #{source.id} by {actor_label}]"]
    if _norm(reason):
        source_bits.append(f"Reason: {reason.strip()}")
    if _norm(source.original_enquiry) and source.original_enquiry != target.original_enquiry:
        source_bits.append(f"Original enquiry: {source.original_enquiry.strip()}")
    if _norm(source.notes):
        source_bits.append(f"Notes: {source.notes.strip()}")
    merge_notes_parts.append(" | ".join(source_bits))
    target.notes = "\n".join(merge_notes_parts)

    # Re-parent conversations & follow-ups (move ORM instances out of source.follow_ups
    # and source.conversations before db.delete(source) so cascade delete-orphan never
    # deletes re-parented rows).
    for conv in list(source.conversations):
        source.conversations.remove(conv)
        conv.lead_id = target.id
        target.conversations.append(conv)
    db.query(Conversation).filter(Conversation.lead_id == source.id).update(
        {"lead_id": target.id}, synchronize_session=False
    )
    for fu in list(source.follow_ups):
        source.follow_ups.remove(fu)
        fu.lead_id = target.id
        target.follow_ups.append(fu)
    db.query(FollowUp).filter(FollowUp.lead_id == source.id).update(
        {"lead_id": target.id}, synchronize_session=False
    )
    db.query(Appointment).filter(Appointment.lead_id == source.id).update(
        {"lead_id": target.id}, synchronize_session=False
    )
    db.query(Offer).filter(Offer.lead_id == source.id).update(
        {"lead_id": target.id}, synchronize_session=False
    )
    db.query(Deal).filter(Deal.lead_id == source.id).update(
        {"lead_id": target.id}, synchronize_session=False
    )

    # Re-parent recommendations without creating duplicate property_record_id links
    existing_rec_prop_ids = {
        r[0]
        for r in db.query(PropertyRecommendation.property_record_id)
        .filter(
            PropertyRecommendation.lead_id == target.id,
            PropertyRecommendation.property_record_id.isnot(None),
        )
        .all()
    }
    source_recs = (
        db.query(PropertyRecommendation)
        .filter(PropertyRecommendation.lead_id == source.id)
        .all()
    )
    for rec in source_recs:
        if rec.property_record_id is not None and rec.property_record_id in existing_rec_prop_ids:
            db.delete(rec)
        else:
            rec.lead_id = target.id
            if rec.property_record_id is not None:
                existing_rec_prop_ids.add(rec.property_record_id)

    # Re-point historical audit entries for the source lead to the canonical target lead
    db.query(AuditLog).filter(
        AuditLog.subject_type == "lead",
        AuditLog.subject_id == source.id,
    ).update({"subject_id": target.id}, synchronize_session=False)

    db.delete(source)
    db.flush()
    recompute_lead_score(target)
    target.updated_at = datetime.utcnow()
    db.flush()
    return target


def lead_activity_history(db: Session, lead_id: int, limit: int = 100) -> List[Dict[str, Any]]:
    """Return chronological audit trail events for a single lead."""
    rows = (
        db.query(AuditLog)
        .filter(AuditLog.subject_type == "lead", AuditLog.subject_id == lead_id)
        .order_by(AuditLog.id.desc())
        .limit(max(1, min(500, limit)))
        .all()
    )
    return [
        {
            "id": r.id,
            "event": r.event,
            "action": (r.event or "").replace(".", "_"),
            "actor": r.actor_label or r.actor_type or "system",
            "actor_type": r.actor_type,
            "actor_id": r.actor_id,
            "actor_label": r.actor_label,
            "subject_type": r.subject_type,
            "subject_id": r.subject_id,
            "subject_label": r.subject_label,
            "detail": r.detail,
            "created_at": r.created_at.isoformat() + "Z" if r.created_at else None,
        }
        for r in rows
    ]


def build_chat_summary(lead: Lead) -> Optional[str]:
    """Short factual conversation summary for the dashboard.

    Deterministic digest of the lead's stored facts plus the latest customer
    message — never invented, never a transcript dump.
    """
    bits: List[str] = []
    if lead.buy_rent in INTENTS:
        bits.append(f"Looking to {lead.buy_rent}")
    if lead.location:
        bits.append(f"in {lead.location}")
    if lead.property_type:
        bits.append(str(lead.property_type))
    if lead.bedrooms:
        bits.append(f"{lead.bedrooms} bed")
    if lead.budget:
        bits.append(f"budget {lead.budget}")
    if lead.timeline:
        bits.append(f"timeline: {lead.timeline}")
    summary = " | ".join(bits)
    msg = _norm(lead.last_customer_message)
    if msg:
        tail = msg if len(msg) <= 160 else msg[:157] + "..."
        prefix = f"{summary} — " if summary else ""
        summary = f'{prefix}last message: "{tail}"'
    return summary or None


def _absorb_placeholder(db: Session, *, source: Lead, target: Lead) -> None:
    """Retire an untouched AI-created placeholder lead that just learned a
    phone/email already owned by an existing record.

    Conversations, recommendations and follow-ups move to the real record and
    missing facts are copied across. The placeholder is deleted ONLY when it
    carries no staff work (status still "new", no notes, no assignment, no
    score, never manually classified) — agent edits are never destroyed.
    """
    for col in (
        "name", "buy_rent", "location", "budget", "property_type", "bedrooms",
        "bathrooms", "requirements", "investment_purpose", "timeline",
        "original_enquiry", "budget_min", "budget_max", "budget_currency",
        "amenities", "summary", "last_customer_message",
    ):
        if getattr(target, col, None) in (None, "") and getattr(source, col, None) not in (None, ""):
            setattr(target, col, getattr(source, col))

    db.query(Conversation).filter(Conversation.lead_id == source.id).update(
        {"lead_id": target.id}, synchronize_session=False
    )
    db.query(PropertyRecommendation).filter(
        PropertyRecommendation.lead_id == source.id
    ).update({"lead_id": target.id}, synchronize_session=False)
    db.query(FollowUp).filter(FollowUp.lead_id == source.id).update(
        {"lead_id": target.id}, synchronize_session=False
    )

    untouched = (
        (source.status or "new") == "new"
        and not source.notes
        and source.assigned_agent_id is None
        and source.lead_score is None
        and (source.temperature_source or "auto") != "manual"
    )
    if untouched:
        db.delete(source)
        db.flush()


def upsert_lead_from_ai(
    db: Session,
    lead_data: Dict,
    conversation: Optional[Conversation] = None,
    last_customer_message: Optional[str] = None,
    agent_state: Optional[Any] = None,
) -> Tuple[Lead, bool]:
    """Create or update a lead from AI-collected data.

    Returns (lead, created). Missing fields are left as None (displayed as
    "Not provided") rather than being guessed.

    Dedup order — one stable row per enquiry, never one per message:
      1. the conversation's already-linked lead (anonymous visitors have no
         contact identifier — the conversation link IS their identity);
      2. a real phone/email match across conversations;
      3. a brand-new row (only when neither exists).
    When a placeholder row later learns contact details that belong to an
    existing record, the real record wins and the untouched placeholder is
    absorbed into it.
    """
    phone = _norm(lead_data.get("phone"))
    email = _norm(lead_data.get("email"))
    now = datetime.utcnow()

    lead = None
    if conversation is not None and conversation.lead_id:
        lead = (
            db.query(Lead)
            .filter(Lead.id == conversation.lead_id)
            .first()
        )
    if lead is None:
        lead = find_existing_lead(db, phone=phone, email=email)

    created = lead is None
    if lead is None:
        lead = Lead(source="AI Assistant")
        db.add(lead)
    elif phone or email:
        # The conversation's linked row may be an anonymous placeholder whose
        # newly-learned contact already exists on another record.
        existing = find_existing_lead(
            db, phone=phone, email=email, exclude_lead_id=lead.id
        )
        if existing is not None and existing.id != lead.id:
            _absorb_placeholder(db, source=lead, target=existing)
            lead = existing

    # Merge only the fields the AI actually learned — never overwrite with None
    for key, value in lead_data.items():
        if value is None or not hasattr(lead, key):
            continue
        if key in ("phone", "email"):
            value = _norm(value)
            if value is None:
                continue
        setattr(lead, key, value)

    # Chat-derived dashboard context (staff `notes` are never touched here).
    if last_customer_message:
        lead.last_customer_message = _norm(last_customer_message)
    lead.summary = build_chat_summary(lead)

    lead.last_interaction_at = now
    lead.updated_at = now
    if lead.source is None:  # backfill pre-migration rows
        lead.source = "AI Assistant"

    # Deterministic temperature from stored facts + cumulative conversation
    # text; a human's manual classification is never overwritten.
    apply_temperature(
        lead,
        text=_norm(lead.last_customer_message) or "",
    )

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

    # Automatic follow-up creation when customer requests callback, viewing, or agent handoff
    if agent_state is not None:
        try:
            from datetime import timedelta
            from app.services.followups import create_followup
            
            # 1. Callback request
            if getattr(agent_state, "callback_request", None) and agent_state.callback_request.get("requested"):
                raw_req = agent_state.callback_request.get("raw") or "Customer requested callback in AI chat"
                due_time = (now + timedelta(hours=24)).isoformat() + "Z"
                create_followup(
                    db,
                    lead=lead,
                    fu_type="call",
                    due_at=due_time,
                    notes=f"LykAI Scheduled: {raw_req}",
                    assigned_agent_id=lead.assigned_agent_id,
                    priority="high",
                )

            # 2. Viewing interest
            if getattr(agent_state, "viewing_interest", None) and agent_state.viewing_interest.get("requested"):
                raw_view = agent_state.viewing_interest.get("raw") or "Customer requested property viewing in AI chat"
                due_time = (now + timedelta(hours=24)).isoformat() + "Z"
                create_followup(
                    db,
                    lead=lead,
                    fu_type="viewing",
                    due_at=due_time,
                    notes=f"LykAI Scheduled: {raw_view}",
                    assigned_agent_id=lead.assigned_agent_id,
                    priority="high",
                )

            # 3. Agent handoff request
            if getattr(agent_state, "handoff_requested", False):
                due_time = (now + timedelta(hours=4)).isoformat() + "Z"
                create_followup(
                    db,
                    lead=lead,
                    fu_type="call",
                    due_at=due_time,
                    notes="LykAI Handoff: Customer requested to speak directly with a human agent/consultant",
                    assigned_agent_id=lead.assigned_agent_id,
                    priority="high",
                )
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Auto follow-up creation failed (non-blocking): %s", exc)

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
    meta = get_qualification_meta(lead)
    qual = qualification_completeness(lead)
    follow_ups = sorted(
        (lead.follow_ups or []),
        key=lambda f: (f.due_at or datetime.max, f.id),
    )
    pending = [f for f in follow_ups if not f.is_completed]
    next_fu = pending[0] if pending else None
    return {
        "id": lead.id,
        "name": _np(lead.name),
        "phone": _np(lead.phone),
        "email": _np(lead.email),
        "buy_rent": _np(lead.buy_rent),
        "intent": lead.buy_rent if lead.buy_rent in INTENTS else None,
        "location": _np(lead.location),
        "emirate": meta.get("emirate"),
        "preferred_language": meta.get("preferred_language"),
        "budget": _np(lead.budget),
        "property_type": _np(lead.property_type),
        "bedrooms": lead.bedrooms,
        "bathrooms": lead.bathrooms,
        "status": lead.status or "new",
        # NULL = not scored yet (legacy rows are never fabricated a score)
        "lead_score": lead.lead_score,
        "priority": lead.priority,
        "qualification_completeness": qual["completeness_pct"],
        "qualification_status": qual["status"],
        "next_action": meta.get("next_action") or (next_fu.notes if next_fu and next_fu.notes else None),
        "next_follow_up": follow_up_summary(next_fu) if next_fu else None,
        # Transparent temperature: hot|warm|cold (NULL = not yet classified),
        # with auto|manual provenance — manual agent choices are locked.
        "temperature": lead.temperature,
        "temperature_source": lead.temperature_source,
        "temperature_updated_at": _iso(lead.temperature_updated_at),
        "summary": lead.summary or None,
        "source": _np(lead.source),
        "assigned_agent_id": lead.assigned_agent_id,
        "assigned_agent_name": lead.assigned_agent.full_name if lead.assigned_agent else None,
        "creator_agent_id": getattr(lead, "creator_agent_id", None),
        "creator_name": lead.creator_agent.full_name if getattr(lead, "creator_agent", None) else None,
        "creator_email": lead.creator_agent.email if getattr(lead, "creator_agent", None) else None,
        "creator_role": lead.creator_agent.role if getattr(lead, "creator_agent", None) else None,
        "created_by": (
            lead.creator_agent.full_name
            if getattr(lead, "creator_agent", None)
            else (_np(lead.source) or "AI Concierge")
        ),
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
    meta = get_qualification_meta(lead)
    qual = qualification_completeness(lead)
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
        # ---- Phase E: UAE qualification & lifecycle fields ----
        "preferred_language": meta.get("preferred_language"),
        "emirate": meta.get("emirate"),
        "financing_type": meta.get("financing_type"),
        "preferred_viewing_time": meta.get("preferred_viewing_time"),
        "qualification_status": qual["status"],
        "next_action": meta.get("next_action"),
        "field_provenance": meta.get("field_provenance") or {},
        "qualification": qual,
        "allowed_next_statuses": allowed_next_statuses(lead.status),
        # ---- AI brain upgrade: temperature rationale + chat context ----
        "temperature_rationale": parse_rationale(lead.temperature_rationale),
        "last_customer_message": lead.last_customer_message or "",
        # ---- Phase 5: follow-ups (from the existing follow_ups table)
        "follow_ups": [follow_up_summary(f) for f in follow_ups],
        "next_follow_up": follow_up_summary(next_follow_up) if next_follow_up else None,
    }
