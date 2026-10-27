"""Repeatable, idempotent import script to load UAErealestate.json into Turso (libSQL) or local SQLite.

Usage:
    # Run against active target from env (DATABASE_URL & TURSO_AUTH_TOKEN in .env):
    python -m app.import_dataset_turso

    # Dry-run preview:
    python -m app.import_dataset_turso --dry-run

    # Test with first 100 rows:
    python -m app.import_dataset_turso --limit 100

    # Explicit Turso URL override:
    python -m app.import_dataset_turso --database-url libsql://my-db.turso.io --auth-token <TOKEN>

Safety & Governance:
    - Never prints, commits or exposes database tokens.
    - Idempotent: Every record has external_ref = "UAE-{property_id}".
      Re-running skips existing references; duplicates are impossible.
    - Unapproved & Off-Market: is_approved=False, availability="off_market",
      source="uae_dataset", is_demo=False.
      Dataset rows are NEVER assumed to be approved Lyka Realty stock.
    - Uses native Turso HTTP Pipeline protocol (v2/pipeline) with httpx,
      enabling seamless execution on Windows without requiring Rust or
      non-Windows drivers, and falls back to local SQLite when DATABASE_URL
      is a local file.
"""

import argparse
import datetime
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import httpx
from dotenv import load_dotenv

# Load repo-root and backend .env
load_dotenv()
_backend_dir = Path(__file__).resolve().parent.parent
load_dotenv(_backend_dir / ".env")
load_dotenv(_backend_dir.parent / ".env")

_CURRENCY_TOKENS = ("AED", "USD", "EUR", "GBP", "INR", "AED.", "د.إ")


def parse_price(price_str: Any) -> Optional[float]:
    """Normalise price to float."""
    if price_str is None or price_str == "":
        return None
    if isinstance(price_str, (int, float)):
        val = float(price_str)
        return val if val >= 0 else None
    try:
        text = str(price_str).strip()
        for token in sorted(_CURRENCY_TOKENS, key=len, reverse=True):
            text = text.replace(token, "")
        text = re.sub(r"[^0-9.\-]", "", text)
        if text.startswith("."):
            text = text.lstrip(".")
        if not text or text in ("-", ".", "-."):
            return None
        val = float(text)
        return val if val >= 0 else None
    except (ValueError, TypeError):
        return None


def parse_area(area_str: Any) -> Optional[float]:
    """Parse area string like '2,766 sqft' to float."""
    if not area_str:
        return None
    try:
        m = re.match(r"[\d,]+", str(area_str))
        if m:
            return float(m.group().replace(",", ""))
    except (ValueError, TypeError):
        return None
    return None


def parse_beds(beds_str: Any) -> Optional[int]:
    """Parse beds: Studio -> 0, '3' -> 3."""
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
    """Parse baths to float."""
    if baths_str in (None, ""):
        return None
    try:
        return float(baths_str)
    except (ValueError, TypeError):
        return None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("lyka.import")

# Estimated storage per row in SQLite is ~240 bytes.
# 25,082 rows consume ~5.7 MB (well within Turso free tier 9GB limit).
ESTIMATED_BYTES_PER_ROW = 240
TURSO_FREE_STORAGE_BYTES = 9 * 1024 * 1024 * 1024  # 9 GB
DEFAULT_BATCH_SIZE = 250


def find_dataset_file() -> Path:
    """Find UAErealestate.json in backend or workspace root."""
    backend_dir = Path(__file__).resolve().parent.parent
    candidates = [
        backend_dir / "UAErealestate.json",
        backend_dir.parent / "UAErealestate.json",
        Path("UAErealestate.json"),
        Path("backend/UAErealestate.json"),
    ]
    for c in candidates:
        if c.is_file():
            return c
    raise FileNotFoundError(
        "Could not find UAErealestate.json dataset file in standard locations."
    )


