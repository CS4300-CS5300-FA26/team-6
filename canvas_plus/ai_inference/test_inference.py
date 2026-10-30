"""AI inference boundary tests; no requests reach OpenAI."""

import logging
import inspect
from io import BytesIO
from unittest.mock import Mock, patch

import openai
import pytest
from openai.lib._pydantic import to_strict_json_schema
from pydantic import BaseModel

from .exceptions import AIConfigurationError, AIInferenceError, AIProviderError
from .inference import MAX_RETRIES, build_content, delete_uploaded_files, infer

INFERENCE_MODULE = infer.__module__

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
    with patch(f"{INFERENCE_MODULE}.OpenAI") as client_class:
        client_class.return_value.responses.create.return_value = complete_response()
        infer("Say hello", "content", Answer)
    client_class.assert_called_once_with()


@pytest.mark.unit
def test_missing_openai_api_key_raises_configuration_error_without_provider_call(
    monkeypatch,
):
    """Missing SDK environment credentials fail clearly before an API request."""
    monkeypatch.delenv("OPENAI_API_KEY")
    with patch(f"{INFERENCE_MODULE}.OpenAI") as client_class:
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
    with patch(f"{INFERENCE_MODULE}.OpenAI") as client_class:
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
    assert response_format["schema"] == to_strict_json_schema(Answer)


@pytest.mark.unit
def test_infer_returns_validated_response_model():
    """A completed inference returns an instance of the requested model."""
    with patch(f"{INFERENCE_MODULE}.OpenAI") as client_class:
        client_class.return_value.responses.create.return_value = complete_response(
            "structured answer"
        )

        answer = infer("Answer briefly", "content", Answer)

    assert isinstance(answer, Answer)
    assert answer == Answer(text="structured answer")


@pytest.mark.unit
def test_build_content_accepts_text_only():
    """Text-only content is built without contacting the Files API."""
    with patch(f"{INFERENCE_MODULE}.OpenAI") as client_class:
        content = build_content(prompt="Summarize this text.")

    assert content == [{
        "role": "user",
        "content": [{"type": "input_text", "text": "Summarize this text."}],
    }]
    client_class.return_value.files.create.assert_not_called()


@pytest.mark.unit
@pytest.mark.parametrize(
    "text, files",
    [
        pytest.param(None, (), id="no-input"),
        pytest.param("", (), id="empty-text"),
        pytest.param(" \n\t", (), id="whitespace-text"),
    ],
)
def test_build_content_rejects_empty_content_before_provider_call(text, files):
    """Empty content is rejected before creating the provider client."""
    with patch(f"{INFERENCE_MODULE}.OpenAI") as client_class:
        with pytest.raises(ValueError):
            build_content(prompt=text, files=files)

    client_class.assert_not_called()


@pytest.mark.unit
def test_build_content_accepts_named_in_memory_bytes():
    """Named byte content is uploaded without requiring a local file."""
    file_bytes = b"document contents"
    with patch(f"{INFERENCE_MODULE}.OpenAI") as client_class:
        client_class.return_value.files.create.return_value = Mock(id="file-memory")

        content = build_content(prompt="Placeholder", files=[("report.txt", file_bytes)])

    assert content == [{
        "role": "user",
        "content": [
            {"type": "input_text", "text": "Placeholder"},
            {"type": "input_file", "file_id": "file-memory"}
            ],
    }]
    client_class.return_value.files.create.assert_called_once_with(
        file=("report.txt", file_bytes),
        purpose="user_data",
    )


