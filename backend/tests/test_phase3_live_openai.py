"""Optional LIVE OpenAI extraction test — opt-IN only (Phase 10).

Two independent guards make this run only deliberately:
1. ``tests/conftest.py`` skips every ``live``/``live_openai`` test unless the
   environment variable ``RUN_LIVE_TESTS=1`` is set (default runs are fully
   offline, even when an API key exists);
2. the ``skipif`` below skips when ``OPENAI_API_KEY`` is not configured.

Makes exactly ONE real provider call only when BOTH guards pass.
"""

import pytest

from app.ai.lead_extraction import (
    INTENTS,
    LeadExtractionRequest,
    extract_lead_requirements,
)
from app.config import settings

pytestmark = pytest.mark.skipif(
    not settings.OPENAI_API_KEY,
    reason="OPENAI_API_KEY not configured — live OpenAI extraction skipped",
)


@pytest.mark.live_openai
def test_live_extraction_smoke():
    request = LeadExtractionRequest(
        enquiry=(
            "I want to rent a 1-bedroom apartment in Business Bay for about "
            "AED 120,000 per year, with a gym. I can move in next month."
        )
    )
    result = extract_lead_requirements(request)

    assert result.original_enquiry == request.enquiry
    assert result.intent in INTENTS
    assert result.intent in ("rent", "unknown")     # never guessed as buy
    # budget/currency survive validation when the model supplies them
    if result.budget_max is not None:
        assert result.budget_max > 0
        assert result.budget_currency == "AED"
    assert isinstance(result.missing_fields, list)
    assert isinstance(result.provenance, dict) and result.provenance
