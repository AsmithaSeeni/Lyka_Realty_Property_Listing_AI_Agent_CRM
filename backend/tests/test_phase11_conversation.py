"""Phase 11 - natural Tamil conversation, active listening, lead generation.

MOCKED vs LIVE (requirement: "Distinguish mocked tests from actual
model/API tests"):

* Everything here is MOCKED/OFFLINE except the two tests marked `live` at
  the bottom (skipped unless RUN_LIVE_TESTS=1). Mocked tests stub
  ``nvidia_client.chat_sync`` (or the voice services) and pin the
  DETERMINISTIC machinery behind conversation quality: language detection,
  reply-language routing, requirement retention, one-question enforcement,
  lead extraction/dedup, voice language hints, cold-start persistence and
  language-preserving fallbacks.
* The `live` tests call the real NVIDIA API through ``respond()`` and assert
  measurable reply-quality properties (script match, at most one question,
  no Markdown/self-talk leaks) while printing the actual replies for
  human review.

Requirement -> test map (the 15 required automated-test categories):
 1. Casual Tamil conversation ........ test_prompt_carries_... + live tests
 2. Tamil-script conversation ........ test_tamil_script_...
 3. Tanglish conversation ............ test_tanglish_... (the reproduced bug)
 4. English conversation ............. test_english_...
 5. Mid-conversation language switch . test_mid_conversation_switching
 6. Budget/location retention ........ test_requirements_retained_..., test_number_word_budget
 7. No repeated qualification questions test_context_lists_known_..., test_extract_never_overwrites
 8. One follow-up question at a time . test_enforce_single_question_... (x3),
                                        test_respond_..., test_..._second_question
 9. Uncertain/casual customers ....... test_prompt_carries_... (no-pressure rules)
10. Explicit lead details ............ test_lead_data_contains_only_...,
                                        test_no_contact_details_means_no_lead
11. No fabricated properties ......... test_cards_come_only_from_real_search
12. Safe lead create/update/dedup .... test_upsert_lead_from_ai_deduplicates_...
13. Voice transcription/interruption . test_transcribe_language_* (+ voice TTS).
   Frontend interruption/duplicate-send behaviour is React-only (no browser
   test runner in this repo) - guarded in ChatPage.jsx and documented in the
   completion report instead.
14. Provider failure fallbacks ....... test_failed_tamil_turn_never_leaks_english,
                                        test_tanglish_net_still_appends_...
15. Existing auth/CRM/search/conversation tests - the full suite (unchanged,
    must stay green).
"""

import pytest

import app.ai.agent as agent_module
from app.ai.agent import AIRealEstateAgent


# ---------------------------------------------------------------- fixtures

@pytest.fixture
def agent_and_chat(monkeypatch):
    """Real agent with the provider call stubbed (records reply languages)."""
    calls = []

    def fake_chat_sync(
        system_prompt, user_message, conversation_history=None, language="auto"
    ):
        calls.append(language)
        canned = {
            "ta": "வணக்கம்! சொல்லுங்கள், எப்படி உதவி செய்யலாம்?",
            "ta-Latn": "Sollunga, eppadi help pannalaam?",
        }
        return canned.get(
            language, "Sure, I can help with that. What would you like to know?"
        )

    monkeypatch.setattr(agent_module.nvidia_client, "chat_sync", fake_chat_sync)
    return AIRealEstateAgent(), calls


def _last_assistant(agent):
    msgs = [m for m in agent.state.messages if m["role"] == "assistant"]
    assert msgs, "expected an assistant reply"
    return msgs[-1]["content"]


# ---------------------------------------- 1+9: prompt = style + active listening

