import os
import json
import secrets
import asyncio
import logging
import threading
from datetime import datetime
from typing import Annotated, Any, Dict, List, Literal, Optional
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Request, Response, Query
from fastapi.responses import Response as RawResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func, or_
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.database import (
    init_db, get_db, SessionLocal,
    Conversation, Message, Lead, Property, PropertyImage, PropertyRecommendation, Customer,
    Agent, SavedProperty, FollowUp, AgentRole, AuditLog,
    Appointment, Offer, Deal, DealChecklistItem,
    CustomerCommunication, CustomerNotification,
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
from app.services.property_crud import (
    create_property,
    get_property as crud_get_property,
    update_property,
    delete_property,
    list_properties,
    archive_property,
    property_reference_counts,
    inventory_summary,
    staff_property_dict,
)
from app.services.property_lifecycle import (
    submit_for_review,
    approve_property,
    reject_property,
    publish_property,
    unpublish_property,
    archive_property_lifecycle,
    update_property_availability,
    manage_property_images,
    bulk_lifecycle_action,
)
from app.services.property_importer import (
    preview_import_records,
    stage_import_batch,
)
from app.services.property_validator import (
    validate_property_payload,
)
from app.database import PropertyImportBatch
from app.services.lead_scoring import score_lead
from app.services.property_matching import (
    MatchRequest, match_properties, save_recommendations,
)
from app.services.followups import (
    FOLLOWUP_FILTERS, FOLLOWUP_TYPES,
    cancel_followup, create_followup, filter_followups, follow_up_summary,
    list_lead_followups, parse_due_at, scoped_followup_query, update_followup,
)
from app.services.crm_stats import dashboard_stats
from app.services.auth import (
    AGENT_COOKIE, CUSTOMER_COOKIE,
    hash_password, verify_password, create_session, revoke_session,
    get_current_agent, get_customer_token, get_or_create_customer,
    set_agent_cookie, clear_agent_cookie, lead_in_scope, scoped_lead_query,
    customer_in_scope, scoped_customer_query, conversation_in_scope, scoped_conversation_query,
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
    TERMINAL_LEAD_STATUSES,
    upsert_lead_from_ai, find_existing_lead, find_duplicate, find_all_duplicates,
    find_lead_by_idempotency_key, lead_summary, lead_detail, lead_to_extraction,
    recompute_lead_score, encode_budget_display, encode_preferences,
    parse_budget_period, get_preferences, get_qualification_meta,
    qualification_completeness, normalize_lead_status, validate_status_transition,
    list_eligible_sales_agents, assign_lead_round_robin, merge_duplicate_leads,
    lead_activity_history,
)
from app.services import customer_ops as cops
from app.services.sales_ops import (
    ACTIVE_APPOINTMENT_STATUSES,
    APPOINTMENT_STATUSES,
    APPOINTMENT_TYPES,
    CHECKLIST_STATUSES,
    COMMISSION_STATUSES,
    CUSTOMER_CONFIRMATION_STATUSES,
    DEAL_STAGES,
    MEETING_METHODS,
    OFFER_INTENTS,
    OFFER_STATUSES,
    PAYMENT_FREQUENCIES,
    TERMINAL_DEAL_STAGES,
    VIEWING_OUTCOMES,
    AppointmentConflictError,
    appointment_in_scope,
    appointment_to_dict,
    cancel_appointment,
    checklist_item_to_dict,
    compute_sales_ops_summary,
    create_appointment,
    create_deal,
    create_offer,
    deal_in_scope,
    deal_to_dict,
    offer_in_scope,
    offer_to_dict,
    record_appointment_outcome,
    record_counteroffer,
    reschedule_appointment,
    scoped_appointment_query,
    scoped_deal_query,
    scoped_offer_query,
    to_utc_naive,
    transition_deal_stage,
    transition_offer_status,
    update_deal_checklist_item,
)
from app.services.ratelimit import rate_limit

from app.services.property_image_storage import (
    store_property_image,
    get_property_image,
    get_primary_property_image,
    list_property_images,
    set_primary_property_image,
    delete_property_image,
)
from app.services.analytics import (
    get_executive_analytics,
    get_manager_analytics,
    get_agent_personal_analytics,
    export_agent_performance_csv,
    parse_reporting_period,
)

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
    # If wildcard is explicitly allowed (dev convenience only)
    if "*" in settings.CORS_ORIGINS:
        return True
    # Same-origin: the Origin matches this request's own scheme://host
    # (covers the production single-host deployment behind any port).
    host = (request.headers.get("host") or "").strip()
    if host and origin in (f"http://{host}", f"https://{host}"):
        return True
    # If behind a reverse proxy (e.g. Vite proxy, Nginx), verify X-Forwarded-Host
    forwarded_host = (request.headers.get("x-forwarded-host") or "").split(",")[0].strip()
    if forwarded_host and origin in (f"http://{forwarded_host}", f"https://{forwarded_host}"):
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

# Per-conversation turn lock: each chat turn is a read-modify-write cycle
# (load state → extract → merge → reply → persist), so two rapid submissions
# (double-click, retried fetch, voice+text overlap) would otherwise race on
# memory, messages and lead rows. Different conversations still run in
# parallel; entries are tiny and bounded by conversations seen per process.
_CONVERSATION_LOCKS: Dict[int, Any] = {}
_CONVERSATION_LOCKS_GUARD = threading.Lock()


def _conversation_lock(conversation_id: int):
    """Serialise turns for ONE conversation (see _CONVERSATION_LOCKS)."""
    with _CONVERSATION_LOCKS_GUARD:
        lock = _CONVERSATION_LOCKS.get(conversation_id)
        if lock is None:
            lock = threading.Lock()
            _CONVERSATION_LOCKS[conversation_id] = lock
        return lock


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
    # --- Phase E: lifecycle, UAE qualification & assignment metadata ---
    reopen: Optional[bool] = Field(
        None, description="Explicitly reopen a closed_won or closed_lost lead")
    status_reason: Optional[str] = Field(None, max_length=500)
    preferred_language: Optional[str] = Field(None, max_length=40)
    emirate: Optional[str] = Field(None, max_length=60)
    financing_type: Optional[Literal[
        "cash", "mortgage", "mortgage_preapproved", "mortgage_needed", "payment_plan", "undecided"
    ]] = None
    preferred_viewing_time: Optional[str] = Field(None, max_length=200)
    qualification_status: Optional[Literal[
        "unqualified", "partially_qualified", "qualified", "disqualified"
    ]] = None
    next_action: Optional[str] = Field(None, max_length=500)
    field_provenance: Optional[Dict[str, str]] = None
    assignment_reason: Optional[str] = Field(None, max_length=500)
    temperature: Optional[Literal["hot", "warm", "cold"]] = None
    temperature_rationale: Optional[str] = Field(None, max_length=1000)


StatusLiteral = Literal[
    "new", "contact_pending", "contacted", "qualified", "viewing",
    "negotiation", "closed_won", "closed_lost", "nurturing",
]
# Route-level and model-level status vocabularies must never drift apart.
assert set(StatusLiteral.__args__) == {
    "new", "contact_pending", "contacted", "qualified", "viewing",
    "negotiation", "closed_won", "closed_lost", "nurturing",
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
    # --- Phase E: UAE qualification, assignment & idempotency ---
    investment_purpose: Optional[Annotated[str, Field(max_length=200)]] = None
    preferred_language: Optional[Annotated[str, Field(max_length=40)]] = None
    emirate: Optional[Annotated[str, Field(max_length=60)]] = None
    financing_type: Optional[Literal[
        "cash", "mortgage", "mortgage_preapproved", "mortgage_needed", "payment_plan", "undecided"
    ]] = None
    preferred_viewing_time: Optional[Annotated[str, Field(max_length=200)]] = None
    qualification_status: Optional[Literal[
        "unqualified", "partially_qualified", "qualified", "disqualified"
    ]] = None
    next_action: Optional[Annotated[str, Field(max_length=500)]] = None
    assignment_mode: Optional[Literal["manual", "round_robin"]] = None
    idempotency_key: Optional[Annotated[str, Field(max_length=120)]] = None

    @field_validator("name", "phone", "email", "budget_currency", mode="before")
    @classmethod
    def _blank_to_none(cls, v):
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @model_validator(mode="after")
    def validate_contact_and_budget(self) -> "LeadCreate":
        # 1. Lead name is required for manual lead creation (min 2 chars)
        name_clean = (self.name or "").strip()
        if not name_clean or len(name_clean) < 2:
            raise ValueError("Lead name is required (minimum 2 characters)")

        # 2. At least one contact method (phone or email) is required
        phone_clean = (self.phone or "").strip()
        email_clean = (self.email or "").strip()
        if not phone_clean and not email_clean:
            raise ValueError("At least one contact method (phone or email) is required to create a lead")

        # 3. Phone minimum digit validation if provided
        if phone_clean:
            digits = [c for c in phone_clean if c.isdigit()]
            if len(digits) < 7:
                raise ValueError("Phone number must contain at least 7 digits")

        # 4. Budget consistency
        if self.budget_min is not None and self.budget_max is not None and self.budget_min > self.budget_max:
            raise ValueError("budget_min cannot exceed budget_max")

        return self


class FollowUpCreate(BaseModel):
    """POST /api/agent/leads/{id}/follow-ups."""
    model_config = ConfigDict(extra="ignore")

    type: str = Field(..., description="call|email|whatsapp|viewing|general")
    due_at: datetime = Field(..., description="ISO-8601; naive values are read as UTC")
    notes: str = Field("", max_length=4000)
    assigned_agent_id: Optional[int] = Field(None, ge=1)
    priority: Optional[Literal["high", "medium", "low", "normal"]] = None


class FollowUpUpdate(BaseModel):
    """PATCH /api/agent/follow-ups/{id} — partial update."""
    model_config = ConfigDict(extra="ignore")

    type: Optional[str] = None
    due_at: Optional[datetime] = None
    notes: Optional[str] = Field(None, max_length=4000)
    is_completed: Optional[bool] = None
    is_cancelled: Optional[bool] = None
    cancel_reason: Optional[str] = Field(None, max_length=500)
    priority: Optional[Literal["high", "medium", "low", "normal"]] = None
    assigned_agent_id: Optional[int] = Field(None, ge=1)


class FollowUpCancelRequest(BaseModel):
    """POST /api/agent/follow-ups/{id}/cancel."""
    model_config = ConfigDict(extra="ignore")

    reason: Optional[str] = Field(None, max_length=500)
    cancel_reason: Optional[str] = Field(None, max_length=500)


class LeadStatusTransitionRequest(BaseModel):
    """POST /api/agent/leads/{id}/status."""
    model_config = ConfigDict(extra="forbid")

    status: str = Field(..., min_length=1, max_length=40)
    reopen: bool = Field(False, description="Required when reopening closed_won/closed_lost")
    reason: Optional[str] = Field(None, max_length=500)


class LeadAssignRequest(BaseModel):
    """POST /api/agent/leads/{id}/assign."""
    model_config = ConfigDict(extra="forbid")

    mode: Literal["manual", "round_robin", "claim", "unassign"] = "manual"
    assigned_agent_id: Optional[int] = Field(None, ge=1)
    reason: Optional[str] = Field(None, max_length=500)


class LeadMergeRequest(BaseModel):
    """POST /api/agent/leads/{id}/merge."""
    model_config = ConfigDict(extra="forbid")

    source_lead_id: int = Field(..., ge=1)
    reason: Optional[str] = Field(None, max_length=500)


class LeadPropertyLinkRequest(BaseModel):
    """POST /api/agent/leads/{id}/properties."""
    model_config = ConfigDict(extra="forbid")

    property_record_id: int = Field(..., ge=1)
    relation_status: Literal["shortlisted", "viewing", "offer", "recommended"] = "shortlisted"
    notes: Optional[str] = Field(None, max_length=1000)
    highlights: Optional[str] = Field(None, max_length=1000)


class RecommendationRun(BaseModel):
    """POST /api/agent/leads/{id}/recommendations."""
    model_config = ConfigDict(extra="ignore")

    limit: int = Field(3, ge=1, le=10)
    save: bool = Field(True, description="Persist new history rows (deduplicated)")


LEAD_STATUSES = {
    "new", "contact_pending", "contacted", "qualified", "viewing",
    "negotiation", "closed_won", "closed_lost", "nurturing",
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

@app.get("/")
def root():
    """Root landing endpoint providing service health and links."""
    return {
        "service": "Lyka Realty CRM & LykAI Backend API",
        "status": "online",
        "frontend_app_url": "http://localhost:5173",
        "api_docs_url": "http://localhost:8000/docs",
        "health_check_url": "http://localhost:8000/api/health",
        "message": "The backend API server is running successfully! To use the Lyka Realty CRM Web Application, please open http://localhost:5173 in your browser.",
    }


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
            tts_language = result.get("reply_language") or result.get("detected_language") or "en-IN"
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
    language: Optional[str] = Field(None, description="en | ta | ta-Latn | en-IN | ta-IN")


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

    if audio.startswith(b"RIFF"):
        media_type = "audio/wav"
    elif audio.startswith(b"ID3") or audio[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        media_type = "audio/mpeg"
    else:
        media_type = "audio/wav"
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

    # One turn at a time per conversation (see _conversation_lock): state is
    # a read-modify-write, so concurrent submissions must not interleave.
    with _conversation_lock(conversation_id):
        # Get or create agent instance for this conversation
        agent = agents.get(conversation_id)
        if agent is None:
            agent = AIRealEstateAgent(conversation_id=conversation_id)
            # 1) Restore persisted structured memory FIRST — the exact slots
            #    the customer confirmed. The regex replay below only runs for
            #    legacy rows that predate the memory column: re-running the
            #    lossy extractor over old messages would overwrite good slots
            #    with stale phrasings (the old repeated-question failure mode).
            had_memory = False
            if conv.memory:
                try:
                    had_memory = agent.load_memory(json.loads(conv.memory))
                except (ValueError, TypeError) as exc:
                    logger.warning(
                        "conversation %s: unreadable memory blob (%s)",
                        conversation_id, exc,
                    )
            # 2) Replay the stored transcript so reopening a conversation
            #    keeps memory across refreshes/restarts (server-owned; the
            #    frontend never sends history back).
            prior = (
                db.query(Message)
                .filter(Message.conversation_id == conversation_id)
                .order_by(Message.id)
                .all()
            )
            for m in prior:
                agent.state.add_message(m.role, m.content, m.detected_language or "en")
                if m.role == "user" and not had_memory:
                    agent._extract_requirements(m.content)
                    # Restore a standing language request too (Phase 11): the
                    # reply-language pin lives only in conversation state, so
                    # without this a cold restart answered "Could you talk in
                    # Tamil?" follow-ups in English again.
                    req = AIRealEstateAgent.detect_language_request(m.content)
                    if req:
                        agent.state.language_request = req
                        agent.state.reply_language = req
            # 3) Restore previously recommended properties so refinements
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

        # If this customer is authenticated and has known profile info, pre-populate contact details
        if customer and getattr(customer, "is_account", False):
            if not agent.state.contact.get("name") and customer.name:
                agent.state.contact["name"] = customer.name
            if not agent.state.contact.get("email") and customer.email:
                agent.state.contact["email"] = customer.email
            if not agent.state.contact.get("phone") and customer.phone:
                agent.state.contact["phone"] = customer.phone

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

        # Pre-extract THIS message before composing the reply: idempotent
        # (respond() runs the same extraction over the same text), but it lets
        # the lead upsert and the prompt's PERSISTENCE section see this turn's
        # facts first. Second layer: LLM structured extraction merged
        # field-by-field — the rules above are the guaranteed baseline, any
        # provider failure degrades to rules-only, and only facts the customer
        # states in THIS message can change stored slots (rest retained).
        agent._extract_requirements(message)
        agent.merge_llm_extractions(message)

        # Stage the structured-memory write BEFORE the reply is generated, so
        # the model's save claims are backed by rows committed in the SAME
        # transaction that delivers the reply — a failed commit surfaces as an
        # HTTP error (frontend error state), never a false "saved" message.
        save_status: Dict[str, bool] = {"preferences": False, "lead": False}

        def _stage_memory() -> None:
            try:
                conv.memory = json.dumps(agent.export_memory(), ensure_ascii=False)
                save_status["preferences"] = True
            except (TypeError, ValueError) as exc:
                save_status["preferences"] = False
                logger.warning(
                    "conversation %s: memory not staged (%s)", conversation_id, exc
                )

        _stage_memory()

        # Create or update the conversation's ONE lead row (dedup: the
        # conversation link first, then phone/email — never a row per message).
        # Runs for any meaningful property enquiry, anonymous visitors included:
        # the conversation link is their stable id until real contact details
        # arrive. Server-side path only — no public endpoint writes leads. A
        # failed write never breaks the chat and leaves PERSISTENCE at
        # "not yet", so the model cannot claim an unconfirmed save.
        try:
            lead_data = agent.get_lead_data()
            has_identity = bool(lead_data.get("phone") or lead_data.get("email"))
            # Only create or update a Lead when valid contact details (phone or email) are present
            # OR if this conversation is already linked to an existing lead.
            # Anonymous visitors are safely preserved in Conversation and memory without creating empty placeholder leads.
            should_upsert = (has_identity or conv.lead_id is not None) and any(v is not None for v in lead_data.values())
            if should_upsert:
                upsert_lead_from_ai(
                    db,
                    lead_data,
                    conversation=conv,
                    last_customer_message=message,
                    agent_state=agent.state,
                )
                save_status["lead"] = True
        except Exception as exc:  # noqa: BLE001 — chat must survive a lead failure
            logger.warning(
                "conversation %s: lead upsert failed (%s)", conversation_id, exc
            )
            try:
                db.rollback()
            except Exception:  # noqa: BLE001 — best effort; commit will surface it
                pass
            # A rollback discarded the staged memory too — re-stage it so the
            # conversation itself is still saved with this reply.
            _stage_memory()
        agent.persistence_status = save_status

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

        # Lead upsert already ran ABOVE (pre-reply) so the model's PERSISTENCE
        # section is honest — nothing to create here afterwards.

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
        conv_row = conv  # already loaded/verified above
        if conv_row:
            conv_row.updated_at = datetime.utcnow()
            if not conv_row.customer_name and agent.state.contact.get("name"):
                conv_row.customer_name = agent.state.contact["name"]
            if not conv_row.customer_phone and agent.state.contact.get("phone"):
                conv_row.customer_phone = agent.state.contact["phone"]
            if not conv_row.customer_email and agent.state.contact.get("email"):
                conv_row.customer_email = agent.state.contact["email"]

            # Synchronize any newly captured contact or requirements into Lead
            lead_data_post = agent.get_lead_data()
            if (conv_row.lead_id or bool(lead_data_post.get("phone") or lead_data_post.get("email"))) and any(v is not None for v in lead_data_post.values()):
                try:
                    upsert_lead_from_ai(
                        db,
                        lead_data_post,
                        conversation=conv_row,
                        last_customer_message=message,
                        agent_state=agent.state,
                    )
                except Exception as exc:
                    logger.warning("Post-reply lead sync: %s", exc)
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
            # (The pre-reply upsert normally linked it already — this is the
            # safety net for turns where the upsert failed or didn't run.)
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

        # Persist the FINAL memory (post-reply state: stage, language pins,
        # anything the reply flow changed) over the pre-reply snapshot —
        # same row, single commit with the messages above.
        _stage_memory()

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
        approved_only=True,
        published_only=True,
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

    # 1. Primary path: High-performance indexed PostgreSQL query across migrated UAE dataset
    query = db.query(Property).filter(Property.source.in_(["uae_dataset", "dataset"]))
    if location:
        query = query.filter(Property.location.ilike(f"%{location.strip()}%"))
    if property_type:
        query = query.filter(Property.property_type.ilike(f"%{property_type.strip()}%"))
    if min_price is not None:
        query = query.filter(Property.price >= min_price)
    if max_price is not None:
        query = query.filter(Property.price <= max_price)
    if min_bedrooms is not None:
        query = query.filter(Property.bedrooms >= min_bedrooms)
    if max_bedrooms is not None:
        query = query.filter(Property.bedrooms <= max_bedrooms)

    total = query.count()
    if total > 0:
        rows = query.order_by(Property.id.asc()).offset(offset).limit(limit).all()
        return {
            "results": [dataset_db_record_dict(p) for p in rows],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    # 2. Fallback to local JSON dataset search if DB query returns 0
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
    """Get a specific property by ID from the official UAE dataset in PostgreSQL."""
    # 1. Authoritative check: PostgreSQL database query by external_ref (UAE-<id>)
    db_prop = (
        db.query(Property)
        .filter(
            Property.source.in_(["uae_dataset", "dataset"]),
            Property.external_ref == f"UAE-{property_id}",
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

    # 2. Fallback: in-memory dataset cache lookup
    prop = get_property_by_id(property_id)
    if prop:
        return prop

    raise HTTPException(status_code=404, detail="Property not found")


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
    auditlog.write_audit(
        db, auditlog.USER_CREATED, actor_type="customer", actor_id=account.id,
        actor_label=account.email, subject_type="customer", subject_id=account.id,
        subject_label=account.email, ip=auditlog.client_ip(http_request),
    )
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
        auditlog.write_audit(
            db, auditlog.LOGIN_FAILURE, actor_type="customer",
            actor_id=account.id if account is not None else None,
            actor_label=email, ip=auditlog.client_ip(http_request),
            detail="bad_credentials",
        )
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
def customer_logout(
    response: Response,
    db: Session = Depends(get_db),
    http_request: Request = None,
):
    """Sign out — rotates the server-side customer token and clears the cookie."""
    customer = find_visitor_customer(db, http_request) if http_request else None
    if customer is not None and customer.is_account:
        reissue_customer_token(db, customer)
        auditlog.write_audit(
            db, auditlog.LOGOUT, actor_type="customer", actor_id=customer.id,
            actor_label=customer.email, ip=auditlog.client_ip(http_request),
        )
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
# CUSTOMER PORTAL — PHASE H
# ================================================================

class CustomerProfileUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=120)
    phone: Optional[str] = Field(None, max_length=50)
    preferred_contact_method: Optional[Literal["email", "phone", "whatsapp"]] = None
    purpose: Optional[Literal["buy", "rent", "investment", "self_use"]] = None
    preferred_locations: Optional[Any] = None
    property_type: Optional[str] = None
    bedrooms_min: Optional[int] = Field(None, ge=0)
    bedrooms_max: Optional[int] = Field(None, ge=0)
    budget_min: Optional[float] = Field(None, ge=0)
    budget_max: Optional[float] = Field(None, ge=0)
    budget_currency: Optional[str] = "AED"


class CustomerPasswordChange(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=6)
    confirm_new_password: Optional[str] = None


class CustomerViewingRequestIn(BaseModel):
    property_id: int
    property_source: Literal["record", "dataset"] = "record"
    start_at: str
    end_at: str
    timezone: str = "Asia/Dubai"
    meeting_method: Literal["in_person", "phone", "video"] = "in_person"
    location_or_link: Optional[str] = None
    notes: Optional[str] = None
    idempotency_key: Optional[str] = None


class CustomerRescheduleRequestIn(BaseModel):
    new_start_at: str
    new_end_at: str
    reason: Optional[str] = None


class CustomerCancelRequestIn(BaseModel):
    reason: Optional[str] = None


class CustomerCommunicationIn(BaseModel):
    message: str = Field(..., min_length=1)
    subject: Optional[str] = None
    property_id: Optional[int] = None
    appointment_id: Optional[int] = None


@app.get("/api/customer/profile")
def customer_get_profile(
    db: Session = Depends(get_db),
    http_request: Request = None,
):
    """Get customer personal profile, property preferences, and completion percentage."""
    customer = _require_account_customer(db, http_request)
    return cops.customer_profile_dict(customer)


@app.put("/api/customer/profile")
def customer_update_profile(
    payload: CustomerProfileUpdate,
    db: Session = Depends(get_db),
    http_request: Request = None,
):
    """Update customer profile and preferences."""
    customer = _require_account_customer(db, http_request)
    if payload.name is not None:
        customer.name = payload.name.strip() or None
    if payload.phone is not None:
        customer.phone = payload.phone.strip() or None
    if payload.preferred_contact_method is not None:
        customer.preferred_contact_method = payload.preferred_contact_method
    if payload.purpose is not None:
        customer.purpose = payload.purpose
    if payload.property_type is not None:
        customer.property_type = payload.property_type.strip() or None
    if payload.bedrooms_min is not None:
        customer.bedrooms_min = payload.bedrooms_min
    if payload.bedrooms_max is not None:
        customer.bedrooms_max = payload.bedrooms_max
    if payload.budget_min is not None:
        customer.budget_min = payload.budget_min
    if payload.budget_max is not None:
        customer.budget_max = payload.budget_max
    if payload.budget_currency is not None:
        customer.budget_currency = payload.budget_currency
    if payload.preferred_locations is not None:
        if isinstance(payload.preferred_locations, list):
            customer.preferred_locations = json.dumps(payload.preferred_locations)
        else:
            customer.preferred_locations = str(payload.preferred_locations).strip() or None

    customer.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(customer)
    auditlog.write_audit(
        db, "customer.profile.updated", actor_type="customer", actor_id=customer.id,
        actor_label=customer.email, ip=auditlog.client_ip(http_request),
    )
    return cops.customer_profile_dict(customer)


@app.post("/api/customer/change-password")
def customer_change_password(
    payload: CustomerPasswordChange,
    db: Session = Depends(get_db),
    http_request: Request = None,
):
    """Change password for authenticated customer account."""
    customer = _require_account_customer(db, http_request)
    if not customer.password_hash or not verify_password(payload.current_password, customer.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if payload.confirm_new_password is not None and payload.new_password != payload.confirm_new_password:
        raise HTTPException(status_code=422, detail="New passwords do not match")
    if payload.new_password == payload.current_password:
        raise HTTPException(status_code=422, detail="New password must be different from current password")

    customer.password_hash = hash_password(payload.new_password)
    customer.updated_at = datetime.utcnow()
    db.commit()
    auditlog.write_audit(
        db, auditlog.PASSWORD_RESET, actor_type="customer", actor_id=customer.id,
        actor_label=customer.email, ip=auditlog.client_ip(http_request),
    )
    return {"ok": True, "detail": "Password successfully updated"}


@app.get("/api/customer/dashboard")
def customer_dashboard(
    db: Session = Depends(get_db),
    http_request: Request = None,
):
    """Customer overview: profile stats, saved properties, viewing requests, and recent activity."""
    customer = _require_account_customer(db, http_request)
    profile_info = cops.customer_profile_dict(customer)

    # Saved properties count & top 3
    saved_rows = db.query(SavedProperty).filter(SavedProperty.customer_id == customer.id).order_by(SavedProperty.id.desc()).all()
    saved_count = len(saved_rows)
    recent_saved = []
    for r in saved_rows[:3]:
        if _saved_is_record_row(r.property_id):
            p = get_public_record(db, r.property_id - _SAVED_RECORD_ID_BASE)
            if p:
                recent_saved.append({**public_record_dict(p), "property_id": p.id, "source": "record"})
        else:
            p = get_property_by_id(r.property_id)
            if p:
                recent_saved.append({**p, "source": "dataset"})

    # Appointments & Viewings
    appts = (
        db.query(Appointment)
        .filter(Appointment.customer_id == customer.id)
        .order_by(Appointment.start_at.desc())
        .all()
    )
    active_viewings = [cops.customer_appointment_to_dict(a, db) for a in appts if a.status in ("scheduled", "confirmed", "rescheduled")]
    upcoming_count = len(active_viewings)

    # Notifications
    unread_notifs = cops.get_unread_notification_count(db, customer_id=customer.id)
    recent_notifs = [
        cops.notification_to_dict(n)
        for n in db.query(CustomerNotification)
        .filter(CustomerNotification.customer_id == customer.id, CustomerNotification.recipient_type == "customer")
        .order_by(CustomerNotification.created_at.desc())
        .limit(5)
        .all()
    ]

    # Recent communications
    recent_comms = [
        cops.communication_to_dict(c)
        for c in cops.get_customer_communications(db, customer.id, include_internal=False, limit=5)
    ]

    return {
        "customer": profile_info,
        "metrics": {
            "saved_count": saved_count,
            "upcoming_viewings_count": upcoming_count,
            "unread_notifications_count": unread_notifs,
            "profile_completion_pct": profile_info["profile_completion"]["percentage"],
        },
        "recent_saved": recent_saved,
        "upcoming_viewings": active_viewings[:5],
        "recent_notifications": recent_notifs,
        "recent_communications": recent_comms,
    }


@app.get("/api/customer/appointments")
def customer_list_appointments(
    db: Session = Depends(get_db),
    http_request: Request = None,
):
    """List all viewing requests and appointments for this customer."""
    customer = _require_account_customer(db, http_request)
    appts = (
        db.query(Appointment)
        .filter(Appointment.customer_id == customer.id)
        .order_by(Appointment.start_at.desc())
        .all()
    )
    return {
        "results": [cops.customer_appointment_to_dict(a, db) for a in appts],
        "total": len(appts),
    }


@app.post("/api/customer/appointments/request")
def customer_request_appointment(
    payload: CustomerViewingRequestIn,
    db: Session = Depends(get_db),
    http_request: Request = None,
):
    """Customer submits a property viewing request."""
    customer = _require_account_customer(db, http_request)
    try:
        start_dt = datetime.fromisoformat(payload.start_at)
        end_dt = datetime.fromisoformat(payload.end_at)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid date format: {exc}")

    try:
        appt, is_replay = cops.request_viewing(
            db,
            customer=customer,
            property_id=payload.property_id,
            property_source=payload.property_source,
            start_at=start_dt,
            end_at=end_dt,
            timezone_name=payload.timezone,
            meeting_method=payload.meeting_method,
            location_or_link=payload.location_or_link,
            customer_notes=payload.notes,
            idempotency_key=payload.idempotency_key,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {
        "appointment": cops.customer_appointment_to_dict(appt, db),
        "idempotent_replay": is_replay,
    }


@app.post("/api/customer/appointments/{appointment_id}/reschedule-request")
def customer_reschedule_request(
    appointment_id: int,
    payload: CustomerRescheduleRequestIn,
    db: Session = Depends(get_db),
    http_request: Request = None,
):
    """Customer requests date/time change for a viewing."""
    customer = _require_account_customer(db, http_request)
    try:
        start_dt = datetime.fromisoformat(payload.new_start_at)
        end_dt = datetime.fromisoformat(payload.new_end_at)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid date format: {exc}")

    try:
        appt = cops.customer_reschedule_viewing(
            db,
            appt_id=appointment_id,
            customer=customer,
            new_start_at=start_dt,
            new_end_at=end_dt,
            reason=payload.reason,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {"appointment": cops.customer_appointment_to_dict(appt, db)}


@app.post("/api/customer/appointments/{appointment_id}/cancel")
def customer_cancel_appointment(
    appointment_id: int,
    payload: Optional[CustomerCancelRequestIn] = None,
    db: Session = Depends(get_db),
    http_request: Request = None,
):
    """Customer cancels their viewing request or appointment."""
    customer = _require_account_customer(db, http_request)
    cancel_reason = payload.reason if payload else None
    try:
        appt = cops.customer_cancel_viewing(
            db,
            appt_id=appointment_id,
            customer=customer,
            reason=cancel_reason,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {"appointment": cops.customer_appointment_to_dict(appt, db)}


@app.get("/api/customer/communications")
def customer_list_communications(
    appointment_id: Optional[int] = None,
    db: Session = Depends(get_db),
    http_request: Request = None,
):
    """Retrieve customer-visible communication thread."""
    customer = _require_account_customer(db, http_request)
    comms = cops.get_customer_communications(
        db, customer.id, include_internal=False, appointment_id=appointment_id
    )
    return {
        "results": [cops.communication_to_dict(c, include_internal=False) for c in comms],
        "total": len(comms),
    }


@app.post("/api/customer/communications")
def customer_send_communication(
    payload: CustomerCommunicationIn,
    db: Session = Depends(get_db),
    http_request: Request = None,
):
    """Customer sends a message via portal."""
    customer = _require_account_customer(db, http_request)
    lead = cops._find_or_create_customer_lead(db, customer)
    comm = cops.log_communication(
        db,
        customer_id=customer.id,
        lead_id=lead.id,
        property_id=payload.property_id,
        appointment_id=payload.appointment_id,
        sender_type="customer",
        channel="portal",
        subject=payload.subject,
        message=payload.message,
        is_customer_visible=True,
    )
    # Notify assigned agent if available
    if lead.assigned_agent_id:
        cops.create_notification(
            db,
            recipient_type="agent",
            agent_id=lead.assigned_agent_id,
            category="general",
            title=f"New Message from {customer.name or customer.email}",
            message=payload.message[:150],
            related_type="lead",
            related_id=lead.id,
            action_url="/agent/leads",
        )
    return cops.communication_to_dict(comm, include_internal=False)


@app.get("/api/customer/notifications")
def customer_get_notifications(
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    http_request: Request = None,
):
    """In-app notifications for authenticated customer."""
    customer = _require_account_customer(db, http_request)
    unread_count = cops.get_unread_notification_count(db, customer_id=customer.id)
    notifs = (
        db.query(CustomerNotification)
        .filter(CustomerNotification.customer_id == customer.id, CustomerNotification.recipient_type == "customer")
        .order_by(CustomerNotification.created_at.desc())
        .limit(limit)
        .all()
    )
    return {
        "unread_count": unread_count,
        "results": [cops.notification_to_dict(n) for n in notifs],
        "total": len(notifs),
    }


@app.post("/api/customer/notifications/{notification_id}/read")
def customer_mark_notification_read(
    notification_id: int,
    db: Session = Depends(get_db),
    http_request: Request = None,
):
    """Mark notification as read."""
    customer = _require_account_customer(db, http_request)
    try:
        notif = cops.mark_notification_read(db, notification_id, customer_id=customer.id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Notification not found")
    return cops.notification_to_dict(notif)


@app.post("/api/customer/notifications/mark-all-read")
def customer_mark_all_notifications_read(
    db: Session = Depends(get_db),
    http_request: Request = None,
):
    """Mark all notifications as read for current customer."""
    customer = _require_account_customer(db, http_request)
    count = cops.mark_all_notifications_read(db, customer_id=customer.id)
    return {"marked_read_count": count}


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
        "must_change_password": bool(getattr(agent, "must_change_password", False)),
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


class PasswordChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)
    confirm_password: str = Field(..., min_length=8, max_length=128)


@app.post("/api/auth/change-password")
def auth_change_password(
    payload: PasswordChangeRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    agent: Agent = Depends(get_current_agent),
):
    """Allow an authenticated staff member to change their password and clear must_change_password."""
    if not verify_password(payload.current_password, agent.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")

    if payload.new_password != payload.confirm_password:
        raise HTTPException(status_code=422, detail="New passwords do not match")

    if payload.new_password == payload.current_password:
        raise HTTPException(status_code=400, detail="New password cannot be the same as the current password")

    np = payload.new_password
    has_upper = any(c.isupper() for c in np)
    has_lower = any(c.islower() for c in np)
    has_digit_or_symbol = any(c.isdigit() or not c.isalnum() for c in np)
    if not (has_upper and has_lower and has_digit_or_symbol):
        raise HTTPException(
            status_code=422,
            detail="Password must be at least 8 characters long and contain uppercase, lowercase, and numeric or special characters",
        )

    agent.password_hash = hash_password(payload.new_password)
    agent.must_change_password = False
    agent.failed_login_count = 0
    agent.locked_until = None
    db.add(agent)
    db.commit()

    revoke_all_sessions(db, agent.id)
    new_token = create_session(db, agent)
    set_agent_cookie(response, new_token)

    auditlog.write_audit(
        db, auditlog.PASSWORD_RESET, actor_type="staff", actor_id=agent.id,
        actor_label=agent.email, subject_type="staff", subject_id=agent.id,
        subject_label=agent.email, ip=auditlog.client_ip(request),
        detail="user completed password change",
    )
    return {
        "status": "ok",
        "message": "Password changed successfully",
        "must_change_password": False,
        "token": new_token,
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
    role_keys = roles_of(agent)
    return {
        "agent": _agent_public(agent),
        "roles": rbac.public_role_view(role_keys),
        "permissions": sorted(permissions_of(agent)),
    }


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


class AdminAgentCreateRequest(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=120)
    email: str = Field(..., max_length=200)
    username: Optional[str] = Field(None, max_length=60)
    password: Optional[str] = Field(None, min_length=8)
    role: Optional[str] = Field("agent")


class AdminAgentResetPasswordRequest(BaseModel):
    temporary_password: Optional[str] = Field(None, min_length=8)


class AdminAgentStatusRequest(BaseModel):
    is_active: bool


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


class OptionalStepUpRequest(BaseModel):
    current_password: Optional[str] = None


@app.post("/api/admin/users/{user_id}/roles/{role_key}")
def admin_grant_role(
    user_id: int,
    role_key: str,
    payload: Optional[OptionalStepUpRequest] = None,
    db: Session = Depends(get_db),
    request: Request = None,
    admin: Agent = Depends(require_permissions("roles.manage")),
):
    """Grant an EXTRA role (roles.manage + step-up when current_password supplied).
    Additive; the primary role in `agents.role` is untouched."""
    if payload is not None and payload.current_password is not None:
        _require_step_up(db, admin, payload.current_password)
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
    revoked = revoke_all_sessions(db, target.id)
    auditlog.write_audit(
        db, auditlog.ROLE_GRANTED, actor_type="staff", actor_id=admin.id,
        actor_label=admin.email, subject_type="staff", subject_id=target.id,
        subject_label=target.email, ip=auditlog.client_ip(request),
        detail=f"extra role {key}; revoked {revoked} session(s)",
    )
    return {"user": _staff_public(target, load_role_keys(db, target))}


@app.delete("/api/admin/users/{user_id}/roles/{role_key}")
def admin_revoke_role(
    user_id: int,
    role_key: str,
    payload: Optional[OptionalStepUpRequest] = None,
    db: Session = Depends(get_db),
    request: Request = None,
    admin: Agent = Depends(require_permissions("roles.manage")),
):
    """Revoke an EXTRA role (roles.manage + step-up when current_password supplied).
    The primary role cannot be revoked here — use the role-change endpoint."""
    if payload is not None and payload.current_password is not None:
        _require_step_up(db, admin, payload.current_password)
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
    revoked = revoke_all_sessions(db, target.id)
    auditlog.write_audit(
        db, auditlog.ROLE_REVOKED, actor_type="staff", actor_id=admin.id,
        actor_label=admin.email, subject_type="staff", subject_id=target.id,
        subject_label=target.email, ip=auditlog.client_ip(request),
        detail=f"revoked extra role {key}; revoked {revoked} session(s)",
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


@app.get("/api/admin/agents")
def admin_list_agents(
    db: Session = Depends(get_db),
    admin: Agent = Depends(require_permissions("users.read", "leads.read_all", mode="any")),
):
    """List all agents with workload statistics and performance metrics."""
    agents = db.query(Agent).order_by(Agent.id.asc()).all()
    results = []
    now = datetime.utcnow()
    for a in agents:
        role_keys = load_role_keys(db, a)
        assigned_leads = db.query(Lead).filter(Lead.assigned_agent_id == a.id).count()
        hot_leads = db.query(Lead).filter(Lead.assigned_agent_id == a.id, Lead.temperature == "hot").count()
        warm_leads = db.query(Lead).filter(Lead.assigned_agent_id == a.id, Lead.temperature == "warm").count()
        cold_leads = db.query(Lead).filter(Lead.assigned_agent_id == a.id, Lead.temperature == "cold").count()

        pending_followups = (
            db.query(FollowUp)
            .join(Lead, FollowUp.lead_id == Lead.id)
            .filter(Lead.assigned_agent_id == a.id, FollowUp.is_completed.is_(False))
            .count()
        )
        overdue_followups = (
            db.query(FollowUp)
            .join(Lead, FollowUp.lead_id == Lead.id)
            .filter(
                Lead.assigned_agent_id == a.id,
                FollowUp.is_completed.is_(False),
                FollowUp.due_at < now,
            )
            .count()
        )
        upcoming_appointments = (
            db.query(Appointment)
            .filter(Appointment.assigned_agent_id == a.id, Appointment.status == "scheduled")
            .count()
        )
        active_deals = (
            db.query(Deal)
            .filter(Deal.assigned_agent_id == a.id, Deal.status.notin_(["closed_won", "closed_lost"]))
            .count()
        )

        results.append({
            "id": a.id,
            "email": a.email,
            "username": a.username,
            "full_name": a.full_name,
            "role": a.role,
            "roles": rbac.public_role_view(role_keys),
            "is_active": a.is_active,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "last_login_at": a.last_login_at.isoformat() if a.last_login_at else None,
            "workload": {
                "assigned_leads": assigned_leads,
                "hot_leads": hot_leads,
                "warm_leads": warm_leads,
                "cold_leads": cold_leads,
                "pending_followups": pending_followups,
                "overdue_followups": overdue_followups,
                "upcoming_appointments": upcoming_appointments,
                "active_deals": active_deals,
            },
        })
    return {"total": len(results), "agents": results}


@app.get("/api/admin/agents/{agent_id}")
def admin_get_agent(
    agent_id: int,
    db: Session = Depends(get_db),
    admin: Agent = Depends(require_permissions("users.read", "leads.read_all", mode="any")),
):
    """Retrieve detailed agent profile with complete workload and recent leads."""
    a = db.query(Agent).filter(Agent.id == agent_id).first()
    if a is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    role_keys = load_role_keys(db, a)
    now = datetime.utcnow()
    assigned_leads_query = db.query(Lead).filter(Lead.assigned_agent_id == a.id)
    assigned_leads = assigned_leads_query.count()
    hot_leads = assigned_leads_query.filter(Lead.temperature == "hot").count()
    warm_leads = assigned_leads_query.filter(Lead.temperature == "warm").count()
    cold_leads = assigned_leads_query.filter(Lead.temperature == "cold").count()

    pending_followups = (
        db.query(FollowUp)
        .join(Lead, FollowUp.lead_id == Lead.id)
        .filter(Lead.assigned_agent_id == a.id, FollowUp.is_completed.is_(False))
        .count()
    )
    overdue_followups = (
        db.query(FollowUp)
        .join(Lead, FollowUp.lead_id == Lead.id)
        .filter(
            Lead.assigned_agent_id == a.id,
            FollowUp.is_completed.is_(False),
            FollowUp.due_at < now,
        )
        .count()
    )
    upcoming_appointments = (
        db.query(Appointment)
        .filter(Appointment.assigned_agent_id == a.id, Appointment.status == "scheduled")
        .count()
    )
    recent_leads = [
        lead_summary(l) for l in assigned_leads_query.order_by(Lead.updated_at.desc()).limit(10).all()
    ]
    return {
        "agent": {
            "id": a.id,
            "email": a.email,
            "username": a.username,
            "full_name": a.full_name,
            "role": a.role,
            "roles": rbac.public_role_view(role_keys),
            "is_active": a.is_active,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "last_login_at": a.last_login_at.isoformat() if a.last_login_at else None,
            "workload": {
                "assigned_leads": assigned_leads,
                "hot_leads": hot_leads,
                "warm_leads": warm_leads,
                "cold_leads": cold_leads,
                "pending_followups": pending_followups,
                "overdue_followups": overdue_followups,
                "upcoming_appointments": upcoming_appointments,
            },
            "recent_leads": recent_leads,
        }
    }


@app.post("/api/admin/agents")
def admin_create_agent(
    payload: AdminAgentCreateRequest,
    request: Request = None,
    db: Session = Depends(get_db),
    admin: Agent = Depends(require_permissions("users.create")),
):
    """Create a new sales-agent account with secure credentials."""
    email = payload.email.strip().lower()
    if "@" not in email:
        raise HTTPException(status_code=422, detail="Invalid email address")
    username = (payload.username or email.split("@")[0]).strip().lower()

    if db.query(Agent).filter(func.lower(Agent.email) == email).first():
        raise HTTPException(status_code=409, detail="An account with this email exists")
    if db.query(Agent).filter(func.lower(Agent.username) == username).first():
        raise HTTPException(status_code=409, detail="This username is taken")

    raw_password = payload.password or (secrets.token_urlsafe(9) + "A1!")
    role = rbac.normalize_role(payload.role or "agent")
    new_agent = Agent(
        email=email,
        username=username,
        full_name=payload.full_name.strip(),
        password_hash=hash_password(raw_password),
        role=role,
        is_active=True,
    )
    db.add(new_agent)
    db.commit()
    db.refresh(new_agent)

    auditlog.write_audit(
        db, auditlog.USER_CREATED, actor_type="staff", actor_id=admin.id,
        actor_label=admin.email, subject_type="staff", subject_id=new_agent.id,
        subject_label=new_agent.email, ip=auditlog.client_ip(request),
        detail=f"role={role}; created via admin agent management",
    )
    return {
        "agent": {
            "id": new_agent.id,
            "email": new_agent.email,
            "username": new_agent.username,
            "full_name": new_agent.full_name,
            "role": new_agent.role,
            "is_active": new_agent.is_active,
        },
        "temporary_password": raw_password if payload.password is None else None,
    }


@app.post("/api/admin/agents/{agent_id}/reset-password")
def admin_reset_agent_password(
    agent_id: int,
    payload: AdminAgentResetPasswordRequest,
    request: Request = None,
    db: Session = Depends(get_db),
    admin: Agent = Depends(require_permissions("users.update")),
):
    """Reset credentials for an agent, generate temporary password and revoke active sessions."""
    target = db.query(Agent).filter(Agent.id == agent_id).first()
    if target is None:
        raise HTTPException(status_code=404, detail="Agent not found")

    temp_pw = payload.temporary_password or (secrets.token_urlsafe(9) + "A1!")
    target.password_hash = hash_password(temp_pw)
    target.must_change_password = True
    target.failed_login_count = 0
    target.locked_until = None
    db.add(target)
    db.commit()

    revoked = revoke_all_sessions(db, target.id)
    auditlog.write_audit(
        db, auditlog.PASSWORD_RESET, actor_type="staff", actor_id=admin.id,
        actor_label=admin.email, subject_type="staff", subject_id=target.id,
        subject_label=target.email, ip=auditlog.client_ip(request),
        detail=f"temporary password generated; revoked {revoked} active sessions",
    )
    return {
        "agent_id": target.id,
        "email": target.email,
        "temporary_password": temp_pw,
        "revoked_sessions": revoked,
        "message": f"Password reset successfully. {revoked} active sessions revoked.",
    }


@app.patch("/api/admin/agents/{agent_id}/status")
def admin_update_agent_status(
    agent_id: int,
    payload: AdminAgentStatusRequest,
    request: Request = None,
    db: Session = Depends(get_db),
    admin: Agent = Depends(require_permissions("users.suspend")),
):
    """Enable or disable an agent account. Disabling revokes all active sessions."""
    target = db.query(Agent).filter(Agent.id == agent_id).first()
    if target is None:
        raise HTTPException(status_code=404, detail="Agent not found")
    if target.id == admin.id and not payload.is_active:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account")

    if target.role in ("superadmin", "admin") and not payload.is_active:
        active_admins = db.query(Agent).filter(Agent.role.in_(["superadmin", "admin"]), Agent.is_active.is_(True)).count()
        if active_admins <= 1:
            raise HTTPException(status_code=400, detail="Cannot deactivate the last system administrator account")

    target.is_active = payload.is_active
    if not target.is_active:
        revoked = revoke_all_sessions(db, target.id)
        event = auditlog.ACCOUNT_SUSPENDED
        detail = f"deactivated by admin; revoked {revoked} sessions"
    else:
        target.failed_login_count = 0
        target.locked_until = None
        event = auditlog.ACCOUNT_REACTIVATED
        detail = "reactivated by admin"
        revoked = 0

    db.add(target)
    db.commit()
    auditlog.write_audit(
        db, event, actor_type="staff", actor_id=admin.id, actor_label=admin.email,
        subject_type="staff", subject_id=target.id, subject_label=target.email,
        ip=auditlog.client_ip(request), detail=detail,
    )
    return {
        "agent": {
            "id": target.id,
            "email": target.email,
            "full_name": target.full_name,
            "is_active": target.is_active,
        },
        "revoked_sessions": revoked,
    }


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
    agent: Agent = Depends(
        require_permissions("leads.read_assigned", "leads.read_all", mode="any")
    ),
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
        "sales_ops": compute_sales_ops_summary(db, agent),
        "recent_leads": [lead_summary(l) for l in recent_leads],
        "recent_conversations": recent_conversations,
    }


def _conversation_row(conv: Conversation) -> dict:
    """Row shape for conversation lists (with last-message preview)."""
    last = conv.messages[-1] if conv.messages else None
    lead = conv.lead
    return {
        "id": conv.id,
        "customer_name": conv.customer_name or (lead.name if lead else None) or "Anonymous Visitor",
        "customer_phone": conv.customer_phone or (lead.phone if lead else None),
        "customer_email": conv.customer_email or (lead.email if lead else None),
        "lead_id": conv.lead_id,
        "lead_name": lead.name if lead else None,
        "lead_status": lead.status if lead else None,
        "status": conv.status,
        "message_count": len(conv.messages or []),
        "last_message_preview": (last.content[:160] if last and last.content else ""),
        "last_message_role": last.role if last else None,
        "created_at": conv.created_at.isoformat() if conv.created_at else None,
        "updated_at": conv.updated_at.isoformat() if conv.updated_at else None,
    }


def _format_lead_duplicates(db: Session, agent: Agent, lead: Lead) -> list:
    """Format duplicate matches for a lead while strictly enforcing scope."""
    matches = find_all_duplicates(
        db, phone=lead.phone, email=lead.email, exclude_lead_id=lead.id
    )
    out = []
    for dup, matched_by in matches:
        in_scope = lead_in_scope(agent, dup)
        reasons_list = [r.strip() for r in str(matched_by).split("+") if r.strip()]
        if in_scope:
            out.append({
                "id": dup.id,
                "lead_id": dup.id,
                "matched_by": matched_by,
                "match_reasons": reasons_list,
                "in_scope": True,
                "name": dup.name or "Not provided",
                "phone": dup.phone or "Not provided",
                "email": dup.email or "Not provided",
                "status": dup.status or "new",
                "assigned_agent_id": dup.assigned_agent_id,
                "assigned_agent_name": dup.assigned_agent.full_name if dup.assigned_agent else None,
                "created_at": dup.created_at.isoformat() if dup.created_at else None,
            })
        else:
            out.append({
                "id": None,
                "lead_id": None,
                "matched_by": matched_by,
                "match_reasons": reasons_list,
                "in_scope": False,
                "name": None,
                "phone": None,
                "email": None,
                "status": None,
                "assigned_agent_id": None,
                "assigned_agent_name": "Assigned to another agent",
                "created_at": None,
            })
    return out


def _format_recommendation_row(db: Session, r: PropertyRecommendation) -> dict:
    """Serialize one PropertyRecommendation row with publication & provenance metadata."""
    reasons = _json_maybe(r.match_reasons)
    mismatches = _json_maybe(r.match_mismatches)
    link_type = "chat_dataset"
    relation_status = "recommended"
    if isinstance(reasons, list):
        for item in reasons:
            if isinstance(item, str) and item.startswith("manual_link:"):
                link_type = "manual"
                relation_status = item.split(":", 1)[1].strip() or "shortlisted"
                break
    if link_type != "manual" and r.property_record_id is not None:
        link_type = "auto_match"

    prop_title = None
    prop_approved = None
    prop_availability = None
    prop_purpose = None
    prop_source = None
    dataset_warning = None

    if r.property_record_id is not None:
        prop = db.query(Property).filter(Property.id == r.property_record_id).first()
        if prop is not None:
            prop_title = prop.title
            prop_approved = bool(prop.is_approved)
            prop_availability = prop.availability
            prop_purpose = prop.purpose
            prop_source = prop.source
            if prop.source == "uae_dataset" or str(prop.source or "").startswith("dataset"):
                dataset_warning = (
                    "Imported from UAE reference dataset — verify title/availability "
                    "details before contract commitment."
                )
    elif r.property_id is not None:
        dataset_warning = (
            "Unverified UAE dataset reference — purpose and live availability "
            "are not verified in the CRM inventory."
        )

    return {
        "id": r.id,
        "lead_id": r.lead_id,
        "property_id": r.property_id,
        "property_record_id": r.property_record_id,
        "property_title": prop_title,
        "property_approved": prop_approved,
        "property_availability": prop_availability,
        "property_purpose": prop_purpose,
        "property_source": prop_source,
        "link_type": link_type,
        "recommendation_source": link_type,
        "relation_status": relation_status,
        "dataset_warning": dataset_warning,
        "dataset_unverified": bool(dataset_warning),
        "match_score": r.match_score,
        "match_reasons": reasons,
        "match_mismatches": mismatches,
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


@app.post("/api/agent/leads")
def agent_create_lead(
    payload: LeadCreate,
    request: Request = None,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("leads.create")),
):
    """Create a lead from REVIEWED, explicitly-confirmed details (staff only).

    Deliberate workflow — no OpenAI call happens here (the agent already
    reviewed/edited the extraction): validate → idempotency check →
    conservative duplicate check (409 unless duplicate_override) → validate
    referenced records → build Lead → deterministic server-side score →
    link conversation → one commit.
    """
    if not payload.confirm:
        raise HTTPException(status_code=422, detail=(
            "Explicit confirmation of the reviewed details is required "
            "(set confirm=true after reviewing them)"))
    if not payload.name or len(payload.name.strip()) < 2:
        raise HTTPException(status_code=422, detail="Lead name is required (minimum 2 characters)")
    if not (payload.phone and payload.phone.strip()) and not (payload.email and payload.email.strip()):
        raise HTTPException(status_code=422, detail="At least one contact method (phone or email) is required")
    if (payload.budget_min is not None and payload.budget_max is not None
            and payload.budget_min > payload.budget_max):
        raise HTTPException(status_code=422,
                            detail="budget_min cannot exceed budget_max")

    # ---- optional idempotency key: safe retry protection ----
    if payload.idempotency_key:
        existing_idem = find_lead_by_idempotency_key(db, payload.idempotency_key)
        if existing_idem is not None and lead_in_scope(agent, existing_idem):
            score_idem = score_lead(lead_to_extraction(existing_idem))
            return {
                "lead": lead_detail(existing_idem),
                "score": _score_payload(score_idem),
                "duplicate": None,
                "idempotent_replay": True,
            }

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
            linked = db.query(Lead).filter(Lead.id == conversation.lead_id).first()
            in_scope = linked is not None and lead_in_scope(agent, linked)
            raise HTTPException(status_code=409, detail={
                "message": "That conversation is already linked to another lead",
                "code": "conversation_linked",
                "lead_id": conversation.lead_id if in_scope else None,
            })
    if payload.customer_id is not None:
        customer = _resolve_customer(db, payload.customer_id)
        if (conversation is not None and conversation.customer_id is not None
                and conversation.customer_id != customer.id):
            raise HTTPException(status_code=422, detail=(
                "The selected conversation belongs to a different customer"))

    use_round_robin = payload.assignment_mode == "round_robin"
    if use_round_robin and not rbac.has_permission(agent, "leads.assign"):
        raise HTTPException(
            status_code=403,
            detail="Only administrators or sales managers may run round-robin assignment",
        )

    if payload.assigned_agent_id is not None and not use_round_robin:
        assigned_id = _resolve_agent(db, agent, payload.assigned_agent_id)
    elif not use_round_robin and not rbac.has_permission(agent, "leads.read_all"):
        # A sales agent without global lead permissions creates a lead assigned to themselves
        assigned_id = agent.id
    else:
        assigned_id = None

    # extraction_source derives from the reviewed provenance (deterministic)
    claims = {v for v in payload.provenance.values()
              if v in ("explicit", "inferred")}
    extraction_source = ("explicit" if claims in (set(), {"explicit"})
                         else "inferred" if claims == {"inferred"} else "mixed")
    budget_currency = (payload.budget_currency.upper()
                       if payload.budget_currency else None)

    qualification_meta = {
        "preferred_language": (payload.preferred_language or "").strip() or None,
        "emirate": (payload.emirate or "").strip() or None,
        "financing_type": payload.financing_type,
        "preferred_viewing_time": (payload.preferred_viewing_time or "").strip() or None,
        "qualification_status": payload.qualification_status,
        "next_action": (payload.next_action or "").strip() or None,
        "field_provenance": payload.provenance or None,
        "idempotency_key": (payload.idempotency_key or "").strip() or None,
    }

    rr_chosen = None
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
            requirements=encode_preferences(payload.preferences, qualification_meta),
            investment_purpose=(payload.investment_purpose or "").strip() or None,
            timeline=(payload.timeline or "").strip() or None,
            timeline_days=payload.timeline_days,
            status=payload.status,
            notes=(payload.notes or "").strip() or None,
            source="Agent CRM",
            extraction_source=extraction_source,
            creator_agent_id=agent.id,
            assigned_agent_id=assigned_id,
            last_interaction_at=datetime.utcnow() if conversation else None,
        )
        db.add(lead)
        db.flush()  # assigns lead.id; still fully rollback-able
        if use_round_robin:
            rr_chosen = assign_lead_round_robin(db, lead)
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
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:  # noqa: BLE001 — boundary: rollback, log class only
        db.rollback()
        logger.error("lead create failed: %s", type(exc).__name__)  # no PII
        raise HTTPException(status_code=500, detail="Lead could not be saved")
    db.refresh(lead)
    auditlog.write_audit(
        db, auditlog.LEAD_CREATED, actor_type="staff", actor_id=agent.id,
        actor_label=agent.email, subject_type="lead", subject_id=lead.id,
        subject_label=lead.name or f"Lead #{lead.id}", ip=auditlog.client_ip(request),
        detail=f"status={lead.status}; assigned={lead.assigned_agent_id}",
    )
    if rr_chosen is not None:
        auditlog.write_audit(
            db, auditlog.LEAD_ROUND_ROBIN_ASSIGNED, actor_type="staff",
            actor_id=agent.id, actor_label=agent.email, subject_type="lead",
            subject_id=lead.id, subject_label=lead.name or f"Lead #{lead.id}",
            ip=auditlog.client_ip(request),
            detail=f"from=None; to={rr_chosen.id}; agent={rr_chosen.email}",
        )
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
    temperature: Optional[Literal["hot", "warm", "cold", "unclassified"]] = None,
    intent: Optional[str] = Query(
        None, description="buy|rent|lease|unknown", pattern="^(buy|rent|lease|unknown)$"),
    location: Optional[str] = None,
    property_type: Optional[str] = None,
    assigned_agent_id: Optional[int] = None,
    unassigned: Optional[bool] = None,
    follow_up: Optional[Literal[
        "pending", "overdue", "due_today", "upcoming", "completed", "cancelled"]] = None,
    q: Optional[str] = None,
    synthetic: Optional[bool] = Query(None, description="Filter synthetic benchmark records (True=synthetic only, False=genuine only)"),
    sort: Optional[str] = Query("newest", pattern="^(newest|interaction|score)$"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    agent: Agent = Depends(
        require_permissions("leads.read_assigned", "leads.read_all", mode="any")
    ),
):
    """Lead list: search + validated filters + stable deterministic order.

    Scoped: agents only ever receive their own + unassigned leads (the
    server re-applies the scope to every query — it never trusts the UI).
    `follow_up=overdue|due_today|upcoming|pending|completed|cancelled` selects
    leads with at least one follow-up in that bucket (UTC day boundaries).
    """
    query = scoped_lead_query(db, agent)

    if status:
        query = query.filter(Lead.status == status)
    if priority == "unscored":
        query = query.filter(Lead.priority.is_(None))
    elif priority:
        query = query.filter(Lead.priority == priority)
    if temperature == "unclassified":
        query = query.filter(Lead.temperature.is_(None))
    elif temperature:
        query = query.filter(Lead.temperature == temperature)
    if intent:
        query = query.filter(Lead.buy_rent == intent)
    if location:
        query = query.filter(Lead.location.ilike(f"%{location}%"))
    if property_type:
        query = query.filter(Lead.property_type.ilike(f"%{property_type}%"))
    if unassigned is True:
        query = query.filter(Lead.assigned_agent_id.is_(None))
    elif assigned_agent_id is not None:
        query = query.filter(Lead.assigned_agent_id == assigned_agent_id)
    if synthetic is not None:
        query = query.filter(Lead.is_synthetic.is_(synthetic))
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
    elif sort == "score":
        query = query.order_by(
            Lead.lead_score.is_(None),
            Lead.lead_score.desc(),
            Lead.id.desc(),
        )
    else:
        query = query.order_by(Lead.created_at.desc(), Lead.id.desc())

    leads = query.offset(offset).limit(limit).all()
    return {"total": total, "results": [lead_summary(l) for l in leads]}


@app.get("/api/agent/leads/{lead_id}")
def agent_get_lead(
    lead_id: int,
    db: Session = Depends(get_db),
    agent: Agent = Depends(
        require_permissions("leads.read_assigned", "leads.read_all", mode="any")
    ),
):
    """Full lead detail: profile, every AI conversation, all recommendations.

    Includes the Phase 5 review fields (score/priority/breakdown, missing
    fields, follow-ups) via `lead_detail`, plus the linked customer account
    (resolved through the linked conversation — `leads` has no customer FK).
    """
    lead = _scoped_lead_or_404(db, agent, lead_id)

    # Reconcile unlinked conversations matching this lead's email, phone, or customer account
    if lead.email or lead.phone:
        norm_email = lead.email.strip().lower() if lead.email else None
        norm_phone = lead.phone.strip() if lead.phone else None
        
        matching_cust_ids = [
            c[0] for c in db.query(Customer.id).filter(
                ((func.lower(Customer.email) == norm_email) if norm_email else False) |
                ((Customer.phone == norm_phone) if norm_phone else False)
            ).all()
        ]
        
        conv_filter = (
            ((func.lower(Conversation.customer_email) == norm_email) if norm_email else False) |
            ((Conversation.customer_phone == norm_phone) if norm_phone else False) |
            (Conversation.customer_id.in_(matching_cust_ids) if matching_cust_ids else False)
        )
        
        unlinked_matches = (
            db.query(Conversation)
            .filter(Conversation.lead_id.is_(None), conv_filter)
            .all()
        )
        if unlinked_matches:
            for cv in unlinked_matches:
                cv.lead_id = lead.id
            try:
                db.commit()
            except Exception:
                db.rollback()

    conversations = (
        db.query(Conversation)
        .filter(Conversation.lead_id == lead.id)
        .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
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

    # Linked customer account (through linked conversations, or matching customer email/phone)
    customer_account = None
    customer_ids = sorted({c.customer_id for c in conversations
                           if c.customer_id is not None})
    if customer_ids:
        cust = db.query(Customer).filter(Customer.id == customer_ids[0]).first()
        if cust is not None:
            customer_account = {"id": cust.id, "name": cust.name,
                                "email": cust.email}
    elif lead.email or lead.phone:
        cust_match = None
        if lead.email:
            cust_match = db.query(Customer).filter(func.lower(Customer.email) == lead.email.strip().lower()).first()
        if not cust_match and lead.phone:
            cust_match = db.query(Customer).filter(Customer.phone == lead.phone.strip()).first()
        if cust_match is not None:
            customer_account = {"id": cust_match.id, "name": cust_match.name, "email": cust_match.email}

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
            _format_recommendation_row(db, r)
            for r in recs
        ],
        "duplicates": _format_lead_duplicates(db, agent, lead),
        "appointments": [
            appointment_to_dict(a, db)
            for a in (
                db.query(Appointment)
                .filter(Appointment.lead_id == lead.id)
                .order_by(Appointment.start_at.desc(), Appointment.id.desc())
                .all()
            )
        ],
        "offers": [
            offer_to_dict(o)
            for o in (
                db.query(Offer)
                .filter(Offer.lead_id == lead.id)
                .order_by(Offer.created_at.desc(), Offer.id.desc())
                .all()
            )
        ],
        "deals": [
            deal_to_dict(d)
            for d in (
                db.query(Deal)
                .filter(Deal.lead_id == lead.id)
                .order_by(Deal.created_at.desc(), Deal.id.desc())
                .all()
            )
        ],
        "activity": lead_activity_history(db, lead.id, limit=50),
    }


@app.patch("/api/agent/leads/{lead_id}")
def agent_update_lead(
    lead_id: int,
    update: LeadUpdate,
    request: Request = None,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("leads.update")),
):
    """Partial update: contact/requirement fields, assignment, status.

    - Score & priority are RECOMPUTED server-side whenever requirement
      fields change; a client-supplied score is never accepted (LeadUpdate
      has no score field).
    - Status transitions are validated server-side (reopening a closed_won or
      closed_lost lead requires reopen=true).
    - `conversation_id` is validated: a new link must be visible to the
      caller and unlinked (or already this lead's); explicit null unlinks.
    - Unrelated fields stay untouched; every failure happens before commit.
    """
    lead = _scoped_lead_or_404(db, agent, lead_id)
    fields = update.model_dump(exclude_unset=True)

    _MISSING = object()
    reopen_flag = bool(fields.pop("reopen", False))
    status_reason = fields.pop("status_reason", None)
    assignment_reason = fields.pop("assignment_reason", None)

    old_status = lead.status or "new"
    old_agent_id = lead.assigned_agent_id

    # --- validations (all before any mutation) ---
    if "status" in fields and fields["status"] is not None:
        try:
            fields["status"] = validate_status_transition(
                old_status, fields["status"], reopen=reopen_flag
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
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
        if target is None:
            if lead.assigned_agent_id is not None and not rbac.has_permission(agent, "leads.assign"):
                raise HTTPException(
                    status_code=403,
                    detail="Only an admin can unassign leads",
                )
        else:
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

    # --- Phase 5 & Phase E specials (keys that are not plain Lead columns) ---
    budget_period = fields.pop("budget_period", _MISSING)   # None = clear period
    preferences = fields.pop("preferences", _MISSING)
    conversation_id = fields.pop("conversation_id", _MISSING)

    meta_updates = {}
    for mkey in (
        "preferred_language",
        "emirate",
        "financing_type",
        "preferred_viewing_time",
        "qualification_status",
        "next_action",
        "field_provenance",
    ):
        if mkey in fields:
            meta_updates[mkey] = fields.pop(mkey)

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
                linked = db.query(Lead).filter(Lead.id == conv.lead_id).first()
                in_scope = linked is not None and lead_in_scope(agent, linked)
                raise HTTPException(status_code=409, detail={
                    "message": "That conversation is already linked to another lead",
                    "code": "conversation_linked",
                    "lead_id": conv.lead_id if in_scope else None,
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
    if "temperature" in fields and fields["temperature"] is not None:
        lead.temperature_source = "manual"
        lead.temperature_updated_at = datetime.utcnow()

    current_meta = get_qualification_meta(lead)
    existing_prov = dict(current_meta.get("field_provenance") or {})
    if existing_prov:
        prov_map = {
            "name": "name",
            "phone": "contact",
            "email": "contact",
            "buy_rent": "intent",
            "location": "location",
            "property_type": "property_type",
            "bedrooms": "bedrooms",
            "budget_min": "budget",
            "budget_max": "budget",
            "budget": "budget",
            "timeline": "timeline",
            "timeline_days": "timeline",
            "investment_purpose": "investment_purpose",
        }
        prov_changed = False
        for edited_col in fields.keys():
            ck = prov_map.get(edited_col)
            if ck and existing_prov.get(ck) == "inferred":
                existing_prov[ck] = "explicit"
                prov_changed = True
            if edited_col in existing_prov and existing_prov.get(edited_col) == "inferred":
                existing_prov[edited_col] = "explicit"
                prov_changed = True
        if prov_changed:
            meta_updates["field_provenance"] = existing_prov
            if all(v != "inferred" for v in existing_prov.values()):
                lead.extraction_source = "explicit"

    if preferences is not _MISSING or meta_updates:
        current_prefs = preferences if preferences is not _MISSING else get_preferences(lead)
        if meta_updates:
            for mk, mv in meta_updates.items():
                if mv in (None, ""):
                    current_meta.pop(mk, None)
                else:
                    current_meta[mk] = mv
        lead.requirements = encode_preferences(current_prefs, current_meta)

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
            or budget_period is not _MISSING
            or bool(meta_updates)):
        result = recompute_lead_score(lead)

    lead.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(lead)

    # --- audit trail for status changes, assignments, and qualification updates ---
    new_status = lead.status or "new"
    if new_status != old_status:
        evt = (
            auditlog.LEAD_REOPENED
            if old_status in TERMINAL_LEAD_STATUSES
            else auditlog.LEAD_STATUS_CHANGED
        )
        reason_suffix = f" ({status_reason.strip()})" if status_reason and status_reason.strip() else ""
        auditlog.write_audit(
            db, evt, actor_type="staff", actor_id=agent.id, actor_label=agent.email,
            subject_type="lead", subject_id=lead.id,
            subject_label=lead.name or f"Lead #{lead.id}",
            ip=auditlog.client_ip(request),
            detail=f"{old_status}->{new_status}{reason_suffix}",
        )
    if lead.assigned_agent_id != old_agent_id:
        evt = auditlog.LEAD_UNASSIGNED if lead.assigned_agent_id is None else auditlog.LEAD_ASSIGNED
        reason_suffix = f" ({assignment_reason.strip()})" if assignment_reason and assignment_reason.strip() else ""
        auditlog.write_audit(
            db, evt, actor_type="staff", actor_id=agent.id, actor_label=agent.email,
            subject_type="lead", subject_id=lead.id,
            subject_label=lead.name or f"Lead #{lead.id}",
            ip=auditlog.client_ip(request),
            detail=f"from={old_agent_id}; to={lead.assigned_agent_id}{reason_suffix}",
        )
    elif result is not None or meta_updates:
        auditlog.write_audit(
            db, auditlog.LEAD_QUALIFIED, actor_type="staff", actor_id=agent.id,
            actor_label=agent.email, subject_type="lead", subject_id=lead.id,
            subject_label=lead.name or f"Lead #{lead.id}",
            ip=auditlog.client_ip(request),
            detail=f"score={lead.lead_score}; priority={lead.priority}",
        )

    return {"lead": lead_detail(lead),
            "score": _score_payload(result) if result is not None else None}


@app.post("/api/agent/leads/extract")
def agent_extract_lead(
    payload: LeadExtractionRequest,
    agent: Agent = Depends(
        require_permissions("leads.create", "leads.update", mode="any")
    ),
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
    agent: Agent = Depends(
        require_permissions(
            "leads.read_assigned", "leads.read_all", "leads.create", "leads.update",
            mode="any",
        )
    ),
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
    agent: Agent = Depends(require_permissions("properties.read")),
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
    request: Request = None,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("followups.manage_assigned")),
):
    """Schedule a follow-up for a lead in this agent's scope (staff only).

    Validates type (CHECK-matching set), due date, priority, and the optional
    agent (admins may assign anyone active; agents may only assign themselves).
    """
    lead = _scoped_lead_or_404(db, agent, lead_id)
    assigned_id = (_resolve_agent(db, agent, payload.assigned_agent_id)
                   if payload.assigned_agent_id is not None else agent.id)
    try:
        fu = create_followup(
            db, lead=lead, fu_type=payload.type, due_at=payload.due_at,
            notes=payload.notes, assigned_agent_id=assigned_id,
            priority=payload.priority)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
    db.refresh(fu)
    auditlog.write_audit(
        db, auditlog.FOLLOWUP_CREATED, actor_type="staff", actor_id=agent.id,
        actor_label=agent.email, subject_type="lead", subject_id=lead.id,
        subject_label=lead.name or f"Lead #{lead.id}", ip=auditlog.client_ip(request),
        detail=f"followup_id={fu.id}; type={fu.type}; assigned={fu.assigned_agent_id}",
    )
    return {"follow_up": follow_up_summary(fu)}


@app.get("/api/agent/leads/{lead_id}/follow-ups")
def agent_lead_followups(
    lead_id: int,
    include_completed: bool = True,
    db: Session = Depends(get_db),
    agent: Agent = Depends(
        require_permissions(
            "followups.manage_assigned", "leads.read_assigned", "leads.read_all",
            mode="any",
        )
    ),
):
    """All follow-ups of a lead in this agent's scope (oldest due first)."""
    lead = _scoped_lead_or_404(db, agent, lead_id)
    rows = list_lead_followups(db, lead, include_completed=include_completed)
    return {"results": [follow_up_summary(f) for f in rows]}


@app.get("/api/agent/follow-ups")
def agent_list_followups(
    filter: Literal[
        "all", "pending", "overdue", "due_today", "upcoming", "completed", "cancelled"
    ] = Query("pending"),
    state: Optional[Literal[
        "all", "pending", "overdue", "due_today", "upcoming", "completed", "cancelled"
    ]] = Query(None),
    lead_id: Optional[int] = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    agent: Agent = Depends(
        require_permissions(
            "followups.manage_assigned", "leads.read_assigned", "leads.read_all",
            mode="any",
        )
    ),
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
        query = filter_followups(query, state or filter)
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
    request: Request = None,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("followups.manage_assigned")),
):
    """Update one follow-up (type/due/notes/completion/cancellation/assignment).

    The follow-up's lead must be inside the caller's scope (404 otherwise —
    existence is never leaked). Completing stamps `completed_at`; restoring
    clears it.
    """
    fu = db.query(FollowUp).filter(FollowUp.id == follow_up_id).first()
    if fu is None or not lead_in_scope(agent, fu.lead):
        raise HTTPException(status_code=404, detail="Follow-up not found")

    was_completed = bool(fu.is_completed)
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
    summary = follow_up_summary(fu)
    evt = (
        auditlog.FOLLOWUP_CANCELLED
        if summary.get("is_cancelled")
        else (
            auditlog.FOLLOWUP_COMPLETED
            if fu.is_completed and not was_completed
            else auditlog.FOLLOWUP_UPDATED
        )
    )
    auditlog.write_audit(
        db, evt, actor_type="staff", actor_id=agent.id, actor_label=agent.email,
        subject_type="lead", subject_id=fu.lead_id,
        subject_label=f"Lead #{fu.lead_id}", ip=auditlog.client_ip(request),
        detail=f"followup_id={fu.id}; status={summary.get('status')}",
    )
    return {"follow_up": summary}


@app.post("/api/agent/follow-ups/{follow_up_id}/cancel")
def agent_cancel_followup(
    follow_up_id: int,
    payload: Optional[FollowUpCancelRequest] = None,
    request: Request = None,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("followups.manage_assigned")),
):
    """Explicitly cancel a scheduled follow-up (preserving history)."""
    fu = db.query(FollowUp).filter(FollowUp.id == follow_up_id).first()
    if fu is None or not lead_in_scope(agent, fu.lead):
        raise HTTPException(status_code=404, detail="Follow-up not found")

    reason = (payload.reason or payload.cancel_reason) if payload is not None else None
    try:
        cancel_followup(db, fu, reason=reason)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
    db.refresh(fu)
    summary = follow_up_summary(fu)
    auditlog.write_audit(
        db, auditlog.FOLLOWUP_CANCELLED, actor_type="staff", actor_id=agent.id,
        actor_label=agent.email, subject_type="lead", subject_id=fu.lead_id,
        subject_label=f"Lead #{fu.lead_id}", ip=auditlog.client_ip(request),
        detail=f"followup_id={fu.id}; reason={(reason or '').strip()[:100]}",
    )
    return {"follow_up": summary}


# ---------------- Phase E: Lifecycle, Assignment, Merge & Property Links ---

@app.get("/api/agent/sales-agents")
def agent_list_sales_agents(
    db: Session = Depends(get_db),
    agent: Agent = Depends(
        require_permissions("leads.read_assigned", "leads.read_all", mode="any")
    ),
):
    """List active sales agents and their active lead counts for assignment UI."""
    rows = (
        db.query(Agent)
        .filter(Agent.is_active.is_(True), Agent.role.in_(("agent", "admin", "sales_manager")))
        .order_by(Agent.id.asc())
        .all()
    )
    counts = dict(
        db.query(Lead.assigned_agent_id, func.count(Lead.id))
        .filter(
            Lead.assigned_agent_id.isnot(None),
            ~Lead.status.in_(("closed_won", "closed_lost")),
        )
        .group_by(Lead.assigned_agent_id)
        .all()
    )
    return {
        "results": [
            {
                "id": a.id,
                "full_name": a.full_name,
                "email": a.email,
                "username": a.username,
                "role": a.role,
                "is_eligible_round_robin": a.role == "agent" and bool(a.is_active),
                "active_lead_count": counts.get(a.id, 0),
            }
            for a in rows
        ]
    }


@app.post("/api/agent/leads/{lead_id}/status")
def agent_transition_lead_status(
    lead_id: int,
    payload: LeadStatusTransitionRequest,
    request: Request = None,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("leads.update")),
):
    """Explicit, validated lead status transition (including authorized reopen)."""
    lead = _scoped_lead_or_404(db, agent, lead_id)
    old_status = lead.status or "new"
    try:
        target_status = validate_status_transition(
            old_status, payload.status, reopen=payload.reopen
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    lead.status = target_status
    lead.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(lead)

    if target_status != old_status:
        evt = (
            auditlog.LEAD_REOPENED
            if old_status in TERMINAL_LEAD_STATUSES
            else auditlog.LEAD_STATUS_CHANGED
        )
        reason_suffix = f" ({payload.reason.strip()})" if payload.reason and payload.reason.strip() else ""
        auditlog.write_audit(
            db, evt, actor_type="staff", actor_id=agent.id, actor_label=agent.email,
            subject_type="lead", subject_id=lead.id,
            subject_label=lead.name or f"Lead #{lead.id}",
            ip=auditlog.client_ip(request),
            detail=f"{old_status}->{target_status}{reason_suffix}",
        )

    return {"lead": lead_detail(lead)}


@app.post("/api/agent/leads/{lead_id}/assign")
def agent_assign_lead(
    lead_id: int,
    payload: LeadAssignRequest,
    request: Request = None,
    db: Session = Depends(get_db),
    agent: Agent = Depends(
        require_permissions("leads.update", "leads.assign", mode="any")
    ),
):
    """Assign, claim, unassign, or round-robin assign a lead with audit history."""
    lead = _scoped_lead_or_404(db, agent, lead_id)
    old_agent_id = lead.assigned_agent_id
    reason_suffix = f" ({payload.reason.strip()})" if payload.reason and payload.reason.strip() else ""

    if payload.mode == "claim":
        if lead.assigned_agent_id is not None and lead.assigned_agent_id != agent.id:
            if not rbac.has_permission(agent, "leads.assign"):
                raise HTTPException(
                    status_code=403,
                    detail="Lead is already assigned to another agent",
                )
        lead.assigned_agent_id = agent.id
        lead.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(lead)
        auditlog.write_audit(
            db, auditlog.LEAD_ASSIGNED, actor_type="staff", actor_id=agent.id,
            actor_label=agent.email, subject_type="lead", subject_id=lead.id,
            subject_label=lead.name or f"Lead #{lead.id}",
            ip=auditlog.client_ip(request),
            detail=f"from={old_agent_id}; to={agent.id}; mode=claim{reason_suffix}",
        )
        return {"lead": lead_detail(lead), "mode": "claim"}

    if payload.mode == "unassign":
        if not rbac.has_permission(agent, "leads.assign"):
            raise HTTPException(
                status_code=403,
                detail="Only administrators or sales managers may unassign leads",
            )
        lead.assigned_agent_id = None
        lead.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(lead)
        auditlog.write_audit(
            db, auditlog.LEAD_UNASSIGNED, actor_type="staff", actor_id=agent.id,
            actor_label=agent.email, subject_type="lead", subject_id=lead.id,
            subject_label=lead.name or f"Lead #{lead.id}",
            ip=auditlog.client_ip(request),
            detail=f"from={old_agent_id}; to=None{reason_suffix}",
        )
        return {"lead": lead_detail(lead), "mode": "unassign"}

    if payload.mode == "round_robin":
        if not rbac.has_permission(agent, "leads.assign"):
            raise HTTPException(
                status_code=403,
                detail="Only administrators or sales managers may run round-robin assignment",
            )
        try:
            chosen = assign_lead_round_robin(db, lead)
            db.commit()
        except ValueError as exc:
            db.rollback()
            raise HTTPException(status_code=422, detail=str(exc))
        db.refresh(lead)
        auditlog.write_audit(
            db, auditlog.LEAD_ROUND_ROBIN_ASSIGNED, actor_type="staff",
            actor_id=agent.id, actor_label=agent.email, subject_type="lead",
            subject_id=lead.id, subject_label=lead.name or f"Lead #{lead.id}",
            ip=auditlog.client_ip(request),
            detail=f"from={old_agent_id}; to={chosen.id}; agent={chosen.email}{reason_suffix}",
        )
        return {"lead": lead_detail(lead), "mode": "round_robin", "assigned_agent": _agent_public(chosen)}

    # mode == "manual"
    if not rbac.has_permission(agent, "leads.assign"):
        raise HTTPException(
            status_code=403,
            detail="Only administrators or sales managers may manually assign leads",
        )
    if payload.assigned_agent_id is None:
        raise HTTPException(
            status_code=422,
            detail="assigned_agent_id is required when mode='manual'",
        )
    target_id = _resolve_agent(db, agent, payload.assigned_agent_id)
    lead.assigned_agent_id = target_id
    lead.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(lead)
    auditlog.write_audit(
        db, auditlog.LEAD_ASSIGNED, actor_type="staff", actor_id=agent.id,
        actor_label=agent.email, subject_type="lead", subject_id=lead.id,
        subject_label=lead.name or f"Lead #{lead.id}",
        ip=auditlog.client_ip(request),
        detail=f"from={old_agent_id}; to={target_id}; mode=manual{reason_suffix}",
    )
    return {"lead": lead_detail(lead), "mode": "manual"}


@app.get("/api/agent/leads/{lead_id}/duplicates")
def agent_get_lead_duplicates(
    lead_id: int,
    db: Session = Depends(get_db),
    agent: Agent = Depends(
        require_permissions("leads.read_assigned", "leads.read_all", mode="any")
    ),
):
    """Inspect potential duplicate leads sharing phone or email with this lead."""
    lead = _scoped_lead_or_404(db, agent, lead_id)
    return {
        "lead_id": lead.id,
        "duplicates": _format_lead_duplicates(db, agent, lead),
    }


@app.post("/api/agent/leads/{lead_id}/merge")
def agent_merge_leads(
    lead_id: int,
    payload: LeadMergeRequest,
    request: Request = None,
    db: Session = Depends(get_db),
    agent: Agent = Depends(
        require_permissions("leads.update", "leads.assign", mode="any")
    ),
):
    """Authorized transactional merge of a duplicate lead (`source_lead_id`) into `lead_id`.

    Both records must be inside the caller's scope (never leaks or merges
    another agent's private lead). Merging across different assigned agents
    requires `leads.assign`.
    """
    if payload.source_lead_id == lead_id:
        raise HTTPException(status_code=422, detail="Cannot merge a lead into itself")

    target = _scoped_lead_or_404(db, agent, lead_id)
    source = _scoped_lead_or_404(db, agent, payload.source_lead_id)

    # If either lead belongs to a different agent, require leads.assign
    if (
        (target.assigned_agent_id not in (None, agent.id))
        or (source.assigned_agent_id not in (None, agent.id))
    ) and not rbac.has_permission(agent, "leads.assign"):
        raise HTTPException(
            status_code=403,
            detail="Only administrators or sales managers may merge leads assigned to other agents",
        )

    source_id = source.id
    try:
        merge_duplicate_leads(
            db,
            target=target,
            source=source,
            actor_label=agent.email,
            reason=payload.reason,
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.error("lead merge failed: %s", type(exc).__name__)
        raise HTTPException(status_code=500, detail="Lead merge could not be completed")

    db.refresh(target)
    reason_suffix = f" ({payload.reason.strip()})" if payload.reason and payload.reason.strip() else ""
    auditlog.write_audit(
        db, auditlog.LEAD_MERGED, actor_type="staff", actor_id=agent.id,
        actor_label=agent.email, subject_type="lead", subject_id=target.id,
        subject_label=target.name or f"Lead #{target.id}",
        ip=auditlog.client_ip(request),
        detail=f"merged_source={source_id}->target={target.id}{reason_suffix}",
    )
    merged_convs = (
        db.query(Conversation)
        .filter(Conversation.lead_id == target.id)
        .order_by(Conversation.created_at.asc())
        .all()
    )
    return {
        "lead": lead_detail(target),
        "merged_lead_id": source_id,
        "conversations": [{"id": c.id, "status": c.status} for c in merged_convs],
    }


@app.post("/api/agent/leads/{lead_id}/properties")
def agent_link_lead_property(
    lead_id: int,
    payload: LeadPropertyLinkRequest,
    request: Request = None,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("leads.update")),
):
    """Manually associate/shortlist a verified, approved, available property with a lead."""
    lead = _scoped_lead_or_404(db, agent, lead_id)
    prop = db.query(Property).filter(Property.id == payload.property_record_id).first()
    if prop is None:
        raise HTTPException(status_code=404, detail="Property not found")
    if not prop.is_approved:
        raise HTTPException(
            status_code=422,
            detail="Cannot shortlist or pitch an unapproved property as available inventory",
        )
    if prop.availability != "available":
        raise HTTPException(
            status_code=422,
            detail=f"Property is currently '{prop.availability}' and cannot be linked as available inventory",
        )

    reasons = [
        f"manual_link:{payload.relation_status}",
        f"Manually linked ({payload.relation_status}) by {agent.full_name or agent.email}",
    ]
    if prop.source == "uae_dataset":
        reasons.append(
            "Dataset-imported listing: verify developer & title deed details prior to contract"
        )

    existing = (
        db.query(PropertyRecommendation)
        .filter(
            PropertyRecommendation.lead_id == lead.id,
            PropertyRecommendation.property_record_id == prop.id,
        )
        .first()
    )
    hl = (payload.notes or payload.highlights or "").strip() or (prop.highlights or prop.title)
    was_already_linked = existing is not None
    if existing is not None:
        existing.match_reasons = json.dumps(reasons, ensure_ascii=False)
        existing.highlights = hl
        existing.price = f"{prop.price:,.0f} {prop.currency}"
        existing.property_type = prop.property_type
        existing.location = prop.location
        existing.bedrooms = prop.bedrooms
        existing.bathrooms = prop.bathrooms
        existing.area = f"{prop.area:g} {prop.area_unit}" if prop.area is not None else None
        rec = existing
    else:
        rec = PropertyRecommendation(
            lead_id=lead.id,
            property_record_id=prop.id,
            property_id=None,
            price=f"{prop.price:,.0f} {prop.currency}",
            property_type=prop.property_type,
            location=prop.location,
            bedrooms=prop.bedrooms,
            bathrooms=prop.bathrooms,
            area=f"{prop.area:g} {prop.area_unit}" if prop.area is not None else None,
            highlights=hl,
            match_score=None,
            match_reasons=json.dumps(reasons, ensure_ascii=False),
            match_mismatches=json.dumps([], ensure_ascii=False),
        )
        db.add(rec)

    db.commit()
    db.refresh(rec)
    auditlog.write_audit(
        db, auditlog.LEAD_PROPERTY_LINKED, actor_type="staff", actor_id=agent.id,
        actor_label=agent.email, subject_type="lead", subject_id=lead.id,
        subject_label=lead.name or f"Lead #{lead.id}",
        ip=auditlog.client_ip(request),
        detail=f"property_record_id={prop.id}; status={payload.relation_status}",
    )
    return {"recommendation": _format_recommendation_row(db, rec), "already_linked": was_already_linked}


@app.delete("/api/agent/leads/{lead_id}/properties/{recommendation_id}")
def agent_unlink_lead_property(
    lead_id: int,
    recommendation_id: int,
    request: Request = None,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("leads.update")),
):
    """Remove a property recommendation/shortlist link from a lead in scope."""
    lead = _scoped_lead_or_404(db, agent, lead_id)
    rec = (
        db.query(PropertyRecommendation)
        .filter(
            PropertyRecommendation.id == recommendation_id,
            PropertyRecommendation.lead_id == lead.id,
        )
        .first()
    )
    if rec is None:
        raise HTTPException(status_code=404, detail="Property link not found")
    prop_ref = rec.property_record_id or rec.property_id
    db.delete(rec)
    db.commit()
    auditlog.write_audit(
        db, auditlog.LEAD_PROPERTY_UNLINKED, actor_type="staff", actor_id=agent.id,
        actor_label=agent.email, subject_type="lead", subject_id=lead.id,
        subject_label=lead.name or f"Lead #{lead.id}",
        ip=auditlog.client_ip(request),
        detail=f"recommendation_id={recommendation_id}; property={prop_ref}",
    )
    return {"ok": True, "deleted_id": recommendation_id}


@app.get("/api/agent/leads/{lead_id}/activity")
def agent_get_lead_activity(
    lead_id: int,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    agent: Agent = Depends(
        require_permissions("leads.read_assigned", "leads.read_all", mode="any")
    ),
):
    """Chronological activity & audit history for a lead in the caller's scope."""
    lead = _scoped_lead_or_404(db, agent, lead_id)
    items = lead_activity_history(db, lead.id, limit=limit)
    return {
        "lead_id": lead.id,
        "results": items,
        "activity": items,
    }


# ---------------- Recommendations (Phase 4 matching + persistence) --------

@app.post("/api/agent/leads/{lead_id}/recommendations")
def agent_run_recommendations(
    lead_id: int,
    run: RecommendationRun,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("leads.update")),
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
    since: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    agent: Agent = Depends(
        require_permissions("conversations.read_authorized", "conversations.read_all", mode="any")
    ),
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

    if since:
        try:
            since_dt = datetime.fromisoformat(since.replace("Z", "+00:00")).replace(tzinfo=None)
            query = query.filter(Conversation.updated_at > since_dt)
        except ValueError:
            pass

    total = query.count()
    rows = (
        query.order_by(Conversation.updated_at.desc(), Conversation.id.desc())
        .offset(max(0, offset))
        .limit(max(1, min(500, limit)))
        .all()
    )
    latest_ts = rows[0].updated_at.isoformat() if rows and rows[0].updated_at else None
    return {
        "total": total,
        "results": [_conversation_row(c) for c in rows],
        "latest_timestamp": latest_ts,
    }


@app.get("/api/agent/conversations/{conversation_id}")
def agent_get_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    agent: Agent = Depends(
        require_permissions("conversations.read_authorized", "conversations.read_all", mode="any")
    ),
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


# ================================================================
# STAFF & ADMIN PROPERTY INVENTORY MANAGEMENT (Phase D)
# ================================================================
# Server-side RBAC policy:
# - `properties.read` (held by admin, property_manager, sales_manager, agent/sales_agent):
#   browse, search, filter, and inspect property details.
#   Callers WITHOUT `properties.update` or `properties.create` (e.g. sales_agent)
#   only see approved, non-archived properties appropriate for active sales work.
#   Admins and property managers see the complete inventory including drafts,
#   unapproved listings, and archived (`off_market`) records.
# - `properties.create` (held by admin, property_manager): create new listings.
# - `properties.update` (held by admin, property_manager): edit listings, change
#   availability status, approve/unapprove (`is_approved`), and archive.
# - `properties.delete` (held by admin, property_manager): delete unreferenced
#   listings or archive referenced ones safely.

class PropertyCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = Field(default="")
    purpose: str = Field(..., description="sale | rent | lease")
    availability: Optional[str] = Field(default="available")
    price: Any = Field(..., description="Non-negative numeric or AED string price")
    currency: Optional[str] = Field(default="AED", max_length=8)
    property_type: str = Field(..., min_length=1, max_length=64)
    location: str = Field(..., min_length=1, max_length=255)
    bedrooms: Optional[int] = Field(default=0)
    bathrooms: Optional[int] = Field(default=1)
    area: Optional[float] = Field(default=None)
    area_unit: Optional[str] = Field(default="sqft", max_length=16)
    amenities: Optional[Any] = Field(default=None)
    highlights: Optional[str] = Field(default=None)
    images: Optional[Any] = Field(default=None)
    primary_image: Optional[str] = Field(default=None)
    external_ref: Optional[str] = Field(default=None, max_length=64)
    source: Optional[str] = Field(default="manual", max_length=32)
    source_id: Optional[str] = Field(default=None, max_length=64)
    import_batch_id: Optional[str] = Field(default=None, max_length=64)
    is_approved: Optional[bool] = Field(default=False)
    is_published: Optional[bool] = Field(default=False)
    verification_status: Optional[str] = Field(default="unverified", max_length=32)
    is_demo: Optional[bool] = Field(default=False)


class PropertyUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = Field(default=None)
    purpose: Optional[str] = Field(default=None)
    availability: Optional[str] = Field(default=None)
    price: Optional[Any] = Field(default=None)
    currency: Optional[str] = Field(default=None, max_length=8)
    property_type: Optional[str] = Field(default=None, max_length=64)
    location: Optional[str] = Field(default=None, max_length=255)
    bedrooms: Optional[int] = Field(default=None)
    bathrooms: Optional[int] = Field(default=None)
    area: Optional[float] = Field(default=None)
    area_unit: Optional[str] = Field(default=None, max_length=16)
    amenities: Optional[Any] = Field(default=None)
    highlights: Optional[str] = Field(default=None)
    images: Optional[Any] = Field(default=None)
    primary_image: Optional[str] = Field(default=None)
    external_ref: Optional[str] = Field(default=None, max_length=64)
    is_approved: Optional[bool] = Field(default=None)
    is_published: Optional[bool] = Field(default=None)
    verification_status: Optional[str] = Field(default=None, max_length=32)
    rejection_reason: Optional[str] = Field(default=None)


class PropertyRejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(..., min_length=3, max_length=1000)


class PropertyImagesUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    images: Any = Field(..., description="List of image objects or URLs")
    primary_image: Optional[str] = Field(default=None)


class PropertyBulkActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    property_ids: List[int] = Field(..., min_length=1)
    action: str = Field(..., description="approve | reject | publish | unpublish | archive")
    reason: Optional[str] = Field(default=None, max_length=1000)


class PropertyImportBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    records: List[Dict[str, Any]] = Field(..., min_length=1, max_length=1000)
    source: Optional[str] = Field(default="uae_dataset", max_length=32)
    filename: Optional[str] = Field(default=None, max_length=255)
    skip_duplicates: Optional[bool] = Field(default=True)
    dry_run: Optional[bool] = Field(default=False)


def _can_manage_inventory(agent: Agent) -> bool:
    return (
        rbac.has_permission(agent, "properties.update")
        or rbac.has_permission(agent, "properties.create")
        or rbac.has_permission(agent, "properties.delete")
    )


@app.get("/api/agent/properties")
@app.get("/api/admin/properties")
def staff_list_properties(
    purpose: Optional[str] = None,
    availability: Optional[str] = None,
    approved: Optional[bool] = None,
    is_published: Optional[bool] = None,
    verification_status: Optional[str] = None,
    is_demo: Optional[bool] = None,
    source: Optional[str] = None,
    include_dataset: bool = True,
    location: Optional[str] = None,
    property_type: Optional[str] = None,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    min_bedrooms: Optional[int] = None,
    max_bedrooms: Optional[int] = None,
    q: Optional[str] = None,
    sort: str = "newest",
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("properties.read")),
):
    """Search, filter, and paginate property inventory for staff and admins."""
    can_manage = _can_manage_inventory(agent)
    eff_is_demo = is_demo if is_demo is not None else False
    exclude_sources = None if include_dataset else ("uae_dataset",)
    summary = inventory_summary(db, exclude_sources=exclude_sources, include_demo=(is_demo is True))

    eff_approved = approved
    eff_availability: Optional[object] = availability
    if not can_manage:
        # Sales agents see approved, active-work properties only (no drafts or archived off_market rows).
        if approved is False:
            return {
                "results": [],
                "total": 0,
                "limit": limit,
                "offset": offset,
                "summary": summary,
            }
        eff_approved = True
        if availability is not None:
            if availability.strip().lower() == "off_market":
                return {
                    "results": [],
                    "total": 0,
                    "limit": limit,
                    "offset": offset,
                    "summary": summary,
                }
            eff_availability = availability
        else:
            eff_availability = ("available", "reserved", "sold", "rented")

    try:
        rows, total = list_properties(
            db,
            purpose=purpose,
            availability=eff_availability,
            approved=eff_approved,
            is_published=is_published,
            verification_status=verification_status,
            is_demo=eff_is_demo,
            source=source,
            exclude_sources=exclude_sources,
            location=location,
            property_type=property_type,
            min_price=min_price,
            max_price=max_price,
            min_bedrooms=min_bedrooms,
            max_bedrooms=max_bedrooms,
            q=q,
            sort=sort,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    return {
        "results": [staff_property_dict(p) for p in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
        "summary": summary,
    }


@app.get("/api/agent/properties/dataset-summary")
@app.get("/api/admin/properties/dataset-summary")
def staff_dataset_summary(
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("properties.read")),
):
    """Read-only summary of UAE dataset file availability and DB synchronization."""
    summary = inventory_summary(db)
    file_records = len(load_properties())
    return {
        "dataset_file_available": file_records > 0,
        "dataset_file_records": file_records,
        "db_dataset_total": summary["dataset_total"],
        "db_dataset_approved": summary["dataset_approved"],
        "db_dataset_unapproved": summary["dataset_unapproved"],
        "db_crm_total": summary["total"],
    }


@app.post("/api/admin/properties/bulk-action")
def admin_bulk_property_action(
    payload: PropertyBulkActionRequest,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("properties.update")),
):
    """Perform safe bulk lifecycle actions (approve, reject, publish, unpublish, archive)."""
    try:
        result = bulk_lifecycle_action(
            db,
            payload.property_ids,
            payload.action,
            actor_id=agent.id,
            reason=payload.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return result


@app.post("/api/admin/properties/import-preview")
def admin_preview_property_import(
    payload: PropertyImportBatchRequest,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("properties.create")),
):
    """Dry-run import preview with zero DB writes."""
    return preview_import_records(db, payload.records)


@app.post("/api/admin/properties/import-batch")
def admin_stage_property_import(
    payload: PropertyImportBatchRequest,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("properties.create")),
):
    """Execute safe staging of property records into unverified / off-market state."""
    try:
        result = stage_import_batch(
            db,
            payload.records,
            source=payload.source or "uae_dataset",
            filename=payload.filename,
            actor_id=agent.id,
            skip_duplicates=payload.skip_duplicates if payload.skip_duplicates is not None else True,
            dry_run=bool(payload.dry_run),
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Import batch failed: {exc}")
    return result


@app.get("/api/admin/properties/import-batches")
def admin_list_import_batches(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("properties.read")),
):
    """List property import batch audit history."""
    query = db.query(PropertyImportBatch).order_by(PropertyImportBatch.created_at.desc())
    total = query.count()
    rows = query.offset(offset).limit(limit).all()
    results = []
    for r in rows:
        results.append({
            "id": r.id,
            "batch_id": r.batch_id,
            "source": r.source,
            "filename": r.filename,
            "status": r.status,
            "total_records": r.total_records,
            "valid_records": r.valid_records,
            "invalid_records": r.invalid_records,
            "duplicate_records": r.duplicate_records,
            "imported_records": r.imported_records,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        })
    return {"results": results, "total": total, "limit": limit, "offset": offset}


@app.get("/api/admin/properties/import-batches/{batch_id}")
def admin_get_import_batch(
    batch_id: str,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("properties.read")),
):
    """Get detailed status and validation report for an import batch."""
    batch = db.query(PropertyImportBatch).filter(PropertyImportBatch.batch_id == batch_id).first()
    if not batch:
        raise HTTPException(status_code=404, detail="Import batch not found")
    report = None
    if batch.validation_report:
        try:
            report = json.loads(batch.validation_report)
        except Exception:
            report = {"raw": batch.validation_report}
    return {
        "id": batch.id,
        "batch_id": batch.batch_id,
        "source": batch.source,
        "filename": batch.filename,
        "status": batch.status,
        "total_records": batch.total_records,
        "valid_records": batch.valid_records,
        "invalid_records": batch.invalid_records,
        "duplicate_records": batch.duplicate_records,
        "imported_records": batch.imported_records,
        "validation_report": report,
        "created_at": batch.created_at.isoformat() if batch.created_at else None,
        "completed_at": batch.completed_at.isoformat() if batch.completed_at else None,
    }


@app.get("/api/agent/properties/{property_id}")
@app.get("/api/admin/properties/{property_id}")
def staff_get_property(
    property_id: int,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("properties.read")),
):
    """Return full property details and reference counts for staff/admin."""
    try:
        prop = crud_get_property(db, property_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Property not found")

    if not _can_manage_inventory(agent):
        if not prop.is_approved or prop.availability == "off_market":
            raise HTTPException(status_code=404, detail="Property not found")

    refs = property_reference_counts(db, prop.id)
    return {"property": staff_property_dict(prop, reference_counts=refs)}


@app.post("/api/agent/properties", status_code=201)
@app.post("/api/admin/properties", status_code=201)
def staff_create_property(
    payload: PropertyCreateRequest,
    request: Request = None,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("properties.create")),
):
    """Create a new database-backed property record (admin / property_manager)."""
    data = payload.model_dump(exclude_unset=True)
    try:
        prop = create_property(db, data)
    except ValueError as exc:
        msg = str(exc)
        if "already exists" in msg:
            raise HTTPException(status_code=409, detail=msg)
        raise HTTPException(status_code=422, detail=msg)

    auditlog.write_audit(
        db,
        auditlog.PROPERTY_CREATED,
        actor_type="staff",
        actor_id=agent.id,
        actor_label=agent.email,
        subject_type="property",
        subject_id=prop.id,
        subject_label=prop.title,
        ip=auditlog.client_ip(request),
        detail=f"purpose={prop.purpose} price={prop.price} approved={prop.is_approved}",
    )
    if prop.is_approved:
        auditlog.write_audit(
            db,
            auditlog.PROPERTY_APPROVED,
            actor_type="staff",
            actor_id=agent.id,
            actor_label=agent.email,
            subject_type="property",
            subject_id=prop.id,
            subject_label=prop.title,
            ip=auditlog.client_ip(request),
            detail="approved_on_create",
        )
    return {
        "property": staff_property_dict(
            prop, reference_counts={"recommendations": 0, "saved": 0, "total": 0}
        )
    }


@app.patch("/api/agent/properties/{property_id}")
@app.patch("/api/admin/properties/{property_id}")
def staff_update_property(
    property_id: int,
    payload: PropertyUpdateRequest,
    request: Request = None,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("properties.update")),
):
    """Update an existing property record, including status and approval state."""
    try:
        before = crud_get_property(db, property_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Property not found")

    was_approved = bool(before.is_approved)
    was_availability = before.availability
    changes = payload.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(status_code=422, detail="No property changes provided")

    try:
        prop = update_property(
            db, property_id, changes, allow_approval_change=True
        )
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg.lower():
            raise HTTPException(status_code=404, detail=msg)
        if "already exists" in msg:
            raise HTTPException(status_code=409, detail=msg)
        raise HTTPException(status_code=422, detail=msg)

    changed_keys = ",".join(sorted(changes.keys()))
    auditlog.write_audit(
        db,
        auditlog.PROPERTY_UPDATED,
        actor_type="staff",
        actor_id=agent.id,
        actor_label=agent.email,
        subject_type="property",
        subject_id=prop.id,
        subject_label=prop.title,
        ip=auditlog.client_ip(request),
        detail=f"fields={changed_keys}"[:200],
    )
    if "is_approved" in changes and bool(prop.is_approved) != was_approved:
        auditlog.write_audit(
            db,
            auditlog.PROPERTY_APPROVED if prop.is_approved else auditlog.PROPERTY_UNAPPROVED,
            actor_type="staff",
            actor_id=agent.id,
            actor_label=agent.email,
            subject_type="property",
            subject_id=prop.id,
            subject_label=prop.title,
            ip=auditlog.client_ip(request),
            detail=f"is_approved={prop.is_approved}",
        )
    if (
        "availability" in changes
        and prop.availability == "off_market"
        and was_availability != "off_market"
    ):
        auditlog.write_audit(
            db,
            auditlog.PROPERTY_ARCHIVED,
            actor_type="staff",
            actor_id=agent.id,
            actor_label=agent.email,
            subject_type="property",
            subject_id=prop.id,
            subject_label=prop.title,
            ip=auditlog.client_ip(request),
            detail=f"from={was_availability}",
        )

    refs = property_reference_counts(db, prop.id)
    return {"property": staff_property_dict(prop, reference_counts=refs)}


@app.post("/api/agent/properties/{property_id}/archive")
@app.post("/api/admin/properties/{property_id}/archive")
def staff_archive_property(
    property_id: int,
    request: Request = None,
    db: Session = Depends(get_db),
    agent: Agent = Depends(
        require_permissions("properties.update", "properties.delete", mode="any")
    ),
):
    """Archive a property (`availability='off_market'`, `is_approved=False`).

    Safe for properties referenced by lead recommendations or customer bookmarks.
    """
    try:
        prop = archive_property(db, property_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Property not found")

    auditlog.write_audit(
        db,
        auditlog.PROPERTY_ARCHIVED,
        actor_type="staff",
        actor_id=agent.id,
        actor_label=agent.email,
        subject_type="property",
        subject_id=prop.id,
        subject_label=prop.title,
        ip=auditlog.client_ip(request),
        detail="archived_off_market",
    )
    refs = property_reference_counts(db, prop.id)
    return {"archived": True, "property": staff_property_dict(prop, reference_counts=refs)}


@app.delete("/api/agent/properties/{property_id}")
@app.delete("/api/admin/properties/{property_id}")
def staff_delete_property(
    property_id: int,
    request: Request = None,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("properties.delete")),
):
    """Hard-delete an unreferenced property record; returns 409 if referenced."""
    try:
        prop = crud_get_property(db, property_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Property not found")

    title_snapshot = prop.title
    try:
        delete_property(db, property_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    auditlog.write_audit(
        db,
        auditlog.PROPERTY_DELETED,
        actor_type="staff",
        actor_id=agent.id,
        actor_label=agent.email,
        subject_type="property",
        subject_id=property_id,
        subject_label=title_snapshot,
        ip=auditlog.client_ip(request),
        detail="hard_deleted",
    )
    return {"deleted": True, "id": property_id}


# =============================================================================
# Phase I: Property Lifecycle, Verification, Media and Batch Operations
# =============================================================================

@app.post("/api/agent/properties/{property_id}/submit-review")
@app.post("/api/admin/properties/{property_id}/submit-review")
def staff_submit_property_for_review(
    property_id: int,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("properties.update", "properties.create", mode="any")),
):
    """Submit property listing for verification review."""
    try:
        prop = submit_for_review(db, property_id, actor_id=agent.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    refs = property_reference_counts(db, prop.id)
    return {"status": "pending_review", "property": staff_property_dict(prop, reference_counts=refs)}


@app.post("/api/admin/properties/{property_id}/approve")
def admin_approve_property(
    property_id: int,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("properties.update")),
):
    """Approve property listing (admin / inventory manager)."""
    try:
        prop = approve_property(db, property_id, actor_id=agent.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    refs = property_reference_counts(db, prop.id)
    return {"status": "approved", "property": staff_property_dict(prop, reference_counts=refs)}


@app.post("/api/admin/properties/{property_id}/reject")
def admin_reject_property(
    property_id: int,
    payload: PropertyRejectRequest,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("properties.update")),
):
    """Reject property listing with a required reason."""
    try:
        prop = reject_property(db, property_id, actor_id=agent.id, reason=payload.reason)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    refs = property_reference_counts(db, prop.id)
    return {"status": "rejected", "property": staff_property_dict(prop, reference_counts=refs)}


@app.post("/api/admin/properties/{property_id}/publish")
def admin_publish_property(
    property_id: int,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("properties.update")),
):
    """Publish verified listing for customer and portal discovery."""
    try:
        prop = publish_property(db, property_id, actor_id=agent.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    refs = property_reference_counts(db, prop.id)
    return {"status": "published", "property": staff_property_dict(prop, reference_counts=refs)}


@app.post("/api/admin/properties/{property_id}/unpublish")
def admin_unpublish_property(
    property_id: int,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("properties.update")),
):
    """Unpublish property listing from customer visibility."""
    try:
        prop = unpublish_property(db, property_id, actor_id=agent.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    refs = property_reference_counts(db, prop.id)
    return {"status": "unpublished", "property": staff_property_dict(prop, reference_counts=refs)}


@app.post("/api/admin/properties/{property_id}/images")
def admin_update_property_images(
    property_id: int,
    payload: PropertyImagesUpdateRequest,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("properties.update")),
):
    """Update gallery images and primary thumbnail for a listing."""
    try:
        prop = manage_property_images(db, property_id, payload.images, primary_url=payload.primary_image, actor_id=agent.id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    refs = property_reference_counts(db, prop.id)
    return {"property": staff_property_dict(prop, reference_counts=refs)}


def _is_staff_request(request: Request, db: Session) -> bool:
    """Evaluate if request carries a valid authenticated staff session without failing public callers."""
    try:
        from app.services.auth import _extract_token, AgentSession
        token = _extract_token(request)
        if not token:
            return False
        s = db.query(AgentSession).filter(AgentSession.token_hash == AgentSession.hash_token(token)).first()
        if s and not s.revoked_at and (not s.expires_at or s.expires_at > datetime.utcnow()):
            agent = db.query(Agent).filter(Agent.id == s.agent_id, Agent.is_active == True).first()
            return agent is not None
    except Exception:
        pass
    return False


def _image_response(img: PropertyImage, request: Request) -> Response:
    """Construct an HTTP response serving binary image bytes with HTTP caching headers."""
    etag = f'"{img.image_hash}"'
    client_etag = request.headers.get("if-none-match")
    if client_etag and client_etag.strip() == etag:
        return Response(status_code=304)
    headers = {
        "Content-Type": img.mime_type,
        "Content-Length": str(img.file_size),
        "ETag": etag,
        "Cache-Control": "public, max-age=86400, stale-while-revalidate=604800",
    }
    return Response(content=img.image_data, media_type=img.mime_type, headers=headers)


@app.post("/api/admin/properties/{property_id}/images/upload", status_code=201)
async def admin_upload_property_image(
    property_id: int,
    file: UploadFile = File(...),
    is_primary: bool = Form(False),
    alt_text: Optional[str] = Form(None),
    display_order: Optional[int] = Form(None),
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("properties.update")),
):
    """Upload an image file from the admin local computer directly into PostgreSQL BYTEA storage."""
    prop = db.query(Property).filter(Property.id == property_id).first()
    if prop is None:
        raise HTTPException(status_code=404, detail="Property not found")

    content = await file.read()
    try:
        stored = store_property_image(
            db,
            property_id=property_id,
            image_bytes=content,
            original_filename=file.filename,
            alt_text=alt_text,
            is_primary=is_primary,
            display_order=display_order,
            actor_id=agent.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    refs = property_reference_counts(db, prop.id)
    return {
        "success": True,
        "image": {
            "id": stored.id,
            "property_id": stored.property_id,
            "original_filename": stored.original_filename,
            "mime_type": stored.mime_type,
            "file_size": stored.file_size,
            "image_hash": stored.image_hash,
            "display_order": stored.display_order,
            "is_primary": bool(stored.is_primary),
            "alt_text": stored.alt_text,
            "url": f"/api/properties/{property_id}/images/{stored.id}",
            "created_at": stored.created_at.isoformat() if stored.created_at else None,
        },
        "property": staff_property_dict(prop, reference_counts=refs),
    }


@app.get("/api/properties/{property_id}/images")
def get_property_images_list(
    property_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """List persistent image metadata for a property."""
    prop = db.query(Property).filter(Property.id == property_id).first()
    if prop is None:
        raise HTTPException(status_code=404, detail="Property not found")

    # Visibility check
    if not (prop.is_published or prop.is_approved):
        if not _is_staff_request(request, db):
            raise HTTPException(status_code=404, detail="Property not found")

    images = list_property_images(db, property_id)
    return {"property_id": property_id, "images": images}


@app.get("/api/properties/{property_id}/images/{image_id}")
def get_property_image_file(
    property_id: int,
    image_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Serve binary image bytes directly from PostgreSQL BYTEA storage."""
    prop = db.query(Property).filter(Property.id == property_id).first()
    if prop is None:
        raise HTTPException(status_code=404, detail="Property not found")

    if not (prop.is_published or prop.is_approved):
        if not _is_staff_request(request, db):
            raise HTTPException(status_code=404, detail="Property not found")

    img = get_property_image(db, property_id, image_id)
    if img is None or not img.image_data:
        raise HTTPException(status_code=404, detail="Image not found")

    return _image_response(img, request)


@app.get("/api/properties/{property_id}/primary-image")
def get_property_primary_image_file(
    property_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    """Serve the primary binary image directly from PostgreSQL BYTEA storage."""
    prop = db.query(Property).filter(Property.id == property_id).first()
    if prop is None:
        raise HTTPException(status_code=404, detail="Property not found")

    if not (prop.is_published or prop.is_approved):
        if not _is_staff_request(request, db):
            raise HTTPException(status_code=404, detail="Property not found")

    img = get_primary_property_image(db, property_id)
    if img is None or not img.image_data:
        raise HTTPException(status_code=404, detail="No image available for this property")

    return _image_response(img, request)


@app.post("/api/admin/properties/{property_id}/images/{image_id}/primary")
def admin_set_primary_image(
    property_id: int,
    image_id: int,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("properties.update")),
):
    """Designate an image as the primary listing image in PostgreSQL."""
    try:
        updated = set_primary_property_image(db, property_id, image_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    prop = db.query(Property).filter(Property.id == property_id).first()
    refs = property_reference_counts(db, prop.id)
    return {
        "success": True,
        "image_id": updated.id,
        "is_primary": True,
        "property": staff_property_dict(prop, reference_counts=refs),
    }


@app.delete("/api/admin/properties/{property_id}/images/{image_id}")
def admin_delete_property_image(
    property_id: int,
    image_id: int,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("properties.update")),
):
    """Permanently delete an image from PostgreSQL BYTEA storage."""
    deleted = delete_property_image(db, property_id, image_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Image not found")

    prop = db.query(Property).filter(Property.id == property_id).first()
    refs = property_reference_counts(db, prop.id)
    return {
        "success": True,
        "deleted_id": image_id,
        "property": staff_property_dict(prop, reference_counts=refs),
    }





# ================================================================
# PHASE F — APPOINTMENTS, PROPERTY VIEWINGS, OFFERS & DEALS
# ================================================================

class AppointmentCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead_id: Optional[int] = Field(None, ge=1)
    customer_id: Optional[int] = Field(None, ge=1)
    property_id: Optional[int] = Field(None, ge=1)
    additional_property_ids: List[int] = Field(default_factory=list, max_length=10)
    assigned_agent_id: Optional[int] = Field(None, ge=1)
    appointment_type: Literal[
        "viewing", "callback", "consultation", "negotiation_meeting", "documentation_meeting"
    ] = "viewing"
    start_at: datetime
    end_at: datetime
    timezone: str = Field("Asia/Dubai", max_length=64)
    meeting_method: Literal["in_person", "phone", "video"] = "in_person"
    location_or_link: Optional[str] = Field(None, max_length=500)
    customer_confirmation_status: Literal[
        "pending", "confirmed", "declined", "reschedule_requested"
    ] = "pending"
    notes: Optional[str] = Field(None, max_length=4000)
    conflict_override: bool = False
    conflict_override_reason: Optional[str] = Field(None, max_length=500)
    idempotency_key: Optional[str] = Field(None, max_length=120)


class AppointmentUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_confirmation_status: Optional[Literal[
        "pending", "confirmed", "declined", "reschedule_requested"
    ]] = None
    status: Optional[Literal["scheduled", "confirmed"]] = None
    meeting_method: Optional[Literal["in_person", "phone", "video"]] = None
    location_or_link: Optional[str] = Field(None, max_length=500)
    notes: Optional[str] = Field(None, max_length=4000)
    assigned_agent_id: Optional[int] = Field(None, ge=1)


class AppointmentRescheduleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_at: datetime
    end_at: datetime
    timezone: Optional[str] = Field(None, max_length=64)
    reason: Optional[str] = Field(None, max_length=500)
    location_or_link: Optional[str] = Field(None, max_length=500)
    conflict_override: bool = False
    conflict_override_reason: Optional[str] = Field(None, max_length=500)


class AppointmentCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(..., min_length=1, max_length=500)


class AppointmentOutcomeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["completed", "no_show"] = "completed"
    viewing_outcome: Optional[Literal[
        "interested", "not_interested", "requested_another_viewing", "requested_more_info", "undecided"
    ]] = None
    customer_feedback: Optional[str] = Field(None, max_length=4000)
    outcome: Optional[str] = Field(None, max_length=2000)
    next_action: Optional[str] = Field(None, max_length=500)


class OfferCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead_id: Optional[int] = Field(None, ge=1)
    customer_id: Optional[int] = Field(None, ge=1)
    property_id: int = Field(..., ge=1)
    assigned_agent_id: Optional[int] = Field(None, ge=1)
    transaction_intent: Literal["purchase", "rent", "lease"] = "purchase"
    asking_price: Optional[float] = Field(None, ge=0, le=1e12)
    offered_price: float = Field(..., gt=0, le=1e12)
    currency: str = Field("AED", min_length=3, max_length=3)
    payment_frequency: Optional[Literal[
        "one_time", "yearly", "semi_annual", "quarterly", "monthly", "installment_plan"
    ]] = None
    cheques_count: Optional[int] = Field(None, ge=1, le=12)
    financing_type: Optional[str] = Field(None, max_length=60)
    submit_immediately: bool = False
    expires_at: Optional[datetime] = None
    notes: Optional[str] = Field(None, max_length=4000)
    terms_conditions: Optional[str] = Field(None, max_length=4000)
    document_references: List[Annotated[str, Field(max_length=250)]] = Field(
        default_factory=list, max_length=20
    )
    idempotency_key: Optional[str] = Field(None, max_length=120)


class OfferCounterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    party: Literal["buyer", "seller", "owner", "landlord", "agent"] = "seller"
    counter_amount: float = Field(..., gt=0, le=1e12)
    payment_frequency: Optional[Literal[
        "one_time", "yearly", "semi_annual", "quarterly", "monthly", "installment_plan"
    ]] = None
    cheques_count: Optional[int] = Field(None, ge=1, le=12)
    expires_at: Optional[datetime] = None
    reason: Optional[str] = Field(None, max_length=500)
    notes: Optional[str] = Field(None, max_length=4000)


class OfferStatusRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["submitted", "accepted", "rejected", "withdrawn", "expired"]
    reason: Optional[str] = Field(None, max_length=500)
    notes: Optional[str] = Field(None, max_length=4000)


class DealCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lead_id: Optional[int] = Field(None, ge=1)
    customer_id: Optional[int] = Field(None, ge=1)
    property_id: int = Field(..., ge=1)
    offer_id: Optional[int] = Field(None, ge=1)
    assigned_agent_id: Optional[int] = Field(None, ge=1)
    transaction_type: Literal["purchase", "rent", "lease"] = "purchase"
    agreed_amount: float = Field(..., gt=0, le=1e12)
    currency: str = Field("AED", min_length=3, max_length=3)
    payment_frequency: Optional[str] = Field(None, max_length=60)
    initial_status: Literal[
        "qualification", "viewing", "offer_preparation", "negotiation",
        "offer_accepted", "reservation_pending", "reservation_confirmed",
        "documentation_pending", "transaction_pending_completion"
    ] = "offer_preparation"
    estimated_commission_pct: Optional[float] = Field(None, ge=0, le=100)
    estimated_commission: Optional[float] = Field(None, ge=0, le=1e12)
    target_completion_date: Optional[datetime] = None
    notes: Optional[str] = Field(None, max_length=4000)


class DealUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agreed_amount: Optional[float] = Field(None, gt=0, le=1e12)
    payment_frequency: Optional[str] = Field(None, max_length=60)
    estimated_commission_pct: Optional[float] = Field(None, ge=0, le=100)
    estimated_commission: Optional[float] = Field(None, ge=0, le=1e12)
    actual_commission: Optional[float] = Field(None, ge=0, le=1e12)
    commission_status: Optional[Literal["estimated", "verified", "earned", "paid"]] = None
    target_completion_date: Optional[datetime] = None
    notes: Optional[str] = Field(None, max_length=4000)
    assigned_agent_id: Optional[int] = Field(None, ge=1)


class DealStageTransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str = Field(..., min_length=1, max_length=60)
    reason: Optional[str] = Field(None, max_length=500)
    confirm: bool = False
    reopen: bool = False


class DealChecklistCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(..., min_length=2, max_length=80)
    title: str = Field(..., min_length=3, max_length=250)
    category: Literal[
        "identity", "property", "contract", "reservation", "regulatory", "completion", "custom", "compliance"
    ] = "custom"
    is_required: bool = True
    notes: Optional[str] = Field(None, max_length=2000)


class DealChecklistUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Optional[Literal["pending", "uploaded", "received", "reviewed", "verified", "waived"]] = None
    document_reference: Optional[str] = Field(None, max_length=250)
    notes: Optional[str] = Field(None, max_length=2000)
    responsible_user_id: Optional[int] = Field(None, ge=1)


def _scoped_appointment_or_404(db: Session, agent: Agent, appointment_id: int) -> Appointment:
    appt = db.query(Appointment).filter(Appointment.id == appointment_id).first()
    if appt is None or not appointment_in_scope(agent, appt):
        raise HTTPException(status_code=404, detail="Appointment not found")
    return appt


def _scoped_offer_or_404(db: Session, agent: Agent, offer_id: int) -> Offer:
    offer = db.query(Offer).filter(Offer.id == offer_id).first()
    if offer is None or not offer_in_scope(agent, offer):
        raise HTTPException(status_code=404, detail="Offer not found")
    return offer


def _scoped_deal_or_404(db: Session, agent: Agent, deal_id: int) -> Deal:
    deal = db.query(Deal).filter(Deal.id == deal_id).first()
    if deal is None or not deal_in_scope(agent, deal):
        raise HTTPException(status_code=404, detail="Deal not found")
    return deal


@app.get("/api/agent/sales-ops/summary")
def agent_sales_ops_summary(
    db: Session = Depends(get_db),
    agent: Agent = Depends(
        require_permissions(
            "appointments.read", "offers.read", "deals.read", "leads.read_assigned", "leads.read_all",
            mode="any",
        )
    ),
):
    """Scoped summary of Appointments, Viewings, Offers & Deals for the CRM dashboard."""
    return compute_sales_ops_summary(db, agent)


# ---------------- Appointments & Property Viewings ------------------------

@app.get("/api/agent/appointments")
def agent_list_appointments(
    lead_id: Optional[int] = None,
    property_id: Optional[int] = None,
    assigned_agent_id: Optional[int] = None,
    appointment_type: Optional[Literal[
        "viewing", "callback", "consultation", "negotiation_meeting", "documentation_meeting"
    ]] = None,
    status: Optional[Literal[
        "scheduled", "confirmed", "completed", "cancelled", "rescheduled", "no_show"
    ]] = None,
    window: Optional[Literal["all", "today", "upcoming", "overdue", "conflicts"]] = Query("all"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    agent: Agent = Depends(
        require_permissions("appointments.read", "leads.read_assigned", "leads.read_all", mode="any")
    ),
):
    """List appointments & viewings inside the caller's scope."""
    if lead_id is not None:
        _scoped_lead_or_404(db, agent, lead_id)
    query = scoped_appointment_query(db, agent)
    if lead_id is not None:
        query = query.filter(Appointment.lead_id == lead_id)
    if property_id is not None:
        query = query.filter(Appointment.property_id == property_id)
    if assigned_agent_id is not None:
        query = query.filter(Appointment.assigned_agent_id == assigned_agent_id)
    if appointment_type is not None:
        query = query.filter(Appointment.appointment_type == appointment_type)
    if status is not None:
        query = query.filter(Appointment.status == status)

    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_start = today_start + __import__("datetime").timedelta(days=1)

    if window == "today":
        query = query.filter(
            Appointment.start_at >= today_start,
            Appointment.start_at < tomorrow_start,
            Appointment.status.in_(ACTIVE_APPOINTMENT_STATUSES),
        )
    elif window == "upcoming":
        query = query.filter(
            Appointment.start_at >= now,
            Appointment.status.in_(ACTIVE_APPOINTMENT_STATUSES),
        )
    elif window == "overdue":
        query = query.filter(
            Appointment.end_at < now,
            Appointment.status.in_(ACTIVE_APPOINTMENT_STATUSES),
        )

    rows = (
        query.order_by(Appointment.start_at.asc(), Appointment.id.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    serialized = [appointment_to_dict(r, db) for r in rows]
    if window == "conflicts":
        serialized = [s for s in serialized if s.get("property_availability_conflict")]
        total = len(serialized)
    else:
        total = query.count()
    return {"total": total, "results": serialized}


def _create_appointment_handler(
    db: Session,
    agent: Agent,
    payload: AppointmentCreateRequest,
    request: Request,
    path_lead_id: Optional[int] = None,
):
    eff_lead_id = path_lead_id if path_lead_id is not None else payload.lead_id
    if eff_lead_id is None:
        raise HTTPException(status_code=422, detail="lead_id is required")
    lead = _scoped_lead_or_404(db, agent, eff_lead_id)

    try:
        appt, replay = create_appointment(
            db,
            actor=agent,
            lead=lead,
            appointment_type=payload.appointment_type,
            start_at=payload.start_at,
            end_at=payload.end_at,
            timezone_name=payload.timezone,
            meeting_method=payload.meeting_method,
            location_or_link=payload.location_or_link,
            property_id=payload.property_id,
            additional_property_ids=payload.additional_property_ids,
            assigned_agent_id=payload.assigned_agent_id,
            customer_id=payload.customer_id,
            customer_confirmation_status=payload.customer_confirmation_status,
            notes=payload.notes,
            conflict_override=payload.conflict_override,
            conflict_override_reason=payload.conflict_override_reason,
            idempotency_key=payload.idempotency_key,
        )
        db.commit()
    except AppointmentConflictError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "code": "appointment_conflict",
                "message": str(exc),
                "conflicts": exc.conflicts,
            },
        )
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc))

    db.refresh(appt)
    if not replay:
        auditlog.write_audit(
            db,
            auditlog.APPOINTMENT_CREATED,
            actor_type="staff",
            actor_id=agent.id,
            actor_label=agent.email,
            subject_type="lead",
            subject_id=lead.id,
            subject_label=lead.name or f"Lead #{lead.id}",
            ip=auditlog.client_ip(request),
            detail=f"appt_id={appt.id}; type={appt.appointment_type}; property={appt.property_id}",
        )
    return {
        "appointment": appointment_to_dict(appt, db),
        "idempotent_replay": replay,
    }


@app.post("/api/agent/appointments")
def agent_create_appointment(
    payload: AppointmentCreateRequest,
    request: Request = None,
    db: Session = Depends(get_db),
    agent: Agent = Depends(
        require_permissions("appointments.manage", "viewings.manage", mode="any")
    ),
):
    return _create_appointment_handler(db, agent, payload, request)


@app.post("/api/agent/leads/{lead_id}/appointments")
def agent_create_lead_appointment(
    lead_id: int,
    payload: AppointmentCreateRequest,
    request: Request = None,
    db: Session = Depends(get_db),
    agent: Agent = Depends(
        require_permissions("appointments.manage", "viewings.manage", mode="any")
    ),
):
    return _create_appointment_handler(db, agent, payload, request, path_lead_id=lead_id)


@app.get("/api/agent/appointments/{appointment_id}")
def agent_get_appointment(
    appointment_id: int,
    db: Session = Depends(get_db),
    agent: Agent = Depends(
        require_permissions("appointments.read", "leads.read_assigned", "leads.read_all", mode="any")
    ),
):
    appt = _scoped_appointment_or_404(db, agent, appointment_id)
    return {"appointment": appointment_to_dict(appt, db)}


@app.patch("/api/agent/appointments/{appointment_id}")
def agent_update_appointment(
    appointment_id: int,
    payload: AppointmentUpdateRequest,
    request: Request = None,
    db: Session = Depends(get_db),
    agent: Agent = Depends(
        require_permissions("appointments.manage", "viewings.manage", mode="any")
    ),
):
    appt = _scoped_appointment_or_404(db, agent, appointment_id)
    fields = payload.model_dump(exclude_unset=True)

    if "assigned_agent_id" in fields and fields["assigned_agent_id"] is not None:
        fields["assigned_agent_id"] = _resolve_agent(db, agent, fields["assigned_agent_id"])

    for k, v in fields.items():
        if hasattr(appt, k):
            setattr(appt, k, v)
    appt.updated_by_id = agent.id
    appt.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(appt)
    auditlog.write_audit(
        db,
        auditlog.APPOINTMENT_UPDATED,
        actor_type="staff",
        actor_id=agent.id,
        actor_label=agent.email,
        subject_type="lead",
        subject_id=appt.lead_id,
        subject_label=f"Lead #{appt.lead_id}",
        ip=auditlog.client_ip(request),
        detail=f"appt_id={appt.id}; status={appt.status}",
    )
    return {"appointment": appointment_to_dict(appt, db)}


@app.post("/api/agent/appointments/{appointment_id}/reschedule")
def agent_reschedule_appointment(
    appointment_id: int,
    payload: AppointmentRescheduleRequest,
    request: Request = None,
    db: Session = Depends(get_db),
    agent: Agent = Depends(
        require_permissions("appointments.manage", "viewings.manage", mode="any")
    ),
):
    appt = _scoped_appointment_or_404(db, agent, appointment_id)
    try:
        reschedule_appointment(
            db,
            actor=agent,
            appt=appt,
            new_start_at=payload.start_at,
            new_end_at=payload.end_at,
            timezone_name=payload.timezone,
            reason=payload.reason,
            location_or_link=payload.location_or_link,
            conflict_override=payload.conflict_override,
            conflict_override_reason=payload.conflict_override_reason,
        )
        db.commit()
    except AppointmentConflictError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "code": "appointment_conflict",
                "message": str(exc),
                "conflicts": exc.conflicts,
            },
        )
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc))

    db.refresh(appt)
    auditlog.write_audit(
        db,
        auditlog.APPOINTMENT_RESCHEDULED,
        actor_type="staff",
        actor_id=agent.id,
        actor_label=agent.email,
        subject_type="lead",
        subject_id=appt.lead_id,
        subject_label=f"Lead #{appt.lead_id}",
        ip=auditlog.client_ip(request),
        detail=f"appt_id={appt.id}; reason={(payload.reason or '')[:80]}",
    )
    return {"appointment": appointment_to_dict(appt, db)}


