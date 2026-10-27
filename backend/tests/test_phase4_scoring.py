"""Phase 4 — deterministic lead scoring (pure; no DB, no provider calls).

Every criterion of the mandated rubric is exercised, including exact
High/Medium/Low boundaries and the "score can never exceed 100" invariant.
"""

import pytest

from app.services.lead_scoring import (
    MAX_SCORE,
    LeadScoreResult,
    LeadScoringError,
    classify_priority,
    score_lead,
    validate_score_result,
)


def _crit(result, name):
    for item in result.breakdown:
        if item.criterion == name:
            return item
    raise AssertionError(f"criterion {name} missing from breakdown")


def _total(**fields):
    return score_lead(fields).total_score


# ---------------------------------------------------------- missing / single

def test_missing_all_fields_scores_zero_low():
    result = score_lead({})
    assert result.total_score == 0
    assert result.priority == "low"
    assert validate_score_result(result)
    # every criterion is explained, awarded and unawarded alike
    names = {c.criterion for c in result.breakdown}
    assert names == {"budget", "location", "type_or_bedrooms", "intent",
                     "timeline", "essential_preferences"}
    assert all(c.reason for c in result.breakdown)


def test_budget_only_scores_20():
    result = score_lead({"budget_max": 1_500_000, "budget_currency": "AED"})
    assert result.total_score == 20
    assert _crit(result, "budget").awarded == 20
    assert result.priority == "low"


def test_budget_min_only_also_counts():
    assert _total(budget_min=500_000) == 20


def test_location_only_scores_20():
    assert _total(location="Dubai Marina") == 20


def test_property_type_only_scores_15():
    assert _total(property_type="apartment") == 15


def test_bedrooms_only_scores_15():
    assert _total(bedrooms=2) == 15


def test_type_and_bedrooms_together_still_15_never_both():
    result = score_lead({"property_type": "apartment", "bedrooms": 2})
    assert _crit(result, "type_or_bedrooms").awarded == 15
    assert result.total_score == 15


@pytest.mark.parametrize("intent", ["buy", "rent", "lease"])
def test_confirmed_intent_scores_15(intent):
    assert _total(intent=intent) == 15


def test_unknown_intent_scores_0():
    result = score_lead({"intent": "unknown"})
    assert _crit(result, "intent").awarded == 0
    assert result.total_score == 0


# ----------------------------------------------------------------- timeline

@pytest.mark.parametrize("days,expected", [
    (30, 20),    # boundary: within 30
    (29, 20),
    (31, 15),    # boundary: 31-90
    (90, 15),    # boundary: 31-90 upper edge
    (91, 5),     # boundary: over 90
    (365, 5),
    (None, 0),   # unknown
    (0, 0),      # invalid — never earns "within 30"
    (-5, 0),     # invalid
])
def test_timeline_bands_mutually_exclusive(days, expected):
    result = score_lead({"timeline_days": days})
    assert _crit(result, "timeline").awarded == expected
    # only ONE timeline criterion line exists
    assert sum(1 for c in result.breakdown if c.criterion == "timeline") == 1


def test_free_text_timeline_alone_never_scores():
    # free-text only (no validated days) -> timeline points impossible
    assert _total(timeline="ASAP probably") == 0


# ------------------------------------------------------- essential preferences

def test_amenities_earn_essentials_10():
    result = score_lead({"amenities": ["balcony"]})
    assert _crit(result, "essential_preferences").awarded == 10


def test_preferences_alone_earn_essentials_10():
    assert _total(preferences=["pet friendly"]) == 10


def test_amenities_and_preferences_together_still_10():
    result = score_lead({"amenities": ["pool"], "preferences": ["high floor"]})
    assert _crit(result, "essential_preferences").awarded == 10


def test_no_essentials_earn_0():
    result = score_lead({"amenities": [], "preferences": []})
    assert _crit(result, "essential_preferences").awarded == 0


# ------------------------------------------------------------- totals & max

