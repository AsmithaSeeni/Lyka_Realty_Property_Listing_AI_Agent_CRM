import os
import json
import asyncio
import logging
from datetime import datetime
from typing import Dict, Optional, List
from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks, UploadFile, File, Request, Response
from fastapi.responses import Response as RawResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel, Field

from app.database import (
    init_db, get_db, SessionLocal,
    Conversation, Message, Lead, PropertyRecommendation, Customer, Agent,
    SavedProperty,
)
from app.config import settings
from app.ai.agent import AIRealEstateAgent, ConversationState
from app.services.property_search import search_properties, load_properties
from app.services.auth import (
    AGENT_COOKIE, CUSTOMER_COOKIE,
    hash_password, verify_password, create_session, revoke_session,
    get_current_agent, get_customer_token, get_or_create_customer,
    set_agent_cookie, clear_agent_cookie, lead_in_scope, scoped_lead_query,
    find_visitor_customer, set_customer_cookie, clear_customer_cookie,
    reissue_customer_token, claim_guest_conversations,
)
from app.services.leads import (
    upsert_lead_from_ai, find_existing_lead, lead_summary, lead_detail,
)

# Initialize database (creates tables, migrates columns, seeds CRM accounts)
init_db()

logger = logging.getLogger("lyka.api")

app = FastAPI(title="LykAI — AI Property Concierge by Lyka Realty (+ Agent CRM)", version="2.0.0")

# CORS — explicit origins so credentials (cookies) are honoured safely
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global agent instances (in production, use proper session management)
agents: Dict[int, AIRealEstateAgent] = {}


class ChatRequest(BaseModel):
    message: str = Field(..., description="User's chat message")
    conversation_id: Optional[int] = Field(None, description="Existing conversation ID")
    channel: Optional[str] = Field("text", description="text | voice (message origin)")
    property_id: Optional[int] = Field(
        None,
        description="Listing the customer is currently viewing (from the details page)",
    )


class ConversationCreate(BaseModel):
    customer_name: Optional[str] = Field(None)
    customer_phone: Optional[str] = Field(None)
    customer_email: Optional[str] = Field(None)


class LeadUpdate(BaseModel):
    """Partial update payload for PATCH /api/agent/leads/{id}."""
    status: Optional[str] = Field(None, description="new|contacted|qualified|viewing|negotiation|closed_won|closed_lost")
    notes: Optional[str] = Field(None)
    name: Optional[str] = Field(None)
    phone: Optional[str] = Field(None)
    email: Optional[str] = Field(None)
    buy_rent: Optional[str] = Field(None)
    location: Optional[str] = Field(None)
    budget: Optional[str] = Field(None)
    property_type: Optional[str] = Field(None)
    bedrooms: Optional[int] = Field(None)
    bathrooms: Optional[int] = Field(None)
    requirements: Optional[str] = Field(None)
    investment_purpose: Optional[str] = Field(None)
    timeline: Optional[str] = Field(None)
    assigned_agent_id: Optional[int] = Field(
        None, description="Assign to an agent (pass null to unassign)"
    )

    class Config:
        extra = "forbid"


LEAD_STATUSES = {
    "new", "contacted", "qualified", "viewing",
    "negotiation", "closed_won", "closed_lost",
}


# API Routes

