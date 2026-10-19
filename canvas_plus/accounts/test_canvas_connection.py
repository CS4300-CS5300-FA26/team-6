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
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from django.test import Client


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
