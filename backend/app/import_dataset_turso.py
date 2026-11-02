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
    if price_str is None or price_str == "" or isinstance(price_str, bool):
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
    if not area_str or isinstance(area_str, bool):
        return None
    try:
        m = re.match(r"^\s*([+-]?[\d,]+(?:\.\d+)?)", str(area_str))
        if m:
            val = float(m.group(1).replace(",", ""))
            return val if val > 0 else None
    except (ValueError, TypeError):
        return None
    return None


def parse_beds(beds_str: Any) -> Optional[int]:
    """Parse beds: Studio -> 0, '3' -> 3."""
    if isinstance(beds_str, bool):
        return None
    text = str(beds_str if beds_str is not None else "").strip()
    if not text:
        return None
    if text.lower() == "studio":
        return 0
    try:
        val = int(float(text))
        return val if val >= 0 else None
    except (ValueError, TypeError):
        return None


def parse_baths(baths_str: Any) -> Optional[float]:
    """Parse baths to float."""
    if baths_str in (None, "") or isinstance(baths_str, bool):
        return None
    try:
        val = float(baths_str)
        return val if val >= 1.0 else None
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
    if not isinstance(raw, dict):
        return None

    pid = raw.get("property_id")
    if pid is None or isinstance(pid, bool):
        return None

    try:
        pid_int = int(pid)
        if str(pid).strip() != str(pid_int) and float(pid) != pid_int:
            return None
    except (ValueError, TypeError):
        return None
    if pid_int <= 0:
        return None

    raw_price = raw.get("price")
    price = parse_price(raw_price)
    if price is None or price <= 0:
        return None

    raw_beds = raw.get("no__of__beds")
    if raw_beds in (None, ""):
        beds = 0
    else:
        beds = parse_beds(raw_beds)
        if beds is None or beds < 0:
            return None

    raw_baths = raw.get("no_of_baths")
    if raw_baths in (None, ""):
        bathrooms = 1
    else:
        baths_float = parse_baths(raw_baths)
        if baths_float is None or baths_float < 1:
            return None
        bathrooms = int(round(baths_float))

    raw_area = str(raw.get("area") or "").strip()
    if raw_area:
        area = parse_area(raw_area)
        if area is None or area <= 0:
            return None
        unit_match = re.match(r"^[0-9.,]+\s*(.*)$", raw_area)
        area_unit = (unit_match.group(1).strip() if unit_match else "") or "sqft"
    else:
        area = None
        area_unit = "sqft"

    location = str(raw.get("location") or "").strip()
    if not location:
        return None

    if "property_type" in raw and raw.get("property_type") is not None:
        property_type = str(raw.get("property_type")).strip()
        if not property_type:
            return None
    else:
        property_type = "Apartment"

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
        "is_published": 0,
        "verification_status": "unverified",
        "images": "[]",
        "primary_image": None,
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
            is_published BOOLEAN NOT NULL DEFAULT 0,
            verification_status VARCHAR NOT NULL DEFAULT 'unverified',
            images TEXT NOT NULL DEFAULT '[]',
            primary_image VARCHAR,
            source_id VARCHAR,
            import_batch_id VARCHAR,
            archived_at DATETIME,
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
            is_published, verification_status, images,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            is_published BOOLEAN NOT NULL DEFAULT 0,
            verification_status VARCHAR NOT NULL DEFAULT 'unverified',
            images TEXT NOT NULL DEFAULT '[]',
            primary_image VARCHAR,
            source_id VARCHAR,
            import_batch_id VARCHAR,
            archived_at DATETIME,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS ix_properties_ext_ref ON properties (external_ref);
        CREATE INDEX IF NOT EXISTS ix_properties_source ON properties (source);
        CREATE INDEX IF NOT EXISTS ix_properties_location ON properties (location);
        CREATE INDEX IF NOT EXISTS ix_properties_price ON properties (price);
        """)
        self.conn.commit()

    def has_properties_table(self) -> bool:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='properties'"
        )
        return cur.fetchone() is not None

    def fetch_existing_refs(self) -> Set[str]:
        if not self.has_properties_table():
            return set()
        cur = self.conn.cursor()
        cur.execute("SELECT external_ref FROM properties WHERE external_ref IS NOT NULL")
        return {row[0] for row in cur.fetchall() if row[0]}

    def count_total(self) -> int:
        if not self.has_properties_table():
            return 0
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
            is_published, verification_status, images,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        rows = [
            (
                b["external_ref"], b["title"], b["description"], b["purpose"],
                b["availability"], b["price"], b["currency"], b["property_type"],
                b["location"], b["bedrooms"], b["bathrooms"], b["area"],
                b["area_unit"], b["amenities"], b["highlights"], b["is_approved"],
                b["is_demo"], b["source"],
                b.get("is_published", 0), b.get("verification_status", "unverified"), b.get("images", "[]"),
                b["created_at"], b["updated_at"],
            )
            for b in batch
        ]
        cur = self.conn.cursor()
        try:
            cur.executemany(insert_sql, rows)
            self.conn.commit()
            return cur.rowcount
        except Exception:
            self.conn.rollback()
            raise

    def rollback_inserted_refs(self, refs: List[str]) -> None:
        if not refs or not self.has_properties_table():
            return
        cur = self.conn.cursor()
        try:
            placeholders = ",".join("?" for _ in refs)
            cur.execute(
                f"DELETE FROM properties WHERE source = 'uae_dataset' AND external_ref IN ({placeholders})",
                list(refs),
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()

    def close(self):
        self.conn.close()


class SQLAlchemyClient:
    """SQLAlchemy-backed client for PostgreSQL (and general SQLAlchemy URLs).

    Preserves existing records (never overwrites manually modified CRM rows)
    and converts SQLite integer boolean flags (0/1) to Python booleans for
    strict PostgreSQL BOOLEAN compatibility.
    """

    def __init__(self, database_url: str):
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker

        norm_url = str(database_url or "").strip()
        if norm_url.startswith("postgres://"):
            norm_url = "postgresql+psycopg://" + norm_url[len("postgres://"):]
        elif norm_url.startswith("postgresql://"):
            norm_url = "postgresql+psycopg://" + norm_url[len("postgresql://"):]
        self.engine = create_engine(norm_url, pool_pre_ping=True)
        self._Session = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)

    def has_properties_table(self) -> bool:
        from sqlalchemy import inspect as sa_inspect

        try:
            return bool(sa_inspect(self.engine).has_table("properties"))
        except Exception:
            return False

    def ensure_table(self) -> None:
        from app.database import Base, Property

        Base.metadata.create_all(bind=self.engine, tables=[Property.__table__])

    def fetch_existing_refs(self) -> Set[str]:
        if not self.has_properties_table():
            return set()
        from app.database import Property

        with self._Session() as session:
            rows = (
                session.query(Property.external_ref)
                .filter(Property.external_ref.isnot(None))
                .all()
            )
            return {r[0] for r in rows if r and r[0]}

    def count_total(self) -> int:
        if not self.has_properties_table():
            return 0
        from sqlalchemy import func
        from app.database import Property

        with self._Session() as session:
            return int(session.query(func.count(Property.id)).scalar() or 0)

    def insert_batch(self, batch: List[Dict[str, Any]]) -> int:
        if not batch:
            return 0
        from app.database import Property

        refs = [b["external_ref"] for b in batch if b.get("external_ref")]
        with self._Session() as session:
            try:
                existing = {
                    r[0]
                    for r in session.query(Property.external_ref)
                    .filter(Property.external_ref.in_(refs))
                    .all()
                    if r and r[0]
                }
                seen_batch: Set[str] = set()
                to_add: List[Property] = []
                for b in batch:
                    ref = b["external_ref"]
                    if ref in existing or ref in seen_batch:
                        continue
                    seen_batch.add(ref)
                    to_add.append(
                        Property(
                            external_ref=ref,
                            title=b["title"],
                            description=b["description"],
                            purpose=b["purpose"],
                            availability=b["availability"],
                            price=float(b["price"]),
                            currency=b["currency"],
                            property_type=b["property_type"],
                            location=b["location"],
                            bedrooms=int(b["bedrooms"]),
                            bathrooms=int(b["bathrooms"]),
                            area=b["area"],
                            area_unit=b["area_unit"],
                            amenities=b["amenities"],
                            highlights=b["highlights"],
                            is_approved=bool(b["is_approved"]),
                            is_demo=bool(b["is_demo"]),
                            source=b["source"],
                            is_published=bool(b.get("is_published", False)),
                            verification_status=str(b.get("verification_status", "unverified")),
                            images=str(b.get("images", "[]")),
                        )
                    )
                if to_add:
                    session.add_all(to_add)
                    session.commit()
                return len(to_add)
            except Exception:
                session.rollback()
                raise

    def rollback_inserted_refs(self, refs: List[str]) -> None:
        if not refs or not self.has_properties_table():
            return
        from app.database import Property

        with self._Session() as session:
            try:
                session.query(Property).filter(
                    Property.source == "uae_dataset",
                    Property.external_ref.in_(refs),
                ).delete(synchronize_session=False)
                session.commit()
            except Exception:
                session.rollback()

    def close(self) -> None:
        self.engine.dispose()


def run_import(
    database_url: Optional[str] = None,
    auth_token: Optional[str] = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    limit: Optional[int] = None,
    dry_run: bool = False,
    records: Optional[List[Dict[str, Any]]] = None,
    atomic: bool = True,
    raise_on_error: bool = False,
) -> Dict[str, Any]:
    """Execute repeatable, idempotent import with transaction-safe batches."""
    if records is not None:
        raw_items = list(records)
        total_in_file = len(raw_items)
        logger.info("Using %d in-memory property records provided to run_import.", total_in_file)
    else:
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

    # Clean, validate & deduplicate intra-dataset duplicates
    valid_records: List[Dict[str, Any]] = []
    rejected_count = 0
    duplicate_in_file_count = 0
    seen_in_file: Set[str] = set()
    rejected_samples: List[Tuple[Any, str]] = []

    for item in raw_items:
        cleaned = clean_row(item)
        if cleaned is not None:
            ext_ref = cleaned["external_ref"]
            if ext_ref in seen_in_file:
                duplicate_in_file_count += 1
                continue
            seen_in_file.add(ext_ref)
            valid_records.append(cleaned)
        else:
            rejected_count += 1
            if len(rejected_samples) < 5:
                pid_hint = item.get("property_id") if isinstance(item, dict) else None
                rejected_samples.append((pid_hint, "unparseable/missing required field"))

    logger.info(
        "Validated %d unique records (%d rejected, %d duplicate in input).",
        len(valid_records),
        rejected_count,
        duplicate_in_file_count,
    )

    # Check Turso storage limits
    estimated_dataset_size_mb = (len(valid_records) * ESTIMATED_BYTES_PER_ROW) / (1024 * 1024)
    logger.info("Estimated database storage footprint: ~%.2f MB (Turso limit: 9,000 MB).", estimated_dataset_size_mb)

    # Resolve database target
    target_url = (database_url or os.getenv("DATABASE_URL") or "sqlite:///real_estate.db").strip()
    token = (auth_token or os.getenv("TURSO_AUTH_TOKEN") or "").strip()

    is_turso = target_url.startswith(("libsql://", "https://", "http://", "sqlite+libsql", "sqlite+aiolibsql"))
    is_postgres = target_url.startswith(("postgresql://", "postgresql+", "postgres://"))

    client = None
    existing_refs: Set[str] = set()
    current_db_total = 0

    if is_turso:
        target_label = "Turso (libSQL)"
        if not dry_run:
            logger.info("Target: Hosted Turso (libSQL) database via native HTTP pipeline.")
            if not token:
                logger.warning("TURSO_AUTH_TOKEN is empty. Requests may fail authentication if required by Turso.")
            client = TursoClient(target_url, token)
    elif is_postgres:
        target_label = "PostgreSQL"
        logger.info("Target: PostgreSQL database via SQLAlchemy.")
        client = SQLAlchemyClient(target_url)
    else:
        target_label = "SQLite"
        logger.info("Target: Local SQLite database.")
        clean_sqlite_path = target_url.replace("sqlite:///", "")
        if not dry_run or Path(clean_sqlite_path).is_file():
            client = SQLiteClient(target_url)

    if client is not None:
        if not dry_run:
            client.ensure_table()
        try:
            existing_refs = client.fetch_existing_refs()
            current_db_total = client.count_total()
            logger.info(
                "Found %d existing reference(s) and %d total row(s) in target database.",
                len(existing_refs),
                current_db_total,
            )
        except Exception as exc:
            logger.warning("Could not inspect existing refs in database: %s", exc)

    to_insert: List[Dict[str, Any]] = []
    skipped_existing_count = 0

    for rec in valid_records:
        if rec["external_ref"] in existing_refs:
            skipped_existing_count += 1
        else:
            to_insert.append(rec)

    skipped_count = skipped_existing_count + duplicate_in_file_count
    logger.info(
        "Records to insert: %d, Records to skip: %d (%d existing in DB, %d duplicate in input)",
        len(to_insert),
        skipped_count,
        skipped_existing_count,
        duplicate_in_file_count,
    )

    inserted_count = 0
    errors: List[str] = []
    inserted_refs_this_run: List[str] = []

    if dry_run:
        logger.info("[DRY-RUN] Simulating batch import of %d records in batches of %d.", len(to_insert), batch_size)
        inserted_count = len(to_insert)
        if client is not None and hasattr(client, "close"):
            client.close()
    else:
        total_batches = (len(to_insert) + batch_size - 1) // batch_size
        for b_idx in range(0, len(to_insert), batch_size):
            batch = to_insert[b_idx : b_idx + batch_size]
            current_batch_num = (b_idx // batch_size) + 1
            try:
                batch_inserted = client.insert_batch(batch)
                actual_added = batch_inserted if batch_inserted >= 0 else len(batch)
                inserted_count += actual_added
                inserted_refs_this_run.extend(b["external_ref"] for b in batch)
                logger.info(
                    "Batch %d/%d completed (%d records in batch).",
                    current_batch_num,
                    total_batches,
                    len(batch),
                )
            except Exception as exc:
                err_msg = f"Batch {current_batch_num}/{total_batches} failed: {type(exc).__name__}: {exc}"
                logger.error(err_msg)
                errors.append(err_msg)
                if atomic and inserted_refs_this_run and hasattr(client, "rollback_inserted_refs"):
                    logger.info(
                        "Rolling back %d previously inserted record(s) from failed import run.",
                        len(inserted_refs_this_run),
                    )
                    client.rollback_inserted_refs(inserted_refs_this_run)
                    inserted_count = 0
                    inserted_refs_this_run.clear()
                if raise_on_error:
                    if hasattr(client, "close"):
                        client.close()
                    raise
                break

    final_total = 0
    if not dry_run and client is not None:
        try:
            final_total = client.count_total()
        finally:
            if hasattr(client, "close"):
                client.close()
    else:
        final_total = current_db_total + inserted_count

    summary = {
        "dataset_total_file": total_in_file,
        "total_records": len(raw_items),
        "processed": len(raw_items),
        "valid_records": len(valid_records),
        "accepted_valid": len(valid_records),
        "imported": inserted_count,
        "inserted": inserted_count,
        "updated": 0,
        "skipped": skipped_count,
        "skipped_existing": skipped_existing_count,
        "duplicate_source_records": duplicate_in_file_count,
        "duplicates_in_file": duplicate_in_file_count,
        "invalid_records": rejected_count,
        "rejected": rejected_count,
        "rejected_samples": rejected_samples,
        "errors": errors,
        "error_count": len(errors),
        "database_current_listings": current_db_total,
        "database_total_listings": final_total,
        "estimated_size_mb": round(estimated_dataset_size_mb, 2),
        "target": target_label,
        "dry_run": dry_run,
    }
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Repeatable, idempotent import of UAErealestate.json into Turso, PostgreSQL, or SQLite."
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
    print(f"Valid Unique Records:  {summary['valid_records']}")
    print(f"Records {verb}:   {summary['inserted']}")
    print(f"Records Updated:       {summary['updated']} (existing records preserved)")
    print(f"Skipped (Existing DB): {summary['skipped_existing']}")
    print(f"Duplicate in Source:   {summary['duplicate_source_records']}")
    print(f"Records Invalid:       {summary['invalid_records']}")
    print(f"Errors:                {summary['error_count']}")
    print(f"Current DB Listings:   {summary['database_current_listings']}")
    print(f"Projected/Final DB:    {summary['database_total_listings']}")
    print(f"Estimated Footprint:   ~{summary['estimated_size_mb']} MB")
    print("=" * 50 + "\n")
    return 0 if summary["error_count"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