@app.get("/api/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "message": "LykAI — AI Property Concierge by Lyka Realty is running"}


# ---------------- Voice endpoints ----------------

@app.post("/api/voice/transcribe")
async def voice_transcribe(
    file: UploadFile = File(...),
    language: Optional[str] = None,
):
    """Speech-to-Text: upload a recorded audio clip, get the transcript."""
    from app.services.voice import transcribe_audio

    audio = await file.read()
    if not audio:
        raise HTTPException(status_code=400, detail="Empty audio upload")
    try:
        result = await transcribe_audio(audio, file.filename or "audio.webm", language)
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    if not result.get("text"):
        raise HTTPException(
            status_code=422,
            detail="Could not understand the audio. Please speak clearly and try again.",
        )
    return result


class VoiceRespondRequest(ChatRequest):
    """Chat request that can also ask for spoken audio back."""
    speak: bool = Field(False, description="Also synthesize the reply as audio")
    voice: Optional[str] = Field(None, description="TTS voice override")


@app.post("/api/voice/respond")
def voice_respond(
    request: VoiceRespondRequest,
    db: Session = Depends(get_db),
    http_request: Request = None,
    response: Response = None,
):
    """
    Full voice turn: takes the transcribed text, runs the same conversation
    state as text chat, and optionally returns audio for the reply.
    """
    # Reuse the exact chat pipeline so voice and text share conversation state.
    # Forward the visitor identity (ownership scoping) and tag the turn as voice.
    result = chat(
        ChatRequest(
            message=request.message,
            conversation_id=request.conversation_id,
            channel="voice",
        ),
        db,
        http_request,
        response,
    )

    audio_b64 = None
    if request.speak and result.get("response"):
        try:
            import base64
            from app.services.voice import synthesize_speech
            audio_bytes = asyncio.run(
                synthesize_speech(result["response"], voice=request.voice,
                                  language=result.get("detected_language"))
            )
            audio_b64 = base64.b64encode(audio_bytes).decode("ascii")
        except Exception as e:
            # Never fail the chat turn because TTS failed
            logger.warning("TTS failed, returning text only: %s", e)

    return {**result, "audio_base64": audio_b64, "audio_format": "wav" if audio_b64 else None}


class SynthesizeRequest(BaseModel):
    text: str = Field(..., description="Text to speak")
    voice: Optional[str] = Field(None, description="Voice name (default from .env)")
    language: Optional[str] = Field(None, description="en | ta | ta-Latn")


@app.post("/api/voice/synthesize")
async def voice_synthesize(request: SynthesizeRequest):
    """Text-to-Speech: returns WAV audio bytes for the given text."""
    from app.services.voice import synthesize_speech

    try:
        audio = await synthesize_speech(request.text, voice=request.voice,
                                        language=request.language)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return RawResponse(content=audio, media_type="audio/wav")


@app.post("/api/chat")
def chat(
    request: ChatRequest,
    db: Session = Depends(get_db),
    http_request: Request = None,
    response: Response = None,
):
    """Handle chat messages from the frontend.

    Customer-scoped: the visitor is identified by an httpOnly cookie, and a
    conversation can only be opened/continued by the customer who owns it.
    """
    message = request.message.strip()
    conversation_id = request.conversation_id
    channel = "voice" if request.channel == "voice" else "text"

    # Identify (or start) the browser so conversations are isolated per customer
    customer = None
    if http_request is not None and response is not None:
        customer = get_or_create_customer(db, http_request, response)

    # Auto-create a conversation for the first message
    if not conversation_id:
        conv = Conversation(
            status="active",
            customer_id=customer.id if customer else None,
        )
        db.add(conv)
        db.commit()
        db.refresh(conv)
        conversation_id = conv.id
    else:
        # Ownership check: a customer may only continue their own conversation.
        # Orphan rows (customer_id NULL, pre-migration) are agents-only.
        conv = (
            db.query(Conversation)
            .filter(Conversation.id == conversation_id)
            .first()
        )
        if conv is None or (customer is not None and conv.customer_id != customer.id):
            raise HTTPException(status_code=404, detail="Conversation not found")

    # Get or create agent instance for this conversation
    agent = agents.get(conversation_id)
    if agent is None:
        agent = AIRealEstateAgent(conversation_id=conversation_id)
        # Restore prior context so reopening a conversation keeps memory:
        # replay messages for history AND re-extract requirements/contact
        prior = (
            db.query(Message)
            .filter(Message.conversation_id == conversation_id)
            .order_by(Message.id)
            .all()
        )
        for m in prior:
            agent.state.add_message(m.role, m.content, m.detected_language or "en")
            if m.role == "user":
                agent._extract_requirements(m.content)
        # Restore previously recommended properties so refinements
        # ("cheaper ones") still work after a restart
        recs = (
            db.query(PropertyRecommendation)
            .filter(PropertyRecommendation.conversation_id == conversation_id)
            .order_by(PropertyRecommendation.id)
            .all()
        )
        if recs:
            agent.state.recommended_properties = [
                {
                    "property_id": rec.property_id,
                    "price": rec.price,
                    "property_type": rec.property_type,
                    "location": rec.location,
                    "no__of__beds": str(rec.bedrooms) if rec.bedrooms else "",
                    "no_of_baths": rec.bathrooms,
                    "area": rec.area,
                    "highlights": rec.highlights,
                }
                for rec in recs
            ]
        agents[conversation_id] = agent

    # Property the customer is viewing (came from the details page "Ask LykAI"
    # action) - resolved server-side from the dataset so the LLM only ever
    # sees real values for that listing.
    focus_property = None
    if request.property_id:
        focus_property = next(
            (p for p in load_properties() if p.get("property_id") == request.property_id),
            None,
        )

    # Process the message
    result = agent.respond(message, focus_property=focus_property)

    # Save the user's message
    db.add(Message(
        conversation_id=conversation_id,
        role="user",
        content=message,
        detected_language=result.get("detected_language", "en"),
        message_type=channel,
    ))

    # Save the assistant's reply
    db.add(Message(
        conversation_id=conversation_id,
        role="assistant",
        content=result["response"],
        detected_language=result.get("detected_language", "en"),
        message_type=channel,
        property_recommendation_ids=json.dumps(
            [p.get("property_id") for p in result.get("properties", [])]
        ) if result.get("properties") else None,
    ))

    # Create or update a lead once enough info + contact details exist.
    # This is a server-side, authenticated code path — there is no public
    # HTTP endpoint that can write leads. Existing leads are REUSED (matched
    # by phone or email) so the same customer never creates duplicates.
    conv_row = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if result.get("action") == "collect_lead" or agent._should_collect_lead():
        lead_data = agent.get_lead_data()
        if any(v is not None for v in lead_data.values()):
            upsert_lead_from_ai(db, lead_data, conversation=conv_row)

    # Persist recommended properties for this conversation
    if result.get("properties"):
        for prop in result.get("properties", [])[:5]:
            prop_id = prop.get("property_id", 0)
            existing = (
                db.query(PropertyRecommendation)
                .filter(
                    PropertyRecommendation.property_id == prop_id,
                    PropertyRecommendation.conversation_id == conversation_id,
                )
                .first()
            )
            if not existing:
                beds_str = str(prop.get("no__of__beds", "")).strip()
                try:
                    bedrooms_val = int(float(beds_str))
                except (ValueError, TypeError):
                    bedrooms_val = 0  # "Studio" or unknown
                try:
                    baths_val = float(prop.get("no_of_baths") or 0)
                except (ValueError, TypeError):
                    baths_val = 0.0
                db.add(PropertyRecommendation(
                    conversation_id=conversation_id,
                    property_id=prop_id,
                    price=prop.get("price", ""),
                    property_type=prop.get("property_type", ""),
                    location=prop.get("location", ""),
                    bedrooms=bedrooms_val,
                    bathrooms=baths_val,
                    area=prop.get("area", ""),
                    highlights=prop.get("highlights", ""),
                    relevance_score=0.5,
                ))

    # Touch conversation timestamp and capture customer name if we learned it
    if conv_row:
        conv_row.updated_at = datetime.utcnow()
        if not conv_row.customer_name and agent.state.contact.get("name"):
            conv_row.customer_name = agent.state.contact["name"]
        if not conv_row.customer_phone and agent.state.contact.get("phone"):
            conv_row.customer_phone = agent.state.contact["phone"]
        if not conv_row.customer_email and agent.state.contact.get("email"):
            conv_row.customer_email = agent.state.contact["email"]

        # Mirror learned contact details onto the visitor record (never invent)
        if customer is not None:
            if not customer.name and agent.state.contact.get("name"):
                customer.name = agent.state.contact["name"]
            if not customer.phone and agent.state.contact.get("phone"):
                customer.phone = agent.state.contact["phone"]
            if not customer.email and agent.state.contact.get("email"):
                customer.email = agent.state.contact["email"]

        # Link the conversation to its lead for the CRM detail view.
        # Only link on a real identifier (phone/email) so anonymous chats
        # never attach to someone else's lead. Reuses existing leads.
        if not conv_row.lead_id:
            link_phone = agent.state.contact.get("phone")
            link_email = agent.state.contact.get("email")
            if link_phone or link_email:
                linked_lead = find_existing_lead(db, phone=link_phone, email=link_email)
                if linked_lead:
                    conv_row.lead_id = linked_lead.id
                    linked_lead.last_interaction_at = datetime.utcnow()
                    # Recommendations shown in this conversation belong to the lead
                    (
                        db.query(PropertyRecommendation)
                        .filter(
                            PropertyRecommendation.conversation_id == conversation_id,
                            PropertyRecommendation.lead_id.is_(None),
                        )
                        .update({"lead_id": linked_lead.id}, synchronize_session=False)
                    )

    db.commit()
    
    # Return response
    return {
        "conversation_id": conversation_id or 0,
        "response": result["response"],
        "action": result["action"],
        "properties": result.get("properties", []),
        "detected_language": result.get("detected_language", "en"),
        "language_style": result.get("language_style", "en"),
        "new_conversation": conversation_id is None
    }


def _current_customer(db: Session, http_request: Request):
    """Resolve the visitor behind the customer cookie (None when absent)."""
    token = get_customer_token(http_request) if http_request else None
    if not token:
        return None
    from app.database import Customer as _C
    return (
        db.query(_C)
        .filter(_C.token_hash == _C.hash_token(token))
        .first()
    )


@app.get("/api/conversations")
async def list_conversations(
    db: Session = Depends(get_db),
    http_request: Request = None,
):
    """List THIS visitor's conversations only (never other customers')."""
    customer = _current_customer(db, http_request)
    if customer is None:
        return []
    conversations = (
        db.query(Conversation)
        .filter(Conversation.customer_id == customer.id)
        .order_by(Conversation.updated_at.desc())
        .all()
    )
    return [
        {
            "id": c.id,
            "customer_name": c.customer_name,
            "customer_phone": c.customer_phone,
            "customer_email": c.customer_email,
            "lead_id": c.lead_id,
            "status": c.status,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
            "message_count": len(c.messages) if c.messages else 0,
        }
        for c in conversations
    ]


@app.get("/api/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    http_request: Request = None,
):
    """Get a specific conversation with messages (owner only).

    Returns 404 both when the conversation doesn't exist and when it belongs
    to somebody else, so IDs can't be probed for existence.
    """
    customer = _current_customer(db, http_request)
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if (
        conv is None
        or customer is None
        or conv.customer_id != customer.id
    ):
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = db.query(Message).filter(Message.conversation_id == conversation_id).all()

    # Try to restore agent state
    agent = None
    if conversation_id in agents:
        agent = agents[conversation_id]
    
    return {
        "conversation": {
            "id": conv.id,
            "customer_name": conv.customer_name,
            "status": conv.status,
        },
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "detected_language": m.detected_language,
                "message_type": m.message_type or "text",
                # Listing ids shared with this exact message, so the chat can
                # re-attach property cards to the reply that introduced them.
                "property_recommendation_ids": (
                    json.loads(m.property_recommendation_ids)
                    if m.property_recommendation_ids else None
                ),
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ],
        "property_recommendations": [
            {
                "property_id": rec.property_id,
                "price": rec.price,
                "property_type": rec.property_type,
                "location": rec.location,
                "bedrooms": rec.bedrooms,
                "bathrooms": rec.bathrooms,
                "area": rec.area,
                "highlights": rec.highlights,
            }
            for rec in conv.property_recommendations
        ] if hasattr(conv, 'property_recommendations') else []
    }


