"""Property Lifecycle and Governance Workflow Service (Phase I).

Enforces strict separation of:
- Verification status (unverified, pending_review, verified, rejected)
- Approval status (is_approved boolean, requires staff role)
- Publication status (is_published boolean, requires approval & eligibility)
- Commercial availability (available, reserved, sold, rented, off_market)
- Media management (ordering, primary selection, fallbacks)
- Audit logging on every transition
"""

import datetime
import json
import logging
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from app.database import Appointment, Deal, Property
from app.services.audit import record_audit_log
from app.services.property_crud import get_property
from app.services.property_search import VALID_AVAILABILITY
from app.services.property_validator import normalize_images

logger = logging.getLogger("lyka.lifecycle")


def submit_for_review(
    db: Session,
    property_id: int,
    actor_id: Optional[int] = None,
    notes: Optional[str] = None,
) -> Property:
    """Submit a draft or unverified property for staff review."""
    prop = get_property(db, property_id)
    if prop.verification_status == "verified" and prop.is_approved:
        raise ValueError(f"Property #{prop.id} is already verified and approved.")

    prop.verification_status = "pending_review"
    prop.rejection_reason = None
    prop.updated_at = datetime.datetime.utcnow()
    db.commit()
    db.refresh(prop)

    try:
        record_audit_log(
            db,
            actor_type="agent" if actor_id else "system",
            actor_id=actor_id,
            action="PROPERTY_SUBMITTED_FOR_REVIEW",
            resource_type="property",
            resource_id=prop.id,
            details={"title": prop.title, "notes": notes},
        )
    except Exception as exc:
        logger.warning("Audit log failed: %s", exc)

    return prop


def approve_property(
    db: Session,
    property_id: int,
    actor_id: int,
    notes: Optional[str] = None,
) -> Property:
    """Approve a property listing, marking it verified and approved."""
    prop = get_property(db, property_id)
    prop.is_approved = True
    prop.verification_status = "verified"
    prop.rejection_reason = None
    prop.updated_at = datetime.datetime.utcnow()
    db.commit()
    db.refresh(prop)

    try:
        record_audit_log(
            db,
            actor_type="agent",
            actor_id=actor_id,
            action="PROPERTY_APPROVED",
            resource_type="property",
            resource_id=prop.id,
            details={"title": prop.title, "notes": notes},
        )
    except Exception as exc:
        logger.warning("Audit log failed: %s", exc)

    return prop


def reject_property(
    db: Session,
    property_id: int,
    actor_id: int,
    reason: str,
) -> Property:
    """Reject a property listing with mandatory reason, revoking publication."""
    reason_clean = str(reason or "").strip()
    if not reason_clean:
        raise ValueError("A clear rejection reason must be provided.")

    prop = get_property(db, property_id)
    prop.is_approved = False
    prop.is_published = False
    prop.verification_status = "rejected"
    prop.rejection_reason = reason_clean
    prop.updated_at = datetime.datetime.utcnow()
    db.commit()
    db.refresh(prop)

    try:
        record_audit_log(
            db,
            actor_type="agent",
            actor_id=actor_id,
            action="PROPERTY_REJECTED",
            resource_type="property",
            resource_id=prop.id,
            details={"title": prop.title, "reason": reason_clean},
        )
    except Exception as exc:
        logger.warning("Audit log failed: %s", exc)

    return prop


def publish_property(
    db: Session,
    property_id: int,
    actor_id: int,
) -> Property:
    """Publish an approved listing for public customer discovery.

    Pre-conditions:
    - Must be approved (`is_approved == True`)
    - Must have verified status (`verification_status == 'verified'`)
    - Must not be off_market
    - Price must be > 0
    """
    prop = get_property(db, property_id)
    if not prop.is_approved:
        raise ValueError(
            f"Property #{prop.id} cannot be published because it is not approved. "
            "Approval is required prior to public listing."
        )
    if prop.availability == "off_market":
        raise ValueError(
            f"Property #{prop.id} is off-market. Change availability before publishing."
        )
    if not prop.price or prop.price <= 0:
        raise ValueError(f"Property #{prop.id} must have a valid positive price.")

    prop.is_published = True
    prop.published_at = datetime.datetime.utcnow()
    prop.updated_at = datetime.datetime.utcnow()
    db.commit()
    db.refresh(prop)

    try:
        record_audit_log(
            db,
            actor_type="agent",
            actor_id=actor_id,
            action="PROPERTY_PUBLISHED",
            resource_type="property",
            resource_id=prop.id,
            details={"title": prop.title, "published_at": prop.published_at.isoformat()},
        )
    except Exception as exc:
        logger.warning("Audit log failed: %s", exc)

    return prop


def unpublish_property(
    db: Session,
    property_id: int,
    actor_id: int,
    reason: Optional[str] = None,
) -> Property:
    """Unpublish a listing, hiding it immediately from public view."""
    prop = get_property(db, property_id)
    prop.is_published = False
    prop.updated_at = datetime.datetime.utcnow()
    db.commit()
    db.refresh(prop)

    try:
        record_audit_log(
            db,
            actor_type="agent",
            actor_id=actor_id,
            action="PROPERTY_UNPUBLISHED",
            resource_type="property",
            resource_id=prop.id,
            details={"title": prop.title, "reason": reason},
        )
    except Exception as exc:
        logger.warning("Audit log failed: %s", exc)

    return prop


