"""Database-backed property CRUD operations (Phase 2 foundation).

Design rules:
- Keep validation/query logic out of route handlers. Routes (added fully in
  Phase 5) only handle auth, request parsing and HTTP status mapping.
- Service functions never do authentication themselves — they receive an
  already-authorized staff session from the route layer. The one authorization
  rule enforced HERE regardless of caller: approval status can only be changed
  when the caller explicitly opts in via ``allow_approval_change=True``, which
  staff routes will do after server-side RBAC checks. Customer-facing code
  paths never pass that flag, so they can never modify approval.
- Validation failures raise ValueError (routes map these to 422/403 later).
- Nothing here ever touches the JSON dataset or the NVIDIA agent.
"""

import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import Property, PropertyRecommendation, SavedProperty
from app.services.property_search import (
    VALID_AVAILABILITY,
    VALID_PURPOSES,
    parse_price,
)

SAVED_RECORD_ID_BASE = 1_000_000

# Fields a caller may set on create.
_CREATE_FIELDS = (
    "title", "description", "purpose", "availability", "price", "currency",
    "property_type", "location", "bedrooms", "bathrooms", "area", "area_unit",
    "amenities", "highlights", "external_ref", "source", "images", "primary_image",
    "source_id", "import_batch_id", "is_published", "verification_status",
)

# Fields allowed in an update. `is_approved`, `is_published`, and `verification_status`
# are deliberately handled apart (allow_approval_change gate). `is_demo` may only be set at creation.
_UPDATE_FIELDS = (
    "title", "description", "purpose", "availability", "price", "currency",
    "property_type", "location", "bedrooms", "bathrooms", "area", "area_unit",
    "amenities", "highlights", "external_ref", "images", "primary_image",
    "rejection_reason",
)


def _normalize_amenities(value: Any) -> str:
    """Accept a list/tuple/set or a JSON string; return a canonical JSON array."""
    if value is None:
        return "[]"
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return "[]"
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"amenities is not valid JSON: {exc}") from exc
        value = parsed
    if not isinstance(value, (list, tuple, set)):
        raise ValueError("amenities must be a list of strings")
    cleaned: List[str] = []
    seen = set()
    for item in value:
        text = str(item).strip()
        key = text.lower()
        if text and key not in seen:
            seen.add(key)
            cleaned.append(text)
    return json.dumps(cleaned, ensure_ascii=False)


def _validate_purpose(purpose: Any) -> str:
    if not isinstance(purpose, str) or purpose.strip().lower() not in VALID_PURPOSES:
        raise ValueError(
            f"Unknown listing purpose {purpose!r}: expected one of "
            f"{', '.join(VALID_PURPOSES)}"
        )
    return purpose.strip().lower()


def _validate_availability(availability: Any) -> str:
    if availability is None:
        return "available"
    if (
        not isinstance(availability, str)
        or availability.strip().lower() not in VALID_AVAILABILITY
    ):
        raise ValueError(
            f"Unknown availability {availability!r}: expected one of "
            f"{', '.join(VALID_AVAILABILITY)}"
        )
    return availability.strip().lower()


def _validate_price(price: Any) -> float:
    if isinstance(price, str):
        parsed = parse_price(price)
        if parsed is None:
            raise ValueError(f"Unparseable price: {price!r}")
        price = parsed
    if not isinstance(price, (int, float)) or isinstance(price, bool):
        raise ValueError(f"price must be a number, got {price!r}")
    if price < 0:
        raise ValueError(f"price must be >= 0, got {price!r}")
    return float(price)


def _validate_int(value: Any, field: str, minimum: int = 0) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value:
        raise ValueError(f"{field} must be an integer, got {value!r}")
    value = int(value)
    if value < minimum:
        raise ValueError(f"{field} must be >= {minimum}, got {value}")
    return value


