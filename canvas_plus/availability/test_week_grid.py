"""Unit tests for week_grid.py, the weekly availability grid on the Study Plan page.

The module's interface, which these tests define:
* GRID_HOURS = range(8, 20): one-hour blocks from 8 AM; the last is 7-8 PM.
* parse_block(value): "2020-11-19T10" -> (date(2020, 11, 19), 10); anything else -> None.
* week_grid(user, today): seven dicts, Monday to Sunday, each
  {"date": date, "editable": bool, "blocks": [{"hour": int, "value": str, "selected": bool}]}.
* save_week(user, today, values): values is request.POST.getlist("block").

Everything takes today as an argument, so no test depends on the real date. Today
is Wednesday, November 18, 2020, the same as availability_grid.feature.
"""
# Test names say what each test checks, so they carry no docstrings.
# pylint: disable=missing-function-docstring

from datetime import date, time

import pytest
from django.contrib.auth import get_user_model
from django.test import TestCase

from .models import Availability
from .week_grid import GRID_HOURS, parse_block, save_week, week_grid

pytestmark = pytest.mark.unit

TODAY = date(2020, 11, 18)  # Wednesday
MONDAY = date(2020, 11, 16)
THURSDAY = date(2020, 11, 19)
FRIDAY = date(2020, 11, 20)
SUNDAY = date(2020, 11, 22)
NEXT_MONDAY = date(2020, 11, 23)


def block(day, hour):
    """The grid's value for one block, e.g. "2020-11-19T10"."""
    return f"{day:%Y-%m-%d}T{hour:02d}"


def at(clock):
    """ "9:30" as a time."""
    hour, minute = clock.split(":")
    return time(int(hour), int(minute))


def periods(user, day):
    """Every (start, end) the user has on the day, earliest first."""
    rows = Availability.objects.filter(user=user, date=day).order_by("start_time")
    return list(rows.values_list("start_time", "end_time"))


class GridTestCase(TestCase):
    """A student, another student, and a way to give either of them a period."""

    def setUp(self):
        users = get_user_model().objects
        self.student = users.create_user(username="grid_student", password="pw-123456")
        self.other = users.create_user(username="other_grid_student", password="pw-123456")

    def available(self, day, start, end, user=None):
        Availability.objects.create(
            user=user or self.student, date=day, start_time=at(start), end_time=at(end)
        )

    def assert_periods(self, day, *expected, user=None):
        """The day's periods are exactly these ("10:00", "11:00") pairs, nothing more."""
        wanted = [(at(start), at(end)) for start, end in expected]
        self.assertEqual(periods(user or self.student, day), wanted)


class ParseBlockTests(TestCase):
    """parse_block is where untrusted form values arrive."""

    def test_a_valid_value_is_a_date_and_hour(self):
        self.assertEqual(parse_block("2020-11-19T10"), (THURSDAY, 10))

    def test_a_malformed_value_is_none_and_never_raises(self):
        for value in [
            "",
            "2020-11-19",
            "2020-11-19T",
            "2020-13-01T10",
            "2020-11-19T1a",
            "nonsense",
            "2020-11-19T10T10",
        ]:
            with self.subTest(value=value):
                self.assertIsNone(parse_block(value))


class WeekGridTests(GridTestCase):
    """week_grid is what the page shows."""

    def selected(self, grid):
        """Every selected block in the grid, as (date, hour).

        An empty grid would have nothing selected, so first check there is a week of blocks.
        """
        self.assertEqual([len(day["blocks"]) for day in grid], [12] * 7)
        return [
            (day["date"], b["hour"]) for day in grid for b in day["blocks"] if b["selected"]
        ]

    def test_the_week_is_monday_to_sunday_with_twelve_blocks_a_day(self):
        grid = week_grid(self.student, TODAY)

        self.assertEqual([day["date"] for day in grid], [date(2020, 11, d) for d in range(16, 23)])
        for day in grid:
            with self.subTest(day=day["date"]):
                self.assertEqual([b["hour"] for b in day["blocks"]], list(GRID_HOURS))
                self.assertEqual(len(day["blocks"]), 12)
                self.assertEqual(
                    [b["value"] for b in day["blocks"]],
                    [block(day["date"], hour) for hour in range(8, 20)],
                )
        self.assertEqual(self.selected(grid), [])

    def test_a_block_is_selected_only_when_a_period_covers_the_whole_hour(self):
        self.available(FRIDAY, "14:00", "16:00")

        selected = self.selected(week_grid(self.student, TODAY))

        self.assertEqual(selected, [(FRIDAY, 14), (FRIDAY, 15)])

    def test_a_partly_covered_hour_is_not_selected(self):
        self.available(THURSDAY, "9:30", "10:15")

        self.assertEqual(self.selected(week_grid(self.student, TODAY)), [])

    def test_days_before_today_are_not_editable_and_today_is(self):
        grid = week_grid(self.student, TODAY)

        self.assertEqual(
            [day["editable"] for day in grid], [False, False, True, True, True, True, True]
        )

    def test_another_students_periods_select_nothing(self):
        self.available(THURSDAY, "10:00", "12:00", user=self.other)

        self.assertEqual(self.selected(week_grid(self.student, TODAY)), [])

    def test_the_whole_week_takes_one_query(self):
        self.available(MONDAY, "10:00", "12:00")
        self.available(FRIDAY, "14:00", "16:00")
        self.available(SUNDAY, "8:00", "9:00")

        with self.assertNumQueries(1):
            week_grid(self.student, TODAY)