def test_all_criteria_satisfied_is_exactly_100():
    result = score_lead({
        "intent": "buy",
        "property_type": "apartment",
        "location": "Dubai Marina",
        "bedrooms": 2,
        "budget_max": 3_000_000,
        "budget_currency": "AED",
        "timeline_days": 30,
        "amenities": ["balcony", "swimming pool"],
    })
    assert result.total_score == MAX_SCORE == 100
    assert result.priority == "high"
    assert validate_score_result(result)


def test_score_never_exceeds_100_even_with_overflow_input():
    # A crafted dict cannot exceed the rubric: every criterion is capped.
    result = score_lead({
        "intent": "buy", "property_type": "villa", "bedrooms": 5,
        "location": "Downtown", "budget_min": 1, "budget_max": 10**12,
        "timeline_days": 1, "amenities": ["a"] * 20, "preferences": ["b"] * 20,
    })
    assert result.total_score == 100
    assert all(c.awarded <= c.maximum for c in result.breakdown)


def test_internal_invariant_violation_raises():
    from pydantic import ValidationError

    from app.services.lead_scoring import CriterionBreakdown, _validated_result

    # a breakdown that doesn't sum to the declared total is caught
    crafted = [CriterionBreakdown(criterion="budget", awarded=50,
                                  maximum=20, reason="impossible")]
    with pytest.raises(LeadScoringError):
        _validated_result(20, crafted)
    # a declared total above the rubric maximum is caught
    with pytest.raises(LeadScoringError):
        _validated_result(120, [CriterionBreakdown(
            criterion="budget", awarded=20, maximum=20, reason="x")])
    # the Pydantic model itself rejects out-of-range totals
    with pytest.raises(ValidationError):
        LeadScoreResult(total_score=101, priority="high", breakdown=[])
    # an unsummed result is detectable via the public invariant check
    bad = LeadScoreResult(total_score=80, priority="high", breakdown=[])
    assert validate_score_result(bad) is False


# ----------------------------------------------------------------- priority

@pytest.mark.parametrize("total,expected", [
    (100, "high"), (70, "high"),      # exact High boundary
    (69, "medium"), (40, "medium"),   # exact Medium boundaries
    (39, "low"), (0, "low"),          # exact Low boundaries
])
def test_priority_boundaries_exact(total, expected):
    assert classify_priority(total) == expected


@pytest.mark.parametrize("fields,expected_total,expected_priority", [
    ({"budget_max": 1e6, "location": "JVC", "property_type": "studio",
      "intent": "buy"}, 70, "high"),
    ({"budget_max": 1e6, "location": "JVC", "property_type": "studio"}, 55, "medium"),
    ({"budget_max": 1e6, "location": "JVC"}, 40, "medium"),
    ({"budget_max": 1e6, "intent": "buy"}, 35, "low"),
])
def test_pipeline_priority_bands(fields, expected_total, expected_priority):
    result = score_lead(fields)
    assert result.total_score == expected_total
    assert result.priority == expected_priority
    assert validate_score_result(result)


# --------------------------------------- provider isolation & score honesty

def test_scoring_never_touches_the_model(monkeypatch):
    """A provider failure can't fabricate a score: scoring never calls it."""
    import app.ai.openai_client as openai_client

    def boom(*args, **kwargs):
        raise AssertionError("scoring must never call the provider")

    monkeypatch.setattr(openai_client, "chat_json", boom)
    result = score_lead({"budget_max": 1e6, "intent": "rent", "bedrooms": 1})
    assert result.total_score == 50  # 20 budget + 15 bedrooms + 15 intent


def test_client_supplied_score_is_never_authoritative():
    payload = {
        "intent": "buy",
        "lead_score": 999,          # ignored (extra="ignore")
        "priority": "high",         # ignored
        "score_breakdown": {"budget": 20},
    }
    result = score_lead(payload)
    assert result.total_score == 15   # computed from validated fields only
    assert result.priority == "low"


def test_invalid_payload_rejected_by_validation():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        score_lead({"intent": "purchase this now", "bedrooms": "two"})
