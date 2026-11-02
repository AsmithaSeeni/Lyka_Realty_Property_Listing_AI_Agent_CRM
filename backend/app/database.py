from sqlalchemy import (
    create_engine, Column, Integer, String, Float, DateTime, Date, Text,
    Boolean, ForeignKey, UniqueConstraint, Index, CheckConstraint, text,
    LargeBinary,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from datetime import datetime
import hashlib
import secrets

from app.config import ACTIVE_DB_FILE, settings

# Phase 1: the database URL is explicit and CWD-independent.
# - Default (DATABASE_URL unset/empty): the ACTIVE database resolved to an
#   absolute path (backend/real_estate.db) — identical file to the historical
#   `sqlite:///./real_estate.db` when run from backend/, but running the
#   server from any other directory can no longer silently open the stale
#   repo-root real_estate.db.
# - A different database requires an EXPLICIT `DATABASE_URL` value.
# No schema/engine migration happens here.
SQLALCHEMY_DATABASE_URL = settings.DATABASE_URL

# Production must be told WHERE to persist. On serverless hosts the local
# filesystem is read-only and ephemeral, so silently defaulting to a SQLite
# file turns into an opaque "attempt to write a readonly database" failure
# at the first query. Fail fast, at import time, naming the missing
# configuration instead (dev/test are unaffected: they run APP_ENV
# development/test and keep the SQLite default).
if (
    settings.APP_ENV.strip().lower() == "production"
    and not str(SQLALCHEMY_DATABASE_URL or "").strip()
):
    raise RuntimeError(
        "APP_ENV=production but DATABASE_URL is empty. Production needs an "
        "explicit persistent database (e.g. libsql://<db-name>.turso.io with "
        "TURSO_AUTH_TOKEN); configure both in the deployment environment."
    )

# ---------------- Serverless / Turso (libSQL) support ----------------
# Vercel Functions have a READ-ONLY, ephemeral filesystem: a local SQLite file
# cannot persist there (every cold start would start empty and each concurrent
# instance would hold its own private copy). Setting DATABASE_URL to a
# libSQL URL (e.g. `libsql://<db>.turso.io`) routes the same SQLAlchemy models
# to a hosted Turso database instead — no code changes in the ORM layer.
#
# The auth token is read from the environment (TURSO_AUTH_TOKEN) and passed via
# connect_args rather than embedded in the URL, so it can never leak into logs,
# error messages or repr(engine).
#
# sqlalchemy-libsql==0.2.0 registers ONLY the `sqlite+libsql` and
# `sqlite+aiolibsql` dialects (verified from the wheel's entry_points.txt);
# a bare `libsql://` / `https://` / `http://` scheme has NO registered
# dialect and would crash create_engine() at import. app.config keeps those
# operator-facing forms working by normalising them to `sqlite+libsql://...`
# — every prefix that must take the libSQL path (raw or normalised) is
# listed here.
_LIBSQL_URL_PREFIXES = ("libsql://", "https://", "http://", "sqlite+libsql", "sqlite+aiolibsql")
_IS_LIBSQL = SQLALCHEMY_DATABASE_URL.startswith(_LIBSQL_URL_PREFIXES)


def _is_local_sqlite(url: str) -> bool:
    """True only for the LOCAL SQLite dialect.

    The Phase 9 PRAGMA contract (foreign_keys / busy_timeout / journal_mode)
    and the SQLite-only connect args apply to local files — never to libSQL
    remotes, whose URL also begins with ``sqlite+libsql://`` after the
    config-layer normalisation above.
    """
    return url.startswith("sqlite") and not url.startswith(
        ("sqlite+libsql", "sqlite+aiolibsql")
    )


def _engine_connect_args() -> dict:
    """Per-scheme connect args. SQLite keeps its Phase 1/9 contract; libSQL
    receives its auth token. Every other dialect gets no extra args."""
    if SQLALCHEMY_DATABASE_URL.startswith(_LIBSQL_URL_PREFIXES):
        # libSQL FIRST: the normalised `sqlite+libsql://...` form ALSO starts
        # with "sqlite" — falling into the SQLite-only branch would silently
        # drop the auth token remote Turso requires.
        args = {}
        if settings.TURSO_AUTH_TOKEN:
            args["auth_token"] = settings.TURSO_AUTH_TOKEN
        return args
    if _is_local_sqlite(SQLALCHEMY_DATABASE_URL):
        return {
            "check_same_thread": False,
            "timeout": settings.SQLITE_BUSY_TIMEOUT_SECONDS,
        }
    return {}


def _engine_kwargs() -> dict:
    kwargs = {
        "echo": False,
        "connect_args": _engine_connect_args(),
    }
    if "postgresql" in SQLALCHEMY_DATABASE_URL:
        kwargs.update({
            "pool_size": 10,
            "max_overflow": 20,
            "pool_timeout": 30,
            "pool_pre_ping": True,
            "pool_recycle": 300,
        })
    return kwargs


try:
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        **_engine_kwargs(),
    )
except Exception as _engine_exc:
    # Fail fast: PostgreSQL is the authoritative database; no silent fallbacks.
    host_info = SQLALCHEMY_DATABASE_URL.split("@")[-1] if "@" in SQLALCHEMY_DATABASE_URL else "target database"
    raise RuntimeError(
        f"FATAL: Failed to initialize authoritative database engine for '{host_info}': {_engine_exc}"
    ) from _engine_exc

# ---------------- Phase 9: per-connection SQLite safety contract ----------------
# SQLite enforces foreign keys OFF by default and SQLAlchemy never turns them
# on, so referential integrity used to live in the service layer alone.
# This hook fires for EVERY new connection this engine opens (application,
# tests, migration helpers) BEFORE any transaction starts — the only moment
# SQLite accepts these PRAGMAs (they are no-ops inside a transaction).
#
# Pre-change audit (Phase 9, read-only, live backend/real_estate.db):
#   foreign_key_check -> 0 violations; per-column orphan scan -> 0 orphans
#   across all 10 FK relationships, so enabling enforcement is safe.
# PostgreSQL connections are structurally untouched (dialect check below).

_SQLITE_JOURNAL_MODES = {"wal", "delete", "truncate", "persist", "memory", "off"}


