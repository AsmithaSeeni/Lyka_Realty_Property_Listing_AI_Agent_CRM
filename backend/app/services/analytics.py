"""Phase G — Business Intelligence & Analytics Service for Lyka Realty CRM.

Provides validated, RBAC-scoped, database-aggregated metrics for:
  1. Executive / Administrator Dashboard (Company-wide KPIs, Conversion Funnel, Revenue, Property Inventory)
  2. Sales Manager Dashboard (Team Workload, Agent Performance, Stalled Leads/Deals, Approaching Deadlines)
  3. Individual Sales Agent Dashboard (Personal Action Items, Viewings Awaiting Feedback, Scoped Pipeline & Commission)
  4. Protected CSV Export with formula injection prevention.

Calculations respect:
  - Standard UAE business reporting timezone: Asia/Dubai (UTC+04:00) converted to naive UTC for storage queries.
  - Strict separation between Estimated Commission (pipeline projection) and Verified Commission (completed/realized).
  - Explicit handling of empty datasets and zero denominators (no ZeroDivisionErrors).
  - Backend-enforced RBAC (agents cannot read other agents' or company-wide data).
"""

import csv
import io
from datetime import datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import and_, case, distinct, func, or_
from sqlalchemy.orm import Session

from app.database import (
    Agent,
    Appointment,
    AuditLog,
    Conversation,
    Customer,
    Deal,
    DealChecklistItem,
    FollowUp,
    Lead,
    Offer,
    Property,
)
from app.services import rbac
from app.services.auth import (
    lead_in_scope,
    scoped_lead_query,
)
from app.services.sales_ops import (
    ACTIVE_APPOINTMENT_STATUSES,
    APPOINTMENT_STATUSES,
    DEAL_STAGES,
    OFFER_STATUSES,
    TERMINAL_DEAL_STAGES,
    TERMINAL_OFFER_STATUSES,
    VIEWING_OUTCOMES,
    scoped_appointment_query,
    scoped_deal_query,
    scoped_offer_query,
)

# ---------------------------------------------------------------------------
# Timezone & Date Range Helpers
# ---------------------------------------------------------------------------

_FALLBACK_OFFSETS = {
    "Asia/Dubai": timezone(timedelta(hours=4)),
    "UTC": timezone.utc,
    "Etc/UTC": timezone.utc,
}


def get_dubai_tz():
    """Return tzinfo for Asia/Dubai."""
    try:
        return ZoneInfo("Asia/Dubai")
    except ZoneInfoNotFoundError:
        return _FALLBACK_OFFSETS["Asia/Dubai"]


def parse_reporting_period(
    period: Optional[str] = "30d",
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    tz_name: str = "Asia/Dubai",
) -> Tuple[Optional[datetime], Optional[datetime], str]:
    """Parse reporting period into UTC naive datetime bounds (start_utc, end_utc, label).

    Supported period shortcuts:
      - '7d': last 7 days
      - '30d': last 30 days (default)
      - '90d': last 90 days
      - 'this_month': 1st of current month in Asia/Dubai to now
      - 'last_month': 1st of prior month to end of prior month in Asia/Dubai
      - 'all': unbounded period (None, None)
      - Custom: date_from and date_to formatted as YYYY-MM-DD
    """
    dubai_tz = get_dubai_tz()
    now_utc = datetime.utcnow()
    now_dubai = datetime.now(dubai_tz)

    if date_from or date_to:
        if not (date_from and date_to):
            raise ValueError("Both date_from and date_to are required for custom date ranges")
        try:
            d_from = datetime.strptime(date_from.strip(), "%Y-%m-%d").date()
            d_to = datetime.strptime(date_to.strip(), "%Y-%m-%d").date()
        except ValueError:
            raise ValueError("Dates must be formatted as YYYY-MM-DD")

        if d_from > d_to:
            raise ValueError("date_from must be before or equal to date_to")

        # Convert local start and end of day in Asia/Dubai to UTC naive
        dt_start_local = datetime.combine(d_from, time.min).replace(tzinfo=dubai_tz)
        dt_end_local = datetime.combine(d_to, time.max).replace(tzinfo=dubai_tz)

        start_utc = dt_start_local.astimezone(timezone.utc).replace(tzinfo=None)
        end_utc = dt_end_local.astimezone(timezone.utc).replace(tzinfo=None)

        # Protect against excessive ranges (> 5 years)
        if (end_utc - start_utc).days > 365 * 5:
            raise ValueError("Date range exceeds maximum allowed span of 5 years")

        return start_utc, end_utc, f"{date_from} to {date_to}"

    p = (period or "30d").strip().lower()
    if p == "7d":
        start_utc = now_utc - timedelta(days=7)
        return start_utc, now_utc, "Last 7 days"
    elif p == "30d":
        start_utc = now_utc - timedelta(days=30)
        return start_utc, now_utc, "Last 30 days"
    elif p == "90d":
        start_utc = now_utc - timedelta(days=90)
        return start_utc, now_utc, "Last 90 days"
    elif p == "this_month":
        start_month_dubai = datetime(now_dubai.year, now_dubai.month, 1, 0, 0, 0, tzinfo=dubai_tz)
        start_utc = start_month_dubai.astimezone(timezone.utc).replace(tzinfo=None)
        return start_utc, now_utc, "This month"
    elif p == "last_month":
        first_current = datetime(now_dubai.year, now_dubai.month, 1, 0, 0, 0, tzinfo=dubai_tz)
        last_prev_local = first_current - timedelta(seconds=1)
        start_prev_local = datetime(last_prev_local.year, last_prev_local.month, 1, 0, 0, 0, tzinfo=dubai_tz)
        start_utc = start_prev_local.astimezone(timezone.utc).replace(tzinfo=None)
        end_utc = last_prev_local.astimezone(timezone.utc).replace(tzinfo=None)
        return start_utc, end_utc, "Last month"
    elif p == "all":
        return None, None, "All time"
    else:
        raise ValueError(f"Unknown period '{period}'. Use '7d', '30d', '90d', 'this_month', 'last_month', 'all' or custom dates.")