@app.post("/api/agent/appointments/{appointment_id}/cancel")
def agent_cancel_appointment(
    appointment_id: int,
    payload: AppointmentCancelRequest,
    request: Request = None,
    db: Session = Depends(get_db),
    agent: Agent = Depends(
        require_permissions("appointments.manage", "viewings.manage", mode="any")
    ),
):
    appt = _scoped_appointment_or_404(db, agent, appointment_id)
    try:
        cancel_appointment(db, actor=agent, appt=appt, reason=payload.reason)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc))

    db.refresh(appt)
    auditlog.write_audit(
        db,
        auditlog.APPOINTMENT_CANCELLED,
        actor_type="staff",
        actor_id=agent.id,
        actor_label=agent.email,
        subject_type="lead",
        subject_id=appt.lead_id,
        subject_label=f"Lead #{appt.lead_id}",
        ip=auditlog.client_ip(request),
        detail=f"appt_id={appt.id}; reason={payload.reason.strip()[:100]}",
    )
    return {"appointment": appointment_to_dict(appt, db)}


@app.post("/api/agent/appointments/{appointment_id}/outcome")
def agent_record_appointment_outcome(
    appointment_id: int,
    payload: AppointmentOutcomeRequest,
    request: Request = None,
    db: Session = Depends(get_db),
    agent: Agent = Depends(
        require_permissions("appointments.manage", "viewings.manage", mode="any")
    ),
):
    appt = _scoped_appointment_or_404(db, agent, appointment_id)
    try:
        record_appointment_outcome(
            db,
            actor=agent,
            appt=appt,
            status=payload.status,
            viewing_outcome=payload.viewing_outcome,
            customer_feedback=payload.customer_feedback,
            outcome=payload.outcome,
            next_action=payload.next_action,
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc))

    db.refresh(appt)
    evt = (
        auditlog.APPOINTMENT_NO_SHOW
        if appt.status == "no_show"
        else (
            auditlog.VIEWING_OUTCOME_RECORDED
            if appt.appointment_type == "viewing"
            else auditlog.APPOINTMENT_COMPLETED
        )
    )
    auditlog.write_audit(
        db,
        evt,
        actor_type="staff",
        actor_id=agent.id,
        actor_label=agent.email,
        subject_type="lead",
        subject_id=appt.lead_id,
        subject_label=f"Lead #{appt.lead_id}",
        ip=auditlog.client_ip(request),
        detail=f"appt_id={appt.id}; status={appt.status}; viewing_outcome={appt.viewing_outcome}",
    )
    return {"appointment": appointment_to_dict(appt, db)}


