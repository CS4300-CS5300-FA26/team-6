"""Arranging upcoming coursework by the student's local due day."""
from datetime import timedelta
from itertools import groupby

from django.utils import timezone

HUB_WINDOW = timedelta(days=7)


def due_this_week(assignments, now):
    """Keep work due from now through the next seven days."""
    return [assignment for assignment in assignments
            if assignment["due_date"] is not None
            and now <= assignment["due_date"] <= now + HUB_WINDOW]


def _day_label(day, today):
    if day is None:
        return "No due date"
    if day == today:
        return f"Today · {day:%a %b} {day.day}"
    return f"{day:%A} · {day:%b} {day.day}"


def group_by_day(assignments, now):
    """Group due-date-sorted work under local day headers such as "Thursday · Nov 12"."""
    today = timezone.localdate(now)

    def local_day(assignment):
        due_date = assignment["due_date"]
        return None if due_date is None else timezone.localdate(due_date)

    return [{"label": _day_label(day, today), "assignments": list(work)}
            for day, work in groupby(assignments, key=local_day)]
