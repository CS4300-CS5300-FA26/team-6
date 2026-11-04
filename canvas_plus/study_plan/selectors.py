"""Read-only queries for displaying a student's study plan."""

from datetime import date

from study_plan.models import StudyPlan  # pylint: disable=import-error

INVALID_DAY_MESSAGE = "That day is not a valid date."


def latest_plan_sessions(user, day=None):
    """Sessions of the user's most recent plan in start order, or None if they have no plan."""
    plan = StudyPlan.objects.filter(user=user).order_by("-created_at").first()
    if plan is None:
        return None
    sessions = plan.sessions.select_related("assignment").order_by("start")
    if day is not None:
        # start__date converts to the local time zone (USE_TZ) before taking the date.
        sessions = sessions.filter(start__date=day)
    return sessions


def study_plan_context(user, raw_day):
    """Template context for the plan section; raw_day is the untrusted ?date= value."""
    day = None
    if raw_day:
        try:
            day = date.fromisoformat(raw_day)
        except ValueError:
            return {"study_day_error": INVALID_DAY_MESSAGE}
    return {"study_sessions": latest_plan_sessions(user, day), "study_day": day}