def _safe_pct(numerator: float, denominator: float, precision: int = 1) -> float:
    """Safe percentage division preventing ZeroDivisionError."""
    if not denominator or denominator <= 0:
        return 0.0
    return round((float(numerator) / float(denominator)) * 100.0, precision)


# ---------------------------------------------------------------------------
# 1. Executive / Administrator Dashboard (Company-wide KPIs)
# ---------------------------------------------------------------------------

def get_executive_analytics(
    db: Session,
    actor: Agent,
    start_utc: Optional[datetime] = None,
    end_utc: Optional[datetime] = None,
    period_label: str = "Last 30 days",
) -> Dict[str, Any]:
    """Calculate company-wide KPIs and conversion funnel for executives/administrators.

    Requires: `reports.read_all` permission.
    """
    if not rbac.has_permission(actor, "reports.read_all"):
        raise PermissionError("Access denied: Executive analytics requires 'reports.read_all' permission")

    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # Lead period filter
    lead_q = db.query(Lead).filter(Lead.is_synthetic.is_(False))
    if start_utc is not None:
        lead_q = lead_q.filter(Lead.created_at >= start_utc)
    if end_utc is not None:
        lead_q = lead_q.filter(Lead.created_at <= end_utc)

    # 1. Lead counts & statuses in period
    total_leads = lead_q.count()
    new_leads = lead_q.filter(Lead.status == "new").count()

    # Qualified leads (status in qualified/viewing/negotiation/closed_won)
    qualified_statuses = ("qualified", "viewing", "negotiation", "closed_won")
    qualified_leads = lead_q.filter(Lead.status.in_(qualified_statuses)).count()
    qualification_rate_pct = _safe_pct(qualified_leads, total_leads)

    # Status distribution
    status_counts_raw = (
        lead_q.with_entities(Lead.status, func.count(Lead.id))
        .group_by(Lead.status)
        .all()
    )
    by_status: Dict[str, int] = {
        "new": 0, "contact_pending": 0, "contacted": 0, "qualified": 0,
        "viewing": 0, "negotiation": 0, "closed_won": 0, "closed_lost": 0, "nurturing": 0,
    }
    for s, c in status_counts_raw:
        if s in by_status:
            by_status[s] = c
        elif s:
            by_status[s] = c

    # Source distribution
    source_counts_raw = (
        lead_q.with_entities(Lead.source, func.count(Lead.id))
        .group_by(Lead.source)
        .all()
    )
    by_source: Dict[str, int] = {}
    for src, c in source_counts_raw:
        by_source[src or "Direct / AI"] = c

    # Priority distribution
    priority_counts_raw = (
        lead_q.with_entities(Lead.priority, func.count(Lead.id))
        .group_by(Lead.priority)
        .all()
    )
    by_priority: Dict[str, int] = {"high": 0, "medium": 0, "low": 0, "unscored": 0}
    for prio, c in priority_counts_raw:
        if prio in ("high", "medium", "low"):
            by_priority[prio] = c
        else:
            by_priority["unscored"] += c

    # 2. Appointments & Viewings in period
    appt_q = db.query(Appointment)
    if start_utc is not None:
        appt_q = appt_q.filter(Appointment.start_at >= start_utc)
    if end_utc is not None:
        appt_q = appt_q.filter(Appointment.start_at <= end_utc)

    total_appointments = appt_q.count()
    viewings_count = appt_q.filter(Appointment.appointment_type == "viewing").count()
    completed_viewings = appt_q.filter(
        Appointment.appointment_type == "viewing",
        Appointment.status == "completed",
    ).count()

    # Viewing outcomes
    outcome_counts_raw = (
        appt_q.filter(Appointment.appointment_type == "viewing")
        .with_entities(Appointment.viewing_outcome, func.count(Appointment.id))
        .group_by(Appointment.viewing_outcome)
        .all()
    )
    by_viewing_outcome: Dict[str, int] = {o: 0 for o in VIEWING_OUTCOMES}
    no_outcome_recorded = 0
    for outc, c in outcome_counts_raw:
        if outc in by_viewing_outcome:
            by_viewing_outcome[outc] = c
        else:
            no_outcome_recorded += c
    by_viewing_outcome["unrecorded"] = no_outcome_recorded

    # Distinct leads in period that had at least one viewing
    leads_with_viewing = (
        appt_q.filter(Appointment.appointment_type == "viewing")
        .with_entities(func.count(distinct(Appointment.lead_id)))
        .scalar()
        or 0
    )
    lead_to_viewing_conversion_pct = _safe_pct(leads_with_viewing, total_leads)

    # 3. Offers in period
    offer_q = db.query(Offer)
    if start_utc is not None:
        offer_q = offer_q.filter(Offer.created_at >= start_utc)
    if end_utc is not None:
        offer_q = offer_q.filter(Offer.created_at <= end_utc)

    total_offers = offer_q.count()
    accepted_offers = offer_q.filter(Offer.status == "accepted").count()
    rejected_offers = offer_q.filter(Offer.status == "rejected").count()
    decided_offers = offer_q.filter(Offer.status.in_(TERMINAL_OFFER_STATUSES)).count()
    offer_acceptance_rate_pct = _safe_pct(accepted_offers, decided_offers)

    # Viewed leads that had an offer created
    viewed_leads_with_offer = (
        db.query(func.count(distinct(Offer.lead_id)))
        .join(Appointment, Appointment.lead_id == Offer.lead_id)
        .filter(Appointment.appointment_type == "viewing")
    )
    if start_utc is not None:
        viewed_leads_with_offer = viewed_leads_with_offer.filter(Offer.created_at >= start_utc)
    if end_utc is not None:
        viewed_leads_with_offer = viewed_leads_with_offer.filter(Offer.created_at <= end_utc)
    viewed_leads_with_offer_count = viewed_leads_with_offer.scalar() or 0
    viewing_to_offer_conversion_pct = _safe_pct(viewed_leads_with_offer_count, leads_with_viewing)

    # 4. Deals & Revenue
    deal_q = db.query(Deal)
    active_deals = deal_q.filter(~Deal.status.in_(TERMINAL_DEAL_STAGES)).all()
    active_deals_count = len(active_deals)
    active_pipeline_value = sum(float(d.agreed_amount or 0.0) for d in active_deals)
    estimated_commission_total = sum(float(d.estimated_commission or 0.0) for d in active_deals)

    by_deal_stage: Dict[str, int] = {s: 0 for s in DEAL_STAGES if s not in TERMINAL_DEAL_STAGES}
    for d in active_deals:
        if d.status in by_deal_stage:
            by_deal_stage[d.status] += 1

    # Completed deals in period (or all time if unbounded)
    completed_deal_q = deal_q.filter(Deal.status == "completed")
    if start_utc is not None:
        completed_deal_q = completed_deal_q.filter(
            or_(
                Deal.actual_completion_date >= start_utc,
                and_(Deal.actual_completion_date.is_(None), Deal.updated_at >= start_utc),
            )
        )
    if end_utc is not None:
        completed_deal_q = completed_deal_q.filter(
            or_(
                Deal.actual_completion_date <= end_utc,
                and_(Deal.actual_completion_date.is_(None), Deal.updated_at <= end_utc),
            )
        )
    completed_deals = completed_deal_q.all()
    completed_deals_count = len(completed_deals)
    completed_deal_value = sum(float(d.agreed_amount or 0.0) for d in completed_deals)

    # Verified commission on completed/verified deals
    verified_commission_total = sum(
        float(d.actual_commission or 0.0)
        for d in completed_deals
        if d.commission_status in ("verified", "earned", "paid") and d.actual_commission is not None
    )

    # 5. Conversion Funnel Stages
    funnel = [
        {
            "stage": "Leads",
            "count": total_leads,
            "step_conversion_pct": 100.0,
            "overall_conversion_pct": 100.0,
            "description": "Total inquiries received in period",
        },
        {
            "stage": "Qualified",
            "count": qualified_leads,
            "step_conversion_pct": qualification_rate_pct,
            "overall_conversion_pct": qualification_rate_pct,
            "description": "Leads meeting budget, timeline and readiness criteria",
        },
        {
            "stage": "Viewing",
            "count": leads_with_viewing,
            "step_conversion_pct": _safe_pct(leads_with_viewing, qualified_leads),
            "overall_conversion_pct": _safe_pct(leads_with_viewing, total_leads),
            "description": "Leads who attended a property viewing",
        },
        {
            "stage": "Offer Made",
            "count": viewed_leads_with_offer_count,
            "step_conversion_pct": viewing_to_offer_conversion_pct,
            "overall_conversion_pct": _safe_pct(viewed_leads_with_offer_count, total_leads),
            "description": "Leads with a submitted formal offer",
        },
        {
            "stage": "Offer Accepted",
            "count": accepted_offers,
            "step_conversion_pct": offer_acceptance_rate_pct,
            "overall_conversion_pct": _safe_pct(accepted_offers, total_leads),
            "description": "Offers accepted by seller / landlord",
        },
        {
            "stage": "Closed Deal",
            "count": completed_deals_count,
            "step_conversion_pct": _safe_pct(completed_deals_count, accepted_offers),
            "overall_conversion_pct": _safe_pct(completed_deals_count, total_leads),
            "description": "Completed transactions with finalized contracts",
        },
    ]

    # 6. Current operational workload (as of now)
    upcoming_appointments = (
        db.query(Appointment)
        .filter(
            Appointment.status.in_(ACTIVE_APPOINTMENT_STATUSES),
            Appointment.start_at >= now,
        )
        .count()
    )
    overdue_followups = (
        db.query(FollowUp)
        .filter(
            FollowUp.is_completed.is_(False),
            FollowUp.due_at < today_start,
        )
        .count()
    )

    # 7. Property Inventory Summary (Snapshot)
    total_properties = db.query(Property).count()
    approved_properties = db.query(Property).filter(Property.is_approved.is_(True)).count()
    published_properties = (
        db.query(Property)
        .filter(Property.is_approved.is_(True), Property.is_published.is_(True), Property.availability == "available")
        .count()
    )
    unverified_properties = db.query(Property).filter(Property.verification_status == "unverified").count()
    pending_review_properties = db.query(Property).filter(Property.verification_status == "pending_review").count()
    rejected_properties = db.query(Property).filter(Property.verification_status == "rejected").count()
    available_properties = (
        db.query(Property)
        .filter(Property.is_approved.is_(True), Property.availability == "available")
        .count()
    )
    reserved_properties = db.query(Property).filter(Property.availability == "reserved").count()
    sold_or_rented = db.query(Property).filter(Property.availability.in_(("sold", "rented"))).count()

    purpose_counts_raw = (
        db.query(Property.purpose, func.count(Property.id))
        .group_by(Property.purpose)
        .all()
    )
    by_purpose: Dict[str, int] = {}
    for purp, c in purpose_counts_raw:
        if purp:
            by_purpose[purp] = c

    type_counts_raw = (
        db.query(Property.property_type, func.count(Property.id))
        .group_by(Property.property_type)
        .all()
    )
    by_property_type: Dict[str, int] = {}
    for ptype, c in type_counts_raw:
        if ptype:
            by_property_type[ptype] = c

    return {
        "period": {
            "label": period_label,
            "start_utc": start_utc.isoformat() if start_utc else None,
            "end_utc": end_utc.isoformat() if end_utc else None,
            "timezone": "Asia/Dubai",
        },
        "kpis": {
            "total_leads": total_leads,
            "new_leads": new_leads,
            "qualified_leads": qualified_leads,
            "qualification_rate_pct": qualification_rate_pct,
            "lead_to_viewing_conversion_pct": lead_to_viewing_conversion_pct,
            "viewing_to_offer_conversion_pct": viewing_to_offer_conversion_pct,
            "offer_acceptance_rate_pct": offer_acceptance_rate_pct,
            "active_deals": active_deals_count,
            "completed_deals": completed_deals_count,
            "active_pipeline_value_aed": round(active_pipeline_value, 2),
            "completed_deal_value_aed": round(completed_deal_value, 2),
            "estimated_commission_aed": round(estimated_commission_total, 2),
            "verified_commission_aed": round(verified_commission_total, 2),
            "upcoming_appointments": upcoming_appointments,
            "overdue_followups": overdue_followups,
        },
        "funnel": funnel,
        "leads_distribution": {
            "by_status": by_status,
            "by_source": by_source,
            "by_priority": by_priority,
        },
        "appointments_summary": {
            "total": total_appointments,
            "viewings": viewings_count,
            "completed_viewings": completed_viewings,
            "by_outcome": by_viewing_outcome,
        },
        "offers_summary": {
            "total": total_offers,
            "accepted": accepted_offers,
            "rejected": rejected_offers,
            "decided": decided_offers,
            "acceptance_rate_pct": offer_acceptance_rate_pct,
        },
        "deals_summary": {
            "active_count": active_deals_count,
            "completed_count": completed_deals_count,
            "by_stage": by_deal_stage,
            "active_value_aed": round(active_pipeline_value, 2),
            "completed_value_aed": round(completed_deal_value, 2),
            "estimated_commission_aed": round(estimated_commission_total, 2),
            "verified_commission_aed": round(verified_commission_total, 2),
        },
        "inventory_summary": {
            "total": total_properties,
            "approved": approved_properties,
            "published": published_properties,
            "unverified": unverified_properties,
            "pending_review": pending_review_properties,
            "rejected": rejected_properties,
            "available": available_properties,
            "reserved": reserved_properties,
            "sold_or_rented": sold_or_rented,
            "by_purpose": by_purpose,
            "by_type": by_property_type,
        },
    }


