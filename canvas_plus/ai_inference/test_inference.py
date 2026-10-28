"""AI inference boundary tests; no requests reach OpenAI."""

import logging
from unittest.mock import Mock, patch

import openai
import pytest
from pydantic import BaseModel

from .exceptions import AIConfigurationError, AIInferenceError
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


@pytest.mark.unit
def test_missing_token_raises_configuration_error_without_provider_call(settings):
    """Given no AI_API_KEY, infer fails clearly and never contacts the provider."""
    settings.AI_API_KEY = ""
    with patch("ai_inference.inference.OpenAI") as client_class:
        with pytest.raises(AIConfigurationError) as error:
            infer("Say hello", "content", Answer)
    client_class.assert_not_called()
    assert FAKE_TOKEN not in str(error.value)


def refusal_response():
    """Construct a Responses API result in which the model refused."""
    part = Mock(type="refusal", refusal="I cannot help with that.")
    return Mock(status="completed", output_text="", output=[Mock(type="message", content=[part])])


def provider_error(error_class):
    """Build an OpenAI SDK error whose own message echoes the token."""
    message = f"Incorrect API key provided: {FAKE_TOKEN}"
    if error_class is openai.AuthenticationError:
        return error_class(message, response=Mock(status_code=401, headers={}), body=None)
    return error_class(message=message, request=Mock())


@pytest.mark.unit
@pytest.mark.parametrize("outcome", [
    pytest.param(None, id="success"),
    pytest.param(provider_error(openai.AuthenticationError), id="authentication"),
    pytest.param(provider_error(openai.APIConnectionError), id="api-failure"),
    pytest.param("refusal", id="refusal"),
])
def test_token_absent_from_logs_and_errors(outcome, caplog):
    """Given any outcome, neither logs nor caller-visible errors contain the token."""
    caplog.set_level(logging.DEBUG)
    with patch("ai_inference.inference.OpenAI") as client_class:
        create = client_class.return_value.responses.create
        if outcome is None:
            create.return_value = complete_response()
        elif outcome == "refusal":
            create.return_value = refusal_response()
        else:
            create.side_effect = outcome
        if outcome is None:
            infer("Say hello", "content", Answer)
        else:
            with pytest.raises(AIInferenceError) as error:
                infer("Say hello", "content", Answer)
            assert FAKE_TOKEN not in str(error.value)
            assert FAKE_TOKEN not in repr(error.value)
    assert FAKE_TOKEN not in caplog.text
