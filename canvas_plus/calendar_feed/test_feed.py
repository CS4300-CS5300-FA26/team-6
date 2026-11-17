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


def request_events(client, token):
    """Fetch and parse the feed, requiring a successful endpoint response."""
    response = request_calendar(client, token)
    assert response.status_code == 200
    return parsed_events(response)


def assert_source_updates_refreshed(client, token, assignment, session_assignment, session):
    """Verify source edits appear in the next feed under the same event UIDs."""
    initial_events = request_events(client, token)
    initial_assignment = next(
        event for event in initial_events if "Original deadline" in str(event["SUMMARY"])
    )
    initial_session = next(
        event
        for event in initial_events
        if "Original session assignment" in str(event["SUMMARY"])
    )
    assignment_uid = str(initial_assignment["UID"])
    session_uid = str(initial_session["UID"])

    assignment.title = "Updated deadline"
    assignment.course = "Updated assignment course"
    assignment.due_date += timedelta(days=1)
    assignment.save(update_fields=["title", "course", "due_date"])
    session_assignment.title = "Updated session assignment"
    session_assignment.course = "Updated session course"
    session_assignment.save(update_fields=["title", "course"])
    session.start += timedelta(hours=2)
    session.end += timedelta(hours=2)
    session.save(update_fields=["start", "end"])

    updated_events = request_events(client, token)
    updated_assignment = next(
        event for event in updated_events if "Updated deadline" in str(event["SUMMARY"])
    )
    updated_session = next(
        event
        for event in updated_events
        if "Updated session assignment" in str(event["SUMMARY"])
    )
    assert str(updated_assignment["UID"]) == assignment_uid
    assert str(updated_session["UID"]) == session_uid
    assert updated_assignment.decoded("DTSTART") == assignment.due_date
    assert updated_session.decoded("DTSTART") == session.start
    assert updated_session.decoded("DTEND") == session.end


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


def test_source_deletion_removes_events_and_source_updates_refresh_them(
    client, django_user_model
):
    """Feed refreshes reflect changed source values and omit deleted sources."""
    user = django_user_model.objects.create_user(username="source-refresh-owner")
    token = "source-refresh-feed-secret"
    create_subscription(user, token)
    assignment_due = timezone.now() + timedelta(days=2)
    assignment = Assignment.objects.create(
        user=user,
        title="Original deadline",
        course="Original assignment course",
        due_date=assignment_due,
        canvas_course_id=1401,
        canvas_assignment_id=1501,
    )
    session_assignment = Assignment.objects.create(
        user=user,
        title="Original session assignment",
        course="Original session course",
        canvas_course_id=1402,
        canvas_assignment_id=1502,
    )
    session = StudySession.objects.create(
        plan=StudyPlan.objects.create(user=user),
        assignment=session_assignment,
        start=timezone.now() + timedelta(days=1),
        end=timezone.now() + timedelta(days=1, hours=1),
    )

    with patch("requests.get", side_effect=AssertionError("Canvas request made")):
        assert_source_updates_refreshed(
            client, token, assignment, session_assignment, session
        )

        assignment.delete()
        session.plan.delete()
        deleted_events = request_events(client, token)

    assert deleted_events == []


def test_feed_includes_all_events_above_1000(client, django_user_model):
    """The feed includes every eligible event and does not cap at 1,000."""
    user = django_user_model.objects.create_user(username="large-feed-owner")
    token = "large-feed-secret"
    create_subscription(user, token)
    due_date = timezone.now() + timedelta(days=10)
    Assignment.objects.bulk_create(
        [
            Assignment(
                user=user,
                title=f"Assignment {index}",
                course="Large feed course",
                due_date=due_date,
                canvas_course_id=1600,
                canvas_assignment_id=1700 + index,
            )
            for index in range(1001)
        ]
    )

    with patch("requests.get", side_effect=AssertionError("Canvas request made")):
        response = request_calendar(client, token)

    assert response.status_code == 200
    assert len(parsed_events(response)) == 1001
