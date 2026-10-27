"""Dashboard statistics from real database queries (Phase 5).

All metrics are computed with GROUP BY / COUNT over the rows the calling
agent is actually allowed to see (admin → everything; agent → own +
unassigned leads), never from hardcoded demo numbers, and never N+1: one
grouped query per metric family.

Timezone: every boundary uses naive UTC (`followups.utcnow`), identical to
how the application writes created_at/due_at.
"""

from datetime import datetime, time, timedelta
from typing import Dict

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import Agent, FollowUp, Lead
from app.services.auth import scoped_lead_query
from app.services.followups import scoped_followup_query

# Statuses in use today (mirrors main.LEAD_STATUSES — kept as a local tuple
# to avoid a circular import with the route module; the routes validate
# against their own set, tests assert the two agree).
LEAD_STATUSES = (
    "new", "contacted", "qualified", "viewing",
    "negotiation", "closed_won", "closed_lost",
)


def dashboard_stats(db: Session, agent: Agent) -> Dict:
    """Metrics for the CRM home. Empty database → all zeros."""
    scoped = scoped_lead_query(db, agent)

    # --- status counts (one grouped query) -------------------------------
    status_rows = (
        scoped.with_entities(Lead.status, func.count(Lead.id))
        .group_by(Lead.status)
        .all()
    )
    by_status = {status: 0 for status in LEAD_STATUSES}
    total = 0
    for status, count in status_rows:
        total += count
        key = status or "new"
        # merge legacy/unknown/NULL statuses into their bucket (never drop)
        by_status[key] = by_status.get(key, 0) + count

    counts = {"total": total, **by_status}
    counts["closed"] = counts.get("closed_won", 0)   # friendly stat-card keys
    counts["lost"] = counts.get("closed_lost", 0)

    # --- priority counts (one grouped query; NULL = never scored) --------
    priority_rows = (
        scoped.with_entities(Lead.priority, func.count(Lead.id))
        .group_by(Lead.priority)
        .all()
    )
    priorities = {"high": 0, "medium": 0, "low": 0, "unscored": 0}
    for priority, count in priority_rows:
        key = priority if priority in ("high", "medium", "low") else "unscored"
        priorities[key] = count

    # --- follow-up buckets (one query over pending scoped rows) ----------
    pending = (
        scoped_followup_query(db, agent)
        .filter(FollowUp.is_completed.is_(False))
        .with_entities(FollowUp.due_at)
        .all()
    )
    now = datetime.utcnow()
    today = datetime.combine(now.date(), time.min)
    tomorrow = today + timedelta(days=1)
    follow_ups = {"overdue": 0, "due_today": 0, "upcoming": 0}
    for (due_at,) in pending:
        if due_at is None:
            continue
        if due_at < today:
            follow_ups["overdue"] += 1
        elif due_at < tomorrow:
            follow_ups["due_today"] += 1
        else:
            follow_ups["upcoming"] += 1

    return {
        "counts": counts,
        "priority": priorities,
        "follow_ups": follow_ups,
    }