def test_prompt_carries_active_listening_and_casual_style_guidance():
    """Mechanism test for requirements 1/9: the SYSTEM_PROMPT must carry the
    conversation contract (style references are style guidance, not
    hardcoded replies)."""
    prompt = AIRealEstateAgent.SYSTEM_PROMPT

    # active listening: acknowledge, answer first, one question, no re-asking
    assert "ACTIVE LISTENING" in prompt
    assert "Never ask for anything the CONTEXT block already shows" in prompt
    assert "at most ONE useful follow-up question" in prompt
    assert "no pressure, no pushing for phone numbers" in prompt

    # casual Tamil/Tanglish style targets (not scripts to copy)
    assert "Style references (NOT scripts to copy)" in prompt
    assert "Aama, kandippa!" in prompt
    assert "friendly contemporary" in prompt

    # natural lead capture with consent + honesty
    assert "contact number share panna viruppama?" in prompt
    assert "never pretend to be a human agent" in prompt
    assert "Never say a viewing is booked" in prompt
    assert "invent or assume them" in prompt

    # customer-facing response quality
    assert "Plain text only: no Markdown" in prompt
    assert "Never repeat the whole conversation back" in prompt
    assert "1-3 sentences before your single follow-up question" in prompt
    assert "distinguish a buying price from a rental price" in prompt
    assert "don't open every message with a greeting" in prompt
    # no fabricated search success (measured live: "I found a few
    # properties..." said with zero cards attached)
    assert "If NO cards are attached, never claim you found properties" in prompt

    # pre-existing pins (phase 10) must survive the prompt changes
    assert "NEVER invent or hallucinate property information" in prompt
    assert "Never make up details about properties, locations, or prices" in prompt


# ------------------------------------------------- 2: Tamil-script conversation

def test_tamil_script_message_routes_to_tamil(agent_and_chat):
    agent, calls = agent_and_chat
    lang, _ = agent.detect_language_and_style("தமிழ்ல பேசுங்க.")
    assert lang == "ta"
    assert AIRealEstateAgent.detect_language_request("தமிழ்ல பேசுங்க.") == "ta"
    agent.respond("தமிழ்ல பேசுங்க.")
    assert calls == ["ta"]
    assert agent.state.reply_language == "ta"


# ------------------------------------------ 3: Tanglish (the reproduced defect)

TANGLISH_PHRASES = [
    "Buy panna poren.",
    "Enakku puriyala.",
    "Summa properties pathi therinjukka vandhen.",
    "Marina pakkathula irundha nalla irukkum.",
    "Konjam simple-ah explain pannunga.",
    "Innum simple-ah sollunga.",
    "Rent-ku venum.",
    "5 lakh AED kulla venum.",
    "Enakku endha area nalla irukkum-nu theriyala.",
]


@pytest.mark.parametrize("message", TANGLISH_PHRASES)
def test_tanglish_phrases_classify_tanglish_not_english(message):
    """Reproduced root cause: English-script Tanglish used to fall through
    to English, so the model - following its reply-language directive -
    answered in English ("English-only Tamil response problem")."""
    lang, _ = AIRealEstateAgent().detect_language_and_style(message)
    assert lang in ("ta-Latn", "ta", "mixed"), f"{message!r} classified {lang!r}"


def test_tanglish_customer_message_gets_tanglish_reply_language(agent_and_chat):
    agent, calls = agent_and_chat
    agent.respond("Buy panna poren.")
    assert calls == ["ta-Latn"]


# ------------------------------------------------------ 4: English conversation

@pytest.mark.parametrize(
    "message",
    [
        "Show me apartments in Dubai Marina",
        "What is the price of this villa?",
        "Budget five lakh AED.",  # Indian-English budget phrasing stays English
    ],
)
def test_english_messages_stay_english(message):
    lang, _ = AIRealEstateAgent().detect_language_and_style(message)
    assert lang == "en"
    assert AIRealEstateAgent.detect_language_request(message) is None


def test_english_requested_within_tanglish_message_wins(agent_and_chat):
    """"English la explain pannunga." contains the Tanglish marker
    "pannunga" - the explicit request for English must still win."""
    agent, calls = agent_and_chat
    assert AIRealEstateAgent.detect_language_request(
        "English la explain pannunga.") == "en"
    agent.respond("English la explain pannunga.")
    assert calls == ["en"]


# ------------------------------------------- 5: mid-conversation language switch

def test_mid_conversation_switching(agent_and_chat):
    agent, calls = agent_and_chat
    agent.respond("Buy panna poren.")        # Tanglish
    agent.respond("is parking included?")    # plain English
    agent.respond("விலை எவ்வளவு?")           # Tamil script
    assert calls == ["ta-Latn", "en", "ta"]


# ------------------------------- 6+7: retention, no repeated qualification asks

