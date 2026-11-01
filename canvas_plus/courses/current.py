"""Deciding which Canvas courses belong in the current course list."""
from datetime import datetime


def is_current(course, now):
    """A course is current unless its term has an end date that has passed."""
    term_end = (course.get("term") or {}).get("end_at")
    if term_end is None:
        return True
    try:
        return datetime.fromisoformat(term_end) > now
    except (TypeError, ValueError):
        return True  # an unreadable date can't prove the term ended
