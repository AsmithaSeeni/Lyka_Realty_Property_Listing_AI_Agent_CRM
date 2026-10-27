import os
import json
import asyncio
import logging
from datetime import datetime
from typing import Annotated, Dict, List, Literal, Optional
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Request, Response, Query
from fastapi.responses import Response as RawResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.database import (
    init_db, get_db, SessionLocal,
    Conversation, Message, Lead, Property, PropertyRecommendation, Customer,
    Agent, SavedProperty, FollowUp, AgentRole, AuditLog,
)
from app.config import settings
from app.ai.agent import AIRealEstateAgent, ConversationState
from app.ai.lead_extraction import (
    INTENTS,
    MAX_ENQUIRY_CHARS,
    LeadExtractionError,
    LeadExtractionRequest,
    LeadExtractionResult,
    extract_lead_requirements,
)
from app.services.property_search import (
    search_properties,
    load_properties,
    get_property_by_id,
    search_property_records,
    public_record_dict,
    dataset_browse_dict,
    dataset_db_record_dict,
    get_public_record,
    get_public_records,
    record_focus_dict,
)
from app.services.lead_scoring import score_lead
from app.services.property_matching import (
    MatchRequest, match_properties, save_recommendations,
)
from app.services.followups import (
    FOLLOWUP_FILTERS, FOLLOWUP_TYPES,
    create_followup, filter_followups, follow_up_summary,
    list_lead_followups, parse_due_at, scoped_followup_query, update_followup,
)
from app.services.crm_stats import dashboard_stats
from app.services.auth import (
    AGENT_COOKIE, CUSTOMER_COOKIE,
    hash_password, verify_password, create_session, revoke_session,
    get_current_agent, get_customer_token, get_or_create_customer,
    set_agent_cookie, clear_agent_cookie, lead_in_scope, scoped_lead_query,
    find_visitor_customer, set_customer_cookie, clear_customer_cookie,
    reissue_customer_token, claim_guest_conversations,
    # Global-auth additions (Phase 1/2/5/6)
    record_login_failure, record_login_success, revoke_all_sessions,
    load_role_keys, cache_permissions, roles_of, permissions_of,
    require_authenticated_user, require_roles, require_permissions,
    ensure_permission, _is_locked,
)
from app.services import rbac
from app.services import audit as auditlog
from app.services.leads import (
    upsert_lead_from_ai, find_existing_lead, find_duplicate, lead_summary,
    lead_detail, lead_to_extraction, recompute_lead_score,
    encode_budget_display, encode_preferences, parse_budget_period,
)
from app.services.ratelimit import rate_limit

logger = logging.getLogger("lyka.api")

# Initialize database (creates tables, migrates columns, seeds CRM accounts).
# Every route depends on the schema, so a failure here must fail loudly at
# import time with an actionable hint (captured in Vercel function logs)
# instead of surfacing as opaque per-request 500s later.
try:
    init_db()
except Exception:
    logger.exception(
        "Database initialisation failed - the API cannot start. Verify "
        "DATABASE_URL (libsql://... for Turso) and TURSO_AUTH_TOKEN in the "
        "deployment environment; a local SQLite fallback is not usable on a "
        "read-only serverless filesystem."
    )
    raise

# Surface per-turn timing logs (respond(): search/llm ms, NVIDIA chat done)
# in the console. Without a handler on the "app" package logger these INFO
# lines are dropped and response-time debugging is impossible.
_app_log = logging.getLogger("app")
if not _app_log.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S")
    )
    _app_log.addHandler(_handler)
    _app_log.setLevel(logging.INFO)

# API schema exposure: in production the interactive docs (/docs, /redoc) and
# the OpenAPI schema are disabled so the full API surface is not published.
# Local development keeps them for convenience.
_IS_PRODUCTION = settings.APP_ENV.strip().lower() == "production"

app = FastAPI(
    title="LykAI — AI Property Concierge by Lyka Realty (+ Agent CRM)",
    version="2.0.0",
    docs_url=None if _IS_PRODUCTION else "/docs",
    redoc_url=None if _IS_PRODUCTION else "/redoc",
    openapi_url=None if _IS_PRODUCTION else "/openapi.json",
)


# ---------------- Phase 1: global error handling ----------------
# Consistent, safe error shape for UNEXPECTED failures: clients get the same
# {"detail": ...} envelope as HTTPException (no stack traces, no secrets).
# The traceback is logged server-side only (code lines — never headers,
# cookies, keys, or request bodies).
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception(
        "Unhandled error on %s %s", request.method, request.url.path
    )
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


# ---------------- Phase 1: request-size guard ----------------
# Registered BEFORE the CORS middleware so the CORS layer stays outermost and
# still decorates 413 responses for cross-origin browsers. Chunked requests
# without a Content-Length are not blocked here (browsers and the Vite proxy
# always send it); field-level max_length validation below covers JSON bodies.
@app.middleware("http")
async def request_size_guard(request: Request, call_next):
    if request.method in ("POST", "PUT", "PATCH"):
        raw_len = request.headers.get("content-length", "")
        if raw_len.isdigit() and int(raw_len) > settings.REQUEST_MAX_BYTES:
            return JSONResponse(
                status_code=413,
                content={"detail": "Request body too large"},
            )
    return await call_next(request)


# ---------------- CSRF defence-in-depth (origin guard) ----------------
# Browser sessions authenticate with httpOnly cookies protected by
# SameSite=Lax (see services.auth), and the API has no state-changing GET
# endpoints — that alone stops classic cross-site form/CSRF abuse in modern
# browsers. As defence in depth, unsafe methods on /api/* additionally
# require a known Origin when the browser sends one: same-origin, or one of
# the explicitly configured CORS origins (the trusted Vite dev server).
# Requests WITHOUT an Origin header (curl, server-to-server, tests) are not
# browser-initiated and are allowed — they cannot be CSRF'd.
_UNSAFE_METHODS = ("POST", "PUT", "PATCH", "DELETE")


def _origin_allowed(origin: str, request: Request) -> bool:
    origin = (origin or "").strip().rstrip("/")
    if not origin:
        return True
    # Same-origin: the Origin matches this request's own scheme://host
    # (covers the production single-host deployment behind any port).
    host = (request.headers.get("host") or "").strip()
    if host and origin in (f"http://{host}", f"https://{host}"):
        return True
    # Explicitly trusted cross-origin clients (e.g. the Vite dev server).
    return origin.rstrip("/") in {o.rstrip("/") for o in settings.CORS_ORIGINS}


@app.middleware("http")
async def csrf_origin_guard(request: Request, call_next):
    if request.method in _UNSAFE_METHODS and request.url.path.startswith("/api/"):
        if not _origin_allowed(request.headers.get("origin", ""), request):
            return JSONResponse(
                status_code=403,
                content={"detail": "Cross-origin request rejected"},
            )
    return await call_next(request)


# CORS — origins from configuration (safe localhost defaults; no wildcard
# possible in production — see config.parse_cors). Explicit origins so
# credentials (cookies) are honoured safely.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global agent instances (in production, use proper session management)
agents: Dict[int, AIRealEstateAgent] = {}


class ChatRequest(BaseModel):
    message: str = Field(
        ...,
        description="User's chat message",
        min_length=1,
        max_length=settings.CHAT_MESSAGE_MAX_CHARS,  # Phase 1 input-length limit
    )
    conversation_id: Optional[int] = Field(None, description="Existing conversation ID")
    channel: Optional[str] = Field("text", description="text | voice (message origin)")
    property_id: Optional[int] = Field(
        None,
        description="Listing the customer is currently viewing (from the details page)",
    )
    # Which listing space `property_id` refers to: the UAE dataset (default,
    # legacy behavior) or a DB-backed Lyka listing record (Phase 6 browse).
    property_source: Optional[Literal["dataset", "record"]] = Field(
        "dataset",
        description="Listing space of property_id: 'dataset' (default) | 'record'",
    )
    # (no language field: the agent classifies each message itself and replies
    #  in that language — the reply-language selector was removed)


class ConversationCreate(BaseModel):
    customer_name: Optional[str] = Field(None)
    customer_phone: Optional[str] = Field(None)
    customer_email: Optional[str] = Field(None)


class LeadUpdate(BaseModel):
    """Partial update payload for PATCH /api/agent/leads/{id}."""
    model_config = ConfigDict(extra="forbid")

    # --- legacy/summary fields (already in use by the CRM UI) ---
    status: Optional[str] = Field(None, description="new|contacted|qualified|viewing|negotiation|closed_won|closed_lost")
    notes: Optional[str] = Field(None)
    name: Optional[str] = Field(None, max_length=120)
    phone: Optional[str] = Field(None, max_length=40)
    email: Optional[str] = Field(None, max_length=200)
    buy_rent: Optional[str] = Field(None, description="intent: buy|rent|lease|unknown")
    location: Optional[str] = Field(None, max_length=100)
    budget: Optional[str] = Field(None, max_length=200)
    property_type: Optional[str] = Field(None, max_length=60)
    bedrooms: Optional[int] = Field(None, ge=0, le=30)
    bathrooms: Optional[int] = Field(None, ge=0, le=30)
    requirements: Optional[str] = Field(None, max_length=4000)
    investment_purpose: Optional[str] = Field(None, max_length=200)
    timeline: Optional[str] = Field(None, max_length=200)
    assigned_agent_id: Optional[int] = Field(
        None, description="Assign to an agent (pass null to unassign)"
    )
    # --- Phase 5: structured requirement / contact / link fields ---
    original_enquiry: Optional[str] = Field(None, max_length=MAX_ENQUIRY_CHARS)
    budget_min: Optional[float] = Field(None, ge=0, le=1e12)
    budget_max: Optional[float] = Field(None, ge=0, le=1e12)
    budget_currency: Optional[str] = Field(
        None, max_length=3, description="ISO currency code (pass '' to clear)")
    budget_period: Optional[Literal["monthly", "yearly", "one_time"]] = Field(
        None, description="Stored as a canonical token in the budget display text")
    amenities: Optional[List[Annotated[str, Field(max_length=80)]]] = Field(
        None, max_length=30)
    preferences: Optional[List[Annotated[str, Field(max_length=80)]]] = Field(
        None, max_length=30)
    timeline_days: Optional[int] = Field(None, ge=1, le=3650)
    conversation_id: Optional[int] = Field(
        None, ge=1, description="Relink conversation (pass null to unlink)")


