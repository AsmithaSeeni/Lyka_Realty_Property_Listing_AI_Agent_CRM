"""Follow-up management on the existing Phase 2 `follow_ups` table (Phase 5).

No duplicate table, no migrations: this module only reads/writes the rows
the schema already supports (lead FK, optional assigned agent, `type` from
the CHECK set call|email|whatsapp|viewing|general, notes, `due_at`,
`is_completed`, `completed_at`).

Timezone policy (applied everywhere, documented and consistent):
- The database stores NAIVE UTC datetimes (same convention as every other
  timestamp in this project — created_at etc. use `datetime.utcnow()`).
- The API accepts ISO-8601 strings. An aware value ("Z" or an offset) is
  converted to UTC; a naive value is INTERPRETED as UTC (never silently
  shifted to another zone).
- The API serialises its own datetimes with an explicit "Z" suffix so
  browsers render the correct instant.
- Overdue / due-today / upcoming buckets are UTC calendar-day buckets over
  PENDING (not completed) rows, and they partition pending rows exactly:
    overdue   → due_at is before today (UTC)
    due_today → due_at is any time today (UTC)
    upcoming  → due_at is tomorrow or later (UTC)
  Completed rows appear only under the "completed" filter.

Out of scope (per Phase 5): no emails/SMS/WhatsApp are ever SENT — the
`type` column is a label only — and no background scheduler exists.
"""

from datetime import datetime, time, timedelta, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from app.database import Agent, FollowUp, Lead
from app.services.auth import scoped_lead_query

# Must match the DB CHECK constraint ck_followups_type.
FOLLOWUP_TYPES = ("call", "email", "whatsapp", "viewing", "general")

# Filter names accepted by the API (validated, never interpolated).
FOLLOWUP_FILTERS = ("all", "pending", "overdue", "due_today", "upcoming",
                    "completed")


def utcnow() -> datetime:
    """Naive UTC 'now' — the single clock for every boundary in this module."""
    return datetime.utcnow()


