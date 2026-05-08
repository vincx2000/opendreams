"""
opendream.llm
-------------

Thin wrapper around the OpenAI Python SDK with a configurable `base_url`.

The single client supports any OpenAI-compatible endpoint — Ollama, vLLM,
OpenAI itself, Together, Groq, Fireworks, and Anthropic via a compatible
proxy. Configuration is read from environment variables so adapters and
pipeline stages don't need to know how the model is reached.

Environment:
- OPENDREAM_LLM_BASE_URL  (default: OpenAI's https://api.openai.com/v1)
- OPENDREAM_LLM_API_KEY   (default: OPENAI_API_KEY)
- OPENDREAM_LLM_MODEL     (default: gpt-4o-mini)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from openai import OpenAI


DEFAULT_MODEL = "gpt-4o-mini"


@dataclass
class LLMConfig:
    base_url: str | None
    api_key: str
    model: str

    @classmethod
    def from_env(cls) -> "LLMConfig":
        return cls(
            base_url=os.environ.get("OPENDREAM_LLM_BASE_URL") or None,
            api_key=(
                os.environ.get("OPENDREAM_LLM_API_KEY")
                or os.environ.get("OPENAI_API_KEY")
                or "sk-no-key"
            ),
            model=os.environ.get("OPENDREAM_LLM_MODEL", DEFAULT_MODEL),
        )


class LLMClient:
    """Minimal chat-completions client returning parsed JSON objects."""

    def __init__(self, config: LLMConfig | None = None) -> None:
        self.config = config or LLMConfig.from_env()
        self._client = OpenAI(base_url=self.config.base_url, api_key=self.config.api_key)

    def complete_json(self, system: str, user: str, *, temperature: float = 0.0) -> dict:
        """Run a chat completion and parse the response as JSON.

        Forces JSON output via response_format when the backend supports it,
        and falls back to brace-extraction when it doesn't.
        """
        try:
            resp = self._client.chat.completions.create(
                model=self.config.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
                response_format={"type": "json_object"},
            )
        except Exception:
            # Older / non-OpenAI backends may not support response_format.
            resp = self._client.chat.completions.create(
                model=self.config.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
            )
        text = resp.choices[0].message.content or ""
        return _extract_json(text)


def _extract_json(text: str) -> dict:
    """Parse the first JSON object out of `text`, tolerant of code-fence wrappers."""
    text = text.strip()
    if text.startswith("```"):
        # Drop opening fence (with optional language tag) and trailing fence.
        first_newline = text.find("\n")
        text = text[first_newline + 1 :] if first_newline != -1 else text
        if text.endswith("```"):
            text = text[: -3]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        return json.loads(text[start : end + 1])
