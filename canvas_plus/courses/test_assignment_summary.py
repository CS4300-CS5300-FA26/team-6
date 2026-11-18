"""Boundary and ordering rules for the Course Hub assignment summary."""
from datetime import datetime, timedelta, timezone

import pytest

NOW = datetime(2026, 11, 16, 12, tzinfo=timezone.utc)


def item(title, days=None, score=None):
    """An assignment with a due date relative to a fixed clock."""
    return {"title": title, "due_date": None if days is None else NOW + timedelta(days=days),
            "score": score, "points_possible": 100}


@pytest.mark.unit
@pytest.mark.parametrize("assignments, upcoming, past", [
    ([item("now", 0), item("before", -1)], ["now"], ["before"]),
    ([item("undated"), item("later", 1)], ["later", "undated"], []),
    ([item("early grade", 4, 0), item("undated grade", score=92)],
     [], ["early grade", "undated grade"]),
    ([item(str(day), day) for day in [4, 2, 3, 1, 0, 5, 6]],
     ["0", "1", "2", "3", "4", "5", "6"], []),
    ([item(str(day), day) for day in [-4, -2, -3, -1, -7, -5, -6]],
     [], ["-1", "-2", "-3", "-4", "-5", "-6", "-7"]),
    ([], [], []),
])
def test_split_summary(assignments, upcoming, past):
    """Each view has the correct membership and ordering; trimming is the view's job."""
    from courses.assignment_summary import split_assignments  # pylint: disable=import-outside-toplevel,import-error
    result = split_assignments(assignments, NOW)
    assert [entry["title"] for entry in result["upcoming"]] == upcoming
    assert [entry["title"] for entry in result["past"]] == past
