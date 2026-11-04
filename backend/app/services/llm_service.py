import argparse
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from google import genai
from google.genai import errors, types


DEFAULT_GEMINI_MODEL = "gemini-flash-latest"
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_BLOCKED_FINISH_REASONS = {
    "BLOCKLIST",
    "IMAGE_SAFETY",
    "PROHIBITED_CONTENT",
    "RECITATION",
    "SAFETY",
    "SPII",
}


class GeminiServiceError(RuntimeError):
    """Base class for sanitized Gemini service failures."""


class MissingAPIKeyError(GeminiServiceError):
    """Raised when GEMINI_API_KEY is not configured."""


class InvalidAPIKeyError(GeminiServiceError):
    """Raised when Gemini rejects the configured API key."""


class InvalidModelError(GeminiServiceError):
    """Raised when the requested Gemini model is unavailable."""


class RateLimitError(GeminiServiceError):
    """Raised when Gemini continues rate limiting after bounded retries."""


class ServiceUnavailableError(GeminiServiceError):
    """Raised when Gemini remains unavailable after bounded retries."""


class RequestTimeoutError(GeminiServiceError):
    """Raised when a Gemini request times out after bounded retries."""


@dataclass(frozen=True)
class TokenUsage:
    prompt_tokens: int | None = None
    response_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True)
class GenerationResult:
    text: str
    model_name: str
    usage: TokenUsage | None
    status: str
    finish_reason: str | None = None
    block_reason: str | None = None


def _enum_label(value: Any) -> str | None:
    if value is None:
        return None
    name = getattr(value, "name", None)
    if isinstance(name, str):
        return name.upper()
    return str(value).rsplit(".", maxsplit=1)[-1].upper()


def _token_usage(response: Any) -> TokenUsage | None:
    metadata = getattr(response, "usage_metadata", None)
    if metadata is None:
        return None

    prompt_tokens = getattr(metadata, "prompt_token_count", None)
    response_tokens = getattr(metadata, "candidates_token_count", None)
    total_tokens = getattr(metadata, "total_token_count", None)
    if prompt_tokens is None and response_tokens is None and total_tokens is None:
        return None

    return TokenUsage(
        prompt_tokens=prompt_tokens,
        response_tokens=response_tokens,
        total_tokens=total_tokens,
    )


def _is_invalid_api_key_error(error: errors.APIError) -> bool:
    if error.code in {401, 403}:
        return True

    payload = getattr(error, "details", None)
    if isinstance(payload, dict):
        error_payload = payload.get("error")
        if not isinstance(error_payload, dict):
            return False
        message = error_payload.get("message", "")
        return isinstance(message, str) and "api key" in message.lower() and (
            "invalid" in message.lower() or "not valid" in message.lower()
        )
    return False