def clean_row(raw: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Map raw UAE dataset row to Property model fields.
    Returns None if the record cannot be safely mapped.
    """
    pid = raw.get("property_id")
    if pid is None:
        return None

    try:
        pid_int = int(pid)
    except (ValueError, TypeError):
        return None

    raw_price = raw.get("price")
    price = parse_price(raw_price)
    if price is None or price < 0:
        return None

    raw_beds = raw.get("no__of__beds")
    beds = parse_beds(raw_beds)
    if beds is None or beds < 0:
        beds = 0  # Studio / unstated defaults to 0

    raw_baths = raw.get("no_of_baths")
    baths_float = parse_baths(raw_baths)
    if baths_float is None or baths_float < 1:
        bathrooms = 1
    else:
        bathrooms = int(round(baths_float))

    raw_area = str(raw.get("area") or "").strip()
    area = parse_area(raw_area)
    unit_match = re.match(r"^[0-9.,]+\s*(.*)$", raw_area)
    area_unit = (unit_match.group(1).strip() if unit_match else "") or "sqft"

    location = str(raw.get("location") or "").strip()
    if not location:
        return None

    property_type = str(raw.get("property_type") or "").strip() or "Apartment"
    highlights = str(raw.get("highlights") or "").strip()
    title = highlights if highlights else f"{property_type} in {location}"
    description = (
        f"External UAE real estate market listing (Reference ID: {pid_int}). "
        f"Location: {location}. Highlights: {highlights or 'None'}"
    )

    now_iso = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    return {
        "external_ref": f"UAE-{pid_int}",
        "title": title,
        "description": description,
        "purpose": "sale",
        "availability": "off_market",
        "price": float(price),
        "currency": "AED",
        "property_type": property_type,
        "location": location,
        "bedrooms": int(beds),
        "bathrooms": int(bathrooms),
        "area": float(area) if area is not None else None,
        "area_unit": area_unit,
        "amenities": "[]",
        "highlights": highlights,
        "is_approved": 0,  # SQLite / libSQL boolean integer
        "is_demo": 0,
        "source": "uae_dataset",
        "created_at": now_iso,
        "updated_at": now_iso,
    }


class TursoClient:
    """Lightweight native client for Turso HTTP Pipeline v2 API.
    Zero C-extensions or Rust toolchains required; runs everywhere via httpx.
    """

    def __init__(self, database_url: str, auth_token: str):
        self.raw_url = database_url
        self.auth_token = auth_token.strip()

        # Extract host: libsql://<host> or https://<host> or sqlite+libsql://<host>
        clean = database_url.split("?")[0]
        for prefix in ("sqlite+libsql://", "sqlite+aiolibsql://", "libsql://", "https://", "http://"):
            if clean.startswith(prefix):
                clean = clean[len(prefix):]
                break
        clean = clean.rstrip("/")
        self.pipeline_url = f"https://{clean}/v2/pipeline"
        self.headers = {
            "Authorization": f"Bearer {self.auth_token}",
            "Content-Type": "application/json",
        }

    def execute_raw(self, requests: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Execute one pipeline batch request."""
        payload = {"requests": requests}
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(self.pipeline_url, headers=self.headers, json=payload)
            if resp.status_code != 200:
                raise RuntimeError(
                    f"Turso HTTP pipeline error (status {resp.status_code}): {resp.text}"
                )
            data = resp.json()
            # Check results for errors
            for item in data.get("results", []):
                if item.get("type") == "error":
                    raise RuntimeError(f"Turso statement error: {item.get('error')}")
            return data

    def close(self) -> None:
        """No-op for stateless HTTP pipeline client."""
        pass

    def ensure_table(self) -> None:
        """Create properties table and indexes if not existing."""
        ddl = """
        CREATE TABLE IF NOT EXISTS properties (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            external_ref VARCHAR UNIQUE,
            title VARCHAR NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            purpose VARCHAR NOT NULL,
            availability VARCHAR NOT NULL DEFAULT 'available',
            price FLOAT NOT NULL,
            currency VARCHAR NOT NULL DEFAULT 'AED',
            property_type VARCHAR NOT NULL,
            location VARCHAR NOT NULL,
            bedrooms INTEGER NOT NULL DEFAULT 0,
            bathrooms INTEGER NOT NULL DEFAULT 1,
            area FLOAT,
            area_unit VARCHAR NOT NULL DEFAULT 'sqft',
            amenities TEXT NOT NULL DEFAULT '[]',
            highlights TEXT,
            is_approved BOOLEAN NOT NULL DEFAULT 0,
            is_demo BOOLEAN NOT NULL DEFAULT 0,
            source VARCHAR NOT NULL DEFAULT 'manual',
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
        self.execute_raw([
            {"type": "execute", "stmt": {"sql": ddl.strip()}},
            {"type": "execute", "stmt": {"sql": "CREATE INDEX IF NOT EXISTS ix_properties_ext_ref ON properties (external_ref);"}},
            {"type": "execute", "stmt": {"sql": "CREATE INDEX IF NOT EXISTS ix_properties_source ON properties (source);"}},
            {"type": "execute", "stmt": {"sql": "CREATE INDEX IF NOT EXISTS ix_properties_location ON properties (location);"}},
            {"type": "execute", "stmt": {"sql": "CREATE INDEX IF NOT EXISTS ix_properties_price ON properties (price);"}},
        ])

    def fetch_existing_refs(self) -> Set[str]:
        """Fetch all external_refs starting with UAE- to avoid duplicate inserts."""
        sql = "SELECT external_ref FROM properties WHERE external_ref LIKE 'UAE-%'"
        data = self.execute_raw([{"type": "execute", "stmt": {"sql": sql}}])
        existing = set()
        try:
            results = data.get("results", [])
            if results:
                rows = results[0].get("response", {}).get("result", {}).get("rows", [])
                for r in rows:
                    if r and len(r) > 0:
                        val = r[0].get("value")
                        if val:
                            existing.add(str(val))
        except Exception as e:
            logger.warning("Could not fetch existing refs: %s", e)
        return existing

    def count_total(self) -> int:
        """Count total properties in table."""
        sql = "SELECT count(*) FROM properties"
        data = self.execute_raw([{"type": "execute", "stmt": {"sql": sql}}])
        try:
            rows = data["results"][0]["response"]["result"]["rows"]
            return int(rows[0][0]["value"])
        except Exception:
            return 0

    def insert_batch(self, batch: List[Dict[str, Any]]) -> int:
        """Insert batch within a pipeline transaction."""
        if not batch:
            return 0
        requests = [{"type": "execute", "stmt": {"sql": "BEGIN TRANSACTION"}}]
        insert_sql = """
        INSERT OR IGNORE INTO properties (
            external_ref, title, description, purpose, availability, price,
            currency, property_type, location, bedrooms, bathrooms, area,
            area_unit, amenities, highlights, is_approved, is_demo, source,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        for item in batch:
            args = [
                {"type": "text", "value": item["external_ref"]},
                {"type": "text", "value": item["title"]},
                {"type": "text", "value": item["description"]},
                {"type": "text", "value": item["purpose"]},
                {"type": "text", "value": item["availability"]},
                {"type": "float", "value": item["price"]},
                {"type": "text", "value": item["currency"]},
                {"type": "text", "value": item["property_type"]},
                {"type": "text", "value": item["location"]},
                {"type": "integer", "value": str(int(item["bedrooms"]))},
                {"type": "integer", "value": str(int(item["bathrooms"]))},
                {"type": "float", "value": item["area"]} if item["area"] is not None else {"type": "null"},
                {"type": "text", "value": item["area_unit"]},
                {"type": "text", "value": item["amenities"]},
                {"type": "text", "value": item["highlights"]},
                {"type": "integer", "value": str(int(item["is_approved"]))},
                {"type": "integer", "value": str(int(item["is_demo"]))},
                {"type": "text", "value": item["source"]},
                {"type": "text", "value": item["created_at"]},
                {"type": "text", "value": item["updated_at"]},
            ]
            requests.append({"type": "execute", "stmt": {"sql": insert_sql.strip(), "args": args}})
        requests.append({"type": "execute", "stmt": {"sql": "COMMIT"}})

        res = self.execute_raw(requests)
        inserted = 0
        for item in res.get("results", []):
            if item.get("type") == "ok":
                affected = item.get("response", {}).get("result", {}).get("affected_row_count", 0)
                if affected:
                    inserted += affected
        return inserted


class SQLiteClient:
    """Local SQLite backend for local testing and dev databases."""

    def __init__(self, db_path: str):
        import sqlite3
        clean_path = db_path.replace("sqlite:///", "")
        self.db_path = clean_path
        self.conn = sqlite3.connect(clean_path)
        self.conn.row_factory = sqlite3.Row

    def ensure_table(self) -> None:
        cur = self.conn.cursor()
        cur.executescript("""
        CREATE TABLE IF NOT EXISTS properties (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            external_ref VARCHAR UNIQUE,
            title VARCHAR NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            purpose VARCHAR NOT NULL,
            availability VARCHAR NOT NULL DEFAULT 'available',
            price FLOAT NOT NULL,
            currency VARCHAR NOT NULL DEFAULT 'AED',
            property_type VARCHAR NOT NULL,
            location VARCHAR NOT NULL,
            bedrooms INTEGER NOT NULL DEFAULT 0,
            bathrooms INTEGER NOT NULL DEFAULT 1,
            area FLOAT,
            area_unit VARCHAR NOT NULL DEFAULT 'sqft',
            amenities TEXT NOT NULL DEFAULT '[]',
            highlights TEXT,
            is_approved BOOLEAN NOT NULL DEFAULT 0,
            is_demo BOOLEAN NOT NULL DEFAULT 0,
            source VARCHAR NOT NULL DEFAULT 'manual',
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS ix_properties_ext_ref ON properties (external_ref);
        CREATE INDEX IF NOT EXISTS ix_properties_source ON properties (source);
        CREATE INDEX IF NOT EXISTS ix_properties_location ON properties (location);
        CREATE INDEX IF NOT EXISTS ix_properties_price ON properties (price);
        """)
        self.conn.commit()

    def fetch_existing_refs(self) -> Set[str]:
        cur = self.conn.cursor()
        cur.execute("SELECT external_ref FROM properties WHERE external_ref LIKE 'UAE-%'")
        return {row[0] for row in cur.fetchall() if row[0]}

    def count_total(self) -> int:
        cur = self.conn.cursor()
        cur.execute("SELECT count(*) FROM properties")
        row = cur.fetchone()
        return row[0] if row else 0

    def insert_batch(self, batch: List[Dict[str, Any]]) -> int:
        if not batch:
            return 0
        insert_sql = """
        INSERT OR IGNORE INTO properties (
            external_ref, title, description, purpose, availability, price,
            currency, property_type, location, bedrooms, bathrooms, area,
            area_unit, amenities, highlights, is_approved, is_demo, source,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        rows = [
            (
                b["external_ref"], b["title"], b["description"], b["purpose"],
                b["availability"], b["price"], b["currency"], b["property_type"],
                b["location"], b["bedrooms"], b["bathrooms"], b["area"],
                b["area_unit"], b["amenities"], b["highlights"], b["is_approved"],
                b["is_demo"], b["source"], b["created_at"], b["updated_at"],
            )
            for b in batch
        ]
        cur = self.conn.cursor()
        cur.executemany(insert_sql, rows)
        self.conn.commit()
        return cur.rowcount

    def close(self):
        self.conn.close()


def run_import(
    database_url: Optional[str] = None,
    auth_token: Optional[str] = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    limit: Optional[int] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Execute repeatable, idempotent import."""
    file_path = find_dataset_file()
    logger.info("Reading dataset from: %s", file_path)

    with open(file_path, "r", encoding="utf-8") as f:
        content = json.load(f)

    raw_items = content.get("properties", [])
    total_in_file = len(raw_items)
    logger.info("Found %d total property records in dataset file.", total_in_file)

    if limit is not None and limit > 0:
        raw_items = raw_items[:limit]
        logger.info("Limiting import to first %d records as requested.", limit)

    # Clean & validate
    valid_records: List[Dict[str, Any]] = []
    rejected_count = 0
    rejected_samples: List[Tuple[Any, str]] = []

    for item in raw_items:
        cleaned = clean_row(item)
        if cleaned is not None:
            valid_records.append(cleaned)
        else:
            rejected_count += 1
            if len(rejected_samples) < 5:
                rejected_samples.append((item.get("property_id"), "unparseable/missing required field"))

    logger.info("Validated %d records (%d rejected).", len(valid_records), rejected_count)

    # Check Turso storage limits
    estimated_dataset_size_mb = (len(valid_records) * ESTIMATED_BYTES_PER_ROW) / (1024 * 1024)
    logger.info("Estimated database storage footprint: ~%.2f MB (Turso limit: 9,000 MB).", estimated_dataset_size_mb)

    # Resolve database target
    target_url = (database_url or os.getenv("DATABASE_URL") or "sqlite:///real_estate.db").strip()
    token = (auth_token or os.getenv("TURSO_AUTH_TOKEN") or "").strip()

    is_turso = target_url.startswith(("libsql://", "https://", "http://", "sqlite+libsql", "sqlite+aiolibsql"))

    if is_turso:
        logger.info("Target: Hosted Turso (libSQL) database via native HTTP pipeline.")
        if not token:
            logger.warning("TURSO_AUTH_TOKEN is empty. Requests may fail authentication if required by Turso.")
        client = TursoClient(target_url, token)
    else:
        logger.info("Target: Local SQLite database.")
        client = SQLiteClient(target_url)

    if not dry_run:
        client.ensure_table()

    # Idempotent deduplication check
    existing_refs: Set[str] = set()
    if not dry_run:
        existing_refs = client.fetch_existing_refs()
        logger.info("Found %d existing dataset records already present in target database.", len(existing_refs))
    else:
        logger.info("[DRY-RUN] Skipping database existing-reference fetch.")

    to_insert: List[Dict[str, Any]] = []
    skipped_count = 0

    for rec in valid_records:
        if rec["external_ref"] in existing_refs:
            skipped_count += 1
        else:
            to_insert.append(rec)

    logger.info("Records to insert: %d, Records to skip (already imported): %d", len(to_insert), skipped_count)

    inserted_count = 0
    if dry_run:
        logger.info("[DRY-RUN] Simulating batch import of %d records in batches of %d.", len(to_insert), batch_size)
        inserted_count = len(to_insert)
    else:
        # Batch insert
        total_batches = (len(to_insert) + batch_size - 1) // batch_size
        for b_idx in range(0, len(to_insert), batch_size):
            batch = to_insert[b_idx : b_idx + batch_size]
            current_batch_num = (b_idx // batch_size) + 1
            batch_inserted = client.insert_batch(batch)
            inserted_count += batch_inserted if batch_inserted > 0 else len(batch)
            logger.info("Batch %d/%d completed (%d records in batch).", current_batch_num, total_batches, len(batch))

    final_total = 0
    if not dry_run:
        final_total = client.count_total()
        if hasattr(client, "close"):
            client.close()
    else:
        final_total = skipped_count + inserted_count

    summary = {
        "dataset_total_file": total_in_file,
        "processed": len(raw_items),
        "inserted": inserted_count,
        "skipped": skipped_count,
        "rejected": rejected_count,
        "rejected_samples": rejected_samples,
        "database_total_listings": final_total,
        "estimated_size_mb": round(estimated_dataset_size_mb, 2),
        "target": "Turso (libSQL)" if is_turso else "SQLite",
        "dry_run": dry_run,
    }
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Repeatable, idempotent import of UAErealestate.json into Turso or SQLite."
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help="Target database URL (default: DATABASE_URL env or settings.DATABASE_URL).",
    )
    parser.add_argument(
        "--auth-token",
        default=None,
        help="Turso auth token (default: TURSO_AUTH_TOKEN env or settings.TURSO_AUTH_TOKEN).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Batch size per transaction (default: {DEFAULT_BATCH_SIZE}).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional limit on number of records to process for quick testing.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate records and simulate import without making any database writes.",
    )

    args = parser.parse_args(argv)

    summary = run_import(
        database_url=args.database_url,
        auth_token=args.auth_token,
        batch_size=args.batch_size,
        limit=args.limit,
        dry_run=args.dry_run,
    )

    verb = "would be inserted" if summary["dry_run"] else "inserted"
    print("\n" + "=" * 50)
    print("IMPORT SUMMARY:")
    print(f"Target:                {summary['target']}")
    print(f"Dry Run:               {summary['dry_run']}")
    print(f"Total Records in File: {summary['dataset_total_file']}")
    print(f"Records Processed:     {summary['processed']}")
    print(f"Records {verb}:   {summary['inserted']}")
    print(f"Records Skipped:       {summary['skipped']} (already present / deduplicated)")
    print(f"Records Rejected:      {summary['rejected']} (invalid fields)")
    print(f"Total Listings in DB:  {summary['database_total_listings']}")
    print(f"Estimated Footprint:   ~{summary['estimated_size_mb']} MB")
    print("=" * 50 + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
