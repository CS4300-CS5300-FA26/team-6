"""Behavior steps for upcoming coursework on the logged-in home page."""
# pylint: disable=import-error,missing-function-docstring,not-callable,duplicate-code

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from behave import given, when, then
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import Client, override_settings
from django.utils import timezone as django_timezone
from django.utils.html import escape
from django.utils.text import slugify

from accounts.canvas_client import CanvasAPIError, CanvasAuthenticationError
from accounts.models import CanvasConnection

COURSE = {"id": 42, "name": "CS 4300"}
ASSIGNMENT_TITLE = "Canvas Project 1"
TOKEN = "fake-behave-canvas-token"


def parse_due_date(value):
    """Translate scenario dates into aware UTC values returned by the API."""
    try:
        parsed = datetime.strptime(value, "%B %d, %Y at %I:%M %p")
    except ValueError:
        parsed = datetime.strptime(value, "%b %d, %Y %I:%M %p")
    return parsed.replace(tzinfo=ZoneInfo("America/Denver")).astimezone(timezone.utc)


def assignment_result(due_date):
    """Build one normalized result from the assignment-read contract."""
    return {
        "title": ASSIGNMENT_TITLE,
        "course_name": COURSE["name"],
        "due_date": due_date,
        "submitted": False,
    }


def prepare_student(context, assignments):
    """Use real per-user encrypted connection storage and stub Canvas calls."""
    configured = override_settings(
        CANVAS_BASE_URL="https://canvas.example.edu",
        CANVAS_TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode(),
    )
    configured.enable()
    context.add_cleanup(configured.disable)

    context.user = get_user_model().objects.create_user(username="canvas-student")
    context.connection = CanvasConnection(
        user=context.user,
        canvas_url="https://canvas.example.edu",
    )
    context.connection.set_token(TOKEN)
    context.connection.save()

    context.client = Client()
    context.client.force_login(context.user)
    context.canvas_courses = Mock(return_value=[COURSE])
    context.canvas_assignments = Mock(return_value=assignments)
    context.graded_submissions = Mock(return_value=[])

    targets = (
        ("accounts.connections.list_courses", context.canvas_courses, False),
        ("assignments.views.list_courses", context.canvas_courses, True),
        ("assignments.views.list_upcoming_assignments", context.canvas_assignments, True),
        ("assignments.views.list_graded_submissions", context.graded_submissions, False),
    )
    for target, replacement, create in targets:
        patcher = patch(target, replacement, create=create)
        patcher.start()
        context.add_cleanup(patcher.stop)


def get_assignment_for_date(value):
    return [assignment_result(parse_due_date(value))]


def prepare_relative_coursework(context, due_in, submitted=False):
    """Anchor coursework to the current time so scenarios do not age."""
    context.dashboard_now = django_timezone.now()
    assignment = assignment_result(context.dashboard_now + due_in)
    assignment["submitted"] = submitted
    prepare_student(context, [assignment])


@given('I am a connected student with upcoming coursework due on "{due_date}"')
def step_connected_student_with_upcoming_work(context, due_date):
    prepare_student(context, get_assignment_for_date(due_date))


@given("I am a connected student with no upcoming coursework")
def step_connected_student_with_no_upcoming_work(context):
    prepare_student(context, [])


@given('I am viewing "{title}" for "{course}" due "{due_date}"')
def step_viewing_assignment(context, title, course, due_date):
    prepare_student(context, get_assignment_for_date(due_date))
    context.response = context.client.get("/assignments/")
    assert context.response.status_code == 200
    html = context.response.content.decode()
    assert title in html
    assert course in html
    assert due_date in html


@when("I open the logged-in home page")
def step_open_logged_in_home(context):
    context.response = context.client.get("/assignments/")


@when('Canvas changes its due date to "{due_date}"')
def step_canvas_changes_due_date(context, due_date):
    context.canvas_assignments.return_value = get_assignment_for_date(due_date)


@when("I reload the logged-in home page")
def step_reload_logged_in_home(context):
    context.response = context.client.get("/assignments/")


@then('I see "{title}" for "{course}" due "{due_date}"')
def step_assignment_due_date_is_visible(context, title, course, due_date):
    assert context.response.status_code == 200
    html = context.response.content.decode()
    for expected in (title, course, due_date):
        assert expected in html