# ---------------------------------------------------------------------------
# 2. Sales Manager Dashboard (Team Performance & Pipeline Monitoring)
# ---------------------------------------------------------------------------

def get_manager_analytics(
    db: Session,
    actor: Agent,
    start_utc: Optional[datetime] = None,
    end_utc: Optional[datetime] = None,
    period_label: str = "Last 30 days",
) -> Dict[str, Any]:
    """Calculate team workload, agent performance breakdown, and stalled items.

    Requires: `reports.read_all` or `leads.read_all`.
    """
    if not (rbac.has_permission(actor, "reports.read_all") or rbac.has_permission(actor, "leads.read_all")):
        raise PermissionError("Access denied: Team analytics requires manager or administrator permissions")

    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    stale_threshold = now - timedelta(days=14)
    deadline_threshold = now + timedelta(days=30)

    # 1. Team workload
    unassigned_leads = (
        db.query(Lead)
        .filter(
            Lead.is_synthetic.is_(False),
            Lead.assigned_agent_id.is_(None),
            ~Lead.status.in_(("closed_won", "closed_lost")),
        )
        .count()
    )
    total_active_leads = (
        db.query(Lead)
        .filter(Lead.is_synthetic.is_(False), ~Lead.status.in_(("closed_won", "closed_lost")))
        .count()
    )
    total_overdue_followups = (
        db.query(FollowUp)
        .filter(
            FollowUp.is_completed.is_(False),
            FollowUp.due_at < today_start,
        )
        .count()
    )
    upcoming_team_appointments = (
        db.query(Appointment)
        .filter(
            Appointment.status.in_(ACTIVE_APPOINTMENT_STATUSES),
            Appointment.start_at >= now,
        )
        .count()
    )

    # 2. Agent performance breakdown
    agents = db.query(Agent).filter(Agent.is_active.is_(True)).order_by(Agent.full_name).all()
    agent_rows: List[Dict[str, Any]] = []

    for ag in agents:
        # Leads assigned in period
        lead_ag_q = db.query(Lead).filter(Lead.is_synthetic.is_(False), Lead.assigned_agent_id == ag.id)
        if start_utc is not None:
            lead_ag_q = lead_ag_q.filter(Lead.created_at >= start_utc)
        if end_utc is not None:
            lead_ag_q = lead_ag_q.filter(Lead.created_at <= end_utc)
        assigned_in_period = lead_ag_q.count()

        # Active assigned leads
        active_assigned = (
            db.query(Lead)
            .filter(
                Lead.is_synthetic.is_(False),
                Lead.assigned_agent_id == ag.id,
                ~Lead.status.in_(("closed_won", "closed_lost")),
            )
            .count()
        )

        # Qualified in period
        qualified_in_period = lead_ag_q.filter(
            Lead.status.in_(("qualified", "viewing", "negotiation", "closed_won"))
        ).count()

        # Viewings in period
        appt_ag_q = db.query(Appointment).filter(
            Appointment.assigned_agent_id == ag.id,
            Appointment.appointment_type == "viewing",
        )
        if start_utc is not None:
            appt_ag_q = appt_ag_q.filter(Appointment.start_at >= start_utc)
        if end_utc is not None:
            appt_ag_q = appt_ag_q.filter(Appointment.start_at <= end_utc)
        viewings_count = appt_ag_q.count()

        # Offers created in period
        offer_ag_q = db.query(Offer).filter(Offer.assigned_agent_id == ag.id)
        if start_utc is not None:
            offer_ag_q = offer_ag_q.filter(Offer.created_at >= start_utc)
        if end_utc is not None:
            offer_ag_q = offer_ag_q.filter(Offer.created_at <= end_utc)
        offers_count = offer_ag_q.count()
        accepted_offers_count = offer_ag_q.filter(Offer.status == "accepted").count()

        # Deals active & completed
        deal_ag_q = db.query(Deal).filter(Deal.assigned_agent_id == ag.id)
        active_deals_list = deal_ag_q.filter(~Deal.status.in_(TERMINAL_DEAL_STAGES)).all()
        active_deals_count = len(active_deals_list)
        estimated_comm = sum(float(d.estimated_commission or 0.0) for d in active_deals_list)

        completed_deal_ag_q = deal_ag_q.filter(Deal.status == "completed")
        if start_utc is not None:
            completed_deal_ag_q = completed_deal_ag_q.filter(
                or_(
                    Deal.actual_completion_date >= start_utc,
                    and_(Deal.actual_completion_date.is_(None), Deal.updated_at >= start_utc),
                )
            )
        if end_utc is not None:
            completed_deal_ag_q = completed_deal_ag_q.filter(
                or_(
                    Deal.actual_completion_date <= end_utc,
                    and_(Deal.actual_completion_date.is_(None), Deal.updated_at <= end_utc),
                )
            )
        completed_deals_list = completed_deal_ag_q.all()
        completed_deals_count = len(completed_deals_list)
        verified_comm = sum(
            float(d.actual_commission or 0.0)
            for d in completed_deals_list
            if d.commission_status in ("verified", "earned", "paid") and d.actual_commission is not None
        )

        # Overdue followups
        ag_overdue_followups = (
            db.query(FollowUp)
            .filter(
                FollowUp.assigned_agent_id == ag.id,
                FollowUp.is_completed.is_(False),
                FollowUp.due_at < today_start,
            )
            .count()
        )

        agent_rows.append({
            "agent_id": ag.id,
            "name": ag.full_name,
            "username": ag.username,
            "email": ag.email,
            "role": ag.role,
            "assigned_leads_in_period": assigned_in_period,
            "active_leads": active_assigned,
            "qualified_leads": qualified_in_period,
            "qualification_rate_pct": _safe_pct(qualified_in_period, assigned_in_period),
            "viewings_conducted": viewings_count,
            "offers_created": offers_count,
            "offers_accepted": accepted_offers_count,
            "active_deals": active_deals_count,
            "completed_deals": completed_deals_count,
            "closing_rate_pct": _safe_pct(completed_deals_count, assigned_in_period),
            "estimated_commission_aed": round(estimated_comm, 2),
            "verified_commission_aed": round(verified_comm, 2),
            "overdue_followups": ag_overdue_followups,
        })

    # 3. Stalled leads (in active progress, untouched for > 14 days)
    stalled_lead_rows = (
        db.query(Lead)
        .filter(
            Lead.is_synthetic.is_(False),
            Lead.status.in_(("contact_pending", "contacted", "qualified", "viewing", "negotiation")),
            or_(
                and_(Lead.last_interaction_at.isnot(None), Lead.last_interaction_at < stale_threshold),
                and_(Lead.last_interaction_at.is_(None), Lead.updated_at < stale_threshold),
            ),
        )
        .order_by(func.coalesce(Lead.last_interaction_at, Lead.updated_at).asc())
        .limit(10)
        .all()
    )
    stalled_leads = []
    agent_map = {ag.id: ag.full_name for ag in agents}
    for l in stalled_lead_rows:
        last_dt = l.last_interaction_at or l.updated_at or l.created_at
        days_stalled = (now - last_dt).days if last_dt else 0
        stalled_leads.append({
            "id": l.id,
            "name": l.name or f"Lead #{l.id}",
            "status": l.status,
            "assigned_agent_id": l.assigned_agent_id,
            "assigned_agent_name": agent_map.get(l.assigned_agent_id, "Unassigned"),
            "days_stalled": days_stalled,
            "last_active": last_dt.isoformat() if last_dt else None,
        })

    # 4. Stalled deals (active deal in progress, untouched for > 14 days)
    stalled_deal_rows = (
        db.query(Deal)
        .filter(
            ~Deal.status.in_(TERMINAL_DEAL_STAGES),
            Deal.updated_at < stale_threshold,
        )
        .order_by(Deal.updated_at.asc())
        .limit(10)
        .all()
    )
    stalled_deals = []
    for d in stalled_deal_rows:
        days_stalled = (now - d.updated_at).days if d.updated_at else 0
        stalled_deals.append({
            "id": d.id,
            "deal_reference": d.deal_reference,
            "status": d.status,
            "agreed_amount": d.agreed_amount,
            "currency": d.currency,
            "assigned_agent_id": d.assigned_agent_id,
            "assigned_agent_name": agent_map.get(d.assigned_agent_id, "Unknown"),
            "days_stalled": days_stalled,
            "last_active": d.updated_at.isoformat() if d.updated_at else None,
        })

    # 5. Deals approaching deadline (target_completion_date within 30 days)
    deadline_deals_raw = (
        db.query(Deal)
        .filter(
            ~Deal.status.in_(TERMINAL_DEAL_STAGES),
            Deal.target_completion_date.isnot(None),
            Deal.target_completion_date <= deadline_threshold,
        )
        .order_by(Deal.target_completion_date.asc())
        .limit(10)
        .all()
    )
    approaching_deadlines = []
    for d in deadline_deals_raw:
        days_remaining = (d.target_completion_date - now).days
        approaching_deadlines.append({
            "id": d.id,
            "deal_reference": d.deal_reference,
            "status": d.status,
            "agreed_amount": d.agreed_amount,
            "currency": d.currency,
            "target_completion_date": d.target_completion_date.isoformat(),
            "days_remaining": days_remaining,
            "assigned_agent_name": agent_map.get(d.assigned_agent_id, "Unknown"),
        })

    return {
        "period": {
            "label": period_label,
            "start_utc": start_utc.isoformat() if start_utc else None,
            "end_utc": end_utc.isoformat() if end_utc else None,
            "timezone": "Asia/Dubai",
        },
        "workload": {
            "unassigned_leads": unassigned_leads,
            "total_active_leads": total_active_leads,
            "overdue_team_followups": total_overdue_followups,
            "upcoming_team_appointments": upcoming_team_appointments,
        },
        "agents": agent_rows,
        "stalled_leads": stalled_leads,
        "stalled_deals": stalled_deals,
        "approaching_deadlines": approaching_deadlines,
    }


