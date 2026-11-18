import io
import json
from urllib.error import HTTPError, URLError

import pytest

from vaanibench.models import Experiment
from vaanibench.providers import MockProvider, OpenAIProvider, ProviderError
from vaanibench.schemas import Message


def messages():
    return [Message(role="user", content="What is 2 + 3? Return only the number.")]


def test_mock_is_repeatable_and_usage_unknown():
    provider = MockProvider(Experiment(name="test"))
    a, b = provider.generate(messages()), provider.generate(messages())
    assert a == b
    assert a.text == "5"
    assert a.usage.input_tokens is None


def test_mock_failure():
    with pytest.raises(ProviderError, match="simulated_failure"):
        MockProvider(Experiment(name="test", mock_mode="failure")).generate(messages())


def test_openai_payload_and_parse(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret-never-log")
    def transport(request, timeout):
        payload = json.loads(request.data)
        assert payload["model"] == "example-model"
        assert payload["response_format"] == {"type": "json_object"}
        assert "reference_answer" not in payload and "rubric" not in payload
        assert payload["max_completion_tokens"] == 256
        assert timeout == 30.0
        return io.BytesIO(json.dumps(dict(model="example-model-snapshot", choices=[dict(
            finish_reason="stop", message=dict(content='{"ok":true}'))],
            usage=dict(prompt_tokens=10, completion_tokens=4))).encode())
    result = OpenAIProvider(Experiment(name="test", provider="openai", model="example-model"),
        json_mode=True, transport=transport).generate(messages())
    assert result.usage.input_tokens == 10
    assert result.usage.output_tokens == 4
    assert result.resolved_model == "example-model-snapshot"


@pytest.mark.parametrize("error,code", [(TimeoutError(), "timeout"),
    (URLError("secret body"), "transport_error"),
    (HTTPError("url", 429, "sensitive body", {}, None), "http_429")])
def test_openai_errors_are_safe(monkeypatch, error, code):
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret")
    def transport(*args, **kwargs):
        raise error
    with pytest.raises(ProviderError, match=code) as raised:
        OpenAIProvider(Experiment(name="test"), transport=transport).generate(messages())
    assert "secret" not in str(raised.value)


def test_openai_missing_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ProviderError, match="missing_api_key"):
        OpenAIProvider(Experiment(name="test")).generate(messages())


@pytest.mark.parametrize("body", [{}, {"choices": []}, {"choices": [{"finish_reason": "length"}]},
    {"choices": [{"finish_reason": "stop", "message": {"content": ""}}]}])
def test_bad_openai_response(monkeypatch, body):
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret")
    with pytest.raises(ProviderError):
        OpenAIProvider(Experiment(name="test"), transport=lambda *a, **k: io.BytesIO(json.dumps(body).encode())).generate(messages())