def apply_sqlite_pragmas(dbapi_connection) -> None:
    """Configure one raw SQLite connection (the Phase 9 connection contract).

    - ``foreign_keys=ON`` — the DATABASE now rejects invalid references
      (e.g. a conversation pointing at a nonexistent customer), not just the
      service layer. Nullable FK columns (``customer_id = NULL`` legacy rows,
      unassigned leads) remain legal.
    - ``busy_timeout`` — explicit wait window (ms) for locked writes, from
      ``settings.SQLITE_BUSY_TIMEOUT_SECONDS``. No blind retries are added
      anywhere: busy handling is exactly this bounded wait.
    - ``journal_mode`` — configurable, default WAL so readers never block the
      single writer. `synchronous` stays FULL (SQLite's durable default), so
      WAL does not weaken durability. Unknown/blank values are ignored and
      SQLite keeps its default rollback-journal mode.

    Exported so tests that build private engines for isolated databases can
    apply the identical contract.
    """
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        busy_ms = max(0, int(settings.SQLITE_BUSY_TIMEOUT_SECONDS * 1000))
        cursor.execute(f"PRAGMA busy_timeout={busy_ms}")
        mode = (settings.SQLITE_JOURNAL_MODE or "").strip().lower()
        if mode in _SQLITE_JOURNAL_MODES:
            cursor.execute(f"PRAGMA journal_mode={mode}")
    finally:
        cursor.close()


if engine.dialect.name == "sqlite" and not str(engine.url).startswith(_LIBSQL_URL_PREFIXES):
    from sqlalchemy import event

    @event.listens_for(engine, "connect")
    def _sqlite_connection_pragmas(dbapi_connection, _connection_record):
        # Registered before init_db() can run, so even the very first
        # connection (create_all/migrations/seeding) gets the contract.
        # Never registered for libSQL remotes or PostgreSQL engines.
        apply_sqlite_pragmas(dbapi_connection)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# Sentinel used when a lead field is genuinely unknown (never invent data).
# Rendered as-is by the agent API and shown verbatim in the CRM UI.
NOT_PROVIDED = "Not provided"


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- Agent side

class Agent(Base):
    """Internal sales agent (CRM user). Passwords are bcrypt hashes only.

    ``role`` is the PRIMARY role (legacy column, kept authoritative on its own
    so every existing query keeps working). Additional roles live in
    ``agent_roles``; together they form the identity's effective role set
    (see services.rbac.effective_roles). ``role`` always stays populated with
    the winning role so old readers see a sensible value.
    """
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, nullable=False, index=True)
    username = Column(String, unique=True, nullable=False, index=True)
    full_name = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)   # bcrypt, never plaintext
    role = Column(String, nullable=False, default="agent")  # primary role key
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    # ---------------- Global-auth additions (additive, nullable) ----------
    # Last successful sign-in (never set for guests). NULL = never logged in
    # through the portal yet, or a pre-migration row.
    last_login_at = Column(DateTime, nullable=True)
    # Consecutive failed sign-ins since the last success. Reset to 0 on a
    # successful login. Purely a counter — no passwords/timestamps of failures.
    failed_login_count = Column(Integer, nullable=False, default=0)
    must_change_password = Column(Boolean, nullable=False, default=False)
    # When set (and in the future) the account is temporarily locked after too
    # many consecutive failures. NULL = not locked.
    locked_until = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    sessions = relationship("AgentSession", backref="agent", cascade="all, delete-orphan")
    assigned_leads = relationship(
        "Lead",
        foreign_keys="[Lead.assigned_agent_id]",
        backref="assigned_agent",
        lazy="selectin",
    )
    created_leads = relationship(
        "Lead",
        foreign_keys="[Lead.creator_agent_id]",
        backref="creator_agent",
        lazy="selectin",
    )
    role_assignments = relationship(
        "AgentRole", backref="agent", cascade="all, delete-orphan", lazy="selectin"
    )


class AgentSession(Base):
    """Server-side session for an authenticated agent.

    The browser only holds a random token in an httpOnly cookie; we store its
    SHA-256 hash here so a database leak cannot be replayed as a live session.
    """
    __tablename__ = "agent_sessions"

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), index=True, nullable=False)
    token_hash = Column(String, unique=True, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)

    @staticmethod
    def hash_token(token: str) -> str:
        return _sha256(token)

    @staticmethod
    def new_token() -> str:
        return secrets.token_urlsafe(32)


class AgentRole(Base):
    """Additional role assignments for a staff identity (Phase 2 — multi-role).

    The PRIMARY role lives in ``agents.role`` and is authoritative on its own.
    This table only ever holds EXTRA roles, so a staff member with a single
    role has zero rows here and behaves exactly as before. The combination is
    de-duplicated and normalised in services.rbac.effective_roles().

    ``role_key`` is validated against the rbac.ROLE_REGISTRY before insert, and
    a UNIQUE constraint is the database-level backstop against duplicates.
    """
    __tablename__ = "agent_roles"

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False, index=True)
    # A registry key, e.g. "sales_manager". Never a permission string.
    role_key = Column(String, nullable=False)
    granted_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        # One row per (agent, role) — re-granting the same role is a no-op.
        UniqueConstraint("agent_id", "role_key", name="uq_agent_roles_agent_role"),
    )


class AuditLog(Base):
    """Append-only security audit trail (Phase 6).

    Written only through services.audit.write_audit(). There is no application
    API to update or delete rows. Sensitive values (passwords, tokens, cookies,
    message bodies) are never stored — see the module docstring in
    services/audit.py for the enforced data-minimisation rules.
    """
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, index=True)
    event = Column(String, nullable=False, index=True)      # e.g. "auth.login.success"
    # "staff" | "customer" | "system" — who performed the action.
    actor_type = Column(String, nullable=False, default="system")
    actor_id = Column(Integer, nullable=True)               # id within actor_type space
    actor_label = Column(String, nullable=True)             # email/username (no secrets)
    subject_type = Column(String, nullable=True)            # what was acted upon
    subject_id = Column(Integer, nullable=True)
    subject_label = Column(String, nullable=True)
    ip = Column(String, nullable=True)
    detail = Column(String, nullable=True)                  # short, non-sensitive note
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index("ix_audit_log_event_created", "event", "created_at"),
        Index("ix_audit_log_actor", "actor_type", "actor_id"),
    )


class Customer(Base):
    """Public visitor, identified by a random cookie token.

    Lets the public chat API scope conversations to a single browser so one
    customer can never list or open another customer's conversations.

    Optional accounts: a customer row with `password_hash` set is a registered
    account (email + bcrypt). Guests have password_hash NULL. Signing in
    re-points the cookie at the account row and the guest's conversations are
    re-assigned, so existing chats survive registration.
    """
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, index=True)
    token_hash = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    email = Column(String, nullable=True)
    password_hash = Column(String, nullable=True)  # bcrypt; NULL = guest
    preferred_locations = Column(Text, nullable=True)
    property_type = Column(String, nullable=True)
    bedrooms_min = Column(Integer, nullable=True)
    bedrooms_max = Column(Integer, nullable=True)
    budget_min = Column(Float, nullable=True)
    budget_max = Column(Float, nullable=True)
    budget_currency = Column(String, nullable=False, default="AED")
    purpose = Column(String, nullable=True)  # buy | rent | investment | self_use
    preferred_contact_method = Column(String, nullable=True)  # email | phone | whatsapp
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    conversations = relationship("Conversation", backref="customer", lazy="selectin")
    saved_properties = relationship("SavedProperty", back_populates="customer", lazy="selectin", cascade="all, delete-orphan")
    appointments = relationship("Appointment", back_populates="customer", lazy="selectin")
    communications = relationship("CustomerCommunication", back_populates="customer", lazy="selectin", cascade="all, delete-orphan")
    notifications = relationship("CustomerNotification", back_populates="customer", lazy="selectin", cascade="all, delete-orphan")

    @property
    def is_account(self) -> bool:
        return self.password_hash is not None

    @staticmethod
    def hash_token(token: str) -> str:
        return _sha256(token)

    @staticmethod
    def new_token() -> str:
        return secrets.token_urlsafe(32)


