"""Run structured inference through OpenAI with the application's configured token."""

from django.views.decorators.debug import sensitive_variables
from openai import OpenAI, OpenAIError
from openai.lib._pydantic import to_strict_json_schema
from pydantic import BaseModel

from .exceptions import (
    AIConfigurationError,
    AIIncompleteResponseError,
    AIInvalidOutputError,
    AIRefusalError,
)

MODEL = "gpt-6-luna"

@sensitive_variables("client")
def infer(prompt, content, response_model):
    """Return a validated response_model instance for the prompt and content."""
    if not isinstance(response_model, type) or not issubclass(response_model, BaseModel):
        raise TypeError("response_model must be a Pydantic BaseModel subclass")
    if not prompt.strip():
        raise ValueError("prompt must not be blank")

    try:
        client = OpenAI()
    except OpenAIError as e:
        if "Missing configuration" in str(e):
            raise AIConfigurationError("Configure OPENAI_API_KEY to use AI inference.") from None
        raise

    response = client.responses.create(
        model=MODEL,
        instructions=prompt,
        input=content,
        text={
            "format": {
                "type": "json_schema",
                "name": response_model.__name__,
                "strict": True,
                "schema": to_strict_json_schema(response_model),
            }
        },
    )

    if response.status != "completed":
        raise AIIncompleteResponseError("The provider did not complete the response.")

    output_items = response.output
    if isinstance(output_items, list) and any(
        part.type == "refusal"
        for item in output_items
        for part in getattr(item, "content", [])
    ):
        raise AIRefusalError("The provider refused to generate a response.")

    try:
        return response_model.model_validate_json(response.output_text)
    except (TypeError, ValueError):
        raise AIInvalidOutputError(
            "The provider response could not be parsed as the requested model."
        ) from None