"""Shared Gemini helper. Every Gemini call in PRE goes through structured_call.

Usage (also for Person 3):
    from ai.gemini import structured_call
    result = structured_call("Extract the hyperparameters from ...", MySchema)

Env: GEMINI_API_KEY, GEMINI_MODEL, and optional GEMINI_FALLBACK_MODEL (used
when the main model is overloaded or out of quota).
"""

import os
from typing import Optional, TypeVar

from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)

MAX_RETRIES = 2

# Overloaded / rate-limited / server errors: worth switching to the fallback model.
FALLBACK_STATUS_CODES = {429, 500, 503, 504}

_client: Optional[genai.Client] = None


class GeminiError(RuntimeError):
    """Gemini failed to return valid output after all retries."""


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise GeminiError("GEMINI_API_KEY is not set")
        _client = genai.Client(api_key=api_key)
    return _client


def _get_models() -> list[str]:
    model = os.environ.get("GEMINI_MODEL")
    if not model:
        raise GeminiError("GEMINI_MODEL is not set")
    fallback = os.environ.get("GEMINI_FALLBACK_MODEL")
    return [model, fallback] if fallback and fallback != model else [model]


def _generate(client: genai.Client, models: list[str], contents: str, config) -> str:
    """Call the first model; on overload/quota errors, try the fallback."""
    for i, model in enumerate(models):
        try:
            response = client.models.generate_content(
                model=model, contents=contents, config=config
            )
            return response.text or ""
        except errors.APIError as e:
            if e.code in FALLBACK_STATUS_CODES and i + 1 < len(models):
                continue
            raise GeminiError(f"Gemini API error from {model}: {e.code} {e.message}") from e
    raise AssertionError("unreachable")


def structured_call(
    prompt: str,
    schema: type[T],
    system: Optional[str] = None,
    retries: int = MAX_RETRIES,
) -> T:
    """Call Gemini with JSON-schema output and return a validated `schema` instance.

    On malformed JSON or schema validation errors, re-prompts with the error
    (up to `retries` extra attempts), then raises GeminiError.
    """
    client = _get_client()
    models = _get_models()
    config = types.GenerateContentConfig(
        system_instruction=system,
        response_mime_type="application/json",
        response_schema=schema,
    )

    contents = prompt
    last_error = ""
    for _ in range(retries + 1):
        text = _generate(client, models, contents, config)
        try:
            return schema.model_validate_json(text)
        except ValidationError as e:
            last_error = str(e)
            contents = (
                f"{prompt}\n\n"
                f"Your previous response was invalid:\n{last_error}\n"
                "Return corrected JSON that matches the schema exactly."
            )

    raise GeminiError(f"Gemini output failed validation after {retries + 1} attempts: {last_error}")