class SavedProperty(Base):
    """A listing a signed-in customer bookmarked from chat or the details page."""
    __tablename__ = "saved_properties"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False, index=True)
    property_id = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    customer = relationship("Customer", foreign_keys=[customer_id], back_populates="saved_properties", lazy="selectin")


# ---------------------------------------------------------------- CRM entities

class Lead(Base):
    __tablename__ = "leads"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=True)
    phone = Column(String, nullable=True, index=True)
    email = Column(String, nullable=True, index=True)
    buy_rent = Column(String, nullable=True)  # "buy" or "rent"
    location = Column(String, nullable=True)
    budget = Column(String, nullable=True)
    property_type = Column(String, nullable=True)  # "apartment", "villa", "townhouse"
    bedrooms = Column(Integer, nullable=True)
    bathrooms = Column(Integer, nullable=True)
    requirements = Column(Text, nullable=True)
    investment_purpose = Column(String, nullable=True)  # "investment", "self_use", etc.
    timeline = Column(String, nullable=True)  # "immediate", "3-6 months", etc.
    notes = Column(Text, nullable=True)
    status = Column(String, default="new")  # new|contacted|qualified|viewing|negotiation|closed_won|closed_lost
    source = Column(String, default="AI Assistant")  # where the lead came from
    assigned_agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True, index=True)
    creator_agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True, index=True)
    last_interaction_at = Column(DateTime, nullable=True)  # last customer activity
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # ---------------- Phase 2: structured lead qualification (all additive,
    # all NULLABLE — existing rows and current chat-created leads unaffected).
    # Scoring fields are storage ONLY; Phase 4 computes scores in plain Python.
    original_enquiry = Column(Text, nullable=True)      # verbatim customer text
    budget_min = Column(Float, nullable=True)           # normalized numbers
    budget_max = Column(Float, nullable=True)
    budget_currency = Column(String, nullable=True)     # e.g. "AED"
    amenities = Column(Text, nullable=True)             # JSON array of required amenities
    lead_score = Column(Integer, nullable=True)         # NULL = not scored yet (never fabricated)
    priority = Column(String, nullable=True)            # high|medium|low (Phase 4)
    score_breakdown = Column(Text, nullable=True)       # JSON per-criterion points (Phase 4)
    missing_fields = Column(Text, nullable=True)        # JSON array of missing field names
    clarification_questions = Column(Text, nullable=True)  # JSON array of suggested questions
    timeline_days = Column(Integer, nullable=True)      # normalized timeline in days, NULL = unknown
    extraction_source = Column(String, nullable=True)   # provenance: explicit|inferred|mixed|chat_regex

    # ---------------- AI brain upgrade: transparent lead temperature -------
    # temperature: hot|warm|cold (NULL = not yet classified — never fabricated).
    # temperature_rationale: JSON {temperature, rules fired, evidence, at}.
    # temperature_source: auto|manual — a human's manual choice is never
    # silently overwritten by the automatic rules (see lead_temperature.py).
    temperature = Column(String, nullable=True)
    temperature_rationale = Column(Text, nullable=True)
    temperature_source = Column(String, nullable=True)
    temperature_updated_at = Column(DateTime, nullable=True)
    # Chat-derived context for the dashboard (staff notes stay in `notes`).
    summary = Column(Text, nullable=True)               # short conversation summary
    last_customer_message = Column(Text, nullable=True) # most recent customer message
    is_synthetic = Column(Boolean, nullable=False, default=False, index=True)

    conversations = relationship("Conversation", backref="lead", lazy="selectin")
    property_recommendations = relationship(
        "PropertyRecommendation",
        backref="lead",
        lazy="selectin",
        foreign_keys="PropertyRecommendation.lead_id",
    )
    follow_ups = relationship(
        "FollowUp",
        backref="lead",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="FollowUp.due_at",
    )


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    customer_name = Column(String, nullable=True)
    customer_phone = Column(String, nullable=True)
    customer_email = Column(String, nullable=True)
    status = Column(String, default="active")  # "active", "closed", "lost"
    # Ownership: which public visitor this conversation belongs to.
    # NULL = pre-migration/orphan record, visible to agents only.
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    messages = relationship(
        "Message",
        backref="conversation",
        lazy="selectin",
        order_by="Message.id",
        cascade="all, delete-orphan",
    )
    property_recommendations = relationship(
        "PropertyRecommendation",
        backref="conversation",
        lazy="selectin",
        order_by="PropertyRecommendation.id",
        cascade="all, delete-orphan",
        foreign_keys="PropertyRecommendation.conversation_id",
    )
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=True, index=True)
    # Persistent structured conversation memory (JSON): requirements, contact,
    # language pins, stage. Written after every chat turn and restored on a
    # cold start, so preference slots no longer depend on re-running the
    # lossy regex extractor over the transcript.
    memory = Column(Text, nullable=True)


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), index=True)
    role = Column(String)  # "user" or "assistant"
    content = Column(Text)
    detected_language = Column(String, default="en")  # "en", "ta", "ta-Latn", "mixed"
    message_type = Column(String, default="text")  # "text" or "voice"
    property_recommendation_ids = Column(String, nullable=True)  # JSON array of property IDs
    created_at = Column(DateTime, default=datetime.utcnow)


class PropertyRecommendation(Base):
    __tablename__ = "property_recommendations"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), index=True)
    # Also linked to the lead so the CRM can show recommendations per lead
    # (Agent → Lead → Property Recommendations)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=True, index=True)
    property_id = Column(Integer)
    price = Column(String)
    property_type = Column(String)
    location = Column(String)
    bedrooms = Column(Integer)
    bathrooms = Column(Float)
    area = Column(String)
    highlights = Column(Text)
    relevance_score = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)

    # ---------------- Phase 2 (additive, all NULLABLE) ----------------
    # Historical rows keep NULL — we never fabricate scores/reasons for
    # recommendations created before this phase existed.
    match_score = Column(Float, nullable=True)          # Phase 4 match score (0-100)
    match_reasons = Column(Text, nullable=True)         # JSON array of match reasons
    match_mismatches = Column(Text, nullable=True)      # JSON array of unmet preferences
    # Logical reference to properties.id for DB-backed matches.
    # NOTE: SQLite cannot ADD a foreign key via ALTER TABLE, so this is a plain
    # integer column; referential integrity is enforced by the service layer
    # (Phase 4/5). Historical rows keep their dataset IDs in `property_id`.
    property_record_id = Column(Integer, nullable=True, index=True)


