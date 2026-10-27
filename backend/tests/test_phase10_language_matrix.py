"""Phase 10 — table-driven language detection matrix (English / Tamil script /
Tanglish / mixed), plus known-limitation documentation.

Expectations are derived from the IMPLEMENTATION (`detect_language_and_style`,
agent.py), not from language labels: Tamil script dominates, Tanglish needs
>=2 dictionary words or >=1 suffix, and everything else defaults to English.
Construction of AIRealEstateAgent is local-only (no network).
"""

import pytest

from app.ai.agent import AIRealEstateAgent
from app.ai.nvidia_client import NVIDIAClient


@pytest.fixture()
def agent():
    return AIRealEstateAgent()


# (message, expected_language, why) — expected values match the implementation.
MATRIX = [
    # ---------------- English ----------------
    ("Hi, I'm looking for a villa in Dubai", "en", "plain English"),
    ("Show me 2 bedroom apartments under 2 million", "en", "English search"),
    ("please find me something near the marina", "en", "English request"),
    ("hello", "en", "short English greeting"),
    ("thank you", "en", "short thanks"),
    ("ok", "en", "very short / ambiguous — defaults to English"),
    ("2", "en", "digits only — no words to classify"),
    ("", "en", "empty input defaults to English (never crashes)"),
    ("     ", "en", "whitespace-only defaults to English"),
    # ---------------- Tamil script ----------------
    ("வணக்கம், எனக்கு ஒரு வீடு வேண்டும்", "ta", "pure Tamil script"),
    ("பட்ஜெட் எவ்வளவு?", "ta", "short Tamil script question"),
    # ---------------- Mixed (Tamil script + English structure) ----------------
    ("எனக்கு ஒரு villa வேண்டும், I need a 3 bedroom", "mixed",
     "Tamil script + English structural words"),
    # ---------------- Tanglish (Latin script) ----------------
    ("marina-ku villa venum", "ta-Latn", "suffix + dictionary words"),
    ("Dubai Marina-la villa irukkaa?", "ta-Latn", "-la suffix pattern"),
    ("villa venum", "ta-Latn", "single dictionary word, no English structure"),
    ("enna price?", "ta-Latn", "single dictionary word, no English structure"),
    ("enna", "ta-Latn", "single dictionary word alone"),
    # ---------------- Known limitations (documented actual behavior) ----------------
    ("I really want to please show find thank you venum", "en",
     "LIMITATION: one Tanglish word drowned in English structure → English"),
    ("Dubai villa வேண்டும்", "ta",
     "LIMITATION: Tamil script dominates even with Latin words and no "
     "English structural words (classified 'ta', not 'mixed')"),
]


@pytest.mark.parametrize("text,expected,why", MATRIX,
                         ids=[m[0] or "<empty>" for m in MATRIX])
def test_language_detection_matrix(agent, text, expected, why):
    lang, style = agent.detect_language_and_style(text)
    assert lang == expected, f"{why!r}: got {lang!r}"
    assert style in ("en", "ta", "ta-Latn")


def test_style_matches_language_codes(agent):
    assert agent.detect_language_and_style("hello") == ("en", "en")
    assert agent.detect_language_and_style("வணக்கம்") == ("ta", "ta")
    assert agent.detect_language_and_style("villa venum") == ("ta-Latn", "ta-Latn")


# ---------------- fallback language behavior (Phase 10 ta-Latn fix) ----------------

def test_tanglish_fallback_is_tamil_canned():
    """Phase 10 fix: ta-Latn no longer falls through to the English canned
    reply on provider failure; it matches the 'mixed' Tamil canned reply."""
    client = NVIDIAClient()
    out_ta = client._fallback_response("hello", "ta")
    out_mixed = client._fallback_response("hello", "mixed")
    out_talatn = client._fallback_response("hello", "ta-Latn")
    assert out_talatn == out_ta == out_mixed
    assert sum(1 for ch in out_talatn if "ீ" <= ch <= "௿") > 20


def test_english_fallback_behavior_unchanged():
    client = NVIDIAClient()
    assert "LykAI" in client._fallback_response("hello", "en")
    assert "LykAI" in client._fallback_response("hello", "auto")


def test_reply_language_does_not_change_thinking_flags():
    """English/Tanglish keep thinking OFF; Tamil-script keeps it ON — the
    Phase 10 fallback change must not alter the speed contract."""
    client = NVIDIAClient()
    assert client.should_think("ta-Latn") is False
    assert client.should_think("ta") is True
