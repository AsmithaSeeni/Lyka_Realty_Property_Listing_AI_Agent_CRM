"""Reusable Property Validation and Normalization Service (Phase I).

Validates, sanitizes, and normalizes property listing payloads across:
- Manual single listing creation / editing by agents or admins
- Import preview and batch staging pipelines
- Staged dataset records from UAErealestate.json or CSV uploads

Features:
- Strict typing and bounds checking (price > 0, beds >= 0, baths >= 1, area > 0)
- Currency awareness (AED canonical; flags non-AED or missing currency)
- Numeric string normalization (Indian grouping '65,00,000' and western '1,250,000')
- Community / emirate normalization with original location preserved
- Exact external reference duplicate detection
- Heuristic candidate duplicate detection (location + type + beds + close price)
"""

import json
import re
from typing import Any, Dict, List, Optional, Set, Tuple
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import Property
from app.services.property_search import (
    VALID_AVAILABILITY,
    VALID_PURPOSES,
    parse_area,
    parse_baths,
    parse_beds,
    parse_price,
)

SUPPORTED_PROPERTY_TYPES = {
    "apartment": "Apartment",
    "villa": "Villa",
    "townhouse": "Townhouse",
    "penthouse": "Penthouse",
    "hotel apartment": "Hotel Apartment",
    "duplex": "Duplex",
    "studio": "Studio",
    "residential floor": "Residential Floor",
    "residential building": "Residential Building",
    "compound": "Compound",
    "land": "Residential Plot",
    "residential plot": "Residential Plot",
    "commercial": "Commercial",
    "office": "Office",
}

UAE_EMIRATES = {
    "dubai": "Dubai",
    "abu dhabi": "Abu Dhabi",
    "sharjah": "Sharjah",
    "ajman": "Ajman",
    "ras al khaimah": "Ras Al Khaimah",
    "fujairah": "Fujairah",
    "umm al quwain": "Umm Al Quwain",
}


def normalize_property_type(raw_type: Any) -> Tuple[str, Optional[str]]:
    """Normalize property type into standard display case.
    Returns (normalized_type, warning_or_none).
    """
    if not raw_type:
        return "Apartment", "Missing property type, defaulted to Apartment"
    text = str(raw_type).strip()
    key = text.lower()
    if key in SUPPORTED_PROPERTY_TYPES:
        return SUPPORTED_PROPERTY_TYPES[key], None
    # If not in exact list, title-case it and return warning
    clean = " ".join(part.capitalize() for part in text.split())
    return clean, f"Uncommon property type: '{text}'"


def normalize_location(raw_location: Any) -> Tuple[str, Dict[str, Optional[str]]]:
    """Clean location string and parse emirate if detectable.
    Returns (cleaned_location, {"community": ..., "emirate": ...}).
    """
    cleaned = str(raw_location or "").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    emirate = None
    lower_loc = cleaned.lower()
    for em_key, em_name in UAE_EMIRATES.items():
        if em_key in lower_loc:
            emirate = em_name
            break

    # Attempt to extract community (often the first segment before comma)
    parts = [p.strip() for p in cleaned.split(",") if p.strip()]
    community = parts[0] if parts else cleaned

    return cleaned, {"community": community, "emirate": emirate}


def normalize_images(raw_images: Any) -> List[Dict[str, Any]]:
    """Standardize images into a structured list of image objects:
    [{"url": str, "caption": str, "order": int, "is_primary": bool}]
    """
    if not raw_images:
        return []
    items: List[Any] = []
    if isinstance(raw_images, str):
        text = raw_images.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                items = parsed
            elif isinstance(parsed, dict):
                items = [parsed]
            else:
                items = [text]
        except Exception:
            items = [url.strip() for url in text.split(",") if url.strip()]
    elif isinstance(raw_images, (list, tuple, set)):
        items = list(raw_images)
    elif isinstance(raw_images, dict):
        items = [raw_images]

    result: List[Dict[str, Any]] = []
    primary_set = False
    for idx, item in enumerate(items):
        if isinstance(item, str):
            url = item.strip()
            if url:
                result.append({
                    "url": url,
                    "caption": "",
                    "order": idx,
                    "is_primary": not primary_set,
                })
                primary_set = True
        elif isinstance(item, dict):
            url = str(item.get("url") or item.get("src") or "").strip()
            if url:
                is_prim = bool(item.get("is_primary", False))
                if is_prim and not primary_set:
                    primary_set = True
                elif is_prim and primary_set:
                    is_prim = False  # Only one primary
                result.append({
                    "url": url,
                    "caption": str(item.get("caption") or "").strip(),
                    "order": int(item.get("order", idx)),
                    "is_primary": is_prim,
                })
    if result and not any(img.get("is_primary") for img in result):
        result[0]["is_primary"] = True
    return result


