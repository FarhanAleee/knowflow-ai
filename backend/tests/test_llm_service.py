import os
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from dotenv import load_dotenv
from google.genai import errors, types

from app.services.llm_service import (
    DEFAULT_GEMINI_MODEL,
    GeminiLLMService,
    GeminiServiceError,
    GenerationResult,
    InvalidAPIKeyError,
    InvalidModelError,
    MissingAPIKeyError,
    RateLimitError,
    RequestTimeoutError,
    ServiceUnavailableError,
)


class FakeModels:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []
        self.list_result = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        result = self.responses.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    def list(self):
        return iter(self.list_result)


class FakeClient:
    def __init__(self, responses=None):
        self.models = FakeModels(responses)


def make_response(
    text="Generated text",
    *,
    prompt_tokens=5,
    response_tokens=7,
    total_tokens=12,
    block_reason=None,
    finish_reason=None,
):
    return SimpleNamespace(
        text=text,
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=prompt_tokens,
            candidates_token_count=response_tokens,
            total_token_count=total_tokens,
        ),
        prompt_feedback=SimpleNamespace(block_reason=block_reason),
        candidates=[SimpleNamespace(finish_reason=finish_reason)],
    )


def api_error(code, payload=None):
    return errors.APIError(code=code, response_json=payload or {})


def make_service(client, **kwargs):
    return GeminiLLMService(api_key="test-key", client=client, **kwargs)


