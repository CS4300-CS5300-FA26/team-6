"""Mapping an assignment's due date and submission state to a dashboard badge."""
from datetime import timedelta

DUE_SOON_WINDOW = timedelta(hours=48)


def priority(due_date, submitted, now):
    """Return the dashboard badge label for one assignment."""
    if submitted:
        return "Submitted"
    if due_date is None:
        return "Upcoming"
    if due_date < now:
        return "Past due"
    if due_date - now <= DUE_SOON_WINDOW:
        return "Due soon"
    return "Upcoming"
