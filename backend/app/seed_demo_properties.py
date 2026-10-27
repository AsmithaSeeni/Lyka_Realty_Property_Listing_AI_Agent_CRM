"""Seed FICTIONAL demo properties into the `properties` table (Phase 2).

Run from backend/:

    python -m app.seed_demo_properties                    # active local DB
    python -m app.seed_demo_properties --dry-run          # preview only
    python -m app.seed_demo_properties --database-url sqlite:///D:/path/other.db

Safety contract:
- Default target is the application's active database (settings.DATABASE_URL,
  the local development file). Targeting ANY other database requires the
  explicit ``--database-url`` command argument (or SEED_DATABASE_URL env),
  which is the intentional action required by the Phase 2 spec.
- This script is NEVER invoked at application startup.
- It creates/updates NO customer, lead, agent or follow-up records — only
  rows in `properties`.
- Idempotent: every row carries a stable ``external_ref``; re-running skips
  existing references, so duplicates are impossible.
- Every seeded row is clearly fictional: ``is_demo=True``, title and
  description both say "Fictional Demo", ``source='demo_seed'``. They are
  approved (``is_approved=True``) ONLY within this explicitly fictional demo
  dataset so demonstration matching has eligible rows — they must never be
  presented as real, currently available Lyka Realty listings.
"""

import argparse
import json
import os
import sys
from typing import Dict, List

# ---------------------------------------------------------------------------
# The fictional dataset: 23 properties across the 5 required Dubai communities.
# Prices are plausible-looking DEMO figures in AED (rental rows are per year).
# ---------------------------------------------------------------------------
DEMO_COMMUNITIES = (
    "Dubai Marina",
    "Business Bay",
    "Downtown Dubai",
    "Jumeirah Village Circle (JVC)",
    "Dubai Hills Estate",
)

FICTION_NOTICE = (
    "FICTIONAL DEMO LISTING — this is synthetic training/demo data, "
    "NOT a real or currently available Lyka Realty property."
)

def _d(title, purpose, ptype, community, beds, baths, price, area, amenities,
       description, availability="available", highlights=None, ref=None):
    return {
        "external_ref": ref,
        "title": title,
        "description": f"{FICTION_NOTICE} {description}",
        "purpose": purpose,
        "availability": availability,
        "price": price,
        "currency": "AED",
        "property_type": ptype,
        "location": community,
        "bedrooms": beds,
        "bathrooms": baths,
        "area": area,
        "area_unit": "sqft",
        "amenities": amenities,
        "highlights": highlights,
        "is_demo": True,
        "is_approved": True,   # approved only within the fictional demo set
        "source": "demo_seed",
    }