@then('I see exactly "{message}"')
def step_exact_empty_state(context, message):
    assert context.response.status_code == 200
    html = context.response.content.decode()
    assert message in html
    assert "You have no assignments." not in html


@then('I see the revised due date "{revised}" instead of "{original}"')
def step_revised_due_date_is_visible(context, revised, original):
    assert context.response.status_code == 200
    html = context.response.content.decode()
    assert revised in html
    assert original not in html


@given("I am a signed-in student without a Canvas connection")
def step_student_without_canvas_connection(context):
    prepare_student(context, [])
    context.connection.delete()


@given("my saved Canvas token is rejected while loading assignments")
def step_saved_token_rejected_for_assignments(context):
    prepare_student(context, [])
    context.canvas_courses.side_effect = CanvasAuthenticationError("Rejected")


@given("Canvas is temporarily unavailable while loading assignments")
def step_canvas_unavailable_for_assignments(context):
    prepare_student(context, [])
    context.canvas_assignments.side_effect = CanvasAPIError("Canvas unavailable")


@then("I see the Canvas connection prompt instead of the empty state")
def step_connection_prompt_not_empty_state(context):
    assert context.response.status_code == 200
    html = context.response.content.decode()
    assert "Connect Canvas to see your upcoming assignments." in html
    assert 'href="/accounts/connect-canvas/"' in html
    assert "No upcoming assignments" not in html


@then("I see the expired Canvas connection message and reconnect link")
def step_expired_connection_message(context):
    assert context.response.status_code == 200
    html = context.response.content.decode()
    assert "Your Canvas connection has expired." in html
    assert 'href="/accounts/connect-canvas/"' in html
    assert "No upcoming assignments" not in html


@then("I see the assignments unavailable message instead of the empty state")
def step_assignments_unavailable_not_empty_state(context):
    assert context.response.status_code == 200
    html = context.response.content.decode()
    assert "Unable to load upcoming assignments. Please try again." in html
    assert "No upcoming assignments" not in html


@given("I am a connected student with unsubmitted coursework due in {amount:d} {unit}")
def step_unsubmitted_coursework_due(context, amount, unit):
    prepare_relative_coursework(context, timedelta(**{unit: amount}))


@given("I am a connected student with unsubmitted coursework that was due {hours:d} hours ago")
def step_unsubmitted_coursework_past_due(context, hours):
    prepare_relative_coursework(context, timedelta(hours=-hours))


@given("I am a connected student who has submitted coursework due in {hours:d} hours")
def step_submitted_coursework_due(context, hours):
    prepare_relative_coursework(context, timedelta(hours=hours), submitted=True)


@given('my dashboard shows "{title}" marked "{label}"')
def step_dashboard_shows_priority(context, title, label):
    step_open_logged_in_home(context)
    step_assignment_marked(context, title, label)


@when("{hours:d} hours pass")
def step_hours_pass(context, hours):
    context.dashboard_now += timedelta(hours=hours)
    clock = patch("django.utils.timezone.now", return_value=context.dashboard_now)
    clock.start()
    context.add_cleanup(clock.stop)


@then('I see "{title}" marked "{label}"')
def step_assignment_marked(context, title, label):
    assert context.response.status_code == 200
    assignments = [
        assignment for assignment in context.response.context["assignments"]
        if assignment["title"] == title
    ]
    assert len(assignments) == 1, f'Expected one assignment titled "{title}"'
    actual = assignments[0]["priority"]
    assert actual == label, f'Expected "{title}" marked "{label}", got "{actual}"'

    html = context.response.content.decode()
    heading = f'<h2 class="assignment-title">{escape(title)}</h2>'
    cards = [
        fragment.split("</li>", 1)[0]
        for fragment in html.split('<li class="assignment-card">')[1:]
    ]
    matching_cards = [card for card in cards if heading in card]
    assert len(matching_cards) == 1, f'Expected one card titled "{title}"'
    badge = (
        f'<span class="assignment-status assignment-status--{slugify(label)}">'
        f'{escape(label)}</span>'
    )
    assert badge in matching_cards[0], f'Card for "{title}" has no "{label}" badge'


@then("I see no high-priority marker")
def step_no_high_priority_marker(context):
    assert context.response.status_code == 200
    html = context.response.content.decode()
    for slug in ("due-soon", "past-due"):
        # The CSS defines both classes even when no card carries either marker.
        assert f'assignment-status--{slug}">' not in html