def test_requirements_retained_across_messages(agent_and_chat):
    """Budget AED 800k + Dubai Marina + apartment stated first; the later
    2-bedroom message must ADD beds without clobbering - the agent never
    re-asks what it already knows."""
    agent, _ = agent_and_chat
    agent.respond("En budget 8 lakh AED. Dubai Marina pakkathula apartment venum.")
    assert agent.state.requirements["budget"] == 800000
    assert agent.state.requirements["location"] == "Dubai Marina"
    assert agent.state.requirements["property_type"] == "apartment"

    agent.respond("2 bedroom irundha nalla irukkum.")
    assert agent.state.requirements["bedrooms"] == 2
    assert agent.state.requirements["budget"] == 800000
    assert agent.state.requirements["location"] == "Dubai Marina"


def test_number_word_budget_is_captured(agent_and_chat):
    """"Budget five lakh AED." (number word) must parse to 500,000 - the
    task's own section-6 example."""
    agent, _ = agent_and_chat
    agent.respond("Budget five lakh AED.")
    assert agent.state.requirements["budget"] == 500000


def test_extract_never_overwrites_already_known_answers(agent_and_chat):
    agent, _ = agent_and_chat
    agent._extract_requirements("budget 2 million")
    agent._extract_requirements("budget 9 million")  # later mention must not clobber
    assert agent.state.requirements["budget"] == 2000000


def test_context_block_lists_known_requirements():
    agent = AIRealEstateAgent()
    agent.state.reply_language = "en"
    agent.state.requirements = {
        "buy_rent": "buy",
        "location": "Dubai Marina",
        "budget": 800000.0,
        "bedrooms": 2,
    }
    ctx = agent._context_block()
    assert "Requirements gathered so far:" in ctx
    assert "- looking to: buy" in ctx
    assert "- location: Dubai Marina" in ctx
    assert "- budget: 800000" in ctx
    assert "- bedrooms: 2" in ctx
    # the prompt tells the model not to re-ask what this block shows
    assert "Never ask for anything the CONTEXT block already shows" in (
        AIRealEstateAgent.SYSTEM_PROMPT
    )


# ------------------------------------------------- 8: one question at a time

def test_enforce_single_question_fast_path_unchanged():
    single = "Seri! Budget evlo?"
    assert AIRealEstateAgent._enforce_single_question(single) == single


def test_enforce_single_question_trims_later_questions_keeps_statements():
    E = AIRealEstateAgent._enforce_single_question
    two = "I found 3 options! Which area do you prefer? Do you want more details?"
    assert E(two) == "I found 3 options! Which area do you prefer?"

    three = "Aama, puriyudhu.\n\nWhat's your budget? Which area? Tell me the timeline."
    out = E(three)
    assert out.count("?") == 1
    assert "Which area" not in out
    assert "What's your budget?" in out      # first question kept
    assert out.endswith("timeline.")         # statement kept


def test_enforce_single_question_preserves_newlines():
    t = "Puriyudhu. 5 lakh budget-a?\nOkay then.\nVehicle venaa?"
    assert AIRealEstateAgent._enforce_single_question(t) == (
        "Puriyudhu. 5 lakh budget-a?\nOkay then."
    )


# ----------------------------------- plain-text guarantee: no Markdown leaks

def test_strip_markdown_unwraps_bold_code_headings_bullets():
    S = AIRealEstateAgent._strip_markdown
    assert S("I found **3 options** in Marina.") == "I found 3 options in Marina."
    assert S("Plan:\n1. **Search results**: check the cards") == (
        "Plan:\n1. Search results: check the cards"
    )
    assert S("`property_id` stays internal") == "property_id stays internal"
    assert S("### Heading\n- bullet line") == "Heading\nbullet line"
    # mid-line dashes are prose, not bullets - untouched
    assert S("AED 1.38 million - great value") == "AED 1.38 million - great value"


def test_respond_strips_markdown_from_provider_reply(monkeypatch):
    def fake(system_prompt, user_message, conversation_history=None, language="auto"):
        return "Your options: **apartment** or **villa** in Dubai. Which type fits?"

    monkeypatch.setattr(agent_module.nvidia_client, "chat_sync", fake)
    agent = AIRealEstateAgent()
    agent.respond("show me options")
    reply = _last_assistant(agent)
    assert "**" not in reply
    assert "apartment" in reply and "villa" in reply
    assert reply.count("?") == 1


