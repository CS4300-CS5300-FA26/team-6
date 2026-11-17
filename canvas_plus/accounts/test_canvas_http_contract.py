"""G1/G2: real HTTP response headers at Canvas pagination and throttling seams.

As a student, I want all Canvas pages and recoverable quota failures handled
faithfully, so that my work stays visible without losing my saved connection.
Contracts: Canvas basics/file.pagination and basics/file.throttling.
"""

import json
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest
import requests
from cryptography.fernet import Fernet
from django.urls import reverse
from django.utils import timezone as django_timezone

from accounts.canvas_client import (
    CanvasAPIError,
    CanvasAuthenticationError,
    list_courses,
    list_graded_submissions,
    list_upcoming_assignments,
)
from accounts.models import CanvasConnection

BASE = "https://canvas.example.edu"
TOKEN = "contract-test-token"
COURSE = {"id": 7, "name": "Software Engineering"}
SINCE = datetime(2026, 10, 1, tzinfo=timezone.utc)
PATHS = {
    "courses": "/api/v1/courses",
    "assignments": "/api/v1/courses/7/assignments",
    "graded": "/api/v1/courses/7/students/submissions",
}


@pytest.fixture(autouse=True)
def canvas_settings(settings):
    """Keep every absolute pagination URL on the configured Canvas origin."""
    settings.CANVAS_BASE_URL = BASE


def http_response(payload, *, status=200, headers=None):
    """Use requests' actual JSON decoding and case-insensitive header/Link parsing."""
    response = requests.Response()
    response.status_code = status
    response._content = json.dumps(payload).encode()  # pylint: disable=protected-access
    response.headers.update({"Content-Type": "application/json", **(headers or {})})
    return response


def quota_response():
    """Canvas's documented 429 status and floating point quota/cost headers."""
    return http_response(
        {"errors": [{"message": "Rate Limit Exceeded"}]},
        status=429,
        headers={"X-Rate-Limit-Remaining": "0.0", "X-Request-Cost": "1.25"},
    )


def records(path, number):
    """Distinct valid records make loss, duplication and normalization observable."""
    name = f"Work {number}"
    if path == "courses":
        return {"id": number, "name": name}
    if path == "assignments":
        return {"id": number, "name": name, "due_at": None}
    return {
        "assignment": {"id": number, "name": name},
        "score": 90,
        "graded_at": django_timezone.now().isoformat(),
        "posted_at": django_timezone.now().isoformat(),
        "excused": False,
    }


def fetch(path, session):
    """Exercise the public list entry point, including normalization and buckets."""
    if path == "courses":
        return list_courses(TOKEN, session=session)
    if path == "assignments":
        return list_upcoming_assignments(TOKEN, [COURSE], session=session)
    return list_graded_submissions(TOKEN, [COURSE], SINCE, session=session)


def names(path, result):
    """Read the student-visible name after each endpoint's normalization."""
    key = {"courses": "name", "assignments": "title", "graded": "assignment"}[path]
    return [item[key] for item in result]


@pytest.mark.unit
@pytest.mark.parametrize("path", PATHS)
def test_lowercase_link_follows_short_pages_and_preserves_opaque_query(path):
    """Given short pages and no last link, every record is returned once via next."""
    url = BASE + PATHS[path]
    next_url = (
        f"{url}?cursor=a%2Fb%2Bz%3D&include%5B%5D=assignment"
        "&include%5B%5D=submission&per_page=2&opaque=keep+this&opaque=%252F"
    )
    first_page = http_response([records(path, 1), records(path, 2)], headers={
        "link": f'<{url}>; rel="current", <{next_url}>; rel="next", <{url}>; rel="first"',
    })
    final_page = http_response([records(path, 3)], headers={
        "link": f'<{next_url}>; rel="current", <{url}>; rel="first"',
    })

    def get(request_url, **kwargs):
        if request_url == next_url:
            assert kwargs["params"] is None
            return final_page
        assert request_url == url
        assert kwargs["params"]["per_page"] == 100
        # The overdue bucket is a separate request, not another pagination page.
        if kwargs["params"].get("bucket") == "overdue":
            return http_response([])
        return first_page

    session = Mock(spec=requests.Session)
    session.get.side_effect = get
    result = fetch(path, session)

    assert "link" in list(first_page.headers)
    assert "last" not in first_page.links
    assert first_page.links["next"]["url"] == next_url
    assert names(path, result) == ["Work 1", "Work 2", "Work 3"]
    next_calls = [call for call in session.get.call_args_list if call.args == (next_url,)]
    assert len(next_calls) == 1
    assert next_calls[0].kwargs == {
        "headers": {"Authorization": f"Bearer {TOKEN}"},
        "params": None,
        "timeout": 10,
        "allow_redirects": False,
    }
    assert session.get.call_count == (3 if path == "assignments" else 2)