DEMO_PROPERTIES: List[Dict] = [
    # ---------------- Dubai Marina (5) ----------------
    _d("Fictional Demo - 2BR Marina Skyline Apartment (Sale)", "sale", "apartment",
       "Dubai Marina", 2, 2, 2_650_000, 1180,
       ["Swimming Pool", "Gym", "Covered Parking", "Balcony", "Sea View"],
       "Two-bedroom fictional apartment with a mock marina-view balcony, "
       "listed for the demo sale catalogue.",
       highlights="Fictional: marina view, high floor, mock listing",
       ref="DEMO-DM-SALE-01"),
    _d("Fictional Demo - 1BR Marina Walk Apartment (Sale)", "sale", "apartment",
       "Dubai Marina", 1, 1, 1_650_000, 720,
       ["Swimming Pool", "Gym", "Covered Parking", "24/7 Security"],
       "One-bedroom fictional apartment near a mock marina promenade.",
       ref="DEMO-DM-SALE-02"),
    _d("Fictional Demo - 2BR Marina View Apartment (Rent)", "rent", "apartment",
       "Dubai Marina", 2, 2, 175_000, 1150,
       ["Swimming Pool", "Gym", "Balcony", "Covered Parking", "Concierge"],
       "Two-bedroom fictional rental, price shown per year for the demo "
       "rental catalogue.",
       ref="DEMO-DM-RENT-01"),
    _d("Fictional Demo - 1BR Marina Plaza Apartment (Rent)", "rent", "apartment",
       "Dubai Marina", 1, 1, 115_000, 700,
       ["Swimming Pool", "Gym", "24/7 Security"],
       "One-bedroom fictional rental, yearly demo price.",
       ref="DEMO-DM-RENT-02"),
    _d("Fictional Demo - Furnished 1BR Marina Residence (Lease)", "lease",
       "apartment", "Dubai Marina", 1, 1, 135_000, 690,
       ["Swimming Pool", "Gym", "Balcony", "Concierge", "Maid's Room"],
       "Furnished fictional long-lease residence for demo purposes; lease is "
       "a purpose distinct from sale and rent.",
       ref="DEMO-DM-LEASE-01"),

    # ---------------- Business Bay (4) ----------------
    _d("Fictional Demo - Studio Business Bay Canal Apartment (Sale)", "sale",
       "studio", "Business Bay", 0, 1, 1_150_000, 480,
       ["Swimming Pool", "Gym", "Covered Parking"],
       "Fictional studio with a mock canal-side view; studio = 0 bedrooms.",
       ref="DEMO-BB-SALE-01"),
    _d("Fictional Demo - 1BR Business Bay Tower Apartment (Sale)", "sale",
       "apartment", "Business Bay", 1, 1, 1_480_000, 760,
       ["Swimming Pool", "Gym", "Balcony", "24/7 Security"],
       "One-bedroom fictional sale listing in a mock Business Bay tower.",
       ref="DEMO-BB-SALE-02"),
    _d("Fictional Demo - 1BR Business Bay Office-View Apartment (Rent)", "rent",
       "apartment", "Business Bay", 1, 1, 125_000, 740,
       ["Gym", "Covered Parking", "24/7 Security"],
       "One-bedroom fictional rental with yearly demo pricing.",
       ref="DEMO-BB-RENT-01"),
    _d("Fictional Demo - 2BR Business Bay Duplex (Lease)", "lease", "townhouse",
       "Business Bay", 2, 3, 210_000, 1350,
       ["Swimming Pool", "Gym", "Balcony", "Maid's Room"],
       "Fictional duplex lease example for the demo catalogue.",
       ref="DEMO-BB-LEASE-01"),

    # ---------------- Downtown Dubai (4) ----------------
    _d("Fictional Demo - 1BR Downtown Boulevard Apartment (Sale)", "sale",
       "apartment", "Downtown Dubai", 1, 1, 2_150_000, 780,
       ["Swimming Pool", "Gym", "Balcony", "Concierge", "24/7 Security"],
       "Fictional one-bedroom sale listing with a mock boulevard view.",
       ref="DEMO-DT-SALE-01"),
    _d("Fictional Demo - 2BR Downtown Skyline Apartment (Rent)", "rent",
       "apartment", "Downtown Dubai", 2, 2, 255_000, 1240,
       ["Swimming Pool", "Gym", "Balcony", "Concierge", "Covered Parking"],
       "Two-bedroom fictional rental, yearly demo price.",
       ref="DEMO-DT-RENT-01"),
    _d("Fictional Demo - 1BR Downtown Fountain View Apartment (Rent)", "rent",
       "apartment", "Downtown Dubai", 1, 1, 168_000, 790,
       ["Swimming Pool", "Gym", "Concierge"],
       "One-bedroom fictional rental with a mock fountain view.",
       ref="DEMO-DT-RENT-02"),
    _d("Fictional Demo - 3BR Downtown Serviced Residence (Lease)", "lease",
       "apartment", "Downtown Dubai", 3, 3, 480_000, 1700,
       ["Swimming Pool", "Gym", "Maid's Room", "Concierge", "Jacuzzi"],
       "Fictional serviced-residence lease for demonstration matching.",
       ref="DEMO-DT-LEASE-01"),

    # ---------------- Jumeirah Village Circle (JVC) (5+1 reserved) --------
    _d("Fictional Demo - Studio JVC Garden Apartment (Sale)", "sale", "studio",
       "Jumeirah Village Circle (JVC)", 0, 1, 650_000, 430,
       ["Covered Parking", "Children's Play Area", "24/7 Security"],
       "Fictional studio sale listing in a mock JVC garden cluster.",
       ref="DEMO-JVC-SALE-01"),
    _d("Fictional Demo - 1BR JVC Parkside Apartment (Sale)", "sale", "apartment",
       "Jumeirah Village Circle (JVC)", 1, 1, 950_000, 690,
       ["Covered Parking", "Balcony", "Children's Play Area", "Gym"],
       "Fictional one-bedroom sale listing beside a mock park.",
       ref="DEMO-JVC-SALE-02"),
    _d("Fictional Demo - Studio JVC Terrace Apartment (Rent)", "rent", "studio",
       "Jumeirah Village Circle (JVC)", 0, 1, 58_000, 420,
       ["Covered Parking", "Balcony"],
       "Fictional studio rental, yearly demo price.",
       ref="DEMO-JVC-RENT-01"),
    _d("Fictional Demo - 1BR JVC Corner Apartment (Rent)", "rent", "apartment",
       "Jumeirah Village Circle (JVC)", 1, 1, 82_000, 670,
       ["Covered Parking", "Gym", "Balcony", "24/7 Security"],
       "Fictional one-bedroom rental, yearly demo price.",
       ref="DEMO-JVC-RENT-02"),
    _d("Fictional Demo - 2BR JVC Family Apartment (Rent)", "rent", "apartment",
       "Jumeirah Village Circle (JVC)", 2, 2, 125_000, 1050,
       ["Covered Parking", "Children's Play Area", "Garden", "Gym"],
       "Fictional two-bedroom family rental, yearly demo price.",
       ref="DEMO-JVC-RENT-03"),
    # Non-available row: valid availability value, excluded from matching.
    _d("Fictional Demo - 1BR JVC Riverside Apartment (Rent, Reserved)",
       "rent", "apartment",
       "Jumeirah Village Circle (JVC)", 1, 1, 88_000, 700,
       ["Covered Parking", "Balcony", "Swimming Pool"],
       "Fictional rental marked 'reserved' to demonstrate that a valid but "
       "non-available status is excluded from eligible recommendations.",
       availability="reserved",
       ref="DEMO-JVC-RENT-04"),

    # ---------------- Dubai Hills Estate (4) ----------------
    _d("Fictional Demo - 3BR Dubai Hills Villa (Sale)", "sale", "villa",
       "Dubai Hills Estate", 3, 4, 5_950_000, 3100,
       ["Garden", "Covered Parking", "Swimming Pool", "Maid's Room",
        "Children's Play Area"],
       "Fictional three-bedroom villa sale listing beside a mock golf course.",
       highlights="Fictional: golf-course community, private garden",
       ref="DEMO-DH-SALE-01"),
    _d("Fictional Demo - 2BR Dubai Hills Apartment (Sale)", "sale", "apartment",
       "Dubai Hills Estate", 2, 2, 2_050_000, 1120,
       ["Swimming Pool", "Gym", "Balcony", "Covered Parking"],
       "Fictional two-bedroom apartment sale listing.",
       ref="DEMO-DH-SALE-02"),
    _d("Fictional Demo - 2BR Dubai Hills Park Apartment (Rent)", "rent",
       "apartment", "Dubai Hills Estate", 2, 2, 175_000, 1100,
       ["Swimming Pool", "Gym", "Garden", "Covered Parking"],
       "Fictional two-bedroom rental, yearly demo price.",
       ref="DEMO-DH-RENT-01"),
    _d("Fictional Demo - 3BR Dubai Hills Townhouse (Rent)", "rent", "townhouse",
       "Dubai Hills Estate", 3, 3, 295_000, 2400,
       ["Garden", "Covered Parking", "Maid's Room", "Children's Play Area"],
       "Fictional three-bedroom townhouse rental, yearly demo price.",
       ref="DEMO-DH-RENT-02"),
]