def parse_due_at(value) -> datetime:
    """ISO-8601 (aware or naive) → naive UTC.

    Raises ValueError for anything unparseable — never reinterprets a
    timestamp silently.
    """
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value or "").strip()
        if text.endswith("Z") or text.endswith("z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)   # raises ValueError on junk
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _start_of_day(day: datetime) -> datetime:
    return datetime.combine(day.date(), time.min)


def follow_up_bucket(due_at: datetime, now: Optional[datetime] = None) -> str:
    """'overdue' | 'due_today' | 'upcoming' for a PENDING row (UTC days)."""
    now = now or utcnow()
    today = _start_of_day(now)
    if due_at < today:
        return "overdue"
    if due_at < today + timedelta(days=1):
        return "due_today"
    return "upcoming"


# ------------------------------------------------------------------ queries

def scoped_followup_query(db: Session, agent: Agent):
    """Follow-ups whose lead is inside this agent's data scope.

    Mirrors `scoped_lead_query` (admin → everything; agent → own +
    unassigned leads) by joining through leads.
    """
    lead_ids = scoped_lead_query(db, agent).with_entities(Lead.id).statement
    return db.query(FollowUp).filter(FollowUp.lead_id.in_(lead_ids))


def filter_followups(query, filt: str, now: Optional[datetime] = None):
    """Apply a validated filter to a FollowUp query (pending = not completed)."""
    now = now or utcnow()
    today = _start_of_day(now)
    if filt == "all":
        return query
    if filt == "pending":
        return query.filter(FollowUp.is_completed.is_(False))
    if filt == "completed":
        return query.filter(FollowUp.is_completed.is_(True))
    pending = query.filter(FollowUp.is_completed.is_(False))
    if filt == "overdue":
        return pending.filter(FollowUp.due_at < today)
    if filt == "due_today":
        return pending.filter(FollowUp.due_at >= today,
                              FollowUp.due_at < today + timedelta(days=1))
    if filt == "upcoming":
        return pending.filter(FollowUp.due_at >= today + timedelta(days=1))
    raise ValueError(f"Unknown follow-up filter: {filt!r}")


# ------------------------------------------------------------------- writes

def create_followup(
    db: Session,
    *,
    lead: Lead,
    fu_type: str,
    due_at,
    notes: str = "",
    assigned_agent_id: Optional[int] = None,
) -> FollowUp:
    """Validate and insert a follow-up for an already-validated lead.

    Raises ValueError on invalid type/date/agent — nothing is written.
    """
    if fu_type not in FOLLOWUP_TYPES:
        raise ValueError(
            f"Unknown follow-up type {fu_type!r} "
            f"(expected one of {', '.join(FOLLOWUP_TYPES)})")
    due = parse_due_at(due_at)                      # ValueError on junk
    agent_id = assigned_agent_id
    if agent_id is not None:
        agent = db.query(Agent).filter(Agent.id == agent_id).first()
        if agent is None or not agent.is_active:
            raise ValueError("Unknown agent")
    fu = FollowUp(
        lead_id=lead.id,
        assigned_agent_id=agent_id,
        type=fu_type,
        notes=str(notes or "").strip(),
        due_at=due,
        is_completed=False,
    )
    db.add(fu)
    return fu


def update_followup(db: Session, fu: FollowUp, fields: dict) -> FollowUp:
    """Apply a validated partial update. Permitted transitions only.

    - type / notes / due_at: plain validated updates.
    - is_completed: toggling to True stamps `completed_at`; toggling to
      False clears it. No other state machine exists in the schema.
    - assigned_agent_id: validated active agent (assignment rules for
      non-self targets are enforced by the caller's RBAC).
    """
    if "type" in fields and fields["type"] is not None:
        if fields["type"] not in FOLLOWUP_TYPES:
            raise ValueError(
                f"Unknown follow-up type {fields['type']!r} "
                f"(expected one of {', '.join(FOLLOWUP_TYPES)})")
        fu.type = fields["type"]
    if "notes" in fields and fields["notes"] is not None:
        fu.notes = str(fields["notes"]).strip()
    if "due_at" in fields and fields["due_at"] is not None:
        fu.due_at = parse_due_at(fields["due_at"])
    if "assigned_agent_id" in fields:
        target = fields["assigned_agent_id"]
        if target is not None:
            agent = db.query(Agent).filter(Agent.id == target).first()
            if agent is None or not agent.is_active:
                raise ValueError("Unknown agent")
        fu.assigned_agent_id = target
    if "is_completed" in fields and fields["is_completed"] is not None:
        done = bool(fields["is_completed"])
        if done and not fu.is_completed:
            fu.is_completed = True
            fu.completed_at = utcnow()
        elif not done and fu.is_completed:
            fu.is_completed = False
            fu.completed_at = None
    fu.updated_at = utcnow()
    return fu


# -------------------------------------------------------------- serialisers

def _iso_z(dt: Optional[datetime]) -> Optional[str]:
    """Naive UTC → ISO-8601 with an explicit 'Z' (correct for browsers)."""
    return dt.isoformat(timespec="seconds") + "Z" if dt else None


def follow_up_summary(fu: Optional[FollowUp]) -> Optional[dict]:
    """One follow-up row (or None). Timezone-explicit serialisation."""
    if fu is None:
        return None
    agent = fu.assigned_agent
    return {
        "id": fu.id,
        "lead_id": fu.lead_id,
        "type": fu.type,
        "notes": fu.notes or "",
        "due_at": _iso_z(fu.due_at),
        "bucket": follow_up_bucket(fu.due_at) if not fu.is_completed else None,
        "is_completed": bool(fu.is_completed),
        "completed_at": _iso_z(fu.completed_at),
        "assigned_agent_id": fu.assigned_agent_id,
        "assigned_agent_name": agent.full_name if agent else None,
        "created_at": _iso_z(fu.created_at),
        "updated_at": _iso_z(fu.updated_at),
    }


def list_lead_followups(db: Session, lead: Lead,
                        include_completed: bool = True) -> List[FollowUp]:
    q = db.query(FollowUp).filter(FollowUp.lead_id == lead.id)
    if not include_completed:
        q = q.filter(FollowUp.is_completed.is_(False))
    return q.order_by(FollowUp.due_at.asc(), FollowUp.id.asc()).all()