# ---------------------------------------------------------------------------
# 3. Individual Sales Agent Dashboard (Personal Scoped Performance)
# ---------------------------------------------------------------------------

def get_agent_personal_analytics(
    db: Session,
    actor: Agent,
    target_agent_id: Optional[int] = None,
    start_utc: Optional[datetime] = None,
    end_utc: Optional[datetime] = None,
    period_label: str = "Last 30 days",
) -> Dict[str, Any]:
    """Calculate personal dashboard metrics for an individual sales agent.

    Security rule:
      - An agent can only inspect their own metrics (`target_agent_id == actor.id`).
      - Inspecting another agent requires `reports.read_all` permission.
    """
    resolved_agent_id = target_agent_id or actor.id
    if resolved_agent_id != actor.id and not rbac.has_permission(actor, "reports.read_all"):
        raise PermissionError("Access denied: You are not authorized to view another agent's personal analytics")

    target_agent = db.query(Agent).filter(Agent.id == resolved_agent_id).first()
    if not target_agent:
        raise LookupError(f"Agent #{resolved_agent_id} not found")

    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start = today_start + timedelta(days=1)

    # 1. Assigned leads in period and active leads
    lead_q = db.query(Lead).filter(Lead.assigned_agent_id == target_agent.id)
    if start_utc is not None:
        lead_q = lead_q.filter(Lead.created_at >= start_utc)
    if end_utc is not None:
        lead_q = lead_q.filter(Lead.created_at <= end_utc)

    assigned_in_period = lead_q.count()

    active_leads_by_status_raw = (
        db.query(Lead.status, func.count(Lead.id))
        .filter(
            Lead.assigned_agent_id == target_agent.id,
            ~Lead.status.in_(("closed_won", "closed_lost")),
        )
        .group_by(Lead.status)
        .all()
    )
    active_by_status: Dict[str, int] = {
        "new": 0, "contact_pending": 0, "contacted": 0, "qualified": 0,
        "viewing": 0, "negotiation": 0, "nurturing": 0,
    }
    for s, c in active_leads_by_status_raw:
        if s in active_by_status:
            active_by_status[s] = c
        elif s:
            active_by_status[s] = c

    # New leads requiring urgent action
    new_leads_action_needed = (
        db.query(Lead)
        .filter(
            Lead.assigned_agent_id == target_agent.id,
            Lead.status.in_(("new", "contact_pending")),
        )
        .count()
    )

    # 2. Appointments & Viewings for agent
    all_agent_appts = (
        db.query(Appointment)
        .filter(Appointment.assigned_agent_id == target_agent.id)
        .all()
    )
    today_appts = [a for a in all_agent_appts if a.status in ACTIVE_APPOINTMENT_STATUSES and today_start <= a.start_at < tomorrow_start]
    upcoming_appts = [a for a in all_agent_appts if a.status in ACTIVE_APPOINTMENT_STATUSES and a.start_at >= tomorrow_start]

    # Viewings awaiting outcome/feedback: past viewing with no recorded outcome
    viewings_awaiting_feedback = [
        {
            "id": a.id,
            "lead_id": a.lead_id,
            "property_id": a.property_id,
            "property_title": a.property_record.title if a.property_record else None,
            "start_at": a.start_at.isoformat() if a.start_at else None,
            "status": a.status,
            "meeting_method": a.meeting_method,
        }
        for a in all_agent_appts
        if a.appointment_type == "viewing"
        and a.status in ("completed", "scheduled")
        and a.start_at < now
        and (not a.viewing_outcome or a.viewing_outcome == "undecided")
    ][:5]

    # 3. Follow-ups
    pending_followups = (
        db.query(FollowUp)
        .filter(
            FollowUp.assigned_agent_id == target_agent.id,
            FollowUp.is_completed.is_(False),
        )
        .all()
    )
    overdue_followups = [f for f in pending_followups if f.due_at and f.due_at < today_start]
    due_today_followups = [f for f in pending_followups if f.due_at and today_start <= f.due_at < tomorrow_start]
    upcoming_followups = [f for f in pending_followups if f.due_at and f.due_at >= tomorrow_start]

    # 4. Offers awaiting response
    offers_awaiting_response_raw = (
        db.query(Offer)
        .filter(
            Offer.assigned_agent_id == target_agent.id,
            Offer.status.in_(("submitted", "countered")),
        )
        .order_by(Offer.updated_at.desc())
        .limit(5)
        .all()
    )
    offers_awaiting_response = [
        {
            "id": o.id,
            "lead_id": o.lead_id,
            "property_id": o.property_id,
            "offered_price": o.offered_price,
            "current_price": o.current_price,
            "currency": o.currency,
            "status": o.status,
            "submitted_at": o.submitted_at.isoformat() if o.submitted_at else None,
        }
        for o in offers_awaiting_response_raw
    ]

    # 5. Deals & Commission
    agent_deals = db.query(Deal).filter(Deal.assigned_agent_id == target_agent.id).all()
    active_deals = [d for d in agent_deals if d.status not in TERMINAL_DEAL_STAGES]
    completed_deals = [d for d in agent_deals if d.status == "completed"]

    estimated_comm = sum(float(d.estimated_commission or 0.0) for d in active_deals)
    verified_comm = sum(
        float(d.actual_commission or 0.0)
        for d in completed_deals
        if d.commission_status in ("verified", "earned", "paid") and d.actual_commission is not None
    )

    deals_by_stage: Dict[str, int] = {s: 0 for s in DEAL_STAGES if s not in TERMINAL_DEAL_STAGES}
    for d in active_deals:
        if d.status in deals_by_stage:
            deals_by_stage[d.status] += 1

    # Personal conversion rates
    qualified_leads_count = (
        db.query(Lead)
        .filter(
            Lead.assigned_agent_id == target_agent.id,
            Lead.status.in_(("qualified", "viewing", "negotiation", "closed_won")),
        )
        .count()
    )
    total_assigned_all_time = db.query(Lead).filter(Lead.assigned_agent_id == target_agent.id).count()
    personal_qualification_rate_pct = _safe_pct(qualified_leads_count, total_assigned_all_time)
    personal_closing_rate_pct = _safe_pct(len(completed_deals), total_assigned_all_time)

    return {
        "agent": {
            "id": target_agent.id,
            "name": target_agent.full_name,
            "username": target_agent.username,
            "email": target_agent.email,
            "role": target_agent.role,
        },
        "period": {
            "label": period_label,
            "start_utc": start_utc.isoformat() if start_utc else None,
            "end_utc": end_utc.isoformat() if end_utc else None,
            "timezone": "Asia/Dubai",
        },
        "action_items": {
            "new_leads_requiring_action": new_leads_action_needed,
            "today_appointments_count": len(today_appts),
            "upcoming_appointments_count": len(upcoming_appts),
            "overdue_followups_count": len(overdue_followups),
            "due_today_followups_count": len(due_today_followups),
            "viewings_awaiting_feedback": viewings_awaiting_feedback,
            "offers_awaiting_response": offers_awaiting_response,
        },
        "pipeline": {
            "assigned_leads_in_period": assigned_in_period,
            "active_leads_total": sum(active_by_status.values()),
            "active_leads_by_status": active_by_status,
            "active_deals_count": len(active_deals),
            "completed_deals_count": len(completed_deals),
            "deals_by_stage": deals_by_stage,
            "estimated_commission_aed": round(estimated_comm, 2),
            "verified_commission_aed": round(verified_comm, 2),
            "qualification_rate_pct": personal_qualification_rate_pct,
            "closing_rate_pct": personal_closing_rate_pct,
        },
    }