def create_property(db: Session, data: Dict[str, Any]) -> Property:
    """Create a property record. All validation errors raise ValueError.

    ``is_demo``/``is_approved`` are accepted ONLY at creation time; the
    caller (staff route, Phase 5) is responsible for RBAC. Defaults are the
    safe ones: not approved, not demo, availability 'available'.
    """
    if not isinstance(data, dict):
        raise ValueError("property data must be an object")

    unknown = set(data) - set(_CREATE_FIELDS) - {"is_approved", "is_demo"}
    if unknown:
        raise ValueError(f"Unknown property field(s): {sorted(unknown)}")

    title = str(data.get("title") or "").strip()
    if not title:
        raise ValueError("title is required")

    location = str(data.get("location") or "").strip()
    if not location:
        raise ValueError("location is required")

    property_type = str(data.get("property_type") or "").strip()
    if not property_type:
        raise ValueError("property_type is required")

    bedrooms = _validate_int(data.get("bedrooms", 0), "bedrooms") or 0
    bathrooms = _validate_int(data.get("bathrooms", 1), "bathrooms")
    if bathrooms is None or bathrooms < 1:
        raise ValueError("bathrooms must be >= 1")
    area = data.get("area")
    if area is not None:
        if not isinstance(area, (int, float)) or isinstance(area, bool) or area < 0:
            raise ValueError(f"area must be a non-negative number, got {area!r}")
        area = float(area)

    external_ref = data.get("external_ref")
    if external_ref is not None:
        external_ref = str(external_ref).strip() or None
        if external_ref:
            existing = (
                db.query(Property)
                .filter(Property.external_ref == external_ref)
                .first()
            )
            if existing is not None:
                raise ValueError(
                    f"external_ref {external_ref!r} already exists (id={existing.id})"
                )

    prop = Property(
        external_ref=external_ref,
        title=title,
        description=str(data.get("description") or "").strip(),
        purpose=_validate_purpose(data.get("purpose")),
        availability=_validate_availability(data.get("availability")),
        price=_validate_price(data.get("price")),
        currency=str(data.get("currency") or "AED").strip().upper() or "AED",
        property_type=property_type,
        location=location,
        bedrooms=bedrooms,
        bathrooms=bathrooms,
        area=area,
        area_unit=str(data.get("area_unit") or "sqft").strip() or "sqft",
        amenities=_normalize_amenities(data.get("amenities")),
        highlights=data.get("highlights"),
        images=str(data.get("images") or "[]"),
        primary_image=str(data.get("primary_image")).strip() if data.get("primary_image") else None,
        source_id=str(data.get("source_id")).strip() if data.get("source_id") else None,
        import_batch_id=str(data.get("import_batch_id")).strip() if data.get("import_batch_id") else None,
        verification_status=(
            str(data.get("verification_status") or "unverified").strip().lower()
            if "verification_status" in data
            else ("verified" if data.get("is_approved") else "unverified")
        ),
        is_published=(
            bool(data.get("is_published"))
            if "is_published" in data
            else bool(data.get("is_approved", False))
        ),
        is_approved=bool(data.get("is_approved", False)),
        is_demo=bool(data.get("is_demo", False)),
        source=str(data.get("source") or "manual").strip() or "manual",
    )
    db.add(prop)
    db.commit()
    db.refresh(prop)
    return prop


def get_property(db: Session, property_id: int) -> Property:
    prop = db.query(Property).filter(Property.id == int(property_id)).first()
    if prop is None:
        raise ValueError(f"Property {property_id} not found")
    return prop


