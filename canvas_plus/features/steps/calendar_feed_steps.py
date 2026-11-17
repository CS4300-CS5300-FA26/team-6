"""Acceptance steps for personal calendar feed journeys."""

# Behave decorators are callable; pylint cannot infer their dynamic registration.
# pylint: disable=not-callable,import-error,missing-function-docstring

import re
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import urlsplit
from uuid import uuid4

from behave import given, then, when
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from icalendar import Calendar

from assignments.models import Assignment
from calendar_feed.services import issue_subscription
from study_plan.models import StudyPlan, StudySession


def prepare_student(context):
    """Create a local student and authenticated test client."""
    context.user = get_user_model().objects.create_user(
        username=f"calendar-student-{uuid4().hex}"
    )
    context.client = Client()
    context.client.force_login(context.user)


def extract_feed_url(response):
    """Extract the one-time absolute feed URL from the action response."""
    body = response.content.decode(response.charset)
    urls = set(
        re.findall(r"https?://[^\s\"'<>]+/calendar-feed/[^\s\"'<>]+\.ics", body)
    )
    assert len(urls) == 1, "Expected one copyable calendar feed URL."
    return urls.pop()


def feed_token(feed_url):
    """Get the bearer token from an absolute feed URL."""
    return urlsplit(feed_url).path.rsplit("/", maxsplit=1)[-1].removesuffix(".ics")


def read_events(response):
    """Parse VEVENT components from a successful calendar response."""
    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/calendar")
    calendar = Calendar.from_ical(response.content)
    return [component for component in calendar.walk() if component.name == "VEVENT"]


@given("I am signed in to Canvas Plus as a student")
def step_signed_in_student(context):
    """Prepare an authenticated local student account."""
    prepare_student(context)


@when("I create a calendar subscription in account settings")
def step_create_subscription(context):
    """Create a subscription through the existing settings action."""
    with patch("requests.get", side_effect=AssertionError("Canvas request made")):
        context.create_response = context.client.post(
            reverse("settings"), {"action": "calendar"}
        )
    assert context.create_response.status_code == 200


@then("I receive a personal calendar URL")
def step_receive_url(context):
    """Verify settings returns one URL tied to the student's account."""
    context.first_url = extract_feed_url(context.create_response)
    parsed_url = urlsplit(context.first_url)
    assert parsed_url.scheme in {"http", "https"}
    assert parsed_url.netloc
    assert parsed_url.path.startswith("/calendar-feed/")
    token = feed_token(context.first_url)
    context.first_token = token
    with patch("requests.get", side_effect=AssertionError("Canvas request made")):
        response = Client().get(parsed_url.path)
    assert response.status_code == 200


@then("the URL is shown only in the creation response")
def step_url_is_one_time(context):
    """Ensure a later settings visit does not reveal the bearer secret."""
    settings_page = context.client.get(reverse("settings"))
    assert settings_page.status_code == 200
    settings_content = settings_page.content.decode(settings_page.charset)
    assert context.first_url not in settings_content
    assert context.first_token not in settings_content


@when("I rotate my calendar subscription")
def step_rotate_subscription(context):
    """Rotate the credential through the same account settings action."""
    with patch("requests.get", side_effect=AssertionError("Canvas request made")):
        context.rotate_response = context.client.post(
            reverse("settings"), {"action": "calendar"}
        )
    assert context.rotate_response.status_code == 200


@then("the new URL differs and the previous URL is revoked")
def step_rotated_url_replaces_old(context):
    """Check rotation creates a new live URL and immediately rejects the old one."""
    context.second_url = extract_feed_url(context.rotate_response)
    assert context.second_url != context.first_url
    old_response = Client().get(urlsplit(context.first_url).path)
    new_response = Client().get(urlsplit(context.second_url).path)
    assert old_response.status_code == 404
    assert new_response.status_code == 200


@given("my account has a due-dated assignment and a saved study session")
def step_account_has_coursework_events(context):
    """Create local assignment and session records for the student."""
    prepare_student(context)
    now = timezone.now().replace(microsecond=0)
    context.assignment_due = now + timedelta(days=2)
    context.session_start = now + timedelta(days=1)
    context.session_end = context.session_start + timedelta(hours=1)
    Assignment.objects.create(
        user=context.user,
        title="Calendar deadline assignment",
        course="Calendar course",
        due_date=context.assignment_due,
        canvas_course_id=4201,
        canvas_assignment_id=4301,
    )
    session_assignment = Assignment.objects.create(
        user=context.user,
        title="Calendar study assignment",
        course="Calendar course",
        canvas_course_id=4201,
        canvas_assignment_id=4302,
    )
    plan = StudyPlan.objects.create(user=context.user)
    StudySession.objects.create(
        plan=plan,
        assignment=session_assignment,
        start=context.session_start,
        end=context.session_end,
    )
    other_user = get_user_model().objects.create_user(
        username=f"other-calendar-student-{uuid4().hex}"
    )
    Assignment.objects.create(
        user=other_user,
        title="Another student's private assignment",
        course="Another course",
        due_date=context.assignment_due,
        canvas_course_id=4202,
        canvas_assignment_id=4303,
    )
    context.feed_token = issue_subscription(context.user)


@given("I have an active subscription and no eligible coursework events")
def step_active_subscription_without_events(context):
    """Create a subscription for a student with no calendar source records."""
    prepare_student(context)
    context.feed_token = issue_subscription(context.user)


@when("a calendar client requests my feed")
def step_calendar_client_requests_feed(context):
    """Fetch the current feed without a Canvas Plus login requirement."""
    feed_path = reverse("calendar_feed", args=[context.feed_token])
    with patch("requests.get", side_effect=AssertionError("Canvas request made")):
        context.feed_response = Client().get(feed_path)
    context.events = read_events(context.feed_response)


@then("the feed contains a point deadline with its assignment and course")
def step_feed_contains_point_deadline(context):
    """Verify the stored due date appears as a named point event."""
    deadline_event = next(
        event
        for event in context.events
        if "Calendar deadline assignment" in str(event["SUMMARY"])
    )
    assert "Calendar course" in str(deadline_event["SUMMARY"])
    assert deadline_event.decoded("DTSTART") == context.assignment_due
    assert "DTEND" not in deadline_event
    assert "DURATION" not in deadline_event


@then("the feed contains a timed study session with its assignment and course")
def step_feed_contains_study_session(context):
    """Verify the saved session appears with its assignment, course, and bounds."""
    session_event = next(
        event
        for event in context.events
        if "Calendar study assignment" in str(event["SUMMARY"])
    )
    assert "Calendar course" in str(session_event["SUMMARY"])
    assert session_event.decoded("DTSTART") == context.session_start
    assert session_event.decoded("DTEND") == context.session_end


@then("the feed excludes another student's coursework")
def step_feed_excludes_other_student(context):
    """Ensure feed contents remain scoped to the subscription owner."""
    summaries = [str(event["SUMMARY"]) for event in context.events]
    assert all(
        "Another student's private assignment" not in summary
        for summary in summaries
    )


@then("I receive a valid calendar with no events")
def step_receive_empty_calendar(context):
    """Check that an empty successful feed is a valid iCalendar document."""
    assert context.events == []
