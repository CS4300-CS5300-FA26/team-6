"""Subscription and calendar-feed service entry points."""

import hashlib
import secrets
from datetime import date, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone
from icalendar import Calendar, Event, Timezone

from assignments.models import Assignment
from study_plan.models import StudySession
from .models import CalendarSubscription


def issue_subscription(user):
    """Issue or rotate a user's calendar subscription credential."""
    token = secrets.token_urlsafe(32)
    token_digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    CalendarSubscription.objects.update_or_create(
        user=user,
        defaults={"token_digest": token_digest},
    )
    return token


def get_subscription_by_token(token):
    """Resolve a bearer token without persisting or returning its plaintext."""
    token_digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return CalendarSubscription.objects.select_related("user").filter(
        token_digest=token_digest
    ).first()


def _add_event(calendar, uid, summary, date_times, current_time):
    """Add one source event to the calendar without descriptions."""
    event = Event()
    event.add("uid", uid)
    event.add("dtstamp", current_time)
    event.add("summary", summary)
    event.add("dtstart", date_times[0])
    if len(date_times) == 2:
        event.add("dtend", date_times[1])
    calendar.add_component(event)


def _add_assignment_events(calendar, user, cutoff, configured_timezone, current_time):
    """Add eligible due-dated assignments and return their local event years."""
    event_years = set()
    assignments = Assignment.objects.filter(
        user=user,
        due_date__gt=cutoff,
    ).order_by("pk")
    for assignment in assignments.iterator():
        due_date = assignment.due_date.astimezone(configured_timezone)
        event_years.add(due_date.year)
        _add_event(
            calendar,
            f"assignment-{assignment.pk}@canvas-plus",
            f"{assignment.title} - {assignment.course}",
            (due_date,),
            current_time,
        )
    return event_years


def _add_session_events(calendar, user, cutoff, configured_timezone, current_time):
    """Add eligible sessions across the user's plans and return their years."""
    event_years = set()
    sessions = StudySession.objects.filter(
        plan__user=user,
        assignment__user=user,
        end__gt=cutoff,
    ).select_related("assignment").order_by("pk")
    for session in sessions.iterator():
        session_start = session.start.astimezone(configured_timezone)
        session_end = session.end.astimezone(configured_timezone)
        event_years.update((session_start.year, session_end.year))
        _add_event(
            calendar,
            f"session-{session.pk}@canvas-plus",
            f"{session.assignment.title} - {session.assignment.course}",
            (session_start, session_end),
            current_time,
        )
    return event_years


def generate_feed(user):
    """Build the user's current calendar feed from local records."""
    retention_days = settings.CALENDAR_FEED_RETENTION_DAYS
    if (
        isinstance(retention_days, bool)
        or not isinstance(retention_days, int)
        or retention_days < 0
    ):
        raise ImproperlyConfigured(
            "CALENDAR_FEED_RETENTION_DAYS must be a nonnegative integer."
        )

    configured_timezone = ZoneInfo(settings.TIME_ZONE)
    current_time = timezone.now()
    cutoff = current_time - timedelta(days=retention_days)
    calendar = Calendar()
    calendar.add("prodid", "-//Canvas Plus//Calendar Feed//EN")
    calendar.add("version", "2.0")
    event_years = _add_assignment_events(
        calendar, user, cutoff, configured_timezone, current_time
    ) | _add_session_events(calendar, user, cutoff, configured_timezone, current_time)
    if event_years:
        first_event_year = min(event_years)
        last_event_year = max(event_years)
        last_timezone_year = min(last_event_year + 1, date.max.year)
        calendar.add_component(
            Timezone.from_tzinfo(
                configured_timezone,
                first_date=date(first_event_year, 1, 1),
                last_date=date(last_timezone_year, 1, 1)
                if last_timezone_year > last_event_year
                else date.max,
            )
        )

    return calendar.to_ical()
