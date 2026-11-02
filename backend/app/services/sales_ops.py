"""Phase F — Sales Operations Service: Appointments, Viewings, Offers, Negotiations & Deals.

Provides validated, transactional, RBAC-scoped operations for:
  1. Appointments & Property Viewings (timezone-aware, conflict-checked, reschedule history, viewing outcomes, dynamic property availability conflict flags)
  2. Offers & Counteroffer Negotiations (immutable append-only negotiation trail, draft vs submitted distinction, authorized acceptance)
  3. Deals & Transaction Pipeline (concurrency-safe unique deal references, duplicate-active-deal guard, validated stage machine, separate estimated vs verified commission, synchronized lead/property states)
  4. Configurable Document & Compliance Checklists (pending -> uploaded -> received -> reviewed -> verified/waived, metadata-only references)
"""

import json
import secrets
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import (
    Agent,
    Appointment,
    AuditLog,
    Conversation,
    Customer,
    Deal,
    DealChecklistItem,
    Lead,
    Offer,
    Property,
    PropertyRecommendation,
)
from app.services import rbac
from app.services.auth import lead_in_scope, scoped_lead_query
from app.services.leads import encode_preferences, get_preferences, get_qualification_meta

# ---------------------------------------------------------------------------
# Constants & Vocabularies
# ---------------------------------------------------------------------------

APPOINTMENT_TYPES = (
    "viewing",
    "callback",
    "consultation",
    "negotiation_meeting",
    "documentation_meeting",
)

MEETING_METHODS = ("in_person", "phone", "video")

APPOINTMENT_STATUSES = (
    "scheduled",
    "confirmed",
    "completed",
    "cancelled",
    "rescheduled",
    "no_show",
)

ACTIVE_APPOINTMENT_STATUSES = ("scheduled", "confirmed", "rescheduled")

CUSTOMER_CONFIRMATION_STATUSES = (
    "pending",
    "confirmed",
    "declined",
    "reschedule_requested",
)

VIEWING_OUTCOMES = (
    "interested",
    "not_interested",
    "requested_another_viewing",
    "requested_more_info",
    "undecided",
)

OFFER_INTENTS = ("purchase", "rent", "lease")

OFFER_STATUSES = (
    "draft",
    "submitted",
    "countered",
    "accepted",
    "rejected",
    "withdrawn",
    "expired",
)

TERMINAL_OFFER_STATUSES = ("accepted", "rejected", "withdrawn", "expired")

PAYMENT_FREQUENCIES = (
    "one_time",
    "yearly",
    "semi_annual",
    "quarterly",
    "monthly",
    "installment_plan",
)

DEAL_STAGES = (
    "qualification",
    "viewing",
    "offer_preparation",
    "negotiation",
    "offer_accepted",
    "reservation_pending",
    "reservation_confirmed",
    "documentation_pending",
    "transaction_pending_completion",
    "completed",
    "cancelled",
    "failed",
)

TERMINAL_DEAL_STAGES = ("completed", "cancelled", "failed")

# Allowed forward/lateral transitions in the deal pipeline.
# Note: jumping directly to 'completed' from early stages without reservation/documentation is prohibited.
ALLOWED_DEAL_TRANSITIONS: Dict[str, Tuple[str, ...]] = {
    "qualification": (
        "qualification", "viewing", "offer_preparation", "negotiation",
        "cancelled", "failed",
    ),
    "viewing": (
        "viewing", "offer_preparation", "negotiation", "offer_accepted",
        "cancelled", "failed",
    ),
    "offer_preparation": (
        "offer_preparation", "viewing", "negotiation", "offer_accepted",
        "cancelled", "failed",
    ),
    "negotiation": (
        "negotiation", "offer_preparation", "offer_accepted",
        "reservation_pending", "cancelled", "failed",
    ),
    "offer_accepted": (
        "offer_accepted", "negotiation", "reservation_pending",
        "reservation_confirmed", "documentation_pending",
        "cancelled", "failed",
    ),
    "reservation_pending": (
        "reservation_pending", "offer_accepted", "reservation_confirmed",
        "documentation_pending", "cancelled", "failed",
    ),
    "reservation_confirmed": (
        "reservation_confirmed", "documentation_pending",
        "transaction_pending_completion", "completed",
        "cancelled", "failed",
    ),
    "documentation_pending": (
        "documentation_pending", "reservation_confirmed",
        "transaction_pending_completion", "completed",
        "cancelled", "failed",
    ),
    "transaction_pending_completion": (
        "transaction_pending_completion", "documentation_pending",
        "completed", "cancelled", "failed",
    ),
    "completed": ("completed",),
    "cancelled": ("cancelled",),
    "failed": ("failed",),
}

CHECKLIST_STATUSES = (
    "pending",
    "uploaded",
    "received",
    "reviewed",
    "verified",
    "waived",
)

COMMISSION_STATUSES = ("estimated", "verified", "earned", "paid")

DEFAULT_DEAL_CHECKLIST: Tuple[Tuple[str, str, str, bool], ...] = (
    (
        "identity_documents_received",
        "Customer identity documents (Emirates ID / Passport / Visa) received",
        "identity",
        True,
    ),
    (
        "property_documentation_verified",
        "Property title deed / RERA permit & listing documentation verified",
        "property",
        True,
    ),
    (
        "offer_contract_reviewed",
        "Offer terms & contract draft (MOU / Form F / Tenancy Contract) reviewed",
        "contract",
        True,
    ),
    (
        "reservation_documentation_completed",
        "Reservation agreement & security deposit documentation completed",
        "reservation",
        True,
    ),
    (
        "required_approvals_verified",
        "Required developer NOC / financing / regulatory approvals verified",
        "regulatory",
        True,
    ),
    (
        "completion_milestone_confirmed",
        "Final transfer / handover / registration milestone confirmed",
        "completion",
        True,
    ),
)

_DEAL_REF_LOCK = threading.Lock()


class AppointmentConflictError(ValueError):
    """Raised when an agent has an overlapping active appointment and no override is supplied."""

    def __init__(self, conflicts: List[Dict[str, Any]]):
        super().__init__("Scheduling conflict detected for the assigned sales agent")
        self.conflicts = conflicts


# ---------------------------------------------------------------------------
# Timezone & JSON Helpers
# ---------------------------------------------------------------------------

_FALLBACK_OFFSETS = {
    "Asia/Dubai": timezone(timedelta(hours=4)),
    "Asia/Muscat": timezone(timedelta(hours=4)),
    "Asia/Riyadh": timezone(timedelta(hours=3)),
    "UTC": timezone.utc,
    "Etc/UTC": timezone.utc,
    "GMT": timezone.utc,
    "Europe/London": timezone.utc,
    "Asia/Kolkata": timezone(timedelta(hours=5, minutes=30)),
}


def resolve_tz(tz_name: Optional[str]):
    """Validate and return a tzinfo for `tz_name` (defaults to Asia/Dubai)."""
    name = (tz_name or "Asia/Dubai").strip() or "Asia/Dubai"
    if name in _FALLBACK_OFFSETS:
        try:
            return ZoneInfo(name), name
        except ZoneInfoNotFoundError:
            return _FALLBACK_OFFSETS[name], name
    try:
        return ZoneInfo(name), name
    except ZoneInfoNotFoundError:
        raise ValueError(f"Unsupported or invalid time zone: {name!r}")


