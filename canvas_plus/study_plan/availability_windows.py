"""Prepare usable, user-scoped availability intervals for plan generation."""

from datetime import datetime, timedelta, timezone as datetime_timezone
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

from availability.models import Availability


def prepare_availability_windows(user, now=None, occupied_sessions=()):
    """Return the user's future free intervals as aware local datetimes.

    Args:
        user: Owner whose availability should be prepared.
        now: Optional aware reference datetime used to trim past time.
        occupied_sessions: Earlier sessions or (start, end) intervals to subtract.
    """
    local_timezone = ZoneInfo(settings.TIME_ZONE)
    current_time = now or timezone.now()
    if timezone.is_naive(current_time):
        raise ValueError("now must be timezone-aware")
    current_utc = current_time.astimezone(datetime_timezone.utc)

    intervals = []
    for availability in Availability.objects.filter(user=user):
        start = _resolve_local_datetime(
            availability.date,
            availability.start_time,
            local_timezone,
        ).astimezone(datetime_timezone.utc)
        end = _resolve_local_datetime(
            availability.date,
            availability.end_time,
            local_timezone,
        ).astimezone(datetime_timezone.utc)
        if end <= start or end <= current_utc:
            continue
        intervals.append((max(start, current_utc), end))

    merged = _merge_intervals(intervals)
    free_intervals = _subtract_intervals(merged, occupied_sessions)
    return [
        (start.astimezone(local_timezone), end.astimezone(local_timezone))
        for start, end in free_intervals
    ]


def _resolve_local_datetime(day, local_time, local_timezone):
    """Resolve a local wall time, shifting gaps forward and choosing standard time."""
    wall_time = datetime.combine(day, local_time)
    valid_candidates = []

    for fold in (0, 1):
        candidate = wall_time.replace(tzinfo=local_timezone, fold=fold)
        round_trip = candidate.astimezone(datetime_timezone.utc).astimezone(local_timezone)
        round_trip_wall_time = round_trip.replace(tzinfo=None)
        if round_trip_wall_time == wall_time:
            valid_candidates.append(candidate)

    if valid_candidates:
        return next(
            (candidate for candidate in valid_candidates if candidate.fold == 1),
            valid_candidates[0],
        )
    search_time = wall_time.replace(second=0, microsecond=0) + timedelta(minutes=1)
    while True:
        for fold in (0, 1):
            candidate = search_time.replace(tzinfo=local_timezone, fold=fold)
            round_trip = candidate.astimezone(datetime_timezone.utc).astimezone(local_timezone)
            if round_trip.replace(tzinfo=None) == search_time:
                if fold == 1:
                    return candidate
                alternate = search_time.replace(tzinfo=local_timezone, fold=1)
                alternate_round_trip = alternate.astimezone(
                    datetime_timezone.utc
                ).astimezone(local_timezone)
                if alternate_round_trip.replace(tzinfo=None) == search_time:
                    return alternate
                return candidate
        search_time += timedelta(minutes=1)


def _merge_intervals(intervals):
    """Merge overlapping or adjacent UTC intervals."""
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _subtract_intervals(intervals, occupied_sessions):
    """Subtract occupied UTC intervals from merged availability."""
    occupied = []
    for session in occupied_sessions:
        if isinstance(session, (tuple, list)):
            start, end = session
        else:
            start, end = session.start, session.end
        if timezone.is_naive(start) or timezone.is_naive(end):
            raise ValueError("occupied session datetimes must be timezone-aware")
        start = start.astimezone(datetime_timezone.utc)
        end = end.astimezone(datetime_timezone.utc)
        if end > start:
            occupied.append((start, end))

    free = intervals
    for occupied_start, occupied_end in sorted(occupied):
        remaining = []
        for start, end in free:
            if occupied_end <= start or occupied_start >= end:
                remaining.append((start, end))
                continue
            if occupied_start > start:
                remaining.append((start, occupied_start))
            if occupied_end < end:
                remaining.append((occupied_end, end))
        free = remaining
    return free