def update_property(
    db: Session,
    property_id: int,
    changes: Dict[str, Any],
    *,
    allow_approval_change: bool = False,
) -> Property:
    """Apply a partial update. Returns the updated record.

    ``is_approved`` can only change when ``allow_approval_change=True``
    (staff-only routes after RBAC). Passing it otherwise raises ValueError so
    a customer-facing caller fails loudly instead of silently succeeding.
    """
    if not isinstance(changes, dict):
        raise ValueError("changes must be an object")
    prop = get_property(db, property_id)

    unknown = set(changes) - set(_UPDATE_FIELDS) - {"is_approved", "is_published", "verification_status"}
    if unknown:
        raise ValueError(f"Unknown property field(s): {sorted(unknown)}")

    if ("is_approved" in changes or "is_published" in changes or "verification_status" in changes) and not allow_approval_change:
        raise ValueError(
            "Changing approval or publication status is not permitted for this caller"
        )

    for field in _UPDATE_FIELDS:
        if field not in changes:
            continue
        value = changes[field]
        if field == "purpose":
            value = _validate_purpose(value)
        elif field == "availability":
            value = _validate_availability(value)
        elif field == "price":
            value = _validate_price(value)
        elif field == "amenities":
            value = _normalize_amenities(value)
        elif field in ("bedrooms", "bathrooms"):
            value = _validate_int(value, field)
            if field == "bathrooms" and (value is None or value < 1):
                raise ValueError("bathrooms must be >= 1")
            if field == "bedrooms" and value is None:
                value = 0
        elif field == "area":
            if value is not None:
                if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
                    raise ValueError(f"area must be a non-negative number, got {value!r}")
                value = float(value)
        elif field in ("title", "location", "property_type"):
            text_val = str(value or "").strip()
            if not text_val:
                raise ValueError(f"{field} cannot be empty")
            value = text_val
        elif field == "description":
            value = str(value or "").strip()
        elif field == "area_unit" and value is not None:
            value = str(value).strip() or "sqft"
        elif field == "currency" and value is not None:
            value = str(value).strip().upper() or "AED"
        elif field == "external_ref":
            ext_val = str(value).strip() if value is not None else None
            ext_val = ext_val or None
            if ext_val and ext_val != prop.external_ref:
                existing = (
                    db.query(Property)
                    .filter(
                        Property.external_ref == ext_val,
                        Property.id != prop.id,
                    )
                    .first()
                )
                if existing is not None:
                    raise ValueError(
                        f"external_ref {ext_val!r} already exists (id={existing.id})"
                    )
            value = ext_val
        setattr(prop, field, value)

    if "is_approved" in changes:
        prop.is_approved = bool(changes["is_approved"])
        if prop.is_approved and "is_published" not in changes and not getattr(prop, "is_published", False):
            prop.is_published = True
            if not getattr(prop, "verification_status", None) or prop.verification_status == "unverified":
                prop.verification_status = "verified" 
    if "is_published" in changes:
        prop.is_published = bool(changes["is_published"])
    if "verification_status" in changes:
        prop.verification_status = str(changes["verification_status"]).strip().lower()

    prop.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(prop)
    return prop


def property_reference_counts(db: Session, property_id: int) -> Dict[str, int]:
    """Return counts of CRM records referencing this property row."""
    from app.database import Appointment, Deal, Offer

    pid = int(property_id)
    rec_count = (
        db.query(func.count(PropertyRecommendation.id))
        .filter(PropertyRecommendation.property_record_id == pid)
        .scalar()
        or 0
    )
    saved_count = (
        db.query(func.count(SavedProperty.id))
        .filter(SavedProperty.property_id == (SAVED_RECORD_ID_BASE + pid))
        .scalar()
        or 0
    )
    appt_count = (
        db.query(func.count(Appointment.id))
        .filter(Appointment.property_id == pid)
        .scalar()
        or 0
    )
    offer_count = (
        db.query(func.count(Offer.id))
        .filter(Offer.property_id == pid)
        .scalar()
        or 0
    )
    deal_count = (
        db.query(func.count(Deal.id))
        .filter(Deal.property_id == pid)
        .scalar()
        or 0
    )
    return {
        "recommendations": int(rec_count),
        "saved": int(saved_count),
        "appointments": int(appt_count),
        "offers": int(offer_count),
        "deals": int(deal_count),
        "total": int(rec_count) + int(saved_count) + int(appt_count) + int(offer_count) + int(deal_count),
    }


def archive_property(db: Session, property_id: int) -> Property:
    """Safely archive a property (`availability='off_market'`, `is_approved=False`).

    Preserves historical lead recommendations and saved-property references while
    immediately removing the property from public customer browsing and active
    lead matching.
    """
    prop = get_property(db, property_id)
    prop.availability = "off_market"
    prop.is_approved = False
    prop.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(prop)
    return prop


def delete_property(db: Session, property_id: int) -> None:
    """Delete an unreferenced property record.

    If the property is referenced by lead recommendations or customer bookmarks,
    hard deletion is refused with a ValueError instructing the caller to archive
    the property instead so historical CRM integrity is never broken.
    """
    prop = get_property(db, property_id)
    refs = property_reference_counts(db, prop.id)
    if refs["total"] > 0:
        raise ValueError(
            f"Property {prop.id} is referenced by {refs['recommendations']} lead "
            f"recommendation(s) and {refs['saved']} saved bookmark(s); archive it "
            f"instead of deleting to preserve historical records."
        )
    db.delete(prop)
    db.commit()