def test_zero_match_search_tells_model_to_report_honestly(monkeypatch):
    """The search runs (requirements complete) but matches nothing: the model
    must be told NO matches so it cannot claim a success it can't show
    (measured live: an English "I found a few properties..." with zero cards)."""
    captured = {}

    def fake(system_prompt, user_message, conversation_history=None, language="auto"):
        captured["user"] = user_message
        return "Nothing matches those criteria right now - want a higher budget?"

    monkeypatch.setattr(agent_module.nvidia_client, "chat_sync", fake)
    agent = AIRealEstateAgent()
    result = agent.respond(
        "I want an apartment in nowhereville zzz with budget 500000"
    )
    assert result["properties"] == []            # nothing invented
    assert "NO matches" in captured["user"]      # the model is told the truth


def test_cards_attached_suppresses_the_no_match_note(monkeypatch):
    """When cards ARE attached the announcement note - not the no-match note -
    must be what the model receives."""
    captured = {}

    def fake(system_prompt, user_message, conversation_history=None, language="auto"):
        captured["user"] = user_message
        return "I found a few options. Which one do you prefer?"

    monkeypatch.setattr(agent_module.nvidia_client, "chat_sync", fake)
    agent = AIRealEstateAgent()
    agent.respond("hello")
    result = agent.respond("Dubai apartment, budget 10 million AED")
    assert result["properties"], "expected cards for this criteria"
    assert "fresh property cards attached" in captured["user"]
    assert "NO matches" not in captured["user"]


def test_respond_asks_exactly_one_question(monkeypatch):
    def fake(system_prompt, user_message, conversation_history=None, language="auto"):
        return "Which area do you prefer? What's your budget? How soon are you moving?"

    monkeypatch.setattr(agent_module.nvidia_client, "chat_sync", fake)
    agent = AIRealEstateAgent()
    agent.respond("I want to buy a property")
    reply = _last_assistant(agent)
    assert reply.count("?") == 1
    assert "Which area do you prefer?" in reply
    assert "budget?" not in reply and "moving?" not in reply


def test_tanglish_net_never_creates_second_question(monkeypatch):
    """An English reply with a question on a Tanglish turn gets NO appended
    question - the historical net could produce two."""
    def fake(system_prompt, user_message, conversation_history=None, language="auto"):
        return "Here are some options. Which one do you like?"

    monkeypatch.setattr(agent_module.nvidia_client, "chat_sync", fake)
    agent = AIRealEstateAgent()
    agent.respond("Buy panna poren.")       # Tanglish customer
    reply = _last_assistant(agent)
    assert reply == "Here are some options. Which one do you like?"
    assert reply.count("?") == 1


# --------------------------------- 14 (and 8): language-preserving safety nets

def test_tanglish_net_still_appends_when_reply_has_no_question(monkeypatch):
    """Provider answered an English statement to a Tanglish customer - the
    net still appends ONE Tanglish question (language preserved)."""
    def fake(system_prompt, user_message, conversation_history=None, language="auto"):
        return "I found several options that match your needs."

    monkeypatch.setattr(agent_module.nvidia_client, "chat_sync", fake)
    agent = AIRealEstateAgent()
    agent.respond("Buy panna poren.")
    reply = _last_assistant(agent)
    assert reply.count("?") == 1
    assert "Sollunga" in reply
    assert reply.rstrip().endswith("?")


def test_failed_tamil_turn_never_leaks_english(monkeypatch):
    """Provider failure text in English on a Tamil-script turn must be
    repaired into the deterministic Tamil reply (no English leak)."""
    def fake(system_prompt, user_message, conversation_history=None, language="auto"):
        return "I am sorry, I could not find any properties right now."

    monkeypatch.setattr(agent_module.nvidia_client, "chat_sync", fake)
    agent = AIRealEstateAgent()
    agent.respond("தமிழ்ல பேசுங்க.")
    reply = _last_assistant(agent)
    assert AIRealEstateAgent._tamil_script_count(reply) >= 10
    assert reply.count("?") <= 1


# ------------------------------------------------- 10: lead details extraction

