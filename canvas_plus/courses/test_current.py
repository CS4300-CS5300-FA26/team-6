"""Unit tests for which Canvas courses count as current."""
from datetime import datetime, timezone

import pytest

from courses.current import is_current  # pylint: disable=import-error

NOW = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)


def course_with_term_end(end_at):
    """A Canvas course whose term ends at the given time."""
    return {"name": "Example Course", "term": {"end_at": end_at}}


@pytest.mark.unit
def test_course_whose_term_has_not_ended_is_current():
    """A course in an unfinished term stays in the list."""
    assert is_current(course_with_term_end("2027-01-09T07:00:00Z"), NOW)


@pytest.mark.unit
def test_course_whose_term_has_ended_is_not_current():
    """A course left open after its term ended is hidden."""
    assert not is_current(course_with_term_end("2026-06-01T06:00:00Z"), NOW)


@pytest.mark.unit
def test_course_without_term_end_date_is_current():
    """A course with no term dates, like advising, stays in the list."""
    assert is_current(course_with_term_end(None), NOW)


@pytest.mark.unit
@pytest.mark.parametrize("end_at", ["not a date", "2027-01-09T07:00:00"])
def test_course_with_unreadable_term_end_date_is_current(end_at):
    """A broken or timezone-less date can't prove the term ended, so the course stays."""
    assert is_current(course_with_term_end(end_at), NOW)


@pytest.mark.unit
@pytest.mark.parametrize("course", [
    {"id": 42, "name": "Advising"},
    {"id": 42, "name": "Advising", "term": None},
], ids=["absent-term", "null-term"])
def test_course_without_term_information_remains_current(course):
    """Given absent or null term information, when courses are selected, then retain the course."""
    assert is_current(course, NOW)


@pytest.mark.unit
def test_course_with_offset_term_end_stops_being_current_after_equivalent_utc_instant():
    """Given an offset term end, when its equivalent UTC instant passes, then hide the course.

    Enrollment terms document offset timestamps:
    https://developerdocs.instructure.com/services/canvas/resources/enrollment_terms
    """
    course = course_with_term_end("2026-10-31T06:00:00-06:00")
    before = datetime(2026, 10, 31, 11, 59, 59, tzinfo=timezone.utc)
    after = datetime(2026, 10, 31, 12, 0, 1, tzinfo=timezone.utc)
    assert is_current(course, before)
    assert not is_current(course, after)
