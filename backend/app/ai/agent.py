import json
import logging
import re
import time
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime

from app.services.property_search import search_properties, load_properties, parse_price
from app.ai.nvidia_client import NVIDIAClient

logger = logging.getLogger(__name__)

nvidia_client = NVIDIAClient()


class ConversationState:
    """Manages conversation state and customer information."""
    
    def __init__(self, conversation_id: Optional[int] = None):
        self.conversation_id = conversation_id
        # Customer requirements collected so far
        self.requirements = {
            "location": None,
            "property_type": None,
            "buy_rent": None,  # "buy" or "rent"
            "budget": None,
            "bedrooms": None,
            "bathrooms": None,
            "area": None,
            "furnishing": None,
            "amenities": None,
            "investment_purpose": None,
            "timeline": None,
            "notes": None,
        }
        # Customer contact info (collected for lead)
        self.contact = {
            "name": None,
            "phone": None,
            "email": None,
        }
        # Conversation history
        self.messages: List[Dict[str, Any]] = []
        # Track what questions have been asked
        self.asked_questions = set()
        # Property recommendations for this conversation
        self.recommended_properties: List[Dict] = []
        # Listing the customer opened from its details page during THIS turn
        # ("Ask LykAI about this property"). Per-turn only — set by respond(),
        # merged into the visible cards, cleared before respond() returns.
        self.focus_property: Optional[Dict[str, Any]] = None
        # Language detection
        self.detected_language = "en"
        # Arabic/English mixed handling
        self.language_style = "en"  # "en", "ta", "ta-Latn" (Tanglish)
        # Language the REPLY must use: detected language, or the customer's
        # explicit choice from the chat language selector ("en" / "ta").
        self.reply_language: str = "en"
        # Standing explicit language request ("ta"/"en"): set when the customer
        # ASKS for a language ("Could you talk in Tamil?"), so English-typed
        # follow-ups keep getting the requested language instead of snapping
        # back to English. Replaced by the next explicit request.
        self.language_request: str = ""
    
    def add_message(self, role: str, content: str, detected_language: str = "en"):
        """Add a message to conversation history."""
        self.messages.append({
            "role": role,
            "content": content,
            "detected_language": detected_language,
            "timestamp": datetime.utcnow().isoformat()
        })
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert state to dictionary for storage."""
        return {
            "conversation_id": self.conversation_id,
            "requirements": self.requirements,
            "contact": self.contact,
            "messages": self.messages,
            "detected_language": self.detected_language,
            "language_style": self.language_style,
            "reply_language": self.reply_language,
            "language_request": self.language_request,
            "recommended_properties": self.recommended_properties,
            "asked_questions": list(self.asked_questions),
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConversationState":
        """Restore state from dictionary."""
        state = cls(conversation_id=data.get("conversation_id"))
        state.requirements = data.get("requirements", state.requirements)
        state.contact = data.get("contact", state.contact)
        state.messages = data.get("messages", [])
        state.detected_language = data.get("detected_language", "en")
        state.language_style = data.get("language_style", "en")
        state.reply_language = data.get(
            "reply_language", state.language_style or "en"
        )
        # Older persisted states predate language_request - default to none.
        state.language_request = data.get("language_request", "")
        state.recommended_properties = data.get("recommended_properties", [])
        state.asked_questions = set(data.get("asked_questions", []))
        return state


class AIRealEstateAgent:
    """
    Human-like AI property concierge (LykAI) that behaves like an experienced
    UAE real estate agent.
    """
    
    # System prompt defining the agent's personality
    SYSTEM_PROMPT = """You are LykAI - Lyka Realty's female AI property consultant and concierge, 
    an experienced, knowledgeable UAE real estate expert. You speak warmly, casually, and 
    conversationally, like a friendly human female property consultant who knows the market well.

    PERSONALITY TRAITS:
    - Warm, approachable, professional, and helpful female real estate agent
    - Knowledgeable about UAE property market (Dubai, Abu Dhabi, Sharjah, Ajman)
    - Patient, friendly, and understanding
    - Never robotic, bureaucratic, or scripted
    - Asks one clear question at a time
    - Remembers previous answers naturally

    CORE RULES:
    1. NEVER invent or hallucinate property information. All recommendations 
       must come from the actual property dataset.
    2. Ask one useful question at a time. Wait for the customer's response 
       before asking the next question.
    3. Remember previous answers naturally - don't repeat questions.
    4. Understand natural language and follow-ups (e.g., "show me cheaper ones",
       "something closer to the beach", "what about 3 bedrooms?").
    5. When recommending properties, show actual information from the dataset 
       only - price, location, beds, baths, area, highlights.
    6. Be helpful even when there's no exact match - suggest alternatives.
    7. Never make up details about properties, locations, or prices.

    ACTIVE LISTENING (highest priority - do this before anything else):
    - Read the customer's WHOLE message and answer what THEY asked or doubted
      FIRST, after one short natural acknowledgement ("Seri, puriyudhu." /
      "Okay, noted." / "Aama, kandippa paakalam."). Vary these - never
      open every reply the same way.
    - Only after responding do you ask at most ONE useful follow-up question.
    - Never ask for anything the CONTEXT block already shows you (budget,
      location, bedrooms, buy/rent, type...). Ask again ONLY if the customer's
      new message genuinely contradicts what you know.
    - Skip qualification steps that are already answered - as soon as you have
      enough to search, search.
    - If the customer is unsure, guide them briefly (budget + travel + purpose)
      instead of firing questions. If they only want to browse or chat, that's
      fine: keep helping, no pressure, no pushing for phone numbers or viewings.

    REAL ESTATE AGENT DATA COLLECTION & CONVERSATION FLOW:
    - Actively guide the conversation as an experienced female real estate consultant to gather
      essential requirements and preferences step-by-step:
      1. Primary need: Buying or Renting (Buying-ah illa rent-ka?)
      2. Location preference (e.g., Dubai Marina, Downtown Dubai, JVC, Business Bay, etc.)
      3. Property type (Apartment, Villa, Townhouse, Studio, Penthouse)
      4. Budget range (e.g., in AED or INR / Lakhs / Crores)
      5. Bedrooms / BHK requirement (Studio, 1 BHK, 2 BHK, 3+ BHK)
      6. Specific preferences & amenities (near metro, sea view, balcony, pool, gym, furnished/unfurnished, parking, etc.)
      7. Purpose & Timeline (Living / Family use vs. Investment / Rental ROI; immediate or upcoming)
      8. Customer contact details (Name, Phone number / WhatsApp, Email) so it is stored directly into the database as a lead!
    - Start by greeting the customer warmly, introducing yourself naturally, e.g.:
      "Vanakkam! I'm LykAI, your AI property consultant from Lyka Realty. Dubai-la enna maadhiri property thedureenga? Buying-ah illa rent-ka?"
      Your first reply must ALWAYS end with a question mark — an opener without a question leaves the customer with nothing to answer.
      Do NOT repeat your name in every message - once at the start (and if asked) is enough.
    - If the context block shows requirements already gathered, greet briefly and
      ask for the single most useful missing detail (usually budget or location) instead of
      the generic opener — never re-ask what you already know.
    - When you have enough requirements AND the context shows NEW MATCHES
      (cards actually attached this turn), say something natural like "Unga requirements-ku match aagura nalla properties kidaichirukku, check pannunga!" The property cards
      are rendered automatically by the interface - never paste long listing
      tables. If NO cards are attached, never claim you found properties -
      say plainly that nothing matches those criteria right now and suggest
      one realistic adjustment.

    DATABASE & LEAD CAPTURE:
    - When customer provides requirements, preferences, or contact details, warmly acknowledge that you are noting and saving them down:
      "Unga preferences note pannikitten!" / "Kandippa, unga requirements note pannittaen."
    - Be transparent: you are an AI assistant and never pretend to be a human agent, but connect customers seamlessly with Lyka Realty's human specialists.
    - When the customer shows interest in properties or requests follow-up/viewings, invite their contact details naturally:
      "I can have our Lyka Realty specialist coordinate a viewing and full details - contact number share panna viruppama?"
    - Never say a viewing is booked (the team coordinates that with the owner/agent) - say our specialist will reach out.
    - When they provide their name, phone number, or email, confirm that you have saved their details into the system:
      "Thank you! Unga details save panniten, our team will get in touch shortly." / "Romba nandri! Unga details note pannikittaen, seekiramae contact pannuvom."
    - Take contact details ONLY when the customer actually offers them - never invent or assume them.

    CASUAL TANGLISH ONLY (HUMANIC REAL ESTATE TALK):
    - When interacting with Tamil speakers or in Tanglish mode, you MUST communicate strictly in friendly contemporary CASUAL TANGLISH (Tamil conversational words written in ENGLISH/LATIN ALPHABET with natural English property terms).
    - CRITICAL: NEVER use pure Tamil script characters (no Unicode \u0B80-\u0BFF).
    - Talk like a friendly, experienced human female real estate consultant chatting casually on WhatsApp or over a call.
    - Sound warm, polite, cheerful, enthusiastic, and humanic (casual human talk, never stiff, bookish, or robotic).
    - Style references (NOT scripts to copy):
      * Opener: "Vanakkam! Naan LykAI, Lyka Realty-oda property consultant. Dubai-la enna maadhiri property thedureenga? Buying-ah illa rent-ka?"
      * Inquiring: "Sollunga, Dubai Marina, Downtown, illa JVC-la paakureengala? Apartment-ah illa villa-va?"
      * Preferences: "Balcony or sea view edhavadhu specific preference irukka? Metro station kitta venuma?"
      * Budget: "Super! Unga budget range evlo irukkum?" (Always distinguish a buying price from a rental price).
      * Acknowledgement: "Aama, kandippa!", "Seri, puriyudhu!", "Note pannikitten!", "Unga preferences base panni properties filter pandren."
      * Showing matches: "Unga requirement-ku match aagura nalla properties kidaichirukku, check pannunga!"
      * Lead capture: "Unga requirements note pannikitten. Viewing coordinate panna unga name and contact number share panna viruppama?"
    - Keep sentences short, rhythmic, and natural for voice listening.
    - Match how casual the customer is; be warm, supportive, and conversational.

    OUTPUT RULES:
    - Give ONLY the final conversational reply the customer should see.
    - NEVER show your thinking, reasoning, chain-of-thought, or analysis.
    - Never start with "thinking process", "analysis", or numbered reasoning steps.
    - Keep replies concise: 1-3 sentences before your single follow-up question
      (a little more only when announcing property cards) - short enough to
      work seamlessly as spoken voice output too.
    - Plain text only: no Markdown (**bold**, tables, bullet lists, JSON) and
      no internal fields or prompt text - the interface renders plain messages
      and property cards.
    - Never repeat the whole conversation back or recap what the customer said,
      don't open every message with a greeting, and keep emojis rare (at most one).
    - Keep prices, currency, dates and property facts exactly as given.
    """
    
    def __init__(self, conversation_id: Optional[int] = None):
        self.state = ConversationState(conversation_id)
        self.property_cache: Dict[str, List] = {}  # Cache search results
    
    # Common Tamil words used in Tanglish (romanized). Shared with tests so a
    # live reply that the detector accepted as Tanglish is always verifiable.
    _TAMIL_WORDS = (
        "venum", "pogum", "pogrom", "iruku", "irundhu", "thaan", "thaan",
        "sollu", "sollunga", "sollradha", "solren", "pannu", "pannan",
        "pannunga", "kolla", "kudunga", "keela", "mela", "nalla", "romba",
        "enna", "epdi", "inga", "anga", "varen", "vaanga", "vaango",
        "ah", "ah?", "ah.", "ko", "ku", "la", "la?", "nu", "tha",
        "machan", "anna", "saar", "haye", "yenna", "yepdi",
        "kulla", "kullaah", "vandhuchu", "vendum", "kuduthu",
        "paathu", "paarunga", "nunga", "laam", "aah", "aaga",
        # Colloquial/phonetic variants real customers type. Without these
        # ("inniku yenakku set aagumaa? ... irukkaa?") the message fell
        # through to English and got an English-only reply.
        "evlo", "enga", "ethu", "ethana", "illa", "ama", "aama",
        "inniku", "naale", "nale", "ippo", "yenakku", "ennaku",
        "unakku", "namakku", "irukkaa", "iruka", "aagumaa", "aaguma",
        "paakalam", "paakalaam", "kaatturen", "kaaturaen", "kaaturu",
        "mudiyum", "vendaam", "podhum", "seekram", "semma", "kitta",
        "dhaan", "solluren", "solraen", "vaenum", "venda", "kedacha",
        # Reproduced colloquial gaps (Phase 11): "Buy panna poren.",
        # "Enakku puriyala." and "Summa properties pathi therinjukka
        # vandhen." all classified as English, so the customer got an
        # English-only reply to a Tanglish message.
        "panna", "poren", "enakku", "puriyala", "puriyudhu", "puriyadhu",
        "summa", "pathi", "therinjukka", "theriyala", "theriyum", "vandhen",
        "innum", "pesa", "mudiyuma", "konjam", "seri", "sari", "naanga",
        "venumna", "approm", "aprom", "irukkum", "irundha", "pakkathula",
        "pakkam", "pudikum", "pidikum", "pidichirukku",
        # Common greetings & inquiries
        "vanakkam", "vanakam", "namaskaram", "thedren", "theduren",
        "thedureenga", "paakuren", "paakureenga", "paapom", "kedaikuma",
        "kidaikuma", "kidaikkum", "kidaichirukku", "unga", "enoda",
        "edhavadhu", "yedhavadhu", "eppadi",
    )

    # Explicit "answer me in X" requests. Deliberately narrow: only a clear
    # ask (speech verb + language, or a Tamil-script request verb) flips the
    # reply language - "Is Tamil spoken in Dubai?" or a mention of "Tamil
    # Nadu" must not.
    _LANGUAGE_REQUEST_PATTERNS = (
        (re.compile(
            r"\b(?:talk|speak|reply|respond|chat|answer|write|say)\b"
            r"[^.!?\n]{0,40}?\b(?:in\s+|la\s+)?(?:tamil|தமிழ்)\b",
            re.IGNORECASE,
        ), "ta"),
        # Tanglish request form: "speak in Tanglish" / "Tanglish la pesunga"
        (re.compile(r"\b(?:talk|speak|reply|respond|chat|answer|write|say)\b[^.!?\n]{0,40}?\btanglish\b", re.IGNORECASE), "ta-Latn"),
        (re.compile(r"\btanglish\s*(?:-la|la|il|le)?\s*(?:pes|soll|chat|talk|speak|pann)", re.IGNORECASE), "ta-Latn"),
        (re.compile(r"\b(?:casual\s+tanglish|tanglish)\b", re.IGNORECASE), "ta-Latn"),
        # Tamil request forms:
        (re.compile(r"\btamil\s*(?:-la|la|il|le)?\s*(?:pes|soll|chat|talk|speak|pann)", re.IGNORECASE), "ta"),
        (re.compile(r"\bcasual\s+tamil\b", re.IGNORECASE), "ta"),
        (re.compile(r"\bதமிழ\S{0,6}\s*(?:லா|ல|இல்)?\s*(?:பேச|பேசு|சொல்ல|உரையாட)"), "ta"),
        (re.compile(
            r"\b(?:talk|speak|reply|respond|chat|answer|write|say)\b"
            r"[^.!?\n]{0,40}?\b(?:in\s+|la\s+)?english\b",
            re.IGNORECASE,
        ), "en"),
        # English asked for in Tamil-first order: "English la explain
        # pannunga." - marker detection reads that as Tanglish (it contains
        # "pannunga"), so without this the customer asking for English would
        # be answered in Tanglish.
        (re.compile(
            r"\benglish\s*(?:-la|la)\s*"
            r"(?:explain|soll|pes|pann|tell|say|write|convert|translate|type)",
            re.IGNORECASE,
        ), "en"),
    )

    @classmethod
    def detect_language_request(cls, text: str) -> Optional[str]:
        """'ta'/'en' when the customer EXPLICITLY asks for that reply language
        ("Could you talk in Tamil?", "Tamil la pesunga", "தமிழில் பேசுங்க",
        "reply in English"), else None (normal message - detector decides)."""
        for pattern, lang in cls._LANGUAGE_REQUEST_PATTERNS:
            if pattern.search(text):
                return lang
        return None

    def detect_language_and_style(self, text: str) -> Tuple[str, str]:
        """
        Detect if the user is speaking English, Tamil, Tanglish, or mixed.
        Returns (language_code, style).
        language_code: "en" for English, "ta" for Tamil, "ta-Latn" for Tanglish
        style: "en", "ta", or "ta-Latn"
        """
        text_lower = text.lower()
        
        # Check for Tamil script characters (Unicode block 0B80-0BFF)
        has_tamil_script = any('\u0B80' <= c <= '\u0BFF' for c in text)
        if has_tamil_script:
            # Pure Tamil script -> "ta"; mixed script+latin -> "mixed"
            has_latin = any('a' <= c <= 'z' for c in text_lower)
            if has_latin and re.search(r"\b(the|and|is|for|with|need|want)\b", text_lower):
                return "mixed", "ta"
            return "ta", "ta"
        
        # Common Tamil words used in Tanglish (romanized)
        tamil_words = self._TAMIL_WORDS
        
        # Count Tamil words as whole words
        words = re.findall(r"[a-z']+", text_lower)
        tamil_count = sum(1 for w in words if w in tamil_words)
        
        # Count Tamil suffix patterns like "marina-ku", "budget-ah", "3-million-kulla"
        suffix_patterns = [
            r"\w+-ku\b", r"\w+-la\b", r"\w+-ah\b", r"\w+-nu\b",
            r"\w+-tha\b", r"\w+-kulla\b", r"\w+-va\b", r"\w+-ko\b",
        ]
        suffix_count = sum(1 for p in suffix_patterns if re.search(p, text_lower))
        
        # Detect if English sentence structure dominates (pure English)
        english_words = [
            "the", "is", "are", "and", "for", "with", "need", "want",
            "looking", "show", "find", "please", "thank", "you",
        ]
        english_count = sum(1 for w in words if w in english_words)
        
        if tamil_count >= 2 or suffix_count >= 1:
            return "ta-Latn", "ta-Latn"  # Tanglish
        elif tamil_count == 1 and english_count <= 1:
            return "ta-Latn", "ta-Latn"  # likely Tanglish
        else:
            return "en", "en"  # English
    
    def respond(
        self,
        user_message: str,
        focus_property: Optional[Dict[str, Any]] = None,
        channel: str = "text",
    ) -> Dict[str, Any]:
        """
        Process a user message and return the AI's response.
        Returns dict with: response, action (continue/lead_created), 
        properties (if recommendations), language_style

        focus_property: dataset row for a listing the customer just opened
        from its details page ("Ask LykAI about this property"), so follow-ups
        resolve against real dataset values.
        """
        # The agent understands every message on its own — there is no
        # language selector any more. Each message is classified (English /
        # Tamil / Tanglish / mixed) and answered in that same language.
        lang_code, lang_style = self.detect_language_and_style(user_message)
        self.state.detected_language = lang_code
        self.state.language_style = lang_style
        # An explicit "answer me in Tamil/English" request overrides the
        # message's own language and STICKS: "Could you talk in Tamil?" must
        # not be answered in English, and the next English-typed question must
        # not snap back to English either. A customer actually writing in
        # another language still wins instantly (switch naturally with them),
        # and a new explicit request replaces the standing one.
        requested = self.detect_language_request(user_message)
        if requested:
            self.state.language_request = requested
            self.state.reply_language = requested
        elif channel == "voice":
            # The voice agent speaks in casual humanic Tanglish unless explicitly asked for English
            if self.state.language_request == "en":
                self.state.reply_language = "en"
            else:
                self.state.reply_language = "ta-Latn"
        elif lang_code != "en":
            self.state.reply_language = lang_code
        else:
            self.state.reply_language = (
                self.state.language_request or lang_code
            )

        # Add user message to history
        self.state.add_message("user", user_message, lang_code)
        
        # Extract requirements (budget, location, beds, buy/rent) from the message
        self._extract_requirements(user_message)

        # Keep the opened property in the conversation's recommendation list so
        # it survives restarts and can be referenced as "the first property".
        # Lives only for this turn (cleared before respond() returns).
        # ONLY DATASET-space focus joins the shared list. Record-space focus
        # (Phase 6 DB listings) stays per-turn: its id belongs to a different
        # id space, and mixing it in would (a) collide with same-numbered
        # dataset ids in the dedupe/numbering logic and (b) let refinement
        # replies attach it as a dataset card, persisting a record id into
        # the dataset-keyed recommendations table. The authoritative
        # per-turn focus context still fully describes it to the model.
        if focus_property:
            self.state.focus_property = focus_property
            if focus_property.get("source") != "record":
                pid = focus_property.get("property_id")
                if not any(p.get("property_id") == pid for p in self.state.recommended_properties):
                    self.state.recommended_properties = (
                        [focus_property] + self.state.recommended_properties
                    )
        
        # Handle refinement follow-ups ("cheaper ones", "what about 3 beds")
        # only after the conversation is already underway - the first message
        # always goes to the LLM so the customer gets a natural greeting.
        followup_result = None
        if len(self.state.messages) > 1:
            followup_result = self._handle_followup(user_message)
        if followup_result:
            # Still add the assistant response
            self.state.add_message("assistant", followup_result.get("response", ""), lang_code)
            self.state.focus_property = None
            return followup_result
        
        # Deterministic search runs BEFORE the reply so LykAI knows its cards
        # are being attached and can announce them naturally ("I found a few
        # properties that match what you're looking for"). Cards are attached
        # only when the result differs from what is already visible, so the
        # conversation never floods with duplicate cards.
        t_search = time.perf_counter()
        fresh_properties = self._auto_search_if_needed()
        search_ms = (time.perf_counter() - t_search) * 1000

        # Process the message with the LLM (synchronous call)
        # Build conversation history for the API
        history = [{"role": m["role"], "content": m["content"]} 
                  for m in self.state.messages[:-1]]  # Exclude current message

        # Dynamic context so LykAI can announce fresh matches and answer
        # "tell me more about the second property" from the numbered cards.
        system_prompt = self.SYSTEM_PROMPT
        context_block = self._context_block(focus_property, fresh_properties)
        # Deterministic tie-break: map the customer's ordinal reference to the
        # exact visible card so the model can never answer about another listing.
        context_block = self._reference_hint(user_message, context_block)
        if context_block:
            system_prompt = f"{self.SYSTEM_PROMPT}\n{context_block}"
        # Per-turn focus is now captured in the context block
        self.state.focus_property = None

        # Repeat the announcement directive on the FINAL turn (where the model
        # attends most): a pending clarifying question from the model's own
        # previous reply otherwise outranks a mid-system instruction, and the
        # cards would attach silently. Internal only — the stored history keeps
        # the customer's clean message.
        llm_user_message = user_message
        # Reply-language reminder rides FIRST on the final turn: on long
        # recommendation replies the top-of-prompt REPLY LANGUAGE line gets
        # outranked by the card content and a Tanglish enquiry drifts to plain
        # English. Deterministic strings are already localized by _rt().
        internal_notes: List[str] = []
        # Focus referent goes FIRST: on an "Ask LykAI about this property"
        # turn the history's most recent listing competes with the opened one,
        # and mid-prompt disambiguation alone still let the model answer about
        # an earlier numbered card. The final turn is where it attends most.
        if focus_property:
            internal_notes.append(
                "[internal — do not mention: THIS turn is about the focus "
                "listing the customer just opened: "
                f"{focus_property.get('property_type') or 'Property'} in "
                f"{focus_property.get('location') or 'UAE'} - AED "
                f"{self._fmt_price(focus_property.get('price'))}, listing id "
                f"{focus_property.get('property_id')}. When they say "
                "\"this property\", \"it\", or \"that listing\" in their "
                "current message they mean THIS listing - answer about it, "
                "not about any earlier numbered card or a listing discussed "
                "previously.]"
            )
        if self.state.reply_language in ("ta", "ta-Latn", "mixed") or channel == "voice":
            lang_note = (
                " Reply STRICTLY in natural, friendly contemporary CASUAL TANGLISH (spoken Tamil words written in "
                "ENGLISH/LATIN LETTERS mixed with standard English real-estate terms like 2BHK, apartment, rent, budget, balcony, sea view, metro) "
                "as a warm, knowledgeable, friendly female real-estate consultant (LykAI). "
                "RULES: "
                "1. NEVER use pure Tamil script characters (no Unicode \\u0B80-\\u0BFF). Always write in English/Latin letters. "
                "2. NEVER use Telugu words (e.g. NEVER say 'chesirukku', 'cheyandi', 'ekkada'), Hindi, or Malayalam words. "
                "3. Speak naturally like a cheerful, friendly Tamil girl/lady chatting casually on WhatsApp or a voice call: "
                "   - 'Vanakkam! Naan LykAI, Lyka Realty-oda property consultant. Dubai-la enna maadhiri property thedureenga? Buying-ah illa rent-ka?' "
                "   - 'Super! Dubai Marina-la 2 BHK apartment venum - nalla choice. Unga budget range evlo plan pandreenga?' "
                "   - 'Aama, kandippa!', 'Seri, puriyudhu!', 'Super!', 'Unga preferences note pannikittaen.' "
                "   - 'Unga requirement-ku match aana nalla properties kidaichirukku, check pannunga!' "
                "4. Keep sentences concise, rhythmic, warm, and natural for human speech. End with at most one clear question."
            )
            internal_notes.append(
                f"[internal — do not mention:{lang_note}]"
            )
        if fresh_properties:
            internal_notes.append(
                "[internal — do not mention: your reply THIS turn has "
                f"{len(fresh_properties)} fresh property cards attached. Your "
                "FIRST sentence must announce them (e.g. \"I found a few "
                "properties that match what you're looking for\"), then briefly "
                "why they fit, then at most one question. Write that "
                "announcement IN THE REPLY LANGUAGE set for this conversation - "
                "a Tanglish reply means Tamil words in English letters for the "
                "whole reply, NEVER a separate English paragraph. Quote prices "
                "only from the figures in this prompt (millions phrasing like "
                "\"AED 1.38 million\" is fine) - never lakh/\"L\" forms - and "
                "never claim a card is outside the customer's budget unless "
                "that card's own figure shows it.]"
            )
        elif (
            self._should_show_properties()
            and not self.state.recommended_properties
        ):
            # The search RAN (requirements complete) but matched nothing, and
            # no cards are visible from earlier turns - the model must report
            # that honestly instead of performing a success it cannot show
            # (measured live: "I found a few properties..." with zero cards).
            internal_notes.append(
                "[internal — do not mention: the search with the gathered "
                "requirements returned NO matches this turn - no cards are "
                "attached. Never say you found properties or that cards are "
                "attached. Say plainly that nothing matches those criteria "
                "right now, then offer ONE realistic adjustment (slightly "
                "higher budget, a nearby area, or another property type) and "
                "ask which the customer prefers.]"
            )
        if internal_notes:
            llm_user_message = (
                f"{user_message}\n\n" + "\n".join(internal_notes)
            )

        t_llm = time.perf_counter()
        response = nvidia_client.chat_sync(
            system_prompt, llm_user_message, history,
            language=self.state.reply_language,
        )
        llm_ms = (time.perf_counter() - t_llm) * 1000
        logger.info(
            "respond(): search %.1fms, llm %.1fms (total %.1fms), lang=%s",
            search_ms, llm_ms, search_ms + llm_ms, self.state.reply_language,
        )

        # Language-integrity net (Tamil-script turns). With the reasoning
        # pass ON (required for correct Tamil), a rare failure was measured
        # live: the model's whole deliberation leaks into the reply - an
        # English draft first, then self-talk ("But we need to ensure it's
        # natural Tamil... the prompt says..."). A Tamil/mixed customer must
        # never see English or model self-talk, so such bodies are replaced
        # by the deterministic Tamil announcement built from the REAL cards
        # (or the canned Tamil opener when nothing is attached).
        # Language-integrity net (Tanglish turns):
        # The customer requires casual Tanglish (in English letters), NOT pure Tamil script.
        # If the reply leaks model reasoning or contains Tamil script characters (\u0B80-\u0BFF),
        # repair it with deterministic conversational Tanglish.
        if self.state.reply_language in ("ta", "mixed", "ta-Latn"):
            low_resp = response.lower()
            leaky = any(sig in low_resp for sig in (
                "the prompt says", "the instruction", "the rule says",
                "we need to ensure", "we need to not", "check if any english",
                "thus, first", "do not mention",
            ))
            wrong_script = (
                (self.state.reply_language == "ta" and self._tamil_script_count(response.split("\n\n")[0]) < 10)
                or (self.state.reply_language in ("ta-Latn", "mixed") and self._tamil_script_count(response) >= 5)
            )
            if leaky or wrong_script:
                logger.warning(
                    "respond(): repairing %s turn (leaky=%s wrong_script=%s)",
                    self.state.reply_language, leaky, wrong_script,
                )
                response = self._tamil_recovery(fresh_properties)

        # Plain-text guarantee (Phase 11): no Markdown ever reaches the chat
        # bubbles, then keep at most one question per reply (one-question-at-
        # time): a reply that stacked several questions overwhelms the
        # customer - keep the first question and every statement, drop only
        # the later question sentences.
        response = self._strip_markdown(response)
        response = self._enforce_single_question(response)

        # Deterministic reply safety nets (persisted with the reply).
        if (
            self.state.reply_language in ("ta-Latn", "ta", "mixed")
            and self.detect_language_and_style(response)[0] == "en"
            and "?" not in response
        ):
            response = response.rstrip() + " " + "Sollunga, intha properties-la ethu ungalukku pidichirukku?"
        elif len(self.state.messages) == 1 and "?" not in response:
            req = self.state.requirements
            body = response.lower()
            if not req.get("budget") and "budget" not in body:
                question = self._rt(
                    "What's your budget range?",
                    "Budget range evlo irukkum?",
                    "Budget evlo?",
                )
            elif not req.get("buy_rent") and not re.search(
                r"\b(buy|rent|invest|investment|live in)\b", body,
            ):
                question = self._rt(
                    "Is this for you to live in or for investment?",
                    "Idhu ungaloda use-kaaka, illa investment-ka?",
                    "Idhu ungaloda use-kaaka, investment-kaaka?",
                )
            else:
                question = self._rt(
                    "Anything else I should know about your ideal property?",
                    "Vera edhavadhu specific preferences irukka (e.g. metro kitta, sea view, balcony)?",
                    "Vera ethu theriyum-nu sollunga?",
                )
            response = response.rstrip() + " " + question
        
        # Add assistant response to history
        self.state.add_message("assistant", response, lang_code)
        
        # Parse the response for actions (lead hints). Property cards always
        # come from the deterministic dataset search - never from LLM text.
        parsed = self._parse_response(response)
        if fresh_properties:
            parsed["action"] = "recommendations"
        
        return {
            "response": response,
            "action": parsed.get("action", "continue"),
            "properties": fresh_properties,
            "language_style": lang_style,
            "detected_language": lang_code,
        }

    @staticmethod
    def _tamil_script_count(text: str) -> int:
        """Number of Tamil-script characters (Unicode block 0B80-0BFF)."""
        return sum(1 for c in text if "\u0B80" <= c <= "\u0BFF")

    @staticmethod
    def _strip_markdown(text: str) -> str:
        """Customers see plain text (the interface renders plain bubbles and
        property cards): unwrap **bold**, `code`, heading prefixes and leading
        bullet markers. Measured live (Phase 11): an English reply emitted a
        numbered plan with ** bold ** even though the prompt forbids Markdown,
        so the guarantee is enforced deterministically, not by prompt alone.
        Numbered "1." markers are left as plain digits - harmless without a
        renderer - and mid-line characters are never touched."""
        out = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
        out = out.replace("**", "")            # unbalanced leftovers
        out = re.sub(r"`([^`\n]+)`", r"\1", out)
        out = re.sub(r"(?m)^#{1,6}\s+", "", out)
        out = re.sub(r"(?m)^\s*[-*]\s+", "", out)  # leading bullet markers only
        return out

    @staticmethod
    def _enforce_single_question(text: str) -> str:
        """Keep at most one question per reply (one-question-at-a-time).

        Drops only LATER sentences that themselves end with '?'; statements
        and the FIRST question are always kept, and line breaks are
        preserved. A reply with at most one '?' is returned unchanged.
        """
        if text.count("?") <= 1:
            return text
        # Fragments ending in '?', never spanning '.', '!' or a newline -
        # so a statement between two questions survives as its own fragment.
        fragments = [m.span() for m in re.finditer(r"[^.!?\n]*\?", text)]
        # Keep the first fragment, drop every later one (expanding the removal
        # left over separating spaces so no double space is left behind).
        for start, end in reversed(fragments[1:]):
            s = start
            while s > 0 and text[s - 1] in " \t":
                s -= 1
            text = text[:s] + text[end:]
        return re.sub(r" {2,}", " ", text).strip()

    def _tamil_recovery(self, cards: List[Dict[str, Any]]) -> str:
        """Deterministic Tamil or Tanglish body for a failed turn.

        Everything in it comes from what is actually being shown: the card
        count and the min/max price are read from the dataset rows themselves
        (never invented), and it always ends with a question so the thread
        continues.
        """
        prices: List[float] = []
        for p in cards or []:
            try:
                v = float(str(p.get("price", "")).replace(",", ""))
                if v > 0:
                    prices.append(v)
            except (TypeError, ValueError):
                continue

        if self.state.reply_language == "ta":
            if cards and prices:
                n = len(cards)
                lo = self._fmt_price(str(int(min(prices))))
                hi = self._fmt_price(str(int(max(prices))))
                if lo == hi:
                    return (
                        f"உங்கள் தேவைக்கு ஏற்ற {n} சொத்துக்கள் கிடைச்சிருக்கு — "
                        f"விலை {lo} AED. எதை முதல்ல பார்க்கலாம்?"
                    )
                return (
                    f"உங்கள் தேவைக்கு ஏற்ற {n} சொத்துக்கள் கிடைச்சிருக்கு — "
                    f"விலை {lo} முதல் {hi} AED வரை. எதை முதல்ல பார்க்கலாம்?"
                )
            return nvidia_client._fallback_response("", "ta")
        else:
            if cards and prices:
                n = len(cards)
                lo = self._fmt_price(str(int(min(prices))))
                hi = self._fmt_price(str(int(max(prices))))
                if lo == hi:
                    return (
                        f"Unga requirements-ku match aana {n} properties kidaichirukku — "
                        f"price {lo} AED. Edha mudhalla paakkalaam?"
                    )
                return (
                    f"Unga requirements-ku match aana {n} properties kidaichirukku — "
                    f"price {lo} mudhal {hi} AED varai. Edha mudhalla paakkalaam?"
                )
            return (
                "Vanakkam! Naan LykAI, unga AI property consultant. Dubai-la endha location, "
                "budget evlo, ethana bedrooms paakureenga nu sonneenga na match aagura "
                "properties thedi tharen! Buying-ah illa rent-ka?"
            )
    
    def _should_show_properties(self) -> bool:
        """
        Decide whether we have enough requirements to show properties.

        Follows the canonical customer journey: an anchor (location or
        property type) PLUS a budget. LykAI asks for the budget first
        ("What's your approximate budget?") and only then are matching cards
        attached - the customer never sees properties before the search is
        meaningful.
        """
        req = self.state.requirements
        has_anchor = bool(req.get("location") or req.get("property_type"))
        return has_anchor and bool(req.get("budget"))

    def _auto_search_if_needed(self) -> List[Dict[str, Any]]:
        """Run the deterministic dataset search when requirements are complete.

        Returns the fresh property list to attach to this reply, or [] when
        requirements are incomplete or the result only contains listings whose
        cards are already visible (so duplicate cards are never re-attached and
        ordinal references like "the second property" keep matching what the
        customer sees).
        """
        if not self._should_show_properties():
            return []
        prev = list(self.state.recommended_properties)
        result = self._search_with_criteria(**self._requirements_to_criteria())
        if not result:
            return []
        new_props = result.get("properties", [])
        new_ids = {p.get("property_id") for p in new_props}
        prev_ids = {p.get("property_id") for p in prev}
        if prev_ids and new_ids and new_ids.issubset(prev_ids):
            # Same listings already shown as cards - keep the existing order.
            self.state.recommended_properties = prev
            return []
        return new_props

    def _context_block(
        self,
        focus_property: Optional[Dict[str, Any]] = None,
        fresh_properties: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """Internal context appended to the system prompt (never customer-facing).

        Gives the LLM (a) requirements gathered so far, (b) whether fresh cards
        are attached to THIS reply (and that it should announce them), (c) the
        numbered list of properties already shown in this conversation, and
        (d) any property the customer opened from its details page. Compact
        one-line summaries of the eight dataset fields only - the full
        dataset/JSON is never sent to the model.
        """
        lines: List[str] = ["", "CONTEXT (internal - never mention this block to the customer):"]

        # Explicit per-turn reply-language instruction: detection alone is not
        # reliable enough for the model to consistently answer in Tamil.
        lang_line = {
            "ta": (
                "REPLY LANGUAGE: Tanglish - write the reply in natural, casual Tanglish "
                "(Tamil words written in ENGLISH/LATIN LETTERS with English property terms, e.g. 'Vanakkam! "
                "Dubai Marina-la 2 BHK apartment thedureengala? Budget evlo irukkum?'). "
                "CRITICAL: DO NOT write in Tamil script unicode characters. Never plain English."
            ),
            "ta-Latn": (
                "REPLY LANGUAGE: Tanglish - Tamil words written in English letters, "
                "casual and natural. Never plain English: mix Tamil words in, e.g. "
                "\"Sollunga, budget evlo? Filter panni kaatturen.\""
            ),
            "mixed": (
                "REPLY LANGUAGE: Tanglish - conversational Tamil words in English letters. "
                "CRITICAL: Do not use pure Tamil script unicode."
            ),
            "en": "REPLY LANGUAGE: English.",
        }.get(self.state.reply_language or "en")
        if lang_line:
            lines.append(lang_line)

        req = self.state.requirements
        known = [
            f"  - {label}: {value}"
            for label, value in (
                ("looking to", req.get("buy_rent")),
                ("location", req.get("location")),
                ("budget", req.get("budget")),
                ("property type", req.get("property_type")),
                ("bedrooms", req.get("bedrooms")),
                ("bathrooms", req.get("bathrooms")),
                ("furnishing", req.get("furnishing")),
                ("preferences & amenities", req.get("preferences") or req.get("amenities")),
                ("investment purpose", req.get("investment_purpose")),
                ("timeline", req.get("timeline")),
            )
            if value not in (None, "", [])
        ]
        if known:
            lines.append("Requirements gathered so far:")
            lines.extend(known)

        recs = self.state.recommended_properties[:10]
        if fresh_properties:
            lines.append(
                f"NEW MATCHES: {len(fresh_properties)} properties matched - their "
                "cards are attached to your reply THIS turn. Your FIRST sentence "
                "must announce them (e.g. \"I found a few properties that match "
                "what you're looking for\"), then say briefly WHY they fit the "
                "stated requirements - and write that announcement in the "
                "conversation's REPLY LANGUAGE (a Tanglish reply stays Tanglish "
                "throughout, never a separate English paragraph). Do not "
                "postpone this behind clarifying questions - announce first, "
                "then continue the conversation (at most one question)."
            )
        elif recs:
            lines.append(
                "No new cards this turn: do NOT announce or re-list matches - "
                "the cards listed below are already visible in the chat."
            )

        if recs:
            lines.append(
                "Properties already shown to the customer (numbered exactly as "
                "their cards appear in the chat):"
            )
            for i, p in enumerate(recs, 1):
                lines.append(
                    f"  {i}) {p.get('property_type') or 'Property'} | "
                    f"{p.get('location') or 'UAE'} | "
                    f"AED {self._fmt_price(p.get('price'))} | "
                    f"beds: {p.get('no__of__beds') or 'Not provided'} | "
                    f"baths: {p.get('no_of_baths') or 'Not provided'} | "
                    f"area: {p.get('area') or 'Not provided'} | "
                    f"listing id: {p.get('property_id')}"
                )

        if focus_property:
            p = focus_property
            lines.append(
                "The customer just opened this listing from its details page and "
                "may ask about it (they never need to give you the id):\n"
                f"  {p.get('property_type') or 'Property'} in "
                f"{p.get('location') or 'UAE'} - AED {self._fmt_price(p.get('price'))}, "
                f"{p.get('no__of__beds') or 'Not provided'} beds, "
                f"{p.get('no_of_baths') or 'Not provided'} baths, "
                f"{p.get('area') or 'Not provided'}, listing id {p.get('property_id')}. "
                f"Highlights: {p.get('highlights') or 'Not provided'}\n"
                "THIS TURN (authoritative): when the customer says \"this property\", "
                "\"it\", or \"that listing\" in their current message, they mean "
                "ONLY this focus listing above — answer about it, never about an "
                "earlier numbered card or a listing discussed previously."
            )
            # Phase 7 honesty guard: fictional demo listings are approved and
            # available inside the demo set, but must never be presented as
            # real, verified, or currently available Lyka Realty inventory.
            if p.get("is_demo"):
                lines.append(
                    "IMPORTANT HONESTY: the focus listing above is explicitly "
                    "marked as a FICTIONAL DEMO listing (synthetic demo data — "
                    "NOT a real, verified, or currently available Lyka Realty "
                    "property). Never present it as a real or verified Lyka "
                    "Realty property. If the customer asks whether it is real, "
                    "verified, or actually available, say clearly that it is a "
                    "fictional demo listing."
                )

        return "\n".join(lines)

    @staticmethod
    def _fmt_price(price: Any) -> str:
        """Format a dataset price for the model context.

        The dataset groups digits Indian-style (\"13,80,000\"), which pulls the
        model into lakh/BHK vocabulary and miscomparisons (\"above 3 million\"
        for a 1,380,000 row). Same value, Western grouping (\"1,380,000\") so
        budget math and phrasing stay natural for a UAE customer. Values with
        decimals or no thousands are returned untouched.
        """
        s = str(price if price is not None else "").strip()
        if not s:
            return "Not provided"
        if "." in s:
            return s
        digits = re.sub(r"[^\d]", "", s)
        if len(digits) < 4:
            return s
        return f"{int(digits):,}"

    # Ordinals the customer may use to point at a numbered card (English +
    # Tamil). Maps the word to the 1-based card index the customer sees.
    _ORDINALS = {
        "first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3,
        "fourth": 4, "4th": 4, "fifth": 5, "5th": 5, "sixth": 6, "6th": 6,
        "seventh": 7, "7th": 7, "eighth": 8, "8th": 8, "ninth": 9, "9th": 9,
        "tenth": 10, "10th": 10,
        # Tamil ordinal suffixes: முதல் (first), இரண்டாவது (second), ...
        "முதல்": 1, "இரண்டாவது": 2, "மூன்றாவது": 3,
        "நான்காவது": 4, "ஐந்தாவது": 5,
    }
    _REF_RE = re.compile(
        r"\b(?P<en>first|1st|second|2nd|third|3rd|fourth|4th|fifth|5th|"
        r"sixth|6th|seventh|7th|eighth|8th|ninth|9th|tenth|10th)\b"
        r"(?:\s+\w+){0,2}[\s-]+(?:one|property|listing|option|card|apartment|"
        r"villa|flat|home|result|match|unit)\b"
        # Tamil ordinals: \b cannot be used — vowel signs/viramas are non-word
        # characters, so a trailing \b never matches (முதல், இரண்டாவது). The
        # block lookarounds also stop suffixed words like முதலில் from matching.
        r"|(?<![\u0b80-\u0bff])(?P<ta>முதல்|இரண்டாவது|மூன்றாவது|"
        r"நான்காவது|ஐந்தாவது)(?![\u0b80-\u0bff])"
        r"|\b(?:property|listing|option|card|result|match|unit)\s*#?\s*"
        r"(?P<num>\d{1,2})\b"
        r"|#\s?(?P<hash>\d{1,2})\b",
        re.IGNORECASE,
    )

    def _reference_hint(self, user_message: str, context_block: str) -> str:
        """Pin ordinal references ("the second property") to the exact card
        the customer can see.

        The numbered list above already mirrors the visible cards, but with
        the reasoning pass disabled the model sometimes answered from its own
        imagination instead — an observed failure described a Dubai Marina
        building that was not in the result set at all. This line makes the
        mapping explicit and authoritative.
        """
        m = self._REF_RE.search(user_message.lower())
        if not m:
            return context_block
        word = m.group("en") or m.group("ta")
        if word:
            index = self._ORDINALS.get(word)
        else:
            digits = m.group("num") or m.group("hash")
            index = int(digits) if digits and 1 <= int(digits) <= 99 else None
        if not index:
            return context_block
        recs = self.state.recommended_properties[:10]
        if not recs:
            return context_block
        quote = " ".join(user_message.split())[:200]
        if index > len(recs):
            extra = (
                f"NOTE: \"{quote}\" points at card #{index}, but only "
                f"{len(recs)} cards are visible to the customer. Do not invent "
                f"a listing — say you can only see {len(recs)} cards."
            )
        else:
            p = recs[index - 1]
            extra = (
                f"CUSTOMER REFERENCE (authoritative): \"{quote}\" points at card "
                f"#{index} above - {p.get('property_type') or 'Property'} | "
                f"{p.get('location') or 'UAE'} | "
                f"AED {self._fmt_price(p.get('price'))} | "
                f"beds: {p.get('no__of__beds') or 'Not provided'} | "
                f"listing id: {p.get('property_id')}. Answer ONLY from that "
                "card's details; never substitute a different listing."
            )
        return f"{context_block}\n{extra}" if context_block else extra

    def _extract_requirements(self, message: str):
        """
        Extract customer requirements from a message and store them
        in conversation state (only if not already set - ask once principle).
        """
        msg = message.lower()
        # Tamil numerals (௦-௯) -> ASCII so "௩ மில்லியன்" parses like "3 million"
        msg = msg.translate({
            ord("\u0BE6"): "0", ord("\u0BE7"): "1", ord("\u0BE8"): "2",
            ord("\u0BE9"): "3", ord("\u0BEA"): "4", ord("\u0BEB"): "5",
            ord("\u0BEC"): "6", ord("\u0BED"): "7", ord("\u0BEE"): "8",
            ord("\u0BEF"): "9",
        })
        
        # Buy / Rent intent (English + common Tamil words)
        if self.state.requirements.get("buy_rent") is None:
            if re.search(
                r"\b(buy|purchas|invest(ment)?|own|for myself|buying)\b|வாங்க",
                msg,
            ):
                self.state.requirements["buy_rent"] = "buy"
            elif re.search(
                r"\b(rent|rental|lease|tenant|renting|hir(e|ing))\b|வாடகை",
                msg,
            ):
                self.state.requirements["buy_rent"] = "rent"
        
        # Budget (number + optional unit)
        if self.state.requirements.get("budget") is None:
            budget = self._parse_budget(msg)
            # _parse_budget returns the largest unit-bearing number (million
            # beats "3 bed"), and filters lone phone-like numbers itself.
            # The >= 10_000 floor excludes bed/bath counts.
            if budget and budget >= 10_000 and budget <= 10_000_000_000:
                price_ctx = re.search(
                    r"(budget|aed|price|under|below|around|within|max|"
                    r"crore|lakh|million|mn|\bcost|afford|"
                    r"விலை|பட்ஜெட்|குள|வரை|லட்சம்|கோடி|மில்லியன்)", msg,
                )
                if price_ctx:
                    self.state.requirements["budget"] = budget
        
        # Location - common UAE areas (English names first)
        if self.state.requirements.get("location") is None:
            known_locations = [
                "dubai marina", "downtown dubai", "business bay", "jbr",
                "palm jumeirah", "arabian ranches", "jvc", "jumeirah village circle",
                "dubai hills", "dubai creek harbour", "al barsha", "bur dubai",
                "deira", "abu dhabi", "sharjah", "ajman", "jlt",
                "dubai lands", "sports city", "damac hills", "furjan",
                "mirdif", "silicon oasis", "knowledge village", "dubai south",
                " Mohammed Bin Rashid", "mbrcity", "the valleys",
                "tilal al ghaf", "dubai production city", "impz",
                "international city", "discovery gardens", "arjan",
                "dubai harbour", "bluewaters", "city walk", "al furjan",
                # Standalone city LAST so compound areas above match first:
                # "Dubai la 2 bedroom apartment venum" / "in dubai" / "dubai?"
                "dubai",
            ]
            for loc in known_locations:
                if loc in msg:
                    # Title-case the location nicely
                    self.state.requirements["location"] = loc.title()
                    break
            # Tamil-script city names -> dataset location ("துபாயில்..." -> Dubai)
            if self.state.requirements.get("location") is None:
                ta_locations = [
                    ("துபாய", "Dubai"),       # துபாய் / துபாயில் / துபாயின்
                    ("அபுதாபி", "Abu Dhabi"),
                    ("ஷார்ஜா", "Sharjah"),
                    ("அஜ்மான்", "Ajman"),
                ]
                for ta_name, loc in ta_locations:
                    if ta_name in msg:
                        self.state.requirements["location"] = loc
                        break
            # Fallback: "in <city>"
            if self.state.requirements.get("location") is None:
                loc_match = re.search(r"\bin\s+([a-z\s]+?)(?:\.|,|$|\s+(?:for|with|under|around))", msg)
                if loc_match:
                    candidate = loc_match.group(1).strip()
                    if len(candidate) > 2 and len(candidate) < 40:
                        self.state.requirements["location"] = candidate.title()
        
        # Property type (English + Tamil words)
        if self.state.requirements.get("property_type") is None:
            type_map = {
                "villa": "villa", "apartment": "apartment", "flat": "apartment",
                "townhouse": "townhouse", "penthouse": "penthouse",
                "studio": "studio", "hotel apartment": "hotel apartment",
                "land": "land", "plot": "land", "office": "office",
                "shop": "shop", "villa compound": "villa",
                # Forgiving Tamil prefixes: cover அபார்ட்மென்ட், அபார்ட்மென்டு
                # and colloquial spellings; வில்லா = villa, வீடு = house/villa
                "அபார்ட்மெ": "apartment",
                "வில்லா": "villa", "வீடு": "villa",
                "ஸ்டுடியோ": "studio", "டவுன்ஹவுஸ்": "townhouse",
            }
            for key, value in type_map.items():
                if re.search(r"\b" + re.escape(key) + r"\b" if key.isascii() else re.escape(key), msg):
                    self.state.requirements["property_type"] = value
                    break
        
        # Bedrooms (English + Tamil: "2 பெட்ரூம்", "2 பெட்"). The separator may
        # be a space, nothing, or a hyphen — "2-bedroom" is the most common
        # English spelling and must not fall through to an unfiltered search.
        if self.state.requirements.get("bedrooms") is None:
            bed_match = re.search(
                r"(\d+)[\s-]*(?:bed|bhk|bedroom|பெட்ரூம்|பெட்)",
                msg,
            )
            if bed_match:
                self.state.requirements["bedrooms"] = int(bed_match.group(1))
            elif re.search(r"\bstudio\b|ஸ்டுடியோ", msg):
                self.state.requirements["bedrooms"] = 0
        
        # Bathrooms
        if self.state.requirements.get("bathrooms") is None:
            bath_match = re.search(r"(\d+)[\s-]*bath", msg)
            if bath_match:
                self.state.requirements["bathrooms"] = int(bath_match.group(1))
        
        # Investment purpose
        if self.state.requirements.get("investment_purpose") is None:
            if re.search(r"\b(invest|investment|roi|yield|rental income|passive)\b", msg):
                self.state.requirements["investment_purpose"] = "investment"
            elif re.search(r"\b(living|live|family|myself|own use|self)\b", msg):
                self.state.requirements["investment_purpose"] = "self_use"
        
        # Timeline
        if self.state.requirements.get("timeline") is None:
            if re.search(r"\b(immediate|asap|now|this month)\b", msg):
                self.state.requirements["timeline"] = "immediate"
            elif re.search(r"\b(\d+\s*month|next year|soon|by \d{4})\b", msg):
                self.state.requirements["timeline"] = "within_months"

        # Specific amenities / preferences (English and Tanglish)
        current_amenities = self.state.requirements.get("amenities") or []
        if isinstance(current_amenities, str):
            try:
                current_amenities = json.loads(current_amenities)
            except Exception:
                current_amenities = [current_amenities]
        current_amenities = list(current_amenities)

        amenity_patterns = [
            ("near_metro", r"\b(metro\s*(?:station|kitta|pakkathula|nearby|walkable)?|near\s*metro|close\s*to\s*metro)\b"),
            ("sea_view", r"\b(sea\s*view|beach\s*view|ocean\s*view|marina\s*view|water\s*view|kadal\s*(?:view|paatha))\b"),
            ("balcony", r"\b(balcony|terrace|verandah)\b"),
            ("pool", r"\b(pool|swimming\s*pool|neechal\s*kulam)\b"),
            ("gym", r"\b(gym|fitness\s*center|fitness\s*centre|workout)\b"),
            ("furnished", r"\b(fully\s*furnished|furnished)\b"),
            ("unfurnished", r"\b(unfurnished|semi[\s-]*furnished)\b"),
            ("parking", r"\b(parking|car\s*parking|garage)\b"),
            ("garden", r"\b(garden|private\s*garden|park|greenery)\b"),
            ("pet_friendly", r"\b(pet\s*friendly|pets?\s*allowed)\b"),
            ("high_floor", r"\b(high\s*floor|top\s*floor|upper\s*floor)\b"),
            ("maid_room", r"\b(maid\s*room|maids?\s*room)\b"),
        ]

        for code, pattern in amenity_patterns:
            if re.search(pattern, msg) and code not in current_amenities:
                current_amenities.append(code)

        if current_amenities:
            self.state.requirements["amenities"] = current_amenities
            self.state.requirements["preferences"] = current_amenities

        if "furnished" in current_amenities and not self.state.requirements.get("furnishing"):
            self.state.requirements["furnishing"] = "Furnished"
        elif "unfurnished" in current_amenities and not self.state.requirements.get("furnishing"):
            self.state.requirements["furnishing"] = "Unfurnished"
        
        # Contact info (name / phone / email)
        if not self.state.contact.get("email"):
            email_match = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", message)
            if email_match:
                self.state.contact["email"] = email_match.group(0)
        if not self.state.contact.get("phone"):
            phone_patterns = [
                r"(?:\+?971[\s-]?)?(?:0)?5[0-9][\s-]?\d{3}[\s-]?\d{4}",
                r"(?:\+?91[\s-]?)?[6-9]\d{9}",
                r"\b[6-9]\d{9}\b",
                r"(?:\+?971|0)?[5-9]\d{8,9}",
            ]
            for pat in phone_patterns:
                phone_match = re.search(pat, message)
                if not phone_match:
                    phone_match = re.search(pat, message.replace(" ", ""))
                if phone_match:
                    raw_val = phone_match.group(0).strip()
                    digits = re.sub(r"[^\d+]", "", raw_val)
                    if 9 <= len(digits.lstrip("+")) <= 14:
                        self.state.contact["phone"] = digits
                        break
        if not self.state.contact.get("name"):
            name_patterns = [
                r"(?:my name is|i am|i'm|this is|call me|name[:\-]?)\s+([A-Za-z\u0B80-\u0BFF]+(?:\s+[A-Za-z\u0B80-\u0BFF]+)?)",
                r"(?:en\s+peyar(?:\s+is)?|en\s+peru?(?:\s+is)?|ennoda\s+peru?(?:\s+is)?|ennoda\s+name(?:\s+is)?|en\s+name(?:\s+is)?)\s+([A-Za-z\u0B80-\u0BFF]+(?:\s+[A-Za-z\u0B80-\u0BFF]+)?)",
                r"(?:naan\s+thaan|naan)\s+([A-Za-z\u0B80-\u0BFF]+(?:\s+[A-Za-z\u0B80-\u0BFF]+)?)",
                r"(?:என்\s+பெயர்|என்\s+பேரு|பெயர்|பேரு)\s*[:\-]?\s*([A-Za-z\u0B80-\u0BFF]+(?:\s+[A-Za-z\u0B80-\u0BFF]+)?)",
            ]
            for pat in name_patterns:
                name_match = re.search(pat, message, re.IGNORECASE)
                if name_match:
                    cand = name_match.group(1).strip()
                    if cand.lower() not in ("looking", "interested", "searching", "buying", "renting", "here", "tamil"):
                        self.state.contact["name"] = cand.title() if cand.isascii() else cand
                        break
    
    def _handle_followup(self, user_message: str) -> Optional[Dict[str, Any]]:
        """
        Handle natural language follow-ups like:
        - "show me cheaper ones"
        - "what about 3 bedrooms?"
        - "something near the beach"
        - "are these available?"
        """
        msg = user_message.lower().strip()
        
        # "show me cheaper ones" - re-rank by price
        if "cheaper" in msg or "less expensive" in msg or "lower price" in msg:
            if self.state.recommended_properties:
                # Sort by price ascending using proper price parsing
                props = sorted(
                    self.state.recommended_properties,
                    key=lambda p: parse_price(p.get("price", "")) or 0,
                )
                return {
                    "action": "recommendations",
                    "properties": props[:10],
                    "response": self._rt(
                        "Here are the more affordable options I found:",
                        "மலிவான விருப்பங்கள் இதோ:",
                        "Konjam kullaana options kandupudichen:",
                    ),
                }
            # If no previous recommendations, search with existing requirements
            # but lower the budget if we have one
            criteria = self._requirements_to_criteria()
            lowered = criteria.get("max_price")
            if lowered:
                criteria["max_price"] = lowered * 0.7
            result = self._search_with_criteria(**criteria)
            if result:
                # Persist the lowered budget (only on success) so later
                # searches stay consistent with the "cheaper" the customer
                # just asked for - otherwise the pricier set comes back.
                if lowered:
                    self.state.requirements["budget"] = str(int(lowered * 0.7))
                result["response"] = self._rt(
                    "Here are some more affordable options I found:",
                    "இன்னும் சில மலிவான விருப்பங்கள் கிடைச்சுது:",
                    "Innum konjam kullaana options kidaichudhu:",
                )
                return result
            return None
        
        # "what about X bedrooms?" 
        bed_match = re.search(r'(\d+)\s*bedroom', msg)
        if bed_match:
            beds = int(bed_match.group(1))
            self.state.requirements["bedrooms"] = beds
            # Filter existing recommendations to this bedroom count
            filtered = []
            if self.state.recommended_properties:
                filtered = [p for p in self.state.recommended_properties 
                          if self._get_bedrooms(p) == beds]
            # Only use the filtered set if it's substantial; otherwise
            # re-search with full criteria so the customer sees real options
            if len(filtered) >= 3:
                return {
                    "action": "recommendations",
                    "properties": filtered[:10],
                    "response": self._rt(
                        f"Here are {beds}-bedroom options I found:",
                        f"{beds} பெட்ரூம் விருப்பங்கள் இதோ:",
                        f"{beds} bedroom options இதோ:",
                    )
                }
            criteria = self._requirements_to_criteria()
            criteria["min_bedrooms"] = beds
            criteria["max_bedrooms"] = beds
            result = self._search_with_criteria(**criteria)
            if result:
                return result
            # Otherwise let the LLM continue the natural conversation
            return None
        
        # "near the beach" / location override
        beach_keywords = ["beach", "marina", "sea", "ocean"]
        if any(k in msg for k in beach_keywords):
            # Could update location preference
            if "dubai marina" in msg or "marina" in msg:
                self.state.requirements["location"] = "Dubai Marina"
                if self.state.recommended_properties:
                    return {
                        "action": "recommendations",
                        "properties": self.state.recommended_properties[:10],
                        "response": self._rt(
                            "Checking Dubai Marina options for you...",
                            "உங்களுக்காக Dubai Marina விருப்பங்களை பார்க்கிறேன்...",
                            "Ungalukkaaga Dubai Marina options paakkuren...",
                        )
                    }
            return None
        
        return None
    
    def _get_bedrooms(self, prop: Dict) -> Optional[int]:
        """Extract bedroom count from property dict."""
        beds_str = prop.get("no__of__beds", "")
        try:
            return int(float(beds_str))
        except (ValueError, TypeError):
            return None

    def _rt(self, en: str, ta: str, ta_latn: str) -> str:
        """Pick the reply-language variant of a deterministic (non-LLM) string
        so refinement answers like "cheaper ones" stay in the customer's
        language instead of always falling back to English."""
        lang = self.state.reply_language or "en"
        if lang in ("ta", "ta-Latn", "mixed"):
            return ta_latn
        return en
    
    def _search_with_criteria(self, **criteria) -> Optional[Dict]:
        """Search properties with given criteria."""
        from sqlalchemy.orm import Session
        from app.database import engine
        db = Session(bind=engine)
        
        try:
            result = search_properties(db=db, **criteria)
            props = result.get("results", [])
        finally:
            db.close()
        
        if props:
            # A fresh search replaces the visible set - keep the DATASET-space
            # property the customer opened from its details page in the list,
            # since it is part of this conversation too. Record-space focus
            # (Phase 6) is deliberately never merged here: its id lives in a
            # different id space, so it would be returned to the caller as a
            # dataset card and persisted as a dataset recommendation.
            focus = self.state.focus_property
            if (
                focus
                and focus.get("source") != "record"
                and not any(
                    p.get("property_id") == focus.get("property_id") for p in props
                )
            ):
                props = [focus] + props
            self.state.recommended_properties = props
            return {
                "action": "recommendations",
                "properties": props[:10],
                "response": self._rt(
                    f"I found {len(props)} properties matching your criteria. "
                    "Here are the top ones:",
                    f"உங்கள் தேவைக்கு பொருந்தும் {len(props)} சொத்துக்கள் கிடைச்சுது. "
                    "முதல்ல இதோ:",
                    f"Unga criteria-ku {len(props)} properties kidaichudhu. "
                    "Mudhalla idho:",
                ),
            }
        return None
    
    def _requirements_to_criteria(self) -> Dict[str, Any]:
        """Convert accumulated conversation requirements into search criteria."""
        req = self.state.requirements
        criteria: Dict[str, Any] = {}
        
        if req.get("location"):
            criteria["location"] = req["location"]
        if req.get("property_type"):
            criteria["property_type"] = req["property_type"]
        if req.get("budget"):
            # Budget may be stored as text like "5 million AED" or "5000000"
            budget_val = self._parse_budget(req["budget"])
            if budget_val:
                criteria["max_price"] = budget_val
        if req.get("bedrooms"):
            criteria["min_bedrooms"] = req["bedrooms"]
            criteria["max_bedrooms"] = req["bedrooms"]
        if req.get("bathrooms"):
            criteria["min_bathrooms"] = req["bathrooms"]
        if req.get("area"):
            criteria["min_area"] = req["area"]
        if req.get("furnishing"):
            criteria["furnishing"] = req["furnishing"]
        
        criteria["limit"] = 20
        return criteria
    
    @staticmethod
    def _parse_budget(budget: Any) -> Optional[float]:
        """Parse a budget value which may be a number or text like '5 million AED'.

        Finds all number+unit candidates and returns the most plausible one:
        - Candidates with an explicit unit (million/lakh/crore/k) always win,
          so "2 bedroom ... under 3 million" -> 3,000,000.
        - A lone bare 9-12 digit number is treated as a phone number and ignored.
        """
        if isinstance(budget, (int, float)):
            return float(budget)
        if not isinstance(budget, str):
            return None
        text = budget.lower().replace(",", "").strip()
        # Tamil numerals (௦-௯) -> ASCII: "௨ மில்லியன்" == "2 million"
        text = text.translate({
            ord("\u0BE6"): "0", ord("\u0BE7"): "1", ord("\u0BE8"): "2",
            ord("\u0BE9"): "3", ord("\u0BEA"): "4", ord("\u0BEB"): "5",
            ord("\u0BEC"): "6", ord("\u0BED"): "7", ord("\u0BEE"): "8",
            ord("\u0BEF"): "9",
        })
        # English number words -> digits: "five lakh AED" == "5 lakh AED".
        # Compound tens first ("twenty five" -> 25), then single words.
        num_words = {
            "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
            "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
            "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
            "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
            "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40,
            "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80,
            "ninety": 90,
        }
        _ones = (
            "one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
            "thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen"
        )
        _tens = "twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety"
        text = re.sub(
            r"\b(" + _tens + r")[-\s](" + _ones + r")\b",
            lambda m: str(num_words[m.group(1)] + num_words[m.group(2)]),
            text,
        )
        text = re.sub(
            r"\b(" + "|".join(num_words) + r")\b",
            lambda m: str(num_words[m.group(0)]),
            text,
        )

        with_unit: List[float] = []
        bare: List[float] = []
        bare_digits: List[int] = []
        # Unit words: English + Tamil (மில்லியன் = million, லட்சம் = lakh,
        # கோடி = crore, ஆயிரம் = thousand) so "பட்ஜெட் 3 மில்லியன்" = 3,000,000.
        unit_multipliers = {
            "million": 1_000_000, "mn": 1_000_000,
            "billion": 1_000_000_000, "bn": 1_000_000_000,
            "crore": 10_000_000, "lakh": 100_000, "k": 1_000,
            # Plurals + "thousand": "5 lakhs" / "3 thousand AED"
            "millions": 1_000_000, "billions": 1_000_000_000,
            "crores": 10_000_000, "lakhs": 100_000,
            "thousand": 1_000, "thousands": 1_000,
            "மில்லியன்": 1_000_000, "மில்லியன": 1_000_000,
            "மில்லியன்ஸ்": 1_000_000,
            "லட்சம்": 100_000, "லட்சம": 100_000, "லக்": 100_000,
            "கோடி": 10_000_000, "ஆயிரம்": 1_000, "ஆயிரம": 1_000,
        }
        for match in re.finditer(
            # NOTE: (?![a-z0-9]) instead of \b — the Tamil virama (்) is a
            # non-word char, so \b never fires after Tamil unit words and
            # "3 மில்லியன்" would fall back to the bare number 3.
            r"([\d.]+)\s*(" + "|".join(
                re.escape(u)
                for u in (
                    # Longer forms first so "5 lakhs" never stops at "lakh".
                    "millions", "million", "mn", "billions", "billion", "bn",
                    "crores", "crore", "lakhs", "lakh", "thousands",
                    "thousand", "k",
                    "aed", "usd", "dh",
                    "மில்லியன்ஸ்", "மில்லியன்", "மில்லியன",
                    "லட்சம்", "லட்சம", "லக்", "கோடி",
                    "ஆயிரம்", "ஆயிரம",
                )
            ) + r")?(?![a-z0-9])",
            text,
        ):
            digits = match.group(1).replace(".", "", 1)
            try:
                value = float(match.group(1))
            except ValueError:
                continue
            unit = match.group(2)
            if unit in unit_multipliers:
                value *= unit_multipliers[unit]
            if unit:
                with_unit.append(value)
            else:
                bare.append(value)
                bare_digits.append(len(digits))

        if with_unit:
            return max(with_unit)
        if not bare:
            return None
        # A single bare number in phone range (9-12 digits, >= 100M) -> phone
        if len(bare) == 1 and 9 <= bare_digits[0] <= 12 and bare[0] >= 100_000_000:
            return None
        # Prefer the largest value (budgets are typically the big numbers);
        # bare small numbers like "2 bedroom" are filtered out by the caller.
        return max(bare)
    
    def _parse_response(self, response: str) -> Dict[str, Any]:
        """
        Parse the LLM response to extract:
        - The actual response text
        - Any property recommendations to show
        - Action to take (continue, collect_lead, etc.)
        """
        msg = response.lower().strip()
        result = {
            "action": "continue",
            "properties": [],
            "response": response,
        }
        
        # Check if the response mentions specific properties
        # Look for property-like information in the response
        # If the AI recommends properties, we need to search and return them
        
        # Check for lead collection indicators
        lead_keywords = [
            "name", "phone", "email", "contact", "reach me",
            "peyar", "per", "peru", "ennoda", "number", "mail",
            "பெயர்", "பேரு", "எண்", "தொடர்பு", "போன்", "வாட்ஸ்அப்", "whatsapp",
        ]
        if any(k in msg for k in lead_keywords) and self._should_collect_lead():
            result["action"] = "collect_lead"
        
        # Check for budget mentions that we should capture
        import re
        price_match = re.search(r'[\d,]+\s*[ ]?[a-zA-Z]*', msg)
        # Don't automatically capture every price mention - only when 
        # it's a clear budget statement
        
        return result
    
    def _should_collect_lead(self) -> bool:
        """Determine if enough information has been collected to create a lead.

        Requires at least one way to contact the customer (phone or email)
        plus any collected requirement or name.
        """
        has_contact = bool(
            self.state.contact.get("phone") or self.state.contact.get("email")
        )
        if not has_contact:
            return False

        req = self.state.requirements
        filled = sum(1 for v in req.values() if v is not None)
        has_name = bool(self.state.contact.get("name"))
        return filled >= 1 or has_name
    
    def collect_contact_info(self, info_type: str, value: str):
        """Collect customer contact information."""
        if info_type in self.state.contact:
            self.state.contact[info_type] = value
    
    def update_requirement(self, key: str, value: Any):
        """Update a requirement if not already set (ask once principle)."""
        if key in self.state.requirements and self.state.requirements[key] is None:
            self.state.requirements[key] = value
        elif key in self.state.requirements:
            # Already set - just note the new info but don't override
            pass
        else:
            self.state.requirements[key] = value
    
    def get_lead_data(self) -> Dict[str, Any]:
        """Get all collected data for lead creation (types match the DB columns)."""
        budget = self.state.requirements.get("budget")
        if isinstance(budget, (int, float)):
            budget = f"AED {budget:,.0f}"

        bedrooms = self.state.requirements.get("bedrooms")
        try:
            bedrooms = int(bedrooms) if bedrooms is not None else None
        except (TypeError, ValueError):
            bedrooms = None

        bathrooms = self.state.requirements.get("bathrooms")
        try:
            bathrooms = int(bathrooms) if bathrooms is not None else None
        except (TypeError, ValueError):
            bathrooms = None

        amenities_val = self.state.requirements.get("amenities") or self.state.requirements.get("preferences") or []
        if isinstance(amenities_val, str):
            try:
                amenities_val = json.loads(amenities_val)
            except Exception:
                amenities_val = [amenities_val]
        amenities_list = list(dict.fromkeys(amenities_val))

        notes_parts = []
        if self.state.requirements.get("investment_purpose"):
            notes_parts.append(f"Purpose: {self.state.requirements['investment_purpose']}")
        if self.state.requirements.get("timeline"):
            notes_parts.append(f"Timeline: {self.state.requirements['timeline']}")
        if amenities_list:
            notes_parts.append(f"Preferences: {', '.join(amenities_list)}")
        if self.state.requirements.get("notes"):
            notes_parts.append(str(self.state.requirements.get("notes")))

        return {
            "name": self.state.contact.get("name"),
            "phone": self.state.contact.get("phone"),
            "email": self.state.contact.get("email"),
            "buy_rent": self.state.requirements.get("buy_rent"),
            "location": self.state.requirements.get("location"),
            "budget": budget,
            "property_type": self.state.requirements.get("property_type"),
            "bedrooms": bedrooms,
            "bathrooms": bathrooms,
            "requirements": json.dumps(amenities_list) if amenities_list else self.state.requirements.get("requirements"),
            "amenities": json.dumps(amenities_list) if amenities_list else None,
            "investment_purpose": self.state.requirements.get("investment_purpose"),
            "timeline": self.state.requirements.get("timeline"),
            "notes": " | ".join(notes_parts) if notes_parts else None,
        }