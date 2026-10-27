"""Deterministic property matching & ranking — Phase 4.

Sources: ONLY the Phase 2 database-backed ``properties`` records (approved +
available, verified purpose). ``UAErealestate.json`` is never used for
recommendations. All arithmetic is plain Python; the LLM has no say in
eligibility, weights, or ranking.

Hard eligibility (excluded BEFORE scoring):
  1. not approved
  2. not available
  3. purpose not verified (sale/rent/lease)
  4. purpose conflicts with a clearly stated buy/rent/lease intent
  5. a clearly stated hard requirement fails: bedrooms (property must have
     >= lead's requirement), bathrooms (>=), property type (exact match
     after normalisation)
Missing lead data is NEVER treated as a match (it scores 0 and is noted).

Ranking weights (auditable, sum = 100):
  Location 30 · Budget 25 · Type/bedrooms 20 · Amenities 15 · Preferences 10

Budget semantics (documented limitations of the existing schema):
  - ``properties.price`` for purpose='rent'/'lease' is the YEARLY amount
    (the schema has no price-period column — documented limitation, not
    silently resolved). A lead budget is therefore compared to rent/lease
    prices ONLY when the lead's ``budget_period == "yearly"``; a monthly or
    unspecified lead period scores 0 with an explicit note. Sale prices are
    total amounts and compare when the lead period is one_time/None.
  - Currencies are never converted and never compared across codes: a
    currency mismatch (or an unstated lead currency) scores 0 with a note.
Unknown intent cannot align any price semantics → budget scores 0 with a note.

Stable ordering: match_score DESC, then price ASC, then id ASC.
"""

import json
import logging
from typing import List, Optional, Tuple, Union

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.ai.lead_extraction import LeadExtractionResult
from app.database import Conversation, Lead, Property, PropertyRecommendation
from app.services.property_search import (
    VALID_PURPOSES,
    is_verified_purpose,
    search_property_records,
)

logger = logging.getLogger(__name__)

WEIGHTS = {
    "location": 30.0,
    "budget": 25.0,
    "type_bedrooms": 20.0,   # type 12 + bedrooms 8
    "amenities": 15.0,
    "preferences": 10.0,     # "area / other preferences" (see limitation note)
}
assert abs(sum(WEIGHTS.values()) - 100.0) < 1e-9, "weights must sum to 100"

TYPE_SUB_WEIGHT = 12.0
BEDROOMS_SUB_WEIGHT = 8.0

DEFAULT_LIMIT = 3
MAX_LIMIT = 10
MAX_CANDIDATES = 100   # candidate pool cap (search_property_records clamp)

_INTENT_TO_PURPOSE = {"buy": "sale", "rent": "rent", "lease": "lease"}


class PropertyMatch(BaseModel):
    """One ranked, eligible property with a full auditable explanation."""
    model_config = ConfigDict(extra="ignore")

    property_id: int
    external_ref: Optional[str] = None
    title: str
    is_demo: bool = False
    purpose: str
    price: float
    currency: str
    location: str
    property_type: str
    bedrooms: int
    bathrooms: int
    area: Optional[float] = None
    area_unit: str = "sqft"
    match_score: float = Field(ge=0, le=100)
    breakdown: dict          # criterion -> points earned
    reasons: List[str]
    mismatches: List[str]
    data_gaps: List[str]     # missing PROPERTY data — never counted as a match


class MatchResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    results: List[PropertyMatch]
    candidates_considered: int
    eligible_count: int
    explanation: str


class MatchRequest(BaseModel):
    """Staff request body for POST /api/agent/properties/match."""
    model_config = ConfigDict(extra="ignore")

    extraction: LeadExtractionResult
    limit: int = Field(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT)


# ------------------------------------------------------------- normalisation

def _norm_text(value: Optional[str]) -> str:
    return " ".join(str(value or "").lower().split())


def _norm_type(value: Optional[str]) -> str:
    return _norm_text(value).replace("-", " ")


def _parse_amenities(raw: str) -> Optional[List[str]]:
    """Property amenities JSON → list; None means the data is unusable."""
    try:
        parsed = json.loads(raw or "[]")
    except (ValueError, TypeError):
        return None
    if not isinstance(parsed, list):
        return None
    return [str(item).strip().lower() for item in parsed if str(item).strip()]


# --------------------------------------------------------- hard eligibility