def test_lead_data_contains_only_explicitly_stated_details(agent_and_chat):
    agent, _ = agent_and_chat
    agent.respond(
        "My name is Ravi Kumar, budget 8 lakh. "
        "Call me at +971501234567 or ravi@example.com"
    )
    data = agent.get_lead_data()
    assert data["name"] == "Ravi Kumar"
    assert data["phone"] == "+971501234567"
    assert data["email"] == "ravi@example.com"
    assert data["budget"] == "AED 800,000"
    # nothing fabricated: details the customer never mentioned stay None
    assert data["bathrooms"] is None


def test_no_contact_details_means_no_lead(agent_and_chat):
    agent, _ = agent_and_chat
    agent.respond("Dubai Marina apartment, budget 8 lakh, 2 bedroom")
    assert agent.state.requirements["budget"] == 800000
    assert agent._should_collect_lead() is False     # requirements alone: no lead

    agent.respond("you can reach me at ravi@example.com")
    assert agent._should_collect_lead() is True      # stated contact: actionable


# ----------------------------------------- 11: cards come from real search only

def test_cards_come_only_from_real_search(monkeypatch):
    from app.services.property_search import get_property_by_id

    def fake(system_prompt, user_message, conversation_history=None, language="auto"):
        return "I found a few options that match. Which one should we discuss?"

    monkeypatch.setattr(agent_module.nvidia_client, "chat_sync", fake)
    agent = AIRealEstateAgent()
    agent.respond("hello")
    result = agent.respond("Dubai apartment, budget 10 million AED")
    assert result["properties"], "expected the deterministic search to attach cards"
    for card in result["properties"]:
        row = get_property_by_id(card["property_id"])
        assert row is not None, f"card {card['property_id']} not in the dataset"
        # cards are verbatim dataset rows - nothing invented
        assert row["price"] == card["price"]
        assert row["location"] == card["location"]


# --------------------------------------------- 12: safe lead create/update/dedup

def test_upsert_lead_from_ai_deduplicates_and_merges(db):
    from app.database import Lead
    from app.services.leads import upsert_lead_from_ai

    phone = "+971507770011"
    lead1, created1 = upsert_lead_from_ai(
        db, {"phone": phone, "name": "Ravi Kumar", "location": "Dubai Marina"}
    )
    lead2, created2 = upsert_lead_from_ai(
        db, {"phone": phone, "budget": "AED 800,000"}
    )
    db.commit()
    assert created1 is True
    assert created2 is False            # same customer -> reused, not duplicated
    assert lead1.id == lead2.id
    assert db.query(Lead).filter(Lead.phone == lead1.phone).count() == 1
    assert lead2.name == "Ravi Kumar"   # merge keeps earlier stated fields
    assert lead2.budget == "AED 800,000"
    assert lead2.location == "Dubai Marina"


# --------------------------------------------------- 13: voice language wiring

def test_transcribe_accepts_language_as_form_field(client, monkeypatch):
    """The client sends `language` as a multipart field; the query-only
    declaration used to drop it so the Whisper hint never arrived."""
    import app.services.voice as voice_mod

    seen = {}

    async def fake_transcribe(audio_bytes, filename="audio.webm", language=None):
        seen["language"] = language
        return {"text": "vanakkam", "language": language}

    monkeypatch.setattr(voice_mod, "transcribe_audio", fake_transcribe)
    r = client.post(
        "/api/voice/transcribe",
        files={"file": ("clip.webm", b"RIFFdata", "audio/webm")},
        data={"language": "ta"},
    )
    assert r.status_code == 200, r.text
    assert seen["language"] == "ta"


def test_transcribe_still_accepts_language_as_query(client, monkeypatch):
    import app.services.voice as voice_mod

    seen = {}

    async def fake_transcribe(audio_bytes, filename="audio.webm", language=None):
        seen["language"] = language
        return {"text": "hello", "language": language}

    monkeypatch.setattr(voice_mod, "transcribe_audio", fake_transcribe)
    r = client.post(
        "/api/voice/transcribe",
        params={"language": "en"},
        files={"file": ("clip.webm", b"RIFFdata", "audio/webm")},
    )
    assert r.status_code == 200, r.text
    assert seen["language"] == "en"