class Property(Base):
    """Database-backed property record (Phase 2).

    STRICT BOUNDARY: rows here are explicitly entered/seeded records with a
    declared purpose, availability and approval status. The 25,082-row
    `UAErealestate.json` dataset is NOT imported into this table — dataset
    rows remain unverified reference data served by property_search.py and
    are never assumed to be approved, available, sale/rent-designated Lyka
    Realty listings.
    """
    __tablename__ = "properties"

    id = Column(Integer, primary_key=True, index=True)
    # Stable external identifier (e.g. "DEMO-DM-SALE-001") used for idempotent
    # seeding/deduplication. NULL for manually created records.
    external_ref = Column(String, unique=True, nullable=True, index=True)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False, default="")
    # Listing purpose — a VERIFIED fact for this row (never inferred from price).
    purpose = Column(String, nullable=False)            # sale | rent | lease
    availability = Column(String, nullable=False, default="available")
    price = Column(Float, nullable=False)
    currency = Column(String, nullable=False, default="AED")
    property_type = Column(String, nullable=False)      # apartment | villa | townhouse | studio | ...
    location = Column(String, nullable=False, index=True)  # community, e.g. "Dubai Marina"
    bedrooms = Column(Integer, nullable=False, default=0)
    bathrooms = Column(Integer, nullable=False, default=1)
    area = Column(Float, nullable=True)
    area_unit = Column(String, nullable=False, default="sqft")
    amenities = Column(Text, nullable=False, default="[]")  # JSON array
    highlights = Column(Text, nullable=True)               # free-text marketing notes
    # Approval: FALSE unless explicitly approved. Dataset records are never
    # assumed approved; demo rows are approved ONLY within the fictional set.
    is_approved = Column(Boolean, nullable=False, default=False)
    is_demo = Column(Boolean, nullable=False, default=False)  # fictional demo data?
    source = Column(String, nullable=False, default="manual")  # manual | demo_seed

    # ---------------- Phase I: Lifecycle, Verification & Media ----------------
    is_published = Column(Boolean, nullable=False, default=False, server_default=text("0"), index=True)
    verification_status = Column(String, nullable=False, default="unverified", server_default="unverified", index=True)  # unverified | pending_review | verified | rejected
    rejection_reason = Column(Text, nullable=True)
    published_at = Column(DateTime, nullable=True)
    images = Column(Text, nullable=False, default="[]", server_default="'[]'")  # JSON array of image objects/URLs
    primary_image = Column(String, nullable=True)
    source_id = Column(String, nullable=True, index=True)
    import_batch_id = Column(String, nullable=True, index=True)
    archived_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def __init__(self, **kwargs):
        # Backward compatibility for legacy tests & seeders:
        if kwargs.get("is_approved") and "is_published" not in kwargs:
            kwargs["is_published"] = True
            if "verification_status" not in kwargs:
                kwargs["verification_status"] = "verified"
        super().__init__(**kwargs)

    __table_args__ = (
        CheckConstraint("purpose IN ('sale','rent','lease')",
                        name="ck_properties_purpose"),
        CheckConstraint(
            "availability IN ('available','sold','rented','reserved','off_market')",
            name="ck_properties_availability",
        ),
        CheckConstraint("price >= 0", name="ck_properties_price"),
        CheckConstraint("bedrooms >= 0", name="ck_properties_bedrooms"),
        # Composite indexes for the Phase 4 eligibility filters.
        Index("ix_properties_purpose_availability", "purpose", "availability"),
        Index("ix_properties_approved_availability", "is_approved", "availability"),
        Index("ix_properties_price", "price"),
        Index("ix_properties_property_type", "property_type"),
        Index("ix_properties_location_purpose", "location", "purpose"),
    )

    stored_images = relationship(
        "PropertyImage",
        back_populates="property",
        cascade="all, delete-orphan",
        order_by="PropertyImage.display_order.asc(), PropertyImage.id.asc()",
    )


