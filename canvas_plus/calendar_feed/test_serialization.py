"""Tests for calendar event selection and serialization."""

from datetime import datetime, timedelta, timezone as datetime_timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings
from django.utils import timezone
from icalendar import Calendar

from assignments.models import Assignment
from calendar_feed.services import generate_feed
from study_plan.models import StudyPlan, StudySession


pytestmark = pytest.mark.django_db


def calendar_events(user):
    """Return parsed VEVENT components from the user's generated feed."""
    calendar = Calendar.from_ical(generate_feed(user))
    return [component for component in calendar.walk() if component.name == "VEVENT"]


def calendar_summaries(user):
    """Return normalized event summaries for retention assertions."""
    return [str(event["SUMMARY"]) for event in calendar_events(user)]


def create_retention_assignment(user, title, due_date, identity):
    """Create a local assignment used to exercise one retention boundary."""
    return Assignment.objects.create(
        user=user,
        title=title,
        course=f"Course {identity}",
        due_date=due_date,
        canvas_course_id=1200 + identity,
        canvas_assignment_id=1300 + identity,
    )


def create_retention_session(user, title, end, identity):
    """Create a session ending at the supplied retention boundary."""
    assignment = create_retention_assignment(user, title, None, identity)
    plan = StudyPlan.objects.create(user=user)
    return StudySession.objects.create(
        plan=plan,
        assignment=assignment,
        start=end - timedelta(hours=1),
        end=end,
    )


def assert_invalid_retention_rejected(user, retention):
    """Reject invalid retention settings before generating a calendar."""
    with override_settings(CALENDAR_FEED_RETENTION_DAYS=retention):
        with pytest.raises(ImproperlyConfigured):
            generate_feed(user)


def next_new_york_spring_transition(now):
    """Return the next New York spring-forward instant within retention."""
    year = now.year
    while True:
        march_first = datetime(year, 3, 1)
        first_sunday = 1 + (6 - march_first.weekday()) % 7
        transition = datetime(
            year,
            3,
            first_sunday + 7,
            7,
            tzinfo=datetime_timezone.utc,
        )
        if transition > now - timedelta(days=100):
            return transition
        year += 1


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
            due_date=timezone.now().replace(microsecond=0) + timedelta(days=offset),
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
        due_date=timezone.now().replace(microsecond=0) + timedelta(days=2),
        canvas_course_id=301,
        canvas_assignment_id=401,
    )

    original_events = calendar_events(user)
    assert len(original_events) == 1
    original_event = original_events[0]
    original_uid = str(original_event["UID"])

    updated_due_date = timezone.now().replace(microsecond=0) + timedelta(days=5)
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