@app.post("/api/conversations")
async def create_conversation(
    request: ConversationCreate, 
    db: Session = Depends(get_db),
    http_request: Request = None,
    response: Response = None,
):
    """Create a new conversation owned by the current visitor."""
    customer = None
    if http_request is not None and response is not None:
        customer = get_or_create_customer(db, http_request, response)

    conv = Conversation(
        customer_name=request.customer_name,
        customer_phone=request.customer_phone,
        customer_email=request.customer_email,
        status="active",
        customer_id=customer.id if customer else None,
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)
    
    # Create agent instance
    agent = AIRealEstateAgent(conversation_id=conv.id)
    agents[conv.id] = agent
    
    return {
        "conversation_id": conv.id,
        "message": "New conversation created",
    }


# Property search APIs

@app.get("/api/properties/search")
async def search_properties_api(
    location: Optional[str] = None,
    property_type: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    min_bedrooms: Optional[int] = None,
    max_bedrooms: Optional[int] = None,
    min_bathrooms: Optional[float] = None,
    max_bathrooms: Optional[float] = None,
    min_area: Optional[float] = None,
    max_area: Optional[float] = None,
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
):
    """Search properties with filters (paginated for the browse page)."""
    result = search_properties(
        db=db,
        location=location,
        property_type=property_type,
        min_price=min_price,
        max_price=max_price,
        min_bedrooms=min_bedrooms,
        max_bedrooms=max_bedrooms,
        min_bathrooms=min_bathrooms,
        max_bathrooms=max_bathrooms,
        min_area=min_area,
        max_area=max_area,
        limit=max(1, min(int(limit), 48)),
        offset=max(0, int(offset)),
    )
    
    return {
        "results": result["results"],
        "total": result["total"],
        "limit": result.get("limit", 20),
        "offset": result.get("offset", 0),
        "filters_applied": {
            "location": location,
            "property_type": property_type,
            "price_range": (min_price, max_price),
            "bedrooms": (min_bedrooms, max_bedrooms),
            "bathrooms": (min_bathrooms, max_bathrooms),
            "area": (min_area, max_area),
        }
    }


