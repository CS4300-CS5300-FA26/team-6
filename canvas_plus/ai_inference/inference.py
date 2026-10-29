"""Run structured inference through OpenAI with the application's configured token."""

import os

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
    """Build Responses API user input from text and caller-provided files."""
    if text is not None and not isinstance(text, str):
        raise TypeError("text must be a string")
    if text is not None and not text.strip():
        text = None

    try:
        file_inputs = tuple(files)
    except TypeError:
        raise TypeError("files must be an iterable of supported file inputs") from None
    if text is None and not file_inputs:
        raise ValueError("content must include text or at least one file")

    normalized_files = [_normalize_file_input(file_input) for file_input in file_inputs]

    content_items = []
    if text is not None:
        content_items.append({"type": "input_text", "text": text})

    if not normalized_files:
        return [{"role": "user", "content": content_items}]

    try:
        client = OpenAI()
    except OpenAIError as error:
        if "OPENAI_API_KEY" in str(error):
            raise AIConfigurationError(
                "Configure OPENAI_API_KEY to use AI inference."
            ) from None
        raise AIProviderError("The provider client could not be initialized.") from None

    try:
        for file_kind, file_data in normalized_files:
            uploaded = _upload_file(client, file_kind, file_data)
            content_items.append({"type": "input_file", "file_id": uploaded.id})
    except AuthenticationError:
        raise AIAuthenticationError("The provider rejected the configured credentials.") from None
    except OpenAIError:
        raise AIProviderError("The provider file upload failed.") from None
    except OSError:
        raise AIProviderError("The local file could not be read.") from None

    return [{"role": "user", "content": content_items}]


def _upload_file(client, file_kind, file_data):
    """Upload one normalized file input and return the provider file record."""
    if file_kind == "path":
        with open(file_data, "rb") as uploaded_file:
            return client.files.create(file=uploaded_file, purpose="user_data")
    return client.files.create(file=file_data, purpose="user_data")


def _normalize_file_input(file_input):
    """Validate one file input and classify it for upload."""
    if isinstance(file_input, (str, os.PathLike)):
        return "path", file_input

    if isinstance(file_input, (tuple, list)):
        if len(file_input) != 2:
            raise TypeError("file pairs must contain a filename and binary content")
        filename, file_data = file_input
        if not isinstance(filename, str) or not filename.strip():
            raise ValueError("file names must not be empty")
        if isinstance(file_data, bytes):
            return "upload", (filename, file_data)
        stream = file_data
    else:
        stream = file_input
        filename = getattr(stream, "name", None)
        if not isinstance(filename, str) or not filename.strip():
            raise ValueError("file streams must have a non-empty name")

    if not callable(getattr(stream, "read", None)):
        raise TypeError("file content must be bytes or a readable binary stream")
    readable = getattr(stream, "readable", None)
    if callable(readable) and not readable():
        raise TypeError("file stream must be readable")
    try:
        sample = stream.read(0)
    except Exception:
        raise AIProviderError("The file stream could not be read.") from None
    if not isinstance(sample, bytes):
        raise TypeError("file content must be binary")

    upload = (filename, stream) if isinstance(file_input, (tuple, list)) else stream
    return "upload", upload
