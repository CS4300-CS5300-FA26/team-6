"""Grouping a student's assignments into the days of the current week."""

from datetime import timedelta

from django.utils import timezone

from .models import Assignment

UNAVAILABLE_MESSAGE = "This Week cannot be loaded right now."


def this_week(user, today):
    """Seven (day, assignments) pairs, Monday through Sunday, for the week containing today."""
    monday = today - timedelta(days=today.weekday())
    days = [monday + timedelta(days=n) for n in range(7)]
    # __date converts to local time first, so a late-Sunday deadline stays in this week.
    assignments = (
        Assignment.objects.filter(user=user, due_date__date__range=(days[0], days[-1]))
        .exclude(sync_state="missing")
        .order_by("due_date")
    )
    by_day = {day: [] for day in days}
    for assignment in assignments:
        by_day[timezone.localtime(assignment.due_date).date()].append(assignment)
    return [(day, by_day[day]) for day in days]


def this_week_context(user, canvas_context, today):
    """The This Week part of the dashboard context, given what loading Canvas produced."""
    # Checked first: the view also marks assignments unavailable when there is no connection,
    # and the page already shows the connect or reconnect prompt then.
    if canvas_context["canvas_connection_missing"] or canvas_context["canvas_connection_expired"]:
        return {}
    if canvas_context["assignments_unavailable"] or "assignment_sync_error" in canvas_context:
        return {"this_week_error": UNAVAILABLE_MESSAGE}
    return {"this_week": this_week(user, today)}