@pytest.mark.unit
def test_build_content_accepts_multiple_named_byte_files():
    """Multiple files from arbitrary storage can be supplied as named bytes."""
    file_inputs = [("one.txt", b"one"), ("two.txt", b"two")]
    with patch(f"{INFERENCE_MODULE}.OpenAI") as client_class:
        client_class.return_value.files.create.side_effect = [
            Mock(id="file-one"),
            Mock(id="file-two"),
        ]

        content = build_content(prompt="Compare", files=file_inputs)

    assert content == [{
        "role": "user",
        "content": [
            {"type": "input_text", "text": "Compare"},
            {"type": "input_file", "file_id": "file-one"},
            {"type": "input_file", "file_id": "file-two"},
        ],
    }]
    assert [call.kwargs for call in client_class.return_value.files.create.call_args_list] == [
        {"file": file_input, "purpose": "user_data"}
        for file_input in file_inputs
    ]


@pytest.mark.unit
def test_build_content_accepts_named_binary_stream_and_preserves_ownership():
    """Named caller-owned streams upload from their current position and stay open."""
    stream = BytesIO(b"downloaded API response")
    stream.name = "download.pdf"
    with patch(f"{INFERENCE_MODULE}.OpenAI") as client_class:
        client_class.return_value.files.create.return_value = Mock(id="file-stream")

        content = build_content(prompt="Placeholder", files=[stream])

    assert content == [{
        "role": "user",
        "content": [
            {"type": "input_text", "text": "Placeholder"},
            {"type": "input_file", "file_id": "file-stream"}
            ],
    }]
    client_class.return_value.files.create.assert_called_once_with(
        file=stream,
        purpose="user_data",
    )
    assert not stream.closed


@pytest.mark.unit
def test_build_content_accepts_named_pair_with_binary_stream():
    """A filename pair allows streams whose source does not provide a name."""
    stream = BytesIO(b"database blob")
    with patch(f"{INFERENCE_MODULE}.OpenAI") as client_class:
        client_class.return_value.files.create.return_value = Mock(id="file-db")

        content = build_content(prompt="Placeholder", files=[("stored.pdf", stream)])

    assert content[0]["content"] == [
        {"type": "input_text", "text": "Placeholder"},
        {"type": "input_file", "file_id": "file-db"}
    ]
    client_class.return_value.files.create.assert_called_once_with(
        file=("stored.pdf", stream),
        purpose="user_data",
    )
    assert not stream.closed


@pytest.mark.unit
def test_build_content_keeps_local_path_as_convenience(tmp_path):
    """Local paths continue to work as a convenience input source."""
    source_file = tmp_path / "source.txt"
    source_file.write_bytes(b"local file")
    with patch(f"{INFERENCE_MODULE}.OpenAI") as client_class:
        client_class.return_value.files.create.return_value = Mock(id="file-local")

        content = build_content(prompt="Placeholder", files=[source_file])

    assert content[0]["content"] == [
        {"type": "input_text", "text": "Placeholder"},
        {"type": "input_file", "file_id": "file-local"}
    ]
    upload = client_class.return_value.files.create.call_args.kwargs
    assert upload["purpose"] == "user_data"
    assert upload["file"].name == str(source_file)


@pytest.mark.unit
@pytest.mark.parametrize(
    "files",
    [
        pytest.param([BytesIO(b"unnamed")], id="unnamed-stream"),
        pytest.param([("", b"bytes")], id="empty-filename"),
        pytest.param([("file.bin", "text-not-bytes")], id="text-content"),
        pytest.param([("file.bin", object())], id="non-binary-content"),
        pytest.param([object()], id="non-path-object"),
    ],
)
def test_build_content_rejects_invalid_file_inputs_before_provider_call(files):
    """Malformed, unnamed, or non-binary files are rejected locally."""
    with patch(f"{INFERENCE_MODULE}.OpenAI") as client_class:
        with pytest.raises((TypeError, ValueError)):
            build_content(prompt="Placeholder", files=files)

    client_class.assert_not_called()


@pytest.mark.unit
def test_build_content_stream_read_failure_raises_typed_error():
    """A stream read failure is translated to a typed inference error."""
    stream = BytesIO(b"content")
    stream.name = "unreadable.txt"
    with patch(f"{INFERENCE_MODULE}.OpenAI") as client_class:
        client_class.return_value.files.create.side_effect = OSError("read failed")

        with pytest.raises(AIInferenceError):
            build_content(prompt="Placeholder", files=[stream])

    assert not stream.closed


