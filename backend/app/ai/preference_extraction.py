"""LLM-assisted structured preference extraction for LIVE chat turns.

Layering (root fix for repeated questions):
  1. Deterministic rules — `agent._extract_requirements` — always run first:
     instant, offline, and the guaranteed baseline.
  2. THIS module optionally runs an LLM structured-output pass over the SAME
     message to catch phrasings the rules miss (unusual locations, budgets
     without keyword context, furnishing nuances, Tanglish variants).
  3. Any provider failure or absence degrades silently to rules-only — the
     conversation never blocks or errors on extraction.

Provider chain:
  1. NVIDIA `chat_json_sync` (the chat provider — key is guaranteed wherever
     chat works; JSON-mode capability is cached on the client).
  2. OpenAI `chat_json` (the existing structured-output helper used by the
     staff extraction tool: temperature 0, response_format json_object).
  3. None → caller keeps rules-only state.

Merge policy lives in `AIRealEstateAgent.merge_llm_extractions`: only fields
the customer explicitly stated in THIS message may change; every other stored
slot is retained (merge, never replace). Unknowns are omitted, never invented.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional

from app.ai.nvidia_client import NVIDIAClient

logger = logging.getLogger(__name__)

# Single NVIDIA client for extraction (separate from the conversational one so
# their capability caches/keys never interfere).
_nvidia = NVIDIAClient()

# Fields the extraction layer may ever emit — everything else is rejected.
ALLOWED_REQUIREMENTS = {
    "buy_rent",
    "location",
    "property_type",
    "bedrooms",
    "bathrooms",
    "furnishing",
    "budget",
    "budget_period",
    "timeline",
    "investment_purpose",
    "area",
}
ALLOWED_CONTACT = {"name", "phone", "email"}

_BUY_RENT = {"rent", "buy"}
_FURNISHING = {
    "furnished": "Furnished",
    "unfurnished": "Unfurnished",
    "semi-furnished": "Semi-furnished",
    "semi furnished": "Semi-furnished",
    "partially furnished": "Semi-furnished",
    "semi": "Semi-furnished",
}
_BUDGET_PERIODS = {"monthly", "yearly", "one_time", "one-time", "onetime"}
_BUDGET_PERIOD_CANON = {
    "monthly": "monthly",
    "yearly": "yearly",
    "one_time": "one_time",
    "one-time": "one_time",
    "onetime": "one_time",
}
_PURPOSES = {"investment": "investment", "self_use": "self_use",
             "self-use": "self_use", "own use": "self_use",
             "living": "self_use", "family": "self_use"}

_EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+\.[\w.]+$")

EXTRACTION_SYSTEM_PROMPT = """You extract real-estate customer preferences from ONE chat message.

Output ONLY a JSON object, no commentary, no markdown:
{"requirements": {...}, "contact": {...}}

STRICT RULES:
- Include a field ONLY when the customer explicitly stated or CHANGED it in
  the message given to you. Otherwise OMIT the field. Never infer from earlier
  conversation, never invent values, never copy the "ALREADY KNOWN" block into
  the output (it is context so you do not re-emit unchanged facts).
- requirements keys (only these):
    buy_rent: "rent" | "buy"
    location: place name as written (e.g. "Dubai Marina", "JVC")
    property_type: apartment|villa|townhouse|studio|penthouse|land|office|shop
    bedrooms: integer (studio = 0)
    bathrooms: integer
    furnishing: "Furnished" | "Unfurnished" | "Semi-furnished"
    budget: number only (AED amount, no commas/currency words)
    budget_period: "monthly" | "yearly" | "one_time"
    timeline: short phrase as stated (e.g. "immediate", "within 2 months")
    investment_purpose: "investment" | "self_use"
    area: area string as stated (e.g. "1200 sqft")
- contact keys: name, phone (digits and + only), email.
- buy_rent: "rent" only for rental intent, "buy" only for purchase intent.
  A rental period stated with a budget ("70,000 AED yearly", "per month",
  "monthly rent") establishes RENT intent; a one-time/total property price
  establishes BUY intent. If neither the message nor such a period supports
  intent, omit buy_rent entirely.
- Understand Tanglish, Tamil and English; extract the same fields regardless
  of the language the customer wrote in.
