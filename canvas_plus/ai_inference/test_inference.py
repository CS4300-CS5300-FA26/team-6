"""AI inference boundary tests; no requests reach OpenAI."""

from unittest.mock import Mock, patch

import pytest
from pydantic import BaseModel

from .inference import infer

FAKE_TOKEN = "fake-ai-token"


class Answer(BaseModel):
    """Minimal structured response used by the tests."""

    text: str


@pytest.fixture(autouse=True)
def ai_settings(settings):
    """Use a fixed, non-secret AI token."""
    settings.AI_API_KEY = FAKE_TOKEN


def complete_response(text="hello"):
    """Construct a successful, complete Responses API result."""
    return Mock(status="completed", output_text=Answer(text=text).model_dump_json())


@pytest.mark.unit
def test_token_read_from_ai_api_key_setting():
    """Given AI_API_KEY is configured, the provider client is built with that key."""
    with patch("ai_inference.inference.OpenAI") as client_class:
        client_class.return_value.responses.create.return_value = complete_response()
        infer("Say hello", "content", Answer)
    client_class.assert_called_once()
    assert client_class.call_args.kwargs["api_key"] == FAKE_TOKEN