def hard_requirement_failures(
    prop: Property, extraction: LeadExtractionResult,
) -> List[str]:
    """Reasons this record cannot be shown for this lead (empty = eligible).

    Defends in depth: the DB CHECK/defaults already guarantee verified
    purpose + approval + availability, and the query pre-filters them, but
    the predicate re-checks everything so a record can never slip through.
    """
    failures: List[str] = []
    if not is_verified_purpose(prop.purpose):
        failures.append(f"purpose {prop.purpose!r} is not verified")
    if not prop.is_approved:
        failures.append("property is not approved")
    if prop.availability != "available":
        failures.append(f"property is {prop.availability}")
    wanted = _INTENT_TO_PURPOSE.get(extraction.intent)
    if wanted and prop.purpose != wanted:
        failures.append(
            f"intent '{extraction.intent}' conflicts with purpose '{prop.purpose}'")
    if extraction.bedrooms is not None and prop.bedrooms < extraction.bedrooms:
        failures.append(
            f"bedrooms: lead requires >= {extraction.bedrooms}, property has {prop.bedrooms}")
    if extraction.bathrooms is not None and prop.bathrooms < extraction.bathrooms:
        failures.append(
            f"bathrooms: lead requires >= {extraction.bathrooms}, property has {prop.bathrooms}")
    if extraction.property_type and _norm_type(prop.property_type) != _norm_type(extraction.property_type):
        failures.append(
            f"type: lead wants '{extraction.property_type}', property is '{prop.property_type}'")
    return failures


# ---------------------------------------------------------------- scoring

def _score_location(prop, extraction, breakdown, reasons, mismatches):
    if not extraction.location:
        breakdown["location"] = 0.0
        mismatches.append("Location: not provided by lead (0/30 — missing data is not a match)")
        return
    lead_loc = _norm_text(extraction.location)
    prop_loc = _norm_text(prop.location)
    if lead_loc == prop_loc:
        breakdown["location"] = 30.0
        reasons.append(f"Location: exact community match ({prop.location}) — 30/30")
    elif lead_loc in prop_loc or prop_loc in lead_loc:
        breakdown["location"] = 20.0
        reasons.append(
            f"Location: partial community match ('{extraction.location}' ~ '{prop.location}') — 20/30")
    else:
        breakdown["location"] = 0.0
        mismatches.append(
            f"Location: lead wants '{extraction.location}', property is in '{prop.location}' (0/30)")


def _budget_comparable(extraction) -> Tuple[bool, str]:
    """Whether lead budget semantics can be compared to this property's price."""
    if extraction.intent not in _INTENT_TO_PURPOSE:
        return False, ("Budget: intent unknown — price semantics cannot be "
                       "aligned (0/25)")
    if extraction.budget_min is None and extraction.budget_max is None:
        return False, ("Budget: no amount provided — nothing to compare "
                       "(0/25)")
    if extraction.budget_currency is None:
        return False, ("Budget: currency not provided — incompatible/unknown "
                       "currency is never assumed (0/25)")
    if extraction.intent == "buy":
        if extraction.budget_period in ("monthly", "yearly"):
            return False, (f"Budget: stated as {extraction.budget_period} but a "
                           "purchase price is a total amount — contradictory "
                           "period (0/25)")
        return True, ""
    # rent / lease: property.price is the YEARLY amount (schema limitation)
    if extraction.budget_period is None:
        return False, ("Budget: rent period unspecified — never assumed "
                       "(property rents are yearly) (0/25)")
    if extraction.budget_period == "monthly":
        return False, ("Budget: lead budget is monthly but property rent is "
                       "quoted yearly — periods are not converted (0/25)")
    return True, ""


def _score_budget(prop, extraction, breakdown, reasons, mismatches):
    comparable, note = _budget_comparable(extraction)
    if not comparable:
        breakdown["budget"] = 0.0
        mismatches.append(note)
        return
    lead_ccy = extraction.budget_currency.upper()
    prop_ccy = str(prop.currency or "").upper()
    if lead_ccy != prop_ccy:
        breakdown["budget"] = 0.0
        mismatches.append(
            f"Budget: currency mismatch (lead {lead_ccy} vs property {prop_ccy}) "
            "— no conversion is assumed (0/25)")
        return

    price = prop.price
    if extraction.budget_max is not None and price > extraction.budget_max:
        breakdown["budget"] = 0.0
        mismatches.append(
            f"Budget: {price:,.0f} {prop_ccy} exceeds stated max "
            f"{extraction.budget_max:,.0f} (0/25)")
        return
    if extraction.budget_min is not None and price < extraction.budget_min:
        breakdown["budget"] = 0.0
        mismatches.append(
            f"Budget: {price:,.0f} {prop_ccy} below stated min "
            f"{extraction.budget_min:,.0f} (0/25)")
        return
    period_note = " (yearly rent)" if extraction.intent in ("rent", "lease") else ""
    breakdown["budget"] = 25.0
    reasons.append(
        f"Budget: {price:,.0f} {prop_ccy}{period_note} within stated bounds — 25/25")


