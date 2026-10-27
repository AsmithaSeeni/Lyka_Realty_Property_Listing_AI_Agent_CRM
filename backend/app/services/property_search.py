import json
import os
import re
import logging
from typing import List, Optional, Dict, Any, Sequence
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# ---------------- Phase 2: database-backed property query constants ----------------
# Verified listing purposes. Anything else is NOT a verified purpose and is
# rejected by the query layer (never silently treated as sale/rent).
VALID_PURPOSES = ("sale", "rent", "lease")
# Availability values matching the `properties` CHECK constraint.
VALID_AVAILABILITY = ("available", "sold", "rented", "reserved", "off_market")

# Currency tokens we explicitly recognise when normalising price strings.
_CURRENCY_TOKENS = ("AED", "USD", "EUR", "GBP", "INR", "AED.", "د.إ")


def parse_price(price_str) -> Optional[float]:
    """Normalise a price to a float, defensively.

    Handles the dataset's Indian-style comma grouping ('65,00,000'),
    western grouping ('1,250,000'), explicit currency tokens
    ('AED 750,000', '750,000 AED', 'USD 1,250,000'), plain numbers, and
    numeric input. Returns None when the value cannot be parsed — missing or
    malformed prices are NEVER treated as a verified number (callers must
    skip/flag them rather than assume 0).
    """
    if price_str is None or price_str == "":
        return None
    if isinstance(price_str, (int, float)):
        value = float(price_str)
        return value if value >= 0 else None
    try:
        text = str(price_str).strip()
        # Drop explicit currency tokens anywhere in the string.
        # Longest-first so "AED." is consumed before "AED" (else ". 750,000"
        # would collapse to a bogus 0.75).
        for token in sorted(_CURRENCY_TOKENS, key=len, reverse=True):
            text = text.replace(token, "")
        # Keep digits, dot and sign only (removes grouping commas, spaces, symbols).
        text = re.sub(r"[^0-9.\-]", "", text)
        if text.startswith("."):
            text = text.lstrip(".")  # a price never legitimately starts with '.'
        if not text or text in ("-", ".", "-."):
            return None
        value = float(text)
        if value < 0:
            return None
        return value
    except (ValueError, TypeError):
        return None


def parse_area(area_str: str) -> Optional[float]:
    """Parse area string like '2,766 sqft' to sqft float."""
    if not area_str:
        return None
    try:
        match = re.match(r"[\d,]+", str(area_str))
        if match:
            return float(match.group().replace(",", ""))
    except (ValueError, TypeError):
        return None
    return None


def parse_beds(beds_str: Any) -> Optional[int]:
    """Bedroom count: 'Studio' -> 0, '3' -> 3, unparseable -> None."""
    text = str(beds_str if beds_str is not None else "").strip()
    if not text:
        return None
    if text.lower() == "studio":
        return 0
    try:
        return int(float(text))
    except (ValueError, TypeError):
        return None


def parse_baths(baths_str: Any) -> Optional[float]:
    """Bathroom count as float; empty/unparseable -> None (filter skipped)."""
    if baths_str in (None, ""):
        return None
    try:
        return float(baths_str)
    except (ValueError, TypeError):
        return None


def _find_dataset() -> Optional[str]:
    """Locate the dataset file, searching common locations."""
    candidates = [
        "UAErealestate.json",
        "uaerealestate.json",
        os.path.join(os.path.dirname(__file__), "..", "..", "UAErealestate.json"),
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "UAErealestate.json"),
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "uaerealestate.json"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


# Cache the loaded dataset in memory (it's read-only)
_properties_cache: Optional[List[Dict[str, Any]]] = None
# Derived lookup structures, built once alongside the cache:
# _search_index - per-row parsed values so filtering never re-parses strings
#                 on all 25k rows per query;
# _id_index     - property_id -> row, replacing per-request linear scans.
_search_index: Optional[List[Dict[str, Any]]] = None
_id_index: Optional[Dict[Any, Dict[str, Any]]] = None


