from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Text, Boolean, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
from datetime import datetime
import json

SQLALCHEMY_DATABASE_URL = "sqlite:///./real_estate.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}, echo=False
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


# Database Models
class Lead(Base):
    __tablename__ = "leads"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    email = Column(String, nullable=True)
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
    status = Column(String, default="new")  # "new", "qualified", "contacted", "viewing", "negotiation", "closed_lost"
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    customer_name = Column(String, nullable=True)
    customer_phone = Column(String, nullable=True)
    customer_email = Column(String, nullable=True)
    status = Column(String, default="active")  # "active", "closed", "lost"
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
    )
    lead_id = Column(Integer, ForeignKey("leads.id"), nullable=True)


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), index=True)
    role = Column(String)  # "user" or "assistant"
    content = Column(Text)
    detected_language = Column(String, default="en")  # "en", "ta", "ta-Latn", "mixed"
    property_recommendation_ids = Column(String, nullable=True)  # JSON array of property IDs
    created_at = Column(DateTime, default=datetime.utcnow)


class PropertyRecommendation(Base):
    __tablename__ = "property_recommendations"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), index=True)
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


# Create tables
def init_db():
    Base.metadata.create_all(bind=engine)


# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()