class PropertyImage(Base):
    """PostgreSQL persistent binary image storage for property listings (Stage 6I).

    Stores actual image byte data (BYTEA in PostgreSQL) uploaded directly from local admin computer.
    Validated by magic byte file signatures (JPEG, PNG, WebP) up to 10MB per file.
    """
    __tablename__ = "property_images"

    id = Column(Integer, primary_key=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id", ondelete="CASCADE"), nullable=False, index=True)
    image_data = Column(LargeBinary, nullable=False)
    mime_type = Column(String(50), nullable=False)  # image/jpeg | image/png | image/webp
    original_filename = Column(String(255), nullable=True)
    file_size = Column(Integer, nullable=False)
    image_hash = Column(String(64), nullable=True, index=True)
    display_order = Column(Integer, nullable=False, default=0)
    is_primary = Column(Boolean, nullable=False, default=False, index=True)
    alt_text = Column(String(255), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    property = relationship("Property", back_populates="stored_images")

    __table_args__ = (
        CheckConstraint(
            "mime_type IN ('image/jpeg', 'image/png', 'image/webp')",
            name="ck_property_images_mime",
        ),
        Index("ix_property_images_prop_primary", "property_id", "is_primary"),
    )


class FollowUp(Base):
    """Follow-up activity for a lead (Phase 5 workflow foundation)."""
    __tablename__ = "follow_ups"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=False, index=True)
    assigned_agent_id = Column(
        Integer, ForeignKey("agents.id"), nullable=True, index=True
    )
    type = Column(String, nullable=False)   # call | email | whatsapp | viewing | general
    notes = Column(Text, nullable=False, default="")
    due_at = Column(DateTime, nullable=False, index=True)
    is_completed = Column(Boolean, nullable=False, default=False)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    assigned_agent = relationship("Agent", lazy="selectin")

    __table_args__ = (
        CheckConstraint(
            "type IN ('call','email','whatsapp','viewing','general')",
            name="ck_followups_type",
        ),
        Index("ix_followups_due_completed", "due_at", "is_completed"),
    )



class Appointment(Base):
    """Appointment & property viewing record (Phase F)."""
    __tablename__ = "appointments"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=False, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id"), nullable=True, index=True)
    additional_property_ids = Column(Text, nullable=False, default="[]")
    assigned_agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False, index=True)
    appointment_type = Column(String, nullable=False, default="viewing")
    start_at = Column(DateTime, nullable=False, index=True)
    end_at = Column(DateTime, nullable=False, index=True)
    timezone = Column(String, nullable=False, default="Asia/Dubai")
    meeting_method = Column(String, nullable=False, default="in_person")
    location_or_link = Column(String, nullable=True)
    status = Column(String, nullable=False, default="scheduled", index=True)
    customer_confirmation_status = Column(String, nullable=False, default="pending")
    notes = Column(Text, nullable=True)
    outcome = Column(Text, nullable=True)
    viewing_outcome = Column(String, nullable=True)
    customer_feedback = Column(Text, nullable=True)
    next_action = Column(Text, nullable=True)
    cancellation_reason = Column(Text, nullable=True)
    reschedule_reason = Column(Text, nullable=True)
    reschedule_history = Column(Text, nullable=False, default="[]")
    conflict_override_reason = Column(Text, nullable=True)
    idempotency_key = Column(String, unique=True, nullable=True, index=True)
    created_by_id = Column(Integer, ForeignKey("agents.id"), nullable=True)
    updated_by_id = Column(Integer, ForeignKey("agents.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    lead = relationship("Lead", foreign_keys=[lead_id], lazy="selectin")
    property_record = relationship("Property", foreign_keys=[property_id], lazy="selectin")
    assigned_agent = relationship("Agent", foreign_keys=[assigned_agent_id], lazy="selectin")
    customer = relationship("Customer", foreign_keys=[customer_id], back_populates="appointments", lazy="selectin")

    __table_args__ = (
        CheckConstraint(
            "appointment_type IN ('viewing','callback','consultation','negotiation_meeting','documentation_meeting')",
            name="ck_appointments_type",
        ),
        CheckConstraint(
            "meeting_method IN ('in_person','phone','video')",
            name="ck_appointments_method",
        ),
        CheckConstraint(
            "status IN ('scheduled','confirmed','completed','cancelled','rescheduled','no_show')",
            name="ck_appointments_status",
        ),
        CheckConstraint(
            "customer_confirmation_status IN ('pending','confirmed','declined','reschedule_requested')",
            name="ck_appointments_cust_conf",
        ),
        Index("ix_appointments_agent_window", "assigned_agent_id", "start_at", "end_at"),
        Index("ix_appointments_lead_status", "lead_id", "status"),
    )


class Offer(Base):
    """Property purchase/rent/lease offer and negotiation trail (Phase F)."""
    __tablename__ = "offers"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=False, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id"), nullable=False, index=True)
    assigned_agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False, index=True)
    transaction_intent = Column(String, nullable=False, default="purchase")
    asking_price = Column(Float, nullable=False)
    offered_price = Column(Float, nullable=False)
    current_price = Column(Float, nullable=False)
    currency = Column(String, nullable=False, default="AED")
    payment_frequency = Column(String, nullable=True)
    cheques_count = Column(Integer, nullable=True)
    financing_type = Column(String, nullable=True)
    status = Column(String, nullable=False, default="draft", index=True)
    submitted_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    decided_at = Column(DateTime, nullable=True)
    notes = Column(Text, nullable=True)
    terms_conditions = Column(Text, nullable=True)
    document_references = Column(Text, nullable=False, default="[]")
    negotiation_history = Column(Text, nullable=False, default="[]")
    idempotency_key = Column(String, unique=True, nullable=True, index=True)
    created_by_id = Column(Integer, ForeignKey("agents.id"), nullable=True)
    updated_by_id = Column(Integer, ForeignKey("agents.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    lead = relationship("Lead", foreign_keys=[lead_id], lazy="selectin")
    property_record = relationship("Property", foreign_keys=[property_id], lazy="selectin")
    assigned_agent = relationship("Agent", foreign_keys=[assigned_agent_id], lazy="selectin")
    customer = relationship("Customer", foreign_keys=[customer_id], lazy="selectin")

    __table_args__ = (
        CheckConstraint(
            "transaction_intent IN ('purchase','rent','lease')",
            name="ck_offers_intent",
        ),
        CheckConstraint(
            "status IN ('draft','submitted','countered','accepted','rejected','withdrawn','expired')",
            name="ck_offers_status",
        ),
        CheckConstraint("asking_price >= 0", name="ck_offers_asking_price"),
        CheckConstraint("offered_price > 0", name="ck_offers_offered_price"),
        CheckConstraint("current_price > 0", name="ck_offers_current_price"),
        Index("ix_offers_lead_status", "lead_id", "status"),
        Index("ix_offers_property_status", "property_id", "status"),
    )


class Deal(Base):
    """Real-estate deal & transaction pipeline record (Phase F)."""
    __tablename__ = "deals"

    id = Column(Integer, primary_key=True, index=True)
    deal_reference = Column(String, unique=True, nullable=False, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=False, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id"), nullable=False, index=True)
    offer_id = Column(Integer, ForeignKey("offers.id"), nullable=True, index=True)
    assigned_agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False, index=True)
    transaction_type = Column(String, nullable=False, default="purchase")
    agreed_amount = Column(Float, nullable=False)
    currency = Column(String, nullable=False, default="AED")
    payment_frequency = Column(String, nullable=True)
    status = Column(String, nullable=False, default="qualification", index=True)
    estimated_commission = Column(Float, nullable=True)
    estimated_commission_pct = Column(Float, nullable=True)
    actual_commission = Column(Float, nullable=True)
    commission_status = Column(String, nullable=False, default="estimated")
    commission_verified_by_id = Column(Integer, ForeignKey("agents.id"), nullable=True)
    commission_verified_at = Column(DateTime, nullable=True)
    reservation_date = Column(DateTime, nullable=True)
    target_completion_date = Column(DateTime, nullable=True)
    actual_completion_date = Column(DateTime, nullable=True)
    cancellation_or_failure_reason = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    stage_history = Column(Text, nullable=False, default="[]")
    created_by_id = Column(Integer, ForeignKey("agents.id"), nullable=True)
    updated_by_id = Column(Integer, ForeignKey("agents.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    lead = relationship("Lead", foreign_keys=[lead_id], lazy="selectin")
    property_record = relationship("Property", foreign_keys=[property_id], lazy="selectin")
    offer = relationship("Offer", foreign_keys=[offer_id], lazy="selectin")
    assigned_agent = relationship("Agent", foreign_keys=[assigned_agent_id], lazy="selectin")
    checklist_items = relationship(
        "DealChecklistItem",
        backref="deal",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="DealChecklistItem.id.asc()",
    )

    __table_args__ = (
        CheckConstraint(
            "transaction_type IN ('purchase','rent','lease')",
            name="ck_deals_type",
        ),
        CheckConstraint(
            "status IN ('qualification','viewing','offer_preparation','negotiation',"
            "'offer_accepted','reservation_pending','reservation_confirmed',"
            "'documentation_pending','transaction_pending_completion',"
            "'completed','cancelled','failed')",
            name="ck_deals_status",
        ),
        CheckConstraint(
            "commission_status IN ('estimated','verified','earned','paid')",
            name="ck_deals_commission_status",
        ),
        CheckConstraint("agreed_amount > 0", name="ck_deals_agreed_amount"),
        Index("ix_deals_lead_property_status", "lead_id", "property_id", "status"),
        Index("ix_deals_agent_status", "assigned_agent_id", "status"),
    )


class DealChecklistItem(Base):
    """Configurable document & compliance milestone item on a Deal (Phase F)."""
    __tablename__ = "deal_checklist_items"

    id = Column(Integer, primary_key=True, index=True)
    deal_id = Column(Integer, ForeignKey("deals.id"), nullable=False, index=True)
    code = Column(String, nullable=False)
    title = Column(String, nullable=False)
    category = Column(String, nullable=False, default="compliance")
    is_required = Column(Boolean, nullable=False, default=True)
    status = Column(String, nullable=False, default="pending")
    document_reference = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    responsible_user_id = Column(Integer, ForeignKey("agents.id"), nullable=True)
    verified_by_id = Column(Integer, ForeignKey("agents.id"), nullable=True)
    verified_by_label = Column(String, nullable=True)
    verified_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','uploaded','received','reviewed','verified','waived')",
            name="ck_deal_checklist_status",
        ),
        Index("ix_deal_checklist_deal_code", "deal_id", "code"),
    )


class CustomerCommunication(Base):
    """Structured customer-agent communication and internal notes (Phase H)."""
    __tablename__ = "customer_communications"

    id = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False, index=True)
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=True, index=True)
    property_id = Column(Integer, ForeignKey("properties.id"), nullable=True, index=True)
    appointment_id = Column(Integer, ForeignKey("appointments.id"), nullable=True, index=True)
    sender_type = Column(String, nullable=False)  # customer | agent | system
    sender_agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True, index=True)
    channel = Column(String, nullable=False, default="portal")  # portal | email | whatsapp | phone | internal_note
    subject = Column(String, nullable=True)
    message = Column(Text, nullable=False)
    is_customer_visible = Column(Boolean, nullable=False, default=True, index=True)
    follow_up_needed = Column(Boolean, nullable=False, default=False)
    follow_up_status = Column(String, nullable=True)  # pending | completed
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = Column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    customer = relationship("Customer", foreign_keys=[customer_id], back_populates="communications", lazy="selectin")
    sender_agent = relationship("Agent", foreign_keys=[sender_agent_id], lazy="selectin")
    lead = relationship("Lead", foreign_keys=[lead_id], lazy="selectin")
    property_record = relationship("Property", foreign_keys=[property_id], lazy="selectin")
    appointment = relationship("Appointment", foreign_keys=[appointment_id], lazy="selectin")

    __table_args__ = (
        CheckConstraint(
            "sender_type IN ('customer','agent','system')",
            name="ck_customer_comm_sender_type",
        ),
        Index("ix_customer_comm_customer_visible", "customer_id", "is_customer_visible", "created_at"),
    )


