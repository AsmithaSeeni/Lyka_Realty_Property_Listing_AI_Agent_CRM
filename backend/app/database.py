from sqlalchemy import (
    create_engine, Column, Integer, String, Float, DateTime, Text,
    Boolean, ForeignKey, UniqueConstraint, Index,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from datetime import datetime
import hashlib
import secrets

SQLALCHEMY_DATABASE_URL = "sqlite:///./real_estate.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}, echo=False
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

# Sentinel used when a lead field is genuinely unknown (never invent data).
# Rendered as-is by the agent API and shown verbatim in the CRM UI.
NOT_PROVIDED = "Not provided"


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- Agent side

class Agent(Base):
    """Internal sales agent (CRM user). Passwords are bcrypt hashes only."""
    __tablename__ = "agents"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, nullable=False, index=True)
    username = Column(String, unique=True, nullable=False, index=True)
    full_name = Column(String, nullable=False)
    password_hash = Column(String, nullable=False)   # bcrypt, never plaintext
    role = Column(String, nullable=False, default="agent")  # "admin" | "agent"
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    sessions = relationship("AgentSession", backref="agent", cascade="all, delete-orphan")
    assigned_leads = relationship("Lead", backref="assigned_agent", lazy="selectin")


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
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    conversations = relationship("Conversation", backref="customer", lazy="selectin")

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
    last_interaction_at = Column(DateTime, nullable=True)  # last customer activity
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    conversations = relationship("Conversation", backref="lead", lazy="selectin")
    property_recommendations = relationship(
        "PropertyRecommendation",
        backref="lead",
        lazy="selectin",
        foreign_keys="PropertyRecommendation.lead_id",
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


# ---------------------------------------------------------------- migration

# create_all() only creates missing tables — it never alters existing ones.
# This adds any columns introduced by the two-tier refactor to old databases.
_MIGRATIONS = {
    "leads": [
        ("source", "VARCHAR"),
        ("assigned_agent_id", "INTEGER REFERENCES agents(id)"),
        ("last_interaction_at", "DATETIME"),
    ],
    "conversations": [
        ("customer_id", "INTEGER REFERENCES customers(id)"),
    ],
    "messages": [
        ("message_type", "VARCHAR"),
    ],
    "property_recommendations": [
        ("lead_id", "INTEGER REFERENCES leads(id)"),
    ],
    "customers": [
        ("password_hash", "VARCHAR"),
    ],
}


def _run_migrations():
    from sqlalchemy import inspect as sa_inspect, text

    inspector = sa_inspect(engine)
    existing_tables = set(inspector.get_table_names())
    for table, cols in _MIGRATIONS.items():
        if table not in existing_tables:
            continue
        have = {c["name"] for c in inspector.get_columns(table)}
        with engine.begin() as conn:
            for name, decl in cols:
                if name not in have:
                    conn.execute(text(f'ALTER TABLE {table} ADD COLUMN {name} {decl}'))


def _seed_agents():
    """Create the initial CRM accounts when the agents table is empty."""
    import os
    import bcrypt

    db = SessionLocal()
    try:
        if db.query(Agent).count() > 0:
            return
        seeds = [
            {
                "email": os.getenv("SEED_ADMIN_EMAIL", "admin@lykarealty.ae"),
                "username": os.getenv("SEED_ADMIN_USERNAME", "admin"),
                "full_name": os.getenv("SEED_ADMIN_NAME", "Lyka Admin"),
                "password": os.getenv("SEED_ADMIN_PASSWORD", "Admin@123"),
                "role": "admin",
            },
            {
                "email": os.getenv("SEED_AGENT_EMAIL", "agent@lykarealty.ae"),
                "username": os.getenv("SEED_AGENT_USERNAME", "agent"),
                "full_name": os.getenv("SEED_AGENT_NAME", "Sales Agent"),
                "password": os.getenv("SEED_AGENT_PASSWORD", "Agent@123"),
                "role": "agent",
            },
        ]
        for s in seeds:
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
    Base.metadata.create_all(bind=engine)
    _run_migrations()
    _seed_agents()


# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