# ---------------------------------------------------------------------------
# 4. CSV Export with Formula Injection Protection
# ---------------------------------------------------------------------------

_FORMULA_INJECTION_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _sanitize_csv_cell(val: Any) -> Any:
    """Sanitize strings against CSV / Excel Formula Injection (CWE-1236)."""
    if val is None:
        return ""
    if isinstance(val, (int, float, bool)):
        return val
    s = str(val).strip()
    if s and s[0] in _FORMULA_INJECTION_PREFIXES:
        return "'" + s
    return s


def export_agent_performance_csv(agent_rows: List[Dict[str, Any]]) -> str:
    """Generate CSV string for agent performance table with sanitization."""
    output = io.StringIO()
    fieldnames = [
        "agent_id",
        "name",
        "username",
        "email",
        "role",
        "assigned_leads_in_period",
        "active_leads",
        "qualified_leads",
        "qualification_rate_pct",
        "viewings_conducted",
        "offers_created",
        "offers_accepted",
        "active_deals",
        "completed_deals",
        "closing_rate_pct",
        "estimated_commission_aed",
        "verified_commission_aed",
        "overdue_followups",
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\r\n")
    writer.writeheader()
    for row in agent_rows:
        sanitized = {k: _sanitize_csv_cell(row.get(k, "")) for k in fieldnames}
        writer.writerow(sanitized)
    return output.getvalue()