# Convenience: stable unique refs are mandatory for idempotent seeding.
for _row in DEMO_PROPERTIES:
    assert _row["external_ref"], "every demo row needs a stable external_ref"
    assert _row["is_demo"] is True
    assert "Fictional Demo" in _row["title"] and "FICTIONAL DEMO" in _row["description"]
assert len({r["external_ref"] for r in DEMO_PROPERTIES}) == len(DEMO_PROPERTIES)
assert len(DEMO_PROPERTIES) >= 20
assert {r["location"] for r in DEMO_PROPERTIES} == set(DEMO_COMMUNITIES)


def seed_demo_properties(engine_=None, dry_run: bool = False):
    """Insert missing demo rows. Existing external_refs are skipped.

    Returns a summary dict: created, skipped, total_demo_rows, by_community,
    by_purpose, dry_run.
    """
    from sqlalchemy import func
    from sqlalchemy.orm import sessionmaker

    from app.database import Base, Property

    if engine_ is None:
        from app import database as dbmod
        engine_ = dbmod.engine

    # Ensure schema exists (create_all/migrations are idempotent + additive).
    Base.metadata.create_all(bind=engine_)
    try:
        from app.database import _ensure_indexes, _run_migrations
        _run_migrations(engine_)
        _ensure_indexes(engine_)
    except Exception as exc:  # pragma: no cover - defensive
        print(f"warning: post-create migration step reported: {exc}")

    SessionLocal = sessionmaker(bind=engine_, autoflush=False)
    db = SessionLocal()
    created, skipped = [], []
    try:
        for row in DEMO_PROPERTIES:
            found = (
                db.query(Property)
                .filter(Property.external_ref == row["external_ref"])
                .first()
            )
            if found is not None:
                skipped.append(row["external_ref"])
                continue
            if dry_run:
                created.append(row["external_ref"])
                continue
            payload = dict(row)
            payload["amenities"] = json.dumps(payload["amenities"], ensure_ascii=False)
            db.add(Property(**payload))
            created.append(row["external_ref"])
        if not dry_run and created:
            db.commit()

        by_comm, by_purp = {}, {}
        if dry_run:
            for row in DEMO_PROPERTIES:
                by_comm[row["location"]] = by_comm.get(row["location"], 0) + 1
                by_purp[row["purpose"]] = by_purp.get(row["purpose"], 0) + 1
            total_demo = len(DEMO_PROPERTIES)
        else:
            for loc, n in db.query(Property.location, func.count(Property.id)).filter(
                Property.is_demo.is_(True)
            ).group_by(Property.location):
                by_comm[loc] = n
            for purp, n in db.query(Property.purpose, func.count(Property.id)).filter(
                Property.is_demo.is_(True)
            ).group_by(Property.purpose):
                by_purp[purp] = n
            total_demo = (
                db.query(func.count(Property.id)).filter(Property.is_demo.is_(True)).scalar() or 0
            )
        return {
            "created": len(created),
            "skipped": len(skipped),
            "total_demo_rows": total_demo,
            "by_community": by_comm,
            "by_purpose": by_purp,
            "dry_run": dry_run,
        }
    finally:
        db.close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Seed FICTIONAL demo properties (never runs at app startup)."
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Intentional override to seed a DIFFERENT database. "
             "Default: the active local database (settings.DATABASE_URL).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report what would be created without writing anything.",
    )
    args = parser.parse_args(argv)

    explicit = args.database_url or os.environ.get("SEED_DATABASE_URL") or None
    if explicit:
        url = explicit
        print(f"SEED TARGET (explicit override): {url}")
    else:
        from app.config import settings
        url = settings.DATABASE_URL
        print(f"SEED TARGET (default active local DB): {url}")

    if not url:
        print("error: empty database URL — refusing to run", file=sys.stderr)
        return 2

    from sqlalchemy import create_engine
    engine = create_engine(
        url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
    )
    summary = seed_demo_properties(engine_=engine, dry_run=args.dry_run)

    verb = "would create" if args.dry_run else "created"
    print(f"Demo properties {verb}: {summary['created']}, "
          f"already present (skipped): {summary['skipped']}")
    print("By community:", json.dumps(summary["by_community"], indent=2))
    print("By purpose:", json.dumps(summary["by_purpose"], indent=2))
    if not args.dry_run:
        print(f"Total rows in properties table: {summary['total_demo_rows']}")
    print("All seeded rows are fictional (is_demo=True, source='demo_seed').")
    return 0


if __name__ == "__main__":
    sys.exit(main())