def validate_property_payload(
    data: Dict[str, Any],
    *,
    db: Optional[Session] = None,
    current_property_id: Optional[int] = None,
    batch_external_refs: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """Validate and normalize a property payload.

    Args:
        data: Raw property dictionary.
        db: Optional database session for duplicate checking.
        current_property_id: ID of property being updated (to exclude self in duplicate checks).
        batch_external_refs: Set of external_refs already seen in the current batch.

    Returns:
        {
            "is_valid": bool,
            "errors": List[str],
            "warnings": List[str],
            "normalized_data": Dict[str, Any],
            "duplicate_candidate": Optional[Dict[str, Any]],
        }
    """
    errors: List[str] = []
    warnings: List[str] = []

    if not isinstance(data, dict):
        return {
            "is_valid": False,
            "errors": ["Property payload must be a JSON object"],
            "warnings": [],
            "normalized_data": {},
            "duplicate_candidate": None,
        }

    # Title
    raw_title = str(data.get("title") or data.get("highlights") or "").strip()
    if not raw_title:
        errors.append("Title is required and cannot be empty")
    elif len(raw_title) < 3:
        errors.append("Title must be at least 3 characters long")

    # Purpose
    raw_purpose = data.get("purpose")
    if not raw_purpose:
        # Default purpose to sale if missing in imported external datasets, but warn
        purpose = "sale"
        warnings.append("Listing purpose missing; defaulted to 'sale'")
    else:
        purp_str = str(raw_purpose).strip().lower()
        if purp_str not in VALID_PURPOSES:
            errors.append(f"Invalid purpose '{raw_purpose}'; must be one of: {', '.join(VALID_PURPOSES)}")
            purpose = "sale"
        else:
            purpose = purp_str

    # Availability
    raw_avail = data.get("availability")
    if raw_avail is None:
        availability = "available"
    else:
        avail_str = str(raw_avail).strip().lower()
        if avail_str not in VALID_AVAILABILITY:
            errors.append(f"Invalid availability '{raw_avail}'; must be one of: {', '.join(VALID_AVAILABILITY)}")
            availability = "available"
        else:
            availability = avail_str

    # Price
    raw_price = data.get("price")
    parsed_price = parse_price(raw_price)
    if parsed_price is None:
        errors.append(f"Price is missing or malformed: {raw_price!r}")
        price = 0.0
    elif parsed_price <= 0:
        errors.append(f"Price must be strictly positive (> 0), got: {parsed_price}")
        price = parsed_price
    else:
        price = parsed_price

    # Currency
    raw_curr = data.get("currency")
    if not raw_curr:
        currency = "AED"
        warnings.append("Currency not specified; defaulted to AED")
    else:
        curr_str = str(raw_curr).strip().upper()
        if curr_str != "AED":
            warnings.append(f"Non-standard currency '{curr_str}' specified (default is AED)")
        currency = curr_str or "AED"

    # Property Type
    raw_type = data.get("property_type")
    prop_type, type_warn = normalize_property_type(raw_type)
    if type_warn:
        warnings.append(type_warn)

    # Location
    raw_loc = data.get("location")
    if not raw_loc or not str(raw_loc).strip():
        errors.append("Location is required")
        location = ""
        loc_meta: Dict[str, Optional[str]] = {"community": None, "emirate": None}
    else:
        location, loc_meta = normalize_location(raw_loc)
        if not loc_meta.get("emirate"):
            warnings.append(f"Could not identify UAE emirate in location '{location}'")

    # Bedrooms
    raw_beds = data.get("bedrooms")
    if raw_beds is None:
        raw_beds = data.get("no__of__beds")
    if raw_beds in (None, "", "studio", "Studio"):
        bedrooms = 0
    else:
        p_beds = parse_beds(raw_beds)
        if p_beds is None or p_beds < 0:
            errors.append(f"Invalid bedroom count: {raw_beds!r}")
            bedrooms = 0
        else:
            bedrooms = p_beds

    # Bathrooms
    raw_baths = data.get("bathrooms")
    if raw_baths is None:
        raw_baths = data.get("no_of_baths")
    if raw_baths in (None, ""):
        bathrooms = 1
    else:
        p_baths = parse_baths(raw_baths)
        if p_baths is None or p_baths < 1:
            errors.append(f"Invalid bathroom count: {raw_baths!r} (must be >= 1)")
            bathrooms = 1
        else:
            bathrooms = int(round(p_baths))

    # Area & Unit
    raw_area = data.get("area")
    area: Optional[float] = None
    area_unit = str(data.get("area_unit") or "sqft").strip() or "sqft"
    if raw_area not in (None, ""):
        p_area = parse_area(str(raw_area))
        if p_area is None or p_area <= 0:
            warnings.append(f"Unparseable area value: {raw_area!r}")
        else:
            area = p_area
    else:
        warnings.append("Listing does not specify property area")

    # Description & Highlights
    description = str(data.get("description") or "").strip()
    highlights = str(data.get("highlights") or "").strip() or None

    # Amenities
    raw_amenities = data.get("amenities")
    amenities_list: List[str] = []
    if isinstance(raw_amenities, str):
        try:
            parsed = json.loads(raw_amenities)
            if isinstance(parsed, list):
                amenities_list = [str(a).strip() for a in parsed if str(a).strip()]
        except Exception:
            amenities_list = [a.strip() for a in raw_amenities.split(",") if a.strip()]
    elif isinstance(raw_amenities, (list, tuple, set)):
        amenities_list = [str(a).strip() for a in raw_amenities if str(a).strip()]

    # Images
    images_list = normalize_images(data.get("images"))
    primary_img = None
    for img in images_list:
        if img.get("is_primary"):
            primary_img = img["url"]
            break
    if not primary_img and images_list:
        primary_img = images_list[0]["url"]

    # External Ref & Deduplication
    raw_ext_ref = data.get("external_ref")
    external_ref = str(raw_ext_ref).strip() if raw_ext_ref is not None else None
    if external_ref == "":
        external_ref = None

    duplicate_candidate = None

    # Batch duplicate check
    if external_ref and batch_external_refs is not None:
        if external_ref in batch_external_refs:
            errors.append(f"Duplicate external_ref '{external_ref}' within current batch")
        else:
            batch_external_refs.add(external_ref)

    # Database duplicate check
    if db is not None:
        if external_ref:
            q = db.query(Property).filter(Property.external_ref == external_ref)
            if current_property_id is not None:
                q = q.filter(Property.id != current_property_id)
            existing_exact = q.first()
            if existing_exact:
                errors.append(f"Property with external_ref '{external_ref}' already exists (ID #{existing_exact.id})")
                duplicate_candidate = {
                    "type": "exact_external_ref",
                    "property_id": existing_exact.id,
                    "title": existing_exact.title,
                    "external_ref": existing_exact.external_ref,
                    "price": existing_exact.price,
                }

        # Fuzzy duplicate candidate check (same community/location + type + beds + price within 1%)
        if not duplicate_candidate and price > 0 and location:
            price_lo = price * 0.99
            price_hi = price * 1.01
            comm = loc_meta.get("community") or location
            fuzzy_q = db.query(Property).filter(
                Property.property_type == prop_type,
                Property.bedrooms == bedrooms,
                Property.price >= price_lo,
                Property.price <= price_hi,
                func.lower(Property.location).like(f"%{comm.lower()}%")
            )
            if current_property_id is not None:
                fuzzy_q = fuzzy_q.filter(Property.id != current_property_id)
            match = fuzzy_q.first()
            if match:
                warnings.append(
                    f"Possible duplicate listing found: #{match.id} '{match.title}' "
                    f"({match.property_type}, {match.bedrooms} beds, AED {match.price:,.0f} in {match.location})"
                )
                duplicate_candidate = {
                    "type": "fuzzy_match",
                    "property_id": match.id,
                    "title": match.title,
                    "external_ref": match.external_ref,
                    "price": match.price,
                    "location": match.location,
                }

    normalized_data = {
        "title": raw_title,
        "description": description,
        "purpose": purpose,
        "availability": availability,
        "price": price,
        "currency": currency,
        "property_type": prop_type,
        "location": location,
        "community": loc_meta.get("community"),
        "emirate": loc_meta.get("emirate"),
        "bedrooms": bedrooms,
        "bathrooms": bathrooms,
        "area": area,
        "area_unit": area_unit,
        "amenities": json.dumps(amenities_list, ensure_ascii=False),
        "highlights": highlights,
        "images": json.dumps(images_list, ensure_ascii=False),
        "primary_image": primary_img,
        "external_ref": external_ref,
        "source": str(data.get("source") or "manual").strip() or "manual",
        "source_id": str(data.get("source_id") or data.get("property_id") or "").strip() or None,
    }

    return {
        "is_valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "normalized_data": normalized_data,
        "duplicate_candidate": duplicate_candidate,
    }