# ---------------- Agent Viewing Request Queue & Customer Management (Phase H) ---

class AgentAcceptViewingIn(BaseModel):
    conflict_override: bool = False
    conflict_override_reason: Optional[str] = None


class AgentRejectViewingIn(BaseModel):
    reason: str = Field(..., min_length=2)


class AgentCustomerCommunicationIn(BaseModel):
    message: str = Field(..., min_length=1)
    subject: Optional[str] = None
    channel: str = "portal"
    is_customer_visible: bool = True
    follow_up_needed: bool = False
    property_id: Optional[int] = None
    appointment_id: Optional[int] = None


@app.get("/api/agent/viewing-requests")
def agent_get_viewing_requests(
    status: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("leads.read_assigned", "leads.read_all", mode="any")),
):
    """Queue of customer-submitted viewing requests within agent's scope."""
    q = scoped_appointment_query(db, agent).filter(Appointment.customer_id.isnot(None))
    if status:
        q = q.filter(Appointment.customer_confirmation_status == status)
    else:
        # Default: pending confirmation
        q = q.filter(Appointment.customer_confirmation_status.in_(("pending", "reschedule_requested")))

    rows = q.order_by(Appointment.start_at.asc()).limit(limit).all()
    return {
        "results": [appointment_to_dict(a, db) for a in rows],
        "total": len(rows),
    }


