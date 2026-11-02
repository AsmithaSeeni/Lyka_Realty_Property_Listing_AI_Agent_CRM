"""Customer operations, notifications, preferences, and portal workflows (Phase H).

Provides:
- Profile completion and preference management
- In-app notification dispatcher with idempotency & deduplication
- Structured customer-agent communication & internal staff note isolation
- Customer viewing request lifecycle (request -> accept/reject -> reschedule/cancel)
- Agent customer dossier and viewing request queue
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.database import (
    Agent,
    Appointment,
    AuditLog,
    Conversation,
    Customer,
    CustomerCommunication,
    CustomerNotification,
    Lead,
    Property,
    SavedProperty,
)
from app.services import audit as auditlog
from app.services import rbac
from app.services.sales_ops import (
    ACTIVE_APPOINTMENT_STATUSES,
    AppointmentConflictError,
    find_agent_conflicts,
    format_local_iso,
    format_utc_iso,
    resolve_tz,
    to_utc_naive,
)
from app.services.property_search import get_property_by_id


# ---------------------------------------------------------------------------
# Profile & Preferences
# ---------------------------------------------------------------------------

PREFERENCE_FIELDS = [
    ("name", "Full Name", 15),
    ("email", "Email Address", 15),
    ("phone", "Phone Number", 15),
    ("preferred_contact_method", "Contact Method", 10),
    ("purpose", "Intent (Buy / Rent / Invest)", 10),
    ("preferred_locations", "Preferred Locations", 15),
    ("property_type", "Property Type", 10),
    ("budget_max", "Budget", 10),
]


def calculate_profile_completion(customer: Customer) -> Dict[str, Any]:
    """Calculate profile completion percentage and missing fields based on verified fields."""
    completed = []
    missing = []
    score = 0
    total_possible = sum(weight for _, _, weight in PREFERENCE_FIELDS)

    for field_name, label, weight in PREFERENCE_FIELDS:
        val = getattr(customer, field_name, None)
        if val is not None and str(val).strip():
            score += weight
            completed.append({"field": field_name, "label": label})
        else:
            missing.append({"field": field_name, "label": label})

    pct = int(round((score / total_possible) * 100)) if total_possible > 0 else 0
    return {
        "percentage": min(100, max(0, pct)),
        "completed_count": len(completed),
        "total_count": len(PREFERENCE_FIELDS),
        "missing_fields": missing,
        "completed_fields": completed,
    }


def customer_profile_dict(customer: Customer) -> Dict[str, Any]:
    """Serialize full customer profile including preferences and completion score."""
    locations = []
    if customer.preferred_locations:
        try:
            parsed = json.loads(customer.preferred_locations)
            if isinstance(parsed, list):
                locations = parsed
            else:
                locations = [str(customer.preferred_locations)]
        except Exception:
            locations = [loc.strip() for loc in customer.preferred_locations.split(",") if loc.strip()]

    completion = calculate_profile_completion(customer)

    return {
        "id": customer.id,
        "name": customer.name,
        "email": customer.email,
        "phone": customer.phone,
        "preferred_contact_method": customer.preferred_contact_method or "email",
        "purpose": customer.purpose,
        "preferred_locations": locations,
        "property_type": customer.property_type,
        "bedrooms_min": customer.bedrooms_min,
        "bedrooms_max": customer.bedrooms_max,
        "budget_min": customer.budget_min,
        "budget_max": customer.budget_max,
        "budget_currency": customer.budget_currency or "AED",
        "profile_completion": completion,
        "created_at": format_utc_iso(customer.created_at),
        "updated_at": format_utc_iso(customer.updated_at),
    }


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

def create_notification(
    db: Session,
    *,
    recipient_type: str,
    title: str,
    message: str,
    customer_id: Optional[int] = None,
    agent_id: Optional[int] = None,
    category: str = "general",
    related_type: Optional[str] = None,
    related_id: Optional[int] = None,
    action_url: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> CustomerNotification:
    """Create a persistent in-app notification with deduplication."""
    if recipient_type not in ("customer", "agent"):
        raise ValueError(f"Invalid recipient_type: {recipient_type}")

    if idempotency_key:
        existing = (
            db.query(CustomerNotification)
            .filter(CustomerNotification.idempotency_key == idempotency_key)
            .first()
        )
        if existing is not None:
            return existing

    notif = CustomerNotification(
        recipient_type=recipient_type,
        customer_id=customer_id,
        agent_id=agent_id,
        category=category,
        title=title,
        message=message,
        related_type=related_type,
        related_id=related_id,
        action_url=action_url,
        is_read=False,
        idempotency_key=idempotency_key,
        created_at=datetime.utcnow(),
    )
    db.add(notif)
    db.commit()
    db.refresh(notif)
    return notif


def mark_notification_read(
    db: Session,
    notification_id: int,
    *,
    customer_id: Optional[int] = None,
    agent_id: Optional[int] = None,
) -> CustomerNotification:
    """Mark a single notification as read, enforcing recipient boundary."""
    q = db.query(CustomerNotification).filter(CustomerNotification.id == notification_id)
    if customer_id is not None:
        q = q.filter(CustomerNotification.customer_id == customer_id, CustomerNotification.recipient_type == "customer")
    elif agent_id is not None:
        q = q.filter(CustomerNotification.agent_id == agent_id, CustomerNotification.recipient_type == "agent")

    notif = q.first()
    if notif is None:
        raise LookupError("Notification not found or access denied")

    if not notif.is_read:
        notif.is_read = True
        notif.read_at = datetime.utcnow()
        db.commit()
        db.refresh(notif)
    return notif


def mark_all_notifications_read(
    db: Session,
    *,
    customer_id: Optional[int] = None,
    agent_id: Optional[int] = None,
) -> int:
    """Mark all unread notifications as read for a customer or agent."""
    q = db.query(CustomerNotification).filter(CustomerNotification.is_read.is_(False))
    if customer_id is not None:
        q = q.filter(CustomerNotification.customer_id == customer_id, CustomerNotification.recipient_type == "customer")
    elif agent_id is not None:
        q = q.filter(CustomerNotification.agent_id == agent_id, CustomerNotification.recipient_type == "agent")
    else:
        return 0

    unread = q.all()
    count = len(unread)
    now = datetime.utcnow()
    for notif in unread:
        notif.is_read = True
        notif.read_at = now
    db.commit()
    return count


def get_unread_notification_count(
    db: Session,
    *,
    customer_id: Optional[int] = None,
    agent_id: Optional[int] = None,
) -> int:
    """Count unread notifications."""
    q = db.query(func.count(CustomerNotification.id)).filter(CustomerNotification.is_read.is_(False))
    if customer_id is not None:
        q = q.filter(CustomerNotification.customer_id == customer_id, CustomerNotification.recipient_type == "customer")
    elif agent_id is not None:
        q = q.filter(CustomerNotification.agent_id == agent_id, CustomerNotification.recipient_type == "agent")
    else:
        return 0
    return int(q.scalar() or 0)


def notification_to_dict(notif: CustomerNotification) -> Dict[str, Any]:
    return {
        "id": notif.id,
        "recipient_type": notif.recipient_type,
        "category": notif.category,
        "title": notif.title,
        "message": notif.message,
        "related_type": notif.related_type,
        "related_id": notif.related_id,
        "action_url": notif.action_url,
        "is_read": notif.is_read,
        "read_at": format_utc_iso(notif.read_at) if notif.read_at else None,
        "created_at": format_utc_iso(notif.created_at),
    }


# ---------------------------------------------------------------------------
# Communications
# ---------------------------------------------------------------------------

def log_communication(
    db: Session,
    *,
    customer_id: int,
    sender_type: str,
    message: str,
    sender_agent_id: Optional[int] = None,
    lead_id: Optional[int] = None,
    property_id: Optional[int] = None,
    appointment_id: Optional[int] = None,
    channel: str = "portal",
    subject: Optional[str] = None,
    is_customer_visible: bool = True,
    follow_up_needed: bool = False,
) -> CustomerCommunication:
    """Log a structured communication or internal staff note."""
    if sender_type not in ("customer", "agent", "system"):
        raise ValueError(f"Invalid sender_type: {sender_type}")

    # If sender is customer, it MUST be customer-visible
    if sender_type == "customer":
        is_customer_visible = True

    comm = CustomerCommunication(
        customer_id=customer_id,
        lead_id=lead_id,
        property_id=property_id,
        appointment_id=appointment_id,
        sender_type=sender_type,
        sender_agent_id=sender_agent_id,
        channel=channel,
        subject=(subject or "").strip() or None,
        message=message.strip(),
        is_customer_visible=bool(is_customer_visible),
        follow_up_needed=bool(follow_up_needed),
        follow_up_status="pending" if follow_up_needed else None,
        created_at=datetime.utcnow(),
    )
    db.add(comm)
    db.commit()
    db.refresh(comm)
    return comm


def get_customer_communications(
    db: Session,
    customer_id: int,
    *,
    include_internal: bool = False,
    appointment_id: Optional[int] = None,
    limit: int = 100,
) -> List[CustomerCommunication]:
    """Retrieve communication thread. Internal staff notes hidden unless include_internal=True."""
    q = db.query(CustomerCommunication).filter(CustomerCommunication.customer_id == customer_id)
    if not include_internal:
        q = q.filter(CustomerCommunication.is_customer_visible.is_(True))
    if appointment_id is not None:
        q = q.filter(CustomerCommunication.appointment_id == appointment_id)

    return q.order_by(CustomerCommunication.created_at.asc()).limit(limit).all()


def communication_to_dict(comm: CustomerCommunication, include_internal: bool = False) -> Dict[str, Any]:
    sender_name = "System"
    if comm.sender_type == "customer":
        sender_name = comm.customer.name or comm.customer.email or "Customer"
    elif comm.sender_type == "agent":
        sender_name = comm.sender_agent.full_name if comm.sender_agent else "Lyka Agent"

    res = {
        "id": comm.id,
        "customer_id": comm.customer_id,
        "lead_id": comm.lead_id,
        "property_id": comm.property_id,
        "appointment_id": comm.appointment_id,
        "sender_type": comm.sender_type,
        "sender_name": sender_name,
        "channel": comm.channel,
        "subject": comm.subject,
        "message": comm.message,
        "is_customer_visible": comm.is_customer_visible,
        "follow_up_needed": comm.follow_up_needed,
        "follow_up_status": comm.follow_up_status,
        "created_at": format_utc_iso(comm.created_at),
    }
    if not include_internal:
        # Guarantee internal flags do not leak in customer payload
        res.pop("follow_up_needed", None)
        res.pop("follow_up_status", None)
    return res


# ---------------------------------------------------------------------------
# Customer Viewing Request Lifecycle
# ---------------------------------------------------------------------------

def _resolve_property_for_customer(db: Session, property_id: int, source: str = "record") -> Property:
    """Resolve a property record, creating an on-demand record for dataset items to enforce referential integrity."""
    if source == "record":
        prop = db.query(Property).filter(Property.id == property_id).first()
        if prop is None:
            raise LookupError(f"Property #{property_id} not found")
        if not prop.is_approved or not getattr(prop, "is_published", False) or prop.availability != "available":
            raise ValueError(f"Property #{property_id} ({prop.title}) is currently not available for viewings")
        return prop

    # Dataset listing: check dataset item existence
    ds_row = get_property_by_id(property_id)
    if ds_row is None:
        raise LookupError(f"Dataset property #{property_id} not found")

    ext_ref = f"DATASET-{property_id}"
    prop = db.query(Property).filter(Property.external_ref == ext_ref).first()
    if prop is None:
        # Create an authorized DB record representation for this dataset viewing
        price_val = 0.0
        try:
            raw_p = str(ds_row.get("price") or "0").replace(",", "").replace("AED", "").strip()
            price_val = float(raw_p) if raw_p else 0.0
        except Exception:
            price_val = 0.0

        prop = Property(
            external_ref=ext_ref,
            title=ds_row.get("title") or f"Property #{property_id}",
            description=ds_row.get("highlights") or f"Dataset property #{property_id}",
            purpose="sale",
            availability="available",
            price=price_val,
            currency="AED",
            property_type=ds_row.get("property_type") or "Apartment",
            location=ds_row.get("location") or "Dubai",
            bedrooms=int(ds_row.get("bedrooms") or 1),
            bathrooms=int(float(ds_row.get("bathrooms") or 1)),
            is_approved=True,
            is_published=True,
            verification_status="verified",
            is_demo=False,
            source="dataset_viewing",
            created_at=datetime.utcnow(),
        )
        db.add(prop)
        db.commit()
        db.refresh(prop)
    return prop


def _find_or_create_customer_lead(db: Session, customer: Customer) -> Lead:
    """Ensure customer has an associated Lead record so appointment relationships are satisfied."""
    # Look for existing lead linked to customer via Conversation
    conv = (
        db.query(Conversation)
        .filter(Conversation.customer_id == customer.id, Conversation.lead_id.isnot(None))
        .order_by(Conversation.id.desc())
        .first()
    )
    if conv is not None and conv.lead is not None:
        return conv.lead

    # Look for existing lead matching phone or email
    lead = None
    if customer.email:
        lead = db.query(Lead).filter(func.lower(Lead.email) == customer.email.lower()).first()
    if lead is None and customer.phone:
        lead = db.query(Lead).filter(Lead.phone == customer.phone).first()

    if lead is not None:
        return lead

    # Assign default active agent
    agent = db.query(Agent).filter(Agent.is_active.is_(True), Agent.role.in_(("agent", "sales_manager"))).first()
    if agent is None:
        agent = db.query(Agent).filter(Agent.is_active.is_(True)).first()

    lead = Lead(
        name=customer.name or "Portal Customer",
        email=customer.email,
        phone=customer.phone,
        source="Customer Portal",
        status="viewing",
        assigned_agent_id=agent.id if agent else None,
        property_type=customer.property_type,
        location=customer.preferred_locations,
        budget_min=customer.budget_min,
        budget_max=customer.budget_max,
        buy_rent=customer.purpose or "buy",
        created_at=datetime.utcnow(),
    )
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


def request_viewing(
    db: Session,
    *,
    customer: Customer,
    property_id: int,
    start_at: datetime,
    end_at: datetime,
    property_source: str = "record",
    timezone_name: str = "Asia/Dubai",
    meeting_method: str = "in_person",
    location_or_link: Optional[str] = None,
    customer_notes: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> Tuple[Appointment, bool]:
    """Customer submits a viewing request.

    Starts with status="scheduled", customer_confirmation_status="pending".
    Never auto-confirmed. Triggers notifications to both agent and customer.
    """
    if idempotency_key:
        existing = db.query(Appointment).filter(Appointment.idempotency_key == idempotency_key).first()
        if existing is not None:
            return existing, True

    _, norm_tz = resolve_tz(timezone_name)
    utc_start = to_utc_naive(start_at, norm_tz)
    utc_end = to_utc_naive(end_at, norm_tz)

    if utc_end <= utc_start:
        raise ValueError("Viewing end time must be after start time")
    if (utc_end - utc_start) > timedelta(hours=24):
        raise ValueError("Viewing duration cannot exceed 24 hours")

    prop = _resolve_property_for_customer(db, property_id, property_source)
    lead = _find_or_create_customer_lead(db, customer)

    # Determine assigned agent
    assigned_agent_id = lead.assigned_agent_id
    if not assigned_agent_id:
        agent = db.query(Agent).filter(Agent.is_active.is_(True)).first()
        assigned_agent_id = agent.id if agent else 1

    appt = Appointment(
        lead_id=lead.id,
        customer_id=customer.id,
        property_id=prop.id,
        additional_property_ids="[]",
        assigned_agent_id=assigned_agent_id,
        appointment_type="viewing",
        start_at=utc_start,
        end_at=utc_end,
        timezone=norm_tz,
        meeting_method=meeting_method,
        location_or_link=location_or_link or prop.location,
        status="scheduled",
        customer_confirmation_status="pending",
        notes=f"Customer Viewing Request: {customer_notes}" if customer_notes else "Customer requested property viewing",
        idempotency_key=idempotency_key,
        created_at=datetime.utcnow(),
    )
    db.add(appt)
    db.commit()
    db.refresh(appt)

    # Dispatch Customer Notification
    create_notification(
        db,
        recipient_type="customer",
        customer_id=customer.id,
        category="viewing",
        title="Viewing Request Received",
        message=f"We have received your viewing request for {prop.title} on {format_local_iso(utc_start, norm_tz)}. Our sales team will confirm shortly.",
        related_type="appointment",
        related_id=appt.id,
        action_url="/portal/appointments",
        idempotency_key=f"notif-cust-req-{appt.id}",
    )

    # Dispatch Agent Notification
    create_notification(
        db,
        recipient_type="agent",
        agent_id=assigned_agent_id,
        category="viewing",
        title="New Viewing Request",
        message=f"{customer.name or customer.email or 'A customer'} requested a viewing for {prop.title} at {format_local_iso(utc_start, norm_tz)}.",
        related_type="appointment",
        related_id=appt.id,
        action_url="/agent/appointments",
        idempotency_key=f"notif-agent-req-{appt.id}",
    )

    # Log initial communication
    log_communication(
        db,
        customer_id=customer.id,
        lead_id=lead.id,
        property_id=prop.id,
        appointment_id=appt.id,
        sender_type="customer",
        channel="portal",
        subject=f"Viewing Request: {prop.title}",
        message=customer_notes or f"Requested property viewing for {prop.title} on {format_local_iso(utc_start, norm_tz)}.",
        is_customer_visible=True,
    )

    auditlog.write_audit(
        db,
        "customer.viewing.requested",
        actor_type="customer",
        actor_id=customer.id,
        actor_label=customer.email,
        subject_type="appointment",
        subject_id=appt.id,
        detail=f"property_id={prop.id}",
    )

    return appt, False


def accept_viewing_request(
    db: Session,
    *,
    appt_id: int,
    agent: Agent,
    conflict_override: bool = False,
    conflict_override_reason: Optional[str] = None,
) -> Appointment:
    """Agent accepts and confirms a customer viewing request."""
    appt = db.query(Appointment).filter(Appointment.id == appt_id).first()
    if appt is None:
        raise LookupError(f"Appointment #{appt_id} not found")

    if not rbac.has_permission(agent, "leads.read_all") and appt.assigned_agent_id != agent.id:
        raise PermissionError("Access denied: appointment belongs to another sales agent")

    # Conflict check
    conflicts = find_agent_conflicts(
        db,
        assigned_agent_id=appt.assigned_agent_id,
        start_at=appt.start_at,
        end_at=appt.end_at,
        exclude_appointment_id=appt.id,
    )
    if conflicts and not conflict_override:
        raise AppointmentConflictError([
            {"id": c.id, "start_at": format_utc_iso(c.start_at), "end_at": format_utc_iso(c.end_at)}
            for c in conflicts
        ])

    appt.status = "confirmed"
    appt.customer_confirmation_status = "confirmed"
    appt.updated_by_id = agent.id
    if conflict_override and conflict_override_reason:
        appt.conflict_override_reason = conflict_override_reason.strip()
    db.commit()
    db.refresh(appt)

    # Customer notification
    if appt.customer_id:
        prop_title = appt.property_record.title if appt.property_record else "Property"
        tz_name = appt.timezone or "Asia/Dubai"
        create_notification(
            db,
            recipient_type="customer",
            customer_id=appt.customer_id,
            category="viewing",
            title="Viewing Confirmed!",
            message=f"Your viewing for {prop_title} has been confirmed for {format_local_iso(appt.start_at, tz_name)}. Your assigned agent is {agent.full_name}.",
            related_type="appointment",
            related_id=appt.id,
            action_url="/portal/appointments",
            idempotency_key=f"notif-cust-confirmed-{appt.id}",
        )

        log_communication(
            db,
            customer_id=appt.customer_id,
            lead_id=appt.lead_id,
            property_id=appt.property_id,
            appointment_id=appt.id,
            sender_type="agent",
            sender_agent_id=agent.id,
            channel="portal",
            subject=f"Viewing Confirmed: {prop_title}",
            message=f"I have confirmed your viewing appointment for {prop_title} on {format_local_iso(appt.start_at, tz_name)}. Looking forward to meeting you!",
            is_customer_visible=True,
        )

    auditlog.write_audit(
        db,
        "agent.viewing.accepted",
        actor_type="staff",
        actor_id=agent.id,
        actor_label=agent.email,
        subject_type="appointment",
        subject_id=appt.id,
    )

    return appt


def reject_viewing_request(
    db: Session,
    *,
    appt_id: int,
    agent: Agent,
    reason: str,
) -> Appointment:
    """Agent rejects or declines a customer viewing request."""
    appt = db.query(Appointment).filter(Appointment.id == appt_id).first()
    if appt is None:
        raise LookupError(f"Appointment #{appt_id} not found")

    if not rbac.has_permission(agent, "leads.read_all") and appt.assigned_agent_id != agent.id:
        raise PermissionError("Access denied: appointment belongs to another sales agent")

    appt.status = "cancelled"
    appt.customer_confirmation_status = "declined"
    appt.cancellation_reason = reason.strip()
    appt.updated_by_id = agent.id
    db.commit()
    db.refresh(appt)

    # Customer notification
    if appt.customer_id:
        prop_title = appt.property_record.title if appt.property_record else "Property"
        create_notification(
            db,
            recipient_type="customer",
            customer_id=appt.customer_id,
            category="viewing",
            title="Viewing Request Update",
            message=f"Unfortunately, your viewing request for {prop_title} could not be confirmed: {reason}. Please request an alternative time or contact your agent.",
            related_type="appointment",
            related_id=appt.id,
            action_url="/portal/appointments",
            idempotency_key=f"notif-cust-rejected-{appt.id}",
        )

        log_communication(
            db,
            customer_id=appt.customer_id,
            lead_id=appt.lead_id,
            property_id=appt.property_id,
            appointment_id=appt.id,
            sender_type="agent",
            sender_agent_id=agent.id,
            channel="portal",
            subject=f"Viewing Request Unavailable: {prop_title}",
            message=f"We are unable to confirm the requested viewing time for {prop_title}. Reason: {reason}. Please feel free to suggest an alternative time slot.",
            is_customer_visible=True,
        )

    auditlog.write_audit(
        db,
        "agent.viewing.rejected",
        actor_type="staff",
        actor_id=agent.id,
        actor_label=agent.email,
        subject_type="appointment",
        subject_id=appt.id,
        detail=f"reason={reason[:200]}",
    )

    return appt


def customer_reschedule_viewing(
    db: Session,
    *,
    appt_id: int,
    customer: Customer,
    new_start_at: datetime,
    new_end_at: datetime,
    reason: Optional[str] = None,
) -> Appointment:
    """Customer requests reschedule of an existing viewing."""
    appt = db.query(Appointment).filter(Appointment.id == appt_id, Appointment.customer_id == customer.id).first()
    if appt is None:
        raise LookupError("Appointment not found or does not belong to you")

    if appt.status in ("cancelled", "completed"):
        raise ValueError(f"Cannot reschedule an appointment that is already {appt.status}")

    norm_tz = appt.timezone or "Asia/Dubai"
    utc_start = to_utc_naive(new_start_at, norm_tz)
    utc_end = to_utc_naive(new_end_at, norm_tz)
    if utc_end <= utc_start:
        raise ValueError("End time must be after start time")

    # Record history
    history = []
    try:
        history = json.loads(appt.reschedule_history or "[]")
    except Exception:
        history = []

    history.append({
        "requested_by": "customer",
        "previous_start_at": format_utc_iso(appt.start_at),
        "previous_end_at": format_utc_iso(appt.end_at),
        "new_start_at": format_utc_iso(utc_start),
        "new_end_at": format_utc_iso(utc_end),
        "reason": reason,
        "at": format_utc_iso(datetime.utcnow()),
    })

    appt.start_at = utc_start
    appt.end_at = utc_end
    appt.reschedule_reason = reason
    appt.reschedule_history = json.dumps(history)
    appt.customer_confirmation_status = "reschedule_requested"
    appt.status = "rescheduled"
    db.commit()
    db.refresh(appt)

    # Notify agent
    prop_title = appt.property_record.title if appt.property_record else "Property"
    create_notification(
        db,
        recipient_type="agent",
        agent_id=appt.assigned_agent_id,
        category="viewing",
        title="Viewing Reschedule Requested",
        message=f"{customer.name or customer.email} requested to reschedule viewing for {prop_title} to {format_local_iso(utc_start, norm_tz)}.",
        related_type="appointment",
        related_id=appt.id,
        action_url="/agent/appointments",
    )

    # Notify customer
    create_notification(
        db,
        recipient_type="customer",
        customer_id=customer.id,
        category="viewing",
        title="Reschedule Requested",
        message=f"Your request to reschedule {prop_title} to {format_local_iso(utc_start, norm_tz)} has been submitted for agent confirmation.",
        related_type="appointment",
        related_id=appt.id,
        action_url="/portal/appointments",
    )

    log_communication(
        db,
        customer_id=customer.id,
        lead_id=appt.lead_id,
        property_id=appt.property_id,
        appointment_id=appt.id,
        sender_type="customer",
        channel="portal",
        subject=f"Reschedule Requested: {prop_title}",
        message=f"Requested reschedule to {format_local_iso(utc_start, norm_tz)}. Note: {reason or 'None'}",
        is_customer_visible=True,
    )

    return appt


def customer_cancel_viewing(
    db: Session,
    *,
    appt_id: int,
    customer: Customer,
    reason: Optional[str] = None,
) -> Appointment:
    """Customer cancels their viewing request or appointment."""
    appt = db.query(Appointment).filter(Appointment.id == appt_id, Appointment.customer_id == customer.id).first()
    if appt is None:
        raise LookupError("Appointment not found or does not belong to you")

    if appt.status in ("cancelled", "completed"):
        raise ValueError(f"Appointment is already {appt.status}")

    cancel_note = f"Cancelled by customer: {reason.strip() if reason else 'No reason provided'}"
    appt.status = "cancelled"
    appt.customer_confirmation_status = "declined"
    appt.cancellation_reason = cancel_note
    db.commit()
    db.refresh(appt)

    prop_title = appt.property_record.title if appt.property_record else "Property"

    # Notify agent
    create_notification(
        db,
        recipient_type="agent",
        agent_id=appt.assigned_agent_id,
        category="viewing",
        title="Viewing Cancelled by Customer",
        message=f"{customer.name or customer.email} cancelled viewing for {prop_title}. Reason: {reason or 'None'}",
        related_type="appointment",
        related_id=appt.id,
        action_url="/agent/appointments",
    )

    # Notify customer
    create_notification(
        db,
        recipient_type="customer",
        customer_id=customer.id,
        category="viewing",
        title="Viewing Cancelled",
        message=f"Your viewing for {prop_title} has been cancelled.",
        related_type="appointment",
        related_id=appt.id,
        action_url="/portal/appointments",
    )

    log_communication(
        db,
        customer_id=customer.id,
        lead_id=appt.lead_id,
        property_id=appt.property_id,
        appointment_id=appt.id,
        sender_type="customer",
        channel="portal",
        subject=f"Viewing Cancelled: {prop_title}",
        message=f"Cancelled viewing. Reason: {reason or 'None'}",
        is_customer_visible=True,
    )

    return appt


def customer_appointment_to_dict(appt: Appointment, db: Optional[Session] = None) -> Dict[str, Any]:
    """Serialize an appointment for customer viewing with public agent and property details."""
    prop_title = None
    prop_location = None
    prop_price = None
    prop_bedrooms = None
    prop_type = None

    if appt.property_record:
        prop_title = appt.property_record.title
        prop_location = appt.property_record.location
        prop_price = appt.property_record.price
        prop_bedrooms = appt.property_record.bedrooms
        prop_type = appt.property_record.property_type

    tz_name = appt.timezone or "Asia/Dubai"
    return {
        "id": appt.id,
        "property_id": appt.property_id,
        "property_title": prop_title,
        "property_location": prop_location,
        "property_price": prop_price,
        "property_bedrooms": prop_bedrooms,
        "property_type": prop_type,
        "agent_name": appt.assigned_agent.full_name if appt.assigned_agent else "Lyka Property Specialist",
        "appointment_type": appt.appointment_type,
        "status": appt.status,
        "customer_confirmation_status": appt.customer_confirmation_status,
        "start_at": format_utc_iso(appt.start_at),
        "end_at": format_utc_iso(appt.end_at),
        "start_at_local": format_local_iso(appt.start_at, tz_name),
        "end_at_local": format_local_iso(appt.end_at, tz_name),
        "timezone": tz_name,
        "meeting_method": appt.meeting_method,
        "location_or_link": appt.location_or_link,
        "notes": appt.notes,
        "cancellation_reason": appt.cancellation_reason,
        "reschedule_reason": appt.reschedule_reason,
        "created_at": format_utc_iso(appt.created_at),
    }

