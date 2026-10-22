"""Executable issue #38 scenarios; replace Canvas calls with deterministic results."""
# Behave decorators are callable; pylint cannot infer their dynamic registration.
# pylint: disable=not-callable,missing-function-docstring,import-error

from unittest.mock import Mock, patch

from behave import given, when, then
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import Client, override_settings
from django.urls import reverse

from accounts.canvas_client import CanvasAuthenticationError

TOKEN = "fake-behave-token-W9Z7"
COURSES = [{"id": 1, "name": "Software Engineering"}, {"id": 2, "name": "Databases"}]


def prepare_student(context):
    """Keep real Django storage and sessions, isolating only the external API."""
    configured = override_settings(
        CANVAS_BASE_URL="https://canvas.example.edu",
        CANVAS_TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode(),
    )
    configured.enable()
    context.add_cleanup(configured.disable)
    context.canvas = Mock(return_value=COURSES)
    context.upcoming_assignments = Mock(return_value=[])
    replacements = (
        ("accounts.views.list_courses", context.canvas),
        ("accounts.connections.list_courses", context.canvas),
        ("assignments.views.list_courses", context.canvas),
        ("assignments.views.list_upcoming_assignments", context.upcoming_assignments),
    )
    for target, replacement_value in replacements:
        replacement = patch(target, replacement_value)
        replacement.start()
        context.add_cleanup(replacement.stop)
    context.user = get_user_model().objects.create_user(username="canvas-student")
    context.client = Client()
    context.client.force_login(context.user)


@given('I am on the "Connect Canvas" page')
def step_connection_page(context):
    prepare_student(context)
    context.response = context.client.get(reverse("connect_canvas"))
    assert context.response.status_code == 200


@when('I paste a valid Canvas personal access token and click "Connect"')
def step_connect_valid(context):
    context.response = context.client.post(reverse("connect_canvas"), {"token": TOKEN})
    assert context.response.status_code == 200


@when('I paste an invalid token and click "Connect"')
def step_connect_invalid(context):
    context.canvas.side_effect = CanvasAuthenticationError("Rejected")
    context.response = context.client.post(reverse("connect_canvas"), {"token": "invalid-token"})


@then("I see a list of my enrolled course names")
def step_course_names(context):
    html = context.response.content.decode()
    for course in COURSES:
        assert f'<li>{course["name"]}</li>' in html


@then('I remain on the "Connect Canvas" page')
def step_still_connect_page(context):
    assert context.response.status_code == 200
    assert context.response.wsgi_request.path == reverse("connect_canvas")


@given("I previously connected my Canvas account")
@given("I have connected my Canvas account")
def step_previously_connected(context):
    prepare_student(context)
    step_connect_valid(context)
    assert "Canvas connected" in context.response.content.decode()
    context.client = Client()
    context.client.force_login(context.user)


@given("my token has since been deleted or has expired in Canvas")
def step_revoked_token(context):
    context.canvas.side_effect = CanvasAuthenticationError("Rejected")


@when("I open the app")
def step_open_app(context):
    context.response = context.client.get("/", follow=True)


@then('I see a link to the "Connect Canvas" page')
def step_reconnect_link(context):
    assert f'href="{reverse("connect_canvas")}"' in context.response.content.decode()


@when('I open the "Connect Canvas" page')
def step_reopen_connection(context):
    context.response = context.client.get(reverse("connect_canvas"))
    assert context.response.status_code == 200


@then("I see only the last 4 characters of my saved token")
def step_masked_suffix(context):
    assert f'••••</span>{TOKEN[-4:]}' in context.response.content.decode()


@then("the rest of the token is hidden")
def step_secret_not_in_html(context):
    html = context.response.content.decode()
    assert TOKEN not in html
    assert TOKEN[:-4] not in html
