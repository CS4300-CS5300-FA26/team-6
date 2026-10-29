"""Run structured inference through OpenAI with the application's configured token."""

from django.views.decorators.debug import sensitive_variables
from openai import AuthenticationError, OpenAI, OpenAIError
from openai.lib._pydantic import to_strict_json_schema
from pydantic import BaseModel

from .exceptions import (
    AIConfigurationError,
    AIAuthenticationError,
    AIIncompleteResponseError,
    AIInvalidOutputError,
    AIProviderError,
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
        if "OPENAI_API_KEY" in str(e):
            raise AIConfigurationError("Configure OPENAI_API_KEY to use AI inference.") from None
        raise

    try:
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
            }
        )
    except AuthenticationError:
        raise AIAuthenticationError("The provider rejected the configured credentials.") from None
    except OpenAIError:
        raise AIProviderError("The provider request failed.") from None

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


@sensitive_variables("client", "uploaded_file")
def build_content(text=None, files=()):
    """Build Responses API user input from optional text and local file paths."""
    if text is not None and not isinstance(text, str):
        raise TypeError("text must be a string")
    if text is not None and not text.strip():
        text = None
    if text is None and not files:
        raise ValueError("content must include text or at least one file")

    content_items = []
    if text is not None:
        content_items.append({"type": "input_text", "text": text})

    try:
        client = OpenAI()
        for file_path in files:
            with open(file_path, "rb") as uploaded_file:
                uploaded = client.files.create(file=uploaded_file, purpose="user_data")
            content_items.append({"type": "input_file", "file_id": uploaded.id})
    except AuthenticationError:
        raise AIAuthenticationError("The provider rejected the configured credentials.") from None
    except OpenAIError:
        raise AIProviderError("The provider file upload failed.") from None
    except OSError:
        raise AIProviderError("The local file could not be read.") from None

    return [{"role": "user", "content": content_items}]