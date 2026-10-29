"""AI inference boundary tests; no requests reach OpenAI."""

import logging
import inspect
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


class CountAnswer(BaseModel):
    """Distinct response schema used to verify per-call schema selection."""

    count: int


class UnsupportedSchema(BaseModel):
    """Open-ended schema fixture for testing provider rejection handling."""

    metadata: dict[str, str]


@pytest.fixture(autouse=True)
def ai_api_key(monkeypatch):
    """Provide a fixed, non-secret process environment key."""
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_TOKEN)


def complete_response(text="hello"):
    """Construct a successful, complete Responses API result."""
    return Mock(status="completed", output_text=Answer(text=text).model_dump_json())


@pytest.mark.unit
def test_openai_client_uses_openai_api_key_environment_variable(monkeypatch):
    """Configured process key is left for the SDK to load automatically."""
    monkeypatch.setenv("OPENAI_API_KEY", FAKE_TOKEN)
    with patch("ai_inference.inference.OpenAI") as client_class:
        client_class.return_value.responses.create.return_value = complete_response()
        infer("Say hello", "content", Answer)
    client_class.assert_called_once_with()


@pytest.mark.unit
def test_missing_openai_api_key_raises_configuration_error_without_provider_call(
    monkeypatch,
):
    """Missing SDK environment credentials fail clearly before an API request."""
    monkeypatch.delenv("OPENAI_API_KEY")
    with patch("ai_inference.inference.OpenAI") as client_class:
        client_class.side_effect = openai.OpenAIError(
            "The api_key client option must be set either by passing api_key "
            "to the client or by setting the OPENAI_API_KEY environment variable"
        )
        with pytest.raises(AIConfigurationError) as error:
            infer("Say hello", "content", Answer)
    client_class.assert_called_once_with()
    client_class.return_value.responses.create.assert_not_called()
    assert FAKE_TOKEN not in str(error.value)


@pytest.mark.unit
def test_infer_sends_authenticated_strict_structured_request():
    """The request uses the fixed model and strict schema for the response type."""
    prompt = "Answer briefly"
    content = "What is 2 + 2?"
    with patch("ai_inference.inference.OpenAI") as client_class:
        client_class.return_value.responses.create.return_value = complete_response()

        infer(prompt, content, Answer)

    create = client_class.return_value.responses.create
    create.assert_called_once()
    request = create.call_args.kwargs
    assert request["model"] == "gpt-6-luna"
    assert request["instructions"] == prompt
    assert request["input"] == content
    response_format = request["text"]["format"]
    assert response_format["type"] == "json_schema"
    assert response_format["strict"] is True
    assert response_format["schema"] == Answer.model_json_schema()


@pytest.mark.unit
def test_infer_returns_validated_response_model():
    """A completed inference returns an instance of the requested model."""
    with patch("ai_inference.inference.OpenAI") as client_class:
        client_class.return_value.responses.create.return_value = complete_response(
            "structured answer"
        )

        answer = infer("Answer briefly", "content", Answer)

    assert isinstance(answer, Answer)
    assert answer == Answer(text="structured answer")


@pytest.mark.unit
def test_infer_supports_different_response_models():
    """The interface rejects model selection and builds schema per response type."""
    assert tuple(inspect.signature(infer).parameters) == (
        "prompt",
        "content",
        "response_model",
    )

    with patch("ai_inference.inference.OpenAI") as client_class:
        create = client_class.return_value.responses.create
        create.side_effect = [
            complete_response(),
            Mock(status="completed", output_text=CountAnswer(count=3).model_dump_json()),
        ]

        with pytest.raises(TypeError):
            infer("Count", "three", Answer, model="another-model")
        infer("Answer", "hello", Answer)
        infer("Count", "three", CountAnswer)

    assert create.call_count == 2
    schemas = [
        call.kwargs["text"]["format"]["schema"]
        for call in create.call_args_list
    ]
    assert schemas == [Answer.model_json_schema(), CountAnswer.model_json_schema()]