def _score_type_bedrooms(prop, extraction, breakdown, reasons, mismatches):
    earned = 0.0
    if extraction.property_type:
        if _norm_type(prop.property_type) == _norm_type(extraction.property_type):
            earned += TYPE_SUB_WEIGHT
            reasons.append(
                f"Type: '{prop.property_type}' matches requirement — {TYPE_SUB_WEIGHT:.0f}/12")
        # hard filter already excludes mismatches; defensive zero kept silent
    else:
        mismatches.append("Type: not provided by lead (0/12 — missing data is not a match)")
    if extraction.bedrooms is not None:
        if prop.bedrooms >= extraction.bedrooms:
            earned += BEDROOMS_SUB_WEIGHT
            reasons.append(
                f"Bedrooms: {prop.bedrooms} meets >= {extraction.bedrooms} "
                f"requirement — {BEDROOMS_SUB_WEIGHT:.0f}/8")
        else:
            mismatches.append(
                f"Bedrooms: property has {prop.bedrooms}, lead needs >= {extraction.bedrooms} (0/8)")
    else:
        mismatches.append("Bedrooms: not provided by lead (0/8 — missing data is not a match)")
    breakdown["type_bedrooms"] = earned


def _score_amenities(prop, extraction, breakdown, reasons, mismatches, data_gaps):
    requested = [a.strip().lower() for a in extraction.amenities if a.strip()]
    if not requested:
        breakdown["amenities"] = 0.0
        mismatches.append("Amenities: none requested by lead (0/15 — missing data is not a match)")
        return
    available = _parse_amenities(prop.amenities)
    if available is None:
        breakdown["amenities"] = 0.0
        data_gaps.append("Amenities: property amenity data is unreadable — not counted as matched (0/15)")
        return
    matched = [a for a in requested if a in available]
    missing = [a for a in requested if a not in available]
    points = round(15.0 * len(matched) / len(requested), 2)
    breakdown["amenities"] = points
    if matched:
        reasons.append(
            f"Amenities: matched {', '.join(matched)} ({len(matched)}/{len(requested)}) — {points}/15")
    if missing:
        mismatches.append(
            f"Amenities: not offered — {', '.join(missing)} ({len(matched)}/{len(requested)} matched)")


def _score_preferences(prop, extraction, breakdown, reasons, mismatches, data_gaps):
    """'Area / other preferences' (10): the extraction schema has NO lead-side
    area field (documented limitation), so this dimension scores the lead's
    stated non-amenity preferences against the property's highlights text."""
    tokens = [p.strip().lower() for p in extraction.preferences if p.strip()]
    if not tokens:
        breakdown["preferences"] = 0.0
        mismatches.append("Preferences: none stated by lead (0/10 — missing data is not a match)")
        return
    highlights = (prop.highlights or "").lower()
    if not prop.highlights:
        breakdown["preferences"] = 0.0
        data_gaps.append("Preferences: property has no highlight data — not counted as matched (0/10)")
        return
    matched = [t for t in tokens if t in highlights]
    missing = [t for t in tokens if t not in highlights]
    points = round(10.0 * len(matched) / len(tokens), 2)
    breakdown["preferences"] = points
    if matched:
        reasons.append(
            f"Preferences: matched {', '.join(matched)} in highlights "
            f"({len(matched)}/{len(tokens)}) — {points}/10")
    if missing:
        mismatches.append(
            f"Preferences: not evidenced — {', '.join(missing)} ({len(matched)}/{len(tokens)} matched)")


def score_property(prop: Property, extraction: LeadExtractionResult) -> PropertyMatch:
    """Score ONE eligible property. Pure arithmetic over real DB fields."""
    breakdown: dict = {}
    reasons: List[str] = []
    mismatches: List[str] = []
    data_gaps: List[str] = []

    _score_location(prop, extraction, breakdown, reasons, mismatches)
    _score_budget(prop, extraction, breakdown, reasons, mismatches)
    _score_type_bedrooms(prop, extraction, breakdown, reasons, mismatches)
    _score_amenities(prop, extraction, breakdown, reasons, mismatches, data_gaps)
    _score_preferences(prop, extraction, breakdown, reasons, mismatches, data_gaps)

    total = round(min(100.0, max(0.0, sum(breakdown.values()))), 2)
    return PropertyMatch(
        property_id=prop.id,
        external_ref=prop.external_ref,
        title=prop.title,
        is_demo=bool(prop.is_demo),
        purpose=prop.purpose,
        price=prop.price,
        currency=prop.currency,
        location=prop.location,
        property_type=prop.property_type,
        bedrooms=prop.bedrooms,
        bathrooms=prop.bathrooms,
        area=prop.area,
        area_unit=prop.area_unit,
        match_score=total,
        breakdown=breakdown,
        reasons=reasons,
        mismatches=mismatches,
        data_gaps=data_gaps,
    )


