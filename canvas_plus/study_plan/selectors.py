"""Read-only queries for displaying a student's study plan."""

from datetime import date

from django.utils import timezone

from study_plan.models import StudyPlan, StudySession  # pylint: disable=import-error

INVALID_DAY_MESSAGE = "That day is not a valid date."


def plan_sessions(user, day=None):
    """Sessions from all of the user's plans in start order, or None if they have no plan."""
    if not StudyPlan.objects.filter(user=user).exists():
        return None
    sessions = (
        StudySession.objects.filter(plan__user=user)
        .select_related("assignment")
        .order_by("start")
    )
    if day is not None:
        # start__date converts to the local time zone (USE_TZ) before taking the date.
        sessions = sessions.filter(start__date=day)
    return sessions


def study_plan_context(user, raw_day):
    """Template context for the plan section; raw_day is the untrusted ?date= value."""
    day = timezone.localdate() if raw_day is None else None
    if raw_day:
        try:
            day = date.fromisoformat(raw_day)
        except ValueError:
            return {"study_day_error": INVALID_DAY_MESSAGE}
    return {"study_sessions": plan_sessions(user, day), "study_day": day}