class SaveWeekTests(GridTestCase):
    """save_week changes data, so each test checks a day's exact periods."""

    def test_touching_blocks_merge_into_one_period(self):
        save_week(self.student, TODAY, [block(THURSDAY, 10), block(THURSDAY, 11)])

        self.assert_periods(THURSDAY, ("10:00", "12:00"))

    def test_separate_blocks_are_separate_periods(self):
        save_week(self.student, TODAY, [block(THURSDAY, 10), block(THURSDAY, 14)])

        self.assert_periods(THURSDAY, ("10:00", "11:00"), ("14:00", "15:00"))

    def test_deselecting_the_end_of_a_period_shortens_it(self):
        self.available(THURSDAY, "10:00", "12:00")

        save_week(self.student, TODAY, [block(THURSDAY, 10)])

        self.assert_periods(THURSDAY, ("10:00", "11:00"))

    def test_deselecting_the_middle_of_a_period_splits_it(self):
        self.available(THURSDAY, "10:00", "13:00")

        save_week(self.student, TODAY, [block(THURSDAY, 10), block(THURSDAY, 12)])

        self.assert_periods(THURSDAY, ("10:00", "11:00"), ("12:00", "13:00"))

    def test_times_the_grid_cannot_show_are_kept(self):
        self.available(THURSDAY, "9:30", "10:15")

        save_week(self.student, TODAY, [block(FRIDAY, 14)])

        self.assert_periods(THURSDAY, ("9:30", "10:15"))
        self.assert_periods(FRIDAY, ("14:00", "15:00"))

    def test_a_block_touching_a_kept_period_merges_with_it(self):
        self.available(THURSDAY, "9:30", "10:15")

        save_week(self.student, TODAY, [block(THURSDAY, 10)])

        self.assert_periods(THURSDAY, ("9:30", "11:00"))

    def test_periods_outside_grid_hours_are_kept(self):
        self.available(THURSDAY, "21:00", "22:00")

        save_week(self.student, TODAY, [block(THURSDAY, 10)])

        self.assert_periods(THURSDAY, ("10:00", "11:00"), ("21:00", "22:00"))

    def test_past_days_keep_their_periods_and_ignore_submitted_blocks(self):
        self.available(MONDAY, "10:00", "12:00")

        save_week(self.student, TODAY, [block(MONDAY, 14), block(THURSDAY, 10)])

        self.assert_periods(MONDAY, ("10:00", "12:00"))
        self.assert_periods(THURSDAY, ("10:00", "11:00"))

    def test_next_week_ignores_submitted_blocks_and_keeps_its_periods(self):
        self.available(NEXT_MONDAY, "10:00", "11:00")

        save_week(self.student, TODAY, [block(NEXT_MONDAY, 14), block(THURSDAY, 10)])

        self.assert_periods(NEXT_MONDAY, ("10:00", "11:00"))
        self.assert_periods(THURSDAY, ("10:00", "11:00"))

    def test_hours_outside_the_grid_are_ignored(self):
        save_week(
            self.student, TODAY, [block(THURSDAY, 3), block(THURSDAY, 20), block(THURSDAY, 10)]
        )

        self.assert_periods(THURSDAY, ("10:00", "11:00"))

    def test_another_students_periods_are_untouched(self):
        self.available(THURSDAY, "10:00", "12:00", user=self.other)

        save_week(self.student, TODAY, [block(THURSDAY, 14)])

        self.assert_periods(THURSDAY, ("10:00", "12:00"), user=self.other)
        self.assert_periods(THURSDAY, ("14:00", "15:00"))

    def test_submitting_nothing_clears_this_weeks_selectable_time(self):
        # A browser sends no "block" key when no box is ticked, so values is empty.
        self.available(MONDAY, "10:00", "12:00")
        self.available(THURSDAY, "10:00", "12:00")
        self.available(SUNDAY, "14:00", "15:00")

        save_week(self.student, TODAY, [])

        self.assert_periods(THURSDAY)
        self.assert_periods(SUNDAY)
        self.assert_periods(MONDAY, ("10:00", "12:00"))