@app.get("/api/properties/{property_id}")
async def get_property(property_id: int, db: Session = Depends(get_db)):
    """Get a specific property by ID."""
    properties = load_properties()
    prop = next((p for p in properties if p.get("property_id") == property_id), None)
    
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    
    return prop


# ================================================================
# CUSTOMER ACCOUNTS (optional — guests chat with LykAI immediately)
# ================================================================

class CustomerRegister(BaseModel):
    email: str = Field(..., min_length=3, description="Account email")
    password: str = Field(..., min_length=6, description="At least 6 characters")
    name: Optional[str] = Field(None, max_length=120)


class CustomerLogin(BaseModel):
    email: str = Field(..., min_length=3)
    password: str = Field(..., min_length=1)


class SavedPropertyIn(BaseModel):
    property_id: int


def _customer_public(customer: Customer) -> dict:
    return {
        "authenticated": customer.is_account,
        "email": customer.email if customer.is_account else None,
        "name": customer.name,
    }


def _normalize_email(email: str) -> str:
    email = (email or "").strip().lower()
    if "@" not in email or len(email) < 5:
        raise HTTPException(status_code=422, detail="Enter a valid email address")
    return email


@app.get("/api/customer/me")
def customer_me(
    db: Session = Depends(get_db),
    http_request: Request = None,
):
    """Who is this browser? Guests get authenticated:false (no cookie is created)."""
    customer = find_visitor_customer(db, http_request) if http_request else None
    if customer is None:
        return {"authenticated": False, "email": None, "name": None}
    return _customer_public(customer)