@pytest.mark.unit
def test_build_content_local_read_failure_raises_typed_error(tmp_path):
    """A missing local path is reported as an inference error."""
    missing_file = tmp_path / "missing.txt"
    with patch(f"{INFERENCE_MODULE}.OpenAI") as client_class:
        with pytest.raises(AIInferenceError):
            build_content(prompt="Placeholder", files=[missing_file])

    client_class.return_value.files.create.assert_not_called()


@pytest.mark.unit
def test_build_content_deletes_earlier_uploads_when_later_upload_fails():
    """A failed upload cleans up files already uploaded and raises a typed error."""
    with patch(f"{INFERENCE_MODULE}.OpenAI") as client_class:
        client = client_class.return_value
        client.files.create.side_effect = [Mock(id="file-1"), openai.OpenAIError("boom")]
        with pytest.raises(AIProviderError):
            build_content(prompt="Placeholder", files=[("a.txt", b"a"), ("b.txt", b"b")])

    client.files.delete.assert_called_once_with("file-1")


@pytest.mark.unit
def test_infer_supports_different_response_models():
    """The interface rejects model selection and builds schema per response type."""
    assert tuple(inspect.signature(infer).parameters) == (
        "system_prompt",
        "content",
        "response_model",
    )

    with patch(f"{INFERENCE_MODULE}.OpenAI") as client_class:
        create = client_class.return_value.responses.create
        create.side_effect = [
            complete_response(),
            Mock(status="completed", output_text=CountAnswer(count=3).model_dump_json()),
        ]

        with pytest.raises(TypeError):
            infer(  # pylint: disable=unexpected-keyword-arg
                "Count",
                "three",
                Answer,
                **{"model": "another-model"},
            )
        infer("Answer", "hello", Answer)
        infer("Count", "three", CountAnswer)

    assert create.call_count == 2
    schemas = [
        call.kwargs["text"]["format"]["schema"]
        for call in create.call_args_list
    ]
    assert schemas == [
        to_strict_json_schema(Answer),
        to_strict_json_schema(CountAnswer),
    ]


@pytest.mark.unit
def test_invalid_token_raises_authentication_error():
    """Provider authentication failures map cleanly without exposing the token."""
    with patch(f"{INFERENCE_MODULE}.OpenAI") as client_class:
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
    with patch(f"{INFERENCE_MODULE}.OpenAI") as client_class:
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
    with patch(f"{INFERENCE_MODULE}.OpenAI") as client_class:
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
        pytest.param("upload-failure", "AIProviderError", id="file-upload-error"),
    ],
)
def test_provider_failures_raise_errors_without_returning_model(
    outcome, expected_error, tmp_path
):
    """Provider, output, and upload failures never return success or partial content."""
    with patch(f"{INFERENCE_MODULE}.OpenAI") as client_class:
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
        elif outcome == "upload-failure":
            client_class.return_value.files.create.side_effect = provider_error(
                openai.APIConnectionError
            )
        else:
            create.return_value = Mock(status="completed", output_text='{"text": 42}')

        with pytest.raises(AIInferenceError) as error:
            if outcome == "upload-failure":
                source_file = tmp_path / "source.txt"
                source_file.write_text("source text", encoding="utf-8")
                build_content(prompt="include this text", files=[source_file])
            else:
                infer("Say hello", "content", Answer)

    assert type(error.value).__name__ == expected_error
    if outcome == "upload-failure":
        client_class.return_value.files.create.assert_called_once()


