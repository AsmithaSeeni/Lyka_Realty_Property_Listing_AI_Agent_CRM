"""Deterministic lead scoring — Phase 4.

Pure Python. No database access, no LLM involvement: the model never assigns
a score or priority; it only supplies the validated extraction fields that
this module scores with the fixed rubric below.

Rubric (maximum 100):
    Budget provided ...................... 20
    Location provided .................... 20
    Property type OR bedrooms ............ 15   (one criterion, never both)
    Intent confirmed (buy/rent/lease) .... 15
    Timeline <= 30 days .................. 20
    Timeline 31-90 days .................. 15
    Timeline > 90 days ................... 5
    Timeline unknown ..................... 0
    Essential preferences provided ....... 10

Priority: high 70-100, medium 40-69, low 0-39.

Essential-preferences rule (documented, deterministic, no new category):
"Essential preferences provided" means the validated extraction contains at
least ONE amenity OR at least one non-amenity preference (non-empty
``amenities`` or ``preferences`` list after Phase 3 validation). It reuses
the existing extraction fields only.

Timeline rule: days are used ONLY from the validated ``timeline_days``
integer (Phase 3 produces it solely when the wording clearly implies a
timeframe). Free-text ``timeline`` is never parsed here, so an ambiguous
"soon" can never earn timeline points.
"""

from typing import List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from app.ai.lead_extraction import LeadExtractionResult

MAX_SCORE = 100

CRITERIA_POINTS = {
    "budget": 20,
    "location": 20,
    "type_or_bedrooms": 15,
    "intent": 15,
    # timeline is banded: <=30 -> 20, 31-90 -> 15, >90 -> 5, unknown -> 0
    "timeline_0_30": 20,
    "timeline_31_90": 15,
    "timeline_90_plus": 5,
    "essential_preferences": 10,
}


class CriterionBreakdown(BaseModel):
    """One auditable line of the score breakdown."""
    model_config = ConfigDict(extra="ignore")

    criterion: str
    awarded: int
    maximum: int
    reason: str


class LeadScoreResult(BaseModel):
    """Structured, deterministic scoring output."""
    model_config = ConfigDict(extra="ignore")

    total_score: int = Field(ge=0, le=MAX_SCORE)
    priority: Literal["high", "medium", "low"]
    breakdown: List[CriterionBreakdown]


class LeadScoringError(RuntimeError):
    """Internal invariant violation (never a provider/database failure)."""


def classify_priority(total: int) -> Literal["high", "medium", "low"]:
    """high 70-100 · medium 40-69 · low 0-39 (pure, tested at boundaries)."""
    if total >= 70:
        return "high"
    if total >= 40:
        return "medium"
    return "low"


def _timeline_points(timeline_days: Optional[int]) -> tuple:
    """Mutually exclusive bands; returns (points, reason).

    Only a positive integer day count (as produced by the validated Phase 3
    extraction) is usable; zero/negative values are treated as unknown —
    an invalid timeline can never earn points.
    """
    if timeline_days is None or timeline_days < 1:
        return 0, "Timeline unknown or invalid — no points (missing data is never rewarded)"
    if timeline_days <= 30:
        return 20, f"Timeline {timeline_days} days — within 30 days (20 pts)"
    if timeline_days <= 90:
        return 15, f"Timeline {timeline_days} days — 31-90 days (15 pts)"
    return 5, f"Timeline {timeline_days} days — over 90 days (5 pts)"


def _as_extraction(
    extraction: Union[LeadExtractionResult, dict],
) -> LeadExtractionResult:
    """Accept the Phase 3 result or a client dict; always re-validate.

    Client-supplied score/priority fields are IGNORED (extra="ignore") —
    only these validated criteria fields ever influence the score.
    """
    if isinstance(extraction, LeadExtractionResult):
        return extraction
    return LeadExtractionResult.model_validate(extraction)