@app.post("/api/agent/appointments/{appointment_id}/accept-request")
def agent_accept_viewing_request(
    appointment_id: int,
    payload: AgentAcceptViewingIn = None,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("appointments.manage", "leads.update", mode="any")),
):
    """Accept and confirm customer viewing request."""
    conflict_override = payload.conflict_override if payload else False
    conflict_override_reason = payload.conflict_override_reason if payload else None
    try:
        appt = cops.accept_viewing_request(
            db,
            appt_id=appointment_id,
            agent=agent,
            conflict_override=conflict_override,
            conflict_override_reason=conflict_override_reason,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except AppointmentConflictError as e:
        raise HTTPException(
            status_code=409,
            detail={"error": "appointment_conflict", "conflicts": e.conflicts},
        )
    return {"appointment": appointment_to_dict(appt, db)}


@app.post("/api/agent/appointments/{appointment_id}/reject-request")
def agent_reject_viewing_request(
    appointment_id: int,
    payload: AgentRejectViewingIn,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("appointments.manage", "leads.update", mode="any")),
):
    """Decline or reject customer viewing request with reason."""
    try:
        appt = cops.reject_viewing_request(
            db,
            appt_id=appointment_id,
            agent=agent,
            reason=payload.reason,
        )
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    return {"appointment": appointment_to_dict(appt, db)}