@pytest.mark.unit
def test_unsupported_schema_fails_explicitly():
    """A mocked schema rejection becomes an inference error, not a result."""
    with patch(f"{INFERENCE_MODULE}.OpenAI") as client_class:
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
    pytest.param("upload-failure", id="upload-failure"),
])
def test_token_absent_from_logs_and_errors(outcome, caplog, tmp_path):
    """Given any outcome, neither logs nor caller-visible errors contain the token."""
    caplog.set_level(logging.DEBUG)
    with patch(f"{INFERENCE_MODULE}.OpenAI") as client_class:
        create = client_class.return_value.responses.create
        if outcome is None:
            create.return_value = complete_response()
        elif outcome == "refusal":
            create.return_value = refusal_response()
        elif outcome == "upload-failure":
            client_class.return_value.files.create.side_effect = provider_error(
                openai.APIConnectionError
            )
        else:
            create.side_effect = outcome
        if outcome is None:
            infer("Say hello", "content", Answer)
        elif outcome == "upload-failure":
            source_file = tmp_path / "source.txt"
            source_file.write_text("source text", encoding="utf-8")
            with pytest.raises(AIInferenceError) as error:
                build_content(prompt="Placeholder", files=[source_file])
            assert FAKE_TOKEN not in str(error.value)
            assert FAKE_TOKEN not in repr(error.value)
        else:
            with pytest.raises(AIInferenceError) as error:
                infer("Say hello", "content", Answer)
            assert FAKE_TOKEN not in str(error.value)
            assert FAKE_TOKEN not in repr(error.value)
    assert FAKE_TOKEN not in caplog.text


def status_error(error_class):
    """Build an SDK status error whose message echoes the token."""
    status = {openai.NotFoundError: 404, openai.RateLimitError: 429}[error_class]
    return error_class(
        f"Incorrect API key provided: {FAKE_TOKEN}",
        response=Mock(status_code=status, headers={}),
        body=None,
    )


def uploaded_content(*file_ids):
    """Build user content shaped like build_content output."""
    return [{
        "role": "user",
        "content": [{"type": "input_text", "text": "Placeholder"}]
        + [{"type": "input_file", "file_id": file_id} for file_id in file_ids],
    }]


@pytest.fixture(name="no_sleep")
def fixture_no_sleep():
    """Disable real backoff delays and make jitter deterministic."""
    with patch(f"{INFERENCE_MODULE}.time.sleep") as sleep, patch(
        f"{INFERENCE_MODULE}.random.uniform", side_effect=lambda low, high: high
    ):
        yield sleep


@pytest.mark.unit
def test_delete_uploaded_file_deletes_every_file_in_order():
    """All input_file items are deleted by id."""
    with patch(f"{INFERENCE_MODULE}.OpenAI") as client_class:
        delete_uploaded_files(uploaded_content("file-one", "file-two"))

    client_class.assert_called_once_with()
    delete = client_class.return_value.files.delete
    assert [call.args for call in delete.call_args_list] == [("file-one",), ("file-two",)]


@pytest.mark.unit
def test_delete_uploaded_file_text_only_makes_no_provider_call(monkeypatch):
    """Without uploaded files no client is created, even with no API key."""
    monkeypatch.delenv("OPENAI_API_KEY")
    with patch(f"{INFERENCE_MODULE}.OpenAI") as client_class:
        delete_uploaded_files(uploaded_content())

    client_class.assert_not_called()


@pytest.mark.unit
def test_delete_uploaded_file_skips_file_items_without_id():
    """File items with a missing or empty id are skipped."""
    content = uploaded_content("file-one")
    content[0]["content"].extend([
        {"type": "input_file"},
        {"type": "input_file", "file_id": ""},
        {"type": "input_file", "file_id": None},
    ])
    with patch(f"{INFERENCE_MODULE}.OpenAI") as client_class:
        delete_uploaded_files(content)

    client_class.return_value.files.delete.assert_called_once_with("file-one")


