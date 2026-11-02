"""Property Import Preview and Staging Pipeline (Phase I).

Provides safe, audited ingestion for property records:
- Dry-run validation & preview with zero database writes
- Detailed quality metrics, price distribution, and error sample reporting
- Staging mode: imports records strictly as UNVERIFIED, UNAPPROVED, UNPUBLISHED, OFF-MARKET
- Exact external_ref deduplication and fuzzy candidate flagging
- Batch audit logging linked to `property_import_batches` table
- Test fixture utilities for isolated synthetic testing
"""

import datetime
import json
import logging
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple
from sqlalchemy.orm import Session

from app.database import Property, PropertyImportBatch
from app.services.audit import record_audit_log
from app.services.property_validator import validate_property_payload

logger = logging.getLogger("lyka.importer")


def generate_batch_id() -> str:
    """Generate human-readable unique batch identifier."""
    now_str = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    rand_suffix = uuid.uuid4().hex[:6].upper()
    return f"BATCH-{now_str}-{rand_suffix}"


def preview_import_records(
    db: Session,
    records: List[Dict[str, Any]],
    preview_limit: int = 10,
) -> Dict[str, Any]:
    """Dry-run validation of a list of raw property records.

    Zero mutations are made to the database. Returns comprehensive quality
    metrics, distributions, and sample validation results.
    """
    total = len(records)
    valid_count = 0
    invalid_count = 0
    duplicate_count = 0

    seen_refs: Set[str] = set()
    preview_items: List[Dict[str, Any]] = []
    sample_errors: List[Dict[str, Any]] = []
    property_type_counts: Dict[str, int] = {}
    location_counts: Dict[str, int] = {}
    prices: List[float] = []

    for idx, raw in enumerate(records):
        # Format raw record for validator if it has dataset keys
        record_data = dict(raw)
        if "highlights" in record_data and not record_data.get("title"):
            record_data["title"] = record_data["highlights"]
        if "property_id" in record_data and not record_data.get("external_ref"):
            record_data["external_ref"] = f"UAE-{record_data['property_id']}"
        if "no__of__beds" in record_data and "bedrooms" not in record_data:
            record_data["bedrooms"] = record_data["no__of__beds"]
        if "no_of_baths" in record_data and "bathrooms" not in record_data:
            record_data["bathrooms"] = record_data["no_of_baths"]

        val_result = validate_property_payload(
            record_data,
            db=db,
            batch_external_refs=seen_refs,
        )

        is_valid = val_result["is_valid"]
        if is_valid:
            valid_count += 1
            norm = val_result["normalized_data"]
            ptype = norm.get("property_type") or "Unknown"
            property_type_counts[ptype] = property_type_counts.get(ptype, 0) + 1
            
            loc = norm.get("community") or norm.get("location") or "Unknown"
            location_counts[loc] = location_counts.get(loc, 0) + 1
            
            p = norm.get("price")
            if p and p > 0:
                prices.append(p)
        else:
            invalid_count += 1
            if len(sample_errors) < 10:
                sample_errors.append({
                    "row_index": idx,
                    "external_ref": record_data.get("external_ref"),
                    "title": record_data.get("title") or record_data.get("highlights"),
                    "errors": val_result["errors"],
                    "warnings": val_result["warnings"],
                })

        if val_result.get("duplicate_candidate"):
            duplicate_count += 1

        if len(preview_items) < preview_limit:
            preview_items.append({
                "row_index": idx,
                "is_valid": is_valid,
                "errors": val_result["errors"],
                "warnings": val_result["warnings"],
                "normalized": val_result["normalized_data"] if is_valid else None,
                "duplicate_candidate": val_result.get("duplicate_candidate"),
            })

    # Summary calculations
    price_stats = {
        "min": min(prices) if prices else 0,
        "max": max(prices) if prices else 0,
        "avg": (sum(prices) / len(prices)) if prices else 0,
    }

    # Sort distributions
    top_types = sorted(property_type_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    top_locs = sorted(location_counts.items(), key=lambda x: x[1], reverse=True)[:5]

    return {
        "total_records": total,
        "valid_records": valid_count,
        "invalid_records": invalid_count,
        "duplicate_records": duplicate_count,
        "preview_items": preview_items,
        "sample_errors": sample_errors,
        "price_summary": price_stats,
        "top_property_types": dict(top_types),
        "top_locations": dict(top_locs),
    }


def stage_import_batch(
    db: Session,
    records: List[Dict[str, Any]],
    *,
    source: str = "uae_dataset",
    filename: Optional[str] = None,
    actor_id: Optional[int] = None,
    skip_duplicates: bool = True,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Execute import into staging state with strict safety gates.

    All imported properties are created with:
    - `is_approved = False`
    - `is_published = False`
    - `verification_status = 'unverified'`
    - `availability = 'off_market'`

    They can NEVER leak into customer searches without explicit manual review
    and publication approval by authorized staff.
    """
    batch_id = generate_batch_id()

    # If dry run, just preview
    if dry_run:
        preview = preview_import_records(db, records)
        preview["batch_id"] = batch_id
        preview["dry_run"] = True
        return preview

    seen_refs: Set[str] = set()
    total = len(records)
    valid_count = 0
    invalid_count = 0
    duplicate_count = 0
    imported_count = 0

    validation_errors: List[Dict[str, Any]] = []
    staged_property_ids: List[int] = []

    for idx, raw in enumerate(records):
        record_data = dict(raw)
        if "highlights" in record_data and not record_data.get("title"):
            record_data["title"] = record_data["highlights"]
        if "property_id" in record_data and not record_data.get("external_ref"):
            record_data["external_ref"] = f"UAE-{record_data['property_id']}"
        if "no__of__beds" in record_data and "bedrooms" not in record_data:
            record_data["bedrooms"] = record_data["no__of__beds"]
        if "no_of_baths" in record_data and "bathrooms" not in record_data:
            record_data["bathrooms"] = record_data["no_of_baths"]

        val_result = validate_property_payload(
            record_data,
            db=db,
            batch_external_refs=seen_refs,
        )

        if not val_result["is_valid"]:
            invalid_count += 1
            if len(validation_errors) < 20:
                validation_errors.append({
                    "row_index": idx,
                    "external_ref": record_data.get("external_ref"),
                    "errors": val_result["errors"],
                })
            continue

        valid_count += 1
        is_dup = val_result.get("duplicate_candidate") is not None
        if is_dup:
            duplicate_count += 1
            if skip_duplicates:
                continue

        norm = val_result["normalized_data"]

        # Build staged property record
        prop = Property(
            external_ref=norm.get("external_ref") or f"IMP-{batch_id}-{idx + 1}",
            title=norm["title"],
            description=norm.get("description") or f"Staged property listing from batch {batch_id}",
            purpose=norm["purpose"],
            availability="off_market",  # Safely quarantined off-market
            price=norm["price"],
            currency=norm["currency"],
            property_type=norm["property_type"],
            location=norm["location"],
            bedrooms=norm["bedrooms"],
            bathrooms=norm["bathrooms"],
            area=norm["area"],
            area_unit=norm["area_unit"],
            amenities=norm["amenities"],
            highlights=norm.get("highlights"),
            images=norm["images"],
            primary_image=norm.get("primary_image"),
            is_approved=False,  # Unapproved by default
            is_published=False,  # Unpublished by default
            verification_status="unverified",
            source=source,
            source_id=norm.get("source_id"),
            import_batch_id=batch_id,
        )
        db.add(prop)
        imported_count += 1

    db.flush()

    # Create batch record
    batch_record = PropertyImportBatch(
        batch_id=batch_id,
        source=source,
        filename=filename,
        status="completed" if imported_count > 0 else "failed",
        total_records=total,
        valid_records=valid_count,
        invalid_records=invalid_count,
        duplicate_records=duplicate_count,
        imported_records=imported_count,
        validation_report=json.dumps({
            "errors": validation_errors,
            "sample_error_count": len(validation_errors),
        }, ensure_ascii=False),
        created_by_agent_id=actor_id,
        completed_at=datetime.datetime.utcnow(),
    )
    db.add(batch_record)
    db.commit()

    # Record audit log
    try:
        record_audit_log(
            db,
            actor_type="agent" if actor_id else "system",
            actor_id=actor_id,
            action="PROPERTY_IMPORT_BATCH_STAGED",
            resource_type="property_import_batch",
            resource_id=batch_record.id,
            details={
                "batch_id": batch_id,
                "source": source,
                "total": total,
                "valid": valid_count,
                "imported": imported_count,
                "duplicates": duplicate_count,
            },
        )
    except Exception as exc:
        logger.warning("Failed to record audit log for batch %s: %s", batch_id, exc)

    return {
        "batch_id": batch_id,
        "batch_record_id": batch_record.id,
        "total_records": total,
        "valid_records": valid_count,
        "invalid_records": invalid_count,
        "duplicate_records": duplicate_count,
        "imported_records": imported_count,
        "status": batch_record.status,
    }

