import os
import re
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class NVIDIAClient:
    """Client for NVIDIA LLM API - the AI brain of the real estate agent.

    Uses synchronous HTTP calls so it can be safely called from FastAPI
    endpoints (which run sync handlers in a threadpool).
    """

    def __init__(self):
        self.api_key = os.getenv("NVIDIA_API_KEY", "")
        self.model = os.getenv("NVIDIA_MODEL", "nvidia/nemotron-3.5-lightning-30b-a3b")
        self.base_url = "https://integrate.api.nvidia.com/v1"

    def chat_sync(
        self,
        system_prompt: str,
        user_message: str,
        conversation_history: Optional[List[Dict]] = None,
    ) -> str:
        """
        Send a chat message to the NVIDIA LLM and get a synchronous response.
        The system prompt defines the agent's personality and constraints.
        """
        if not self.api_key:
            logger.warning("NVIDIA API key not configured")
            return self._fallback_response(user_message)

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # Build messages
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

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 4000,
        }

        try:
            with httpx.Client(timeout=120.0, verify=True) as client:
                response = client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
                choice = data.get("choices", [{}])[0]
                content = choice.get("message", {}).get("content", "")
                cleaned = self._clean_response(content)
                # If the model hit the token cap mid-sentence, tidy the tail
                if choice.get("finish_reason") == "length":
                    cleaned = self._trim_incomplete_tail(cleaned)
                return cleaned
        except httpx.HTTPStatusError as e:
            logger.error("NVIDIA API HTTP error: %s - %s", e.response.status_code, e.response.text[:500])
            return self._fallback_response(user_message)
        except Exception as e:
            logger.error("NVIDIA API error: %s", e)
            return self._fallback_response(user_message)

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
        lower = text.lower()
        for pat in preamble_patterns:
            m = re.match(pat, text, re.IGNORECASE)
            if m:
                text = text[m.end():].strip()

        # If a "final answer" marker exists, cut everything before it
        final_markers = [
            "**final answer**", "final response:", "**response:**",
            "assistant:", "reply:",
        ]
        for marker in final_markers:
            idx = lower.find(marker)
            if idx != -1:
                text = text[idx + len(marker):].strip()
                break

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

        return text if text else content

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

    def _fallback_response(self, user_message: str) -> str:
        """Fallback response when API is unavailable."""
        msg = user_message.lower().strip()
        if any(word in msg for word in ["hello", "hi", "hey"]):
            return (
                "Hi! I'm LykAI, your AI property concierge from Lyka Realty. "
                "I can help you find properties in the UAE — what are you "
                "looking for?"
            )
        elif "thank" in msg or "thanks" in msg:
            return "You're welcome! Is there anything else I can help you with?"
        elif "bye" in msg or "goodbye" in msg:
            return (
                "Goodbye! Feel free to reach out whenever you're ready to "
                "find your next property."
            )
        else:
            return (
                "I'd love to help you with that! Could you tell me more "
                "about what you're looking for?"
            )
