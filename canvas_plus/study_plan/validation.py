"""Validate AI-proposed sessions against study-plan constraints."""

from datetime import datetime, timedelta, timezone as datetime_timezone

from django.utils import timezone


class PlanValidationError(ValueError):
    """Raised when an AI-proposed plan violates scheduling constraints."""


def validate_plan(
    plan,
    assignment_deadlines,
    availability_windows,
    *,
    occupied_sessions=(),
    allow_late=False,
):
    """Validate a proposed plan against assignment and time-window constraints.

    Args:
        plan: Structured plan proposal to validate.
        assignment_deadlines: Mapping from selected assignment IDs to deadlines.
        availability_windows: Allowed aware start/end datetime pairs.
        occupied_sessions: Earlier sessions unavailable for new scheduling.
        allow_late: Whether sessions past an assignment deadline may be accepted.

        Raises:
        PlanValidationError: If the proposal violates any scheduling constraint.
    """
    sessions = getattr(plan, "sessions", None)
    if not sessions:
        raise PlanValidationError("A study plan must contain at least one session.")

    available = [
        _normalize_interval(window, "availability window")
        for window in availability_windows
    ]
    occupied = [
        _normalize_interval(session, "occupied session")
        for session in occupied_sessions
    ]
    proposed = []

    for session in sessions:
        assignment_id = getattr(session, "assignment_id", None)
        if assignment_id not in assignment_deadlines:
            raise PlanValidationError("A session references an unknown assignment.")

        start = getattr(session, "start", None)
        end = getattr(session, "end", None)
        start_utc, end_utc = _normalize_interval((start, end), "proposed session")
        duration = end_utc - start_utc
        if duration <= timedelta(0) or duration % timedelta(minutes=15):
            raise PlanValidationError(
                "Session duration must be a positive multiple of 15 minutes."
            )

        if not any(
            window_start <= start_utc and end_utc <= window_end
            for window_start, window_end in available
        ):
            raise PlanValidationError("A session falls outside availability.")

        deadline = assignment_deadlines[assignment_id]
        if not _is_aware_datetime(deadline):
            raise PlanValidationError("Assignment deadlines must be timezone-aware.")
        is_late = end_utc > deadline.astimezone(datetime_timezone.utc)
        late_flag = getattr(session, "late", None)
        if not isinstance(late_flag, bool) or late_flag != is_late:
            raise PlanValidationError("The session late flag does not match its deadline.")
        if is_late and not allow_late:
            raise PlanValidationError("Late sessions require explicit opt-in.")

        proposed.append((start_utc, end_utc))

    _reject_overlaps(proposed, "Sessions in the proposed plan overlap.")
    for proposed_start, proposed_end in proposed:
        if any(
            proposed_start < occupied_end and occupied_start < proposed_end
            for occupied_start, occupied_end in occupied
        ):
            raise PlanValidationError(
                "A proposed session overlaps an earlier plan session."
            )
    return plan


def _is_aware_datetime(value):
    """Return whether value is an aware datetime without raising on wrong types."""
    return isinstance(value, datetime) and not timezone.is_naive(value)


def _normalize_interval(interval, label):
    """Validate an interval pair and normalize it to UTC."""
    if isinstance(interval, (tuple, list)):
        if len(interval) != 2:
            raise PlanValidationError(f"Invalid {label} interval.")
        start, end = interval
    else:
        start = getattr(interval, "start", None)
        end = getattr(interval, "end", None)
    if not _is_aware_datetime(start) or not _is_aware_datetime(end):
        raise PlanValidationError(f"{label.capitalize()} datetimes must be timezone-aware.")
    return (
        start.astimezone(datetime_timezone.utc),
        end.astimezone(datetime_timezone.utc),
    )


def _reject_overlaps(intervals, message):
    """Reject intersecting intervals; touching boundaries are permitted."""
    ordered = sorted(intervals)
    active_end = None
    for start, end in ordered:
        if active_end is not None and start < active_end:
            raise PlanValidationError(message)
        active_end = end if active_end is None else max(active_end, end)