def list_properties(
    db: Session,
    *,
    purpose: Optional[str] = None,
    availability: Optional[object] = None,
    approved: Optional[bool] = None,
    is_published: Optional[bool] = None,
    verification_status: Optional[str] = None,
    is_demo: Optional[bool] = None,
    source: Optional[str] = None,
    exclude_sources: Optional[Sequence[str]] = None,
    location: Optional[str] = None,
    property_type: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    min_bedrooms: Optional[int] = None,
    max_bedrooms: Optional[int] = None,
    q: Optional[str] = None,
    sort: str = "newest",
    limit: int = 20,
    offset: int = 0,
) -> Tuple[List[Property], int]:
    """Filtered, paginated listing. Returns ``(rows, total)``.

    Unlike ``search_property_records`` this is an ADMIN/STAFF view: no eligibility
    filter is applied unless the caller asks for one (each parameter is
    optional; ``None`` means "no filter").
    """
    limit = max(1, min(int(limit or 20), 100))
    offset = max(0, int(offset or 0))

    query = db.query(Property)
    if purpose is not None:
        query = query.filter(Property.purpose == _validate_purpose(purpose))
    if availability is not None:
        if isinstance(availability, str):
            query = query.filter(
                Property.availability == _validate_availability(availability)
            )
        else:
            values = [_validate_availability(v) for v in availability]
            query = query.filter(Property.availability.in_(values))
    if approved is not None:
        query = query.filter(Property.is_approved.is_(bool(approved)))
    if is_published is not None:
        query = query.filter(Property.is_published.is_(bool(is_published)))
    if verification_status is not None and str(verification_status).strip():
        query = query.filter(func.lower(Property.verification_status) == str(verification_status).strip().lower())
    if is_demo is not None:
        query = query.filter(Property.is_demo.is_(bool(is_demo)))
    if source is not None and str(source).strip():
        query = query.filter(
            func.lower(Property.source) == str(source).strip().lower()
        )
    if exclude_sources:
        excluded = [str(s).strip().lower() for s in exclude_sources if str(s).strip()]
        if excluded:
            query = query.filter(~func.lower(Property.source).in_(excluded))
    if location:
        query = query.filter(
            func.lower(Property.location).like(f"%{str(location).strip().lower()}%")
        )
    if property_type:
        query = query.filter(
            func.lower(Property.property_type)
            == str(property_type).strip().lower()
        )
    if min_price is not None:
        query = query.filter(Property.price >= _validate_price(min_price))
    if max_price is not None:
        query = query.filter(Property.price <= _validate_price(max_price))
    if min_bedrooms is not None:
        query = query.filter(
            Property.bedrooms >= (_validate_int(min_bedrooms, "min_bedrooms") or 0)
        )
    if max_bedrooms is not None:
        query = query.filter(
            Property.bedrooms <= (_validate_int(max_bedrooms, "max_bedrooms") or 0)
        )
    if q:
        token = f"%{str(q).strip().lower()}%"
        query = query.filter(
            func.lower(Property.title).like(token)
            | func.lower(Property.location).like(token)
            | func.lower(func.coalesce(Property.description, "")).like(token)
            | func.lower(func.coalesce(Property.external_ref, "")).like(token)
        )

    total = query.count()
    order = {
        "newest": Property.created_at.desc(),
        "oldest": Property.created_at.asc(),
        "price_asc": Property.price.asc(),
        "price_desc": Property.price.desc(),
        "updated_desc": Property.updated_at.desc(),
    }.get(sort)
    if order is None:
        raise ValueError(
            f"Unknown sort {sort!r} "
            "(expected newest|oldest|price_asc|price_desc|updated_desc)"
        )
    rows = query.order_by(order, Property.id.asc()).offset(offset).limit(limit).all()
    return rows, total