- If the message contains no stated preference or contact fact, output {}.
"""


def _parse_json_text(text: Any) -> Optional[Dict[str, Any]]:
    """Parse model output into a dict; tolerates code fences; never raises."""
    if not isinstance(text, str) or not text.strip():
        return None
    raw = text.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", raw, re.DOTALL)
    if fence:
        raw = fence.group(1)
    # Tolerate leading prose before the first brace (some models preface).
    if not raw.startswith("{"):
        start = raw.find("{")
        end = raw.rfind("}")
        if start == -1 or end <= start:
            return None
        raw = raw[start:end + 1]
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _clean_str(value: Any, max_len: int) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split()).strip()
    if not text or len(text) > max_len:
        return None
    return text


def _as_int(value: Any, lo: int, hi: int) -> Optional[int]:
    try:
        number = int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return None
    return number if lo <= number <= hi else None


def _as_number(value: Any) -> Optional[float]:
    try:
        number = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    if number != number or number <= 0 or number > 10_000_000_000:
        return None
    return number


def validate_updates(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Type/range-validate a parsed model response; drop anything invalid.

    Never guesses: an out-of-range or malformed field is omitted entirely.
    """
    out: Dict[str, Any] = {"requirements": {}, "contact": {}}
    if not isinstance(raw, dict):
        return out

    req = raw.get("requirements")
    if isinstance(req, dict):
        value = str(req.get("buy_rent") or "").strip().lower()
        if value in _BUY_RENT:
            out["requirements"]["buy_rent"] = value

        location = _clean_str(req.get("location"), 80)
        if location and location.lower() not in ("unknown", "none", "null", "n/a"):
            out["requirements"]["location"] = location

        ptype = _clean_str(req.get("property_type"), 40)
        if ptype:
            out["requirements"]["property_type"] = ptype.lower()

        bedrooms = _as_int(req.get("bedrooms"), 0, 20)
        if bedrooms is not None:
            out["requirements"]["bedrooms"] = bedrooms
        bathrooms = _as_int(req.get("bathrooms"), 0, 20)
        if bathrooms is not None:
            out["requirements"]["bathrooms"] = bathrooms

        furnishing = _clean_str(req.get("furnishing"), 30)
        if furnishing:
            canonical = _FURNISHING.get(furnishing.lower())
            if canonical:
                out["requirements"]["furnishing"] = canonical

        budget = _as_number(req.get("budget"))
        if budget is not None:
            out["requirements"]["budget"] = budget

        period = _clean_str(req.get("budget_period"), 12)
        if period and period.lower() in _BUDGET_PERIODS:
            out["requirements"]["budget_period"] = _BUDGET_PERIOD_CANON[period.lower()]

        timeline = _clean_str(req.get("timeline"), 60)
        if timeline:
            out["requirements"]["timeline"] = timeline

        purpose = _clean_str(req.get("investment_purpose"), 20)
        if purpose:
            canonical = _PURPOSES.get(purpose.lower())
            if canonical:
                out["requirements"]["investment_purpose"] = canonical

        area = _clean_str(req.get("area"), 40)
        if area:
            out["requirements"]["area"] = area

    contact = raw.get("contact")
    if isinstance(contact, dict):
        name = _clean_str(contact.get("name"), 80)
        if name and re.fullmatch(r"[A-Za-z\u0B80-\u0BFF][A-Za-z\u0B80-\u0BFF.'\- ]*", name):
            out["contact"]["name"] = name
        phone = contact.get("phone")
        if isinstance(phone, str):
            digits = re.sub(r"[^\d+]", "", phone)
            if 9 <= len(digits.lstrip("+")) <= 14 and digits.lstrip("+").isdigit():
                out["contact"]["phone"] = digits
        email = _clean_str(contact.get("email"), 120)
        if email and _EMAIL_RE.match(email):
            out["contact"]["email"] = email

    if not out["requirements"] and not out["contact"]:
        return {"requirements": {}, "contact": {}}
    return out


def _user_prompt(message: str,
                 requirements: Optional[Dict[str, Any]] = None,
                 contact: Optional[Dict[str, Any]] = None) -> str:
    known_bits = []
    for key in sorted(ALLOWED_REQUIREMENTS):
        value = (requirements or {}).get(key)
        if value not in (None, "", []):
            known_bits.append(f"{key}={value}")
    for key in sorted(ALLOWED_CONTACT):
        if (contact or {}).get(key):
            known_bits.append(f"contact.{key}=present")
    known = ", ".join(known_bits) or "none"
    return (
        f"ALREADY KNOWN (do not re-output unless the message changes it): {known}\n\n"
        f"MESSAGE:\n{message}"
    )


def extract_updates(
    message: str,
    *,
    requirements: Optional[Dict[str, Any]] = None,
    contact: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """LLM structured extraction for ONE message. Returns validated
    {"requirements": {...}, "contact": {...}} (fields present ONLY when
    stated), or None when no provider answered — callers stay rules-only.

    Never raises: provider/parse/validation failures all collapse to None.
    """
    if len(message.split()) < 4:
        # Greetings/acks carry no facts — skip the round-trip entirely.
        return None

    user_prompt = _user_prompt(message, requirements, contact)

    parsed: Optional[Dict[str, Any]] = None
    try:
        raw_text = _nvidia.chat_json_sync(EXTRACTION_SYSTEM_PROMPT, user_prompt)
        parsed = _parse_json_text(raw_text)
    except Exception as exc:  # noqa: BLE001 — extraction must never break chat
        logger.warning("NVIDIA preference extraction failed: %s", exc)
        parsed = None

    if parsed is None:
        try:
            from app.ai.openai_client import OpenAIClientError, chat_json

            parsed = chat_json(EXTRACTION_SYSTEM_PROMPT, user_prompt, max_tokens=700)
        except Exception as exc:  # noqa: BLE001 — includes missing-config
            logger.debug("OpenAI preference extraction unavailable: %s", exc)
            parsed = None

    if parsed is None:
        return None
    return validate_updates(parsed)
