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

from app.database import Property
from app.services.property_search import (
    VALID_AVAILABILITY,
    VALID_PURPOSES,
    parse_price,
)

# Fields a caller may set on create.
_CREATE_FIELDS = (
    "title", "description", "purpose", "availability", "price", "currency",
    "property_type", "location", "bedrooms", "bathrooms", "area", "area_unit",
    "amenities", "highlights", "external_ref", "source",
)

# Fields allowed in an update. `is_approved` is deliberately handled apart
# (allow_approval_change gate). `is_demo` may only be set at creation so a
# record's fictional/real provenance can never be rewritten afterwards.
_UPDATE_FIELDS = (
    "title", "description", "purpose", "availability", "price", "currency",
    "property_type", "location", "bedrooms", "bathrooms", "area", "area_unit",
    "amenities", "highlights",
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

    unknown = set(changes) - set(_UPDATE_FIELDS) - {"is_approved"}
    if unknown:
        raise ValueError(f"Unknown property field(s): {sorted(unknown)}")

    if "is_approved" in changes and not allow_approval_change:
        raise ValueError(
            "Changing approval status is not permitted for this caller"
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
        elif field in ("title", "location", "property_type") and not str(value or "").strip():
            raise ValueError(f"{field} cannot be empty")
        elif field == "currency" and value is not None:
            value = str(value).strip().upper() or "AED"
        setattr(prop, field, value)

    if "is_approved" in changes:
        prop.is_approved = bool(changes["is_approved"])

    prop.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(prop)
    return prop


def delete_property(db: Session, property_id: int) -> None:
    prop = get_property(db, property_id)
    db.delete(prop)
    db.commit()


def list_properties(
    db: Session,
    *,
    purpose: Optional[str] = None,
    availability: Optional[object] = None,
    approved: Optional[bool] = None,
    is_demo: Optional[bool] = None,
    location: Optional[str] = None,
    property_type: Optional[str] = None,
    q: Optional[str] = None,
    sort: str = "newest",
    limit: int = 20,
    offset: int = 0,
) -> Tuple[List[Property], int]:
    """Filtered, paginated listing. Returns ``(rows, total)``.

    Unlike ``search_property_records`` this is an ADMIN view: no eligibility
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
    if is_demo is not None:
        query = query.filter(Property.is_demo.is_(bool(is_demo)))
    if location:
        query = query.filter(
            func.lower(Property.location).like(f"%{str(location).strip().lower()}%")
        )
    if property_type:
        query = query.filter(
            func.lower(Property.property_type)
            == str(property_type).strip().lower()
        )
    if q:
        token = f"%{str(q).strip().lower()}%"
        query = query.filter(
            func.lower(Property.title).like(token)
            | func.lower(Property.location).like(token)
            | func.lower(Property.description).like(token)
        )

    total = query.count()
    order = {
        "newest": Property.created_at.desc(),
        "oldest": Property.created_at.asc(),
        "price_asc": Property.price.asc(),
        "price_desc": Property.price.desc(),
    }.get(sort)
    if order is None:
        raise ValueError(
            f"Unknown sort {sort!r} "
            "(expected newest|oldest|price_asc|price_desc)"
        )
    rows = query.order_by(order, Property.id.asc()).offset(offset).limit(limit).all()
    return rows, total
