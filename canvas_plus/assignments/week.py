"""Grouping a student's assignments into the days of the current week."""

from datetime import timedelta

from django.utils import timezone

from .models import Assignment


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
