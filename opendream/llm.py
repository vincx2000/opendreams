"""
opendream.llm
-------------

Dual-backend LLM client: OpenAI-compatible (default) and Anthropic native.
Selected via `OPENDREAM_LLM_PROVIDER` (`openai` | `anthropic`).

The OpenAI backend covers Ollama, vLLM, OpenAI itself, Together, Groq,
Fireworks, and any other OpenAI-compatible endpoint via `OPENDREAM_LLM_BASE_URL`.
The Anthropic backend talks to api.anthropic.com directly so we get prompt
caching, thinking, and the latest Claude features without proxy contortions.

Reflect (Stage 1) and Dream (Stage 2) have opposite cost/quality profiles:
reflect runs once per session and stays cheap; dream runs once per cycle and
needs the strongest model in the locker. So we expose two separate model
selectors, not one.

Environment variables (read once at construction):
- OPENDREAM_LLM_PROVIDER   openai (default) | anthropic
- OPENDREAM_LLM_BASE_URL   OpenAI: custom endpoint. Anthropic: ignored.
- OPENDREAM_LLM_API_KEY    shared override; falls back to OPENAI_API_KEY / ANTHROPIC_API_KEY.
- OPENDREAM_REFLECT_MODEL  Stage 1 model. Defaults: gpt-4o-mini / claude-haiku-4-5-20251001.
- OPENDREAM_DREAM_MODEL    Stage 2 model. Defaults: gpt-4o      / claude-sonnet-4-6.

Both backends expose the same `complete_json(system, user)` surface, so the
rest of the pipeline (`reflect.py`, `consolidate.py`) is provider-agnostic.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Literal


Purpose = Literal["reflect", "dream"]

DEFAULTS: dict[str, dict[str, str]] = {
    "openai": {
        "reflect": "gpt-4o-mini",
        "dream": "gpt-4o",
    },
    "anthropic": {
        "reflect": "claude-haiku-4-5-20251001",
        "dream": "claude-sonnet-4-6",
    },
}


@dataclass
class LLMConfig:
    provider: str  # "openai" | "anthropic"
    base_url: str | None
    api_key: str
    reflect_model: str
    dream_model: str

    @classmethod
    def from_env(cls) -> "LLMConfig":
        provider = (os.environ.get("OPENDREAM_LLM_PROVIDER") or "openai").lower()
        if provider not in {"openai", "anthropic"}:
            raise ValueError(
                f"OPENDREAM_LLM_PROVIDER must be 'openai' or 'anthropic', got {provider!r}"
            )

        explicit_key = os.environ.get("OPENDREAM_LLM_API_KEY")
        if provider == "openai":
            api_key = explicit_key or os.environ.get("OPENAI_API_KEY") or "sk-no-key"
            base_url = os.environ.get("OPENDREAM_LLM_BASE_URL") or None
        else:
            api_key = (
                explicit_key or os.environ.get("ANTHROPIC_API_KEY") or "sk-ant-no-key"
            )
            base_url = None  # Anthropic SDK handles its own routing.

        defaults = DEFAULTS[provider]
        reflect_model = (
            os.environ.get("OPENDREAM_REFLECT_MODEL") or defaults["reflect"]
        )
        dream_model = (
            os.environ.get("OPENDREAM_DREAM_MODEL") or defaults["dream"]
        )
        return cls(
            provider=provider,
            base_url=base_url,
            api_key=api_key,
            reflect_model=reflect_model,
            dream_model=dream_model,
        )

    def model_for(self, purpose: Purpose) -> str:
        if purpose == "reflect":
            return self.reflect_model
        if purpose == "dream":
            return self.dream_model
        raise ValueError(f"unknown purpose {purpose!r}; expected 'reflect' or 'dream'")


class LLMClient:
    """Provider-agnostic façade with `complete_json(system, user)`."""

    def __init__(
        self,
        purpose: Purpose = "reflect",
        config: LLMConfig | None = None,
    ) -> None:
        if purpose not in {"reflect", "dream"}:
            raise ValueError(f"purpose must be 'reflect' or 'dream', got {purpose!r}")
        self.purpose: Purpose = purpose
        self.config = config or LLMConfig.from_env()
        self.model = self.config.model_for(purpose)
        self._impl = _build_backend(self.config, self.model)

    def complete_json(self, system: str, user: str, *, temperature: float = 0.0) -> dict:
        return self._impl.complete_json(system, user, temperature=temperature)


def _build_backend(config: LLMConfig, model: str):
    if config.provider == "anthropic":
        return _AnthropicBackend(config, model)
    return _OpenAIBackend(config, model)


class _OpenAIBackend:
    def __init__(self, config: LLMConfig, model: str) -> None:
        from openai import OpenAI

        self.config = config
        self.model = model
        self.client = OpenAI(base_url=config.base_url, api_key=config.api_key)

    def complete_json(self, system: str, user: str, *, temperature: float) -> dict:
        # Defer the SDK import so the openai package isn't required just to
        # construct an _OpenAIBackend at config time on Anthropic-only setups.
        from openai import BadRequestError

        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
                response_format={"type": "json_object"},
            )
        except BadRequestError as exc:
            # Some OpenAI-compatible backends (older Ollama, certain vLLM
            # builds, some proxies) reject `response_format` with a 400.
            # Retry without it ONLY when the 400 is plausibly about that
            # parameter — anything else (auth, rate limit, context length,
            # bad model id) propagates so the user sees the real problem.
            # Auth/RateLimit/Connection errors are sibling classes of
            # BadRequestError, so this `except` doesn't catch them.
            if "response_format" not in str(exc) and "json" not in str(exc).lower():
                raise
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
            )
        return extract_json(resp.choices[0].message.content or "")


class _AnthropicBackend:
    def __init__(self, config: LLMConfig, model: str) -> None:
        from anthropic import Anthropic

        self.config = config
        self.model = model
        self.client = Anthropic(api_key=config.api_key)

    def complete_json(self, system: str, user: str, *, temperature: float) -> dict:
        # Anthropic doesn't have OpenAI's strict JSON-mode; we instruct the
        # model and rely on extract_json's brace-extraction fallback.
        from anthropic.types import TextBlock

        resp = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=system + "\n\nReturn ONLY a JSON object. No prose, no markdown fences.",
            messages=[{"role": "user", "content": user}],
            temperature=temperature,
        )
        text = "".join(
            block.text for block in resp.content if isinstance(block, TextBlock)
        )
        return extract_json(text)


def extract_json(text: str) -> dict:
    """Parse the first JSON object out of `text`, tolerant of code-fence wrappers."""
    text = text.strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        text = text[first_newline + 1 :] if first_newline != -1 else text
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        return json.loads(text[start : end + 1])