@pytest.mark.unit
@pytest.mark.parametrize(
    "content",
    [
        pytest.param(None, id="none"),
        pytest.param("text", id="string"),
        pytest.param({"content": []}, id="dict"),
        pytest.param([], id="empty-list"),
        pytest.param([{"role": "user"}], id="missing-content-key"),
    ],
)
def test_delete_uploaded_file_rejects_invalid_structure_before_provider_call(content):
    """Malformed content is rejected without creating a provider client."""
    with patch(f"{INFERENCE_MODULE}.OpenAI") as client_class:
        with pytest.raises(ValueError):
            delete_uploaded_files(content)

    client_class.assert_not_called()


@pytest.mark.unit
def test_delete_uploaded_file_missing_api_key_raises_configuration_error(monkeypatch):
    """A missing key fails clearly and no deletion is attempted."""
    monkeypatch.delenv("OPENAI_API_KEY")
    with patch(f"{INFERENCE_MODULE}.OpenAI") as client_class:
        client_class.side_effect = openai.OpenAIError(
            "The api_key client option must be set either by passing api_key "
            "to the client or by setting the OPENAI_API_KEY environment variable"
        )
        with pytest.raises(AIConfigurationError):
            delete_uploaded_files(uploaded_content("file-one"))

    client_class.return_value.files.delete.assert_not_called()


@pytest.mark.unit
def test_delete_uploaded_file_client_init_failure_raises_authentication_error():
    """Other client initialization errors map to AIAuthenticationError."""
    with patch(f"{INFERENCE_MODULE}.OpenAI") as client_class:
        client_class.side_effect = openai.OpenAIError("boom")
        with pytest.raises(AIInferenceError) as error:
            delete_uploaded_files(uploaded_content("file-one"))

    assert type(error.value).__name__ == "AIAuthenticationError"


@pytest.mark.unit
def test_delete_uploaded_file_ignores_already_deleted_file():
    """A not-found file is treated as deleted and later files are still processed."""
    with patch(f"{INFERENCE_MODULE}.OpenAI") as client_class:
        delete = client_class.return_value.files.delete
        delete.side_effect = [status_error(openai.NotFoundError), None]

        delete_uploaded_files(uploaded_content("file-one", "file-two"))

    assert [call.args for call in delete.call_args_list] == [("file-one",), ("file-two",)]


@pytest.mark.unit
def test_delete_uploaded_file_rate_limit_retries_with_backoff_until_success(no_sleep):
    """A rate-limited delete is retried with jittered exponential backoff."""
    with patch(f"{INFERENCE_MODULE}.OpenAI") as client_class:
        delete = client_class.return_value.files.delete
        delete.side_effect = [
            status_error(openai.RateLimitError),
            status_error(openai.RateLimitError),
            None,
        ]
        with patch(f"{INFERENCE_MODULE}.random.uniform", return_value=0.5) as uniform:
            delete_uploaded_files(uploaded_content("file-one"))

    assert delete.call_count == 3
    assert [call.args for call in delete.call_args_list] == [("file-one",)] * 3
    uniform.assert_called_once_with(0, 1)
    no_sleep.assert_called_once_with(0.5)


@pytest.mark.unit
def test_delete_uploaded_file_rate_limit_exhaustion_raises_provider_error(no_sleep):
    """Persistent rate limiting raises a typed error after bounded retries."""
    with patch(f"{INFERENCE_MODULE}.OpenAI") as client_class:
        delete = client_class.return_value.files.delete
        delete.side_effect = status_error(openai.RateLimitError)

        with pytest.raises(AIInferenceError) as error:
            delete_uploaded_files(uploaded_content("file-one", "file-two"))

    assert type(error.value).__name__ == "AIProviderError"
    assert FAKE_TOKEN not in str(error.value)
    # One initial attempt plus MAX_RETRIES retries; the second file is never tried.
    assert delete.call_count == 1 + MAX_RETRIES
    assert no_sleep.call_count == MAX_RETRIES - 1


