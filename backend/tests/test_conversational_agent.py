"""Tests for conversational agent flow, natural English dialogue,
contextual preference retention, preference updates, and honest recommendations.
"""

import pytest
from app.ai.agent import AIRealEstateAgent
import app.ai.agent as agent_module


def test_first_greeting_opener_natural_english(monkeypatch):
    """Customer says 'Hi' -> agent answers naturally without robotic opening."""
    def fake_llm(system_prompt, user_message, conversation_history=None, language="auto"):
        return "Hey! Looking for a property in Dubai?"

    monkeypatch.setattr(agent_module.nvidia_client, "chat_sync", fake_llm)
    agent = AIRealEstateAgent()
    res = agent.respond("Hi")
    reply = res["response"]

    # Natural, concise English
    assert "Welcome to Lyka Realty AI Assistant" not in reply
    assert reply.count("?") == 1
    assert "Looking for a property in Dubai?" in reply


def test_first_turn_fallback_question_asks_dubai_property_when_no_criteria(monkeypatch):
    """If provider returns a plain greeting with no question, fallback asks if looking for property in Dubai."""
    def fake_llm(system_prompt, user_message, conversation_history=None, language="auto"):
        return "Hey there!"

    monkeypatch.setattr(agent_module.nvidia_client, "chat_sync", fake_llm)
    agent = AIRealEstateAgent()
    res = agent.respond("Hello")
    reply = res["response"]
    assert reply.count("?") == 1
    assert "Looking for a property in Dubai?" in reply


def test_contextual_multi_turn_retention_and_no_repeated_questions(monkeypatch):
    """Preferences stated across turns are retained and not re-asked."""
    def fake_llm(system_prompt, user_message, conversation_history=None, language="auto"):
        # Context block must contain gathered requirements
        assert "Requirements gathered so far:" in system_prompt
        assert "- location: Dubai Marina" in system_prompt
        assert "- property type: villa" in system_prompt
        return "Got it — a villa in Dubai Marina, around AED 2 million. Let me check the matching property data."

    agent = AIRealEstateAgent()
    # Turn 1: customer specifies villa in Dubai Marina
    agent.respond("I want a villa in Dubai Marina.")
    assert agent.state.requirements["property_type"] == "villa"
    assert agent.state.requirements["location"] == "Dubai Marina"

    # Turn 2: customer specifies budget
    monkeypatch.setattr(agent_module.nvidia_client, "chat_sync", fake_llm)
    res = agent.respond("Around AED 2 million.")
    assert agent.state.requirements["budget"] == 2000000
    assert agent.state.requirements["location"] == "Dubai Marina"
    assert agent.state.requirements["property_type"] == "villa"
    assert "villa in Dubai Marina" in res["response"]


def test_customer_preference_change_updates_requirements():
    """If customer explicitly updates or changes preference, requirements update."""
    agent = AIRealEstateAgent()
    agent.respond("I want a villa in Dubai Marina, budget 2 million.")
    assert agent.state.requirements["property_type"] == "villa"
    assert agent.state.requirements["location"] == "Dubai Marina"
    assert agent.state.requirements["budget"] == 2000000

    # Customer changes their mind
    agent.respond("Actually my budget is 3 million and I prefer an apartment instead in Downtown Dubai.")
    assert agent.state.requirements["budget"] == 3000000
    assert agent.state.requirements["property_type"] == "apartment"
    assert agent.state.requirements["location"] == "Downtown Dubai"


def test_programmatic_update_requirement():
    """update_requirement directly modifies the requirement key."""
    agent = AIRealEstateAgent()
    agent.update_requirement("budget", 2500000)
    assert agent.state.requirements["budget"] == 2500000
    agent.update_requirement("budget", 4000000)
    assert agent.state.requirements["budget"] == 4000000


def test_direct_question_answered_without_lead_forcing(monkeypatch):
    """Customer asking an area question receives direct answer without robotic lead forcing."""
    def fake_llm(system_prompt, user_message, conversation_history=None, language="auto"):
        return "Dubai Marina is a vibrant waterfront community close to JBR Beach and metro stations. What type of home are you considering there?"

    monkeypatch.setattr(agent_module.nvidia_client, "chat_sync", fake_llm)
    agent = AIRealEstateAgent()
    res = agent.respond("Is Dubai Marina close to the beach and metro?")
    reply = res["response"]
    assert "Dubai Marina" in reply
    assert "waterfront community" in reply
    # Did not prematurely trigger lead collection
    assert res.get("action") != "collect_lead"


def test_lead_saving_when_contact_info_provided():
    """Contact details are stored and packaged for lead follow-up."""
    agent = AIRealEstateAgent()
    agent.respond("I am looking for a 2 bedroom apartment in JVC under AED 1.2 million.")
    agent.respond("My name is Tariq, email is tariq@example.com and phone is +971501234567.")

    lead_data = agent.get_lead_data()
    assert lead_data["name"] == "Tariq"
    assert lead_data["email"] == "tariq@example.com"
    assert lead_data["phone"] == "+971501234567"
    assert lead_data["property_type"] == "apartment"
    assert lead_data["location"] == "Jvc"
    assert lead_data["bedrooms"] == 2
    assert "1,200,000" in str(lead_data["budget"])