@app.get("/api/agent/customers")
def agent_list_customers(
    search: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("leads.read_assigned", "leads.read_all", mode="any")),
):
    """List customers within agent scope with preferences and activity overview."""
    q = db.query(Customer).filter(Customer.password_hash.isnot(None))
    if not rbac.has_permission(agent, "leads.read_all"):
        # Agent sees customers who have leads assigned to this agent or appointments with this agent
        agent_lead_emails = db.query(func.lower(Lead.email)).filter(Lead.assigned_agent_id == agent.id, Lead.email.isnot(None)).subquery()
        agent_appt_cust_ids = db.query(Appointment.customer_id).filter(Appointment.assigned_agent_id == agent.id, Appointment.customer_id.isnot(None)).subquery()
        q = q.filter(
            or_(
                func.lower(Customer.email).in_(agent_lead_emails),
                Customer.id.in_(agent_appt_cust_ids),
            )
        )

    if search:
        s = f"%{search.strip().lower()}%"
        q = q.filter(
            or_(
                func.lower(Customer.name).like(s),
                func.lower(Customer.email).like(s),
                Customer.phone.like(s),
            )
        )

    total = q.count()
    rows = q.order_by(Customer.created_at.desc()).offset(offset).limit(limit).all()
    results = []
    for c in rows:
        c_dict = cops.customer_profile_dict(c)
        saved_count = db.query(func.count(SavedProperty.id)).filter(SavedProperty.customer_id == c.id).scalar() or 0
        appt_count = db.query(func.count(Appointment.id)).filter(Appointment.customer_id == c.id).scalar() or 0
        c_dict["saved_count"] = saved_count
        c_dict["appointment_count"] = appt_count
        results.append(c_dict)

    return {"results": results, "total": total}