def score_lead(
    extraction: Union[LeadExtractionResult, dict],
) -> LeadScoreResult:
    """Score one validated extraction. Pure: no DB, no network, no LLM."""
    data = _as_extraction(extraction)
    breakdown: List[CriterionBreakdown] = []

    # --- Budget (20) -------------------------------------------------------
    has_budget = data.budget_min is not None or data.budget_max is not None
    if has_budget:
        detail = []
        if data.budget_min is not None:
            detail.append(f"min {data.budget_min:,.0f}")
        if data.budget_max is not None:
            detail.append(f"max {data.budget_max:,.0f}")
        currency = data.budget_currency or "unstated currency"
        reason = f"Budget provided ({' / '.join(detail)} {currency}) — 20 pts"
        breakdown.append(CriterionBreakdown(
            criterion="budget", awarded=20, maximum=20, reason=reason))
    else:
        breakdown.append(CriterionBreakdown(
            criterion="budget", awarded=0, maximum=20,
            reason="Budget not provided — 0 pts"))

    # --- Location (20) -----------------------------------------------------
    if data.location:
        breakdown.append(CriterionBreakdown(
            criterion="location", awarded=20, maximum=20,
            reason=f"Location provided ({data.location}) — 20 pts"))
    else:
        breakdown.append(CriterionBreakdown(
            criterion="location", awarded=0, maximum=20,
            reason="Location not provided — 0 pts"))

    # --- Property type OR bedrooms (15 — never both) -----------------------
    if data.property_type or data.bedrooms is not None:
        parts = []
        if data.property_type:
            parts.append(f"type={data.property_type}")
        if data.bedrooms is not None:
            parts.append(f"bedrooms={data.bedrooms}")
        breakdown.append(CriterionBreakdown(
            criterion="type_or_bedrooms", awarded=15, maximum=15,
            reason=f"Requirement stated ({', '.join(parts)}) — 15 pts"))
    else:
        breakdown.append(CriterionBreakdown(
            criterion="type_or_bedrooms", awarded=0, maximum=15,
            reason="Neither property type nor bedrooms stated — 0 pts"))

    # --- Intent (15) -------------------------------------------------------
    if data.intent in ("buy", "rent", "lease"):
        breakdown.append(CriterionBreakdown(
            criterion="intent", awarded=15, maximum=15,
            reason=f"Intent confirmed ({data.intent}) — 15 pts"))
    else:
        breakdown.append(CriterionBreakdown(
            criterion="intent", awarded=0, maximum=15,
            reason="Intent unknown — 0 pts"))

    # --- Timeline (banded, mutually exclusive) ----------------------------
    points, reason = _timeline_points(data.timeline_days)
    breakdown.append(CriterionBreakdown(
        criterion="timeline", awarded=points, maximum=20, reason=reason))

    # --- Essential preferences (10) ---------------------------------------
    if data.amenities or data.preferences:
        bits = []
        if data.amenities:
            bits.append(f"{len(data.amenities)} amenit(ies)")
        if data.preferences:
            bits.append(f"{len(data.preferences)} preference(s)")
        breakdown.append(CriterionBreakdown(
            criterion="essential_preferences", awarded=10, maximum=10,
            reason=f"Essential preferences stated ({', '.join(bits)}) — 10 pts"))
    else:
        breakdown.append(CriterionBreakdown(
            criterion="essential_preferences", awarded=0, maximum=10,
            reason="No amenities or preferences stated — 0 pts"))

    total = sum(item.awarded for item in breakdown)
    return _validated_result(total, breakdown)


def _validated_result(total: int, breakdown: List[CriterionBreakdown]) -> LeadScoreResult:
    """Final safety net: bounds, integer, sum, and priority consistency."""
    if not isinstance(total, int) or not (0 <= total <= MAX_SCORE):
        raise LeadScoringError(f"score out of bounds: {total!r}")
    for item in breakdown:
        if not (0 <= item.awarded <= item.maximum):
            raise LeadScoringError(
                f"awarded points outside criterion bounds: {item.criterion}")
    if sum(item.awarded for item in breakdown) != total:
        raise LeadScoringError("breakdown does not sum to the declared total")
    result = LeadScoreResult(
        total_score=total, priority=classify_priority(total),
        breakdown=breakdown)
    # Priority must match the thresholds exactly.
    if result.priority != classify_priority(result.total_score):
        raise LeadScoringError("priority does not match thresholds")
    return result


def validate_score_result(result: LeadScoreResult) -> bool:
    """Public invariant check (used by tests and future persistence)."""
    total = sum(c.awarded for c in result.breakdown)
    return (
        0 <= result.total_score <= MAX_SCORE
        and isinstance(result.total_score, int)
        and total == result.total_score
        and result.priority == classify_priority(result.total_score)
        and all(0 <= c.awarded <= c.maximum for c in result.breakdown)
    )
