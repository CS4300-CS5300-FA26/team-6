"""Unit tests for the dashboard urgency label."""
from datetime import datetime, timedelta, timezone

import pytest

from assignments.priority import priority  # pylint: disable=import-error

NOW = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)


@pytest.mark.unit
@pytest.mark.parametrize("due_date, submitted, expected", [
    (NOW + timedelta(hours=48), False, "Due soon"),
    (NOW + timedelta(hours=48, seconds=1), False, "Upcoming"),
    (NOW + timedelta(days=6), False, "Upcoming"),
    (NOW, False, "Due soon"),
    (NOW - timedelta(seconds=1), False, "Past due"),
    (NOW + timedelta(hours=1), True, "Submitted"),
    (NOW - timedelta(days=1), True, "Submitted"),
    (NOW + timedelta(days=6), True, "Submitted"),
    (None, False, "Upcoming"),
])
def test_priority_label(due_date, submitted, expected):
    """Each rule row and boundary from the spec maps to exactly one label."""
    assert priority(due_date, submitted, NOW) == expected