@app.get("/api/agent/customers/{customer_id}")
def agent_get_customer_detail(
    customer_id: int,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("leads.read_assigned", "leads.read_all", mode="any")),
):
    """Detailed dossier of customer: preferences, saved listings, appointments, full communications."""
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    if not rbac.has_permission(agent, "leads.read_all"):
        if not customer_in_scope(db, agent, customer):
            raise HTTPException(status_code=404, detail="Customer not found")

    # Scope check
    if not rbac.has_permission(agent, "leads.read_all"):
        has_lead = db.query(Lead).filter(Lead.assigned_agent_id == agent.id, func.lower(Lead.email) == (customer.email or "").lower()).first()
        has_appt = db.query(Appointment).filter(Appointment.assigned_agent_id == agent.id, Appointment.customer_id == customer.id).first()
        if not has_lead and not has_appt:
            raise HTTPException(status_code=404, detail="Customer not found")

    profile_data = cops.customer_profile_dict(customer)

    # Saved properties
    saved_rows = db.query(SavedProperty).filter(SavedProperty.customer_id == customer.id).all()
    saved_listings = []
    for r in saved_rows:
        if _saved_is_record_row(r.property_id):
            p = get_public_record(db, r.property_id - _SAVED_RECORD_ID_BASE)
            if p:
                saved_listings.append({**public_record_dict(p), "property_id": p.id, "source": "record"})
        else:
            p = get_property_by_id(r.property_id)
            if p:
                saved_listings.append({**p, "source": "dataset"})

    # Appointments
    appts = db.query(Appointment).filter(Appointment.customer_id == customer.id).order_by(Appointment.start_at.desc()).all()

    # Communications (including internal notes)
    comms = cops.get_customer_communications(db, customer.id, include_internal=True)

    return {
        "customer": profile_data,
        "saved_properties": saved_listings,
        "appointments": [appointment_to_dict(a, db) for a in appts],
        "communications": [cops.communication_to_dict(c, include_internal=True) for c in comms],
    }


