from __future__ import annotations

import json

import pytest

from opendream import llm


def test_extract_plain_json():
    assert llm.extract_json('{"a": 1}') == {"a": 1}


def test_extract_strips_markdown_fence_with_lang_tag():
    text = '```json\n{"a": 1, "b": [2, 3]}\n```'
    assert llm.extract_json(text) == {"a": 1, "b": [2, 3]}


def test_extract_strips_markdown_fence_without_lang_tag():
    text = '```\n{"a": 1}\n```'
    assert llm.extract_json(text) == {"a": 1}


def test_extract_brace_fallback_handles_chatty_prefix_suffix():
    text = 'Sure! Here is your JSON:\n{"answer": 42}\nLet me know if that helps.'
    assert llm.extract_json(text) == {"answer": 42}


def test_extract_raises_on_unrecoverable_text():
    with pytest.raises(json.JSONDecodeError):
        llm.extract_json("not json at all")


def _clear_provider_env(monkeypatch):
    for var in (
        "OPENDREAM_LLM_PROVIDER",
        "OPENDREAM_LLM_BASE_URL",
        "OPENDREAM_LLM_API_KEY",
        "OPENDREAM_REFLECT_MODEL",
        "OPENDREAM_DREAM_MODEL",
    ):
        monkeypatch.delenv(var, raising=False)


def test_llm_config_openai_defaults(monkeypatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "secret-openai")
    cfg = llm.LLMConfig.from_env()
    assert cfg.provider == "openai"
    assert cfg.base_url is None
    assert cfg.api_key == "secret-openai"
    assert cfg.reflect_model == llm.DEFAULTS["openai"]["reflect"]
    assert cfg.dream_model == llm.DEFAULTS["openai"]["dream"]


def test_llm_config_anthropic_defaults(monkeypatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("OPENDREAM_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    cfg = llm.LLMConfig.from_env()
    assert cfg.provider == "anthropic"
    assert cfg.api_key == "sk-ant-test"
    assert cfg.reflect_model == "claude-haiku-4-5-20251001"
    assert cfg.dream_model == "claude-sonnet-4-6"
    assert cfg.base_url is None


def test_llm_config_per_purpose_overrides(monkeypatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("OPENDREAM_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("OPENDREAM_REFLECT_MODEL", "custom-cheap")
    monkeypatch.setenv("OPENDREAM_DREAM_MODEL", "custom-strong")
    cfg = llm.LLMConfig.from_env()
    assert cfg.reflect_model == "custom-cheap"
    assert cfg.dream_model == "custom-strong"
    # model_for selects on purpose
    assert cfg.model_for("reflect") == "custom-cheap"
    assert cfg.model_for("dream") == "custom-strong"


def test_llm_config_overrides_are_independent(monkeypatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("OPENDREAM_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("OPENDREAM_REFLECT_MODEL", "only-reflect-overridden")
    cfg = llm.LLMConfig.from_env()
    assert cfg.reflect_model == "only-reflect-overridden"
    assert cfg.dream_model == "claude-sonnet-4-6"  # default still applies


def test_llm_config_rejects_unknown_provider(monkeypatch):
    monkeypatch.setenv("OPENDREAM_LLM_PROVIDER", "deepseek")
    with pytest.raises(ValueError, match="OPENDREAM_LLM_PROVIDER"):
        llm.LLMConfig.from_env()


def test_llm_config_rejects_unknown_purpose(monkeypatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    cfg = llm.LLMConfig.from_env()
    with pytest.raises(ValueError, match="unknown purpose"):
        cfg.model_for("hallucinate")  # type: ignore[arg-type]


def test_llm_client_picks_model_per_purpose(monkeypatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("OPENDREAM_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")

    reflect_client = llm.LLMClient(purpose="reflect")
    dream_client = llm.LLMClient(purpose="dream")

    assert reflect_client._impl.__class__.__name__ == "_AnthropicBackend"
    assert reflect_client.model == "claude-haiku-4-5-20251001"
    assert dream_client.model == "claude-sonnet-4-6"


def test_llm_client_rejects_unknown_purpose():
    with pytest.raises(ValueError, match="purpose must be"):
        llm.LLMClient(purpose="hallucinate")  # type: ignore[arg-type]


def test_llm_client_dispatches_to_correct_backend(monkeypatch):
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("OPENDREAM_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    assert llm.LLMClient(purpose="reflect")._impl.__class__.__name__ == "_AnthropicBackend"

    monkeypatch.setenv("OPENDREAM_LLM_PROVIDER", "openai")
    assert llm.LLMClient(purpose="reflect")._impl.__class__.__name__ == "_OpenAIBackend"


# --------------------------------------------------------------------------
# OpenAI backend retry behavior (response_format unsupported by some
# OpenAI-compatible backends). Mocked — no network, no key.
# --------------------------------------------------------------------------


class _FakeChoice:
    def __init__(self, content: str):
        self.message = type("M", (), {"content": content})


class _FakeResp:
    def __init__(self, content: str):
        self.choices = [_FakeChoice(content)]


def _make_bad_request_error(message: str):
    """Build a real `openai.BadRequestError` without making a network call."""
    import httpx
    from openai import BadRequestError

    request = httpx.Request("POST", "https://api.openai.test/v1/chat/completions")
    response = httpx.Response(400, request=request, text=message)
    return BadRequestError(message=message, response=response, body=None)


def test_openai_backend_retries_without_response_format_on_unsupported_400(monkeypatch):
    """When the backend rejects `response_format` with a 400 mentioning it,
    the retry path drops the parameter and proceeds."""
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    client = llm.LLMClient(purpose="reflect")

    calls: list[dict] = []

    def fake_create(**kwargs):
        calls.append(kwargs)
        if "response_format" in kwargs:
            raise _make_bad_request_error(
                "response_format is not supported by this model"
            )
        return _FakeResp('{"ok": true}')

    monkeypatch.setattr(client._impl.client.chat.completions, "create", fake_create)
    out = client.complete_json("sys", "usr")
    assert out == {"ok": True}
    assert len(calls) == 2
    assert "response_format" in calls[0]
    assert "response_format" not in calls[1]


def test_openai_backend_does_not_retry_on_auth_error(monkeypatch):
    """A 401 / AuthenticationError is a sibling class of BadRequestError —
    the retry must NOT swallow it. The user has to see the real problem."""
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    client = llm.LLMClient(purpose="reflect")

    import httpx
    from openai import AuthenticationError

    def fake_create(**_):
        raise AuthenticationError(
            message="Incorrect API key provided",
            response=httpx.Response(
                401,
                request=httpx.Request("POST", "https://api.openai.test/v1/x"),
            ),
            body=None,
        )

    monkeypatch.setattr(client._impl.client.chat.completions, "create", fake_create)
    with pytest.raises(AuthenticationError):
        client.complete_json("sys", "usr")


def test_openai_backend_does_not_retry_on_unrelated_400(monkeypatch):
    """A 400 that isn't about response_format (e.g. context length, bad
    model id) must propagate — silently retrying without response_format
    just hides the real failure."""
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake")
    client = llm.LLMClient(purpose="reflect")

    def fake_create(**_):
        raise _make_bad_request_error(
            "Invalid model 'gpt-this-does-not-exist'"
        )

    monkeypatch.setattr(client._impl.client.chat.completions, "create", fake_create)
    with pytest.raises(Exception, match="Invalid model"):
        client.complete_json("sys", "usr")
