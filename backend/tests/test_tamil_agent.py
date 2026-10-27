"""Tamil-chat upgrade (2026-10): model routing + explicit language switching.

Context - real measurements, not assumptions:
- A customer screenshot showed the 30B lightning model answering
  "Could you talk in Tamil?" with code-mixed English + Tamil-script mush.
- Probing the account's own NVIDIA key (80 catalog models): only
  nvidia/nemotron-3-super-120b-a12b answered with committed natural Tamil
  (11.2s, thinking OFF). The SAME model with thinking ON returned EMPTY
  content after 46.6s of reasoning, so thinking stays on the base model.
  Other catalog models 404'd for this account or timed out 60-120s.
- An explicit language request previously lost to the message's own
  language (the English question "Could you talk in Tamil?" was answered
  in English).

Guards pinned here:
- ta/ta-Latn/mixed payload -> Tamil model, thinking OFF, max_tokens 800
- en/auto payload -> base model, original thinking contract unchanged
- NVIDIA_MODEL_TAMIL env override (blank -> default)
- explicit requests detected; near-misses must NOT flip the language
- respond() pins reply_language on request, it persists across English
  typed follow-ups, a customer writing Tamil switches immediately, and
  state round-trips survive (all provider calls stubbed - zero live calls)
"""

import pytest

import app.ai.agent as agent_module
from app.ai.agent import AIRealEstateAgent, ConversationState
from app.ai.nvidia_client import NVIDIAClient, TAMIL_MODEL_DEFAULT


# ------------------------------------------------------------ model routing

def test_tamil_turns_route_to_stronger_model_thinking_off():
    c = NVIDIAClient()
    assert c.model_tamil == TAMIL_MODEL_DEFAULT
    for lang in ("ta", "ta-Latn", "mixed"):
        p = c._build_payload("SYS", "hi", None, language=lang)
        assert p["model"] == TAMIL_MODEL_DEFAULT
        assert p["max_tokens"] == 800
        assert p["chat_template_kwargs"] == {"enable_thinking": False}
        assert p["temperature"] == 0.7


def test_english_and_unknown_language_keep_base_model_contract():
    c = NVIDIAClient()
    en = c._build_payload("SYS", "hello", None, language="en")
    assert en["model"] == c.model
    assert en["max_tokens"] == 800
    assert en["chat_template_kwargs"] == {"enable_thinking": False}

    # Unknown language keeps the base model's original thinking contract.
    auto = c._build_payload("SYS", "hello", None, language="auto")
    assert auto["model"] == c.model
    assert auto["max_tokens"] == 4000
    assert auto["chat_template_kwargs"] == {"enable_thinking": True}


def test_base_and_tamil_models_are_distinct_by_default():
    c = NVIDIAClient()
    assert c.model != c.model_tamil


def test_tamil_model_env_override_and_blank_fallback(monkeypatch):
    monkeypatch.setenv("NVIDIA_MODEL_TAMIL", "unit/tamil-model")
    assert NVIDIAClient().model_tamil == "unit/tamil-model"
    monkeypatch.setenv("NVIDIA_MODEL_TAMIL", "")
    assert NVIDIAClient().model_tamil == TAMIL_MODEL_DEFAULT


# ------------------------------------------------- explicit language requests

@pytest.mark.parametrize(
    "message, expected",
    [
        # the reported scenario, verbatim
        ("Hello, are you there? Could you talk in Tamil?", "ta"),
        ("please speak in Tamil", "ta"),
        ("reply in tamil", "ta"),
        ("Can you speak Tamil?", "ta"),
        ("Tamil la pesunga", "ta"),
        ("tamil la pesu", "ta"),
        ("தமிழில் பேசுங்க", "ta"),
        ("தமிழ் பேசு", "ta"),
        ("respond in English please", "en"),
        ("say it in english", "en"),
        # near-misses that must NOT flip the reply language
        ("show me apartments in Dubai Marina", None),
        ("Is Tamil spoken in Dubai?", None),
        ("I want a villa, budget 2 million", None),
        ("what does the English summary say?", None),
        ("I am looking for a2 BHK", None),
    ],
)
def test_detect_language_request(message, expected):
    assert AIRealEstateAgent.detect_language_request(message) == expected


# --------------------------------------------------------- respond() wiring

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
        return canned.get(language, "Sure - tell me more about what you need.")

    monkeypatch.setattr(agent_module.nvidia_client, "chat_sync", fake_chat_sync)
    return AIRealEstateAgent(), calls


def test_explicit_request_pins_reply_language(agent_and_chat):
    agent, calls = agent_and_chat
    agent.respond("Hello, are you there? Could you talk in Tamil?")
    assert agent.state.reply_language == "ta"
    assert calls == ["ta"]


def test_request_persists_across_english_typed_followups(agent_and_chat):
    """The whole point of the report: after "talk in Tamil", the next
    English-typed question must NOT snap back to English."""
    agent, calls = agent_and_chat
    agent.respond("Could you talk in Tamil?")
    agent.respond("How much for a 2 BHK in Dubai Marina?")
    agent.respond("And is parking included?")
    assert calls == ["ta", "ta", "ta"]


def test_writing_in_another_language_switches_immediately(agent_and_chat):
    """Natural switching still wins over a standing request."""
    agent, calls = agent_and_chat
    agent.respond("reply in English please")
    assert calls == ["en"]
    agent.respond("இந்த வீட்டின் விலை எவ்வளவு?")
    assert calls[-1] == "ta"
    # ...and typing English again returns to the standing "en" request
    agent.respond("okay, thanks")
    assert calls[-1] == "en"


def test_new_explicit_request_replaces_standing_one(agent_and_chat):
    agent, calls = agent_and_chat
    agent.respond("talk in Tamil")
    agent.respond("reply in English now")
    agent.respond("okay sure")  # English-typed; standing request now "en"
    assert calls == ["ta", "en", "en"]


def test_plain_conversation_unaffected_without_requests(agent_and_chat):
    agent, calls = agent_and_chat
    agent.respond("show me apartments in Dubai")
    agent.respond("budget is 2 million")
    assert calls == ["en", "en"]
    assert agent.state.language_request == ""
    assert agent.state.reply_language == "en"


# ------------------------------------------------------------ state plumbing

def test_language_request_survives_state_round_trip():
    state = ConversationState(conversation_id=7)
    state.language_request = "ta"
    state.reply_language = "ta"
    restored = ConversationState.from_dict(state.to_dict())
    assert restored.language_request == "ta"
    assert restored.reply_language == "ta"


def test_old_persisted_state_without_language_request_is_compatible():
    """States saved before this feature must restore with no request set."""
    restored = ConversationState.from_dict(
        {"conversation_id": 3, "reply_language": "en", "messages": []}
    )
    assert restored.language_request == ""
    assert restored.reply_language == "en"
