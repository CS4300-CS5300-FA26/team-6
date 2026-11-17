"""Tests for the public calendar feed endpoint."""

import hashlib
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.db import OperationalError
from django.urls import reverse
from django.utils import timezone
from icalendar import Calendar

from assignments.models import Assignment
from calendar_feed.models import CalendarSubscription
from study_plan.models import StudyPlan, StudySession


pytestmark = pytest.mark.django_db


def create_subscription(user, token):
    """Create a local bearer credential fixture without storing its plaintext."""
    CalendarSubscription.objects.create(
        user=user,
        token_digest=hashlib.sha256(token.encode()).hexdigest(),
    )


def request_calendar(client, token):
    """Request a feed as an unauthenticated calendar client."""
    return client.get(reverse("calendar_feed", args=[token]))


def parsed_events(response):
    """Parse the returned iCalendar document and collect its events."""
    calendar = Calendar.from_ical(response.content)
    return [component for component in calendar.walk() if component.name == "VEVENT"]


def test_feed_is_valid_when_empty_or_only_one_source_has_events(
    client, django_user_model
):
    """Empty, assignment-only, and session-only feeds are valid calendars."""
    users = [
        django_user_model.objects.create_user(username="empty-feed-owner"),
        django_user_model.objects.create_user(username="assignment-feed-owner"),
        django_user_model.objects.create_user(username="session-feed-owner"),
    ]
    tokens = ("empty-feed-secret", "assignment-feed-secret", "session-feed-secret")
    for user, token in zip(users, tokens):
        create_subscription(user, token)

    Assignment.objects.create(
        user=users[1],
        title="Assignment-only deadline",
        course="Assignment course",
        due_date=timezone.now() + timedelta(days=2),
        canvas_course_id=1001,
        canvas_assignment_id=1101,
    )

    StudySession.objects.create(
        plan=StudyPlan.objects.create(user=users[2]),
        assignment=Assignment.objects.create(
            user=users[2],
            title="Session-only assignment",
            course="Session course",
            canvas_course_id=1002,
            canvas_assignment_id=1102,
        ),
        start=timezone.now() + timedelta(days=1),
        end=timezone.now() + timedelta(days=1, hours=1),
    )

    with patch("requests.get", side_effect=AssertionError("Canvas request made")):
        responses = [request_calendar(client, token) for token in tokens]

    for response in responses:
        assert response.status_code == 200
        assert response["Content-Type"].startswith("text/calendar")
    empty_events, assignment_events, session_events = [
        parsed_events(response) for response in responses
    ]
    assert empty_events == []
    assert len(assignment_events) == 1
    assert "Assignment-only deadline" in str(assignment_events[0]["SUMMARY"])
    assert len(session_events) == 1
    assert "Session-only assignment" in str(session_events[0]["SUMMARY"])


def test_feed_returns_error_when_local_data_cannot_be_read(
    client, django_user_model
):
    """A database read failure must not be presented as a valid empty calendar."""
    user = django_user_model.objects.create_user(username="failed-read-owner")
    token = "failed-read-feed-secret"
    create_subscription(user, token)

    with patch.object(
        Assignment.objects,
        "filter",
        side_effect=OperationalError("Local assignment read failed"),
    ):
        response = request_calendar(client, token)

    assert response.status_code != 200
