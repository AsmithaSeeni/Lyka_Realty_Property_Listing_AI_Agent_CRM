"""Knowledge Base Loader and Retriever for LykAI AI Property Concierge.

Extracts, indexes, and retrieves authoritative Dubai real-estate domain knowledge
from `backend/app/knowledge/` (transferred from D:\\Lyka_ADK).

Provides structured, source-aware grounding excerpts to the conversational AI engine
(AIRealEstateAgent) with verified DLD/RERA regulatory citations, misconception guards,
and bilingual guidance (English and Tanglish).
"""

import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

KNOWLEDGE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "knowledge")


@dataclass
class KnowledgeDocument:
    filename: str
    title: str
    topic_key: str
    authorities: List[str]
    summary_en: str
    summary_tanglish: str
    verified_facts: List[str]
    misconceptions: List[str]
    faqs: Dict[str, str]
    sources: List[str]
    raw_content: str


# In-memory document registry
_DOCUMENT_REGISTRY: Dict[str, KnowledgeDocument] = {}
_TOPIC_INDEX: Dict[str, List[str]] = {}


def _clean_markdown(text: str) -> str:
    """Strip verbose links, markdown table borders, and citation URLs for clean prompt feeding."""
    lines = []
    for line in text.splitlines():
        line_s = line.strip()
        if line_s.startswith("## Sources") or line_s.startswith("http://") or line_s.startswith("https://"):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def load_knowledge_registry() -> Dict[str, KnowledgeDocument]:
    """Load and index all 21 knowledge documents from the knowledge directory."""
    global _DOCUMENT_REGISTRY, _TOPIC_INDEX
    if _DOCUMENT_REGISTRY:
        return _DOCUMENT_REGISTRY

    if not os.path.isdir(KNOWLEDGE_DIR):
        return {}

    for fname in sorted(os.listdir(KNOWLEDGE_DIR)):
        if not fname.endswith(".md"):
            continue
        fpath = os.path.join(KNOWLEDGE_DIR, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                raw = f.read()
        except Exception:
            continue

        topic_key = fname.replace(".md", "").lower()
        title_match = re.search(r"^#\s+(.+)$", raw, re.MULTILINE)
        title = title_match.group(1).strip() if title_match else topic_key.replace("_", " ").title()

        # Extract authorities (DLD, RERA, Law No. 8 of 2007, Central Bank, etc.)
        auths = set(re.findall(
            r"\b(DLD|RERA|Law No\.\s*\([0-9]+\)\s*of\s*[0-9]+|Oqood|Ejari|MOU|Form F|NOC|Central Bank|FEMA|LRS|RBI)\b",
            raw,
            re.IGNORECASE,
        ))

        # Extract Tanglish spoken excerpt if present
        tanglish_match = re.search(r"## Short spoken explanation \(Tanglish\)\s*\n\"([^\"]+)\"", raw, re.DOTALL)
        tanglish_summary = tanglish_match.group(1).strip() if tanglish_match else ""

        # Extract facts and misconceptions
        facts: List[str] = []
        misconceptions: List[str] = []
        faqs: Dict[str, str] = {}

        current_section = None
        for line in raw.splitlines():
            line_str = line.strip()
            if line_str.startswith("## "):
                current_section = line_str.replace("## ", "").lower()
                continue
            if current_section:
                if "verified" in current_section and (line_str.startswith("- ") or line_str.startswith("* ")):
                    facts.append(line_str[2:].strip())
                elif "misconception" in current_section and (line_str.startswith("- ") or line_str.startswith("* ")):
                    misconceptions.append(line_str[2:].strip())

        # Extract sources
        sources = re.findall(r"(https?://[^\s\)]+)", raw)

        doc = KnowledgeDocument(
            filename=fname,
            title=title,
            topic_key=topic_key,
            authorities=sorted(list(auths)),
            summary_en=_clean_markdown(raw[:600]),
            summary_tanglish=tanglish_summary,
            verified_facts=facts,
            misconceptions=misconceptions,
            faqs=faqs,
            sources=sources,
            raw_content=raw,
        )
        _DOCUMENT_REGISTRY[topic_key] = doc

    # Build topic keywords index
    _TOPIC_INDEX = {
        "escrow_accounts": [
            "escrow", "escrow account", "safe", "money safe", "security", "project funds",
            "developer funds", "cancelled project", "protection", "deposit safe", "guarantee",
            "get my money right", "where does my money go", "is my money protected", "bank account"
        ],
        "dubai_dld_rera": [
            "dld", "rera", "regulation", "authority", "government", "rules", "complaint",
            "licence", "license", "trakheesi", "registration", "who regulates", "legal framework"
        ],
        "freehold_ownership": [
            "freehold", "leasehold", "foreign", "foreigner", "expat", "nationality", "own 100%",
            "ownership", "can i buy", "can foreigners own", "eligible areas", "99 years"
        ],
        "ready_vs_offplan": [
            "offplan", "off-plan", "ready", "under construction", "handover", "completion",
            "difference between ready and offplan", "which is better", "resale vs offplan"
        ],
        "payment_plans": [
            "payment plan", "installment", "instalment", "post handover", "down payment",
            "milestone", "40/60", "50/50", "60/40", "70/30", "1%", "booking deposit", "schedule"
        ],
        "ownership_costs": [
            "cost", "fee", "service charge", "dld fee", "4%", "maintenance", "expenses",
            "commission", "registration fee", "trustee fee", "hidden cost", "extra charges"
        ],
        "buying_from_india": [
            "india", "indian", "lrs", "rbi", "remittance", "inr", "funds from india",
            "nri", "pan", "tax", "can i buy from india", "send money to dubai"
        ],
        "rental_yield_roi": [
            "yield", "roi", "return", "rental income", "capital appreciation", "investment",
            "how much return", "good investment", "dubai rental yield", "gross yield", "net yield"
        ],
        "title_deed_registration": [
            "title deed", "oqood", "registration", "certificate", "ownership proof",
            "registration trustee", "property deed", "when do i get title deed"
        ],
        "developer_due_diligence": [
            "developer", "track record", "emaar", "damac", "sobha", "nakheel", "binghatti",
            "reputation", "delay", "what if developer delays", "reliable developer"
        ],
        "mortgages_financing": [
            "mortgage", "loan", "finance", "bank", "interest", "pre-approval", "downpayment",
            "can expat get mortgage", "non resident mortgage", "loan to value", "ltv"
        ],
        "customer_faq_objections": [
            "golden visa", "residency", "visa", "tax free", "why dubai", "faq", "safety in dubai"
        ],
        "objection_handling": [
            "expensive", "bubble", "crash", "risk", "delay", "not sure", "thinking", "worry",
            "scam", "market crash", "property market high"
        ],
        "property_management_resale": [
            "resale", "selling", "property management", "tenant", "renting out", "ejari",
            "short term rental", "airbnb", "find tenant"
        ],
        "dubai_buying_process": [
            "process", "steps", "procedure", "how to buy", "form f", "mou", "noc", "transfer"
        ],
        "company_facts": [
            "lyka realty", "who are you", "office", "barsha heights", "brokerage", "license number"
        ],
    }

    return _DOCUMENT_REGISTRY


# Specific high-accuracy grounding generators for core topics
ESCROW_GROUNDING_FACTS = """VERIFIED DUBAI ESCROW KNOWLEDGE (Law No. 8 of 2007 & DLD/RERA Framework):
1. WHAT IT IS: Under Dubai Law No. (8) of 2007, every developer selling off-plan property MUST open an independent, project-specific escrow account with an approved financial institution (escrow trustee bank) authorized by the Dubai Land Department (DLD).
2. REGULATORY OVERSIGHT: DLD and its regulatory arm, RERA, govern and audit all escrow accounts. Developer access to the funds is legally restricted and monitored.
3. HOW FUNDS ARE RELEASED: Money is NOT paid upfront to the developer. Disbursements occur strictly in stages linked to certified construction milestones verified by official DLD engineering/technical inspection reports (not older than 3 months). A 5% retention is held for 1 year post-handover for defect liability.
4. IMPORTANT MISCONCEPTION GUARDS:
   - Escrow accounts are NOT ordinary general government bank accounts; they are project-specific commercial trust accounts held by approved licensed banks.
   - Escrow is a regulatory safeguard against fund diversion; it is NOT an absolute commercial guarantee against developer delays or market price fluctuations.
   - Escrow applies to OFF-PLAN development sales. Completed/ready properties are transferred via DLD Registration Trustee with Title Deed and do not use development escrow.
5. CONVERSATIONAL GUIDANCE: Explain the DLD escrow safeguard clearly and concisely. Clarify that funds are ring-fenced per project and released upon certified construction progress. Then ask the customer if they are looking at off-plan or ready property."""

FREEHOLD_GROUNDING_FACTS = """VERIFIED DUBAI FREEHOLD OWNERSHIP KNOWLEDGE (Law No. 7 of 2006):
1. FOREIGN OWNERSHIP: Foreign nationals of any nationality can purchase and own 100% freehold property in designated freehold areas in Dubai (e.g., Dubai Marina, Downtown Dubai, Palm Jumeirah, JVC, Business Bay, Dubai Hills Estate).
2. ABSOLUTE OWNERSHIP: Freehold ownership grants absolute, perpetual ownership of both the unit and the underlying land share, which can be sold, leased, or inherited without time restriction.
3. LEASEHOLD CONTRAST: In non-freehold areas, foreign ownership is limited to leasehold (typically 99 years) rather than absolute freehold ownership.
4. REGISTRATION: All freehold purchases are officially registered with the Dubai Land Department (DLD), issuing an official Title Deed (for ready property) or an Oqood certificate (for off-plan)."""

BUYING_FROM_INDIA_FACTS = """VERIFIED BUYING FROM INDIA (LRS & RBI GUIDELINES):
1. LEGALITY: Indian citizens and NRIs can legally purchase property in Dubai.
2. FUNDS TRANSFER (LRS): Resident Indians can remit funds under RBI's Liberalised Remittance Scheme (LRS), up to USD 250,000 per financial year per individual (family members can pool allowances).
3. NON-RESIDENT INDIANS (NRIs): NRIs earning abroad can invest directly without LRS restrictions using their foreign currency / NRE accounts.
4. TAXATION & ADVICE: Dubai has 0% property tax and 0% capital gains tax. Indian tax implications (such as TCS on LRS remittance or Indian tax disclosures) require consulting an Indian Chartered Accountant / tax advisor."""

OWNERSHIP_COSTS_FACTS = """VERIFIED DUBAI PROPERTY TRANSACTION COSTS:
1. DLD TRANSFER FEE: Exactly 4% of the property purchase price paid to Dubai Land Department (+ AED 580 administrative/knowledge fee).
2. DLD REGISTRATION TRUSTEE FEE: AED 4,000 (+ VAT) for properties >= AED 500k; AED 2,000 (+ VAT) for properties < AED 500k.
3. BROKERAGE COMMISSION: Standard 2% (+ VAT) of property value for resale transactions (off-plan purchases directly from developers usually incur 0% buyer commission).
4. ONGOING COSTS: Annual service charges / maintenance fees per square foot set according to the DLD RERA Service Charge Index."""

RENTAL_YIELD_ROI_FACTS = """VERIFIED DUBAI RENTAL YIELDS & ROI:
1. MARKET YIELDS: Dubai offers attractive gross rental yields typically ranging between 6% to 9% depending on location, property type, and short-term vs long-term leasing (e.g. JVC, Business Bay, Dubai Marina).
2. NO GUARANTEED RETURNS: Never guarantee fixed capital appreciation or guaranteed returns. Yields depend on market occupancy, tenant demand, and annual service charges.
3. TAX BENEFIT: Rental income in Dubai is free of local income tax for individual property investors."""


def retrieve_relevant_knowledge(query: str, max_chars: int = 1400) -> str:
    """Retrieve relevant domain knowledge sections based on query intent and keywords.
    
    Returns structured excerpts with regulatory grounding, verified facts,
    and misconception safeguards.
    """
    if not query or not query.strip():
        return ""

    q_lower = query.lower().strip()
    load_knowledge_registry()

    # 1. Exact high-priority domain pattern matchers
    if any(k in q_lower for k in ["escrow", "safe", "money safe", "get my money right", "protect my money", "cancelled project"]):
        return f"--- KNOWLEDGE: ESCROW ACCOUNTS (DLD / RERA LAW NO. 8 OF 2007) ---\n{ESCROW_GROUNDING_FACTS}"

    if any(k in q_lower for k in ["freehold", "leasehold", "can foreigner", "foreign ownership", "own 100%"]):
        return f"--- KNOWLEDGE: FREEHOLD OWNERSHIP (LAW NO. 7 OF 2006) ---\n{FREEHOLD_GROUNDING_FACTS}"

    if any(k in q_lower for k in ["india", "indian", "lrs", "rbi", "remit", "inr", "from india"]):
        return f"--- KNOWLEDGE: BUYING FROM INDIA (LRS & RBI) ---\n{BUYING_FROM_INDIA_FACTS}"

    if any(k in q_lower for k in ["service charge", "dld fee", "4%", "extra cost", "hidden fee", "transaction fee"]):
        return f"--- KNOWLEDGE: OWNERSHIP COSTS & DLD FEES ---\n{OWNERSHIP_COSTS_FACTS}"

    if any(k in q_lower for k in ["roi", "yield", "rental return", "rental income", "how much return"]):
        return f"--- KNOWLEDGE: RENTAL YIELD & ROI ---\n{RENTAL_YIELD_ROI_FACTS}"

    # 2. General topic keyword scoring across registry
    scores: List[Tuple[int, str]] = []
    for topic_key, keywords in _TOPIC_INDEX.items():
        score = sum(1 for kw in keywords if kw in q_lower)
        if score > 0:
            scores.append((score, topic_key))

    scores.sort(key=lambda x: x[0], reverse=True)
    if not scores:
        return ""

    excerpts: List[str] = []
    total_len = 0

    for score, topic_key in scores[:2]:
        doc = _DOCUMENT_REGISTRY.get(topic_key)
        if not doc:
            continue

        lines = [f"--- KNOWLEDGE: {doc.title.upper()} (Source: {doc.filename}) ---"]
        if doc.authorities:
            lines.append(f"Regulatory Authorities: {', '.join(doc.authorities)}")

        if doc.verified_facts:
            lines.append("Verified Facts:")
            for fact in doc.verified_facts[:4]:
                lines.append(f"  * {fact}")

        if doc.misconceptions:
            lines.append("Misconception & Safety Limits:")
            for misc in doc.misconceptions[:3]:
                lines.append(f"  * {misc}")

        if not doc.verified_facts and not doc.misconceptions:
            # Fall back to cleaned summary
            lines.append(doc.summary_en[:500])

        block = "\n".join(lines).strip()
        excerpts.append(block)
        total_len += len(block)
        if total_len >= max_chars:
            break

    return "\n\n".join(excerpts)


def format_escrow_explanation(lang_style: str = "en") -> str:
    """Return the authoritative, verified escrow explanation in the requested language."""
    if lang_style in ("ta", "ta-Latn", "tanglish"):
        return (
            "Yes nga! Dubai-la off-plan projects-ku DLD Law No. (8) of 2007 padi escrow account compulsory. "
            "Unga money developer direct-ah eduka mudiyadhu — DLD approved trustee bank-la safe-ah irukkum. "
            "DLD technical inspection paathu, construction progress aaga aaga dhaan funds release pannuvanga. "
            "Idhu oru strong safeguard for buyers. Aana idhu market price guarantee illa. "
            "Neenga off-plan property paakkureengala, illa ready property-ah?"
        )
    return (
        "Yes, the escrow arrangement in Dubai is a regulated safeguard designed to protect buyers of off-plan properties. "
        "Under DLD Law No. (8) of 2007, your installment payments are deposited into a project-specific escrow account held at an approved bank, "
        "not paid directly to the developer or into an ordinary government account. "
        "Funds are released to the developer in stages strictly against certified construction milestones verified by DLD technical audit reports. "
        "While it safeguards project funds from being diverted, it does not guarantee against market risk or project delays. "
        "Are you currently considering an off-plan development or a ready property?"
    )
