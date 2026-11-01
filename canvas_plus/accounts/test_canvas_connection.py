"""Issue #38 acceptance tests: connect, reject, reconnect, and mask a Canvas token.

As an enrolled student, I want to connect Canvas with a personal access token
so that Canvas+ can load my courses and coursework.

These tests define the feature's initial interface:
* GET/POST /accounts/connect-canvas/, with a form field named ``token``.
* A Django setting named CANVAS_BASE_URL, pointing at the school's Canvas host.
* Opening / (following redirects) checks a saved connection's validity.

Only Canvas is replaced, by a local HTTP server. Django routes, forms, views,
templates, sessions, and the test database remain real. There are no real tokens.
HTTP is used only for this loopback test server; production must use HTTPS.
"""

import json
from unittest.mock import ANY, patch
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from cryptography.fernet import Fernet
from django.test import Client

from .canvas_client import CanvasAPIError
from .models import CanvasConnection


pytestmark = [pytest.mark.django_db, pytest.mark.integration]

CONNECT_URL = "/accounts/connect-canvas/"
VALID_TOKEN = "fake-canvas-secret-prefix-W9Z7"
INVALID_TOKEN = "fake-invalid-canvas-token"
COURSES = [
    {"id": 101, "name": "Software Engineering"},
    {"id": 202, "name": "Database Systems"},
]


class PageContent(HTMLParser):
    """Read text, list items, and links without depending on HTML formatting."""

    def __init__(self, response):
        super().__init__()
        self.text_parts = []
        self.list_items = []
        self.links = []
        self._item_parts = None
        self.feed(response.content.decode(response.charset))

    def handle_starttag(self, tag, attrs):
        if tag == "li":
            self._item_parts = []
        if tag == "a":
            self.links.append(dict(attrs).get("href"))

    def handle_data(self, data):
        self.text_parts.append(data)
        if self._item_parts is not None:
            self._item_parts.append(data)

    def handle_endtag(self, tag):
        if tag == "li" and self._item_parts is not None:
            self.list_items.append(" ".join("".join(self._item_parts).split()))
            self._item_parts = None

    @property
    def text(self):
        """Normalize whitespace so template indentation does not affect checks."""
        return " ".join(" ".join(self.text_parts).split())


@pytest.fixture(name="canvas_api")
def fake_canvas_api(settings):
    """Canvas accepts one fake token until the test revokes it."""
    settings.CANVAS_TOKEN_ENCRYPTION_KEY = Fernet.generate_key().decode()
    state = SimpleNamespace(revoked=False, course_requests=0, rejected_requests=0)

    class Handler(BaseHTTPRequestHandler):
        """Return Canvas-shaped course, identity, and authentication responses."""

        def do_GET(self):  # pylint: disable=invalid-name
            """Authenticate the bearer token before returning any Canvas data."""
            authorized = (
                self.headers.get("Authorization") == f"Bearer {VALID_TOKEN}"
                and not state.revoked
            )
            path = urlsplit(self.path).path
            if not authorized:
                state.rejected_requests += 1
                status, payload = 401, {"errors": [{"message": "Invalid access token."}]}
            elif path == "/api/v1/courses":
                state.course_requests += 1
                status, payload = 200, COURSES
            elif path in ("/api/v1/users/self", "/api/v1/users/self/profile"):
                status, payload = 200, {"id": 7, "name": "Test Student"}
            else:
                status, payload = 404, {"errors": [{"message": "Unknown test endpoint."}]}

            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):  # pylint: disable=redefined-builtin
            """Keep fake-server request logs out of test output."""

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        settings.CANVAS_BASE_URL = f"http://127.0.0.1:{server.server_port}"
        worker = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
        worker.start()
        try:
            yield state
        finally:
            server.shutdown()
            worker.join(timeout=5)


@pytest.fixture(name="student_client")
def signed_in_student(client, django_user_model, canvas_api):
    """All four scenarios start with a signed-in Canvas+ student."""
    del canvas_api  # Request the fake server before opening any application page.
    user = django_user_model.objects.create_user(username="canvas-student")
    client.force_login(user)
    return client, user


def connect_successfully(client):
    """Establish the Given state through the same page a student will use."""
    page = client.get(CONNECT_URL)
    assert page.status_code == 200, "The Connect Canvas page must exist."
    response = client.post(CONNECT_URL, {"token": VALID_TOKEN}, follow=True)
    assert response.status_code == 200
    assert "Canvas connected" in PageContent(response).text
    return response


def test_student_connects_with_a_valid_token(student_client, canvas_api):
    """Given the connection page, a valid token shows success and enrolled courses."""
    client, _user = student_client

    # Given / When: open the page and submit the valid fake Canvas token.
    response = connect_successfully(client)

    # Then: success came from Canvas, and both returned courses appear in a list.
    assert canvas_api.course_requests > 0
    page = PageContent(response)
    for course in COURSES:
        assert any(course["name"] in item for item in page.list_items)


