import os
import re
import logging
from typing import Optional, Dict, Any, List

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Persistent keep-alive pool: opening a fresh TLS connection per message
# added hundreds of ms to every LLM call for no reason.
_CLIENT: Optional[httpx.Client] = None

# Reply languages whose short answers do not benefit from the model's hidden
# reasoning pass. Measured on the BASE model (2026-10): with thinking enabled
# a 2-sentence reply took 18-74s (600-5000 hidden reasoning tokens); with it
# disabled English/Tanglish replies took 1.4-7.4s at equal quality. This set
# is the BASE-model contract only: Tamil-script/Tanglish/mixed turns are
# routed to NVIDIA_MODEL_TAMIL (same key/endpoint), which runs thinking OFF -
# measured 2026-10: thinking on -> 46.6s of reasoning and an EMPTY reply;
# thinking off -> 11.2s committed natural Tamil.
THINKING_OFF_LANGUAGES = {"en", "ta-Latn"}

# Reply languages answered by the stronger multilingual Tamil model.
TAMIL_MODEL_LANGUAGES = {"ta", "ta-Latn", "mixed"}

# Default model for those turns (env-overridable via NVIDIA_MODEL_TAMIL).
TAMIL_MODEL_DEFAULT = "nvidia/nemotron-3-super-120b-a12b"


def _get_client() -> httpx.Client:
    """Shared HTTP client (module-level, lazily created, thread-tolerant)."""
    global _CLIENT
    if _CLIENT is None or _CLIENT.is_closed:
        # Serverless-safe bounds: vercel.json caps the backend function at 30s
        # (maxDuration), so a 25s read keeps the worst case (one non-retried
        # read timeout, or a fast 5xx plus its single retry) inside the
        # function budget — customers get the honest fallback instead of a
        # killed invocation. Connect stays short because connect errors ARE
        # retried once, and two connect timeouts (2x8s) also fit the budget.
        _CLIENT = httpx.Client(
            timeout=httpx.Timeout(25.0, connect=8.0),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )
    return _CLIENT