class PropertyImportBatch(Base):
    """Audit log and staging tracker for property import operations (Phase I)."""
    __tablename__ = "property_import_batches"

    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(String, unique=True, nullable=False, index=True)
    source = Column(String, nullable=False, default="uae_dataset")  # uae_dataset | json_file | csv_upload | manual_batch
    filename = Column(String, nullable=True)
    status = Column(String, nullable=False, default="preview")  # preview | staged | completed | failed
    total_records = Column(Integer, nullable=False, default=0)
    valid_records = Column(Integer, nullable=False, default=0)
    invalid_records = Column(Integer, nullable=False, default=0)
    duplicate_records = Column(Integer, nullable=False, default=0)
    imported_records = Column(Integer, nullable=False, default=0)
    validation_report = Column(Text, nullable=True)  # JSON summary of errors/warnings
    created_by_agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    completed_at = Column(DateTime, nullable=True)

    created_by_agent = relationship("Agent", foreign_keys=[created_by_agent_id], lazy="selectin")


class CustomerNotification(Base):
    """In-app notifications for customers and agents (Phase H)."""
    __tablename__ = "customer_notifications"

    id = Column(Integer, primary_key=True, index=True)
    recipient_type = Column(String, nullable=False)  # customer | agent
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=True, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=True, index=True)
    category = Column(String, nullable=False, default="general")  # appointment | viewing | offer | deal | general | system
    title = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    related_type = Column(String, nullable=True)  # appointment | property | deal | lead
    related_id = Column(Integer, nullable=True)
    action_url = Column(String, nullable=True)
    is_read = Column(Boolean, nullable=False, default=False, index=True)
    read_at = Column(DateTime, nullable=True)
    idempotency_key = Column(String, unique=True, nullable=True, index=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)

    customer = relationship("Customer", foreign_keys=[customer_id], back_populates="notifications", lazy="selectin")
    agent = relationship("Agent", foreign_keys=[agent_id], lazy="selectin")

    __table_args__ = (
        CheckConstraint(
            "recipient_type IN ('customer','agent')",
            name="ck_cust_notif_recipient_type",
        ),
        Index("ix_cust_notif_customer_unread", "customer_id", "is_read", "created_at"),
        Index("ix_cust_notif_agent_unread", "agent_id", "is_read", "created_at"),
    )




# ================================================================
# STAGE 6J — HR MANAGEMENT FOUNDATION
# ================================================================

class Employee(Base):
    """Employee master records linked to system users (Stage 6J)."""
    __tablename__ = "employees"

    id = Column(Integer, primary_key=True, index=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), unique=True, nullable=True, index=True)
    employee_id = Column(String(50), unique=True, nullable=False, index=True)
    full_name = Column(String(150), nullable=False, index=True)
    official_email = Column(String(200), unique=True, nullable=False, index=True)
    contact_number = Column(String(50), nullable=True)
    department = Column(String(100), nullable=False, default="Sales", index=True)
    designation = Column(String(100), nullable=False, default="Real Estate Consultant")
    reporting_manager_id = Column(Integer, ForeignKey("employees.id"), nullable=True)
    employment_type = Column(String(50), nullable=False, default="Full-time")  # Full-time | Part-time | Contract | Probation
    joining_date = Column(Date, nullable=True)
    employment_status = Column(String(50), nullable=False, default="Active", index=True)  # Active | On Leave | Suspended | Resigned | Terminated
    crm_role = Column(String(50), nullable=False, default="agent")
    branch = Column(String(100), nullable=False, default="Dubai Main Branch")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = Column(Integer, ForeignKey("agents.id"), nullable=True)
    updated_by = Column(Integer, ForeignKey("agents.id"), nullable=True)

    agent = relationship("Agent", foreign_keys=[agent_id], lazy="selectin", backref="employee_profile")
    reporting_manager = relationship("Employee", remote_side=[id], foreign_keys=[reporting_manager_id], lazy="selectin")
    attendance_records = relationship("Attendance", backref="employee", cascade="all, delete-orphan", lazy="selectin")
    leave_requests = relationship("LeaveRequest", backref="employee", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        CheckConstraint(
            "employment_status IN ('Active','On Leave','Suspended','Resigned','Terminated')",
            name="ck_employee_status",
        ),
    )