@pytest.mark.unit
def test_delete_uploaded_file_not_found_during_retry_is_success(no_sleep):
    """A file that disappears while retrying counts as deleted."""
    with patch(f"{INFERENCE_MODULE}.OpenAI") as client_class:
        delete = client_class.return_value.files.delete
        delete.side_effect = [
            status_error(openai.RateLimitError),
            status_error(openai.NotFoundError),
        ]

        delete_uploaded_files(uploaded_content("file-one"))

    assert delete.call_count == 2
    no_sleep.assert_not_called()


@pytest.mark.unit
def test_delete_uploaded_file_provider_error_during_retry_raises_provider_error(no_sleep):
    """A non-rate-limit failure while retrying stops immediately."""
    with patch(f"{INFERENCE_MODULE}.OpenAI") as client_class:
        delete = client_class.return_value.files.delete
        delete.side_effect = [
            status_error(openai.RateLimitError),
            provider_error(openai.APIConnectionError),
        ]

        with pytest.raises(AIInferenceError) as error:
            delete_uploaded_files(uploaded_content("file-one"))

    assert type(error.value).__name__ == "AIProviderError"
    assert FAKE_TOKEN not in str(error.value)
    no_sleep.assert_not_called()


@pytest.mark.unit
@pytest.mark.parametrize(
    "error_class",
    [openai.APIConnectionError, openai.InternalServerError],
)
def test_delete_uploaded_file_other_failure_raises_provider_error_without_token(error_class):
    """Other deletion failures are typed, abort the loop, and do not leak the token."""
    with patch(f"{INFERENCE_MODULE}.OpenAI") as client_class:
        delete = client_class.return_value.files.delete
        delete.side_effect = provider_error(error_class)

        with pytest.raises(AIInferenceError) as error:
            delete_uploaded_files(uploaded_content("file-one", "file-two"))

    assert type(error.value).__name__ == "AIProviderError"
    assert FAKE_TOKEN not in str(error.value)
    assert FAKE_TOKEN not in repr(error.value)
    delete.assert_called_once_with("file-one")


@pytest.mark.unit
@pytest.mark.parametrize("first_error", [None, openai.RateLimitError])
def test_delete_uploaded_file_authentication_failure_raises_authentication_error(
    first_error, no_sleep
):
    """Rejected credentials map to AIAuthenticationError, including during retries."""
    with patch(f"{INFERENCE_MODULE}.OpenAI") as client_class:
        delete = client_class.return_value.files.delete
        auth_error = provider_error(openai.AuthenticationError)
        delete.side_effect = (
            [status_error(first_error), auth_error] if first_error else auth_error
        )

        with pytest.raises(AIInferenceError) as error:
            delete_uploaded_files(uploaded_content("file-one", "file-two"))

    assert type(error.value).__name__ == "AIAuthenticationError"
    assert FAKE_TOKEN not in str(error.value)


@pytest.mark.unit
def test_delete_uploaded_file_cleans_up_build_content_output():
    """Integration: ids uploaded by build_content are the ones deleted."""
    with patch(f"{INFERENCE_MODULE}.OpenAI") as client_class:
        client_class.return_value.files.create.side_effect = [
            Mock(id="file-one"),
            Mock(id="file-two"),
        ]
        content = build_content(
            prompt="Compare", files=[("one.txt", b"one"), ("two.txt", b"two")]
        )

        delete_uploaded_files(content)

    delete = client_class.return_value.files.delete
    assert [call.args for call in delete.call_args_list] == [("file-one",), ("file-two",)]


@pytest.mark.unit
def test_delete_uploaded_file_token_absent_from_logs(caplog, no_sleep):
    """Neither success, retry, nor failure paths log the token."""
    caplog.set_level(logging.DEBUG)
    with patch(f"{INFERENCE_MODULE}.OpenAI") as client_class:
        delete = client_class.return_value.files.delete
        delete.side_effect = status_error(openai.RateLimitError)
        with pytest.raises(AIInferenceError):
            delete_uploaded_files(uploaded_content("file-one"))

    assert no_sleep.called
    assert FAKE_TOKEN not in caplog.text
