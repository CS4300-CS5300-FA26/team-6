"""Canvas error responses must preserve valid credentials and hide upstream details.

As a student, I want permission failures to leave my saved connection usable,
so that losing access to one course does not require reconnecting Canvas.
"""

import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
import requests
from cryptography.fernet import Fernet
from django.core.cache import cache

from .canvas_client import (
    CanvasAPIError,
    get_course_syllabus,
    list_graded_submissions,
    list_upcoming_assignments,
)
from .models import CanvasConnection

pytestmark = [pytest.mark.django_db, pytest.mark.integration]
TOKEN = "fake-private-canvas-token"
SERVER_DETAIL = f"Private upstream diagnostic containing {TOKEN}"
COURSE = {"id": 101, "name": "Software Engineering"}
CHALLENGE = {"www-authenticate": 'Bearer realm="canvas-lms"'}
RESOURCE_PATHS = {
    "syllabus": "/api/v1/courses/101",
    "assignments": "/api/v1/courses/101/assignments",
    "submissions": "/api/v1/courses/101/students/submissions",
}
UNAVAILABLE = {
    "syllabus": "Unable to load this course. Please try again.",
    "assignments": "Unable to load upcoming assignments. Please try again.",
    "submissions": "Unable to load recently graded work right now.",
}


def http_response(status, body, headers=None):
    """Use requests' actual header and JSON handling at the HTTP boundary."""
    response = requests.Response()
    response.status_code = status
    response.headers.update(headers or {})
    response._content = body.encode()  # pylint: disable=protected-access
    response.encoding = "utf-8"
    return response


@pytest.fixture(name="saved_student")
def saved_student_fixture(client, django_user_model, settings, monkeypatch):
    """Given a saved, valid token and a cached course that may lose access."""
    settings.CANVAS_BASE_URL = "https://canvas.example.edu"
    settings.CANVAS_TOKEN_ENCRYPTION_KEY = Fernet.generate_key().decode()
    monkeypatch.setattr("accounts.canvas_client.MAX_CONCURRENT_REQUESTS", 1)
    cache.clear()
    user = django_user_model.objects.create_user(username="error-response-student")
    client.force_login(user)
    connection = CanvasConnection(user=user, canvas_url=settings.CANVAS_BASE_URL)
    connection.set_token(TOKEN)
    connection.save()
    # Django supplies a datetime value for this model field after saving.
    # pylint: disable-next=no-member
    cache.set(f"canvas-courses:{connection.pk}:{connection.updated_at.timestamp()}", [COURSE])
    yield client, connection
    cache.clear()


def request_resource(client, resource, error):
    """Keep Canvas normalization, consumer error handling, and rendering real."""
    requested = []

    def get(url, **kwargs):
        assert kwargs["headers"] == {"Authorization": f"Bearer {TOKEN}"}
        if url.endswith(RESOURCE_PATHS[resource]):
            requested.append(url)
            return error
        if url.endswith("/api/v1/courses"):
            return http_response(200, json.dumps([COURSE]))
        return http_response(200, "[]")

    with patch("accounts.canvas_client.requests.get", side_effect=get), patch(
        "accounts.canvas_client.requests.Session.get", side_effect=get
    ):
        url = "/courses/101/" if resource == "syllabus" else "/assignments/"
        page = client.get(url)
    assert requested, "The inaccessible resource must actually reach the HTTP boundary."
    assert page.status_code == 200
    return page


def assert_private_details_hidden(page):
    """Neither raw diagnostics nor credentials may reach the rendered page."""
    html = page.content.decode()
    assert TOKEN not in html
    assert "Private upstream diagnostic" not in html
    assert "Your Canvas connection expired" not in html


@pytest.mark.parametrize("resource", RESOURCE_PATHS)
def test_permission_401_preserves_saved_connection(saved_student, resource):
    """Given a valid token, a bare permission 401 shows unavailable access."""
    client, connection = saved_student
    error = http_response(401, json.dumps({"errors": [{"message": SERVER_DETAIL}]}))
    page = request_resource(client, resource, error)
    connection.refresh_from_db()
    assert connection.is_valid
    assert UNAVAILABLE[resource] in page.content.decode()
    assert_private_details_hidden(page)


@pytest.mark.parametrize("resource", RESOURCE_PATHS)
def test_challenged_401_requires_reconnect(saved_student, resource):
    """Given a revoked token, a challenged 401 invalidates it and offers reconnect."""
    client, connection = saved_student
    error = http_response(
        401, json.dumps({"errors": [{"message": "Invalid access token."}]}), CHALLENGE
    )
    page = request_resource(client, resource, error)
    connection.refresh_from_db()
    assert not connection.is_valid
    assert "Your Canvas connection expired. Please reconnect." in page.content.decode()
    assert '/accounts/connect-canvas/' in page.content.decode()
    assert TOKEN not in page.content.decode()
    assert "Invalid access token." not in page.content.decode()


@pytest.mark.parametrize("resource", RESOURCE_PATHS)
@pytest.mark.parametrize("status", [403, 404])
@pytest.mark.parametrize("body", [
    json.dumps({"errors": [{"message": SERVER_DETAIL}]}),
    f"<html>{SERVER_DETAIL}</html>",
], ids=["canvas-error-json", "html-error"])
def test_inaccessible_course_shows_safe_unavailable_state(saved_student, resource, status, body):
    """Given a vanished/inaccessible course, status errors do not claim empty work."""
    client, connection = saved_student
    page = request_resource(client, resource, http_response(status, body))
    connection.refresh_from_db()
    assert connection.is_valid
    assert UNAVAILABLE[resource] in page.content.decode()
    empty_message = {
        "syllabus": "No syllabus posted", "assignments": "No upcoming assignments",
        "submissions": "No recently graded work",
    }[resource]
    assert empty_message not in page.content.decode()
    assert_private_details_hidden(page)


@pytest.mark.parametrize("resource", RESOURCE_PATHS)
def test_unreadable_success_json_uses_shared_safe_decode_error(saved_student, resource):
    """Given unreadable JSON on 200, the shared decoder and page fail safely."""
    client, connection = saved_student
    error = http_response(200, f"<html>{SERVER_DETAIL}</html>")
    with patch("accounts.canvas_client.requests.get", return_value=error):
        with pytest.raises(CanvasAPIError) as caught:
            if resource == "syllabus":
                get_course_syllabus(TOKEN, COURSE["id"])
            elif resource == "assignments":
                list_upcoming_assignments(TOKEN, [COURSE])
            else:
                list_graded_submissions(TOKEN, [COURSE], datetime.now(timezone.utc))
    assert str(caught.value) == "Canvas returned an unreadable response. Please try again."
    page = request_resource(client, resource, error)
    connection.refresh_from_db()
    assert connection.is_valid
    assert UNAVAILABLE[resource] in page.content.decode()
    assert_private_details_hidden(page)