class Attendance(Base):
    """Daily employee attendance tracking and corrections (Stage 6J)."""
    __tablename__ = "attendance"

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    attendance_date = Column(Date, nullable=False, index=True)
    status = Column(String(50), nullable=False, default="Present", index=True)
    check_in = Column(DateTime, nullable=True)
    check_out = Column(DateTime, nullable=True)
    shift = Column(String(50), nullable=False, default="Standard (09:00 - 18:00 GST)")
    work_mode = Column(String(50), nullable=True, default="OFFICE")  # OFFICE | WORK_FROM_HOME | FIELD_DUTY
    source = Column(String(50), nullable=False, default="web")  # web | manual_correction | system_auto
    notes = Column(Text, nullable=True)
    correction_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = Column(Integer, ForeignKey("agents.id"), nullable=True)
    last_modified_by = Column(Integer, ForeignKey("agents.id"), nullable=True)

    __table_args__ = (
        UniqueConstraint("employee_id", "attendance_date", name="uq_attendance_emp_date"),
        CheckConstraint(
            "status IN ('Present','Absent','Late','Half Day','Field Duty','Work From Home','On Leave','Holiday','Weekly Off')",
            name="ck_attendance_status",
        ),
    )


class LeaveRequest(Base):
    """Employee leave requests and approvals (Stage 6J)."""
    __tablename__ = "leave_requests"

    id = Column(Integer, primary_key=True, index=True)
    employee_id = Column(Integer, ForeignKey("employees.id"), nullable=False, index=True)
    leave_type = Column(String(50), nullable=False)  # Casual Leave | Sick Leave | Annual/Earned Leave | Unpaid Leave | Other
    start_date = Column(Date, nullable=False, index=True)
    end_date = Column(Date, nullable=False, index=True)
    days_count = Column(Float, nullable=False, default=1.0)
    reason = Column(Text, nullable=False)
    status = Column(String(50), nullable=False, default="pending", index=True)  # pending | approved | rejected | cancelled
    reviewed_by = Column(Integer, ForeignKey("agents.id"), nullable=True)
    review_notes = Column(Text, nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    reviewer = relationship("Agent", foreign_keys=[reviewed_by], lazy="selectin")

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','approved','rejected','cancelled')",
            name="ck_leave_request_status",
        ),
        CheckConstraint(
            "leave_type IN ('Casual Leave','Sick Leave','Annual/Earned Leave','Unpaid Leave','Other')",
            name="ck_leave_type",
        ),
    )


# ---------------------------------------------------------------- migration

# create_all() only creates missing tables — it never alters existing ones.
# This adds any columns introduced by the two-tier refactor to old databases.
# Phase 2: additive columns for structured lead qualification and
# recommendation match history. Every entry is idempotent (column existence
# is checked before the ALTER), so re-running init_db() is always safe.
_MIGRATIONS = {
    "leads": [
        ("source", "VARCHAR"),
        ("assigned_agent_id", "INTEGER REFERENCES agents(id)"),
        ("last_interaction_at", "DATETIME"),
        # ---- Phase 2 (all nullable; NULL = not provided / not scored) ----
        ("original_enquiry", "TEXT"),
        ("budget_min", "FLOAT"),
        ("budget_max", "FLOAT"),
        ("budget_currency", "VARCHAR"),
        ("amenities", "TEXT"),
        ("lead_score", "INTEGER"),
        ("priority", "VARCHAR"),
        ("score_breakdown", "TEXT"),
        ("missing_fields", "TEXT"),
        ("clarification_questions", "TEXT"),
        ("timeline_days", "INTEGER"),
        ("extraction_source", "VARCHAR"),
        # ---- AI brain upgrade (all nullable; NULL = not set) ----
        ("temperature", "VARCHAR"),            # hot|warm|cold (server-classified)
        ("temperature_rationale", "TEXT"),     # JSON evidence for the temperature
        ("temperature_source", "VARCHAR"),     # auto|manual (manual locks auto-recompute)
        ("temperature_updated_at", "DATETIME"),
        ("summary", "TEXT"),                   # short conversation summary
        ("last_customer_message", "TEXT"),     # most recent customer message
    ],
    "conversations": [
        ("customer_id", "INTEGER REFERENCES customers(id)"),
        ("memory", "TEXT"),
    ],
    "messages": [
        ("message_type", "VARCHAR"),
    ],
    "property_recommendations": [
        ("lead_id", "INTEGER REFERENCES leads(id)"),
        # ---- Phase 2 (nullable: historical rows keep NULL) ----
        ("match_score", "FLOAT"),
        ("match_reasons", "TEXT"),
        ("match_mismatches", "TEXT"),
        # Plain INTEGER (no FK): SQLite cannot add a FK via ALTER TABLE.
        ("property_record_id", "INTEGER"),
    ],
    "customers": [
        ("password_hash", "VARCHAR"),
        ("preferred_locations", "TEXT"),
        ("property_type", "VARCHAR"),
        ("bedrooms_min", "INTEGER"),
        ("bedrooms_max", "INTEGER"),
        ("budget_min", "FLOAT"),
        ("budget_max", "FLOAT"),
        ("budget_currency", "VARCHAR DEFAULT 'AED'"),
        ("purpose", "VARCHAR"),
        ("preferred_contact_method", "VARCHAR"),
    ],
    # ---------------- Global auth (additive; every column nullable/defaulted) ---
    # No row is deleted or rewritten; existing staff keep working unchanged.
    "agents": [
        ("last_login_at", "DATETIME"),
        # NOT NULL with a default: SQLite ADD COLUMN supports this, and the
        # backfill sets existing rows to 0 (never a fabricated login).
        ("failed_login_count", "INTEGER NOT NULL DEFAULT 0"),
        ("locked_until", "DATETIME"),
        ("updated_at", "DATETIME"),
    ],
    "properties": [
        ("is_published", "BOOLEAN DEFAULT 0"),
        ("verification_status", "VARCHAR DEFAULT 'unverified'"),
        ("rejection_reason", "TEXT"),
        ("published_at", "DATETIME"),
        ("images", "TEXT DEFAULT '[]'"),
        ("primary_image", "VARCHAR"),
        ("source_id", "VARCHAR"),
        ("import_batch_id", "VARCHAR"),
        ("archived_at", "DATETIME"),
    ],
}