def load_properties(path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Load properties from the dataset JSON file (cached after first load)."""
    global _properties_cache, _search_index, _id_index
    if _properties_cache is not None and path is None:
        return _properties_cache

    file_path = path or _find_dataset()
    if not file_path:
        logger.warning("Dataset file not found")
        return []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            _properties_cache = data.get("properties", [])
            _build_indexes()
            logger.info("Loaded %d properties from %s", len(_properties_cache), file_path)
            return _properties_cache
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error("Failed to load dataset: %s", e)
        return []


def _build_indexes() -> None:
    """Precompute parsed search fields and the id lookup (one-time, ~100ms)."""
    global _search_index, _id_index
    rows = _properties_cache or []
    index: List[Dict[str, Any]] = []
    by_id: Dict[Any, Dict[str, Any]] = {}
    for prop in rows:
        index.append({
            "p": prop,
            "price": parse_price(prop.get("price", "")),
            "beds": parse_beds(prop.get("no__of__beds", "")),
            "baths": parse_baths(prop.get("no_of_baths")),
            "area": parse_area(prop.get("area", "")),
            "loc": str(prop.get("location", "")).lower(),
            "type": str(prop.get("property_type", "")).lower(),
            "high": str(prop.get("highlights", "")).lower(),
        })
        pid = prop.get("property_id")
        if pid is not None:
            by_id[pid] = prop
    _search_index = index
    _id_index = by_id


def get_property_by_id(property_id: Any) -> Optional[Dict[str, Any]]:
    """O(1) dataset lookup by property_id (replaces per-request scans)."""
    if _id_index is None:
        load_properties()
    return (_id_index or {}).get(property_id)


def search_properties(
    db: Session,
    location: Optional[str] = None,
    property_type: Optional[str] = None,
    buy_rent: Optional[str] = None,
    max_price: Optional[float] = None,
    min_price: Optional[float] = None,
    min_bedrooms: Optional[int] = None,
    max_bedrooms: Optional[int] = None,
    min_bathrooms: Optional[float] = None,
    max_bathrooms: Optional[float] = None,
    min_area: Optional[float] = None,
    max_area: Optional[float] = None,
    furnishing: Optional[str] = None,
    amenities: Optional[str] = None,
    developer: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> Dict[str, Any]:
    """
    Deterministic property search that filters and ranks properties based on available fields.
    Never invents property information; recommendations must come from the dataset.

    Runs against a precomputed index of parsed values (price/beds/area and
    lowercased strings), so no string parsing happens inside the 25k-row loop.
    """
    if _search_index is None:
        load_properties()

    loc_filter = location.lower() if location else None
    type_filter = property_type.lower() if property_type else None
    furn_filter = furnishing.lower() if furnishing else None

    results: List[Dict[str, Any]] = []
    for entry in _search_index or []:
        # Location filter (check if location contains the search term)
        if loc_filter is not None and loc_filter not in entry["loc"]:
            continue

        # Property type filter
        if type_filter is not None and type_filter not in entry["type"]:
            continue

        # Buy/Rent filter - dataset doesn't distinguish, so skip (all available)

        # Price filter (price None -> dataset row has no parseable price)
        price = entry["price"]
        if price is not None:
            if max_price is not None and price > max_price:
                continue
            if min_price is not None and price < min_price:
                continue

        # Bedrooms filter ("Studio" counts as 0; unknown -> excluded when filtering)
        if min_bedrooms is not None or max_bedrooms is not None:
            beds = entry["beds"]
            if beds is None:
                continue
            if min_bedrooms is not None and beds < min_bedrooms:
                continue
            if max_bedrooms is not None and beds > max_bedrooms:
                continue

        # Bathrooms filter
        baths = entry["baths"]
        if baths is not None:
            if min_bathrooms is not None and baths < min_bathrooms:
                continue
            if max_bathrooms is not None and baths > max_bathrooms:
                continue

        # Area filter
        area = entry["area"]
        if area is not None:
            if min_area is not None and area < min_area:
                continue
            if max_area is not None and area > max_area:
                continue

        # furnishing filter (search in highlights)
        if furn_filter is not None and furn_filter not in entry["high"]:
            continue

        results.append(entry)

    # Sort by relevance - sort by price (ascending) as default
    results.sort(key=lambda e: e["price"] or 0)

    # Apply pagination (map back to the original dataset rows)
    total = len(results)
    paginated = [e["p"] for e in results[offset:offset + limit]]

    return {
        "results": paginated,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


# ---------------------------------------------------------------------------
# Browse serialization for GET /api/properties/dataset.
#
# The dataset has exactly 8 columns (property_id, price, property_type,
# no__of__beds, no_of_baths, area, highlights, location) and carries NO
# purpose, currency column, title column, images or live availability.
# Every one of those gaps is stated as null here instead of guessed, so the
# browse UI can honestly render "not specified" rather than invent facts.
# ---------------------------------------------------------------------------


def dataset_browse_dict(row: Dict[str, Any]) -> Dict[str, Any]:
    """One UAE-dataset row in the normalized browse schema.

    Mapping rules — verbatim values or explicitly parsed numbers, never
    invented:

    - ``id``: the dataset's own ``property_id`` (unique ints 1..25082). This
      is a DIFFERENT id space from ``properties.id`` (DB records); callers
      must route detail/enquiry links by ``source == "dataset"``.
    - ``title``: the dataset's ``highlights`` headline used verbatim (there
      is no title column; nothing is composed or rewritten). All 25,082 rows
      have non-empty highlights.
    - ``price``: parsed to float via :func:`parse_price` (every row parses;
      handles Indian-style ``65,00,000`` and western grouping). ``currency``
      is AED — the project's established dataset convention (the legacy
      dataset detail view and the agent already render dataset prices as AED).
    - ``purpose`` / ``price_period`` / ``availability``: always None. The
      dataset records no sale-vs-rent intent, no billing period and no live
      availability, and an external row must never be presented as approved
      or available Lyka inventory.
    - ``bedrooms``: parsed int (``"Studio"`` -> 0 via :func:`parse_beds`);
      ``bathrooms`` parsed float; ``area`` parsed float with ``area_unit``
      read from the raw string (all rows are ``"<n> sqft"`` today, but the
      unit is never hardcoded from that assumption).
    - ``images``: always [] — the dataset has no image fields and listing
      photos are never fabricated.
    - ``is_demo``: False — these are real external listing rows, not Lyka's
      synthetic demo records; provenance is carried by ``source`` instead.
    """
    raw_area = str(row.get("area") or "").strip()
    unit_match = re.match(r"^[0-9.,]+\s*(.*)$", raw_area)
    area_unit = (unit_match.group(1).strip() if unit_match else "") or None
    return {
        "id": row.get("property_id"),
        "source": "dataset",
        "title": str(row.get("highlights") or "").strip() or None,
        "price": parse_price(row.get("price")),
        "currency": "AED",
        "purpose": None,
        "price_period": None,
        "property_type": row.get("property_type") or None,
        "bedrooms": parse_beds(row.get("no__of__beds")),
        "bathrooms": parse_baths(row.get("no_of_baths")),
        "area": parse_area(raw_area),
        "area_unit": area_unit,
        "location": str(row.get("location") or ""),
        "highlights": str(row.get("highlights") or ""),
        "images": [],
        "availability": None,
        "is_demo": False,
    }


# =============================================================================
# Phase 2: database-backed property queries (foundation for Phase 4 matching)
# =============================================================================
# BOUNDARY: everything below queries the `properties` table ONLY. It is a
# separate code path from the JSON dataset search above (`search_properties`),
# which is left untouched for the existing chat behaviour. Dataset rows are
# never imported here and never treated as approved/available listings.

from sqlalchemy import func  # noqa: E402  (kept next to the query layer)

from app.database import Property  # noqa: E402


def is_verified_purpose(value) -> bool:
    """True only for an explicitly recognised listing purpose.

    Missing, blank or unknown values are NEVER treated as a verified
    purpose (we do not infer sale/rent from price or free text).
    """
    if not isinstance(value, str):
        return False
    return value.strip().lower() in VALID_PURPOSES


def search_property_records(
    db: Session,
    *,
    purpose: Optional[str] = None,
    availability: Optional[object] = "available",
    approved_only: bool = True,
    location: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    currency: Optional[str] = None,
    property_type: Optional[str] = None,
    min_bedrooms: Optional[int] = None,
    max_bedrooms: Optional[int] = None,
    min_bathrooms: Optional[int] = None,
    amenities: Optional[Sequence[str]] = None,
    limit: int = 20,
    offset: int = 0,
) -> Dict[str, Any]:
    """Query approved `properties` rows with hard eligibility filters.

    Rules enforced here (Phase 2 foundation — the Phase 4 weighted scoring
    layer sits on top of this, it does not weaken it):

    - ``purpose`` must be a verified purpose ('sale' | 'rent' | 'lease') when
      supplied; anything else raises ValueError instead of being guessed.
      Sale queries therefore can never match rent rows and vice versa
      (equality over the verified enum), and lease stays a distinct purpose.
    - By default only APPROVED + AVAILABLE rows are returned; callers must
      opt out explicitly (staff/admin views) to see anything else.
    - Price bounds are compared on normalised numbers (Indian comma grouping
      and currency tokens handled by ``parse_price`` when given as strings).
    - No results → empty list. Nothing is ever invented or back-filled from
      the JSON dataset.

    Returns the same envelope shape as ``search_properties``:
    {"results": [Property, ...], "total": int, "limit": int, "offset": int}
    """
    limit = max(1, min(int(limit or 20), 100))
    offset = max(0, int(offset or 0))

    query = db.query(Property)

    # --- purpose: verified only, otherwise reject loudly ---------------
    if purpose is not None:
        purpose_norm = str(purpose).strip().lower()
        if purpose_norm not in VALID_PURPOSES:
            raise ValueError(
                f"Unknown listing purpose {purpose!r}: not a verified purpose "
                f"(expected one of {', '.join(VALID_PURPOSES)})"
            )
        query = query.filter(Property.purpose == purpose_norm)

    # --- availability: default 'available'; None = no filter (staff view) --
    if availability is None:
        pass
    elif isinstance(availability, str):
        avail_norm = availability.strip().lower()
        if avail_norm not in VALID_AVAILABILITY:
            raise ValueError(
                f"Unknown availability {availability!r} "
                f"(expected one of {', '.join(VALID_AVAILABILITY)} or None)"
            )
        query = query.filter(Property.availability == avail_norm)
    else:
        values = [str(v).strip().lower() for v in availability]
        bad = [v for v in values if v not in VALID_AVAILABILITY]
        if bad:
            raise ValueError(f"Unknown availability value(s): {bad}")
        if values:
            query = query.filter(Property.availability.in_(values))
        else:
            query = query.filter(Property.availability.is_(None))  # empty → nothing

    # --- approval: eligible recommendations are approved-only (default) ---
    if approved_only:
        query = query.filter(Property.is_approved.is_(True))

    # --- location / community: case-insensitive containment -------------
    if location:
        query = query.filter(
            func.lower(Property.location).like(f"%{str(location).strip().lower()}%")
        )

    # --- price range + currency (defensive normalisation) ----------------
    lo = parse_price(min_price) if min_price is not None else None
    hi = parse_price(max_price) if max_price is not None else None
    if min_price is not None and lo is None:
        raise ValueError(f"Unparseable min_price: {min_price!r}")
    if max_price is not None and hi is None:
        raise ValueError(f"Unparseable max_price: {max_price!r}")
    if lo is not None:
        query = query.filter(Property.price >= lo)
    if hi is not None:
        query = query.filter(Property.price <= hi)
    if currency:
        query = query.filter(
            func.upper(Property.currency) == str(currency).strip().upper()
        )

    # --- type & room counts ---------------------------------------------
    if property_type:
        query = query.filter(
            func.lower(Property.property_type)
            == str(property_type).strip().lower()
        )
    if min_bedrooms is not None:
        query = query.filter(Property.bedrooms >= int(min_bedrooms))
    if max_bedrooms is not None:
        query = query.filter(Property.bedrooms <= int(max_bedrooms))
    if min_bathrooms is not None:
        query = query.filter(Property.bathrooms >= int(min_bathrooms))

    # --- amenities: ALL requested must be present (case-insensitive) -----
    if amenities:
        for amenity in amenities:
            token = str(amenity).strip().lower()
            if token:
                query = query.filter(
                    func.lower(Property.amenities).like(f'%"{token}"%')
                )

    total = query.count()
    rows = (
        query.order_by(Property.price.asc(), Property.id.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return {"results": rows, "total": total, "limit": limit, "offset": offset}


# ---------------------------------------------------------------------------
# Phase 6 — public (customer-facing) serialization of DB-backed records.
#
# The `properties` table has no price-period column. The project's established
# convention (documented in property_matching.py and the Phase 2 seeder) is:
#   - sale           -> price is a ONE-TIME purchase price
#   - rent / lease   -> `properties.price` is the YEARLY amount
# Nothing is ever converted or assumed beyond that convention.
# ---------------------------------------------------------------------------
PRICE_PERIOD_BY_PURPOSE = {
    "sale": "one-time",
    "rent": "per year",
    "lease": "per year",
}


def public_record_dict(prop: "Property") -> Dict[str, Any]:
    """Customer-safe serialization of an approved `properties` row.

    Exposes only fields a visitor may see. Internal governance columns
    (``is_approved``, ``source``, ``external_ref``, ``created_at`` /
    ``updated_at``) are deliberately never included so approval flags,
    seeding metadata and administrative timestamps cannot leak through the
    public API.

    ``price_period`` is None (rendered honestly as "not specified" by the
    frontend) whenever the purpose is not one of the verified purposes —
    it is never invented.
    """
    amenities: List[str] = []
    try:
        parsed = json.loads(prop.amenities or "[]")
        if isinstance(parsed, list):
            amenities = [str(a) for a in parsed]
    except (TypeError, ValueError):
        amenities = []
    return {
        "id": prop.id,
        "title": prop.title,
        "description": prop.description or "",
        "purpose": prop.purpose,
        "price": prop.price,
        "currency": prop.currency or "AED",
        "price_period": PRICE_PERIOD_BY_PURPOSE.get(prop.purpose),
        "property_type": prop.property_type,
        "location": prop.location,
        "bedrooms": prop.bedrooms,
        "bathrooms": prop.bathrooms,
        "area": prop.area,
        "area_unit": prop.area_unit or "sqft",
        "amenities": amenities,
        "highlights": prop.highlights or "",
        "availability": prop.availability,
        "is_demo": bool(prop.is_demo),
    }


def get_public_record(db: Session, property_id: int) -> Optional["Property"]:
    """One publicly eligible row, or None.

    A row qualifies only when it is APPROVED and AVAILABLE — the exact same
    eligibility rule as ``search_property_records``. Unknown ids and rows that
    exist but are not publicly eligible both return None so callers can
    answer with an identical 404 and never reveal private inventory.
    """
    return (
        db.query(Property)
        .filter(
            Property.id == int(property_id),
            Property.is_approved.is_(True),
            Property.availability == "available",
        )
        .first()
    )


def get_public_records(db: Session, property_ids: Sequence[int]) -> List["Property"]:
    """Bulk variant of ``get_public_record`` (same eligibility rule)."""
    ids = [int(i) for i in property_ids if i is not None]
    if not ids:
        return []
    return (
        db.query(Property)
        .filter(
            Property.id.in_(ids),
            Property.is_approved.is_(True),
            Property.availability == "available",
        )
        .all()
    )


def record_focus_dict(prop: "Property") -> Dict[str, Any]:
    """Map a DB record into the dataset-shaped focus payload the NVIDIA agent
    already understands (the keys ``agent.respond``/``_context_block`` read:
    ``property_id``, ``property_type``, ``location``, ``price``,
    ``no__of__beds`` ...).

    This lets the enquiry flow discuss a DB-backed listing through the exact
    same agent code path as a dataset listing — no agent or prompt changes.
    """
    return {
        "property_id": prop.id,
        "title": prop.title,
        "property_type": prop.property_type,
        "location": prop.location,
        "price": prop.price,
        "no__of__beds": str(prop.bedrooms) if prop.bedrooms is not None else "",
        "no_of_baths": prop.bathrooms,
        "area": prop.area,
        "highlights": prop.highlights or "",
        "purpose": prop.purpose,
        # Honesty marker (Phase 7): lets the agent's deterministic context
        # block tell the model when the focus listing is fictional demo
        # inventory, so it never presents it as a verified real listing.
        "is_demo": bool(prop.is_demo),
        "source": "record",
    }