@app.post("/api/customer/register")
def customer_register(
    payload: CustomerRegister,
    db: Session = Depends(get_db),
    http_request: Request = None,
    response: Response = None,
):
    """Create an optional customer account and link this guest's conversations."""
    email = _normalize_email(payload.email)
    existing = (
        db.query(Customer)
        .filter(Customer.password_hash.isnot(None), Customer.email == email)
        .first()
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="An account already exists — sign in instead")

    token = Customer.new_token()
    account = Customer(
        token_hash=Customer.hash_token(token),
        email=email,
        name=(payload.name or "").strip() or None,
        password_hash=hash_password(payload.password),
    )
    db.add(account)
    db.commit()
    db.refresh(account)

    # Existing guest chats now belong to the account (test: history survives)
    guest = find_visitor_customer(db, http_request) if http_request else None
    if guest is not None and not guest.is_account:
        claim_guest_conversations(db, guest, account)

    if response is not None:
        set_customer_cookie(response, token, max_age_days=30)
    return _customer_public(account)


@app.post("/api/customer/login")
def customer_login(
    payload: CustomerLogin,
    db: Session = Depends(get_db),
    http_request: Request = None,
    response: Response = None,
):
    """Sign in to an existing customer account (guest chats are claimed too)."""
    email = _normalize_email(payload.email)
    account = (
        db.query(Customer)
        .filter(Customer.password_hash.isnot(None), Customer.email == email)
        .first()
    )
    # Same generic error whether the account is unknown or the password is wrong
    if account is None or not verify_password(payload.password, account.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    current = find_visitor_customer(db, http_request) if http_request else None
    if current is None or current.id != account.id:
        if current is not None and not current.is_account:
            claim_guest_conversations(db, current, account)
        token = reissue_customer_token(db, account)
        if response is not None:
            set_customer_cookie(response, token, max_age_days=30)
    return _customer_public(account)


@app.post("/api/customer/logout")
def customer_logout(response: Response):
    """Sign out — the next chat starts a fresh guest session."""
    clear_customer_cookie(response)
    return {"ok": True}


# ---------------- Saved properties (signed-in customers) ----------------

def _require_account_customer(db: Session, http_request: Request) -> Customer:
    customer = find_visitor_customer(db, http_request) if http_request else None
    if customer is None or not customer.is_account:
        raise HTTPException(
            status_code=401,
            detail="Sign in to save properties",
        )
    return customer


@app.get("/api/customer/saved")
def customer_saved(
    db: Session = Depends(get_db),
    http_request: Request = None,
):
    """Full dataset rows for this customer's saved listings (real data only)."""
    customer = _require_account_customer(db, http_request)
    rows = (
        db.query(SavedProperty)
        .filter(SavedProperty.customer_id == customer.id)
        .order_by(SavedProperty.id.desc())
        .all()
    )
    by_id = {p.get("property_id"): p for p in load_properties()}
    results = [by_id[r.property_id] for r in rows if r.property_id in by_id]
    return {"results": results, "total": len(results)}


@app.post("/api/customer/saved")
def customer_save(
    payload: SavedPropertyIn,
    db: Session = Depends(get_db),
    http_request: Request = None,
):
    """Bookmark a listing (idempotent — never creates duplicates)."""
    customer = _require_account_customer(db, http_request)
    prop = next(
        (p for p in load_properties() if p.get("property_id") == payload.property_id),
        None,
    )
    if prop is None:
        raise HTTPException(status_code=404, detail="Property not found")
    existing = (
        db.query(SavedProperty)
        .filter(
            SavedProperty.customer_id == customer.id,
            SavedProperty.property_id == payload.property_id,
        )
        .first()
    )
    if existing is None:
        db.add(SavedProperty(customer_id=customer.id, property_id=payload.property_id))
        db.commit()
    return {"saved": True, "property_id": payload.property_id}


@app.delete("/api/customer/saved/{property_id}")
def customer_unsave(
    property_id: int,
    db: Session = Depends(get_db),
    http_request: Request = None,
):
    customer = _require_account_customer(db, http_request)
    (
        db.query(SavedProperty)
        .filter(
            SavedProperty.customer_id == customer.id,
            SavedProperty.property_id == property_id,
        )
        .delete()
    )
    db.commit()
    return {"saved": False, "property_id": property_id}


# ================================================================
# AGENT AUTHENTICATION (internal CRM)
# ================================================================

class LoginRequest(BaseModel):
    username: str = Field(..., description="Email address or username")
    password: str = Field(..., min_length=1)


def _agent_public(agent: Agent) -> dict:
    return {
        "id": agent.id,
        "email": agent.email,
        "username": agent.username,
        "full_name": agent.full_name,
        "role": agent.role,
    }


@app.post("/api/auth/login")
def auth_login(
    payload: LoginRequest,
    db: Session = Depends(get_db),
    response: Response = None,
):
    """Authenticate an agent (email OR username + password).

    On success sets an httpOnly session cookie and returns the token once for
    API clients that prefer `Authorization: Bearer <token>`.
    """
    identifier = (payload.username or "").strip().lower()
    agent = (
        db.query(Agent)
        .filter(
            (func.lower(Agent.email) == identifier)
            | (func.lower(Agent.username) == identifier)
        )
        .first()
    )
    # Same generic error for unknown user vs wrong password (no user probing)
    if agent is None or not agent.is_active or not verify_password(payload.password, agent.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = create_session(db, agent)
    set_agent_cookie(response, token)
    return {
        "agent": _agent_public(agent),
        "token": token,
        "token_type": "bearer",
    }


@app.post("/api/auth/logout")
def auth_logout(
    request: Request,
    db: Session = Depends(get_db),
    response: Response = None,
):
    """Revoke the current session and clear the cookie (idempotent)."""
    token = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
    if not token:
        token = request.cookies.get(AGENT_COOKIE)
    if token:
        revoke_session(db, token)
    clear_agent_cookie(response)
    return {"ok": True}


@app.get("/api/auth/me")
def auth_me(agent: Agent = Depends(get_current_agent)):
    """Who am I? 401 when unauthenticated — used for route guarding."""
    return {"agent": _agent_public(agent)}


# ================================================================
# AGENT CRM API  (role-based, scope-checked on EVERY request)
# ================================================================

def _scoped_lead_or_404(db: Session, agent: Agent, lead_id: int) -> Lead:
    """404 for leads outside this agent's scope (never leak existence)."""
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if lead is None or not lead_in_scope(agent, lead):
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


def _scoped_conversations(db: Session, agent: Agent):
    """Conversations visible to this agent.

    - admin → every conversation
    - agent → conversations attached to leads in their scope
      (assigned to them, or unassigned in the shared pool)
    """
    q = db.query(Conversation)
    if agent.role != "admin":
        rows = scoped_lead_query(db, agent).with_entities(Lead.id).all()
        scoped_lead_ids = [r[0] for r in rows]
        if not scoped_lead_ids:
            return q.filter(Conversation.id.is_(None))
        q = q.filter(Conversation.lead_id.in_(scoped_lead_ids))
    return q


@app.get("/api/agent/dashboard")
def agent_dashboard(
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """CRM home: status counts + recent leads + recent conversations."""
    scoped = scoped_lead_query(db, agent)
    all_leads = scoped.all()

    counts = {"total": len(all_leads)}
    for status in sorted(LEAD_STATUSES):
        counts[status] = sum(1 for l in all_leads if (l.status or "new") == status)
    # Friendly aliases used by the stat cards
    counts["closed"] = counts.get("closed_won", 0)
    counts["lost"] = counts.get("closed_lost", 0)

    recent_leads = sorted(
        all_leads,
        key=lambda l: l.last_interaction_at or l.updated_at or l.created_at,
        reverse=True,
    )[:8]

    conv_rows = (
        _scoped_conversations(db, agent)
        .order_by(Conversation.updated_at.desc())
        .limit(8)
        .all()
    )
    recent_conversations = [_conversation_row(c) for c in conv_rows]

    return {
        "agent": _agent_public(agent),
        "counts": counts,
        "recent_leads": [lead_summary(l) for l in recent_leads],
        "recent_conversations": recent_conversations,
    }


def _conversation_row(conv: Conversation) -> dict:
    """Row shape for conversation lists (with last-message preview)."""
    last = conv.messages[-1] if conv.messages else None
    lead = conv.lead
    return {
        "id": conv.id,
        "customer_name": conv.customer_name or (lead.name if lead else None),
        "customer_phone": conv.customer_phone or (lead.phone if lead else None),
        "customer_email": conv.customer_email or (lead.email if lead else None),
        "lead_id": conv.lead_id,
        "lead_status": lead.status if lead else None,
        "status": conv.status,
        "message_count": len(conv.messages or []),
        "last_message_preview": (last.content[:160] if last and last.content else ""),
        "last_message_role": last.role if last else None,
        "created_at": conv.created_at.isoformat() if conv.created_at else None,
        "updated_at": conv.updated_at.isoformat() if conv.updated_at else None,
    }


@app.get("/api/agent/leads")
def agent_list_leads(
    status: Optional[str] = None,
    location: Optional[str] = None,
    q: Optional[str] = None,
    sort: Optional[str] = "newest",   # newest | interaction
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """Lead list with search, status/location filters and sorting.

    Scoped: agents only ever receive their own + unassigned leads.
    """
    query = scoped_lead_query(db, agent)

    if status:
        query = query.filter(Lead.status == status)
    if location:
        query = query.filter(Lead.location.ilike(f"%{location}%"))
    if q:
        needle = f"%{q.strip()}%"
        query = query.filter(
            (Lead.name.ilike(needle))
            | (Lead.phone.ilike(needle))
            | (Lead.email.ilike(needle))
            | (Lead.location.ilike(needle))
            | (Lead.id == q.strip() if q.strip().isdigit() else False)
        )

    total = query.count()

    if sort == "interaction":
        # Manual NULLS LAST (portable across SQLite versions)
        query = query.order_by(
            Lead.last_interaction_at.is_(None),
            Lead.last_interaction_at.desc(),
            Lead.updated_at.desc(),
        )
    else:
        query = query.order_by(Lead.created_at.desc())

    leads = query.offset(max(0, offset)).limit(max(1, min(500, limit))).all()
    return {"total": total, "results": [lead_summary(l) for l in leads]}


@app.get("/api/agent/leads/{lead_id}")
def agent_get_lead(
    lead_id: int,
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """Full lead detail: profile, every AI conversation, all recommendations."""
    lead = _scoped_lead_or_404(db, agent, lead_id)

    conversations = (
        db.query(Conversation)
        .filter(Conversation.lead_id == lead.id)
        .order_by(Conversation.created_at.asc())
        .all()
    )

    # Lead -> Property Recommendations (from linked conversations)
    recs = (
        db.query(PropertyRecommendation)
        .filter(
            (PropertyRecommendation.lead_id == lead.id)
            | (
                PropertyRecommendation.lead_id.is_(None)
                & PropertyRecommendation.conversation_id.in_(
                    [c.id for c in conversations] or [0]
                )
            )
        )
        .order_by(PropertyRecommendation.created_at.desc())
        .all()
    )

    return {
        "lead": lead_detail(lead),
        "conversations": [
            {
                "id": c.id,
                "status": c.status,
                "created_at": c.created_at.isoformat() if c.created_at else None,
                "updated_at": c.updated_at.isoformat() if c.updated_at else None,
                "messages": [
                    {
                        "id": m.id,
                        "role": m.role,
                        "content": m.content,
                        "detected_language": m.detected_language,
                        "message_type": m.message_type or "text",
                        "created_at": m.created_at.isoformat() if m.created_at else None,
                    }
                    for m in c.messages
                ],
            }
            for c in conversations
        ],
        "property_recommendations": [
            {
                "property_id": r.property_id,
                "price": r.price,
                "property_type": r.property_type,
                "location": r.location,
                "bedrooms": r.bedrooms,
                "bathrooms": r.bathrooms,
                "area": r.area,
                "highlights": r.highlights,
                "conversation_id": r.conversation_id,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in recs
        ],
    }


@app.patch("/api/agent/leads/{lead_id}")
def agent_update_lead(
    lead_id: int,
    update: LeadUpdate,
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """Update status/notes/assignment for a lead in this agent's scope."""
    lead = _scoped_lead_or_404(db, agent, lead_id)

    fields = update.model_dump(exclude_unset=True)

    # Status validation
    if "status" in fields and fields["status"] is not None:
        if fields["status"] not in LEAD_STATUSES:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid status. Allowed: {', '.join(sorted(LEAD_STATUSES))}",
            )

    # Assignment rules (role-based access control)
    if "assigned_agent_id" in fields:
        target = fields["assigned_agent_id"]
        if target is not None:
            target_agent = db.query(Agent).filter(Agent.id == target).first()
            if target_agent is None or not target_agent.is_active:
                raise HTTPException(status_code=422, detail="Unknown agent")
            if agent.role != "admin" and target != agent.id:
                raise HTTPException(
                    status_code=403,
                    detail="Only an admin can assign leads to another agent",
                )

    for key, value in fields.items():
        if hasattr(lead, key):
            setattr(lead, key, value)
    lead.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(lead)

    return {"lead": lead_detail(lead)}


@app.get("/api/agent/conversations")
def agent_list_conversations(
    q: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """All customer conversations in this agent's scope (business view).

    Search matches customer name/phone/email, lead id, conversation id and
    an ISO date (same day) or date range on the last interaction.
    """
    query = _scoped_conversations(db, agent)

    if q:
        needle = f"%{q.strip()}%"
        query = query.filter(
            (Conversation.customer_name.ilike(needle))
            | (Conversation.customer_phone.ilike(needle))
            | (Conversation.customer_email.ilike(needle))
            | (Conversation.lead_id == q.strip() if q.strip().isdigit() else False)
            | (Conversation.id == q.strip() if q.strip().isdigit() else False)
        )
    if date_from:
        try:
            query = query.filter(Conversation.updated_at >= datetime.fromisoformat(date_from))
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid date_from (use YYYY-MM-DD)")
    if date_to:
        try:
            end = datetime.fromisoformat(date_to)
            if len(date_to) == 10:  # inclusive whole day
                from datetime import timedelta
                end = end + timedelta(days=1)
            query = query.filter(Conversation.updated_at < end)
        except ValueError:
            raise HTTPException(status_code=422, detail="Invalid date_to (use YYYY-MM-DD)")

    total = query.count()
    rows = (
        query.order_by(Conversation.updated_at.desc())
        .offset(max(0, offset))
        .limit(max(1, min(500, limit)))
        .all()
    )
    return {"total": total, "results": [_conversation_row(c) for c in rows]}


@app.get("/api/agent/conversations/{conversation_id}")
def agent_get_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """Full conversation thread + recommendations for the agent review view."""
    conv = (
        db.query(Conversation)
        .filter(Conversation.id == conversation_id)
        .first()
    )
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    # Scope: admin sees all; agents see conversations of leads in their scope
    if agent.role != "admin":
        if conv.lead_id is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        _scoped_lead_or_404(db, agent, conv.lead_id)

    return {
        "conversation": _conversation_row(conv),
        "lead": lead_detail(conv.lead) if conv.lead else None,
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "detected_language": m.detected_language,
                "message_type": m.message_type or "text",
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in conv.messages
        ],
        "property_recommendations": [
            {
                "property_id": r.property_id,
                "price": r.price,
                "property_type": r.property_type,
                "location": r.location,
                "bedrooms": r.bedrooms,
                "bathrooms": r.bathrooms,
                "area": r.area,
                "highlights": r.highlights,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in conv.property_recommendations
        ],
    }