# ---------------------------------------------------------------- matching

def match_properties(
    db: Session,
    extraction: Union[LeadExtractionResult, dict],
    limit: int = DEFAULT_LIMIT,
) -> MatchResult:
    """Rank approved+available ``properties`` rows for one extraction.

    Read-only: this function never writes to the database (persistence is
    the separate ``save_recommendations``).
    """
    if not isinstance(extraction, LeadExtractionResult):
        extraction = LeadExtractionResult.model_validate(extraction)
    # Deterministic clamp: any invalid limit falls back/limits to 1..MAX_LIMIT
    # (the endpoint additionally validates 1..10 via Pydantic).
    limit = DEFAULT_LIMIT if limit is None else int(limit)
    limit = max(1, min(limit, MAX_LIMIT))

    purpose = _INTENT_TO_PURPOSE.get(extraction.intent)  # None for unknown
    pool = search_property_records(
        db,
        purpose=purpose,
        availability="available",
        approved_only=True,
        limit=MAX_CANDIDATES,
    )["results"]

    eligible: List[Tuple[Property, PropertyMatch]] = []
    for prop in pool:
        if hard_requirement_failures(prop, extraction):
            continue
        eligible.append((prop, score_property(prop, extraction)))

    # Stable ordering: score DESC, price ASC, id ASC.
    eligible.sort(key=lambda pair: (-pair[1].match_score, pair[1].price,
                                    pair[1].property_id))
    top = [match for _, match in eligible[:limit]]

    considered = len(pool)
    if top:
        explanation = (
            f"{len(eligible)} of {considered} approved+available candidate(s) "
            f"met the hard requirements; showing top {len(top)} "
            "(score DESC, price ASC, id ASC)."
        )
    else:
        explanation = (
            f"No eligible properties: 0 of {considered} approved+available "
            "candidate(s) passed the hard requirements (verified purpose, "
            "stated intent, bedrooms/bathrooms/type). Nothing was invented or "
            "substituted from the JSON dataset."
        )
    return MatchResult(
        results=top,
        candidates_considered=considered,
        eligible_count=len(eligible),
        explanation=explanation,
    )


# ------------------------------------------------------------- persistence

def save_recommendations(
    db: Session,
    match_result: MatchResult,
    *,
    lead_id: Optional[int] = None,
    conversation_id: Optional[int] = None,
) -> List[int]:
    """Explicitly persist ranked results to ``property_recommendations``.

    Uses ONLY existing Phase 2 columns (no schema change):
    ``property_record_id`` stores the real ``properties.id``; ``match_score``,
    ``match_reasons`` and ``match_mismatches`` store the computed score and
    explanations (data gaps are folded into the mismatches JSON with a
    'data gap:' prefix — the schema has exactly two explanation slots).
    ``property_id`` stays NULL (it historically held JSON-dataset ids).

    Never creates leads and never touches customer/conversation records.
    Invalid references raise ValueError (nothing is written).
    """
    if lead_id is not None and db.query(Lead).filter(Lead.id == lead_id).first() is None:
        raise ValueError(f"lead {lead_id} does not exist")
    if conversation_id is not None and \
            db.query(Conversation).filter(Conversation.id == conversation_id).first() is None:
        raise ValueError(f"conversation {conversation_id} does not exist")

    created: List[int] = []
    for match in match_result.results:
        prop = db.query(Property).filter(Property.id == match.property_id).first()
        if prop is None:
            raise ValueError(f"property {match.property_id} does not exist")
        rec = PropertyRecommendation(
            conversation_id=conversation_id,
            lead_id=lead_id,
            property_id=None,                       # never a dataset id
            price=f"{prop.price:,.0f} {prop.currency}",
            property_type=prop.property_type,
            location=prop.location,
            bedrooms=prop.bedrooms,
            bathrooms=float(prop.bathrooms),
            area=(f"{prop.area:,.0f} {prop.area_unit}" if prop.area else None),
            highlights=prop.highlights,
            relevance_score=round(match.match_score / 100.0, 4),
            match_score=match.match_score,
            match_reasons=json.dumps(match.reasons, ensure_ascii=False),
            match_mismatches=json.dumps(
                list(match.mismatches)
                + [f"data gap: {gap}" for gap in match.data_gaps],
                ensure_ascii=False,
            ),
            property_record_id=prop.id,
        )
        db.add(rec)
        db.flush()
        created.append(rec.id)
    db.commit()
    return created
