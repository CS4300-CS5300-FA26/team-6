"""Choosing which graded Canvas work counts as recent."""
from datetime import timedelta

from django.utils import timezone

RECENT_WINDOW = timedelta(days=14)


def recent_grades(grades, now=None):
    """Return scored submissions graded within the window, newest first."""
    cutoff = (now or timezone.now()) - RECENT_WINDOW
    recent = [
        grade for grade in grades
        if grade["score"] is not None and grade["graded_at"] >= cutoff
    ]
    return sorted(recent, key=lambda grade: grade["graded_at"], reverse=True)
