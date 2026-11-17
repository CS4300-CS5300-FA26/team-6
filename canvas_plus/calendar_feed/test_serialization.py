"""Tests for calendar event selection and serialization."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone
from icalendar import Calendar

from assignments.models import Assignment
from calendar_feed.services import generate_feed


pytestmark = pytest.mark.django_db


def calendar_events(user):
    """Return parsed VEVENT components from the user's generated feed."""
    calendar = Calendar.from_ical(generate_feed(user))
    return [component for component in calendar.walk() if component.name == "VEVENT"]


def test_feed_includes_stored_due_dates_for_every_sync_state(
    django_user_model,
):
    """Every due-dated local assignment is exported regardless of sync state."""
    user = django_user_model.objects.create_user(username="calendar-assignment-owner")
    expected_due_dates = {}
    for offset, sync_state in enumerate(("synced", "missing", "failed"), start=1):
        assignment = Assignment.objects.create(
            user=user,
            title=f"Assignment {sync_state}",
            course=f"Course {sync_state}",
            due_date=timezone.now() + timedelta(days=offset),
            description=f"Private description {sync_state}",
            sync_state=sync_state,
            canvas_course_id=100 + offset,
            canvas_assignment_id=200 + offset,
        )
        expected_due_dates[assignment.title] = assignment.due_date

    Assignment.objects.create(
        user=user,
        title="Undated assignment",
        course="Undated course",
        description="Must not be exported",
        canvas_course_id=104,
        canvas_assignment_id=204,
    )

    with patch("requests.get", side_effect=AssertionError("Canvas request made")):
        events = calendar_events(user)

    assert len(events) == len(expected_due_dates)
    summaries = [str(event.get("SUMMARY", "")) for event in events]
    for title, due_date in expected_due_dates.items():
        event = next(item for item in events if title in str(item.get("SUMMARY", "")))
        summary = str(event["SUMMARY"])
        assert title in summary
        assert f"Course {title.removeprefix('Assignment ')}" in summary
        assert event.decoded("DTSTART") == due_date
        assert "DESCRIPTION" not in event
    assert all("Undated assignment" not in summary for summary in summaries)


def test_assignment_event_is_a_point_with_stable_uid(django_user_model):
    """An assignment's UID is stable while updated source values replace old ones."""
    user = django_user_model.objects.create_user(username="stable-event-owner")
    assignment = Assignment.objects.create(
        user=user,
        title="Original assignment title",
        course="Original course name",
        due_date=timezone.now() + timedelta(days=2),
        canvas_course_id=301,
        canvas_assignment_id=401,
    )

    original_events = calendar_events(user)
    assert len(original_events) == 1
    original_event = original_events[0]
    original_uid = str(original_event["UID"])

    updated_due_date = timezone.now() + timedelta(days=5)
    assignment.title = "Updated assignment title"
    assignment.course = "Updated course name"
    assignment.due_date = updated_due_date
    assignment.save(update_fields=["title", "course", "due_date"])

    updated_events = calendar_events(user)
    assert len(updated_events) == 1
    updated_event = updated_events[0]
    assert str(updated_event["UID"]) == original_uid
    assert "Updated assignment title" in str(updated_event["SUMMARY"])
    assert "Updated course name" in str(updated_event["SUMMARY"])
    assert "Original assignment title" not in str(updated_event["SUMMARY"])
    assert updated_event.decoded("DTSTART") == updated_due_date
    assert "DTEND" not in updated_event
    assert "DURATION" not in updated_event
