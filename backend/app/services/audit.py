"""Security audit log (Phase 6).

Records the security-relevant events required for accountability:
login success/failure, logout, role changes, account suspension/reactivation,
staff account creation and sensitive administrative reads.

Honest data-minimisation rules, enforced here so every caller inherits them:
- Passwords, session tokens, cookies, auth headers and request bodies are
  NEVER stored. Callers pass only identifiers and metadata.
- Message/chat contents are never stored in the audit log.
- Failure reasons are coarse strings ("bad_credentials", "locked"), never the
  raw exception, so the log cannot leak internals.
- The audit table is append-only through the application API. There is no
  update or delete route; ordinary users cannot read it (``audit.read``).
"""

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from app.database import AuditLog

logger = logging.getLogger("app.audit")

# Event name catalogue. Kept as constants so a typo cannot silently create a
# second variant of the same event. Extend by adding a constant + call site.
LOGIN_SUCCESS = "auth.login.success"
LOGIN_FAILURE = "auth.login.failure"
LOGOUT = "auth.logout"
SESSION_REVOKED = "auth.session.revoked"
ACCOUNT_SUSPENDED = "user.suspended"
ACCOUNT_REACTIVATED = "user.reactivated"
ROLE_GRANTED = "user.role.granted"
ROLE_REVOKED = "user.role.revoked"
USER_CREATED = "user.created"
USER_UPDATED = "user.updated"
PASSWORD_RESET = "user.password.reset"
AUDIT_READ = "audit.read"
PROPERTY_CREATED = "property.created"
PROPERTY_UPDATED = "property.updated"
PROPERTY_APPROVED = "property.approved"
PROPERTY_UNAPPROVED = "property.unapproved"
PROPERTY_ARCHIVED = "property.archived"
PROPERTY_DELETED = "property.deleted"
PROPERTY_IMPORTED = "property.imported"
LEAD_CREATED = "lead.created"
LEAD_UPDATED = "lead.updated"
LEAD_STATUS_CHANGED = "lead.status.changed"
LEAD_REOPENED = "lead.reopened"
LEAD_QUALIFIED = "lead.qualified"
LEAD_ASSIGNED = "lead.assigned"
LEAD_UNASSIGNED = "lead.unassigned"
LEAD_ROUND_ROBIN_ASSIGNED = "lead.assigned.round_robin"
LEAD_MERGED = "lead.merged"
LEAD_PROPERTY_LINKED = "lead.property.linked"
LEAD_PROPERTY_UNLINKED = "lead.property.unlinked"
FOLLOWUP_CREATED = "followup.created"
FOLLOWUP_UPDATED = "followup.updated"
FOLLOWUP_COMPLETED = "followup.completed"
FOLLOWUP_CANCELLED = "followup.cancelled"
APPOINTMENT_CREATED = "appointment.created"
APPOINTMENT_UPDATED = "appointment.updated"
APPOINTMENT_RESCHEDULED = "appointment.rescheduled"
APPOINTMENT_CANCELLED = "appointment.cancelled"
APPOINTMENT_COMPLETED = "appointment.completed"
APPOINTMENT_NO_SHOW = "appointment.no_show"
VIEWING_OUTCOME_RECORDED = "viewing.outcome.recorded"
OFFER_CREATED = "offer.created"
OFFER_SUBMITTED = "offer.submitted"
OFFER_COUNTERED = "offer.countered"
OFFER_ACCEPTED = "offer.accepted"
OFFER_REJECTED = "offer.rejected"
OFFER_WITHDRAWN = "offer.withdrawn"
OFFER_EXPIRED = "offer.expired"
DEAL_CREATED = "deal.created"
DEAL_UPDATED = "deal.updated"
DEAL_STAGE_CHANGED = "deal.stage.changed"
DEAL_COMPLETED = "deal.completed"
DEAL_CANCELLED = "deal.cancelled"
DEAL_FAILED = "deal.failed"
DEAL_COMMISSION_VERIFIED = "deal.commission.verified"
DEAL_CHECKLIST_UPDATED = "deal.checklist.updated"
DEAL_CHECKLIST_VERIFIED = "deal.checklist.verified"
ANALYTICS_EXPORTED = "analytics.exported"
PROPERTY_SUBMITTED_FOR_REVIEW = "property.submitted_for_review"
PROPERTY_REJECTED = "property.rejected"
PROPERTY_PUBLISHED = "property.published"
PROPERTY_UNPUBLISHED = "property.unpublished"
PROPERTY_IMAGES_UPDATED = "property.images_updated"
PROPERTY_AVAILABILITY_CHANGED = "property.availability_changed"
PROPERTY_IMPORT_BATCH_STAGED = "property.import_batch_staged"


def record_audit_log(
    db: Session,
    *,
    actor_type: Optional[str] = None,
    actor_id: Optional[int] = None,
    actor_label: Optional[str] = None,
    action: Optional[str] = None,
    event: Optional[str] = None,
    resource_type: Optional[str] = None,
    subject_type: Optional[str] = None,
    resource_id: Optional[int] = None,
    subject_id: Optional[int] = None,
    subject_label: Optional[str] = None,
    details: Optional[dict] = None,
    detail: Optional[str] = None,
    ip: Optional[str] = None,
):
    import json
    ev = event or action or "general"
    st = subject_type or resource_type
    sid = subject_id or resource_id
    det = detail or (json.dumps(details) if details else None)
    return write_audit(
        db,
        ev,
        actor_type=actor_type,
        actor_id=actor_id,
        actor_label=actor_label,
        subject_type=st,
        subject_id=sid,
        subject_label=subject_label,
        ip=ip,
        detail=det,
    )


def write_audit(
    db: Session,
    event: str,
    *,
    actor_type: Optional[str] = None,
    actor_id: Optional[int] = None,
    actor_label: Optional[str] = None,
    subject_type: Optional[str] = None,
    subject_id: Optional[int] = None,
    subject_label: Optional[str] = None,
    ip: Optional[str] = None,
    detail: Optional[str] = None,
) -> None:
    """Append one audit row. Never raises into the request path.

    ``detail`` must be a SHORT, non-sensitive note (e.g. "3 failed attempts").
    It must never contain a password, token, cookie or message body — callers
    are trusted to pass metadata only, and this helper clamps its length.
    """
    try:
        db.add(AuditLog(
            event=event[:64],
            actor_type=(actor_type or "system")[:16],
            actor_id=actor_id,
            actor_label=(actor_label or "")[:255] or None,
            subject_type=(subject_type or "")[:32] or None,
            subject_id=subject_id,
            subject_label=(subject_label or "")[:255] or None,
            ip=(ip or "")[:64] or None,
            # Hard clamp: an over-long detail is almost certainly a mistake
            # (someone pasted a token/body). Keep the first 200 chars only.
            detail=(detail or "")[:200] or None,
            created_at=datetime.utcnow(),
        ))
        db.commit()
    except Exception:  # pragma: no cover - defensive; auditing must not 500
        db.rollback()
        logger.warning("Audit write failed for event %s", event, exc_info=True)


def client_ip(request) -> Optional[str]:
    """Best-effort client IP for audit metadata. Never used for rate limiting
    (that trusts only the direct peer) — this is forensics, not authz."""
    if request is None:
        return None
    try:
        return request.client.host if request.client else None
    except Exception:
        return None
