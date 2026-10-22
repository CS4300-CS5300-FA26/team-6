"""Unit tests for choosing which graded work counts as recent."""
from datetime import datetime, timedelta, timezone

import pytest

from assignments.grades import recent_grades  # pylint: disable=import-error

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


def graded(title, days_ago, score=90.0):
    """One submission shaped like list_graded_submissions' results."""
    return {"assignment": title, "course": "CS 4300", "score": score,
            "graded_at": NOW - timedelta(days=days_ago)}


@pytest.mark.unit
def test_keeps_grade_inside_window():
    """A grade from a few days ago counts as recent."""
    grade = graded("Sprint Retro", days_ago=3)
    assert recent_grades([grade], now=NOW) == [grade]


@pytest.mark.unit
def test_drops_grade_older_than_window():
    """A grade older than 14 days is no longer recent."""
    assert recent_grades([graded("Project Proposal", days_ago=15)], now=NOW) == []


@pytest.mark.unit
def test_grade_exactly_at_window_edge_is_kept():
    """Exactly 14 days old is recent; one second older is not."""
    edge = graded("Use Case Diagram", days_ago=14)
    just_past = {**graded("Requirements Quiz", days_ago=14),
                 "graded_at": NOW - timedelta(days=14, seconds=1)}
    assert recent_grades([edge, just_past], now=NOW) == [edge]


@pytest.mark.unit
def test_sorts_newest_first():
    """Recent grades come back newest first, whatever the input order."""
    grades = [graded("Middle", days_ago=5), graded("Newest", days_ago=1),
              graded("Oldest", days_ago=10)]
    titles = [grade["assignment"] for grade in recent_grades(grades, now=NOW)]
    assert titles == ["Newest", "Middle", "Oldest"]


@pytest.mark.unit
def test_empty_input_gives_empty_result():
    """No graded work gives an empty list, not an error."""
    assert recent_grades([], now=NOW) == []


@pytest.mark.unit
def test_drops_submission_without_score():
    """A submission with no score is not graded work, but a zero is."""
    unscored = graded("Ungraded Draft", days_ago=2, score=None)
    zero = graded("Missed Quiz", days_ago=2, score=0.0)
    assert recent_grades([unscored, zero], now=NOW) == [zero]