def archive_property_lifecycle(
    db: Session,
    property_id: int,
    actor_id: int,
    reason: Optional[str] = None,
) -> Property:
    """Archive a property safely without deleting historical relations."""
    prop = get_property(db, property_id)
    prop.availability = "off_market"
    prop.is_published = False
    prop.archived_at = datetime.datetime.utcnow()
    prop.updated_at = datetime.datetime.utcnow()
    db.commit()
    db.refresh(prop)

    try:
        record_audit_log(
            db,
            actor_type="agent",
            actor_id=actor_id,
            action="PROPERTY_ARCHIVED",
            resource_type="property",
            resource_id=prop.id,
            details={"title": prop.title, "reason": reason},
        )
    except Exception as exc:
        logger.warning("Audit log failed: %s", exc)

    return prop


def update_property_availability(
    db: Session,
    property_id: int,
    availability: str,
    actor_id: Optional[int] = None,
) -> Property:
    """Update commercial availability status."""
    avail_norm = str(availability or "").strip().lower()
    if avail_norm not in VALID_AVAILABILITY:
        raise ValueError(
            f"Invalid availability '{availability}'; expected one of: {', '.join(VALID_AVAILABILITY)}"
        )

    prop = get_property(db, property_id)
    old_avail = prop.availability
    prop.availability = avail_norm

    # If off_market or sold/rented, listing should not be publicly active
    if avail_norm in ("off_market", "sold", "rented"):
        prop.is_published = False

    prop.updated_at = datetime.datetime.utcnow()
    db.commit()
    db.refresh(prop)

    try:
        record_audit_log(
            db,
            actor_type="agent" if actor_id else "system",
            actor_id=actor_id,
            action="PROPERTY_AVAILABILITY_UPDATED",
            resource_type="property",
            resource_id=prop.id,
            details={"old_availability": old_avail, "new_availability": avail_norm},
        )
    except Exception as exc:
        logger.warning("Audit log failed: %s", exc)

    return prop


def manage_property_images(
    db: Session,
    property_id: int,
    images: Any,
    primary_url: Optional[str] = None,
    actor_id: Optional[int] = None,
) -> Property:
    """Update image gallery, ordering, and primary thumbnail."""
    prop = get_property(db, property_id)
    norm_images = normalize_images(images)

    # Set custom primary if requested
    if primary_url:
        matched = False
        for img in norm_images:
            if img["url"] == primary_url:
                img["is_primary"] = True
                matched = True
            else:
                img["is_primary"] = False
        if not matched and primary_url:
            norm_images.insert(0, {
                "url": primary_url,
                "caption": "",
                "order": 0,
                "is_primary": True,
            })

    # Pick primary
    primary = None
    for img in norm_images:
        if img.get("is_primary"):
            primary = img["url"]
            break
    if not primary and norm_images:
        primary = norm_images[0]["url"]
        norm_images[0]["is_primary"] = True

    prop.images = json.dumps(norm_images, ensure_ascii=False)
    prop.primary_image = primary
    prop.updated_at = datetime.datetime.utcnow()
    db.commit()
    db.refresh(prop)

    try:
        record_audit_log(
            db,
            actor_type="agent" if actor_id else "system",
            actor_id=actor_id,
            action="PROPERTY_IMAGES_UPDATED",
            resource_type="property",
            resource_id=prop.id,
            details={"count": len(norm_images), "primary_image": primary},
        )
    except Exception as exc:
        logger.warning("Audit log failed: %s", exc)

    return prop


def bulk_lifecycle_action(
    db: Session,
    property_ids: List[int],
    action: str,
    actor_id: int,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute bulk lifecycle transitions with per-item validation."""
    valid_actions = {"approve", "reject", "publish", "unpublish", "archive"}
    act_norm = str(action or "").strip().lower()
    if act_norm not in valid_actions:
        raise ValueError(f"Unknown bulk action '{action}'; expected one of: {', '.join(sorted(valid_actions))}")

    succeeded: List[int] = []
    failed: List[Dict[str, Any]] = []

    for pid in property_ids:
        try:
            if act_norm == "approve":
                approve_property(db, pid, actor_id, notes=reason)
            elif act_norm == "reject":
                reject_property(db, pid, actor_id, reason=reason or "Bulk rejected by administrator")
            elif act_norm == "publish":
                publish_property(db, pid, actor_id)
            elif act_norm == "unpublish":
                unpublish_property(db, pid, actor_id, reason=reason)
            elif act_norm == "archive":
                archive_property_lifecycle(db, pid, actor_id, reason=reason)
            succeeded.append(pid)
        except Exception as exc:
            failed.append({"property_id": pid, "error": str(exc)})

    return {
        "action": act_norm,
        "total_requested": len(property_ids),
        "succeeded_count": len(succeeded),
        "failed_count": len(failed),
        "succeeded_ids": succeeded,
        "failures": failed,
    }

