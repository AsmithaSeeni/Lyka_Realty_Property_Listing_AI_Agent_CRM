"""Server-side lead temperature classification (hot | warm | cold).

Deterministic, transparent rules — no LLM. Every decision stores its evidence
in `leads.temperature_rationale` so agents can see WHY a lead is classified
the way it is. Follow-up is a SEPARATE concept (stored on `follow_ups` and
surfaced through due/overdue buckets): a hot lead may also be awaiting a
scheduled callback, and a cold lead may still have a follow-up due.

Classification rules (configurable constants below):

HOT  — strong intent AND reasonably specific requirements AND a near-term
       timeline or a concrete next step:
         * intent known (buy/rent), AND
         * >= 3 core requirements known (location, property_type, bedrooms,
           budget), AND
         * (timeline within NEAR_TERM_DAYS, or urgent/near-term wording, or a
           next-step signal: viewing requested, callback requested, "contact
           me", "send details", ready to proceed).
WARM — genuine, identifiable interest but no confirmed immediate next step:
         * intent known AND >= 2 core requirements — and not HOT.
COLD — early-stage browsing, vague intent or low engagement:
         * everything else (< 2 core requirements, or no intent at all).

Guard rails (enforced by tests):
  * A missing phone/email NEVER makes a lead cold on its own.
  * A budget alone NEVER makes a lead hot (one requirement is not specificity).
  * Unanswered questions are never treated as negative intent.
  * Not every lead is hot — HOT requires specificity AND a next-step/timeline.
  * A human's manual choice (`temperature_source == "manual"`) is never
    silently overwritten by automatic recomputation unless `force=True`.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

NEAR_TERM_DAYS = 30
HOT_MIN_REQUIREMENTS = 3
WARM_MIN_REQUIREMENTS = 2

NEAR_TERM_WORDS = re.compile(
    r"\b(immediate|immediately|asap|urgent|this month|end of month|"
    r"next month|within \d+ ?(days|weeks)|moving (now|soon)|ready to move|"
    r"today|tomorrow|this week|next week)\b",
    re.IGNORECASE,
)
NEXT_STEP_WORDS = re.compile(
    r"\b(viewing|view it|visit|schedule|callback|call me|contact me|"
    r"whatsapp me|message me|send (me )?(details|documents)|"
    r"book|proceed|ready to (buy|rent|proceed)|share (it )?over|"
    r"arrange a (call|meeting)|meeting|appointment)\b",
    re.IGNORECASE,
)

TEMPERATURES = ("hot", "warm", "cold")


def _truthy(value: Any) -> bool:
    return value is not None and value != "" and value != []


def classify_lead_temperature(
    *,
    buy_rent: Optional[str] = None,
    location: Optional[str] = None,
    property_type: Optional[str] = None,
    bedrooms: Optional[int] = None,
    budget: Optional[str] = None,
    timeline: Optional[str] = None,
    timeline_days: Optional[int] = None,
    text: Optional[str] = None,
) -> Dict[str, Any]:
    """Classify a lead's temperature from its stored facts.

    Returns {"temperature", "rules": [...], "evidence": [...]} — never a
    fabricated value: insufficient evidence classifies as "cold" with the
    exact missing-fact reasons recorded.
    """
    requirements = {
        "intent": buy_rent if buy_rent in ("buy", "rent") else None,
        "location": location,
        "property_type": property_type,
        "bedrooms": bedrooms,
        "budget": budget,
    }
    known = [name for name, value in requirements.items() if _truthy(value)]
    rules: List[str] = []
    evidence: List[str] = [
        f"core requirements known ({len(known)}/5): "
        + (", ".join(known) if known else "none")
    ]

    corpus = " ".join(
        str(part) for part in (text or "", timeline or "") if part
    ).strip()
    near_term = bool(timeline_days is not None and timeline_days <= NEAR_TERM_DAYS)
    if near_term:
        evidence.append(f"timeline within {NEAR_TERM_DAYS} days ({timeline_days})")
    elif timeline and NEAR_TERM_WORDS.search(timeline):
        near_term = True
        evidence.append(f"near-term timeline wording: {timeline!r}")
    elif corpus and NEAR_TERM_WORDS.search(corpus):
        near_term = True
        match = NEAR_TERM_WORDS.search(corpus)
        evidence.append(f"near-term wording in conversation: {match.group(0)!r}")

    next_step = bool(corpus and NEXT_STEP_WORDS.search(corpus))
    if next_step:
        match = NEXT_STEP_WORDS.search(corpus)
        evidence.append(f"concrete next-step signal: {match.group(0)!r}")

    intent = requirements["intent"]
    if intent:
        evidence.append(f"stated intent: {intent}")
    else:
        rules.append("no-intent-is-cold")

    if intent and len(known) >= HOT_MIN_REQUIREMENTS and (near_term or next_step):
        temperature = "hot"
        rules += ["intent+specificity+near-term/next-step"]
    elif intent and len(known) >= WARM_MIN_REQUIREMENTS:
        temperature = "warm"
        rules += ["intent+identifiable-requirements"]
    else:
        temperature = "cold"
        rules.append(
            "insufficient-evidence"
            if not intent
            else "intent-known-but-requirements-too-vague"
        )
        # NOTE: contact details are deliberately NOT inputs to this function —
        # a missing phone/email can never make a lead cold (module guard rail).

    return {
        "temperature": temperature,
        "rules": rules,
        "evidence": evidence,
    }


def apply_temperature(lead: Any, *, text: Optional[str] = None, force: bool = False) -> bool:
    """Classify and store temperature + rationale on a lead row.

    Skips (returns False) when a human set the temperature manually and
    `force` is not requested — an agent's manual classification is never
    silently overwritten by the automatic rules.
    """
    if getattr(lead, "temperature_source", None) == "manual" and not force:
        return False

    # Rolling conversation evidence: carry the previous corpus forward so a
    # concrete next-step signal ("call me this week") does not silently decay
    # when the following message is generic ("ok"). Capped to stay compact.
    prior = parse_rationale(getattr(lead, "temperature_rationale", None)) or {}
    prior_corpus = str(prior.get("corpus") or "")
    corpus = f"{prior_corpus} {text or ''}".strip()[-1500:]

    result = classify_lead_temperature(
        buy_rent=getattr(lead, "buy_rent", None),
        location=getattr(lead, "location", None),
        property_type=getattr(lead, "property_type", None),
        bedrooms=getattr(lead, "bedrooms", None),
        budget=getattr(lead, "budget", None),
        timeline=getattr(lead, "timeline", None),
        timeline_days=getattr(lead, "timeline_days", None),
        text=corpus or None,
    )
    now = datetime.utcnow()
    lead.temperature = result["temperature"]
    lead.temperature_rationale = json.dumps(
        {
            **result,
            "corpus": corpus,
            "at": now.isoformat() + "Z",
        },
        ensure_ascii=False,
    )
    if not (getattr(lead, "temperature_source", None) == "manual" and not force):
        lead.temperature_source = "auto"
    lead.temperature_updated_at = now
    return True


def parse_rationale(raw: Optional[str]) -> Optional[Dict[str, Any]]:
    """JSON column -> dict; unreadable/absent -> None (never guessed)."""
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None