@app.post("/api/agent/customers/{customer_id}/communications")
def agent_add_customer_communication(
    customer_id: int,
    payload: AgentCustomerCommunicationIn,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("appointments.manage", "leads.update", mode="any")),
):
    """Agent logs a customer message or private internal note."""
    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    if not rbac.has_permission(agent, "leads.read_all"):
        if not customer_in_scope(db, agent, customer):
            raise HTTPException(status_code=404, detail="Customer not found")

    lead = cops._find_or_create_customer_lead(db, customer)
    comm = cops.log_communication(
        db,
        customer_id=customer.id,
        lead_id=lead.id,
        property_id=payload.property_id,
        appointment_id=payload.appointment_id,
        sender_type="agent",
        sender_agent_id=agent.id,
        channel=payload.channel,
        subject=payload.subject,
        message=payload.message,
        is_customer_visible=payload.is_customer_visible,
        follow_up_needed=payload.follow_up_needed,
    )

    # If message is customer-visible, dispatch notification to customer
    if payload.is_customer_visible:
        cops.create_notification(
            db,
            recipient_type="customer",
            customer_id=customer.id,
            category="general",
            title=f"Message from {agent.full_name}",
            message=payload.message[:150],
            related_type="communication",
            related_id=comm.id,
            action_url="/portal/messages",
        )

    return cops.communication_to_dict(comm, include_internal=True)


@app.get("/api/agent/notifications")
def agent_get_notifications(
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("leads.read_assigned", "leads.read_all", mode="any")),
):
    """Agent in-app notifications."""
    unread_count = cops.get_unread_notification_count(db, agent_id=agent.id)
    notifs = (
        db.query(CustomerNotification)
        .filter(CustomerNotification.agent_id == agent.id, CustomerNotification.recipient_type == "agent")
        .order_by(CustomerNotification.created_at.desc())
        .limit(limit)
        .all()
    )
    return {
        "unread_count": unread_count,
        "results": [cops.notification_to_dict(n) for n in notifs],
        "total": len(notifs),
    }


@app.post("/api/agent/notifications/{notification_id}/read")
def agent_mark_notification_read(
    notification_id: int,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("leads.read_assigned", "leads.read_all", mode="any")),
):
    """Mark agent notification as read."""
    try:
        notif = cops.mark_notification_read(db, notification_id, agent_id=agent.id)
    except LookupError:
        raise HTTPException(status_code=404, detail="Notification not found")
    return cops.notification_to_dict(notif)


@app.post("/api/agent/notifications/mark-all-read")
def agent_mark_all_notifications_read(
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("leads.read_assigned", "leads.read_all", mode="any")),
):
    """Mark all agent notifications as read."""
    count = cops.mark_all_notifications_read(db, agent_id=agent.id)
    return {"marked_read_count": count}


# ---------------- Offers & Counteroffer Negotiations ----------------------

@app.get("/api/agent/offers")
def agent_list_offers(
    lead_id: Optional[int] = None,
    property_id: Optional[int] = None,
    assigned_agent_id: Optional[int] = None,
    status: Optional[Literal[
        "draft", "submitted", "countered", "accepted", "rejected", "withdrawn", "expired"
    ]] = None,
    transaction_intent: Optional[Literal["purchase", "rent", "lease"]] = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    agent: Agent = Depends(
        require_permissions("offers.read", "leads.read_assigned", "leads.read_all", mode="any")
    ),
):
    if lead_id is not None:
        _scoped_lead_or_404(db, agent, lead_id)
    query = scoped_offer_query(db, agent)
    if lead_id is not None:
        query = query.filter(Offer.lead_id == lead_id)
    if property_id is not None:
        query = query.filter(Offer.property_id == property_id)
    if assigned_agent_id is not None:
        query = query.filter(Offer.assigned_agent_id == assigned_agent_id)
    if status is not None:
        query = query.filter(Offer.status == status)
    if transaction_intent is not None:
        query = query.filter(Offer.transaction_intent == transaction_intent)

    total = query.count()
    rows = (
        query.order_by(Offer.created_at.desc(), Offer.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {"total": total, "results": [offer_to_dict(r) for r in rows]}


def _create_offer_handler(
    db: Session,
    agent: Agent,
    payload: OfferCreateRequest,
    request: Request,
    path_lead_id: Optional[int] = None,
):
    eff_lead_id = path_lead_id if path_lead_id is not None else payload.lead_id
    if eff_lead_id is None:
        raise HTTPException(status_code=422, detail="lead_id is required")
    lead = _scoped_lead_or_404(db, agent, eff_lead_id)

    try:
        offer, replay = create_offer(
            db,
            actor=agent,
            lead=lead,
            property_id=payload.property_id,
            transaction_intent=payload.transaction_intent,
            offered_price=payload.offered_price,
            asking_price=payload.asking_price,
            currency=payload.currency,
            payment_frequency=payload.payment_frequency,
            cheques_count=payload.cheques_count,
            financing_type=payload.financing_type,
            submit_immediately=payload.submit_immediately,
            expires_at=payload.expires_at,
            notes=payload.notes,
            terms_conditions=payload.terms_conditions,
            document_references=payload.document_references,
            assigned_agent_id=payload.assigned_agent_id,
            customer_id=payload.customer_id,
            idempotency_key=payload.idempotency_key,
        )
        db.commit()
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc))

    db.refresh(offer)
    if not replay:
        auditlog.write_audit(
            db,
            auditlog.OFFER_SUBMITTED if offer.status == "submitted" else auditlog.OFFER_CREATED,
            actor_type="staff",
            actor_id=agent.id,
            actor_label=agent.email,
            subject_type="lead",
            subject_id=lead.id,
            subject_label=lead.name or f"Lead #{lead.id}",
            ip=auditlog.client_ip(request),
            detail=f"offer_id={offer.id}; property={offer.property_id}; price={offer.offered_price} {offer.currency}; status={offer.status}",
        )
    return {
        "offer": offer_to_dict(offer),
        "idempotent_replay": replay,
    }


@app.post("/api/agent/offers")
def agent_create_offer(
    payload: OfferCreateRequest,
    request: Request = None,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("offers.create")),
):
    return _create_offer_handler(db, agent, payload, request)


@app.post("/api/agent/leads/{lead_id}/offers")
def agent_create_lead_offer(
    lead_id: int,
    payload: OfferCreateRequest,
    request: Request = None,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("offers.create")),
):
    return _create_offer_handler(db, agent, payload, request, path_lead_id=lead_id)


@app.get("/api/agent/offers/{offer_id}")
def agent_get_offer(
    offer_id: int,
    db: Session = Depends(get_db),
    agent: Agent = Depends(
        require_permissions("offers.read", "leads.read_assigned", "leads.read_all", mode="any")
    ),
):
    offer = _scoped_offer_or_404(db, agent, offer_id)
    return {"offer": offer_to_dict(offer)}


@app.post("/api/agent/offers/{offer_id}/counter")
def agent_counter_offer(
    offer_id: int,
    payload: OfferCounterRequest,
    request: Request = None,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("offers.update")),
):
    offer = _scoped_offer_or_404(db, agent, offer_id)
    try:
        record_counteroffer(
            db,
            actor=agent,
            offer=offer,
            party=payload.party,
            counter_amount=payload.counter_amount,
            payment_frequency=payload.payment_frequency,
            cheques_count=payload.cheques_count,
            expires_at=payload.expires_at,
            reason=payload.reason,
            notes=payload.notes,
        )
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc))

    db.refresh(offer)
    auditlog.write_audit(
        db,
        auditlog.OFFER_COUNTERED,
        actor_type="staff",
        actor_id=agent.id,
        actor_label=agent.email,
        subject_type="lead",
        subject_id=offer.lead_id,
        subject_label=f"Lead #{offer.lead_id}",
        ip=auditlog.client_ip(request),
        detail=f"offer_id={offer.id}; party={payload.party}; amount={offer.current_price} {offer.currency}",
    )
    return {"offer": offer_to_dict(offer)}


@app.post("/api/agent/offers/{offer_id}/status")
def agent_transition_offer_status(
    offer_id: int,
    payload: OfferStatusRequest,
    request: Request = None,
    db: Session = Depends(get_db),
    agent: Agent = Depends(
        require_permissions("offers.update", "offers.accept", mode="any")
    ),
):
    offer = _scoped_offer_or_404(db, agent, offer_id)
    prev_status = offer.status
    try:
        transition_offer_status(
            db,
            actor=agent,
            offer=offer,
            target_status=payload.status,
            reason=payload.reason,
            notes=payload.notes,
        )
        db.commit()
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc))

    db.refresh(offer)
    evt_map = {
        "submitted": auditlog.OFFER_SUBMITTED,
        "accepted": auditlog.OFFER_ACCEPTED,
        "rejected": auditlog.OFFER_REJECTED,
        "withdrawn": auditlog.OFFER_WITHDRAWN,
        "expired": auditlog.OFFER_EXPIRED,
    }
    auditlog.write_audit(
        db,
        evt_map.get(offer.status, auditlog.OFFER_CREATED),
        actor_type="staff",
        actor_id=agent.id,
        actor_label=agent.email,
        subject_type="lead",
        subject_id=offer.lead_id,
        subject_label=f"Lead #{offer.lead_id}",
        ip=auditlog.client_ip(request),
        detail=f"offer_id={offer.id}; {prev_status}->{offer.status}; amount={offer.current_price} {offer.currency}",
    )
    return {"offer": offer_to_dict(offer)}


# ---------------- Deals & Transaction Pipeline ----------------------------

@app.get("/api/agent/deals")
def agent_list_deals(
    lead_id: Optional[int] = None,
    property_id: Optional[int] = None,
    assigned_agent_id: Optional[int] = None,
    status: Optional[str] = None,
    transaction_type: Optional[Literal["purchase", "rent", "lease"]] = None,
    q: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    agent: Agent = Depends(
        require_permissions("deals.read", "leads.read_assigned", "leads.read_all", mode="any")
    ),
):
    if lead_id is not None:
        _scoped_lead_or_404(db, agent, lead_id)
    query = scoped_deal_query(db, agent)
    if lead_id is not None:
        query = query.filter(Deal.lead_id == lead_id)
    if property_id is not None:
        query = query.filter(Deal.property_id == property_id)
    if assigned_agent_id is not None:
        query = query.filter(Deal.assigned_agent_id == assigned_agent_id)
    if status:
        if status not in DEAL_STAGES:
            raise HTTPException(status_code=422, detail=f"Invalid deal stage '{status}'")
        query = query.filter(Deal.status == status)
    if transaction_type is not None:
        query = query.filter(Deal.transaction_type == transaction_type)
    if q and q.strip():
        needle = f"%{q.strip()}%"
        query = query.filter(Deal.deal_reference.ilike(needle))

    total = query.count()
    rows = (
        query.order_by(Deal.updated_at.desc(), Deal.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {"total": total, "results": [deal_to_dict(r) for r in rows]}


def _create_deal_handler(
    db: Session,
    agent: Agent,
    payload: DealCreateRequest,
    request: Request,
    path_lead_id: Optional[int] = None,
):
    eff_lead_id = path_lead_id if path_lead_id is not None else payload.lead_id
    if eff_lead_id is None:
        raise HTTPException(status_code=422, detail="lead_id is required")
    lead = _scoped_lead_or_404(db, agent, eff_lead_id)

    try:
        deal = create_deal(
            db,
            actor=agent,
            lead=lead,
            property_id=payload.property_id,
            transaction_type=payload.transaction_type,
            agreed_amount=payload.agreed_amount,
            currency=payload.currency,
            payment_frequency=payload.payment_frequency,
            offer_id=payload.offer_id,
            initial_status=payload.initial_status,
            estimated_commission_pct=payload.estimated_commission_pct,
            estimated_commission=payload.estimated_commission,
            target_completion_date=payload.target_completion_date,
            notes=payload.notes,
            assigned_agent_id=payload.assigned_agent_id,
            customer_id=payload.customer_id,
        )
        db.commit()
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc))
    except LookupError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        db.rollback()
        msg = str(exc)
        if msg.startswith("DUPLICATE_ACTIVE_DEAL:"):
            parts = msg.split(":")
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "duplicate_active_deal",
                    "message": f"An active deal ({parts[2]}) already exists for this lead and property.",
                    "deal_id": int(parts[1]),
                    "deal_reference": parts[2],
                },
            )
        raise HTTPException(status_code=422, detail=msg)

    db.refresh(deal)
    auditlog.write_audit(
        db,
        auditlog.DEAL_CREATED,
        actor_type="staff",
        actor_id=agent.id,
        actor_label=agent.email,
        subject_type="lead",
        subject_id=lead.id,
        subject_label=lead.name or f"Lead #{lead.id}",
        ip=auditlog.client_ip(request),
        detail=f"deal_id={deal.id}; ref={deal.deal_reference}; status={deal.status}; amount={deal.agreed_amount} {deal.currency}",
    )
    return {"deal": deal_to_dict(deal)}


@app.post("/api/agent/deals")
def agent_create_deal(
    payload: DealCreateRequest,
    request: Request = None,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("deals.create")),
):
    return _create_deal_handler(db, agent, payload, request)


@app.post("/api/agent/leads/{lead_id}/deals")
def agent_create_lead_deal(
    lead_id: int,
    payload: DealCreateRequest,
    request: Request = None,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("deals.create")),
):
    return _create_deal_handler(db, agent, payload, request, path_lead_id=lead_id)


@app.get("/api/agent/deals/{deal_id}")
def agent_get_deal(
    deal_id: int,
    db: Session = Depends(get_db),
    agent: Agent = Depends(
        require_permissions("deals.read", "leads.read_assigned", "leads.read_all", mode="any")
    ),
):
    deal = _scoped_deal_or_404(db, agent, deal_id)
    return {
        "deal": deal_to_dict(deal),
        "offer": offer_to_dict(deal.offer) if deal.offer else None,
        "activity": lead_activity_history(db, deal.lead_id, limit=50),
    }


@app.patch("/api/agent/deals/{deal_id}")
def agent_update_deal(
    deal_id: int,
    payload: DealUpdateRequest,
    request: Request = None,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("deals.update")),
):
    deal = _scoped_deal_or_404(db, agent, deal_id)
    fields = payload.model_dump(exclude_unset=True)

    if "assigned_agent_id" in fields and fields["assigned_agent_id"] is not None:
        fields["assigned_agent_id"] = _resolve_agent(db, agent, fields["assigned_agent_id"])

    commission_verified = False
    if "actual_commission" in fields or "commission_status" in fields:
        if not rbac.has_permission(agent, "deals.approve"):
            raise HTTPException(
                status_code=403,
                detail="Only an administrator or sales manager ('deals.approve') can verify actual commission",
            )
        if fields.get("commission_status") in ("verified", "earned", "paid"):
            deal.commission_verified_by_id = agent.id
            deal.commission_verified_at = datetime.utcnow()
            commission_verified = True

    if "target_completion_date" in fields and fields["target_completion_date"] is not None:
        fields["target_completion_date"] = to_utc_naive(fields["target_completion_date"])

    for k, v in fields.items():
        if hasattr(deal, k):
            setattr(deal, k, v)

    # Recompute estimated_commission if pct or agreed_amount changed without explicit estimated_commission
    if ("agreed_amount" in fields or "estimated_commission_pct" in fields) and "estimated_commission" not in fields:
        if deal.estimated_commission_pct is not None and deal.agreed_amount is not None:
            deal.estimated_commission = round((float(deal.agreed_amount) * float(deal.estimated_commission_pct)) / 100.0, 2)

    deal.updated_by_id = agent.id
    deal.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(deal)
    auditlog.write_audit(
        db,
        auditlog.DEAL_COMMISSION_VERIFIED if commission_verified else auditlog.DEAL_UPDATED,
        actor_type="staff",
        actor_id=agent.id,
        actor_label=agent.email,
        subject_type="lead",
        subject_id=deal.lead_id,
        subject_label=f"Lead #{deal.lead_id}",
        ip=auditlog.client_ip(request),
        detail=f"deal_id={deal.id}; ref={deal.deal_reference}; comm_status={deal.commission_status}",
    )
    return {"deal": deal_to_dict(deal)}


@app.post("/api/agent/deals/{deal_id}/stage")
def agent_transition_deal_stage(
    deal_id: int,
    payload: DealStageTransitionRequest,
    request: Request = None,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("deals.update")),
):
    deal = _scoped_deal_or_404(db, agent, deal_id)
    prev = deal.status
    try:
        transition_deal_stage(
            db,
            actor=agent,
            deal=deal,
            target_status=payload.status,
            reason=payload.reason,
            confirm=payload.confirm,
            reopen=payload.reopen,
        )
        db.commit()
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc))

    db.refresh(deal)
    evt = (
        auditlog.DEAL_COMPLETED
        if deal.status == "completed"
        else (
            auditlog.DEAL_CANCELLED
            if deal.status == "cancelled"
            else (
                auditlog.DEAL_FAILED
                if deal.status == "failed"
                else auditlog.DEAL_STAGE_CHANGED
            )
        )
    )
    auditlog.write_audit(
        db,
        evt,
        actor_type="staff",
        actor_id=agent.id,
        actor_label=agent.email,
        subject_type="lead",
        subject_id=deal.lead_id,
        subject_label=f"Lead #{deal.lead_id}",
        ip=auditlog.client_ip(request),
        detail=f"deal_id={deal.id}; ref={deal.deal_reference}; {prev}->{deal.status}",
    )
    return {"deal": deal_to_dict(deal)}


@app.post("/api/agent/deals/{deal_id}/checklist")
def agent_add_deal_checklist_item(
    deal_id: int,
    payload: DealChecklistCreateRequest,
    request: Request = None,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("deals.update")),
):
    deal = _scoped_deal_or_404(db, agent, deal_id)
    item = DealChecklistItem(
        deal_id=deal.id,
        code=payload.code.strip().lower().replace(" ", "_"),
        title=payload.title.strip(),
        category=payload.category,
        is_required=payload.is_required,
        status="pending",
        notes=(payload.notes or "").strip() or None,
        responsible_user_id=deal.assigned_agent_id,
    )
    db.add(item)
    deal.updated_by_id = agent.id
    deal.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(deal)
    auditlog.write_audit(
        db,
        auditlog.DEAL_CHECKLIST_UPDATED,
        actor_type="staff",
        actor_id=agent.id,
        actor_label=agent.email,
        subject_type="lead",
        subject_id=deal.lead_id,
        subject_label=f"Lead #{deal.lead_id}",
        ip=auditlog.client_ip(request),
        detail=f"deal_id={deal.id}; added_checklist={item.code}",
    )
    return {"deal": deal_to_dict(deal), "item": checklist_item_to_dict(item)}


@app.patch("/api/agent/deals/{deal_id}/checklist/{item_id}")
def agent_update_deal_checklist_item(
    deal_id: int,
    item_id: int,
    payload: DealChecklistUpdateRequest,
    request: Request = None,
    db: Session = Depends(get_db),
    agent: Agent = Depends(
        require_permissions("deals.update", "deals.checklist_verify", "deals.approve", mode="any")
    ),
):
    deal = _scoped_deal_or_404(db, agent, deal_id)
    item = (
        db.query(DealChecklistItem)
        .filter(DealChecklistItem.id == item_id, DealChecklistItem.deal_id == deal.id)
        .first()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Checklist item not found")

    if payload.responsible_user_id is not None:
        _resolve_agent(db, agent, payload.responsible_user_id)

    try:
        update_deal_checklist_item(
            db,
            actor=agent,
            deal=deal,
            item=item,
            status=payload.status,
            document_reference=payload.document_reference,
            notes=payload.notes,
            responsible_user_id=payload.responsible_user_id,
        )
        db.commit()
    except PermissionError as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc))
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc))

    db.refresh(deal)
    db.refresh(item)
    evt = (
        auditlog.DEAL_CHECKLIST_VERIFIED
        if item.status in ("verified", "waived")
        else auditlog.DEAL_CHECKLIST_UPDATED
    )
    auditlog.write_audit(
        db,
        evt,
        actor_type="staff",
        actor_id=agent.id,
        actor_label=agent.email,
        subject_type="lead",
        subject_id=deal.lead_id,
        subject_label=f"Lead #{deal.lead_id}",
        ip=auditlog.client_ip(request),
        detail=f"deal_id={deal.id}; code={item.code}; status={item.status}",
    )
    return {"deal": deal_to_dict(deal), "item": checklist_item_to_dict(item)}