class GeminiLLMService:
    """Reusable Google Gen AI client with bounded retries and safe errors."""

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str | None = None,
        temperature: float = 0.2,
        max_output_tokens: int = 1024,
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.5,
        client: Any | None = None,
    ) -> None:
        load_dotenv(_BACKEND_ROOT / ".env", override=False)
        configured_key = api_key if api_key is not None else os.getenv("GEMINI_API_KEY")
        if not configured_key or not configured_key.strip():
            raise MissingAPIKeyError(
                "Gemini API key is missing. Set GEMINI_API_KEY in the environment or backend/.env."
            )

        configured_model = model_name or os.getenv("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL
        if not configured_model.strip():
            raise ValueError("model_name must not be empty.")
        if not 0.0 <= temperature <= 2.0:
            raise ValueError("temperature must be between 0.0 and 2.0.")
        if not isinstance(max_output_tokens, int) or isinstance(max_output_tokens, bool) or max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be a positive integer.")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive.")
        if not isinstance(max_retries, int) or isinstance(max_retries, bool) or max_retries < 0:
            raise ValueError("max_retries must be a nonnegative integer.")
        if retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must be nonnegative.")

        self.model_name = configured_model.strip()
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self._client = client or genai.Client(
            api_key=configured_key.strip(),
            http_options=types.HttpOptions(timeout=int(timeout_seconds * 1000)),
        )

    def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
    ) -> GenerationResult:
        """Generate text; failures contain safe diagnostics, never request details."""
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt must be a non-empty string.")
        if system_instruction is not None and not isinstance(system_instruction, str):
            raise ValueError("system_instruction must be a string or None.")

        config = types.GenerateContentConfig(
            temperature=self.temperature,
            max_output_tokens=self.max_output_tokens,
            system_instruction=system_instruction,
        )
        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=config,
                )
                return self._result_from_response(response)
            except errors.APIError as error:
                if _is_invalid_api_key_error(error):
                    raise InvalidAPIKeyError("Gemini rejected the configured API key.") from None
                if error.code == 404:
                    raise InvalidModelError(
                        "The configured Gemini model is unavailable. Use the model-list utility to check models."
                    ) from None
                if error.code == 429:
                    if attempt < self.max_retries:
                        self._wait_before_retry(attempt)
                        continue
                    raise RateLimitError("Gemini rate limit persisted after retries.") from None
                if error.code in {500, 502, 503, 504}:
                    if attempt < self.max_retries:
                        self._wait_before_retry(attempt)
                        continue
                    raise ServiceUnavailableError(
                        "Gemini is temporarily unavailable. Please try again later."
                    ) from None
                raise GeminiServiceError(
                    "Gemini rejected the generation request."
                ) from None
            except (httpx.TimeoutException, TimeoutError):
                if attempt < self.max_retries:
                    self._wait_before_retry(attempt)
                    continue
                raise RequestTimeoutError(
                    "Gemini request timed out after retries."
                ) from None
            except httpx.NetworkError:
                if attempt < self.max_retries:
                    self._wait_before_retry(attempt)
                    continue
                raise ServiceUnavailableError(
                    "Gemini could not be reached after retries."
                ) from None

        raise ServiceUnavailableError("Gemini request could not be completed.")

    def _wait_before_retry(self, attempt: int) -> None:
        delay = min(self.retry_backoff_seconds * (2**attempt), 8.0)
        if delay:
            time.sleep(delay)

    def _result_from_response(self, response: Any) -> GenerationResult:
        usage = _token_usage(response)
        prompt_feedback = getattr(response, "prompt_feedback", None)
        block_reason = _enum_label(
            getattr(prompt_feedback, "block_reason", None)
        )
        candidates = getattr(response, "candidates", None) or []
        finish_reason = (
            _enum_label(getattr(candidates[0], "finish_reason", None))
            if candidates
            else None
        )

        if block_reason or finish_reason in _BLOCKED_FINISH_REASONS:
            return GenerationResult(
                text="",
                model_name=self.model_name,
                usage=usage,
                status="blocked",
                finish_reason=finish_reason,
                block_reason=block_reason or finish_reason,
            )

        try:
            text = response.text
        except ValueError:
            text = None
        if not isinstance(text, str) or not text.strip():
            return GenerationResult(
                text="",
                model_name=self.model_name,
                usage=usage,
                status="empty",
                finish_reason=finish_reason,
            )

        return GenerationResult(
            text=text,
            model_name=self.model_name,
            usage=usage,
            status="success",
            finish_reason=finish_reason,
        )

    def list_available_models(self) -> list[str]:
        """List only models that advertise generateContent support."""
        try:
            models = self._client.models.list()
            return sorted(
                name.removeprefix("models/")
                for model in models
                if "generateContent" in (getattr(model, "supported_actions", None) or [])
                and isinstance((name := getattr(model, "name", None)), str)
            )
        except errors.APIError as error:
            if _is_invalid_api_key_error(error):
                raise InvalidAPIKeyError("Gemini rejected the configured API key.") from None
            raise GeminiServiceError("Unable to list Gemini models.") from None
        except (httpx.TimeoutException, TimeoutError):
            raise RequestTimeoutError("Gemini model listing timed out.") from None
        except httpx.NetworkError:
            raise ServiceUnavailableError("Gemini model listing could not reach the service.") from None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="List Gemini models available for generateContent."
    )
    parser.parse_args()
    try:
        service = GeminiLLMService()
        models = service.list_available_models()
    except GeminiServiceError as error:
        parser.exit(status=1, message=f"{error}\n")

    if not models:
        print("No models supporting generateContent are available for this API key.")
        return
    print("\n".join(models))


if __name__ == "__main__":
    main()