def test_missing_api_key_is_reported_without_constructing_client(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr("app.services.llm_service._BACKEND_ROOT", tmp_path)

    with pytest.raises(MissingAPIKeyError, match="GEMINI_API_KEY"):
        GeminiLLMService()


def test_generate_returns_text_model_and_token_usage():
    client = FakeClient([make_response("The answer.")])
    service = make_service(client, model_name="test-model", temperature=0.4, max_output_tokens=90)

    result = service.generate("A private prompt", system_instruction="Be concise.")

    assert isinstance(result, GenerationResult)
    assert result.text == "The answer."
    assert result.model_name == "test-model"
    assert result.status == "success"
    assert result.usage.prompt_tokens == 5
    assert result.usage.response_tokens == 7
    assert result.usage.total_tokens == 12
    assert client.models.calls[0]["contents"] == "A private prompt"
    assert client.models.calls[0]["config"].system_instruction == "Be concise."
    assert client.models.calls[0]["config"].temperature == 0.4
    assert client.models.calls[0]["config"].max_output_tokens == 90


def test_empty_and_blocked_responses_are_explicit_results():
    client = FakeClient(
        [
            make_response("  "),
            make_response("", block_reason=types.BlockedReason.SAFETY),
        ]
    )
    service = make_service(client)

    empty = service.generate("prompt")
    blocked = service.generate("another prompt")

    assert empty.status == "empty"
    assert empty.text == ""
    assert blocked.status == "blocked"
    assert blocked.block_reason == "SAFETY"


def test_invalid_api_key_is_not_retried_or_exposed():
    secret = "private-api-key-value"
    client = FakeClient(
        [
            api_error(
                400,
                {"error": {"message": f"API key {secret} is not valid"}},
            )
        ]
    )
    service = make_service(client, max_retries=3)

    with pytest.raises(InvalidAPIKeyError) as error:
        service.generate("prompt")

    assert secret not in str(error.value)
    assert len(client.models.calls) == 1


def test_invalid_model_is_not_retried():
    client = FakeClient([api_error(404), make_response()])
    service = make_service(client, max_retries=2)

    with pytest.raises(InvalidModelError, match="model is unavailable"):
        service.generate("prompt")

    assert len(client.models.calls) == 1


def test_rate_limit_retries_then_raises_sanitized_error(monkeypatch):
    delays = []
    monkeypatch.setattr("app.services.llm_service.time.sleep", delays.append)
    client = FakeClient([api_error(429), api_error(429)])
    service = make_service(
        client,
        max_retries=1,
        retry_backoff_seconds=0.25,
    )

    with pytest.raises(RateLimitError):
        service.generate("prompt")

    assert len(client.models.calls) == 2
    assert delays == [0.25]


def test_temporary_503_retries_and_can_succeed(monkeypatch):
    delays = []
    monkeypatch.setattr("app.services.llm_service.time.sleep", delays.append)
    client = FakeClient([api_error(503), make_response("Recovered")])
    service = make_service(client, max_retries=2)

    result = service.generate("prompt")

    assert result.text == "Recovered"
    assert len(client.models.calls) == 2
    assert delays == [0.5]


def test_client_is_reused_and_default_model_is_configurable(monkeypatch, tmp_path):
    clients = []

    def fake_client(**kwargs):
        clients.append(kwargs)
        return FakeClient([make_response(), make_response()])

    monkeypatch.setattr("app.services.llm_service._BACKEND_ROOT", tmp_path)
    monkeypatch.setattr("app.services.llm_service.genai.Client", fake_client)
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("GEMINI_MODEL", "configured-model")

    service = GeminiLLMService()
    service.generate("one")
    service.generate("two")

    assert len(clients) == 1
    assert clients[0]["api_key"] == "test-key"
    assert clients[0]["http_options"].timeout == 30000
    assert service.model_name == "configured-model"
    assert service.model_name != DEFAULT_GEMINI_MODEL
    assert DEFAULT_GEMINI_MODEL == "gemini-flash-latest"


def test_model_listing_filters_for_generate_content_support():
    client = FakeClient()
    client.models.list_result = [
        SimpleNamespace(name="models/model-a", supported_actions=["generateContent"]),
        SimpleNamespace(name="models/model-b", supported_actions=["embedContent"]),
        SimpleNamespace(name="models/model-c", supported_actions=["generateContent"]),
    ]

    assert make_service(client).list_available_models() == ["model-a", "model-c"]


def test_timeout_has_bounded_retries_and_safe_message(monkeypatch):
    delays = []
    monkeypatch.setattr("app.services.llm_service.time.sleep", delays.append)
    client = FakeClient([httpx.TimeoutException("secret request details")])
    service = make_service(client, max_retries=0)

    with pytest.raises(RequestTimeoutError) as error:
        service.generate("prompt")

    assert "secret request details" not in str(error.value)
    assert len(client.models.calls) == 1
    assert delays == []


def test_network_timeout_retries_before_success(monkeypatch):
    delays = []
    monkeypatch.setattr("app.services.llm_service.time.sleep", delays.append)
    client = FakeClient(
        [
            httpx.TimeoutException("private timeout detail"),
            make_response("Recovered after timeout"),
        ]
    )
    service = make_service(client, max_retries=1, retry_backoff_seconds=0.1)

    result = service.generate("prompt")

    assert result.text == "Recovered after timeout"
    assert len(client.models.calls) == 2
    assert delays == [0.1]


def test_unavailable_error_after_503_retries(monkeypatch):
    delays = []
    monkeypatch.setattr("app.services.llm_service.time.sleep", delays.append)
    client = FakeClient([api_error(503), api_error(503)])
    service = make_service(client, max_retries=1, retry_backoff_seconds=0.2)

    with pytest.raises(ServiceUnavailableError):
        service.generate("prompt")

    assert len(client.models.calls) == 2
    assert delays == [0.2]


@pytest.mark.parametrize("prompt", ["", "  ", None])
def test_empty_prompt_is_rejected(prompt):
    service = make_service(FakeClient())

    with pytest.raises(ValueError, match="non-empty"):
        service.generate(prompt)


def test_generic_api_errors_are_sanitized():
    client = FakeClient([api_error(400, {"error": {"message": "sensitive request detail"}})])
    service = make_service(client)

    with pytest.raises(GeminiServiceError) as error:
        service.generate("private prompt")

    assert "sensitive request detail" not in str(error.value)


@pytest.mark.skipif(
    os.environ.get("RUN_REAL_GEMINI_TESTS") != "1",
    reason="Optional real Gemini API smoke test; set RUN_REAL_GEMINI_TESTS=1 to opt in.",
)
def test_real_gemini_api_smoke():
    load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
    if not os.getenv("GEMINI_API_KEY"):
        pytest.skip("GEMINI_API_KEY is not configured.")

    result = GeminiLLMService().generate("Reply with the single word: ready")

    assert result.status == "success"
    assert result.text.strip()