class NVIDIAClient:
    """Client for NVIDIA LLM API - the AI brain of the real estate agent.

    Uses synchronous HTTP calls so it can be safely called from FastAPI
    endpoints (which run sync handlers in a threadpool).
    """

    def __init__(self):
        self.api_key = os.getenv("NVIDIA_API_KEY", "")
        self.model = os.getenv("NVIDIA_MODEL", "nvidia/nemotron-3.5-lightning-30b-a3b")
        # Blank env must fall back to the default (mirrors config._env).
        self.model_tamil = (
            os.getenv("NVIDIA_MODEL_TAMIL", "").strip() or TAMIL_MODEL_DEFAULT
        )
        self.base_url = "https://integrate.api.nvidia.com/v1"

    # ------------------------------------------------------------------
    # Payload construction (kept separate so it is unit-testable)
    # ------------------------------------------------------------------
    @staticmethod
    def should_think(language: str) -> bool:
        """Whether this reply language needs the model's reasoning pass."""
        return language not in THINKING_OFF_LANGUAGES

    def _select_model(self, language: str):
        """(model_id, thinking) for this reply language.

        Tamil-script/Tanglish/mixed turns use the stronger multilingual model
        (identical API key, endpoint and payload shape - only the model id
        changes). That model is a NON-reasoning route: with
        chat_template_kwargs.enable_thinking=true it spent 46.6s on hidden
        reasoning and returned EMPTY content (measured 2026-10), so thinking
        stays a property of the base model only.
        """
        if language in TAMIL_MODEL_LANGUAGES and self.model_tamil:
            return self.model_tamil, False
        return self.model, self.should_think(language)

    def _build_payload(
        self,
        system_prompt: str,
        user_message: str,
        conversation_history: Optional[List[Dict]] = None,
        language: str = "auto",
    ) -> Dict[str, Any]:
        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        if conversation_history:
            for msg in conversation_history:
                role = msg.get("role", "user")
                content = msg.get("content", "")
                if role in ("user", "assistant"):
                    messages.append({"role": role, "content": content})

        messages.append({"role": "user", "content": user_message})

        model, thinking = self._select_model(language)
        return {
            "model": model,
            "messages": messages,
            "temperature": 0.7,
            # Reasoning tokens count against max_tokens: keep the generous cap
            # for thinking replies; short conversational replies never need it.
            "max_tokens": 4000 if thinking else 800,
            # Measured 10-20x speedup for English/Tanglish (18-74s -> 1.4-7.4s).
            "chat_template_kwargs": {"enable_thinking": thinking},
        }

    def chat_sync(
        self,
        system_prompt: str,
        user_message: str,
        conversation_history: Optional[List[Dict]] = None,
        language: str = "auto",
    ) -> str:
        """
        Send a chat message to the NVIDIA LLM and get a synchronous response.
        The system prompt defines the agent's personality and constraints.

        `language` is the language the reply must be written in ("en",
        "ta", "ta-Latn", "mixed", "auto") - it selects the model (the
        stronger multilingual model for ta/ta-Latn/mixed) and whether the
        reasoning pass is enabled for this call.
        """
        if not self.api_key:
            logger.warning("NVIDIA API key not configured")
            return self._fallback_response(user_message, language)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = self._build_payload(
            system_prompt, user_message, conversation_history, language
        )
        thinking = payload["chat_template_kwargs"]["enable_thinking"]  # as sent
        url = f"{self.base_url}/chat/completions"

        import time as _time

        # One safe retry: only for fast-failing conditions (connection refused
        # / dropped, 5xx). Read timeouts are NOT retried (they are slow and
        # the caller has a fallback), so worst-case latency stays bounded.
        last_error: Optional[Exception] = None
        for attempt in (1, 2):
            started = _time.perf_counter()
            try:
                response = _get_client().post(url, headers=headers, json=payload)
                if response.status_code >= 500 and attempt == 1:
                    logger.warning(
                        "NVIDIA API %d on attempt %d - retrying",
                        response.status_code, attempt,
                    )
                    last_error = None
                    continue
                response.raise_for_status()
                data = response.json()
                choice = data.get("choices", [{}])[0]
                content = choice.get("message", {}).get("content", "")
                cleaned = self._clean_response(content)
                # If the model hit the token cap mid-sentence, tidy the tail
                if choice.get("finish_reason") == "length":
                    cleaned = self._trim_incomplete_tail(cleaned)
                # Phase 10: a blank/whitespace-only reply is a provider
                # failure, not an answer. Customers get the canned fallback —
                # never an empty bubble (which downstream could turn into a
                # bare appended question). Successful replies are untouched.
                if not cleaned or not cleaned.strip():
                    logger.warning(
                        "NVIDIA returned an empty reply - using fallback"
                    )
                    return self._fallback_response(user_message, language)
                logger.info(
                    "NVIDIA chat done in %.2fs (attempt %d, thinking=%s, "
                    "lang=%s, prompt_chars=%d, reply_chars=%d)",
                    _time.perf_counter() - started, attempt, thinking,
                    language, len(payload["messages"][-1]["content"]),
                    len(cleaned or ""),
                )
                return cleaned
            except httpx.HTTPStatusError as e:
                # 5xx already retried above; everything else is final
                logger.error(
                    "NVIDIA API HTTP error: %s - %s",
                    e.response.status_code, e.response.text[:500],
                )
                return self._fallback_response(user_message, language)
            except (httpx.ConnectError, httpx.ConnectTimeout) as e:
                last_error = e
                if attempt == 1:
                    logger.warning("NVIDIA connect error - retrying: %s", e)
                    continue
                logger.error("NVIDIA API unreachable: %s", e)
                return self._fallback_response(user_message, language)
            except Exception as e:
                logger.error("NVIDIA API error: %s", e)
                return self._fallback_response(user_message, language)
        # Defensive: never reached in practice
        logger.error("NVIDIA API failed after retries: %s", last_error)
        return self._fallback_response(user_message, language)

    def _clean_response(self, content: str) -> str:
        """Strip model thinking/reasoning preamble so customers only see
        the actual conversational reply."""
        if not content:
            return content
        text = content.strip()

        # Common thinking preambles used by reasoning models
        preamble_patterns = [
            r"^\s*(?:sure|ok(?:ay)?)[,!\s]*(?:here(?:'s| is)\s+)?(?:the\s+)?"
            r"(?:thinking process|reasoning|analysis)\b[:\-]?\s*",
            r"^\s*(?:here(?:'s| is)\s+(?:a\s+)?)?(?:thinking process|"
            r"chain of thought|reasoning|analysis)\b[:\-]?\s*",
            r"^\s*#+\s*(?:thinking|reasoning|analysis)\b[:\-]?\s*",
        ]
        for pat in preamble_patterns:
            m = re.match(pat, text, re.IGNORECASE)
            if m:
                text = text[m.end():].strip()

        # Markers must match the CURRENT text: the preamble strip above shifts
        # offsets, and using a stale copy would slice at the wrong index.
        lower = text.lower()

        # If a "final answer" marker exists, cut everything before it
        final_markers = [
            "**final answer**", "final response:", "**response:**",
            "assistant:", "reply:",
        ]
        marker_cut = False
        for marker in final_markers:
            idx = lower.find(marker)
            if idx != -1:
                text = text[idx + len(marker):].strip()
                marker_cut = True
                break
        # `reply: "..."` artifacts: after a marker cut the model's own
        # quotation marks can wrap the whole answer - unwrap them (the
        # content stays).
        if marker_cut and text.startswith('"'):
            m = re.match(r'^"([^"\n]+)"(.*)$', text, re.S)
            text = ((m.group(1) + m.group(2)) if m else text[1:]).lstrip()

        # Drop a leading numbered/step analysis block, e.g.
        # "1. **Analyze User Input:** ..." followed by a blank line and the reply
        if re.match(r"^\s*\d+\.\s+\*\*", text):
            paras = re.split(r"\n\s*\n", text)
            if len(paras) > 1:
                # Keep everything from the first paragraph that does NOT
                # look like numbered analysis, so no reply content is lost
                for i, para in enumerate(paras):
                    if not re.match(r"^\s*(\d+\.\s+\*\*|\*\*Step|Step \d)", para.strip()):
                        text = "\n\n".join(paras[i:]).strip()
                        break

        # With reasoning disabled the model sometimes writes meta-notes in
        # parentheses ("(the person's name is not provided in the message, so
        # I'll just respond naturally)"). Drop such internal asides.
        text = re.sub(
            r"\(\s*[^()]{0,400}?"
            r"(?:respond naturally|not provided in the message|"
            r"no context|don't have (?:the|any) (?:name|context)|"
            r"internal (?:note|instruction)|no information provided)"
            r"[^()]{0,400}?\)",
            "",
            text,
            flags=re.IGNORECASE,
        )

        # If the model echoes internal context lines (observed once with the
        # reasoning pass disabled), strip them - customers must never see
        # prompt scaffolding.
        text = re.sub(
            r"Tamil - write the ENTIRE reply in natural, simple Tamil script"
            r"[^.]*\.(?:\s*Never[^.]*\.)*(?:\s*do not translate property names\.)?",
            "",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(r"REPLY LANGUAGE:\s*[A-Za-z -]+[^\n]*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"CONTEXT \(internal[^\n]*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\[internal[^\]]*\]", "", text, flags=re.IGNORECASE)
        # Final-turn internal directives echoed WITHOUT their brackets
        # (observed with thinking off: the reply ended "...specific one?
        # Reply in Tanglish."). Strip each known directive phrase to end of
        # line - the surrounding customer-facing content stays intact.
        for pat in (
            r"\s*Write the ENTIRE reply in [A-Za-z() ,\-]+\.?",
            r"\s*Reply in Tanglish[^\n]*",
            r"\s*Reply ENTIRELY in Tamil script\.?",
            r"\s*Match the customer's Tamil-English mix\.?",
            r"\s*Sollunga, budget evlo[^\n]*",
            r"\s*your reply THIS turn has \d+ fresh property cards attached[^\n]*",
            r"\s*FIRST sentence must announce them[^\n]*",
            r"\s*Quote prices only from the figures in this prompt[^\n]*",
            r"\s*THIS turn is about the focus listing[^\n]*",
            r"\s*at most one question\]?",
        ):
            text = re.sub(pat, "", text, flags=re.IGNORECASE)

        # A trailing self-note about the reply itself (observed live: the
        # answer ended "...specific property?\n\nBut we need to ensure it's
        # natural Tamil."). Model self-talk must never reach the customer.
        noteless = re.sub(
            r"\n\s*(?:But|So|Now|Also|And)?\s*(?:we|I)\s+"
            r"(?:need to|should|must|have to|will)?\s*"
            r"(?:ensure|make sure|rewrite|translate|rephrase|be careful)\b"
            r"[^.!?\n]{0,200}[.!?]\s*$",
            "",
            text,
            flags=re.IGNORECASE,
        )
        if noteless.strip():
            text = noteless

        text = re.sub(r"\n{3,}", "\n\n", text).strip()

        return text if text.strip() else content

    def _trim_incomplete_tail(self, text: str) -> str:
        """Remove a trailing incomplete sentence/markdown fragment caused by
        hitting the max token cap."""
        if not text:
            return text
        # Drop unbalanced trailing markdown emphasis (**, *, _, `)
        stripped = text.rstrip()
        for token in ("**", "*", "_", "`"):
            if stripped.endswith(token) and not stripped.endswith(token * 2):
                stripped = stripped[: -len(token)].rstrip()
            # count trailing tokens; drop if odd (unbalanced)
            tail = len(stripped) - len(stripped.rstrip(token))
            if tail % 2 != 0:
                stripped = stripped[: len(stripped) - tail].rstrip()
        # If the last sentence has no ending punctuation, cut it off
        sentences = re.split(r"(?<=[.!?])\s+", stripped)
        if sentences and not re.search(r"[.!?)]\s*$", sentences[-1]) and len(sentences) > 1:
            stripped = " ".join(sentences[:-1]).rstrip()
        return stripped

    def _fallback_response(self, user_message: str, language: str = "auto") -> str:
        """Honest outage message used when the provider cannot answer.

        This is deliberately NOT a substitute AI reply: it never greets,
        never asks a follow-up question and never fabricates listings — it
        says the assistant is unavailable right now and asks the customer to
        retry, in the reply language. (`user_message` is kept in the
        signature for call-site compatibility.)
        """
        if language in ("ta", "mixed", "ta-Latn"):
            return (
                "LykAI-ஐ அணுக இப்போது முடியவில்லை. சிறிது நேரம் கழித்து "
                "மீண்டும் முயற்சிக்கவும்."
            )
        return (
            "LykAI is having trouble reaching its service right now, so I can't "
            "search listings at the moment. Please try again in a little while."
        )