StatusLiteral = Literal[
    "new", "contacted", "qualified", "viewing",
    "negotiation", "closed_won", "closed_lost",
]
# Route-level and model-level status vocabularies must never drift apart.
assert set(StatusLiteral.__args__) == {
    "new", "contacted", "qualified", "viewing",
    "negotiation", "closed_won", "closed_lost",
}


class LeadCreate(BaseModel):
    """Reviewed lead payload for POST /api/agent/leads (staff only).

    Extends the Phase 3 extraction contract so a reviewed/edited extraction
    can be confirmed as-is, with CRM-only additions. There is deliberately
    NO score/priority field: scores are computed server-side by
    `lead_scoring`, and extra keys (e.g. a spoofed `lead_score`) are ignored.

    Schema equivalents (no migration — see README Phase 5):
    - budget period → canonical token inside `budget` ("per month"/"per year")
    - preferences   → JSON array string inside `requirements`
    - customer link → validated here; stored through the linked conversation
      (`conversations.customer_id`), because `leads` has no customer FK.
    """
    model_config = ConfigDict(extra="ignore")

    # --- contact (validated; blank → None) ---
    name: Optional[Annotated[str, Field(max_length=120)]] = None
    phone: Optional[Annotated[str, Field(
        max_length=40, pattern=r"^\+?[0-9()\-\s]{4,40}$")]] = None
    email: Optional[Annotated[str, Field(
        max_length=200, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")]] = None
    # --- requirements ---
    intent: Literal["buy", "rent", "lease", "unknown"] = "unknown"
    property_type: Optional[Annotated[str, Field(max_length=60)]] = None
    location: Optional[Annotated[str, Field(max_length=100)]] = None
    bedrooms: Optional[int] = Field(None, ge=0, le=30)
    bathrooms: Optional[int] = Field(None, ge=0, le=30)
    budget_min: Optional[float] = Field(None, ge=0, le=1e12)
    budget_max: Optional[float] = Field(None, ge=0, le=1e12)
    budget_currency: Optional[Annotated[str, Field(
        min_length=3, max_length=3, pattern=r"^[A-Za-z]{3}$")]] = None
    budget_period: Optional[Literal["monthly", "yearly", "one_time"]] = None
    amenities: List[Annotated[str, Field(max_length=80)]] = Field(
        default_factory=list, max_length=30)
    preferences: List[Annotated[str, Field(max_length=80)]] = Field(
        default_factory=list, max_length=30)
    timeline: Optional[Annotated[str, Field(max_length=200)]] = None
    timeline_days: Optional[int] = Field(None, ge=1, le=3650)
    original_enquiry: str = Field("", max_length=MAX_ENQUIRY_CHARS)
    provenance: Dict[str, str] = Field(
        default_factory=dict,
        description="Phase 3 review provenance (used only to set extraction_source)")

    # --- CRM additions ---
    confirm: bool = Field(
        ..., description="Explicit confirmation of the reviewed details (required)")
    duplicate_override: bool = Field(
        False, description="Create anyway after a duplicate warning (never overwrites)")
    status: StatusLiteral = "new"
    notes: str = Field("", max_length=4000)
    customer_id: Optional[int] = Field(None, ge=1)
    conversation_id: Optional[int] = Field(None, ge=1)
    assigned_agent_id: Optional[int] = Field(None, ge=1)

    @field_validator("name", "phone", "email", "budget_currency", mode="before")
    @classmethod
    def _blank_to_none(cls, v):
        if isinstance(v, str) and not v.strip():
            return None
        return v


class FollowUpCreate(BaseModel):
    """POST /api/agent/leads/{id}/follow-ups."""
    model_config = ConfigDict(extra="ignore")

    type: str = Field(..., description="call|email|whatsapp|viewing|general")
    due_at: datetime = Field(..., description="ISO-8601; naive values are read as UTC")
    notes: str = Field("", max_length=4000)
    assigned_agent_id: Optional[int] = Field(None, ge=1)


class FollowUpUpdate(BaseModel):
    """PATCH /api/agent/follow-ups/{id} — partial update."""
    model_config = ConfigDict(extra="ignore")

    type: Optional[str] = None
    due_at: Optional[datetime] = None
    notes: Optional[str] = Field(None, max_length=4000)
    is_completed: Optional[bool] = None
    assigned_agent_id: Optional[int] = Field(None, ge=1)


class RecommendationRun(BaseModel):
    """POST /api/agent/leads/{id}/recommendations."""
    model_config = ConfigDict(extra="ignore")

    limit: int = Field(3, ge=1, le=10)
    save: bool = Field(True, description="Persist new history rows (deduplicated)")


LEAD_STATUSES = {
    "new", "contacted", "qualified", "viewing",
    "negotiation", "closed_won", "closed_lost",
}

# Lead fields whose change requires a deterministic server-side re-score.
SCORE_TRIGGER_FIELDS = {
    "buy_rent", "location", "property_type", "bedrooms", "bathrooms",
    "budget", "budget_min", "budget_max", "budget_currency", "budget_period",
    "amenities", "preferences", "timeline", "timeline_days",
    "original_enquiry", "requirements",
}

PRIORITY_FILTERS = {"high", "medium", "low", "unscored"}


# API Routes

@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    """Cheap liveness + dependency checks. Never calls an AI provider.

    Always HTTP 200 (liveness); `status` is "healthy" only when every check
    passes, so a probe can tell "process is up" apart from "database reachable
    / property data present / providers configured".
    """
    checks: Dict[str, object] = {"application": "ok"}

    listings = None
    try:
        listings = db.query(func.count(Property.id)).scalar() or 0
        checks["database"] = "ok"
    except Exception as e:  # database unreachable — reported, not raised
        logger.warning("health: database check failed: %s", e)
        checks["database"] = "error"

    # Dataset parsing is a one-time per-instance cost (~100ms); afterwards
    # len() is O(1). A missing file logs a warning inside and yields 0 rows.
    checks["property_data"] = {
        "dataset_rows": len(load_properties()),
        "db_listings": listings,
    }
    checks["ai_config"] = {
        "nvidia_configured": bool(os.getenv("NVIDIA_API_KEY", "").strip()),
        "stt_provider": os.getenv("STT_PROVIDER", "").strip() or None,
        "tts_provider": os.getenv("TTS_PROVIDER", "").strip() or None,
    }

    return {
        "status": "healthy" if checks["database"] == "ok" else "degraded",
        "message": "LykAI — AI Property Concierge by Lyka Realty is running",
        "checks": checks,
    }


# ---------------- Voice endpoints ----------------

@app.post("/api/voice/transcribe")
async def voice_transcribe(
    request: Request,
    file: UploadFile = File(...),
    language: Optional[str] = None,
    _rl: None = Depends(rate_limit("voice", "VOICE_RATE_LIMIT")),
):
    """Speech-to-Text: upload a recorded audio clip, get the transcript.

    Customer-facing: intentionally NOT staff-authenticated (any visitor may
    speak to the concierge). Protected by rate limiting + upload size limits.

    ``language`` (the Whisper hint) is accepted BOTH as a query parameter and
    as a multipart form field: the client sends a form field, and the earlier
    query-only declaration silently dropped it, so the Tamil/English hint
    never reached the transcription provider (Phase 11 fix).
    """
    from app.services.voice import transcribe_audio

    if not language:
        form = await request.form()
        language = form.get("language") or None
    audio = await file.read()
    if not audio:
        raise HTTPException(status_code=400, detail="Empty audio upload")
    if len(audio) > settings.VOICE_UPLOAD_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Audio upload too large")
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
    _rl: None = Depends(rate_limit("voice", "VOICE_RATE_LIMIT")),
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
            property_id=request.property_id,
            property_source=request.property_source,
        ),
        db,
        http_request,
        response,
    )

    audio_b64 = None
    audio_format = None
    if request.speak and result.get("response"):
        try:
            import base64
            from app.services.voice import synthesize_speech
            # TTS hint: "mixed" is not a synthesis language - a mixed reply's
            # spoken body is Tamil-dominant, so hint "ta" instead of dropping
            # the hint entirely (Phase 11 fix).
            tts_language = result.get("reply_language") or result.get("detected_language") or "ta-Latn"
            if tts_language == "mixed":
                tts_language = "ta"
            audio_bytes = asyncio.run(
                synthesize_speech(result["response"], voice=request.voice,
                                  language=tts_language)
            )
            audio_b64 = base64.b64encode(audio_bytes).decode("ascii")
            is_mp3 = audio_bytes.startswith(b"ID3") or audio_bytes[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")
            audio_format = "mp3" if is_mp3 else "wav"
        except Exception as e:
            # Never fail the chat turn because TTS failed
            logger.warning("TTS failed, returning text only: %s", e)

    return {**result, "audio_base64": audio_b64, "audio_format": audio_format}


class SynthesizeRequest(BaseModel):
    text: str = Field(
        ...,
        description="Text to speak",
        min_length=1,
        max_length=settings.SYNTHESIZE_TEXT_MAX_CHARS,  # Phase 1 input-length limit
    )
    voice: Optional[str] = Field(None, description="Voice name (default from .env)")
    language: Optional[str] = Field(None, description="en | ta | ta-Latn")


@app.post("/api/voice/synthesize")
async def voice_synthesize(
    request: SynthesizeRequest,
    _rl: None = Depends(rate_limit("voice", "VOICE_RATE_LIMIT")),
):
    """Text-to-Speech: returns audio bytes for the given text.

    Customer-facing (no staff login required); rate-limited like the other
    voice endpoints.
    """
    from app.services.voice import synthesize_speech

    try:
        audio = await synthesize_speech(request.text, voice=request.voice,
                                        language=request.language)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))

    media_type = (
        "audio/mpeg"
        if audio.startswith(b"ID3") or audio[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")
        else "audio/wav"
    )
    return RawResponse(content=audio, media_type=media_type)


@app.post("/api/chat")
def chat(
    request: ChatRequest,
    db: Session = Depends(get_db),
    http_request: Request = None,
    response: Response = None,
    _rl: None = Depends(rate_limit("chat", "CHAT_RATE_LIMIT")),
):
    """Handle chat messages from the frontend.

    Customer-scoped: the visitor is identified by an httpOnly cookie, and a
    conversation can only be opened/continued by the customer who owns it.
    Rate-limited per IP (chat calls the LLM); body length is capped by
    ChatRequest.max_length.
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
                # Restore a standing language request too (Phase 11): the
                # reply-language pin lives only in conversation state, so
                # without this a cold restart answered "Could you talk in
                # Tamil?" follow-ups in English again.
                req = AIRealEstateAgent.detect_language_request(m.content)
                if req:
                    agent.state.language_request = req
                    agent.state.reply_language = req
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
    # action) - resolved server-side so the LLM only ever sees real values for
    # that listing. Two id spaces exist (Phase 6):
    #  - 'dataset' (default): the UAE dataset listing (legacy behavior);
    #  - 'record': a DB-backed Lyka listing, resolved with the SAME public
    #    eligibility rule as the browse pages (approved + available). An
    #    ineligible record resolves to NO focus at all, so the assistant can
    #    never claim an unverified listing is available.
    focus_property = None
    if request.property_id:
        if request.property_source == "record":
            record = get_public_record(db, request.property_id)
            focus_property = record_focus_dict(record) if record else None
        else:
            focus_property = get_property_by_id(request.property_id)

    # Process the message — the agent decides the reply language itself
    # (English / Tamil / Tanglish / mixed) from the customer's message.
    try:
        result = agent.respond(
            message,
            focus_property=focus_property,
            channel=channel,
        )
    except TypeError:
        result = agent.respond(
            message,
            focus_property=focus_property,
        )

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

    # Persist recommended properties for this conversation. Persist ALL cards
    # the customer saw (up to 10), not just the first five — otherwise a
    # reopened conversation renumbers only 5 of the 10 visible cards and
    # ordinal references ("the second property") drift after a restart.
    if result.get("properties"):
        for prop in result.get("properties", [])[:10]:
            # Defense in depth (Phase 7): the recommendations table is keyed
            # by DATASET ids — a record-space dict (Phase 6 browse listings)
            # must never be persisted as a dataset row. The agent already
            # keeps record-space focus out of its card lists; this guard
            # preserves the invariant for any future code path.
            if prop.get("source") == "record":
                continue
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
        "reply_language": getattr(getattr(agent, "state", None), "reply_language", "en"),
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


# ---------------------------------------------------------------------------
# Phase 6 — public browsing of DB-backed listings (the `properties` table).
# These endpoints serve ONLY approved + available rows; the legacy dataset
# endpoints above/below are untouched for existing chat/history/saved flows.
# ---------------------------------------------------------------------------

@app.get("/api/properties")
def list_public_properties(
    purpose: Optional[Literal["sale", "rent", "lease"]] = None,
    location: Optional[str] = Query(None, max_length=120),
    property_type: Optional[str] = Query(None, max_length=60),
    min_price: Optional[float] = Query(None, ge=0),
    max_price: Optional[float] = Query(None, ge=0),
    min_bedrooms: Optional[int] = Query(None, ge=0, le=20),
    max_bedrooms: Optional[int] = Query(None, ge=0, le=20),
    limit: int = Query(24, ge=1, le=48),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Public browse of APPROVED + AVAILABLE listings only (Phase 6).

    Server-side filtering and pagination over the `properties` table — the
    25,082-row JSON dataset is never shipped to the browser. Ordering is
    deterministic (price ascending, id ascending) via `search_property_records`.
    Invalid query values are rejected with a validation error (422), never
    silently guessed. Rows are serialized with `public_record_dict`, so
    internal governance fields (is_approved, source, external_ref, timestamps)
    are never exposed.
    """
    result = search_property_records(
        db,
        purpose=purpose,
        location=location,
        property_type=property_type,
        min_price=min_price,
        max_price=max_price,
        min_bedrooms=min_bedrooms,
        max_bedrooms=max_bedrooms,
        limit=limit,
        offset=offset,
    )
    return {
        "results": [public_record_dict(p) for p in result["results"]],
        "total": result["total"],
        "limit": result["limit"],
        "offset": result["offset"],
    }


# NOTE: must stay registered BEFORE /api/properties/{property_id} so the
# literal "record" segment is never captured by the legacy dataset path route.
@app.get("/api/properties/record/{property_id}")
def get_public_property_record(property_id: int, db: Session = Depends(get_db)):
    """One DB-backed listing, only while publicly eligible (Phase 6).

    Unknown ids AND rows that exist but are unapproved or no longer available
    all return the same 404, so the API never reveals private inventory.
    """
    prop = get_public_record(db, property_id)
    if prop is None:
        raise HTTPException(status_code=404, detail="Property not found")
    return public_record_dict(prop)


# Dataset browse — a SEPARATE endpoint with its OWN id space
# (dataset property_id 1..25082, never properties.id). Registered BEFORE
# /api/properties/{property_id} so the literal "dataset" segment is never
# captured by the legacy dataset-detail route (same ordering rule as the
# "record" route above). The DB-backed GET /api/properties stays untouched:
# it continues to serve approved + available Lyka inventory only.
@app.get("/api/properties/dataset")
def browse_dataset_properties(
    location: Optional[str] = Query(None, max_length=120),
    property_type: Optional[str] = Query(None, max_length=60),
    min_price: Optional[float] = Query(None, ge=0),
    max_price: Optional[float] = Query(None, ge=0),
    min_bedrooms: Optional[int] = Query(None, ge=0, le=20),
    max_bedrooms: Optional[int] = Query(None, ge=0, le=20),
    purpose: Optional[Literal["sale", "rent", "lease"]] = None,
    limit: int = Query(24, ge=1, le=48),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Browse the UAE dataset with normalized, honest fields.

    When imported into Turso / SQLite, this endpoint queries the database
    with server-side filtering, pagination, and deterministic price ordering.
    If the database holds zero dataset rows, it falls back seamlessly to
    the local JSON dataset search.

    Separate from GET /api/properties (approved + available Lyka inventory):
    dataset rows are unverified reference data, never Lyka-approved listings,
    so the payload labels unknown governance fields as null and carries
    source="dataset".
    """
    if purpose is not None:
        raise HTTPException(
            status_code=422,
            detail=(
                "The dataset has no sale/rent purpose field, so a purpose "
                "filter cannot be applied. Use GET /api/properties for "
                "purpose-filtered Lyka inventory."
            ),
        )

    # 1. Check if database has imported dataset listings
    has_db_dataset = (
        db.query(func.count(Property.id))
        .filter(Property.source.in_(["uae_dataset", "dataset"]))
        .scalar()
        or 0
    )

    if has_db_dataset > 0:
        query = db.query(Property).filter(
            Property.source.in_(["uae_dataset", "dataset"])
        )
        if location:
            query = query.filter(
                func.lower(Property.location).like(f"%{location.strip().lower()}%")
            )
        if property_type:
            query = query.filter(
                func.lower(Property.property_type).like(f"%{property_type.strip().lower()}%")
            )
        if min_price is not None:
            query = query.filter(Property.price >= min_price)
        if max_price is not None:
            query = query.filter(Property.price <= max_price)
        if min_bedrooms is not None:
            query = query.filter(Property.bedrooms >= min_bedrooms)
        if max_bedrooms is not None:
            query = query.filter(Property.bedrooms <= max_bedrooms)

        total = query.count()
        rows = (
            query.order_by(Property.price.asc(), Property.id.asc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return {
            "results": [dataset_db_record_dict(p) for p in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    # 2. Fallback to bundled JSON when database has not yet been seeded with dataset rows
    result = search_properties(
        None,
        location=location,
        property_type=property_type,
        min_price=min_price,
        max_price=max_price,
        min_bedrooms=min_bedrooms,
        max_bedrooms=max_bedrooms,
        limit=limit,
        offset=offset,
    )
    return {
        "results": [dataset_browse_dict(p) for p in result["results"]],
        "total": result["total"],
        "limit": result["limit"],
        "offset": result["offset"],
    }


@app.get("/api/properties/{property_id}")
async def get_property(property_id: int, db: Session = Depends(get_db)):
    """Get a specific property by ID (checks database first, then dataset cache)."""
    # Check DB for dataset row by external_ref (UAE-<id>) or ID
    db_prop = (
        db.query(Property)
        .filter(
            (Property.external_ref == f"UAE-{property_id}")
            | (
                (Property.id == property_id)
                & Property.source.in_(["uae_dataset", "dataset"])
            )
        )
        .first()
    )
    if db_prop:
        return {
            "property_id": property_id,
            "price": f"{int(db_prop.price):,}" if db_prop.price else "",
            "property_type": db_prop.property_type,
            "no__of__beds": str(db_prop.bedrooms) if db_prop.bedrooms else "Studio",
            "no_of_baths": float(db_prop.bathrooms) if db_prop.bathrooms else 1.0,
            "area": f"{int(db_prop.area):,} sqft" if db_prop.area else "",
            "highlights": db_prop.highlights or db_prop.title,
            "location": db_prop.location,
        }

    prop = get_property_by_id(property_id)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    return prop


# ================================================================
# CUSTOMER ACCOUNTS (optional — guests chat with LykAI immediately)
# ================================================================

class CustomerRegister(BaseModel):
    email: str = Field(..., min_length=3, description="Account email")
    password: str = Field(..., min_length=6, description="At least 6 characters")
    confirm_password: Optional[str] = Field(
        None,
        description="Repeat of the password from the signup form; must match",
    )
    name: Optional[str] = Field(None, max_length=120)


class CustomerLogin(BaseModel):
    email: str = Field(..., min_length=3)
    password: str = Field(..., min_length=1)


class SavedPropertyIn(BaseModel):
    property_id: int
    # Which listing space property_id refers to. 'dataset' (default) keeps the
    # legacy behavior byte-for-byte; 'record' bookmarks a DB-backed listing
    # (stored in a reserved id range — see _SAVED_RECORD_ID_BASE below).
    source: Literal["dataset", "record"] = "dataset"


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
    _rl: None = Depends(rate_limit("auth", "AUTH_RATE_LIMIT")),
):
    """Create an optional customer account and link this guest's conversations."""
    # Signup form sends the confirm-password field back: reject a mismatch
    # server-side too (the frontend already validates it client-side).
    if payload.confirm_password is not None and payload.confirm_password != payload.password:
        raise HTTPException(status_code=422, detail="Passwords do not match")
    email = _normalize_email(payload.email)
    # Customer and staff identities are separate worlds: a staff account must
    # never be mirrored into the customer table (it once leaked into /history
    # as "Signed in as admin@lykarealty.ae").  Reserve staff emails outright.
    staff = db.query(Agent).filter(func.lower(Agent.email) == email).first()
    if staff is not None:
        raise HTTPException(
            status_code=422,
            detail="This email is reserved for Lyka Realty staff. Use a personal email address.",
        )
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
    _rl: None = Depends(rate_limit("auth", "AUTH_RATE_LIMIT")),
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
    auditlog.write_audit(
        db, auditlog.LOGIN_SUCCESS, actor_type="customer", actor_id=account.id,
        actor_label=account.email, ip=auditlog.client_ip(http_request),
    )
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


# ---------------------------------------------------------------------------
# Phase 6 — saved-property id-space encoding (documented convention, NO
# schema migration). `saved_properties.property_id` is a single INTEGER
# column shared by two id spaces:
#   - the UAE dataset (property_id 1..25,082) — legacy bookmarks, unchanged;
#   - DB-backed listing records (properties.id) — stored in a reserved high
#     range (_SAVED_RECORD_ID_BASE + id) so they can never collide with
#     dataset ids (the dataset's maximum id is far below the base).
# Rows are decoded on read; every legacy row keeps its exact stored value.
# ---------------------------------------------------------------------------
_SAVED_RECORD_ID_BASE = 1_000_000


def _saved_encode_record_id(record_id: int) -> int:
    return _SAVED_RECORD_ID_BASE + int(record_id)


def _saved_is_record_row(stored_property_id: int) -> bool:
    return stored_property_id >= _SAVED_RECORD_ID_BASE


@app.get("/api/customer/saved")
def customer_saved(
    db: Session = Depends(get_db),
    http_request: Request = None,
):
    """This customer's saved listings (real data only).

    Each result carries `source: "dataset" | "record"` so the frontend can
    route to the correct detail space. Rows that no longer resolve to a
    publicly eligible listing are skipped (same rule the dataset path always
    applied for ids missing from the dataset). Dataset dicts are copied
    before the marker is added — the cached dataset rows are never mutated.
    """
    customer = _require_account_customer(db, http_request)
    rows = (
        db.query(SavedProperty)
        .filter(SavedProperty.customer_id == customer.id)
        .order_by(SavedProperty.id.desc())
        .all()
    )
    record_ids = [
        r.property_id - _SAVED_RECORD_ID_BASE
        for r in rows
        if _saved_is_record_row(r.property_id)
    ]
    record_by_id = {
        # `property_id` mirrors the record id so saved results expose the
        # same key shape as dataset rows (SavedGrid and the detail page's
        # saved-state check compare on it uniformly).
        p.id: {**public_record_dict(p), "property_id": p.id, "source": "record"}
        for p in get_public_records(db, record_ids)
    }
    results = []
    for r in rows:
        if _saved_is_record_row(r.property_id):
            rec = record_by_id.get(r.property_id - _SAVED_RECORD_ID_BASE)
            if rec is not None:
                results.append(rec)
        else:
            row = get_property_by_id(r.property_id)
            if row is not None:
                results.append({**row, "source": "dataset"})
    return {"results": results, "total": len(results)}


@app.post("/api/customer/saved")
def customer_save(
    payload: SavedPropertyIn,
    db: Session = Depends(get_db),
    http_request: Request = None,
):
    """Bookmark a listing (idempotent — never creates duplicates).

    `source` selects the id space: 'dataset' (default, legacy behavior
    unchanged) or 'record' (DB-backed listing; must be publicly eligible —
    approved + available — or the save is rejected with 404).
    """
    customer = _require_account_customer(db, http_request)
    if payload.source == "record":
        if get_public_record(db, payload.property_id) is None:
            raise HTTPException(status_code=404, detail="Property not found")
        stored_id = _saved_encode_record_id(payload.property_id)
    else:
        prop = get_property_by_id(payload.property_id)
        if prop is None:
            raise HTTPException(status_code=404, detail="Property not found")
        stored_id = payload.property_id
    existing = (
        db.query(SavedProperty)
        .filter(
            SavedProperty.customer_id == customer.id,
            SavedProperty.property_id == stored_id,
        )
        .first()
    )
    if existing is None:
        db.add(SavedProperty(customer_id=customer.id, property_id=stored_id))
        db.commit()
    return {"saved": True, "property_id": payload.property_id, "source": payload.source}


@app.delete("/api/customer/saved/{property_id}")
def customer_unsave(
    property_id: int,
    source: Literal["dataset", "record"] = "dataset",
    db: Session = Depends(get_db),
    http_request: Request = None,
):
    """Remove a bookmark. `source` targets the id space, so unsaving a
    dataset id can never delete a record bookmark of the same number (and
    vice versa)."""
    customer = _require_account_customer(db, http_request)
    stored_id = (
        _saved_encode_record_id(property_id) if source == "record" else property_id
    )
    (
        db.query(SavedProperty)
        .filter(
            SavedProperty.customer_id == customer.id,
            SavedProperty.property_id == stored_id,
        )
        .delete()
    )
    db.commit()
    return {"saved": False, "property_id": property_id, "source": source}


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
    request: Request = None,
    _rl: None = Depends(rate_limit("auth", "AUTH_RATE_LIMIT")),
):
    """Authenticate an agent (email OR username + password).

    On success sets an httpOnly session cookie and returns the token once for
    API clients that prefer `Authorization: Bearer <token>`. The response also
    carries the identity's roles, permissions and post-login landing route so
    the global portal can route without a second round-trip.
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
    # Same generic error for unknown user, wrong password AND a locked account
    # (no user probing, no lock-detection oracle).
    generic = HTTPException(status_code=401, detail="Invalid username or password")
    if agent is None:
        # Unknown identifier: nothing to track (no row exists).
        auditlog.write_audit(
            db, auditlog.LOGIN_FAILURE, actor_type="staff",
            actor_label=identifier[:255], ip=auditlog.client_ip(request),
            detail="bad_credentials",
        )
        raise generic
    if _is_locked(agent):
        auditlog.write_audit(
            db, auditlog.LOGIN_FAILURE, actor_type="staff", actor_id=agent.id,
            actor_label=agent.email, ip=auditlog.client_ip(request),
            detail="locked_out",
        )
        raise generic
    if not agent.is_active or not verify_password(payload.password, agent.password_hash):
        record_login_failure(db, agent)
        auditlog.write_audit(
            db, auditlog.LOGIN_FAILURE, actor_type="staff", actor_id=agent.id,
            actor_label=agent.email, ip=auditlog.client_ip(request),
            detail="bad_credentials",
        )
        raise generic

    record_login_success(db, agent)
    token = create_session(db, agent)
    set_agent_cookie(response, token)
    # Resolve the full role/permission set for the portal payload.
    cache_permissions(db, agent)
    role_keys = roles_of(agent)
    auditlog.write_audit(
        db, auditlog.LOGIN_SUCCESS, actor_type="staff", actor_id=agent.id,
        actor_label=agent.email, ip=auditlog.client_ip(request),
        detail=f"roles={','.join(role_keys)}",
    )
    return {
        "agent": _agent_public(agent),
        "token": token,
        "token_type": "bearer",
        "roles": rbac.public_role_view(role_keys),
        "permissions": sorted(permissions_of(agent)),
        "landing": rbac.landing_for_roles(role_keys),
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
        auditlog.write_audit(
            db, auditlog.LOGOUT, actor_type="staff",
            ip=auditlog.client_ip(request),
        )
    clear_agent_cookie(response)
    return {"ok": True}


@app.get("/api/auth/me")
def auth_me(agent: Agent = Depends(get_current_agent)):
    """Who am I? 401 when unauthenticated — used for route guarding."""
    return {"agent": _agent_public(agent)}


@app.get("/api/auth/session")
def auth_session(
    request: Request,
    db: Session = Depends(get_db),
):
    """Unified session resolver for the GLOBAL PORTAL (Phase 3).

    Returns whichever identity the browser currently holds — a STAFF session
    (``lyka_agent_session``) or a CUSTOMER session (``lyka_customer``) — plus
    that identity's roles, permissions and post-login landing route. This is
    the single endpoint the frontend AuthContext polls to know "who am I?".

    Never raises for the anonymous case: returns ``{authenticated:false}`` so
    a logged-out visitor sees the portal, not an error. Authorization itself
    is still enforced per-request on every protected route (defence in depth).
    """
    # ---- staff first (a staff cookie is the more privileged identity) ----
    staff_token = request.cookies.get(AGENT_COOKIE)
    if staff_token:
        try:
            agent = get_current_agent(request, db)
        except HTTPException:
            agent = None  # expired/revoked/disabled — fall through to customer
        if agent is not None:
            role_keys = roles_of(agent)
            return {
                "authenticated": True,
                "kind": "staff",
                "identity": _agent_public(agent),
                "roles": rbac.public_role_view(role_keys),
                "permissions": sorted(permissions_of(agent)),
                "landing": rbac.landing_for_roles(role_keys),
                "module": rbac.module_for_roles(role_keys),
            }
    # ---- customer (registered account or guest) ----
    customer = find_visitor_customer(db, request)
    if customer is not None and customer.is_account:
        return {
            "authenticated": True,
            "kind": "customer",
            "identity": _customer_public(customer),
            "roles": rbac.public_role_view([rbac.CUSTOMER_ROLE]),
            "permissions": sorted(rbac.ROLE_REGISTRY[rbac.CUSTOMER_ROLE].permissions),
            "landing": rbac.CUSTOMER_LANDING,
            "module": "customer",
        }
    return {"authenticated": False, "kind": None, "landing": rbac.CUSTOMER_LANDING}


class PortalLoginRequest(BaseModel):
    identifier: str = Field(..., min_length=1, description="Email or username")
    password: str = Field(..., min_length=1)


@app.post("/api/auth/portal-login")
def auth_portal_login(
    payload: PortalLoginRequest,
    db: Session = Depends(get_db),
    request: Request = None,
    response: Response = None,
    _rl: None = Depends(rate_limit("auth", "AUTH_RATE_LIMIT")),
):
    """Unified sign-in for the GLOBAL PORTAL (Phase 3).

    One form, one endpoint: resolves the credential against the STAFF world
    (agents: email or username) first, then the CUSTOMER world (email). Whichever
    identity matches gets its own session cookie; the response says which ``kind``
    signed in plus that identity's roles, permissions and landing route.

    The client supplies NO role — identity, roles and permissions come entirely
    from the server-side database row. A wrong password and an unknown identifier
    return the identical generic 401 (no account probing). Lockout and audit are
    enforced for the staff world; customers reuse the plain login path.
    """
    identifier = (payload.identifier or "").strip().lower()
    generic = HTTPException(status_code=401, detail="Invalid email or password")

    # ---------------- staff world ----------------
    agent = (
        db.query(Agent)
        .filter(
            (func.lower(Agent.email) == identifier)
            | (func.lower(Agent.username) == identifier)
        )
        .first()
    )
    if agent is not None:
        if _is_locked(agent):
            auditlog.write_audit(
                db, auditlog.LOGIN_FAILURE, actor_type="staff", actor_id=agent.id,
                actor_label=agent.email, ip=auditlog.client_ip(request),
                detail="locked_out",
            )
            raise generic
        if agent.is_active and verify_password(payload.password, agent.password_hash):
            record_login_success(db, agent)
            token = create_session(db, agent)
            set_agent_cookie(response, token)
            cache_permissions(db, agent)
            role_keys = roles_of(agent)
            auditlog.write_audit(
                db, auditlog.LOGIN_SUCCESS, actor_type="staff", actor_id=agent.id,
                actor_label=agent.email, ip=auditlog.client_ip(request),
                detail=f"roles={','.join(role_keys)}",
            )
            return {
                "authenticated": True,
                "kind": "staff",
                "identity": _agent_public(agent),
                "roles": rbac.public_role_view(role_keys),
                "permissions": sorted(permissions_of(agent)),
                "landing": rbac.landing_for_roles(role_keys),
                "module": rbac.module_for_roles(role_keys),
                "token": token,
                "token_type": "bearer",
            }
        # Wrong password / inactive on a KNOWN staff account → track + generic.
        if agent.is_active:
            record_login_failure(db, agent)
        auditlog.write_audit(
            db, auditlog.LOGIN_FAILURE, actor_type="staff", actor_id=agent.id,
            actor_label=agent.email, ip=auditlog.client_ip(request),
            detail="bad_credentials",
        )
        raise generic

    # ---------------- customer world ----------------
    # Only accounts (password_hash set) can sign in; guests have no password.
    account = (
        db.query(Customer)
        .filter(Customer.password_hash.isnot(None), Customer.email == identifier)
        .first()
    )
    if account is not None and verify_password(payload.password, account.password_hash):
        current = find_visitor_customer(db, request) if request else None
        if current is not None and not current.is_account and current.id != account.id:
            claim_guest_conversations(db, current, account)
        token = reissue_customer_token(db, account)
        if response is not None:
            set_customer_cookie(response, token, max_age_days=30)
        auditlog.write_audit(
            db, auditlog.LOGIN_SUCCESS, actor_type="customer", actor_id=account.id,
            actor_label=account.email, ip=auditlog.client_ip(request),
        )
        return {
            "authenticated": True,
            "kind": "customer",
            "identity": _customer_public(account),
            "roles": rbac.public_role_view([rbac.CUSTOMER_ROLE]),
            "permissions": sorted(rbac.ROLE_REGISTRY[rbac.CUSTOMER_ROLE].permissions),
            "landing": rbac.CUSTOMER_LANDING,
            "module": "customer",
        }

    # Unknown in BOTH worlds (or wrong customer password) → one generic error.
    auditlog.write_audit(
        db, auditlog.LOGIN_FAILURE, actor_type="system",
        actor_label=identifier[:255], ip=auditlog.client_ip(request),
        detail="bad_credentials",
    )
    raise generic


# ================================================================
# ADMIN: user provisioning, role management, audit (Phase 5 & 6)
# ================================================================
# Every route below is gated by PERMISSIONS (server-side), never by a client
# -supplied role. High-impact changes (role grant/revoke, suspend, password
# reset) additionally require the acting admin to re-enter their OWN password
# (step-up reauthentication) and revoke the target's sessions so an already-open
# browser loses access immediately.

class StaffCreateRequest(BaseModel):
    email: str = Field(..., min_length=5)
    username: str = Field(..., min_length=2)
    full_name: str = Field(..., min_length=1, max_length=120)
    password: str = Field(..., min_length=8)
    role: str = Field(..., description="Primary role key from the registry")


class RoleChangeRequest(BaseModel):
    role: str = Field(..., description="New PRIMARY role key")
    current_password: str = Field(
        ..., min_length=1, description="Acting admin's password (step-up check)"
    )


class SuspendRequest(BaseModel):
    suspend: bool = Field(..., description="true = suspend, false = reactivate")
    current_password: str = Field(..., min_length=1)


class PasswordResetRequest(BaseModel):
    new_password: str = Field(..., min_length=8)
    current_password: str = Field(..., min_length=1)


def _staff_public(agent: Agent, role_keys) -> dict:
    """Safe staff representation (never includes password_hash or tokens)."""
    return {
        "id": agent.id,
        "email": agent.email,
        "username": agent.username,
        "full_name": agent.full_name,
        "is_active": agent.is_active,
        "role": agent.role,
        "roles": rbac.public_role_view(role_keys),
        "last_login_at": agent.last_login_at.isoformat() if agent.last_login_at else None,
        "locked_until": agent.locked_until.isoformat() if agent.locked_until else None,
        "created_at": agent.created_at.isoformat() if agent.created_at else None,
    }


def _require_step_up(db: Session, actor: Agent, current_password: str) -> None:
    """Reauthenticate the acting admin before a high-impact change."""
    if not verify_password(current_password or "", actor.password_hash):
        raise HTTPException(
            status_code=403,
            detail="Password confirmation required for this action",
        )


def _count_active_admins(db: Session, exclude_id: int = None) -> int:
    """Active staff holding the `admin` role (primary or extra)."""
    admins = db.query(Agent).filter(Agent.is_active.is_(True)).all()
    n = 0
    for a in admins:
        if exclude_id is not None and a.id == exclude_id:
            continue
        if "admin" in load_role_keys(db, a):
            n += 1
    return n


@app.get("/api/admin/users")
def admin_list_users(
    db: Session = Depends(get_db),
    admin: Agent = Depends(require_permissions("users.read")),
):
    """List all staff accounts with their effective roles (users.read)."""
    rows = db.query(Agent).order_by(Agent.id.asc()).all()
    return {
        "total": len(rows),
        "results": [_staff_public(a, load_role_keys(db, a)) for a in rows],
    }


@app.get("/api/admin/roles")
def admin_list_roles(
    admin: Agent = Depends(require_permissions("roles.read", "users.read", mode="any")),
):
    """The role registry (keys, display names, module status). No secrets."""
    return {
        "roles": [
            {
                "key": spec.key,
                "display_name": spec.display_name,
                "description": spec.description,
                "landing": spec.landing,
                "module": spec.module,
                "permission_count": len(spec.permissions),
            }
            for spec in sorted(rbac.ROLE_REGISTRY.values(), key=lambda s: s.priority)
        ],
        "permissions": [
            {"key": p.key, "description": p.description}
            for p in sorted(rbac.PERMISSIONS.values(), key=lambda p: p.key)
        ],
    }


@app.post("/api/admin/users")
def admin_create_user(
    payload: StaffCreateRequest,
    db: Session = Depends(get_db),
    request: Request = None,
    admin: Agent = Depends(require_permissions("users.create")),
):
    """Create a STAFF account (users.create). Public registration can never
    reach this route — it lives behind the permission and only ever writes to
    the `agents` table, never `customers`.
    """
    if not rbac.is_known_role(payload.role) or payload.role == rbac.CUSTOMER_ROLE:
        raise HTTPException(status_code=422, detail="Unknown role")
    email = payload.email.strip().lower()
    username = payload.username.strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=422, detail="Enter a valid email address")
    if db.query(Agent).filter(func.lower(Agent.email) == email).first():
        raise HTTPException(status_code=409, detail="An account with this email exists")
    if db.query(Agent).filter(func.lower(Agent.username) == username).first():
        raise HTTPException(status_code=409, detail="This username is taken")

    primary = rbac.normalize_role(payload.role)
    agent = Agent(
        email=email,
        username=username,
        full_name=payload.full_name.strip(),
        password_hash=hash_password(payload.password),
        role=primary,
        is_active=True,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    auditlog.write_audit(
        db, auditlog.USER_CREATED, actor_type="staff", actor_id=admin.id,
        actor_label=admin.email, subject_type="staff", subject_id=agent.id,
        subject_label=agent.email, ip=auditlog.client_ip(request),
        detail=f"role={primary}",
    )
    return {"user": _staff_public(agent, load_role_keys(db, agent))}


@app.patch("/api/admin/users/{user_id}/role")
def admin_change_role(
    user_id: int,
    payload: RoleChangeRequest,
    db: Session = Depends(get_db),
    request: Request = None,
    admin: Agent = Depends(require_permissions("roles.manage")),
):
    """Change a staff member's PRIMARY role (roles.manage + step-up).

    Extra roles are unaffected. The target's sessions are revoked so the change
    takes effect on their next request, not at TTL. The LAST active admin can
    never be demoted.
    """
    _require_step_up(db, admin, payload.current_password)
    target = db.query(Agent).filter(Agent.id == user_id).first()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    new_role = rbac.normalize_role(payload.role)
    if new_role is None or new_role == rbac.CUSTOMER_ROLE:
        raise HTTPException(status_code=422, detail="Unknown role")

    old_role = target.role
    # Last-admin protection: demoting the only admin would lock everyone out.
    if old_role == "admin" and new_role != "admin":
        if "admin" in load_role_keys(db, target) and _count_active_admins(db, target.id) == 0:
            raise HTTPException(
                status_code=409,
                detail="Cannot demote the last active administrator",
            )

    target.role = new_role
    db.add(target)
    db.commit()
    revoked = revoke_all_sessions(db, target.id)
    auditlog.write_audit(
        db, auditlog.ROLE_GRANTED, actor_type="staff", actor_id=admin.id,
        actor_label=admin.email, subject_type="staff", subject_id=target.id,
        subject_label=target.email, ip=auditlog.client_ip(request),
        detail=f"{old_role}->{new_role}; revoked {revoked} session(s)",
    )
    return {"user": _staff_public(target, load_role_keys(db, target))}


@app.post("/api/admin/users/{user_id}/roles/{role_key}")
def admin_grant_role(
    user_id: int,
    role_key: str,
    db: Session = Depends(get_db),
    request: Request = None,
    admin: Agent = Depends(require_permissions("roles.manage")),
):
    """Grant an EXTRA role (roles.manage + step-up). Additive; the primary role
    in `agents.role` is untouched, so the user keeps working unchanged."""
    target = db.query(Agent).filter(Agent.id == user_id).first()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    key = rbac.normalize_role(role_key)
    if key is None or key == rbac.CUSTOMER_ROLE:
        raise HTTPException(status_code=422, detail="Unknown role")
    exists = (
        db.query(AgentRole).filter(
            AgentRole.agent_id == target.id, AgentRole.role_key == key
        ).first()
    )
    if exists is None:
        db.add(AgentRole(agent_id=target.id, role_key=key))
        db.commit()
    auditlog.write_audit(
        db, auditlog.ROLE_GRANTED, actor_type="staff", actor_id=admin.id,
        actor_label=admin.email, subject_type="staff", subject_id=target.id,
        subject_label=target.email, ip=auditlog.client_ip(request),
        detail=f"extra role {key}",
    )
    return {"user": _staff_public(target, load_role_keys(db, target))}


@app.delete("/api/admin/users/{user_id}/roles/{role_key}")
def admin_revoke_role(
    user_id: int,
    role_key: str,
    db: Session = Depends(get_db),
    request: Request = None,
    admin: Agent = Depends(require_permissions("roles.manage")),
):
    """Revoke an EXTRA role (roles.manage + step-up). The primary role cannot
    be revoked here — use the role-change endpoint."""
    target = db.query(Agent).filter(Agent.id == user_id).first()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    key = rbac.normalize_role(role_key)
    if key is None:
        raise HTTPException(status_code=422, detail="Unknown role")
    if key == rbac.normalize_role(target.role):
        raise HTTPException(
            status_code=409,
            detail="This is the primary role — change it instead of revoking",
        )
    db.query(AgentRole).filter(
        AgentRole.agent_id == target.id, AgentRole.role_key == key
    ).delete(synchronize_session=False)
    db.commit()
    auditlog.write_audit(
        db, auditlog.ROLE_REVOKED, actor_type="staff", actor_id=admin.id,
        actor_label=admin.email, subject_type="staff", subject_id=target.id,
        subject_label=target.email, ip=auditlog.client_ip(request),
        detail=f"revoked extra role {key}",
    )
    return {"user": _staff_public(target, load_role_keys(db, target))}


@app.post("/api/admin/users/{user_id}/suspend")
def admin_suspend_user(
    user_id: int,
    payload: SuspendRequest,
    db: Session = Depends(get_db),
    request: Request = None,
    admin: Agent = Depends(require_permissions("users.suspend")),
):
    """Suspend or reactivate a staff account (users.suspend + step-up).

    Suspending revokes every live session immediately. The LAST active admin
    cannot be suspended. An admin cannot suspend their OWN account."""
    _require_step_up(db, admin, payload.current_password)
    target = db.query(Agent).filter(Agent.id == user_id).first()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    if target.id == admin.id:
        raise HTTPException(status_code=409, detail="You cannot suspend your own account")

    if payload.suspend:
        if "admin" in load_role_keys(db, target) and _count_active_admins(db, target.id) == 0:
            raise HTTPException(
                status_code=409,
                detail="Cannot suspend the last active administrator",
            )
        target.is_active = False
        event = auditlog.ACCOUNT_SUSPENDED
        detail = "suspended"
    else:
        target.is_active = True
        target.failed_login_count = 0
        target.locked_until = None
        event = auditlog.ACCOUNT_REACTIVATED
        detail = "reactivated"

    db.add(target)
    db.commit()
    revoked = revoke_all_sessions(db, target.id) if payload.suspend else 0
    auditlog.write_audit(
        db, event, actor_type="staff", actor_id=admin.id, actor_label=admin.email,
        subject_type="staff", subject_id=target.id, subject_label=target.email,
        ip=auditlog.client_ip(request), detail=f"{detail}; revoked {revoked}",
    )
    return {"user": _staff_public(target, load_role_keys(db, target))}


@app.post("/api/admin/users/{user_id}/reset-password")
def admin_reset_password(
    user_id: int,
    payload: PasswordResetRequest,
    db: Session = Depends(get_db),
    request: Request = None,
    admin: Agent = Depends(require_permissions("users.update")),
):
    """Administratively reset a staff password (users.update + step-up).

    Revokes the target's sessions. This is the ONLY supported recovery path —
    there is no self-service email reset (no mail transport is configured, and
    faking one would be dishonest)."""
    _require_step_up(db, admin, payload.current_password)
    target = db.query(Agent).filter(Agent.id == user_id).first()
    if target is None:
        raise HTTPException(status_code=404, detail="User not found")
    target.password_hash = hash_password(payload.new_password)
    target.failed_login_count = 0
    target.locked_until = None
    db.add(target)
    db.commit()
    revoked = revoke_all_sessions(db, target.id)
    auditlog.write_audit(
        db, auditlog.PASSWORD_RESET, actor_type="staff", actor_id=admin.id,
        actor_label=admin.email, subject_type="staff", subject_id=target.id,
        subject_label=target.email, ip=auditlog.client_ip(request),
        detail=f"reset; revoked {revoked} session(s)",
    )
    return {"ok": True, "revoked_sessions": revoked}


@app.get("/api/audit/log")
def audit_read(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    event: Optional[str] = Query(None, description="Filter by exact event name"),
    db: Session = Depends(get_db),
    admin: Agent = Depends(require_permissions("audit.read")),
):
    """Read the security audit log (audit.read only). Append-only upstream: no
    application route can modify or delete these rows."""
    q = db.query(AuditLog)
    if event:
        q = q.filter(AuditLog.event == event)
    total = q.count()
    rows = (
        q.order_by(AuditLog.id.desc()).offset(offset).limit(limit).all()
    )
    auditlog.write_audit(
        db, auditlog.AUDIT_READ, actor_type="staff", actor_id=admin.id,
        actor_label=admin.email, detail=f"limit={limit}",
    )
    return {
        "total": total,
        "results": [
            {
                "id": r.id,
                "event": r.event,
                "actor_type": r.actor_type,
                "actor_id": r.actor_id,
                "actor_label": r.actor_label,
                "subject_type": r.subject_type,
                "subject_id": r.subject_id,
                "subject_label": r.subject_label,
                "ip": r.ip,
                "detail": r.detail,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


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
    """Conversations visible to this agent (permission-scoped).

    - holds ``conversations.read_all`` (admin, sales manager) → every conversation
    - otherwise → conversations attached to leads in their scope
      (assigned to them, or unassigned in the shared pool)
    """
    q = db.query(Conversation)
    if not rbac.has_permission(agent, "conversations.read_all"):
        rows = scoped_lead_query(db, agent).with_entities(Lead.id).all()
        scoped_lead_ids = [r[0] for r in rows]
        if not scoped_lead_ids:
            return q.filter(Conversation.id.is_(None))
        q = q.filter(Conversation.lead_id.in_(scoped_lead_ids))
    return q


def _conversation_linkable(db: Session, agent: Agent, conversation: Conversation):
    """May this agent attach this conversation to a lead?

    Same visibility rule as `_scoped_conversations`, plus unlinked
    conversations (`lead_id IS NULL`): those are the conversation-side
    equivalent of the unassigned pickup pool, so any staff agent may claim
    one for a new lead. Returns the conversation or None (404 by caller).
    """
    if rbac.has_permission(agent, "conversations.read_all"):
        return conversation
    if conversation.lead_id is None:
        return conversation
    allowed = _scoped_conversations(db, agent).filter(
        Conversation.id == conversation.id).first()
    return allowed


def _resolve_customer(db: Session, customer_id: int) -> Customer:
    """Customer must exist; 422 (not 404) — this is a validation failure."""
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if customer is None:
        raise HTTPException(status_code=422, detail="Unknown customer reference")
    return customer


def _resolve_agent(db: Session, agent: Agent, target_id: int) -> int:
    """Assignment target must be an active agent the caller may assign to."""
    target = db.query(Agent).filter(Agent.id == target_id).first()
    if target is None or not target.is_active:
        raise HTTPException(status_code=422, detail="Unknown agent reference")
    # Only holders of leads.assign may assign to someone ELSE; everyone may
    # always assign/claim for themselves.
    if target.id != agent.id and not rbac.has_permission(agent, "leads.assign"):
        raise HTTPException(
            status_code=403, detail="Only administrators may assign other agents")
    return target.id


def _score_payload(result) -> dict:
    """LeadScoreResult → API dict (server-computed, never client-supplied)."""
    return {
        "total_score": result.total_score,
        "priority": result.priority,
        "breakdown": [c.model_dump() for c in result.breakdown],
    }


def _json_maybe(raw):
    """JSON text column → Python value; unreadable/absent → None."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


@app.get("/api/agent/dashboard")
def agent_dashboard(
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """CRM home: real DB metrics + recent leads + recent conversations.

    Counts come from grouped SQL over the agent's data scope (never
    hardcoded demo numbers): status counts, priority counts (NULL = never
    scored, reported as "unscored"), and pending follow-up buckets
    (UTC calendar days — overdue / due today / upcoming).
    """
    stats = dashboard_stats(db, agent)

    recent_leads = (
        scoped_lead_query(db, agent)
        .order_by(
            func.coalesce(Lead.last_interaction_at, Lead.updated_at,
                          Lead.created_at).desc(),
            Lead.id.desc(),
        )
        .limit(8)
        .all()
    )

    conv_rows = (
        _scoped_conversations(db, agent)
        .order_by(Conversation.updated_at.desc())
        .limit(8)
        .all()
    )
    recent_conversations = [_conversation_row(c) for c in conv_rows]

    return {
        "agent": _agent_public(agent),
        "counts": stats["counts"],
        "priority": stats["priority"],
        "follow_ups": stats["follow_ups"],
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


@app.post("/api/agent/leads")
def agent_create_lead(
    payload: LeadCreate,
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """Create a lead from REVIEWED, explicitly-confirmed details (staff only).

    Deliberate workflow — no OpenAI call happens here (the agent already
    reviewed/edited the extraction): validate → conservative duplicate check
    (409 unless duplicate_override) → validate referenced records → build
    Lead → deterministic server-side score → link conversation → one commit.
    Any failure rolls the transaction back — never a partial lead. Scores
    are always computed by `lead_scoring`; a client-supplied score is
    impossible (LeadCreate has no score field, extras are ignored).
    """
    if not payload.confirm:
        raise HTTPException(status_code=422, detail=(
            "Explicit confirmation of the reviewed details is required "
            "(set confirm=true after reviewing them)"))
    if (payload.budget_min is not None and payload.budget_max is not None
            and payload.budget_min > payload.budget_max):
        raise HTTPException(status_code=422,
                            detail="budget_min cannot exceed budget_max")

    # ---- conservative duplicate policy: phone first, then email ----
    # (name-only similarity never matches). Possible duplicates are surfaced
    # for an explicit decision — existing requirements are never overwritten.
    dup, matched_by = find_duplicate(db, payload.phone, payload.email)
    if dup is not None and not payload.duplicate_override:
        in_scope = lead_in_scope(agent, dup)
        raise HTTPException(status_code=409, detail={
            "message": (f"A possible duplicate lead already exists (matched by "
                        f"{matched_by}). Open it to review or update it, or "
                        f"resubmit with duplicate_override=true to keep a "
                        f"separate lead."),
            "code": "duplicate_lead",
            "matched_by": matched_by,
            # ID only when the caller may actually open it (no leaks)
            "lead_id": dup.id if in_scope else None,
            "in_scope": in_scope,
        })

    # ---- referenced records ----
    conversation = None
    if payload.conversation_id is not None:
        conversation = db.query(Conversation).filter(
            Conversation.id == payload.conversation_id).first()
        if (conversation is None
                or _conversation_linkable(db, agent, conversation) is None):
            raise HTTPException(status_code=404, detail="Conversation not found")
        if conversation.lead_id is not None:
            raise HTTPException(status_code=409, detail={
                "message": "That conversation is already linked to another lead",
                "code": "conversation_linked",
                "lead_id": conversation.lead_id,
            })
    if payload.customer_id is not None:
        customer = _resolve_customer(db, payload.customer_id)
        if (conversation is not None and conversation.customer_id is not None
                and conversation.customer_id != customer.id):
            raise HTTPException(status_code=422, detail=(
                "The selected conversation belongs to a different customer"))

    assigned_id = (_resolve_agent(db, agent, payload.assigned_agent_id)
                   if payload.assigned_agent_id is not None else None)

    # extraction_source derives from the reviewed provenance (deterministic)
    claims = {v for v in payload.provenance.values()
              if v in ("explicit", "inferred")}
    extraction_source = ("explicit" if claims in (set(), {"explicit"})
                         else "inferred" if claims == {"inferred"} else "mixed")
    budget_currency = (payload.budget_currency.upper()
                       if payload.budget_currency else None)

    try:
        lead = Lead(
            name=(payload.name or "").strip() or None,
            phone=(payload.phone or "").strip() or None,
            email=(payload.email or "").strip() or None,
            buy_rent=payload.intent,
            original_enquiry=(payload.original_enquiry or "").strip() or None,
            location=(payload.location or "").strip() or None,
            property_type=(payload.property_type or "").strip() or None,
            bedrooms=payload.bedrooms,
            bathrooms=payload.bathrooms,
            budget_min=payload.budget_min,
            budget_max=payload.budget_max,
            budget_currency=budget_currency,
            budget=encode_budget_display(budget_currency, payload.budget_min,
                                         payload.budget_max,
                                         payload.budget_period),
            amenities=json.dumps(payload.amenities, ensure_ascii=False),
            requirements=encode_preferences(payload.preferences),
            timeline=(payload.timeline or "").strip() or None,
            timeline_days=payload.timeline_days,
            status=payload.status,
            notes=(payload.notes or "").strip() or None,
            source="Agent CRM",
            extraction_source=extraction_source,
            assigned_agent_id=assigned_id,
            last_interaction_at=datetime.utcnow() if conversation else None,
        )
        db.add(lead)
        db.flush()  # assigns lead.id; still fully rollback-able
        score = recompute_lead_score(lead)
        if conversation is not None:
            if conversation.customer_id is None and payload.customer_id is not None:
                conversation.customer_id = payload.customer_id
            conversation.lead_id = lead.id
            # adopt any conversation recommendations not yet tied to a lead
            db.query(PropertyRecommendation).filter(
                PropertyRecommendation.conversation_id == conversation.id,
                PropertyRecommendation.lead_id.is_(None),
            ).update({"lead_id": lead.id}, synchronize_session=False)
        db.commit()
    except Exception as exc:  # noqa: BLE001 — boundary: rollback, log class only
        db.rollback()
        logger.error("lead create failed: %s", type(exc).__name__)  # no PII
        raise HTTPException(status_code=500, detail="Lead could not be saved")
    db.refresh(lead)
    return {
        "lead": lead_detail(lead),
        "score": _score_payload(score),
        "duplicate": ({"lead_id": dup.id, "matched_by": matched_by}
                      if dup is not None else None),
    }


@app.get("/api/agent/leads")
def agent_list_leads(
    status: Optional[StatusLiteral] = None,
    priority: Optional[Literal["high", "medium", "low", "unscored"]] = None,
    intent: Optional[str] = Query(
        None, description="buy|rent|lease|unknown", pattern="^(buy|rent|lease|unknown)$"),
    location: Optional[str] = None,
    property_type: Optional[str] = None,
    assigned_agent_id: Optional[int] = None,
    follow_up: Optional[Literal[
        "pending", "overdue", "due_today", "upcoming", "completed"]] = None,
    q: Optional[str] = None,
    sort: Optional[str] = Query("newest", pattern="^(newest|interaction)$"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """Lead list: search + validated filters + stable deterministic order.

    Scoped: agents only ever receive their own + unassigned leads (the
    server re-applies the scope to every query — it never trusts the UI).
    `follow_up=overdue|due_today|upcoming|pending|completed` selects leads
    with at least one follow-up in that bucket (UTC day boundaries).
    """
    query = scoped_lead_query(db, agent)

    if status:
        query = query.filter(Lead.status == status)
    if priority == "unscored":
        query = query.filter(Lead.priority.is_(None))
    elif priority:
        query = query.filter(Lead.priority == priority)
    if intent:
        query = query.filter(Lead.buy_rent == intent)
    if location:
        query = query.filter(Lead.location.ilike(f"%{location}%"))
    if property_type:
        query = query.filter(Lead.property_type.ilike(f"%{property_type}%"))
    if assigned_agent_id is not None:
        query = query.filter(Lead.assigned_agent_id == assigned_agent_id)
    if follow_up:
        # leads with >= 1 follow-up in the requested bucket (single EXISTS)
        fuq = filter_followups(
            db.query(FollowUp.id).filter(FollowUp.lead_id == Lead.id),
            follow_up)
        query = query.filter(fuq.exists())
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
            Lead.id.desc(),  # stable tiebreak → deterministic pagination
        )
    else:
        query = query.order_by(Lead.created_at.desc(), Lead.id.desc())

    leads = query.offset(offset).limit(limit).all()
    return {"total": total, "results": [lead_summary(l) for l in leads]}


@app.get("/api/agent/leads/{lead_id}")
def agent_get_lead(
    lead_id: int,
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """Full lead detail: profile, every AI conversation, all recommendations.

    Includes the Phase 5 review fields (score/priority/breakdown, missing
    fields, follow-ups) via `lead_detail`, plus the linked customer account
    (resolved through the linked conversation — `leads` has no customer FK).
    """
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

    # Linked customer account (only through this lead's own conversations)
    customer_account = None
    customer_ids = sorted({c.customer_id for c in conversations
                           if c.customer_id is not None})
    if customer_ids:
        cust = db.query(Customer).filter(Customer.id == customer_ids[0]).first()
        if cust is not None:
            customer_account = {"id": cust.id, "name": cust.name,
                                "email": cust.email}

    return {
        "lead": lead_detail(lead),
        "customer_account": customer_account,
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
                "id": r.id,
                "lead_id": r.lead_id,
                "property_id": r.property_id,
                # Phase 2 columns (NULL for dataset-era conversation rows)
                "property_record_id": r.property_record_id,
                "match_score": r.match_score,
                "match_reasons": _json_maybe(r.match_reasons),
                "match_mismatches": _json_maybe(r.match_mismatches),
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
    """Partial update: contact/requirement fields, assignment, status.

    - Score & priority are RECOMPUTED server-side whenever requirement
      fields change; a client-supplied score is never accepted (LeadUpdate
    has no score field).
    - `conversation_id` is validated: a new link must be visible to the
      caller and unlinked (or already this lead's); explicit null unlinks.
    - Unrelated fields stay untouched; every failure happens before commit.
    """
    lead = _scoped_lead_or_404(db, agent, lead_id)
    fields = update.model_dump(exclude_unset=True)

    # --- validations (all before any mutation) ---
    if "status" in fields and fields["status"] is not None:
        if fields["status"] not in LEAD_STATUSES:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid status. Allowed: {', '.join(sorted(LEAD_STATUSES))}",
            )
    if "buy_rent" in fields and fields["buy_rent"] is not None:
        if fields["buy_rent"] not in INTENTS:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid intent. Allowed: {', '.join(sorted(INTENTS))}",
            )
    if "budget_currency" in fields and fields["budget_currency"] is not None:
        cur = fields["budget_currency"].strip().upper()
        if cur and (len(cur) != 3 or not cur.isalpha()):
            raise HTTPException(status_code=422,
                                detail="budget_currency must be a 3-letter code")
        fields["budget_currency"] = cur or None
    if "amenities" in fields and fields["amenities"] is not None:
        fields["amenities"] = json.dumps(fields["amenities"], ensure_ascii=False)

    # Assignment rules (permission-based access control)
    if "assigned_agent_id" in fields:
        target = fields["assigned_agent_id"]
        if target is not None:
            target_agent = db.query(Agent).filter(Agent.id == target).first()
            if target_agent is None or not target_agent.is_active:
                raise HTTPException(status_code=422, detail="Unknown agent")
            # Only leads.assign holders may assign to another agent; anyone may
            # always assign to themselves.
            if target != agent.id and not rbac.has_permission(agent, "leads.assign"):
                raise HTTPException(
                    status_code=403,
                    detail="Only an admin can assign leads to another agent",
                )

    # Budget min/max must stay consistent on the MERGED result
    new_min = fields.get("budget_min", lead.budget_min)
    new_max = fields.get("budget_max", lead.budget_max)
    if new_min is not None and new_max is not None and new_min > new_max:
        raise HTTPException(status_code=422,
                            detail="budget_min cannot exceed budget_max")

    # --- Phase 5 specials (keys that are not plain Lead columns) ---
    _MISSING = object()
    budget_period = fields.pop("budget_period", _MISSING)   # None = clear period
    preferences = fields.pop("preferences", _MISSING)
    conversation_id = fields.pop("conversation_id", _MISSING)

    if conversation_id is not _MISSING:
        if conversation_id is None:
            for conv in list(lead.conversations):
                conv.lead_id = None
        else:
            conv = db.query(Conversation).filter(
                Conversation.id == conversation_id).first()
            if conv is None or _conversation_linkable(db, agent, conv) is None:
                raise HTTPException(status_code=404,
                                    detail="Conversation not found")
            if conv.lead_id is not None and conv.lead_id != lead.id:
                raise HTTPException(status_code=409, detail={
                    "message": "That conversation is already linked to another lead",
                    "code": "conversation_linked",
                    "lead_id": conv.lead_id,
                })
            for other in list(lead.conversations):
                if other.id != conv.id:
                    other.lead_id = None
            conv.lead_id = lead.id
            db.query(PropertyRecommendation).filter(
                PropertyRecommendation.conversation_id == conv.id,
                PropertyRecommendation.lead_id.is_(None),
            ).update({"lead_id": lead.id}, synchronize_session=False)

    # --- apply plain columns ---
    parts_sent = (not fields.keys().isdisjoint(
        {"budget_min", "budget_max", "budget_currency"})
        or budget_period is not _MISSING)
    for key, value in fields.items():
        if hasattr(lead, key):
            setattr(lead, key, value)

    if preferences is not _MISSING:
        # preferences are stored in the existing `requirements` column
        lead.requirements = encode_preferences(preferences)
    if parts_sent:
        # canonical re-encode keeps the display string and the round-trip
        # period in sync; explicit null clears the period
        final_period = (budget_period if budget_period is not _MISSING
                        else parse_budget_period(lead.budget))
        lead.budget = encode_budget_display(
            lead.budget_currency.upper() if lead.budget_currency else None,
            lead.budget_min, lead.budget_max, final_period)

    # --- deterministic server-side re-score on requirement changes ---
    result = None
    if (not fields.keys().isdisjoint(SCORE_TRIGGER_FIELDS)
            or preferences is not _MISSING
            or budget_period is not _MISSING):
        result = recompute_lead_score(lead)

    lead.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(lead)

    return {"lead": lead_detail(lead),
            "score": _score_payload(result) if result is not None else None}


@app.post("/api/agent/leads/extract")
def agent_extract_lead(
    payload: LeadExtractionRequest,
    agent: Agent = Depends(get_current_agent),
    _rl: None = Depends(rate_limit("chat", "CHAT_RATE_LIMIT")),
):
    """Staff-only structured lead extraction (Phase 3).

    REVIEW STEP ONLY — creates/updates NOTHING. The agent inspects and edits
    the extracted fields; persistence happens in a later phase through the
    validated save workflow. Uses OpenAI exclusively for extraction; the
    NVIDIA customer chat path is untouched.
    """
    try:
        result = extract_lead_requirements(payload)
    except LeadExtractionError as exc:
        # Safe, structured error: provider internals/keys never surface.
        raise HTTPException(
            status_code=exc.status_code,
            detail={"message": exc.message, "code": exc.code},
        )
    return {
        "extraction": result.model_dump(),
        "lead_created": False,
        "note": "Review only: no lead was created or modified.",
        "extracted_by": agent.email,
    }


@app.post("/api/agent/leads/score")
def agent_score_lead(
    extraction: LeadExtractionResult,
    agent: Agent = Depends(get_current_agent),
):
    """Deterministic lead scoring (Phase 4) — staff only.

    Pure CPU: no database access, no LLM call, no writes. The body is the
    reviewed extraction payload; any client-supplied score/priority fields
    are ignored (Pydantic extra="ignore") — only the validated criteria
    fields ever influence the computed score.
    """
    return {"score": score_lead(extraction).model_dump()}


@app.post("/api/agent/properties/match")
def agent_match_properties(
    request: MatchRequest,
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
    _rl: None = Depends(rate_limit("chat", "CHAT_RATE_LIMIT")),
):
    """Deterministic property matching (Phase 4) — staff only, read-only.

    Matches ONLY approved+available database ``properties`` records (never
    the JSON dataset), applies hard eligibility (verified purpose, stated
    intent, bedrooms/bathrooms/type), and ranks with the auditable
    30/25/20/15/10 weights. Returns at most ``limit`` (1-10, default 3)
    results; empty results come with a clear explanation. Persists nothing.
    """
    try:
        result = match_properties(db, request.extraction, limit=request.limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return result.model_dump()


# ---------------- Follow-ups (existing Phase 2 `follow_ups` table) --------
# No emails/SMS/WhatsApp are ever SENT, no schedulers: `type` is a label.
# Timezone: due_at is stored as naive UTC (project-wide convention); the
# API accepts ISO-8601 (aware → converted, naive → read as UTC) and
# serialises with an explicit "Z". Buckets (overdue/due_today/upcoming)
# are UTC calendar-day buckets over pending rows.

@app.post("/api/agent/leads/{lead_id}/follow-ups")
def agent_create_followup(
    lead_id: int,
    payload: FollowUpCreate,
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """Schedule a follow-up for a lead in this agent's scope (staff only).

    Validates type (CHECK-matching set), due date, and the optional agent
    (admins may assign anyone active; agents may only assign themselves).
    """
    lead = _scoped_lead_or_404(db, agent, lead_id)
    assigned_id = (_resolve_agent(db, agent, payload.assigned_agent_id)
                   if payload.assigned_agent_id is not None else agent.id)
    try:
        fu = create_followup(
            db, lead=lead, fu_type=payload.type, due_at=payload.due_at,
            notes=payload.notes, assigned_agent_id=assigned_id)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
    db.refresh(fu)
    return {"follow_up": follow_up_summary(fu)}


@app.get("/api/agent/leads/{lead_id}/follow-ups")
def agent_lead_followups(
    lead_id: int,
    include_completed: bool = True,
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """All follow-ups of a lead in this agent's scope (oldest due first)."""
    lead = _scoped_lead_or_404(db, agent, lead_id)
    rows = list_lead_followups(db, lead, include_completed=include_completed)
    return {"results": [follow_up_summary(f) for f in rows]}


@app.get("/api/agent/follow-ups")
def agent_list_followups(
    filter: Literal[
        "all", "pending", "overdue", "due_today", "upcoming", "completed"
    ] = Query("pending"),
    lead_id: Optional[int] = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """Follow-ups across this agent's scoped leads, filterable by bucket.

    Buckets (UTC days, pending rows only — the three partition exactly):
    overdue = due before today · due_today = any time today ·
    upcoming = tomorrow onward. `lead_id` must also be in scope (404).
    """
    if lead_id is not None:
        _scoped_lead_or_404(db, agent, lead_id)
    query = scoped_followup_query(db, agent)
    if lead_id is not None:
        query = query.filter(FollowUp.lead_id == lead_id)
    try:
        query = filter_followups(query, filter)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    total = query.count()
    rows = (
        query.options(joinedload(FollowUp.lead))
        .order_by(FollowUp.due_at.asc(), FollowUp.id.asc())
        .offset(offset).limit(limit).all()
    )
    return {
        "total": total,
        "results": [
            {
                **(follow_up_summary(f) or {}),
                "lead_name": (f.lead.name if f.lead else None),
                "lead_status": (f.lead.status if f.lead else None),
            }
            for f in rows
        ],
    }


@app.patch("/api/agent/follow-ups/{follow_up_id}")
def agent_update_followup(
    follow_up_id: int,
    update: FollowUpUpdate,
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """Update one follow-up (type/due/notes/completion/assignment).

    The follow-up's lead must be inside the caller's scope (404 otherwise —
    existence is never leaked). Completing stamps `completed_at`; restoring
    clears it. No other state machine exists in the schema.
    """
    fu = db.query(FollowUp).filter(FollowUp.id == follow_up_id).first()
    if fu is None or not lead_in_scope(agent, fu.lead):
        raise HTTPException(status_code=404, detail="Follow-up not found")

    fields = update.model_dump(exclude_unset=True)
    if "assigned_agent_id" in fields and fields["assigned_agent_id"] is not None:
        fields["assigned_agent_id"] = _resolve_agent(
            db, agent, fields["assigned_agent_id"])
    try:
        update_followup(db, fu, fields)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
    db.refresh(fu)
    return {"follow_up": follow_up_summary(fu)}


# ---------------- Recommendations (Phase 4 matching + persistence) --------

@app.post("/api/agent/leads/{lead_id}/recommendations")
def agent_run_recommendations(
    lead_id: int,
    run: RecommendationRun,
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """Deterministic match for a saved lead + explicit history persistence.

    Workflow: load the reviewed lead → re-score it (server-side) → match
    approved+available properties → persist ONLY history rows that do not
    exist yet for this lead (a repeated request never duplicates rows).

    Transaction design: the score refresh and the new history rows commit
    together (one transaction). A matching/validation failure rolls
    everything back — the already-valid lead itself is untouched, because
    the lead was saved earlier through its own operation.
    """
    lead = _scoped_lead_or_404(db, agent, lead_id)
    try:
        extraction = lead_to_extraction(lead)
        score = recompute_lead_score(lead)
        result = match_properties(db, extraction, limit=run.limit)

        already = {
            row[0] for row in
            db.query(PropertyRecommendation.property_record_id)
            .filter(PropertyRecommendation.lead_id == lead.id,
                    PropertyRecommendation.property_record_id.isnot(None))
            .all()
        }
        new_rows = [m for m in result.results if m.property_id not in already]
        if run.save and new_rows:
            subset = result.model_copy(update={"results": new_rows})
            saved_ids = save_recommendations(db, subset, lead_id=lead.id)
        else:
            # dry run, or everything was already saved: persist the
            # refreshed score on its own (still no duplicate history)
            saved_ids = []
            db.commit()
    except HTTPException:
        db.rollback()
        raise
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — boundary: rollback, log class only
        db.rollback()
        logger.error("recommendation run failed: %s", type(exc).__name__)
        raise HTTPException(status_code=500,
                            detail="Recommendations could not be saved")

    return {
        "lead_id": lead.id,
        "results": [
            {**m.model_dump(), "previously_saved": m.property_id in already}
            for m in result.results
        ],
        "saved_count": len(saved_ids),
        "saved_row_ids": saved_ids,
        "explanation": result.explanation,
        "score": _score_payload(score),
    }


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
    # Scope: read_all holders see everything; others see conversations of
    # leads in their scope
    if not rbac.has_permission(agent, "conversations.read_all"):
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