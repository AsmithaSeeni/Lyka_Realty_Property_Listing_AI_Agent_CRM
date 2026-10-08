import json
import logging
import re
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
        # Language detection
        self.detected_language = "en"
        # Arabic/English mixed handling
        self.language_style = "en"  # "en", "ta", "ta-Latn" (Tanglish)
    
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
        state.recommended_properties = data.get("recommended_properties", [])
        state.asked_questions = set(data.get("asked_questions", []))
        return state


class AIRealEstateAgent:
    """
    Human-like AI real estate consultant that behaves like an experienced
    UAE real estate agent.
    """
    
    # System prompt defining the agent's personality
    SYSTEM_PROMPT = """You are Lyka Realty's AI real estate consultant - an experienced, 
    knowledgeable UAE property expert. You speak naturally and conversationally, 
    like a human agent who knows the market well.

    PERSONALITY TRAITS:
    - Warm, professional, and helpful
    - Knowledgeable about UAE property market (Dubai, Abu Dhabi, Sharjah)
    - Patient and understanding
    - Never robotic or scripted
    - Asks one question at a time
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

    CONVERSATION FLOW:
    - Start by greeting the customer
    - Ask about their primary need: buying or renting
    - Then ask about location preference
    - Then budget
    - Then property type (apartment, villa, townhouse)
    - Then bedrooms
    - Then any other preferences
    - Naturally collect contact info when the conversation is flowing
    - Create a lead when enough information is available

    LANGUAGE:
    - Understand English, Tamil, Tanglish, and mixed Tamil-English
    - Detect the customer's language and respond in the same style
    - If customer switches languages, switch naturally with them
    - Tanglish is English with Tamil words/phrases (e.g., "2 bedroom villa ah", 
      "Dubai Marina-ku search pannan")

    OUTPUT RULES:
    - Give ONLY the final conversational reply the customer should see.
    - NEVER show your thinking, reasoning, chain-of-thought, or analysis.
    - Never start with "thinking process", "analysis", or numbered reasoning steps.
    - Keep replies concise (2-5 sentences typically) so they work well for voice too.
    - When you mention properties, only mention details the customer already 
      shared or that appear in the provided search results.
    """
    
    def __init__(self, conversation_id: Optional[int] = None):
        self.state = ConversationState(conversation_id)
        self.property_cache: Dict[str, List] = {}  # Cache search results
    
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
        tamil_words = [
            "venum", "pogum", "pogrom", "iruku", "irundhu", "thaan", "thaan",
            "sollu", "sollunga", "sollradha", "solren", "pannu", "pannan",
            "pannunga", "kolla", "kudunga", "keela", "mela", "nalla", "romba",
            "enna", "epdi", "inga", "anga", "varen", "vaanga", "vaango",
            "ah", "ah?", "ah.", "ko", "ku", "la", "la?", "nu", "tha",
            "machan", "anna", "saar", "haye", "yenna", "yepdi",
            "kulla", "kullaah", "vandhuchu", "vendum", "kuduthu",
            "paathu", "paarunga", "nunga", "laam", "aah", "aaga",
        ]
        
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
    
    def respond(self, user_message: str) -> Dict[str, Any]:
        """
        Process a user message and return the AI's response.
        Returns dict with: response, action (continue/lead_created), 
        properties (if recommendations), language_style
        """
        # Detect language
        lang_code, lang_style = self.detect_language_and_style(user_message)
        self.state.detected_language = lang_code
        self.state.language_style = lang_style
        
        # Add user message to history
        self.state.add_message("user", user_message, lang_code)
        
        # Extract requirements (budget, location, beds, buy/rent) from the message
        self._extract_requirements(user_message)
        
        # Handle refinement follow-ups ("cheaper ones", "what about 3 beds")
        # only after the conversation is already underway - the first message
        # always goes to the LLM so the customer gets a natural greeting.
        followup_result = None
        if len(self.state.messages) > 1:
            followup_result = self._handle_followup(user_message)
        if followup_result:
            # Still add the assistant response
            self.state.add_message("assistant", followup_result.get("response", ""), lang_code)
            return followup_result
        
        # Process the message with the LLM (synchronous call)
        # Build conversation history for the API
        history = [{"role": m["role"], "content": m["content"]} 
                  for m in self.state.messages[:-1]]  # Exclude current message
        
        response = nvidia_client.chat_sync(self.SYSTEM_PROMPT, user_message, history)
        
        # Add assistant response to history
        self.state.add_message("assistant", response, lang_code)
        
        # Parse the response to extract actions and property recommendations
        parsed = self._parse_response(response)
        
        # If we have enough requirements and no properties attached yet,
        # run a search so the customer actually sees matching properties
        properties = parsed.get("properties", [])
        if not properties and self._should_show_properties():
            search_result = self._search_with_criteria(**self._requirements_to_criteria())
            if search_result:
                properties = search_result.get("properties", [])
                parsed["action"] = "recommendations"
        
        return {
            "response": response,
            "action": parsed.get("action", "continue"),
            "properties": properties,
            "language_style": lang_style,
            "detected_language": lang_code,
        }
    
    def _should_show_properties(self) -> bool:
        """
        Decide whether we have enough requirements to show properties.
        Requires at least a location or property type plus bedrooms/budget.
        """
        req = self.state.requirements
        has_anchor = bool(req.get("location") or req.get("property_type"))
        has_detail = bool(
            req.get("bedrooms") is not None or req.get("budget")
        )
        return has_anchor and has_detail
    
    def _extract_requirements(self, message: str):
        """
        Extract customer requirements from a message and store them
        in conversation state (only if not already set - ask once principle).
        """
        msg = message.lower()
        
        # Buy / Rent intent
        if self.state.requirements.get("buy_rent") is None:
            if re.search(r"\b(buy|purchas|invest(ment)?|own|for myself|buying)\b", msg):
                self.state.requirements["buy_rent"] = "buy"
            elif re.search(r"\b(rent|rental|lease|tenant|renting|hir(e|ing))\b", msg):
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
                    r"crore|lakh|million|mn|\bcost|afford)", msg,
                )
                if price_ctx:
                    self.state.requirements["budget"] = budget
        
        # Location - common UAE areas
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
            ]
            for loc in known_locations:
                if loc in msg:
                    # Title-case the location nicely
                    self.state.requirements["location"] = loc.title()
                    break
            # Fallback: "in <city>"
            if self.state.requirements.get("location") is None:
                loc_match = re.search(r"\bin\s+([a-z\s]+?)(?:\.|,|$|\s+(?:for|with|under|around))", msg)
                if loc_match:
                    candidate = loc_match.group(1).strip()
                    if len(candidate) > 2 and len(candidate) < 40:
                        self.state.requirements["location"] = candidate.title()
        
        # Property type
        if self.state.requirements.get("property_type") is None:
            type_map = {
                "villa": "villa", "apartment": "apartment", "flat": "apartment",
                "townhouse": "townhouse", "penthouse": "penthouse",
                "studio": "studio", "hotel apartment": "hotel apartment",
                "land": "land", "plot": "land", "office": "office",
                "shop": "shop", "villa compound": "villa",
            }
            for key, value in type_map.items():
                if re.search(r"\b" + re.escape(key) + r"\b", msg):
                    self.state.requirements["property_type"] = value
                    break
        
        # Bedrooms
        if self.state.requirements.get("bedrooms") is None:
            bed_match = re.search(r"(\d+)\s*(?:bed|bhk|bedroom)", msg)
            if bed_match:
                self.state.requirements["bedrooms"] = int(bed_match.group(1))
            elif re.search(r"\bstudio\b", msg):
                self.state.requirements["bedrooms"] = 0
        
        # Bathrooms
        if self.state.requirements.get("bathrooms") is None:
            bath_match = re.search(r"(\d+)\s*bath", msg)
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
        
        # Contact info (name / phone / email)
        if not self.state.contact.get("email"):
            email_match = re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", message)
            if email_match:
                self.state.contact["email"] = email_match.group(0)
        if not self.state.contact.get("phone"):
            phone_match = re.search(r"(?:\+?971|0)?[5-9]\d{8,9}", message.replace(" ", ""))
            if phone_match:
                self.state.contact["phone"] = phone_match.group(0)
        if not self.state.contact.get("name"):
            name_match = re.search(
                r"(?:my name is|i am|i'm|this is|call me|name[:\-]?)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
                message,
            )
            if name_match:
                self.state.contact["name"] = name_match.group(1).strip()
            else:
                # Case-insensitive fallback for the common "My name is X" pattern
                name_match = re.search(
                    r"my name is\s+([a-z]+(?:\s+[a-z]+)?)",
                    message,
                    re.IGNORECASE,
                )
                if name_match:
                    self.state.contact["name"] = name_match.group(1).strip().title()
    
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
                    "response": "Here are the more affordable options I found:",
                }
            # If no previous recommendations, search with existing requirements
            # but lower the budget if we have one
            criteria = self._requirements_to_criteria()
            if criteria.get("max_price"):
                criteria["max_price"] = criteria["max_price"] * 0.7
            result = self._search_with_criteria(**criteria)
            if result:
                result["response"] = "Here are some more affordable options I found:"
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
                    "response": f"Here are {beds}-bedroom options I found:"
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
                        "response": "Checking Dubai Marina options for you..."
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
            self.state.recommended_properties = props
            return {
                "action": "recommendations",
                "properties": props[:10],
                "response": f"I found {len(props)} properties matching your criteria. Here are the top ones:"
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

        with_unit: List[float] = []
        bare: List[float] = []
        bare_digits: List[int] = []
        for match in re.finditer(
            r"([\d.]+)\s*(million|mn|billion|bn|crore|lakh|k|aed|usd|dh)?\b",
            text,
        ):
            digits = match.group(1).replace(".", "", 1)
            try:
                value = float(match.group(1))
            except ValueError:
                continue
            unit = match.group(2)
            if unit in ("million", "mn"):
                value *= 1_000_000
            elif unit in ("billion", "bn"):
                value *= 1_000_000_000
            elif unit == "crore":
                value *= 10_000_000
            elif unit == "lakh":
                value *= 100_000
            elif unit == "k":
                value *= 1_000
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
        lead_keywords = ["name", "phone", "email", "contact", "reach me"]
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

        Requires meaningful requirements AND at least one way to contact
        the customer (phone or email) - a lead without contact details
        is not actionable for the sales team.
        """
        has_contact = bool(
            self.state.contact.get("phone") or self.state.contact.get("email")
        )
        if not has_contact:
            return False

        req = self.state.requirements
        filled = sum(1 for v in req.values() if v is not None)
        has_location = req.get("location") is not None
        has_buy_rent = req.get("buy_rent") is not None
        has_budget = req.get("budget") is not None

        return filled >= 3 or (filled >= 1 and has_location and has_buy_rent and has_budget)
    
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
            "requirements": self.state.requirements.get("requirements"),
            "investment_purpose": self.state.requirements.get("investment_purpose"),
            "timeline": self.state.requirements.get("timeline"),
            "notes": self.state.requirements.get("notes"),
        }