def test_feed_includes_sessions_from_all_owned_plans(django_user_model):
    """All sessions from every owned plan appear, but another student's do not."""
    user = django_user_model.objects.create_user(username="session-owner")
    other_user = django_user_model.objects.create_user(username="other-session-owner")
    now = timezone.now().replace(microsecond=0)

    assignments = [
        Assignment.objects.create(
            user=user,
            title=f"Assignment {index}",
            course=f"Course {index}",
            canvas_course_id=500 + index,
            canvas_assignment_id=600 + index,
        )
        for index in range(1, 5)
    ]
    plans = [StudyPlan.objects.create(user=user) for _ in range(2)]

    session_times = [
        (now - timedelta(days=2), now - timedelta(days=2) + timedelta(hours=1)),
        (now - timedelta(minutes=30), now + timedelta(minutes=30)),
        (now + timedelta(days=1), now + timedelta(days=1, hours=2)),
        (now + timedelta(days=3), now + timedelta(days=3, hours=2)),
    ]
    for index, assignment in enumerate(assignments):
        StudySession.objects.create(
            plan=plans[index // 2],
            assignment=assignment,
            start=session_times[index][0],
            end=session_times[index][1],
        )

    StudySession.objects.create(
        plan=StudyPlan.objects.create(user=other_user),
        assignment=Assignment.objects.create(
            user=other_user,
            title="Private other assignment",
            course="Private other course",
            canvas_course_id=700,
            canvas_assignment_id=800,
        ),
        start=now + timedelta(days=1),
        end=now + timedelta(days=1, hours=1),
    )

    events = calendar_events(user)
    sessions = [event for event in events if "DTEND" in event]
    assert len(sessions) == len(session_times)
    for index, assignment in enumerate(assignments):
        event = next(item for item in sessions if assignment.title in str(item["SUMMARY"]))
        assert assignment.course in str(event["SUMMARY"])
        assert event.decoded("DTSTART") == session_times[index][0]
        assert event.decoded("DTEND") == session_times[index][1]
    assert all("Private other" not in str(event["SUMMARY"]) for event in events)


def test_feed_uses_configured_timezone_across_dst(django_user_model):
    """Assignment and session times preserve instants and New York DST offsets."""
    user = django_user_model.objects.create_user(username="dst-calendar-owner")
    timezone_name = "America/New_York"
    configured_timezone = ZoneInfo(timezone_name)
    transition = next_new_york_spring_transition(timezone.now())
    due_instant = transition - timedelta(minutes=30)
    session_end = transition + timedelta(minutes=30)

    assignment = Assignment.objects.create(
        user=user,
        title="DST assignment",
        course="DST course",
        due_date=due_instant,
        canvas_course_id=901,
        canvas_assignment_id=902,
    )
    plan = StudyPlan.objects.create(user=user)
    StudySession.objects.create(
        plan=plan,
        assignment=assignment,
        start=due_instant,
        end=session_end,
    )

    with override_settings(TIME_ZONE=timezone_name), timezone.override(timezone_name):
        events = calendar_events(user)

    assignment_event = next(event for event in events if "DTEND" not in event)
    session_event = next(event for event in events if "DTEND" in event)
    encoded_due = assignment_event.decoded("DTSTART")
    encoded_start = session_event.decoded("DTSTART")
    encoded_end = session_event.decoded("DTEND")

    assert encoded_due.astimezone(datetime_timezone.utc) == due_instant
    assert encoded_start.astimezone(datetime_timezone.utc) == due_instant
    assert encoded_end.astimezone(datetime_timezone.utc) == session_end
    assert encoded_due.utcoffset() == due_instant.astimezone(configured_timezone).utcoffset()
    assert encoded_start.utcoffset() == due_instant.astimezone(configured_timezone).utcoffset()
    assert encoded_end.utcoffset() == session_end.astimezone(configured_timezone).utcoffset()


def test_events_obey_elapsed_retention_cutoffs(django_user_model):
    """Events expire at elapsed-day cutoffs but future events remain eligible."""
    user = django_user_model.objects.create_user(username="retention-calendar-owner")
    now = datetime(2026, 6, 1, 12, 0, tzinfo=datetime_timezone.utc)
    default_cutoff = now - timedelta(days=112)
    retention_sources = (
        ("default-before-assignment", default_cutoff + timedelta(seconds=1)),
        ("default-at-assignment", default_cutoff),
        ("default-after-assignment", default_cutoff - timedelta(seconds=1)),
        ("zero-before-assignment", now + timedelta(seconds=1)),
        ("zero-at-assignment", now),
        ("zero-after-assignment", now - timedelta(seconds=1)),
        ("future-assignment", now + timedelta(days=1000)),
    )
    for identity, (title, due_date) in enumerate(retention_sources, start=1):
        create_retention_assignment(user, title, due_date, identity)

    session_sources = (
        ("default-before-session", default_cutoff + timedelta(seconds=1)),
        ("default-at-session", default_cutoff),
        ("default-after-session", default_cutoff - timedelta(seconds=1)),
        ("zero-before-session", now + timedelta(seconds=1)),
        ("zero-at-session", now),
        ("zero-after-session", now - timedelta(seconds=1)),
        ("future-session", now + timedelta(days=1000)),
    )
    for identity, (title, session_end) in enumerate(session_sources, start=20):
        create_retention_session(user, title, session_end, identity)

    with patch("django.utils.timezone.now", return_value=now):
        default_summaries = calendar_summaries(user)
    assert settings.CALENDAR_FEED_RETENTION_DAYS == 112
    assert any("default-before-assignment" in summary for summary in default_summaries)
    assert any("default-before-session" in summary for summary in default_summaries)
    for expired_title in (
        "default-at-assignment",
        "default-after-assignment",
        "default-at-session",
        "default-after-session",
    ):
        assert all(expired_title not in summary for summary in default_summaries)

    with override_settings(CALENDAR_FEED_RETENTION_DAYS=0):
        with patch("django.utils.timezone.now", return_value=now):
            zero_day_summaries = calendar_summaries(user)
    assert any("zero-before-assignment" in summary for summary in zero_day_summaries)
    assert any("zero-before-session" in summary for summary in zero_day_summaries)
    assert any("future-assignment" in summary for summary in zero_day_summaries)
    assert any("future-session" in summary for summary in zero_day_summaries)
    for expired_title in (
        "zero-at-assignment",
        "zero-after-assignment",
        "zero-at-session",
        "zero-after-session",
    ):
        assert all(expired_title not in summary for summary in zero_day_summaries)

    for invalid_retention in (-1, 1.5, "112", True):
        assert_invalid_retention_rejected(user, invalid_retention)