def test_voice_respond_tts_language_mixed_maps_to_tamil(client, monkeypatch):
    """A mixed-script turn's spoken body is Tamil-dominant - TTS must get a
    real language hint instead of the unsupported "mixed" code."""
    import app.main as main_mod
    import app.services.voice as voice_mod

    def fake_chat(request, db=None, http_request=None, response=None):
        return {
            "response": "Vanga, paakalam.",
            "action": "continue",
            "detected_language": "mixed",
        }

    seen = {}

    async def fake_tts(text, voice=None, language=None):
        seen["language"] = language
        return b"RIFF"

    monkeypatch.setattr(main_mod, "chat", fake_chat)
    monkeypatch.setattr(voice_mod, "synthesize_speech", fake_tts)
    r = client.post(
        "/api/voice/respond", json={"message": "வணக்கம்", "speak": True}
    )
    assert r.status_code == 200, r.text
    assert r.json()["audio_base64"]
    assert seen["language"] == "ta"


# ---------------------------- cold-start persistence: standing Tamil survives

def test_cold_restart_restores_standing_tamil_request(client, monkeypatch):
    """Replay used to restore messages + requirements but NOT the standing
    language request - after a server restart the Tamil conversation
    silently fell back to English."""
    import app.main as main_mod

    calls = []

    def fake_chat_sync(system_prompt, user_message, history=None, language="auto"):
        calls.append(language)
        return "Okay, I can help with that."

    monkeypatch.setattr(agent_module.nvidia_client, "chat_sync", fake_chat_sync)
    main_mod.agents.clear()
    try:
        r1 = client.post("/api/chat", json={"message": "Could you talk in Tamil?"})
        assert r1.status_code == 200, r1.text
        conv_id = r1.json()["conversation_id"]
        assert calls[-1] == "ta"                # request honoured live

        main_mod.agents.clear()                 # simulate a server restart
        n = len(calls)
        r2 = client.post(
            "/api/chat",
            json={"message": "sure, go ahead", "conversation_id": conv_id},
        )
        assert r2.status_code == 200, r2.text
        assert len(calls) == n + 1              # really went to the provider
        assert calls[-1] == "ta"                # ...still in Tamil after restart
    finally:
        main_mod.agents.clear()


# ============================================================ LIVE model tests
# Real NVIDIA API - no stubs. Skipped unless RUN_LIVE_TESTS=1 (conftest).

@pytest.mark.live
def test_live_tamil_tanglish_conversation_quality():
    """Actual model evaluation: natural Tamil/Tanglish replies, at most one
    question each, no Markdown or self-talk leaks, language switches honoured.
    Replies are printed for human review."""
    agent = AIRealEstateAgent()
    replies = []

    agent.respond("Hi, could you talk in Tamil?")
    replies.append(_last_assistant(agent))

    agent.respond("Enakku Dubai la oru apartment venum.")
    replies.append(_last_assistant(agent))

    agent.respond("5 lakh AED kulla venum, Marina pakkathula.")
    replies.append(_last_assistant(agent))

    agent.respond("Reply in English: what are my next steps?")
    replies.append(_last_assistant(agent))

    print("\n=== LIVE TURN SAMPLES ===")
    for i, r in enumerate(replies, 1):
        print(f"{i}. {r}\n")

    # 1) explicit Tamil request -> Tamil script
    assert AIRealEstateAgent._tamil_script_count(replies[0]) >= 10
    # 1-3) Tamil/Tanglish turns answered in their language (not English)
    for r in replies[:3]:
        lang, _ = agent.detect_language_and_style(r)
        assert lang in ("ta-Latn", "ta", "mixed"), f"reply classified {lang!r}: {r}"
        # ...and no plain-English paragraph smuggled into the reply
        # (measured live: the card announcement drifted into English).
        for para in r.split("\n\n"):
            para = para.strip()
            if len(para.split()) >= 8:
                plang, _ = agent.detect_language_and_style(para)
                assert plang != "en", f"English paragraph in a non-English turn: {para}"
    # 4) explicit English request -> English
    lang4, _ = agent.detect_language_and_style(replies[3])
    assert lang4 == "en", f"expected English, got {lang4!r}: {replies[3]}"

    for r in replies:
        assert r.count("?") <= 1, f"more than one question: {r}"
        assert "**" not in r and "```" not in r, f"markdown leak: {r}"
        low = r.lower()
        assert "thinking process" not in low and "the prompt says" not in low, (
            f"self-talk leak: {r}"
        )