def inventory_summary(
    db: Session,
    *,
    exclude_sources: Optional[Sequence[str]] = None,
    include_demo: bool = False,
) -> Dict[str, int]:
    """Return real database counts across key inventory lifecycle states.

    Raw, uncurated dataset rows (`source='uae_dataset'`, `is_approved=False`,
    `availability='off_market'`) are tracked separately in `dataset_*` counters
    so they never inflate CRM `total` or `archived` KPIs unexpectedly, while any
    dataset row promoted/curated into CRM workflow (`is_approved=True` or
    `availability != 'off_market'`) is included in the active CRM KPIs.
    """
    dataset_base = db.query(Property).filter(
        func.lower(Property.source) == "uae_dataset"
    )
    dataset_total = dataset_base.count()
    dataset_approved = dataset_base.filter(Property.is_approved.is_(True)).count()
    dataset_unapproved = dataset_base.filter(Property.is_approved.is_(False)).count()

    base = db.query(Property)
    if exclude_sources:
        excluded = [str(s).strip().lower() for s in exclude_sources if str(s).strip()]
        if excluded:
            base = base.filter(~func.lower(Property.source).in_(excluded))
    else:
        # Exclude raw uncurated uae_dataset rows (is_approved=False & off_market)
        # from active CRM KPIs so importing 25,082 market rows does not report
        # 25,082 "Archived" CRM listings.
        base = base.filter(
            (func.lower(Property.source) != "uae_dataset")
            | Property.is_approved.is_(True)
            | (Property.availability != "off_market")
        )

    if not include_demo:
        base = base.filter(Property.is_demo.is_(False))
    total = base.count()
    published = (
        base.filter(
            Property.is_approved.is_(True),
            Property.is_published.is_(True),
            Property.availability == "available",
        ).count()
    )
    pending_approval = (
        base.filter(
            (Property.verification_status == "pending_review")
            | (Property.is_approved.is_(False) & (Property.availability != "off_market"))
        ).count()
    )
    unverified = base.filter(Property.verification_status == "unverified").count()
    rejected = base.filter(Property.verification_status == "rejected").count()
    reserved_or_closed = (
        base.filter(
            Property.availability.in_(("reserved", "sold", "rented"))
        ).count()
    )
    archived = base.filter(Property.availability == "off_market").count()
    return {
        "total": int(total),
        "published": int(published),
        "pending_approval": int(pending_approval),
        "unverified": int(unverified),
        "rejected": int(rejected),
        "reserved_or_closed": int(reserved_or_closed),
        "archived": int(archived),
        "dataset_total": int(dataset_total),
        "dataset_approved": int(dataset_approved),
        "dataset_unapproved": int(dataset_unapproved),
    }


def staff_property_dict(
    prop: Property,
    *,
    reference_counts: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """Serialize a Property row for authorized staff/admin endpoints."""
    try:
        amenities_list = json.loads(prop.amenities or "[]")
        if not isinstance(amenities_list, list):
            amenities_list = []
    except Exception:
        amenities_list = []
    payload: Dict[str, Any] = {
        "id": prop.id,
        "external_ref": prop.external_ref,
        "title": prop.title,
        "description": prop.description or "",
        "purpose": prop.purpose,
        "availability": prop.availability,
        "price": prop.price,
        "currency": prop.currency or "AED",
        "property_type": prop.property_type,
        "location": prop.location,
        "bedrooms": prop.bedrooms,
        "bathrooms": prop.bathrooms,
        "area": prop.area,
        "area_unit": prop.area_unit or "sqft",
        "amenities": amenities_list,
        "highlights": prop.highlights,
        "is_approved": bool(prop.is_approved),
        "is_published": bool(getattr(prop, "is_published", False)),
        "verification_status": getattr(prop, "verification_status", "unverified") or "unverified",
        "rejection_reason": getattr(prop, "rejection_reason", None),
        "published_at": prop.published_at.isoformat() if getattr(prop, "published_at", None) else None,
        "images": json.loads(getattr(prop, "images", "[]") or "[]") if isinstance(getattr(prop, "images", None), str) else (getattr(prop, "images", []) or []),
        "primary_image": getattr(prop, "primary_image", None),
        "source_id": getattr(prop, "source_id", None),
        "import_batch_id": getattr(prop, "import_batch_id", None),
        "archived_at": prop.archived_at.isoformat() if getattr(prop, "archived_at", None) else None,
        "is_demo": bool(prop.is_demo),
        "source": prop.source or "manual",
        "created_at": prop.created_at.isoformat() if prop.created_at else None,
        "updated_at": prop.updated_at.isoformat() if prop.updated_at else None,
    }
    if reference_counts is not None:
        payload["reference_counts"] = reference_counts
    return payload
