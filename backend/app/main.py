import os
import json
import asyncio
import logging
from datetime import datetime
from typing import Dict, Optional, List
from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks, UploadFile, File
from fastapi.responses import Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field

from app.database import init_db, get_db, SessionLocal, Conversation, Message, Lead, PropertyRecommendation
from app.config import settings
from app.ai.agent import AIRealEstateAgent, ConversationState
from app.services.property_search import search_properties, load_properties

# Initialize database
init_db()

logger = logging.getLogger("lyka.api")

app = FastAPI(title="Lyka Realty AI Agent + CRM", version="1.0.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global agent instances (in production, use proper session management)
agents: Dict[int, AIRealEstateAgent] = {}


class ChatRequest(BaseModel):
    message: str = Field(..., description="User's chat message")
    conversation_id: Optional[int] = Field(None, description="Existing conversation ID")


class ConversationCreate(BaseModel):
    customer_name: Optional[str] = Field(None)
    customer_phone: Optional[str] = Field(None)
    customer_email: Optional[str] = Field(None)


class LeadUpdate(BaseModel):
    """Partial update payload for PATCH /api/leads/{id}."""
    status: Optional[str] = Field(None, description="new|qualified|contacted|viewing|negotiation|closed_won|closed_lost")
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

    class Config:
        extra = "forbid"


# API Routes

@app.get("/api/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "message": "Lyka Realty AI Agent is running"}


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
def voice_respond(request: VoiceRespondRequest, db: Session = Depends(get_db)):
    """
    Full voice turn: takes the transcribed text, runs the same conversation
    state as text chat, and optionally returns audio for the reply.
    """
    # Reuse the exact chat pipeline so voice and text share conversation state
    result = chat(ChatRequest(message=request.message, conversation_id=request.conversation_id), db)

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
    return Response(content=audio, media_type="audio/wav")


@app.post("/api/chat")
def chat(request: ChatRequest, db: Session = Depends(get_db)):
    """Handle chat messages from the frontend."""
    message = request.message.strip()
    conversation_id = request.conversation_id

    # Auto-create a conversation for the first message
    if not conversation_id:
        conv = Conversation(status="active")
        db.add(conv)
        db.commit()
        db.refresh(conv)
        conversation_id = conv.id

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

    # Process the message
    result = agent.respond(message)

    # Save the user's message
    db.add(Message(
        conversation_id=conversation_id,
        role="user",
        content=message,
        detected_language=result.get("detected_language", "en"),
    ))

    # Save the assistant's reply
    db.add(Message(
        conversation_id=conversation_id,
        role="assistant",
        content=result["response"],
        detected_language=result.get("detected_language", "en"),
        property_recommendation_ids=json.dumps(
            [p.get("property_id") for p in result.get("properties", [])]
        ) if result.get("properties") else None,
    ))

    # Create or update a lead once enough info + contact details exist
    if result.get("action") == "collect_lead" or agent._should_collect_lead():
        lead_data = agent.get_lead_data()
        if any(v is not None for v in lead_data.values()):
            existing_lead = (
                db.query(Lead)
                .filter(
                    Lead.phone == lead_data.get("phone"),
                    Lead.phone.isnot(None),
                )
                .first()
                if lead_data.get("phone")
                else None
            )
            if existing_lead:
                for key, value in lead_data.items():
                    if value is not None:
                        setattr(existing_lead, key, value)
                existing_lead.updated_at = datetime.utcnow()
            else:
                db.add(Lead(**lead_data))

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
    conv_row = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if conv_row:
        conv_row.updated_at = datetime.utcnow()
        if not conv_row.customer_name and agent.state.contact.get("name"):
            conv_row.customer_name = agent.state.contact["name"]
        if not conv_row.customer_phone and agent.state.contact.get("phone"):
            conv_row.customer_phone = agent.state.contact["phone"]
        if not conv_row.customer_email and agent.state.contact.get("email"):
            conv_row.customer_email = agent.state.contact["email"]
        # Link the conversation to its lead for the CRM detail view.
        # Only link on a real identifier (phone/email) so anonymous chats
        # never attach to someone else's lead.
        if not conv_row.lead_id:
            lead_q = db.query(Lead)
            if agent.state.contact.get("phone"):
                lead_q = lead_q.filter(Lead.phone == agent.state.contact["phone"])
            elif agent.state.contact.get("email"):
                lead_q = lead_q.filter(Lead.email == agent.state.contact["email"])
            else:
                lead_q = None
            if lead_q is not None:
                linked_lead = lead_q.order_by(Lead.id.desc()).first()
                if linked_lead:
                    conv_row.lead_id = linked_lead.id

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


@app.get("/api/conversations")
async def list_conversations(db: Session = Depends(get_db)):
    """List all conversations."""
    conversations = db.query(Conversation).order_by(Conversation.created_at.desc()).all()
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
async def get_conversation(conversation_id: int, db: Session = Depends(get_db)):
    """Get a specific conversation with messages."""
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
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
    db: Session = Depends(get_db)
):
    """Create a new conversation."""
    conv = Conversation(
        customer_name=request.customer_name,
        customer_phone=request.customer_phone,
        customer_email=request.customer_email,
        status="active",
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
    db: Session = Depends(get_db),
):
    """Search properties with filters."""
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
        limit=20,
    )
    
    return {
        "results": result["results"],
        "total": result["total"],
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


# Lead APIs

@app.post("/api/leads")
async def create_lead(
    lead_data: dict,
    db: Session = Depends(get_db)
):
    """Create a new lead."""
    db_lead = Lead(**lead_data)
    db.add(db_lead)
    db.commit()
    db.refresh(db_lead)
    
    return {
        "id": db_lead.id,
        "created_at": db_lead.created_at.isoformat() if db_lead.created_at else None,
        "status": db_lead.status,
    }


@app.get("/api/leads")
async def list_leads(
    status: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """List all leads with optional status filter."""
    query = db.query(Lead)
    if status:
        query = query.filter(Lead.status == status)
    
    leads = query.order_by(Lead.created_at.desc()).all()
    return [
        {
            "id": l.id,
            "name": l.name,
            "phone": l.phone,
            "email": l.email,
            "buy_rent": l.buy_rent,
            "location": l.location,
            "budget": l.budget,
            "property_type": l.property_type,
            "bedrooms": l.bedrooms,
            "status": l.status,
            "created_at": l.created_at.isoformat() if l.created_at else None,
        }
        for l in leads
    ]


@app.get("/api/leads/{lead_id}")
async def get_lead(lead_id: int, db: Session = Depends(get_db)):
    """Get a specific lead."""
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    return {
        "id": lead.id,
        "name": lead.name,
        "phone": lead.phone,
        "email": lead.email,
        "buy_rent": lead.buy_rent,
        "location": lead.location,
        "budget": lead.budget,
        "property_type": lead.property_type,
        "bedrooms": lead.bedrooms,
        "bathrooms": lead.bathrooms,
        "requirements": lead.requirements,
        "investment_purpose": lead.investment_purpose,
        "timeline": lead.timeline,
        "notes": lead.notes,
        "status": lead.status,
        "created_at": lead.created_at.isoformat() if lead.created_at else None,
        "updated_at": lead.updated_at.isoformat() if lead.updated_at else None,
    }


@app.patch("/api/leads/{lead_id}")
def update_lead(
    lead_id: int,
    update: LeadUpdate,
    db: Session = Depends(get_db),
):
    """Update a lead's status, notes, or other fields via JSON body."""
    lead = db.query(Lead).filter(Lead.id == lead_id).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    fields = update.model_dump(exclude_unset=True)
    for key, value in fields.items():
        if value is not None and hasattr(lead, key):
            setattr(lead, key, value)
    lead.updated_at = datetime.utcnow()

    db.commit()

    return {
        "id": lead.id,
        "status": lead.status,
        "notes": lead.notes,
        "updated_at": lead.updated_at.isoformat() if lead.updated_at else None,
    }