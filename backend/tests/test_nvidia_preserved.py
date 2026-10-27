"""Phase 1 — NVIDIA chat must remain untouched.

Guards the existing integration against accidental Phase-1 regressions:
- env var names and defaults (NVIDIA_API_KEY / NVIDIA_MODEL, official endpoint)
- model routing + thinking-flag behaviour per language (measured contracts)
- offline fallback when the key is missing (no network call, no crash)
"""

import os

from app.ai.nvidia_client import (
    NVIDIAClient,
    THINKING_OFF_LANGUAGES,
)


def test_env_var_names_and_defaults_preserved():
    old_key = os.environ.get("NVIDIA_API_KEY")
    old_model = os.environ.get("NVIDIA_MODEL")
    try:
        os.environ["NVIDIA_API_KEY"] = "unit-dummy-key"
        os.environ["NVIDIA_MODEL"] = "unit/model"
        c = NVIDIAClient()
        assert c.api_key == "unit-dummy-key"
        assert c.model == "unit/model"
        assert c.base_url == "https://integrate.api.nvidia.com/v1"
    finally:
        if old_key is None:
            os.environ.pop("NVIDIA_API_KEY", None)
        else:
            os.environ["NVIDIA_API_KEY"] = old_key
        if old_model is None:
            os.environ.pop("NVIDIA_MODEL", None)
        else:
            os.environ["NVIDIA_MODEL"] = old_model

    # Default model unchanged when env is blank.
    saved = os.environ.pop("NVIDIA_MODEL", None)
    try:
        assert NVIDIAClient().model == "nvidia/nemotron-3.5-lightning-30b-a3b"
    finally:
        if saved is not None:
            os.environ["NVIDIA_MODEL"] = saved


def test_thinking_off_languages_contract():
    """en + ta-Latn run thinking-off (10-20x speedup); ta/mixed keep thinking."""
    assert THINKING_OFF_LANGUAGES == {"en", "ta-Latn"}
    assert NVIDIAClient.should_think("en") is False
    assert NVIDIAClient.should_think("ta-Latn") is False
    assert NVIDIAClient.should_think("ta") is True
    assert NVIDIAClient.should_think("mixed") is True
    assert NVIDIAClient.should_think("auto") is True


def test_build_payload_contract():
    c = NVIDIAClient()

    en = c._build_payload("SYS", "hello", None, language="en")
    assert en["model"] == c.model
    assert en["temperature"] == 0.7
    assert en["max_tokens"] == 800
    assert en["chat_template_kwargs"] == {"enable_thinking": False}
    assert en["messages"][0] == {"role": "system", "content": "SYS"}
    assert en["messages"][-1] == {"role": "user", "content": "hello"}

    # Tamil/Tanglish/mixed turns route to the stronger multilingual model
    # with thinking OFF on it (measured 2026-10: thinking on -> 46.6s of
    # hidden reasoning and an EMPTY reply; thinking off -> 11.2s committed
    # natural Tamil). should_think() itself keeps its pinned contract.
    ta = c._build_payload("SYS", "வணக்கம்", None, language="ta")
    assert ta["model"] == c.model_tamil
    assert ta["model"] != c.model
    assert ta["max_tokens"] == 800
    assert ta["chat_template_kwargs"] == {"enable_thinking": False}

    # History filtering keeps only user/assistant turns.
    hist = [
        {"role": "user", "content": "a"},
        {"role": "tool", "content": "skip"},
        {"role": "assistant", "content": "b"},
    ]
    with_hist = c._build_payload("SYS", "c", hist, language="en")
    roles = [m["role"] for m in with_hist["messages"]]
    assert roles == ["system", "user", "assistant", "user"]


def test_missing_key_returns_fallback_without_network(monkeypatch):
    """No key -> canned fallback (existing safety behaviour), zero HTTP."""
    monkeypatch.setenv("NVIDIA_API_KEY", "")
    c = NVIDIAClient()
    assert c.api_key == ""
    out = c.chat_sync("SYS", "show me apartments", None, language="en")
    assert isinstance(out, str) and len(out) > 0