@pytest.mark.unit
def test_invalid_token_raises_authentication_error():
    """Provider authentication failures map cleanly without exposing the token."""
    with patch("ai_inference.inference.OpenAI") as client_class:
        client_class.return_value.responses.create.side_effect = provider_error(
            openai.AuthenticationError
        )

        with pytest.raises(AIInferenceError) as error:
            infer("Say hello", "content", Answer)

    assert type(error.value).__name__ == "AIAuthenticationError"
    assert FAKE_TOKEN not in str(error.value)


@pytest.mark.unit
@pytest.mark.parametrize("prompt", ["", "   ", "\n\t"])
def test_blank_prompt_rejected_before_provider_call(prompt):
    """Blank prompts are rejected without creating a provider client."""
    with patch("ai_inference.inference.OpenAI") as client_class:
        with pytest.raises(ValueError):
            infer(prompt, "content", Answer)

    client_class.assert_not_called()


@pytest.mark.unit
@pytest.mark.parametrize(
    "response_model",
    [dict, Answer(text="not a class")],
    ids=["non-pydantic-class", "model-instance"],
)
def test_non_basemodel_response_model_rejected(response_model):
    """Only Pydantic model classes are accepted as response models."""
    with patch("ai_inference.inference.OpenAI") as client_class:
        with pytest.raises(TypeError):
            infer("Say hello", "content", response_model)

    client_class.assert_not_called()


def refusal_response():
    """Construct a Responses API result in which the model refused."""
    part = Mock(type="refusal", refusal="I cannot help with that.")
    return Mock(status="completed", output_text="", output=[Mock(type="message", content=[part])])


def provider_error(error_class):
    """Build an OpenAI SDK error whose own message echoes the token."""
    message = f"Incorrect API key provided: {FAKE_TOKEN}"
    if error_class is openai.AuthenticationError:
        return error_class(message, response=Mock(status_code=401, headers={}), body=None)
    if error_class is openai.InternalServerError:
        return error_class(message, response=Mock(status_code=500, headers={}), body=None)
    if error_class is openai.BadRequestError:
        return error_class(message, response=Mock(status_code=400, headers={}), body=None)
    return error_class(message=message, request=Mock())


@pytest.mark.unit
@pytest.mark.parametrize(
    "outcome, expected_error",
    [
        pytest.param("refusal", "AIRefusalError", id="refusal"),
        pytest.param("incomplete", "AIIncompleteResponseError", id="incomplete"),
        pytest.param("provider-api", "AIProviderError", id="provider-api-error"),
        pytest.param("provider-connection", "AIProviderError", id="provider-connection-error"),
        pytest.param("invalid-json", "AIInvalidOutputError", id="invalid-json"),
        pytest.param("invalid-model-output", "AIInvalidOutputError", id="invalid-model-output"),
    ],
)
def test_provider_failures_raise_errors_without_returning_model(outcome, expected_error):
    """Provider and output failures raise errors instead of returning a model."""
    with patch("ai_inference.inference.OpenAI") as client_class:
        create = client_class.return_value.responses.create
        if outcome == "refusal":
            create.return_value = refusal_response()
        elif outcome == "incomplete":
            create.return_value = Mock(status="incomplete", output_text="")
        elif outcome == "provider-api":
            create.side_effect = provider_error(openai.InternalServerError)
        elif outcome == "provider-connection":
            create.side_effect = provider_error(openai.APIConnectionError)
        elif outcome == "invalid-json":
            create.return_value = Mock(status="completed", output_text="not json")
        else:
            create.return_value = Mock(status="completed", output_text='{"text": 42}')

        with pytest.raises(AIInferenceError) as error:
            infer("Say hello", "content", Answer)

    assert type(error.value).__name__ == expected_error


@pytest.mark.unit
def test_unsupported_schema_fails_explicitly():
    """A mocked schema rejection becomes an inference error, not a result."""
    with patch("ai_inference.inference.OpenAI") as client_class:
        client_class.return_value.responses.create.side_effect = provider_error(
            openai.BadRequestError
        )

        with pytest.raises(AIInferenceError) as error:
            infer("Summarize metadata", "content", UnsupportedSchema)

    assert FAKE_TOKEN not in str(error.value)


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