def test_student_enters_an_invalid_token(student_client, canvas_api):
    """Given the connection page, an invalid token shows an error on that page."""
    client, _user = student_client
    assert client.get(CONNECT_URL).status_code == 200

    # When: Canvas rejects the submitted token.
    response = client.post(CONNECT_URL, {"token": INVALID_TOKEN}, follow=True)

    # Then: the exact error appears, and the student stays on Connect Canvas.
    assert response.status_code == 200
    assert response.wsgi_request.path == CONNECT_URL
    assert "Invalid token. Check your token and try again." in PageContent(response).text
    assert "Canvas connected" not in PageContent(response).text
    assert canvas_api.rejected_requests > 0


def test_students_saved_token_stops_working(student_client, canvas_api):
    """Given a saved token revoked in Canvas, opening the app offers reconnection."""
    client, user = student_client
    connect_successfully(client)
    canvas_api.revoked = True
    rejected_before = canvas_api.rejected_requests

    # When: return in a new session, so the app must use the saved connection.
    returning_client = Client()
    returning_client.force_login(user)
    response = returning_client.get("/", follow=True)

    # Then: revalidation detects rejection and provides a working reconnect link.
    assert response.status_code == 200
    page = PageContent(response)
    assert "Your Canvas connection expired. Please reconnect." in page.text
    assert CONNECT_URL in page.links
    assert canvas_api.rejected_requests > rejected_before
    assert returning_client.get(CONNECT_URL).status_code == 200


def test_saved_token_is_not_displayed_in_full(student_client):
    """Given a saved token, reopening the connection page reveals only its suffix."""
    client, user = student_client
    connect_successfully(client)

    # When: a new session opens the page, exercising the persisted token display.
    returning_client = Client()
    returning_client.force_login(user)
    response = returning_client.get(CONNECT_URL)

    # Then: show the last four characters, but never send the secret to the page.
    assert response.status_code == 200
    assert VALID_TOKEN[-4:] in PageContent(response).text
    html = response.content.decode(response.charset)
    assert VALID_TOKEN not in html
    assert VALID_TOKEN[:-4] not in html
    assert "fake-canvas-secret" not in html


def test_saved_token_is_encrypted_in_the_database(student_client):
    """The database stores ciphertext while the server can recover the credential."""
    client, user = student_client
    connect_successfully(client)
    connection = CanvasConnection.objects.get(user=user)
    assert VALID_TOKEN not in connection.encrypted_token
    assert "fake-canvas-secret" not in connection.encrypted_token
    assert connection.get_token() == VALID_TOKEN
    assert connection.token_last_four == "W9Z7"
    assert connection.is_valid


def test_rejected_replacement_preserves_the_saved_connection(student_client):
    """A mistyped replacement must not destroy a working saved credential."""
    client, user = student_client
    connect_successfully(client)
    before = CanvasConnection.objects.get(user=user).encrypted_token
    response = client.post(CONNECT_URL, {"token": INVALID_TOKEN})
    assert "Invalid token. Check your token and try again." in PageContent(response).text
    connection = CanvasConnection.objects.get(user=user)
    assert connection.encrypted_token == before
    assert connection.is_valid
    assert INVALID_TOKEN not in response.content.decode()


def test_reconnect_updates_existing_record_and_clears_expiry(student_client, canvas_api):
    """Revocation persists until a successful reconnect replaces the credential."""
    client, user = student_client
    connect_successfully(client)
    original_pk = CanvasConnection.objects.get(user=user).pk
    canvas_api.revoked = True
    client.get("/", follow=True)
    connection = CanvasConnection.objects.get(user=user)
    assert not connection.is_valid
    response = client.get("/assignments/")
    assert "Your Canvas connection expired. Please reconnect." in PageContent(response).text
    canvas_api.revoked = False
    connect_successfully(client)
    connection.refresh_from_db()
    assert connection.pk == original_pk
    assert connection.is_valid
    assert CanvasConnection.objects.filter(user=user).count() == 1
    response = client.get("/assignments/")
    assert "Your Canvas connection expired." not in PageContent(response).text


def test_another_student_cannot_see_or_replace_the_connection(student_client, django_user_model):
    """Connections are always selected using the authenticated user."""
    client, owner = student_client
    connect_successfully(client)
    other = django_user_model.objects.create_user(username="other-student")
    client.force_login(other)
    response = client.get(CONNECT_URL, {"user_id": owner.pk})
    assert "W9Z7" not in PageContent(response).text
    response = client.post(CONNECT_URL, {"token": VALID_TOKEN, "user_id": owner.pk})
    assert response.status_code == 200
    assert CanvasConnection.objects.filter(user=owner).exists()
    assert CanvasConnection.objects.filter(user=other).exists()
    assert CanvasConnection.objects.count() == 2


def test_anonymous_student_is_redirected_to_login(canvas_api):
    """A credential page cannot be used without a Canvas+ account session."""
    del canvas_api
    response = Client().get(CONNECT_URL)
    assert response.status_code == 302
    assert response.url == f"/accounts/login/?next={CONNECT_URL}"