# ---------------------------------------------------------------------------
# Phase G: Executive Dashboards, Agent Performance & Business Intelligence
# ---------------------------------------------------------------------------

@app.get("/api/analytics/executive")
@app.get("/api/analytics/overview")
def analytics_executive_overview(
    period: Optional[str] = Query("30d", description="7d, 30d, 90d, this_month, last_month, all"),
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD"),
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("reports.read_all")),
):
    """Company-wide executive KPIs, conversion funnel, property inventory and revenue."""
    try:
        start_utc, end_utc, label = parse_reporting_period(period, date_from, date_to)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    try:
        data = get_executive_analytics(db, actor=agent, start_utc=start_utc, end_utc=end_utc, period_label=label)
        return data
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


@app.get("/api/analytics/manager")
@app.get("/api/analytics/team")
def analytics_manager_overview(
    period: Optional[str] = Query("30d", description="7d, 30d, 90d, this_month, last_month, all"),
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD"),
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("reports.read_all", "leads.read_all", mode="any")),
):
    """Sales manager dashboard: team workload, agent performance table, stalled items & deadlines."""
    try:
        start_utc, end_utc, label = parse_reporting_period(period, date_from, date_to)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    try:
        data = get_manager_analytics(db, actor=agent, start_utc=start_utc, end_utc=end_utc, period_label=label)
        return data
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


@app.get("/api/analytics/agent")
def analytics_agent_personal(
    agent_id: Optional[int] = Query(None, description="Target agent ID (admin only to view others)"),
    period: Optional[str] = Query("30d", description="7d, 30d, 90d, this_month, last_month, all"),
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD"),
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("leads.read_assigned", "reports.read_team", mode="any")),
):
    """Personal agent dashboard: action items, viewings awaiting feedback, deals & commission."""
    try:
        start_utc, end_utc, label = parse_reporting_period(period, date_from, date_to)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    try:
        data = get_agent_personal_analytics(
            db,
            actor=agent,
            target_agent_id=agent_id,
            start_utc=start_utc,
            end_utc=end_utc,
            period_label=label,
        )
        return data
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


@app.get("/api/analytics/export/agents")
def analytics_export_agents_csv(
    period: Optional[str] = Query("30d", description="7d, 30d, 90d, this_month, last_month, all"),
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD"),
    request: Request = None,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("reports.read_all")),
):
    """Protected CSV export of agent performance table with formula injection sanitization."""
    try:
        start_utc, end_utc, label = parse_reporting_period(period, date_from, date_to)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    try:
        data = get_manager_analytics(db, actor=agent, start_utc=start_utc, end_utc=end_utc, period_label=label)
        csv_text = export_agent_performance_csv(data.get("agents", []))
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc))

    auditlog.write_audit(
        db,
        auditlog.ANALYTICS_EXPORTED,
        actor_type="staff",
        actor_id=agent.id,
        actor_label=agent.email,
        subject_type="analytics",
        subject_id=None,
        subject_label="agent_performance_export",
        ip=auditlog.client_ip(request),
        detail=f"period={label}; agents_count={len(data.get('agents', []))}",
    )

    filename = f"lyka_agents_performance_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
    return RawResponse(
        content=csv_text,
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "Cache-Control": "no-store",
        },
    )
# ================================================================
# STAGE 6J — HR MANAGEMENT & ATTENDANCE ENDPOINTS
# ================================================================

from app.services import hr_ops

class EmployeeCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name: str = Field(..., min_length=2, max_length=150)
    official_email: str = Field(..., max_length=200)
    employee_id: Optional[str] = Field(default=None, max_length=50)
    contact_number: Optional[str] = Field(default=None, max_length=50)
    department: str = Field(default="Sales", max_length=100)
    designation: str = Field(default="Real Estate Consultant", max_length=100)
    reporting_manager_id: Optional[int] = Field(default=None)
    employment_type: str = Field(default="Full-time", max_length=50)
    joining_date: Optional[str] = Field(default=None)
    employment_status: str = Field(default="Active", max_length=50)
    crm_role: str = Field(default="agent", max_length=50)
    branch: str = Field(default="Dubai Main Branch", max_length=100)
    create_crm_account: Optional[bool] = Field(default=False)
    initial_password: Optional[str] = Field(default=None)

class EmployeeUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name: Optional[str] = Field(default=None, min_length=2, max_length=150)
    contact_number: Optional[str] = Field(default=None, max_length=50)
    department: Optional[str] = Field(default=None, max_length=100)
    designation: Optional[str] = Field(default=None, max_length=100)
    reporting_manager_id: Optional[int] = Field(default=None)
    employment_type: Optional[str] = Field(default=None, max_length=50)
    joining_date: Optional[str] = Field(default=None)
    employment_status: Optional[str] = Field(default=None, max_length=50)
    crm_role: Optional[str] = Field(default=None, max_length=50)
    branch: Optional[str] = Field(default=None, max_length=100)

class EmployeeDeactivateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(..., min_length=5, max_length=500)

class EmployeeAccountUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    login_email: Optional[EmailStr] = None
    username: Optional[str] = Field(default=None, max_length=50)
    crm_role: Optional[str] = Field(default=None, max_length=50)
    is_active: Optional[bool] = None
    reason: Optional[str] = Field(default=None, max_length=500)

class EmployeeAccountLinkRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    initial_password: Optional[str] = Field(default=None, min_length=6, max_length=100)
    username: Optional[str] = Field(default=None, max_length=50)

class AttendanceCheckInRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    shift: Optional[str] = Field(default="Standard (09:00 - 18:00 GST)", max_length=50)
    work_mode: Optional[str] = Field(default="OFFICE", max_length=50, description="OFFICE|WORK_FROM_HOME|FIELD_DUTY")
    notes: Optional[str] = Field(default=None, max_length=500)

class AttendanceCheckOutRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    notes: Optional[str] = Field(default=None, max_length=500)

class AttendanceCorrectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attendance_id: int
    status: str = Field(..., description="Present|Absent|Late|Half Day|Field Duty|Work From Home|On Leave|Holiday|Weekly Off")
    check_in: Optional[str] = Field(default=None, description="ISO timestamp")
    check_out: Optional[str] = Field(default=None, description="ISO timestamp")
    reason: str = Field(..., min_length=5, max_length=500)

class LeaveSubmitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    leave_type: str = Field(..., description="Casual Leave|Sick Leave|Annual/Earned Leave|Unpaid Leave|Other")
    start_date: str = Field(..., description="YYYY-MM-DD")
    end_date: str = Field(..., description="YYYY-MM-DD")
    reason: str = Field(..., min_length=5, max_length=1000)

class LeaveReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approved: bool
    review_notes: Optional[str] = Field(default="", max_length=500)


@app.get("/api/hr/dashboard")
def hr_get_dashboard(
    date: Optional[str] = None,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("hr_reports.view", "attendance.view", mode="any")),
):
    """HR Dashboard summary metrics (real PostgreSQL counts)."""
    target_d = None
    if date:
        try:
            target_d = datetime.fromisoformat(date).date()
        except ValueError:
            pass
    return hr_ops.get_hr_dashboard_stats(db, target_date=target_d)


@app.get("/api/hr/employees")
def hr_list_employees(
    department: Optional[str] = None,
    status: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("employees.view")),
):
    """List and search employee master records with pagination."""
    results, total = hr_ops.list_employees(
        db, department=department, status=status, q=q, limit=limit, offset=offset
    )
    return {"results": results, "total": total, "limit": limit, "offset": offset}


@app.post("/api/hr/employees", status_code=201)
def hr_create_employee(
    payload: EmployeeCreateRequest,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("employees.create")),
):
    """Create a new employee record and optional linked CRM account."""
    if payload.crm_role in ("admin", "superadmin") and agent.role not in ("admin", "superadmin"):
        raise HTTPException(
            status_code=403,
            detail="HR administrators are not permitted to grant system administrator privileges",
        )
    data = payload.model_dump()
    linked_agent_id = None
    if payload.create_crm_account:
        from app.services.auth import hash_password
        existing_agent = db.query(Agent).filter(Agent.email == payload.official_email.lower().strip()).first()
        if existing_agent:
            linked_agent_id = existing_agent.id
        else:
            uname = payload.official_email.split("@")[0].replace(".", "_")
            new_agent = Agent(
                email=payload.official_email.lower().strip(),
                username=uname,
                full_name=payload.full_name.strip(),
                password_hash=hash_password(payload.initial_password or "Lyka@2026"),
                role=payload.crm_role or "agent",
                is_active=payload.employment_status == "Active",
            )
            db.add(new_agent)
            db.commit()
            db.refresh(new_agent)
            linked_agent_id = new_agent.id
    data["agent_id"] = linked_agent_id

    try:
        emp = hr_ops.create_employee(db, data, creator_agent_id=agent.id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"employee": hr_ops.employee_dict(emp)}


@app.get("/api/hr/employees/{employee_id}")
def hr_get_employee(
    employee_id: int,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("employees.view")),
):
    """Get full employee profile with attendance and leave history."""
    emp = hr_ops.get_employee(db, employee_id)
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    recent_attendance, _ = hr_ops.list_attendance(db, employee_id=emp.id, limit=30)
    recent_leaves, _ = hr_ops.list_leave_requests(db, employee_id=emp.id, limit=20)
    return {
        "employee": hr_ops.employee_dict(emp),
        "recent_attendance": recent_attendance,
        "recent_leaves": recent_leaves,
    }


@app.patch("/api/hr/employees/{employee_id}")
def hr_update_employee(
    employee_id: int,
    payload: EmployeeUpdateRequest,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("employees.update")),
):
    """Update permitted fields on an employee profile."""
    emp = hr_ops.get_employee(db, employee_id)
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    data = payload.model_dump(exclude_unset=True)
    updated = hr_ops.update_employee(db, emp, data, modifier_agent_id=agent.id)
    return {"employee": hr_ops.employee_dict(updated)}


@app.post("/api/hr/employees/{employee_id}/deactivate")
def hr_deactivate_employee(
    employee_id: int,
    payload: EmployeeDeactivateRequest,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("employees.deactivate")),
):
    """Deactivate employee account and revoke CRM system login."""
    emp = hr_ops.get_employee(db, employee_id)
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")

    updated = hr_ops.deactivate_employee(db, emp, reason=payload.reason, modifier_agent_id=agent.id)
    return {"employee": hr_ops.employee_dict(updated), "status": "deactivated"}


@app.post("/api/hr/employees/{employee_id}/reset-password")
def hr_reset_employee_password(
    employee_id: int,
    payload: AdminAgentResetPasswordRequest,
    request: Request = None,
    db: Session = Depends(get_db),
    admin: Agent = Depends(require_permissions("users.update")),
):
    """Administratively reset employee login credentials and revoke active sessions."""
    emp = hr_ops.get_employee(db, employee_id)
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    if not emp.agent_id:
        raise HTTPException(status_code=400, detail="Employee has no linked login account")

    target = db.query(Agent).filter(Agent.id == emp.agent_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Linked login account not found")

    temp_pw = payload.temporary_password or (secrets.token_urlsafe(9) + "A1!")
    target.password_hash = hash_password(temp_pw)
    target.must_change_password = True
    target.failed_login_count = 0
    target.locked_until = None
    db.add(target)
    db.commit()

    revoked = revoke_all_sessions(db, target.id)
    auditlog.write_audit(
        db, auditlog.PASSWORD_RESET, actor_type="staff", actor_id=admin.id,
        actor_label=admin.email, subject_type="employee", subject_id=emp.id,
        subject_label=f"{emp.employee_id} - {emp.full_name}",
        ip=auditlog.client_ip(request),
        detail=f"password reset for user {target.id} ({target.email}); revoked {revoked} session(s)",
    )
    return {"ok": True, "temporary_password": temp_pw, "revoked_sessions": revoked}


@app.post("/api/hr/employees/{employee_id}/account")
def hr_update_employee_account(
    employee_id: int,
    payload: EmployeeAccountUpdateRequest,
    request: Request = None,
    db: Session = Depends(get_db),
    admin: Agent = Depends(require_permissions("users.update")),
):
    """Update linked CRM login credentials (email, username, role, active status)."""
    emp = hr_ops.get_employee(db, employee_id)
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    if not emp.agent_id:
        raise HTTPException(status_code=400, detail="Employee has no linked login account")

    target = db.query(Agent).filter(Agent.id == emp.agent_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="Linked login account not found")

    changes = []
    if payload.login_email and payload.login_email.strip().lower() != target.email:
        new_email = payload.login_email.strip().lower()
        collision = db.query(Agent).filter(Agent.email == new_email, Agent.id != target.id).first()
        if collision:
            raise HTTPException(status_code=409, detail="An account with this email already exists")
        changes.append(f"email: {target.email} -> {new_email}")
        target.email = new_email
        emp.official_email = new_email

    if payload.username and payload.username.strip() != target.username:
        new_uname = payload.username.strip()
        collision = db.query(Agent).filter(Agent.username == new_uname, Agent.id != target.id).first()
        if collision:
            raise HTTPException(status_code=409, detail="An account with this username already exists")
        changes.append(f"username: {target.username} -> {new_uname}")
        target.username = new_uname

    if payload.crm_role and payload.crm_role != target.role:
        norm_role = rbac.normalize_role(payload.crm_role)
        if not rbac.is_known_role(norm_role):
            raise HTTPException(status_code=422, detail=f"Unknown role: {payload.crm_role}")
        if target.role == "admin" and norm_role != "admin":
            admin_count = db.query(Agent).filter(Agent.role == "admin", Agent.is_active == True).count()
            if admin_count <= 1:
                raise HTTPException(status_code=400, detail="Cannot demote the last active System Administrator")
        changes.append(f"role: {target.role} -> {norm_role}")
        target.role = norm_role
        emp.crm_role = norm_role

    if payload.is_active is not None and payload.is_active != target.is_active:
        changes.append(f"is_active: {target.is_active} -> {payload.is_active}")
        target.is_active = payload.is_active
        if not payload.is_active:
            revoke_all_sessions(db, target.id)
            if emp.employment_status == "Active":
                emp.employment_status = "Suspended"
        else:
            if emp.employment_status == "Suspended":
                emp.employment_status = "Active"

    db.add(target)
    db.add(emp)
    db.commit()
    db.refresh(target)
    db.refresh(emp)

    if changes:
        auditlog.write_audit(
            db, auditlog.STAFF_UPDATED if hasattr(auditlog, 'STAFF_UPDATED') else "hr.employee.account_updated",
            actor_type="staff", actor_id=admin.id, actor_label=admin.email,
            subject_type="employee", subject_id=emp.id,
            subject_label=f"{emp.employee_id} - {emp.full_name}",
            ip=auditlog.client_ip(request),
            detail="; ".join(changes),
        )

    return {"employee": hr_ops.employee_dict(emp)}


@app.post("/api/hr/employees/{employee_id}/link-account")
def hr_link_employee_account(
    employee_id: int,
    payload: EmployeeAccountLinkRequest,
    request: Request = None,
    db: Session = Depends(get_db),
    admin: Agent = Depends(require_permissions("users.update")),
):
    """Create or link a CRM login account for an existing employee."""
    emp = hr_ops.get_employee(db, employee_id)
    if not emp:
        raise HTTPException(status_code=404, detail="Employee not found")
    if emp.agent_id:
        raise HTTPException(status_code=400, detail="Employee already has a linked login account")

    existing_agent = db.query(Agent).filter(Agent.email == emp.official_email.lower().strip()).first()
    if existing_agent:
        emp.agent_id = existing_agent.id
        db.add(emp)
        db.commit()
        db.refresh(emp)
        return {"employee": hr_ops.employee_dict(emp), "mode": "linked_existing"}

    uname = payload.username or emp.official_email.split("@")[0].replace(".", "_")
    collision = db.query(Agent).filter(Agent.username == uname).first()
    if collision:
        uname = f"{uname}_{secrets.token_hex(2)}"

    init_pw = payload.initial_password or (secrets.token_urlsafe(9) + "A1!")
    new_agent = Agent(
        email=emp.official_email.lower().strip(),
        username=uname,
        full_name=emp.full_name.strip(),
        password_hash=hash_password(init_pw),
        role=emp.crm_role or "agent",
        is_active=emp.employment_status == "Active",
    )
    db.add(new_agent)
    db.commit()
    db.refresh(new_agent)

    emp.agent_id = new_agent.id
    db.add(emp)
    db.commit()
    db.refresh(emp)

    auditlog.write_audit(
        db, "hr.employee.account_created",
        actor_type="staff", actor_id=admin.id, actor_label=admin.email,
        subject_type="employee", subject_id=emp.id,
        subject_label=f"{emp.employee_id} - {emp.full_name}",
        ip=auditlog.client_ip(request),
        detail=f"created linked user {new_agent.id} ({new_agent.email})",
    )

    return {"employee": hr_ops.employee_dict(emp), "mode": "created_new", "temporary_password": init_pw}


@app.get("/api/hr/attendance")
def hr_list_attendance(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    employee_id: Optional[int] = None,
    department: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("attendance.view")),
):
    """Company-wide attendance records with date and department filters."""
    df = datetime.fromisoformat(date_from).date() if date_from else None
    dt = datetime.fromisoformat(date_to).date() if date_to else None
    results, total = hr_ops.list_attendance(
        db, date_from=df, date_to=dt, employee_id=employee_id,
        department=department, status=status, limit=limit, offset=offset
    )
    return {"results": results, "total": total, "limit": limit, "offset": offset}


@app.post("/api/hr/attendance/correct")
def hr_correct_attendance(
    payload: AttendanceCorrectRequest,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("attendance.correct")),
):
    """Authorized manual attendance correction with mandatory audit reason."""
    ci = datetime.fromisoformat(payload.check_in) if payload.check_in else None
    co = datetime.fromisoformat(payload.check_out) if payload.check_out else None
    try:
        att = hr_ops.correct_attendance(
            db,
            attendance_id=payload.attendance_id,
            new_status=payload.status,
            new_check_in=ci,
            new_check_out=co,
            reason=payload.reason,
            modifier_agent_id=agent.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"attendance": hr_ops.attendance_dict(att)}


@app.get("/api/hr/leave-requests")
def hr_list_leave_requests(
    employee_id: Optional[int] = None,
    status: Optional[str] = None,
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("leave.review")),
):
    """List employee leave requests for HR review."""
    results, total = hr_ops.list_leave_requests(
        db, employee_id=employee_id, status=status, limit=limit, offset=offset
    )
    return {"results": results, "total": total, "limit": limit, "offset": offset}


@app.post("/api/hr/leave-requests/{request_id}/review")
def hr_review_leave(
    request_id: int,
    payload: LeaveReviewRequest,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("leave.review")),
):
    """Approve or reject employee leave application."""
    try:
        req = hr_ops.review_leave_request(
            db,
            request_id=request_id,
            approved=payload.approved,
            review_notes=payload.review_notes,
            reviewer_agent_id=agent.id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"leave_request": hr_ops.leave_dict(req)}


# ---------------------------------------------------------------------------
# Employee Self-Service Attendance & Leave Endpoints
# ---------------------------------------------------------------------------

@app.post("/api/agent/attendance/check-in")
def agent_attendance_check_in(
    payload: AttendanceCheckInRequest,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("attendance.manage")),
):
    """Authenticated employee self-service check-in for today."""
    emp = hr_ops.ensure_employee_for_agent(db, agent)
    try:
        att = hr_ops.record_check_in(
            db, emp, shift=payload.shift, notes=payload.notes, work_mode=payload.work_mode
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"attendance": hr_ops.attendance_dict(att)}


@app.post("/api/agent/attendance/check-out")
def agent_attendance_check_out(
    payload: AttendanceCheckOutRequest,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("attendance.manage")),
):
    """Authenticated employee self-service check-out for today."""
    emp = hr_ops.ensure_employee_for_agent(db, agent)
    try:
        att = hr_ops.record_check_out(db, emp, notes=payload.notes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"attendance": hr_ops.attendance_dict(att)}


@app.get("/api/agent/attendance/today")
def agent_get_today_attendance(
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("attendance.manage")),
):
    """Return today's attendance status and recent attendance history for this employee."""
    emp = hr_ops.ensure_employee_for_agent(db, agent)
    today_att = hr_ops.get_today_attendance(db, emp)
    recent_history, _ = hr_ops.list_attendance(db, employee_id=emp.id, limit=14)
    return {
        "employee": hr_ops.employee_dict(emp),
        "today": hr_ops.attendance_dict(today_att) if today_att else None,
        "recent_history": recent_history,
    }


@app.post("/api/agent/leave-requests")
def agent_submit_leave_request(
    payload: LeaveSubmitRequest,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("leave.manage")),
):
    """Employee submits a personal leave request."""
    emp = hr_ops.ensure_employee_for_agent(db, agent)
    try:
        s_date = datetime.fromisoformat(payload.start_date).date()
        e_date = datetime.fromisoformat(payload.end_date).date()
        req = hr_ops.submit_leave_request(
            db,
            emp=emp,
            leave_type=payload.leave_type,
            start_date=s_date,
            end_date=e_date,
            reason=payload.reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"leave_request": hr_ops.leave_dict(req)}


@app.get("/api/agent/leave-requests")
def agent_get_own_leave_requests(
    status: Optional[str] = None,
    limit: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("leave.view")),
):
    """Employee inspects their own submitted leave requests."""
    emp = hr_ops.ensure_employee_for_agent(db, agent)
    results, total = hr_ops.list_leave_requests(
        db, employee_id=emp.id, status=status, limit=limit
    )
    return {"results": results, "total": total}


@app.post("/api/agent/leave-requests/{request_id}/cancel")
def agent_cancel_own_leave_request(
    request_id: int,
    db: Session = Depends(get_db),
    agent: Agent = Depends(require_permissions("leave.manage")),
):
    """Employee cancels their own pending leave request."""
    emp = hr_ops.ensure_employee_for_agent(db, agent)
    try:
        req = hr_ops.cancel_leave_request(db, request_id, emp)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {"leave_request": hr_ops.leave_dict(req), "status": "cancelled"}
