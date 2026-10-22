"""Canvas HTTP boundary tests; no requests reach a real Canvas server."""

from unittest.mock import Mock, patch

import pytest
import requests

from .canvas_client import CanvasAPIError, CanvasAuthenticationError, list_courses


@pytest.fixture(autouse=True)
def canvas_settings(settings):
    """Use a fixed, non-secret Canvas origin."""
    settings.CANVAS_BASE_URL = "https://canvas.example.edu/"


def response(courses, *, status=200, next_url=None):
    """Construct a requests-like response, including its pagination links."""
    result = Mock(status_code=status)
    result.json.return_value = courses
    result.links = {"next": {"url": next_url}} if next_url else {}
    return result


@pytest.mark.unit
def test_courses_include_every_page_and_authenticate_each_request():
    """Given two pages, return both and preserve the opaque next-page query."""
    next_url = "https://canvas.example.edu/api/v1/courses?opaque=next"
    with patch("accounts.canvas_client.requests.get", side_effect=[
        response([{"id": 1, "name": "First"}], next_url=next_url),
        response([{"id": 2, "name": "Second"}]),
    ]) as get:
        assert [course["name"] for course in list_courses("fake-token")] == ["First", "Second"]
    assert get.call_count == 2
    assert get.call_args_list[1].args == (next_url,)
    assert get.call_args_list[0].kwargs["params"]["enrollment_state"] == "active"
    assert get.call_args_list[1].kwargs["params"] is None
    for call in get.call_args_list:
        assert call.kwargs["headers"]["Authorization"] == "Bearer fake-token"
        assert call.kwargs["timeout"] == 10
        assert call.kwargs["allow_redirects"] is False


@pytest.mark.unit
@pytest.mark.parametrize("next_url", [
    "https://untrusted.example/api/v1/courses",
    "http://canvas.example.edu/api/v1/courses",
    "https://user:password@canvas.example.edu/api/v1/courses",
])
def test_pagination_does_not_send_credentials_to_another_origin(next_url):
    """A pagination link must never leak the bearer token to another origin."""
    with patch(
        "accounts.canvas_client.requests.get", return_value=response([], next_url=next_url)
    ) as get:
        with pytest.raises(CanvasAPIError):
            list_courses("fake-token")
    assert get.call_count == 1


@pytest.mark.unit
def test_repeated_pagination_link_stops_instead_of_looping():
    """A repeated next link must not hang the web request indefinitely."""
    url = "https://canvas.example.edu/api/v1/courses"
    with patch(
        "accounts.canvas_client.requests.get", return_value=response([], next_url=url)
    ) as get:
        with pytest.raises(CanvasAPIError):
            list_courses("fake-token")
    assert get.call_count == 1


@pytest.mark.unit
@pytest.mark.parametrize("status", [302, 403, 429, 500])
def test_other_http_failures_are_not_invalid_tokens(status):
    """Redirects, permissions, throttling, and outages have a separate outcome."""
    with patch("accounts.canvas_client.requests.get", return_value=response({}, status=status)):
        with pytest.raises(CanvasAPIError):
            list_courses("fake-token")


@pytest.mark.unit
def test_rejected_credentials_on_a_later_page_expire_the_connection():
    """Authentication must be checked for every page, not just the first."""
    with patch("accounts.canvas_client.requests.get", side_effect=[
        response([], next_url="https://canvas.example.edu/api/v1/courses?page=2"),
        response({}, status=401),
    ]):
        with pytest.raises(CanvasAuthenticationError):
            list_courses("fake-token")


@pytest.mark.unit
@pytest.mark.parametrize("error", [requests.Timeout, requests.ConnectionError])
def test_network_failures_have_a_safe_error(error):
    """Network exceptions are translated without exposing request credentials."""
    with patch("accounts.canvas_client.requests.get", side_effect=error("fake-token")):
        with pytest.raises(CanvasAPIError) as caught:
            list_courses("fake-token")
    assert "fake-token" not in str(caught.value)


@pytest.mark.unit
@pytest.mark.parametrize("payload", [{"error": "not a list"}, ["not a course"], [{"id": 1}]])
def test_malformed_course_data_is_not_treated_as_success(payload):
    """Unexpected JSON shapes cannot silently become course names."""
    with patch("accounts.canvas_client.requests.get", return_value=response(payload)):
        with pytest.raises(CanvasAPIError):
            list_courses("fake-token")