def test_connect_form_requires_csrf(student_client):
    """Even a signed-in student must submit the CSRF token."""
    _client, user = student_client
    protected_client = Client(enforce_csrf_checks=True)
    protected_client.force_login(user)
    response = protected_client.post(CONNECT_URL, {"token": VALID_TOKEN})
    assert response.status_code == 403
    assert not CanvasConnection.objects.filter(user=user).exists()
    page = protected_client.get(CONNECT_URL)
    response = protected_client.post(CONNECT_URL, {
        "token": VALID_TOKEN,
        "csrfmiddlewaretoken": page.context["csrf_token"],
    })
    assert "Canvas connected" in PageContent(response).text


def test_blank_submission_does_not_contact_canvas(student_client, canvas_api):
    """Empty POST data must bind the form and display required-field feedback."""
    client, _user = student_client
    response = client.post(CONNECT_URL, {})
    assert "This field is required." in PageContent(response).text
    assert canvas_api.course_requests == 0
    assert not CanvasConnection.objects.exists()


@pytest.mark.parametrize("key", ["", "not-a-fernet-key"])
def test_missing_or_invalid_encryption_key_fails_closed(student_client, settings, key):
    """A valid Canvas token cannot be saved without configured encryption."""
    client, _user = student_client
    settings.CANVAS_TOKEN_ENCRYPTION_KEY = key
    response = client.post(CONNECT_URL, {"token": VALID_TOKEN})
    assert "Canvas connection is not configured." in PageContent(response).text
    assert "Canvas connected" not in PageContent(response).text
    assert VALID_TOKEN not in response.content.decode()
    assert not CanvasConnection.objects.exists()


def test_changed_canvas_host_does_not_receive_a_saved_token(student_client, settings):
    """A saved credential remains bound to the Canvas origin it was validated on."""
    client, _user = student_client
    connect_successfully(client)
    settings.CANVAS_BASE_URL = "https://different-school.example"
    with patch("accounts.connections.list_courses") as request:
        response = client.get("/assignments/")
    request.assert_not_called()
    assert "Your Canvas connection expired. Please reconnect." in PageContent(response).text


@pytest.mark.parametrize("saved_url,configured_url", [
    ("https://canvas.example.edu", "https://canvas.example.edu:443"),
    ("https://canvas.example.edu:443", "https://canvas.example.edu"),
    ("https://Canvas.Example.edu", "https://canvas.example.edu"),
])
def test_equivalent_canvas_origin_preserves_connection(student_client, settings,
                                                       saved_url, configured_url):
    """Equivalent origin notation must not expire a working saved credential."""
    client, user = student_client
    settings.CANVAS_BASE_URL = saved_url
    with patch("accounts.views.list_courses", return_value=COURSES):
        connect_successfully(client)

    settings.CANVAS_BASE_URL = configured_url
    with patch("assignments.views.list_courses", return_value=COURSES) as request:
        with patch("assignments.views.list_upcoming_assignments", return_value=[]):
            with patch("assignments.views.list_graded_submissions", return_value=[]):
                response = client.get("/", follow=True)

    assert response.status_code == 200
    assert "Your Canvas connection expired." not in PageContent(response).text
    request.assert_called_once_with(VALID_TOKEN, session=ANY)
    assert CanvasConnection.objects.get(user=user).is_valid


def test_unreadable_saved_token_offers_reconnection(student_client):
    """Tampered ciphertext is rejected and never sent to Canvas."""
    client, user = student_client
    connect_successfully(client)
    CanvasConnection.objects.filter(user=user).update(encrypted_token="corrupted")
    response = client.get("/assignments/")
    assert "Your Canvas connection expired. Please reconnect." in PageContent(response).text


def test_temporary_outage_does_not_expire_saved_token(student_client):
    """An outage preserves the credential and offers retry rather than expiry."""
    client, user = student_client
    connect_successfully(client)
    with patch(
        "assignments.views.list_courses",
        side_effect=CanvasAPIError("Unavailable"),
    ):
        response = client.get("/assignments/")
    assert "Unable to load upcoming assignments. Please try again." in PageContent(response).text
    assert "Your Canvas connection expired." not in PageContent(response).text
    assert CanvasConnection.objects.get(user=user).is_valid


def test_valid_token_with_no_courses_still_connects(student_client):
    """An empty enrollment list is a successful connection, not an invalid token."""
    client, user = student_client
    with patch("accounts.views.list_courses", return_value=[]):
        response = client.post(CONNECT_URL, {"token": VALID_TOKEN})
    assert "Canvas connected" in PageContent(response).text
    assert "No active enrolled courses found." in PageContent(response).text
    assert CanvasConnection.objects.get(user=user).is_valid


def test_canvas_failure_during_connect_shows_safe_feedback(student_client):
    """Service failures do not save credentials or report invalid tokens."""
    client, _user = student_client
    with patch("accounts.views.list_courses", side_effect=CanvasAPIError("Please try again.")):
        response = client.post(CONNECT_URL, {"token": VALID_TOKEN})
    assert "Please try again." in PageContent(response).text
    assert "Invalid token." not in PageContent(response).text
    assert not CanvasConnection.objects.exists()