def to_utc_naive(dt: datetime, default_tz_name: str = "Asia/Dubai") -> datetime:
    """Convert a datetime to UTC naive for portable DB storage.

    - If `dt` is timezone-aware, convert to UTC and strip tzinfo.
    - If `dt` is naive, interpret it in `default_tz_name` (defaults to Asia/Dubai) and convert to UTC naive.
    """
    if not isinstance(dt, datetime):
        raise ValueError("Expected a valid datetime")
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    tz_obj, _ = resolve_tz(default_tz_name)
    return dt.replace(tzinfo=tz_obj).astimezone(timezone.utc).replace(tzinfo=None)


def format_utc_iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def format_local_iso(dt: Optional[datetime], tz_name: str = "Asia/Dubai") -> Optional[str]:
    if dt is None:
        return None
    tz_obj, _ = resolve_tz(tz_name)
    aware_utc = dt.replace(tzinfo=timezone.utc)
    return aware_utc.astimezone(tz_obj).isoformat()


def _safe_json_list(raw: Optional[str]) -> List[Any]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def _resolve_lead_customer_id(db: Session, lead: Lead, explicit_customer_id: Optional[int] = None) -> Optional[int]:
    if explicit_customer_id is not None:
        cust = db.query(Customer).filter(Customer.id == explicit_customer_id).first()
        if cust is None:
            raise ValueError(f"Customer #{explicit_customer_id} not found")
        return cust.id
    conv = (
        db.query(Conversation)
        .filter(Conversation.lead_id == lead.id, Conversation.customer_id.isnot(None))
        .order_by(Conversation.id.desc())
        .first()
    )
    return conv.customer_id if conv is not None else None


# ---------------------------------------------------------------------------
# Scope Helpers (Object-Level Access Control)
# ---------------------------------------------------------------------------

def appointment_in_scope(agent: Agent, appt: Appointment) -> bool:
    if rbac.has_permission(agent, "leads.read_all"):
        return True
    if appt.assigned_agent_id == agent.id:
        return True
    if appt.lead is not None and lead_in_scope(agent, appt.lead):
        return True
    return False


def scoped_appointment_query(db: Session, agent: Agent):
    q = db.query(Appointment)
    if rbac.has_permission(agent, "leads.read_all"):
        return q
    visible_lead_ids = scoped_lead_query(db, agent).with_entities(Lead.id)
    return q.filter(
        (Appointment.assigned_agent_id == agent.id)
        | (Appointment.lead_id.in_(visible_lead_ids))
    )


def offer_in_scope(agent: Agent, offer: Offer) -> bool:
    if rbac.has_permission(agent, "leads.read_all"):
        return True
    if offer.assigned_agent_id == agent.id:
        return True
    if offer.lead is not None and lead_in_scope(agent, offer.lead):
        return True
    return False


def scoped_offer_query(db: Session, agent: Agent):
    q = db.query(Offer)
    if rbac.has_permission(agent, "leads.read_all"):
        return q
    visible_lead_ids = scoped_lead_query(db, agent).with_entities(Lead.id)
    return q.filter(
        (Offer.assigned_agent_id == agent.id)
        | (Offer.lead_id.in_(visible_lead_ids))
    )


def deal_in_scope(agent: Agent, deal: Deal) -> bool:
    if rbac.has_permission(agent, "leads.read_all"):
        return True
    if deal.assigned_agent_id == agent.id:
        return True
    if deal.lead is not None and lead_in_scope(agent, deal.lead):
        return True
    return False


def scoped_deal_query(db: Session, agent: Agent):
    q = db.query(Deal)
    if rbac.has_permission(agent, "leads.read_all"):
        return q
    visible_lead_ids = scoped_lead_query(db, agent).with_entities(Lead.id)
    return q.filter(
        (Deal.assigned_agent_id == agent.id)
        | (Deal.lead_id.in_(visible_lead_ids))
    )


# ---------------------------------------------------------------------------
# Phase 1 & Phase 2: Appointments & Property Viewings
# ---------------------------------------------------------------------------

def _validate_property_for_viewing(db: Session, prop_id: int) -> Property:
    prop = db.query(Property).filter(Property.id == prop_id).first()
    if prop is None:
        raise LookupError(f"Property #{prop_id} not found")
    if not prop.is_approved:
        raise ValueError(
            f"Property #{prop_id} ({prop.title}) is not approved and cannot be scheduled for a viewing"
        )
    if prop.availability != "available":
        raise ValueError(
            f"Property #{prop_id} ({prop.title}) is currently '{prop.availability}' and cannot be scheduled as available inventory"
        )
    return prop


def find_agent_conflicts(
    db: Session,
    *,
    assigned_agent_id: int,
    start_at: datetime,
    end_at: datetime,
    exclude_appointment_id: Optional[int] = None,
) -> List[Appointment]:
    """Return active appointments for `assigned_agent_id` overlapping `(start_at, end_at)`."""
    q = db.query(Appointment).filter(
        Appointment.assigned_agent_id == assigned_agent_id,
        Appointment.status.in_(ACTIVE_APPOINTMENT_STATUSES),
        Appointment.start_at < end_at,
        Appointment.end_at > start_at,
    )
    if exclude_appointment_id is not None:
        q = q.filter(Appointment.id != exclude_appointment_id)
    return q.order_by(Appointment.start_at.asc()).all()


def appointment_to_dict(appt: Appointment, db: Optional[Session] = None) -> Dict[str, Any]:
    """Serialize an Appointment with UAE local time and live property availability conflict detection."""
    add_ids = _safe_json_list(appt.additional_property_ids)
    all_prop_ids = ([appt.property_id] if appt.property_id is not None else []) + [
        pid for pid in add_ids if isinstance(pid, int) and pid != appt.property_id
    ]

    prop_title = None
    prop_location = None
    prop_availability = None
    prop_approved = None
    property_availability_conflict = False
    property_conflict_detail = None

    prop_obj = appt.property_record
    if prop_obj is None and db is not None and appt.property_id is not None:
        prop_obj = db.query(Property).filter(Property.id == appt.property_id).first()

    if prop_obj is not None:
        prop_title = prop_obj.title
        prop_location = prop_obj.location
        prop_availability = prop_obj.availability
        prop_approved = bool(prop_obj.is_approved)
        if appt.status in ACTIVE_APPOINTMENT_STATUSES and (
            not prop_obj.is_approved or prop_obj.availability != "available"
        ):
            property_availability_conflict = True
            property_conflict_detail = (
                f"Property #{prop_obj.id} ({prop_obj.title}) is now "
                f"{'unapproved' if not prop_obj.is_approved else prop_obj.availability}. "
                f"Review or reschedule this appointment."
            )

    if not property_availability_conflict and db is not None and add_ids and appt.status in ACTIVE_APPOINTMENT_STATUSES:
        extra_props = db.query(Property).filter(Property.id.in_(add_ids)).all()
        for ep in extra_props:
            if not ep.is_approved or ep.availability != "available":
                property_availability_conflict = True
                property_conflict_detail = (
                    f"Additional property #{ep.id} ({ep.title}) is now "
                    f"{'unapproved' if not ep.is_approved else ep.availability}."
                )
                break

    tz_name = appt.timezone or "Asia/Dubai"
    return {
        "id": appt.id,
        "lead_id": appt.lead_id,
        "lead_name": appt.lead.name if appt.lead else None,
        "lead_status": appt.lead.status if appt.lead else None,
        "customer_id": appt.customer_id,
        "property_id": appt.property_id,
        "property_ids": all_prop_ids,
        "additional_property_ids": add_ids,
        "property_title": prop_title,
        "property_location": prop_location,
        "property_availability": prop_availability,
        "property_approved": prop_approved,
        "property_availability_conflict": property_availability_conflict,
        "property_conflict_detail": property_conflict_detail,
        "assigned_agent_id": appt.assigned_agent_id,
        "assigned_agent_name": appt.assigned_agent.full_name if appt.assigned_agent else None,
        "appointment_type": appt.appointment_type,
        "start_at": format_utc_iso(appt.start_at),
        "end_at": format_utc_iso(appt.end_at),
        "start_at_local": format_local_iso(appt.start_at, tz_name),
        "end_at_local": format_local_iso(appt.end_at, tz_name),
        "timezone": tz_name,
        "meeting_method": appt.meeting_method,
        "location_or_link": appt.location_or_link,
        "status": appt.status,
        "customer_confirmation_status": appt.customer_confirmation_status,
        "notes": appt.notes,
        "outcome": appt.outcome,
        "viewing_outcome": appt.viewing_outcome,
        "customer_feedback": appt.customer_feedback,
        "next_action": appt.next_action,
        "cancellation_reason": appt.cancellation_reason,
        "reschedule_reason": appt.reschedule_reason,
        "reschedule_history": _safe_json_list(appt.reschedule_history),
        "conflict_override_reason": appt.conflict_override_reason,
        "notification_delivery": "manual_only",
        "created_by_id": appt.created_by_id,
        "updated_by_id": appt.updated_by_id,
        "created_at": format_utc_iso(appt.created_at),
        "updated_at": format_utc_iso(appt.updated_at),
    }