def _resolve_migration_type(decl: str, dialect_name: str) -> str:
    """Translate SQLite column declarations to dialect-compatible SQL when needed.

    PostgreSQL uses ``TIMESTAMP`` rather than ``DATETIME``; SQLite and libSQL
    keep ``DATETIME`` unchanged.
    """
    if dialect_name == "postgresql" and decl == "DATETIME":
        return "TIMESTAMP"
    return decl


def _run_migrations(target_engine=None):
    """Apply additive column migrations. Idempotent & repeatable.

    `target_engine` lets tests migrate a DISPOSABLE copy of a database
    without ever touching the live engine.
    """
    from sqlalchemy import inspect as sa_inspect, text

    eng = target_engine or engine
    dialect_name = eng.dialect.name
    inspector = sa_inspect(eng)
    existing_tables = set(inspector.get_table_names())
    for table, cols in _MIGRATIONS.items():
        if table not in existing_tables:
            continue
        have = {c["name"] for c in inspector.get_columns(table)}
        with eng.begin() as conn:
            for name, decl in cols:
                if name not in have:
                    col_decl = _resolve_migration_type(decl, dialect_name)
                    conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {col_decl}'))

    if "properties" in existing_tables:
        with eng.begin() as conn:
            # Phase I backfill: existing demo/approved rows should be verified and published if available
            bool_true = "TRUE" if dialect_name == "postgresql" else "1"
            bool_false = "FALSE" if dialect_name == "postgresql" else "0"
            conn.execute(text(
                f"UPDATE properties SET verification_status = 'verified' "
                f"WHERE is_approved = {bool_true} AND (verification_status IS NULL OR verification_status = 'unverified')"
            ))
            conn.execute(text(
                f"UPDATE properties SET is_published = {bool_true} "
                f"WHERE is_approved = {bool_true} AND availability = 'available' "
                f"AND (is_published IS NULL OR is_published = {bool_false}) AND source = 'demo_seed'"
            ))


# Indexes on columns that were added by ALTER (create_all can't index those
# on an existing table). All statements use IF NOT EXISTS → repeatable.
_POST_MIGRATION_INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_leads_priority ON leads (priority)",
    "CREATE INDEX IF NOT EXISTS ix_leads_lead_score ON leads (lead_score)",
    "CREATE INDEX IF NOT EXISTS ix_leads_created_at ON leads (created_at)",
    "CREATE INDEX IF NOT EXISTS ix_followups_lead_id ON follow_ups (lead_id)",
    "CREATE INDEX IF NOT EXISTS ix_followups_assigned_agent_id "
    "ON follow_ups (assigned_agent_id)",
    "CREATE INDEX IF NOT EXISTS ix_followups_due_at ON follow_ups (due_at)",
    "CREATE INDEX IF NOT EXISTS ix_recommendations_match_score "
    "ON property_recommendations (match_score)",
    "CREATE INDEX IF NOT EXISTS ix_recommendations_property_record_id "
    "ON property_recommendations (property_record_id)",
    "CREATE INDEX IF NOT EXISTS ix_leads_temperature ON leads (temperature)",
    "CREATE INDEX IF NOT EXISTS ix_conversations_lead_id ON conversations (lead_id)",
    "CREATE INDEX IF NOT EXISTS ix_cust_notif_customer_unread ON customer_notifications (customer_id, is_read, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_cust_notif_agent_unread ON customer_notifications (agent_id, is_read, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_customer_comm_customer_visible ON customer_communications (customer_id, is_customer_visible, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_properties_published ON properties (is_published)",
    "CREATE INDEX IF NOT EXISTS ix_properties_verification ON properties (verification_status)",
    "CREATE INDEX IF NOT EXISTS ix_properties_source_id ON properties (source_id)",
    "CREATE INDEX IF NOT EXISTS ix_properties_import_batch ON properties (import_batch_id)",
]


def _ensure_indexes(target_engine=None):
    from sqlalchemy import text

    eng = target_engine or engine
    with eng.begin() as conn:
        for stmt in _POST_MIGRATION_INDEXES:
            conn.execute(text(stmt))


def _seed_agents():
    """Create the initial CRM accounts when the agents table is empty.

    Development (APP_ENV unset/development) seeds the demo staff accounts with
    well-known passwords so the CRM works out of the box.  Production
    (APP_ENV=production) never uses the built-in demo passwords: a staff
    account is only seeded when its password is supplied explicitly through
    SEED_ADMIN_PASSWORD / SEED_AGENT_PASSWORD, so development credentials can
    never silently become production credentials.  Passwords are never logged.
    """
    import os
    import logging
    import bcrypt

    logger = logging.getLogger(__name__)
    is_production = os.getenv("APP_ENV", "development").strip().lower() in {
        "production",
        "prod",
    }

    db = SessionLocal()
    try:
        if db.query(Agent).count() > 0:
            return

        def _password(env_var: str, dev_default: str):
            """Explicit env password; demo default only outside production."""
            supplied = (os.getenv(env_var) or "").strip()
            if supplied:
                return supplied
            if is_production:
                logger.warning(
                    "APP_ENV=production and %s not set — skipping this staff seed. "
                    "Set %s to provision the account.", env_var, env_var,
                )
                return None
            return dev_default

        seeds = [
            {
                "email": os.getenv("SEED_ADMIN_EMAIL", "admin@lykarealty.ae"),
                "username": os.getenv("SEED_ADMIN_USERNAME", "admin"),
                "full_name": os.getenv("SEED_ADMIN_NAME", "Lyka Admin"),
                "password": _password("SEED_ADMIN_PASSWORD", "Admin@123"),
                "role": "admin",
            },
            {
                "email": os.getenv("SEED_AGENT_EMAIL", "agent@lykarealty.ae"),
                "username": os.getenv("SEED_AGENT_USERNAME", "agent"),
                "full_name": os.getenv("SEED_AGENT_NAME", "Sales Agent"),
                "password": _password("SEED_AGENT_PASSWORD", "Agent@123"),
                "role": "agent",
            },
        ]
        for s in seeds:
            if not s["password"]:
                continue
            db.add(Agent(
                email=s["email"],
                username=s["username"],
                full_name=s["full_name"],
                password_hash=bcrypt.hashpw(
                    s["password"].encode("utf-8"), bcrypt.gensalt()
                ).decode("utf-8"),
                role=s["role"],
            ))
        db.commit()
    finally:
        db.close()


# Create tables
def init_db():
    """Create missing tables, apply additive column migrations, index new
    columns, seed dev staff accounts. Safe to run repeatedly: create_all only
    creates missing tables, migrations check column existence, index creation
    uses IF NOT EXISTS, and staff seeding only runs on an empty agents table.
    """
    Base.metadata.create_all(bind=engine)
    _run_migrations()
    _ensure_indexes()
    _seed_agents()


# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
