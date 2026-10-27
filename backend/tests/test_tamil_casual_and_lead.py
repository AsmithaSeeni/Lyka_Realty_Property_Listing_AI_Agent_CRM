"""Tests for casual Tamil conversational requests, contact/phone extraction, and lead capture."""
import pytest
from app.ai.agent import AIRealEstateAgent, ConversationState


def test_casual_tamil_detection_requests():
    agent = AIRealEstateAgent()
    assert agent.detect_language_request("can you speak in casual tamil?") == "ta"
    assert agent.detect_language_request("tamil la pesunga please") == "ta"
    assert agent.detect_language_request("tamil la chat pannu") == "ta"
    assert agent.detect_language_request("தமிழில் பேசவும்") == "ta"
    assert agent.detect_language_request("casual tamil please") == "ta"


def test_tanglish_detection_requests():
    agent = AIRealEstateAgent()
    assert agent.detect_language_request("speak in Tanglish please") == "ta-Latn"
    assert agent.detect_language_request("tanglish la pesunga") == "ta-Latn"
    assert agent.detect_language_request("casual tanglish") == "ta-Latn"


def test_tamil_name_extraction():
    agent = AIRealEstateAgent()
    agent._extract_requirements("En per Priya. 2 BHK apartment theduren.")
    assert agent.state.contact["name"] == "Priya"

    agent2 = AIRealEstateAgent()
    agent2._extract_requirements("En peyar Karthik, Dubai Marina-la flat venum.")
    assert agent2.state.contact["name"] == "Karthik"

    agent3 = AIRealEstateAgent()
    agent3._extract_requirements("என் பெயர் சுரேஷ். துபாயில் வீடு வேண்டும்.")
    assert agent3.state.contact["name"] == "சுரேஷ்"


def test_phone_extraction_uae_and_india():
    agent = AIRealEstateAgent()
    agent._extract_requirements("My number is +971 50 123 4567")
    assert "971501234567" in agent.state.contact["phone"].replace("+", "")

    agent2 = AIRealEstateAgent()
    agent2._extract_requirements("En number 9876543210")
    assert agent2.state.contact["phone"] == "9876543210"

    agent3 = AIRealEstateAgent()
    agent3._extract_requirements("reach me at +91 9840123456 or test@example.com")
    assert "919840123456" in agent3.state.contact["phone"].replace("+", "")
    assert agent3.state.contact["email"] == "test@example.com"


def test_lead_collection_trigger_with_contact_and_preferences():
    agent = AIRealEstateAgent()
    agent._extract_requirements("En per Anitha, phone 9840112233. Dubai Marina-la 2 BHK buy panna poren.")
    assert agent._should_collect_lead() is True
    lead = agent.get_lead_data()
    assert lead["name"] == "Anitha"
    assert lead["phone"] == "9840112233"
    assert lead["location"] == "Dubai Marina"
    assert lead["bedrooms"] == 2
    assert lead["buy_rent"] == "buy"


def test_customer_preferences_and_amenities_extraction():
    agent = AIRealEstateAgent()
    agent._extract_requirements(
        "Dubai Marina-la sea view venum, metro kitta irukkanum, balcony and swimming pool kooda irundha nalla irukkum."
    )
    prefs = agent.state.requirements.get("preferences") or []
    assert "sea_view" in prefs
    assert "near_metro" in prefs
    assert "balcony" in prefs
    assert "pool" in prefs

    lead = agent.get_lead_data()
    assert "sea_view" in lead["amenities"]
    assert "near_metro" in lead["amenities"]
    assert "Preferences:" in lead["notes"]


def test_tanglish_fallback_and_recovery_has_no_tamil_script_unicode():
    agent = AIRealEstateAgent()
    agent.state.reply_language = "ta-Latn"
    # Test recovery when no cards
    recovery_empty = agent._tamil_recovery([])
    assert any(c in recovery_empty for c in ("Vanakkam", "Dubai", "LykAI"))
    assert sum(1 for c in recovery_empty if "\u0B80" <= c <= "\u0BFF") == 0

    # Test recovery with cards
    sample_cards = [{"price": "1500000"}, {"price": "2000000"}]
    recovery_cards = agent._tamil_recovery(sample_cards)
    assert "properties kidaichirukku" in recovery_cards
    assert sum(1 for c in recovery_cards if "\u0B80" <= c <= "\u0BFF") == 0