def create_appointment(
    db: Session,
    *,
    actor: Agent,
    lead: Lead,
    appointment_type: str,
    start_at: datetime,
    end_at: datetime,
    timezone_name: str = "Asia/Dubai",
    meeting_method: str = "in_person",
    location_or_link: Optional[str] = None,
    property_id: Optional[int] = None,
    additional_property_ids: Optional[Sequence[int]] = None,
    assigned_agent_id: Optional[int] = None,
    customer_id: Optional[int] = None,
    customer_confirmation_status: str = "pending",
    notes: Optional[str] = None,
    conflict_override: bool = False,
    conflict_override_reason: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> Tuple[Appointment, bool]:
    """Create a validated appointment or property viewing. Returns `(appointment, idempotent_replay)`."""
    if appointment_type not in APPOINTMENT_TYPES:
        raise ValueError(f"Invalid appointment_type. Allowed: {', '.join(APPOINTMENT_TYPES)}")
    if meeting_method not in MEETING_METHODS:
        raise ValueError(f"Invalid meeting_method. Allowed: {', '.join(MEETING_METHODS)}")
    if customer_confirmation_status not in CUSTOMER_CONFIRMATION_STATUSES:
        raise ValueError(
            f"Invalid customer_confirmation_status. Allowed: {', '.join(CUSTOMER_CONFIRMATION_STATUSES)}"
        )

    _, norm_tz = resolve_tz(timezone_name)
    utc_start = to_utc_naive(start_at, norm_tz)
    utc_end = to_utc_naive(end_at, norm_tz)
    if utc_end <= utc_start:
        raise ValueError("Appointment end_at must be strictly after start_at")
    if (utc_end - utc_start) > timedelta(hours=24):
        raise ValueError("Appointment duration cannot exceed 24 hours")

    # Idempotency check by key
    norm_idem = (idempotency_key or "").strip() or None
    if norm_idem:
        existing_idem = db.query(Appointment).filter(Appointment.idempotency_key == norm_idem).first()
        if existing_idem is not None:
            return existing_idem, True

    # Target agent resolution & authorization
    target_agent_id = assigned_agent_id or lead.assigned_agent_id or actor.id
    if target_agent_id != actor.id and not rbac.has_permission(actor, "leads.assign"):
        raise PermissionError("Only an administrator or sales manager can schedule appointments for another agent")
    target_agent = db.query(Agent).filter(Agent.id == target_agent_id).first()
    if target_agent is None or not target_agent.is_active:
        raise ValueError("Assigned sales agent does not exist or is inactive")

    # Property validation
    extra_ids = []
    if additional_property_ids:
        for pid in additional_property_ids:
            if pid is not None and int(pid) not in extra_ids and int(pid) != property_id:
                extra_ids.append(int(pid))
    if property_id is None and extra_ids:
        property_id = extra_ids.pop(0)

    if appointment_type == "viewing" and property_id is None:
        raise ValueError("A property viewing requires at least one approved, available property_id")

    primary_prop = None
    if property_id is not None:
        if appointment_type == "viewing":
            primary_prop = _validate_property_for_viewing(db, property_id)
        else:
            primary_prop = db.query(Property).filter(Property.id == property_id).first()
            if primary_prop is None:
                raise LookupError(f"Property #{property_id} not found")
            if not primary_prop.is_approved:
                raise ValueError(f"Property #{property_id} is not approved")

    for eid in extra_ids:
        _validate_property_for_viewing(db, eid)

    # Natural duplicate guard (same lead, agent, type, start, end, property)
    natural_dup = (
        db.query(Appointment)
        .filter(
            Appointment.lead_id == lead.id,
            Appointment.assigned_agent_id == target_agent_id,
            Appointment.appointment_type == appointment_type,
            Appointment.start_at == utc_start,
            Appointment.end_at == utc_end,
            Appointment.property_id == property_id,
            Appointment.status.in_(ACTIVE_APPOINTMENT_STATUSES),
        )
        .first()
    )
    if natural_dup is not None:
        return natural_dup, True

    # Conflict check for the assigned agent
    conflicts = find_agent_conflicts(
        db,
        assigned_agent_id=target_agent_id,
        start_at=utc_start,
        end_at=utc_end,
    )
    override_note = None
    if conflicts:
        if not conflict_override:
            raise AppointmentConflictError([appointment_to_dict(c, db) for c in conflicts])
        if not rbac.has_permission(actor, "appointments.override_conflict"):
            raise PermissionError("Caller lacks permission to override scheduling conflicts")
        override_note = (conflict_override_reason or "").strip()
        if not override_note:
            raise ValueError("conflict_override_reason is required when overriding a scheduling conflict")

    resolved_customer_id = _resolve_lead_customer_id(db, lead, customer_id)
    loc = (location_or_link or "").strip() or (
        primary_prop.location if (primary_prop and meeting_method == "in_person") else None
    )

    appt = Appointment(
        lead_id=lead.id,
        customer_id=resolved_customer_id,
        property_id=property_id,
        additional_property_ids=json.dumps(extra_ids),
        assigned_agent_id=target_agent_id,
        appointment_type=appointment_type,
        start_at=utc_start,
        end_at=utc_end,
        timezone=norm_tz,
        meeting_method=meeting_method,
        location_or_link=loc,
        status="confirmed" if customer_confirmation_status == "confirmed" else "scheduled",
        customer_confirmation_status=customer_confirmation_status,
        notes=(notes or "").strip() or None,
        conflict_override_reason=override_note,
        idempotency_key=norm_idem,
        created_by_id=actor.id,
        updated_by_id=actor.id,
    )
    db.add(appt)

    # If scheduling a viewing on a lead that is in an earlier stage, advance lead to 'viewing'
    if appointment_type == "viewing" and lead.status in ("new", "contact_pending", "contacted", "qualified"):
        lead.status = "viewing"
    lead.last_interaction_at = datetime.utcnow()
    db.flush()
    return appt, False


def reschedule_appointment(
    db: Session,
    *,
    actor: Agent,
    appt: Appointment,
    new_start_at: datetime,
    new_end_at: datetime,
    timezone_name: Optional[str] = None,
    reason: Optional[str] = None,
    location_or_link: Optional[str] = None,
    conflict_override: bool = False,
    conflict_override_reason: Optional[str] = None,
) -> Appointment:
    """Reschedule an appointment while preserving the complete prior schedule history."""
    if appt.status in ("cancelled", "completed"):
        raise ValueError(f"Cannot reschedule an appointment that is already '{appt.status}'")

    tz_to_use = timezone_name or appt.timezone or "Asia/Dubai"
    _, norm_tz = resolve_tz(tz_to_use)
    utc_start = to_utc_naive(new_start_at, norm_tz)
    utc_end = to_utc_naive(new_end_at, norm_tz)
    if utc_end <= utc_start:
        raise ValueError("Appointment end_at must be strictly after start_at")
    if (utc_end - utc_start) > timedelta(hours=24):
        raise ValueError("Appointment duration cannot exceed 24 hours")

    if appt.appointment_type == "viewing" and appt.property_id is not None:
        _validate_property_for_viewing(db, appt.property_id)

    conflicts = find_agent_conflicts(
        db,
        assigned_agent_id=appt.assigned_agent_id,
        start_at=utc_start,
        end_at=utc_end,
        exclude_appointment_id=appt.id,
    )
    if conflicts:
        if not conflict_override:
            raise AppointmentConflictError([appointment_to_dict(c, db) for c in conflicts])
        if not rbac.has_permission(actor, "appointments.override_conflict"):
            raise PermissionError("Caller lacks permission to override scheduling conflicts")
        override_note = (conflict_override_reason or "").strip()
        if not override_note:
            raise ValueError("conflict_override_reason is required when overriding a scheduling conflict")
        appt.conflict_override_reason = override_note

    history = _safe_json_list(appt.reschedule_history)
    history.append({
        "previous_start_at": format_utc_iso(appt.start_at),
        "previous_end_at": format_utc_iso(appt.end_at),
        "previous_timezone": appt.timezone,
        "new_start_at": format_utc_iso(utc_start),
        "new_end_at": format_utc_iso(utc_end),
        "reason": (reason or "").strip() or None,
        "actor_id": actor.id,
        "actor_label": actor.email,
        "rescheduled_at": format_utc_iso(datetime.utcnow()),
    })
    appt.reschedule_history = json.dumps(history, ensure_ascii=False)
    appt.start_at = utc_start
    appt.end_at = utc_end
    appt.timezone = norm_tz
    appt.reschedule_reason = (reason or "").strip() or None
    if location_or_link is not None:
        appt.location_or_link = location_or_link.strip() or None
    appt.status = "rescheduled"
    appt.updated_by_id = actor.id
    appt.updated_at = datetime.utcnow()
    db.flush()
    return appt


def cancel_appointment(
    db: Session,
    *,
    actor: Agent,
    appt: Appointment,
    reason: str,
) -> Appointment:
    """Cancel an appointment and preserve the cancellation reason."""
    if appt.status == "completed":
        raise ValueError("Cannot cancel an already completed appointment")
    clean_reason = (reason or "").strip()
    if not clean_reason:
        raise ValueError("A cancellation reason is required")
    appt.status = "cancelled"
    appt.cancellation_reason = clean_reason
    appt.updated_by_id = actor.id
    appt.updated_at = datetime.utcnow()
    db.flush()
    return appt


def record_appointment_outcome(
    db: Session,
    *,
    actor: Agent,
    appt: Appointment,
    status: str = "completed",
    viewing_outcome: Optional[str] = None,
    customer_feedback: Optional[str] = None,
    outcome: Optional[str] = None,
    next_action: Optional[str] = None,
) -> Appointment:
    """Record completion, no-show, or structured property viewing outcome & feedback."""
    if status not in ("completed", "no_show"):
        raise ValueError("Outcome status must be 'completed' or 'no_show'")
    if appt.status == "cancelled":
        raise ValueError("Cannot record a completion outcome on a cancelled appointment")

    if viewing_outcome is not None:
        if viewing_outcome not in VIEWING_OUTCOMES:
            raise ValueError(f"Invalid viewing_outcome. Allowed: {', '.join(VIEWING_OUTCOMES)}")
        appt.viewing_outcome = viewing_outcome
    elif appt.appointment_type == "viewing" and status == "completed" and not appt.viewing_outcome:
        raise ValueError(
            f"viewing_outcome is required when completing a viewing ({', '.join(VIEWING_OUTCOMES)})"
        )

    appt.status = status
    if customer_feedback is not None:
        appt.customer_feedback = customer_feedback.strip() or None
    if outcome is not None:
        appt.outcome = outcome.strip() or None
    if next_action is not None:
        appt.next_action = next_action.strip() or None
    appt.updated_by_id = actor.id
    appt.updated_at = datetime.utcnow()

    if appt.lead is not None:
        appt.lead.last_interaction_at = datetime.utcnow()
        if appt.next_action:
            prefs = get_preferences(appt.lead)
            meta = get_qualification_meta(appt.lead)
            meta["next_action"] = appt.next_action
            appt.lead.requirements = encode_preferences(prefs, meta)
        if appt.appointment_type == "viewing" and status == "completed":
            if appt.lead.status in ("new", "contact_pending", "contacted", "qualified"):
                appt.lead.status = "viewing"
    db.flush()
    return appt


# ---------------------------------------------------------------------------
# Phase 3: Offers & Counteroffer Negotiations
# ---------------------------------------------------------------------------

def offer_to_dict(offer: Offer) -> Dict[str, Any]:
    return {
        "id": offer.id,
        "lead_id": offer.lead_id,
        "lead_name": offer.lead.name if offer.lead else None,
        "customer_id": offer.customer_id,
        "property_id": offer.property_id,
        "property_title": offer.property_record.title if offer.property_record else None,
        "property_location": offer.property_record.location if offer.property_record else None,
        "property_availability": offer.property_record.availability if offer.property_record else None,
        "assigned_agent_id": offer.assigned_agent_id,
        "assigned_agent_name": offer.assigned_agent.full_name if offer.assigned_agent else None,
        "transaction_intent": offer.transaction_intent,
        "asking_price": offer.asking_price,
        "offered_price": offer.offered_price,
        "current_price": offer.current_price,
        "currency": offer.currency,
        "payment_frequency": offer.payment_frequency,
        "cheques_count": offer.cheques_count,
        "financing_type": offer.financing_type,
        "status": offer.status,
        "is_draft": offer.status == "draft",
        "legal_completion_notice": (
            "Offer acceptance records commercial agreement only and does NOT constitute "
            "a completed legal transfer, registered contract, or payment confirmation."
        ),
        "submitted_at": format_utc_iso(offer.submitted_at),
        "expires_at": format_utc_iso(offer.expires_at),
        "decided_at": format_utc_iso(offer.decided_at),
        "notes": offer.notes,
        "terms_conditions": offer.terms_conditions,
        "document_references": _safe_json_list(offer.document_references),
        "negotiation_history": _safe_json_list(offer.negotiation_history),
        "created_by_id": offer.created_by_id,
        "updated_by_id": offer.updated_by_id,
        "created_at": format_utc_iso(offer.created_at),
        "updated_at": format_utc_iso(offer.updated_at),
    }


def create_offer(
    db: Session,
    *,
    actor: Agent,
    lead: Lead,
    property_id: int,
    transaction_intent: str,
    offered_price: float,
    asking_price: Optional[float] = None,
    currency: str = "AED",
    payment_frequency: Optional[str] = None,
    cheques_count: Optional[int] = None,
    financing_type: Optional[str] = None,
    submit_immediately: bool = False,
    expires_at: Optional[datetime] = None,
    notes: Optional[str] = None,
    terms_conditions: Optional[str] = None,
    document_references: Optional[Sequence[str]] = None,
    assigned_agent_id: Optional[int] = None,
    customer_id: Optional[int] = None,
    idempotency_key: Optional[str] = None,
) -> Tuple[Offer, bool]:
    """Create a draft or submitted Offer with an initial negotiation history entry."""
    if transaction_intent not in OFFER_INTENTS:
        raise ValueError(f"Invalid transaction_intent. Allowed: {', '.join(OFFER_INTENTS)}")
    if offered_price is None or float(offered_price) <= 0:
        raise ValueError("offered_price must be greater than 0")
    cur = (currency or "AED").strip().upper()
    if len(cur) != 3 or not cur.isalpha():
        raise ValueError("currency must be a 3-letter ISO code (e.g. AED)")
    if payment_frequency is not None and payment_frequency not in PAYMENT_FREQUENCIES:
        raise ValueError(f"Invalid payment_frequency. Allowed: {', '.join(PAYMENT_FREQUENCIES)}")
    if cheques_count is not None and (int(cheques_count) < 1 or int(cheques_count) > 12):
        raise ValueError("cheques_count must be between 1 and 12")

    norm_idem = (idempotency_key or "").strip() or None
    if norm_idem:
        existing_idem = db.query(Offer).filter(Offer.idempotency_key == norm_idem).first()
        if existing_idem is not None:
            return existing_idem, True

    prop = db.query(Property).filter(Property.id == property_id).first()
    if prop is None:
        raise LookupError(f"Property #{property_id} not found")
    if not prop.is_approved:
        raise ValueError("Cannot create an offer against an unapproved property")
    if prop.availability in ("sold", "rented", "off_market"):
        raise ValueError(f"Property #{property_id} is currently '{prop.availability}' and cannot receive new offers")

    resolved_asking = float(asking_price) if asking_price is not None else float(prop.price)
    if resolved_asking < 0:
        raise ValueError("asking_price cannot be negative")

    now = datetime.utcnow()
    utc_expires = to_utc_naive(expires_at) if expires_at is not None else None
    if utc_expires is not None and utc_expires <= now:
        raise ValueError("expires_at must be in the future")

    target_agent_id = assigned_agent_id or lead.assigned_agent_id or actor.id
    if target_agent_id != actor.id and not rbac.has_permission(actor, "leads.assign"):
        raise PermissionError("Only an administrator or sales manager can assign an offer to another agent")

    initial_status = "submitted" if submit_immediately else "draft"
    history = [
        {
            "seq": 1,
            "event_type": "offer_submitted" if submit_immediately else "draft_created",
            "party": "buyer",
            "amount": float(offered_price),
            "currency": cur,
            "payment_frequency": payment_frequency,
            "cheques_count": cheques_count,
            "previous_status": None,
            "new_status": initial_status,
            "reason": "Initial offer submitted" if submit_immediately else "Internal offer draft created",
            "notes": (notes or "").strip() or None,
            "actor_id": actor.id,
            "actor_label": actor.email,
            "created_at": format_utc_iso(now),
        }
    ]

    docs = [str(d).strip() for d in (document_references or []) if str(d).strip()]
    resolved_customer_id = _resolve_lead_customer_id(db, lead, customer_id)

    offer = Offer(
        lead_id=lead.id,
        customer_id=resolved_customer_id,
        property_id=prop.id,
        assigned_agent_id=target_agent_id,
        transaction_intent=transaction_intent,
        asking_price=resolved_asking,
        offered_price=float(offered_price),
        current_price=float(offered_price),
        currency=cur,
        payment_frequency=payment_frequency,
        cheques_count=cheques_count,
        financing_type=(financing_type or "").strip() or None,
        status=initial_status,
        submitted_at=now if submit_immediately else None,
        expires_at=utc_expires,
        notes=(notes or "").strip() or None,
        terms_conditions=(terms_conditions or "").strip() or None,
        document_references=json.dumps(docs, ensure_ascii=False),
        negotiation_history=json.dumps(history, ensure_ascii=False),
        idempotency_key=norm_idem,
        created_by_id=actor.id,
        updated_by_id=actor.id,
    )
    db.add(offer)

    if submit_immediately and lead.status in ("new", "contact_pending", "contacted", "qualified", "viewing"):
        lead.status = "negotiation"
    lead.last_interaction_at = now
    db.flush()
    return offer, False


def record_counteroffer(
    db: Session,
    *,
    actor: Agent,
    offer: Offer,
    party: str,
    counter_amount: float,
    payment_frequency: Optional[str] = None,
    cheques_count: Optional[int] = None,
    expires_at: Optional[datetime] = None,
    reason: Optional[str] = None,
    notes: Optional[str] = None,
) -> Offer:
    """Append a counteroffer to `offer.negotiation_history` without overwriting prior offers."""
    if offer.status in TERMINAL_OFFER_STATUSES:
        raise ValueError(f"Cannot counter an offer in terminal status '{offer.status}'")
    if offer.status == "draft":
        raise ValueError("Submit the draft offer before recording a counteroffer")
    if party not in ("buyer", "seller", "owner", "landlord", "agent"):
        raise ValueError("party must be 'buyer', 'seller', 'owner', 'landlord', or 'agent'")
    if counter_amount is None or float(counter_amount) <= 0:
        raise ValueError("counter_amount must be greater than 0")
    if payment_frequency is not None and payment_frequency not in PAYMENT_FREQUENCIES:
        raise ValueError(f"Invalid payment_frequency. Allowed: {', '.join(PAYMENT_FREQUENCIES)}")

    now = datetime.utcnow()
    prev_status = offer.status
    history = _safe_json_list(offer.negotiation_history)
    history.append({
        "seq": len(history) + 1,
        "event_type": "counteroffer",
        "party": party,
        "amount": float(counter_amount),
        "previous_amount": offer.current_price,
        "currency": offer.currency,
        "payment_frequency": payment_frequency or offer.payment_frequency,
        "cheques_count": cheques_count if cheques_count is not None else offer.cheques_count,
        "previous_status": prev_status,
        "new_status": "countered",
        "reason": (reason or "").strip() or f"Counteroffer by {party}",
        "notes": (notes or "").strip() or None,
        "actor_id": actor.id,
        "actor_label": actor.email,
        "created_at": format_utc_iso(now),
    })

    offer.current_price = float(counter_amount)
    if payment_frequency is not None:
        offer.payment_frequency = payment_frequency
    if cheques_count is not None:
        offer.cheques_count = cheques_count
    if expires_at is not None:
        offer.expires_at = to_utc_naive(expires_at)
    if notes:
        offer.notes = notes.strip()
    offer.status = "countered"
    offer.negotiation_history = json.dumps(history, ensure_ascii=False)
    offer.updated_by_id = actor.id
    offer.updated_at = now
    if offer.lead is not None:
        if offer.lead.status in ("new", "contact_pending", "contacted", "qualified", "viewing"):
            offer.lead.status = "negotiation"
        offer.lead.last_interaction_at = now
    db.flush()
    return offer


def transition_offer_status(
    db: Session,
    *,
    actor: Agent,
    offer: Offer,
    target_status: str,
    reason: Optional[str] = None,
    notes: Optional[str] = None,
) -> Offer:
    """Validate and transition an Offer's status (`submitted`, `accepted`, `rejected`, `withdrawn`, `expired`)."""
    if target_status not in OFFER_STATUSES:
        raise ValueError(f"Invalid offer status. Allowed: {', '.join(OFFER_STATUSES)}")
    if target_status == "countered":
        raise ValueError("Use the counteroffer endpoint to record a counteroffer with an amount")

    prev = offer.status
    if prev == target_status:
        return offer
    if prev in TERMINAL_OFFER_STATUSES:
        raise ValueError(f"Offer #{offer.id} is already '{prev}' and cannot transition to '{target_status}'")

    allowed_map = {
        "draft": ("submitted", "withdrawn"),
        "submitted": ("accepted", "rejected", "withdrawn", "expired"),
        "countered": ("accepted", "rejected", "withdrawn", "expired"),
    }
    allowed = allowed_map.get(prev, ())
    if target_status not in allowed:
        raise ValueError(
            f"Invalid offer status transition from '{prev}' to '{target_status}'. "
            f"Allowed from '{prev}': {', '.join(allowed) or 'none'}"
        )

    if target_status in ("accepted", "rejected") and not rbac.has_permission(actor, "offers.accept"):
        raise PermissionError("Caller lacks permission ('offers.accept') to accept or reject offers")

    if target_status in ("rejected", "withdrawn") and not (reason or "").strip():
        raise ValueError(f"A reason is required when marking an offer as '{target_status}'")

    now = datetime.utcnow()
    if target_status == "submitted":
        offer.submitted_at = now
    if target_status in TERMINAL_OFFER_STATUSES:
        offer.decided_at = now

    history = _safe_json_list(offer.negotiation_history)
    history.append({
        "seq": len(history) + 1,
        "event_type": f"status_{target_status}",
        "party": "staff",
        "amount": offer.current_price,
        "currency": offer.currency,
        "payment_frequency": offer.payment_frequency,
        "cheques_count": offer.cheques_count,
        "previous_status": prev,
        "new_status": target_status,
        "reason": (reason or "").strip() or None,
        "notes": (notes or "").strip() or None,
        "actor_id": actor.id,
        "actor_label": actor.email,
        "created_at": format_utc_iso(now),
    })
    offer.status = target_status
    if notes:
        offer.notes = notes.strip()
    offer.negotiation_history = json.dumps(history, ensure_ascii=False)
    offer.updated_by_id = actor.id
    offer.updated_at = now

    if offer.lead is not None:
        # Accepting an offer moves the lead to 'negotiation' (never directly to closed_won:
        # legal completion happens only when the Deal is completed).
        if target_status in ("submitted", "accepted") and offer.lead.status in (
            "new", "contact_pending", "contacted", "qualified", "viewing"
        ):
            offer.lead.status = "negotiation"
        offer.lead.last_interaction_at = now

    db.flush()
    return offer


# ---------------------------------------------------------------------------
# Phase 4 & Phase 5: Deals, Transaction Pipeline & Compliance Checklist
# ---------------------------------------------------------------------------

def _generate_deal_reference(db: Session) -> str:
    """Generate a concurrency-safe unique deal reference (`LYKA-DEAL-YYYY-NNNN`)."""
    year = datetime.utcnow().year
    prefix = f"LYKA-DEAL-{year}-"
    existing_refs = (
        db.query(Deal.deal_reference)
        .filter(Deal.deal_reference.like(f"{prefix}%"))
        .all()
    )
    max_seq = 0
    for (ref,) in existing_refs:
        if isinstance(ref, str) and ref.startswith(prefix):
            tail = ref[len(prefix):].split("-")[0]
            if tail.isdigit():
                max_seq = max(max_seq, int(tail))
    next_seq = max_seq + 1
    candidate = f"{prefix}{next_seq:04d}"
    while db.query(Deal.id).filter(Deal.deal_reference == candidate).first() is not None:
        next_seq += 1
        candidate = f"{prefix}{next_seq:04d}-{secrets.token_hex(2).upper()}"
    return candidate


def checklist_item_to_dict(item: DealChecklistItem) -> Dict[str, Any]:
    return {
        "id": item.id,
        "deal_id": item.deal_id,
        "code": item.code,
        "title": item.title,
        "category": item.category,
        "is_required": bool(item.is_required),
        "status": item.status,
        "document_reference": item.document_reference,
        "notes": item.notes,
        "responsible_user_id": item.responsible_user_id,
        "verified_by_id": item.verified_by_id,
        "verified_by_label": item.verified_by_label,
        "verified_at": format_utc_iso(item.verified_at),
        "created_at": format_utc_iso(item.created_at),
        "updated_at": format_utc_iso(item.updated_at),
    }


def deal_checklist_summary(deal: Deal) -> Dict[str, Any]:
    items = list(deal.checklist_items or [])
    req_items = [i for i in items if i.is_required]
    verified_req = [i for i in req_items if i.status in ("verified", "waived")]
    unverified_req = [i for i in req_items if i.status not in ("verified", "waived")]
    total_req = len(req_items)
    pct = int(round((len(verified_req) / total_req) * 100)) if total_req else 100
    return {
        "total_items": len(items),
        "required_items": total_req,
        "verified_required_items": len(verified_req),
        "unverified_required_codes": [i.code for i in unverified_req],
        "all_required_verified": len(unverified_req) == 0,
        "completeness_pct": pct,
    }


def deal_to_dict(deal: Deal) -> Dict[str, Any]:
    items = [checklist_item_to_dict(i) for i in (deal.checklist_items or [])]
    return {
        "id": deal.id,
        "deal_reference": deal.deal_reference,
        "lead_id": deal.lead_id,
        "lead_name": deal.lead.name if deal.lead else None,
        "lead_status": deal.lead.status if deal.lead else None,
        "customer_id": deal.customer_id,
        "property_id": deal.property_id,
        "property_title": deal.property_record.title if deal.property_record else None,
        "property_location": deal.property_record.location if deal.property_record else None,
        "property_availability": deal.property_record.availability if deal.property_record else None,
        "offer_id": deal.offer_id,
        "assigned_agent_id": deal.assigned_agent_id,
        "assigned_agent_name": deal.assigned_agent.full_name if deal.assigned_agent else None,
        "transaction_type": deal.transaction_type,
        "agreed_amount": deal.agreed_amount,
        "currency": deal.currency,
        "payment_frequency": deal.payment_frequency,
        "status": deal.status,
        "allowed_next_stages": list(ALLOWED_DEAL_TRANSITIONS.get(deal.status, ())),
        "estimated_commission": deal.estimated_commission,
        "estimated_commission_pct": deal.estimated_commission_pct,
        "actual_commission": deal.actual_commission,
        "commission_status": deal.commission_status,
        "commission_verified_by_id": deal.commission_verified_by_id,
        "commission_verified_at": format_utc_iso(deal.commission_verified_at),
        "reservation_date": format_utc_iso(deal.reservation_date),
        "target_completion_date": format_utc_iso(deal.target_completion_date),
        "actual_completion_date": format_utc_iso(deal.actual_completion_date),
        "cancellation_or_failure_reason": deal.cancellation_or_failure_reason,
        "notes": deal.notes,
        "stage_history": _safe_json_list(deal.stage_history),
        "checklist": items,
        "checklist_summary": deal_checklist_summary(deal),
        "created_by_id": deal.created_by_id,
        "updated_by_id": deal.updated_by_id,
        "created_at": format_utc_iso(deal.created_at),
        "updated_at": format_utc_iso(deal.updated_at),
    }


def _sync_lead_and_property_with_deal_stage(db: Session, deal: Deal, target_stage: str) -> None:
    """Keep Lead.status and Property.availability consistent with Deal stage."""
    lead = deal.lead
    prop = deal.property_record

    if lead is not None:
        if target_stage == "viewing" and lead.status in ("new", "contact_pending", "contacted", "qualified"):
            lead.status = "viewing"
        elif target_stage in (
            "offer_preparation",
            "negotiation",
            "offer_accepted",
            "reservation_pending",
            "reservation_confirmed",
            "documentation_pending",
            "transaction_pending_completion",
        ):
            if lead.status not in ("closed_won", "closed_lost"):
                lead.status = "negotiation"
        elif target_stage == "completed":
            lead.status = "closed_won"
        lead.last_interaction_at = datetime.utcnow()

    if prop is not None:
        if target_stage in ("reservation_confirmed", "documentation_pending", "transaction_pending_completion"):
            if prop.availability == "available":
                prop.availability = "reserved"
        elif target_stage == "completed":
            prop.availability = "sold" if deal.transaction_type == "purchase" else "rented"
        elif target_stage in ("cancelled", "failed"):
            if prop.availability == "reserved":
                other_active = (
                    db.query(Deal.id)
                    .filter(
                        Deal.property_id == prop.id,
                        Deal.id != deal.id,
                        Deal.status.in_(
                            ("reservation_confirmed", "documentation_pending", "transaction_pending_completion")
                        ),
                    )
                    .first()
                )
                if other_active is None:
                    prop.availability = "available"


def create_deal(
    db: Session,
    *,
    actor: Agent,
    lead: Lead,
    property_id: int,
    transaction_type: str,
    agreed_amount: float,
    currency: str = "AED",
    payment_frequency: Optional[str] = None,
    offer_id: Optional[int] = None,
    initial_status: str = "offer_preparation",
    estimated_commission_pct: Optional[float] = None,
    estimated_commission: Optional[float] = None,
    target_completion_date: Optional[datetime] = None,
    notes: Optional[str] = None,
    assigned_agent_id: Optional[int] = None,
    customer_id: Optional[int] = None,
) -> Deal:
    """Create a Deal record with default compliance checklist and duplicate-active-deal guard."""
    if transaction_type not in OFFER_INTENTS:
        raise ValueError(f"Invalid transaction_type. Allowed: {', '.join(OFFER_INTENTS)}")
    if agreed_amount is None or float(agreed_amount) <= 0:
        raise ValueError("agreed_amount must be greater than 0")
    cur = (currency or "AED").strip().upper()
    if len(cur) != 3 or not cur.isalpha():
        raise ValueError("currency must be a 3-letter ISO code (e.g. AED)")
    if initial_status not in DEAL_STAGES:
        raise ValueError(f"Invalid initial deal status. Allowed: {', '.join(DEAL_STAGES)}")
    if initial_status == "completed":
        raise ValueError(
            "A newly created deal cannot start in 'completed' status; checklist verification is required first"
        )

    prop = db.query(Property).filter(Property.id == property_id).first()
    if prop is None:
        raise LookupError(f"Property #{property_id} not found")
    if not prop.is_approved:
        raise ValueError("Cannot create a deal for an unapproved property")
    if prop.availability in ("sold", "rented", "off_market"):
        raise ValueError(f"Property #{property_id} is currently '{prop.availability}' and cannot be placed into a new deal")

    # Verify offer if supplied
    offer_obj = None
    if offer_id is not None:
        offer_obj = db.query(Offer).filter(Offer.id == offer_id).first()
        if offer_obj is None:
            raise LookupError(f"Offer #{offer_id} not found")
        if offer_obj.lead_id != lead.id or offer_obj.property_id != prop.id:
            raise ValueError("Selected offer does not match the deal's lead and property")
        if initial_status in ("offer_accepted", "reservation_pending", "reservation_confirmed") and offer_obj.status != "accepted":
            raise ValueError("Offer must be in 'accepted' status before advancing deal to offer_accepted/reservation")

    # Prevent accidental duplicate active deals for the same (lead_id, property_id)
    existing_active = (
        db.query(Deal)
        .filter(
            Deal.lead_id == lead.id,
            Deal.property_id == prop.id,
            Deal.status.notin_(TERMINAL_DEAL_STAGES),
        )
        .first()
    )
    if existing_active is not None:
        raise ValueError(
            f"DUPLICATE_ACTIVE_DEAL:{existing_active.id}:{existing_active.deal_reference}"
        )

    target_agent_id = assigned_agent_id or lead.assigned_agent_id or actor.id
    if target_agent_id != actor.id and not rbac.has_permission(actor, "leads.assign"):
        raise PermissionError("Only an administrator or sales manager can assign a deal to another agent")

    # Estimated commission calculation (never fabricates actual/paid commission)
    est_pct = float(estimated_commission_pct) if estimated_commission_pct is not None else (2.0 if transaction_type == "purchase" else 5.0)
    if est_pct < 0 or est_pct > 100:
        raise ValueError("estimated_commission_pct must be between 0 and 100")
    est_comm = (
        float(estimated_commission)
        if estimated_commission is not None
        else round((float(agreed_amount) * est_pct) / 100.0, 2)
    )
    if est_comm < 0:
        raise ValueError("estimated_commission cannot be negative")

    now = datetime.utcnow()
    resolved_customer_id = _resolve_lead_customer_id(db, lead, customer_id)

    with _DEAL_REF_LOCK:
        deal_ref = _generate_deal_reference(db)
        history = [
            {
                "from_status": None,
                "to_status": initial_status,
                "reason": "Deal created",
                "actor_id": actor.id,
                "actor_label": actor.email,
                "created_at": format_utc_iso(now),
            }
        ]
        deal = Deal(
            deal_reference=deal_ref,
            lead_id=lead.id,
            customer_id=resolved_customer_id,
            property_id=prop.id,
            offer_id=offer_obj.id if offer_obj else None,
            assigned_agent_id=target_agent_id,
            transaction_type=transaction_type,
            agreed_amount=float(agreed_amount),
            currency=cur,
            payment_frequency=payment_frequency or (offer_obj.payment_frequency if offer_obj else None),
            status=initial_status,
            estimated_commission=est_comm,
            estimated_commission_pct=est_pct,
            actual_commission=None,
            commission_status="estimated",
            reservation_date=now if initial_status == "reservation_confirmed" else None,
            target_completion_date=to_utc_naive(target_completion_date) if target_completion_date else None,
            notes=(notes or "").strip() or None,
            stage_history=json.dumps(history, ensure_ascii=False),
            created_by_id=actor.id,
            updated_by_id=actor.id,
        )
        db.add(deal)
        db.flush()

        for code, title, category, is_req in DEFAULT_DEAL_CHECKLIST:
            db.add(
                DealChecklistItem(
                    deal_id=deal.id,
                    code=code,
                    title=title,
                    category=category,
                    is_required=is_req,
                    status="pending",
                    responsible_user_id=target_agent_id,
                )
            )
        db.flush()

    db.refresh(deal)
    _sync_lead_and_property_with_deal_stage(db, deal, initial_status)
    db.flush()
    return deal


def transition_deal_stage(
    db: Session,
    *,
    actor: Agent,
    deal: Deal,
    target_status: str,
    reason: Optional[str] = None,
    confirm: bool = False,
    reopen: bool = False,
) -> Deal:
    """Validate and transition a Deal to `target_status`, enforcing checklist & approval gates."""
    if target_status not in DEAL_STAGES:
        raise ValueError(f"Invalid deal stage '{target_status}'. Allowed: {', '.join(DEAL_STAGES)}")

    prev = deal.status
    if prev == target_status:
        return deal

    if prev in TERMINAL_DEAL_STAGES:
        if not reopen:
            raise ValueError(
                f"Deal {deal.deal_reference} is in terminal status '{prev}'. Pass reopen=True with a reason to reopen."
            )
        if not rbac.has_permission(actor, "deals.approve"):
            raise PermissionError("Only an administrator or sales manager ('deals.approve') can reopen a terminal deal")
        if not (reason or "").strip():
            raise ValueError("A reason is required when reopening a terminal deal")
    else:
        allowed = ALLOWED_DEAL_TRANSITIONS.get(prev, ())
        if target_status not in allowed:
            raise ValueError(
                f"Invalid deal stage transition from '{prev}' to '{target_status}'. "
                f"Allowed from '{prev}': {', '.join(allowed)}"
            )

    if target_status in ("cancelled", "failed") and not (reason or "").strip():
        raise ValueError(f"A reason is required when marking a deal as '{target_status}'")

    if target_status in ("reservation_confirmed", "completed") and not confirm:
        raise ValueError(f"Explicit confirmation (confirm=True) is required to mark a deal as '{target_status}'")

    if target_status == "completed":
        if not rbac.has_permission(actor, "deals.approve"):
            raise PermissionError("Only an administrator or sales manager ('deals.approve') can mark a deal completed")
        summary = deal_checklist_summary(deal)
        if not summary["all_required_verified"]:
            missing_str = ", ".join(summary["unverified_required_codes"])
            raise ValueError(
                f"Cannot mark deal completed until all required compliance checklist items are verified "
                f"(unverified: {missing_str})"
            )

    now = datetime.utcnow()
    history = _safe_json_list(deal.stage_history)
    history.append({
        "from_status": prev,
        "to_status": target_status,
        "reason": (reason or "").strip() or None,
        "reopened": bool(prev in TERMINAL_DEAL_STAGES and reopen),
        "actor_id": actor.id,
        "actor_label": actor.email,
        "created_at": format_utc_iso(now),
    })
    deal.stage_history = json.dumps(history, ensure_ascii=False)
    deal.status = target_status
    if target_status == "reservation_confirmed" and deal.reservation_date is None:
        deal.reservation_date = now
    if target_status == "completed":
        deal.actual_completion_date = now
    if target_status in ("cancelled", "failed"):
        deal.cancellation_or_failure_reason = (reason or "").strip()
    deal.updated_by_id = actor.id
    deal.updated_at = now

    _sync_lead_and_property_with_deal_stage(db, deal, target_status)
    db.flush()
    return deal


def update_deal_checklist_item(
    db: Session,
    *,
    actor: Agent,
    deal: Deal,
    item: DealChecklistItem,
    status: Optional[str] = None,
    document_reference: Optional[str] = None,
    notes: Optional[str] = None,
    responsible_user_id: Optional[int] = None,
) -> DealChecklistItem:
    """Update or verify a checklist item on a Deal."""
    if status is not None:
        if status not in CHECKLIST_STATUSES:
            raise ValueError(f"Invalid checklist status. Allowed: {', '.join(CHECKLIST_STATUSES)}")
        if status in ("verified", "waived"):
            if not rbac.has_any_permission(actor, ("deals.checklist_verify", "deals.approve")):
                raise PermissionError(
                    "Only an administrator or authorized manager ('deals.checklist_verify') can mark checklist items verified or waived"
                )
            if status == "waived" and not (notes or item.notes or "").strip():
                raise ValueError("Notes explaining the reason are required when waiving a checklist item")
            item.verified_by_id = actor.id
            item.verified_by_label = actor.email
            item.verified_at = datetime.utcnow()
        else:
            item.verified_by_id = None
            item.verified_by_label = None
            item.verified_at = None
        item.status = status

    if document_reference is not None:
        item.document_reference = document_reference.strip() or None
    if notes is not None:
        item.notes = notes.strip() or None
    if responsible_user_id is not None:
        item.responsible_user_id = responsible_user_id
    item.updated_at = datetime.utcnow()
    deal.updated_by_id = actor.id
    deal.updated_at = datetime.utcnow()
    db.flush()
    return item


def compute_sales_ops_summary(db: Session, agent: Agent) -> Dict[str, Any]:
    """Compute real, scoped dashboard counts for Appointments, Viewings, Offers & Deals."""
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start = today_start + timedelta(days=1)

    appt_q = scoped_appointment_query(db, agent)
    all_appts = appt_q.all()

    appts_today = 0
    upcoming_viewings = 0
    overdue_appointments = 0
    conflict_flagged_viewings = 0
    by_appt_status: Dict[str, int] = {s: 0 for s in APPOINTMENT_STATUSES}

    for a in all_appts:
        by_appt_status[a.status] = by_appt_status.get(a.status, 0) + 1
        if a.status in ACTIVE_APPOINTMENT_STATUSES:
            if today_start <= a.start_at < tomorrow_start:
                appts_today += 1
            if a.appointment_type == "viewing" and a.start_at >= now:
                upcoming_viewings += 1
            if a.end_at < now:
                overdue_appointments += 1
            if a.property_record is not None and (
                not a.property_record.is_approved or a.property_record.availability != "available"
            ):
                conflict_flagged_viewings += 1

    offer_q = scoped_offer_query(db, agent)
    all_offers = offer_q.all()
    by_offer_status: Dict[str, int] = {s: 0 for s in OFFER_STATUSES}
    for o in all_offers:
        by_offer_status[o.status] = by_offer_status.get(o.status, 0) + 1

    deal_q = scoped_deal_query(db, agent)
    all_deals = deal_q.all()
    by_deal_stage: Dict[str, int] = {s: 0 for s in DEAL_STAGES}
    active_pipeline_value = 0.0
    completed_deal_value = 0.0
    estimated_commission_total = 0.0
    verified_commission_total = 0.0

    for d in all_deals:
        by_deal_stage[d.status] = by_deal_stage.get(d.status, 0) + 1
        if d.status not in TERMINAL_DEAL_STAGES:
            active_pipeline_value += float(d.agreed_amount or 0.0)
            estimated_commission_total += float(d.estimated_commission or 0.0)
        elif d.status == "completed":
            completed_deal_value += float(d.agreed_amount or 0.0)
        if d.commission_status in ("verified", "earned", "paid") and d.actual_commission is not None:
            verified_commission_total += float(d.actual_commission)

    return {
        "appointments": {
            "total": len(all_appts),
            "today": appts_today,
            "upcoming_viewings": upcoming_viewings,
            "overdue_action_needed": overdue_appointments,
            "property_conflicts": conflict_flagged_viewings,
            "by_status": by_appt_status,
        },
        "offers": {
            "total": len(all_offers),
            "active_negotiations": by_offer_status.get("submitted", 0) + by_offer_status.get("countered", 0),
            "accepted": by_offer_status.get("accepted", 0),
            "by_status": by_offer_status,
        },
        "deals": {
            "total": len(all_deals),
            "active": sum(v for k, v in by_deal_stage.items() if k not in TERMINAL_DEAL_STAGES),
            "completed": by_deal_stage.get("completed", 0),
            "active_pipeline_value_aed": round(active_pipeline_value, 2),
            "completed_deal_value_aed": round(completed_deal_value, 2),
            "estimated_commission_aed": round(estimated_commission_total, 2),
            "verified_commission_aed": round(verified_commission_total, 2),
            "by_stage": by_deal_stage,
        },
    }