@pytest.mark.unit
@pytest.mark.parametrize("path", PATHS)
def test_quota_exhaustion_is_retryable_and_later_attempt_loads_data(path):
    """Given exhausted quota, 429 is temporary; a separate later attempt succeeds."""
    throttled = True

    def get(url, **kwargs):
        assert url == BASE + PATHS[path]
        if kwargs["params"].get("bucket") == "overdue":
            return http_response([])
        if throttled:
            return quota_response()
        return http_response([records(path, 1)], headers={
            "X-Rate-Limit-Remaining": "200.0", "X-Request-Cost": "0.75",
        })

    session = Mock(spec=requests.Session)
    session.get.side_effect = get
    with pytest.raises(CanvasAPIError, match="Please try again") as raised:
        fetch(path, session)
    assert not isinstance(raised.value, CanvasAuthenticationError)
    # No automatic retry is required: the first attempt ends in a service error.
    attempts = [
        call for call in session.get.call_args_list
        if call.kwargs["params"].get("bucket") != "overdue"
    ]
    assert len(attempts) == 1

    throttled = False
    assert names(path, fetch(path, session)) == ["Work 1"]


@pytest.mark.integration
@pytest.mark.django_db
@pytest.mark.parametrize("throttled_path", PATHS)
def test_throttled_dashboard_preserves_connection_and_recovers(
    throttled_path, client, django_user_model, settings,
):
    """Given 429, preserve credentials and feedback; grade-only failure keeps work."""
    settings.CANVAS_TOKEN_ENCRYPTION_KEY = Fernet.generate_key().decode()
    user = django_user_model.objects.create_user(username="quota-student")
    connection = CanvasConnection(user=user, canvas_url=BASE)
    connection.set_token(TOKEN)
    connection.save()
    original_ciphertext = connection.encrypted_token
    client.force_login(user)
    throttled = True

    def get(_session, url, **kwargs):
        path = next(key for key, value in PATHS.items() if url == BASE + value)
        if path == throttled_path and throttled:
            return quota_response()
        if path == "courses":
            return http_response([COURSE])
        if path == "assignments" and kwargs["params"]["bucket"] == "overdue":
            return http_response([])
        return http_response([records(path, 1)])

    # Retain the real client, session, normalization, view, model and template.
    with patch("accounts.canvas_client.requests.Session.get", autospec=True, side_effect=get):
        response = client.get(reverse("assignment_list"))
        assert response.status_code == 200
        connection.refresh_from_db()
        assert connection.is_valid
        assert connection.encrypted_token == original_ciphertext
        assert connection.get_token() == TOKEN
        assert not response.context["canvas_connection_expired"]
        assert not response.context["canvas_connection_missing"]
        content = response.content.decode()
        assert "Please reconnect" not in content
        if throttled_path == "graded":
            assert not response.context["assignments_unavailable"]
            assert [item["title"] for item in response.context["assignments"]] == ["Work 1"]
            assert "Work 1" in content
            assert "Unable to load recently graded work right now." in content
        else:
            assert response.context["assignments_unavailable"]
            assert "Please try again" in content
            assert "No upcoming assignments" not in content

        throttled = False
        recovered = client.get(reverse("assignment_list"))

    assert recovered.status_code == 200
    connection.refresh_from_db()
    assert connection.is_valid
    assert not recovered.context["assignments_unavailable"]
    assert [item["title"] for item in recovered.context["assignments"]] == ["Work 1"]
    assert recovered.context["show_recently_graded"]
    assert [item["assignment"] for item in recovered.context["recently_graded"]] == ["Work 1"]
