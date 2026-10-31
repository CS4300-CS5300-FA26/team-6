"""Tests for preparing a student's usable availability windows."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase

from availability.models import Availability
from study_plan.availability_windows import prepare_availability_windows


class AvailabilityWindowPreparationTests(TestCase):
    """Availability is normalized into usable, user-scoped intervals."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="planner")
        self.other_user = get_user_model().objects.create_user(username="another-planner")
        self.local_timezone = ZoneInfo(settings.TIME_ZONE)
        self.test_date = date(2026, 2, 1)
        self.now = self.local_datetime(self.test_date, time(8, 0))

    def local_datetime(self, day, at, fold=0):
        """Create a local aware datetime, including an explicit repeated-time fold."""
        return datetime.combine(day, at).replace(
            tzinfo=self.local_timezone,
            fold=fold,
        )

    def add_window(self, user, day, start, end):
        return Availability.objects.create(
            user=user,
            date=day,
            start_time=start,
            end_time=end,
        )

    def prepare(self, occupied_sessions=()):
        return prepare_availability_windows(
            self.user,
            now=self.now,
            occupied_sessions=occupied_sessions,
        )

    def test_overlapping_and_adjacent_windows_are_merged(self):
        """Overlapping and touching windows become one continuous interval."""
        self.add_window(self.user, self.test_date, time(9), time(10))
        self.add_window(self.user, self.test_date, time(9, 30), time(11))
        self.add_window(self.user, self.test_date, time(11), time(12))

        windows = self.prepare()

        self.assertEqual(
            windows,
            [(
                self.local_datetime(self.test_date, time(9)),
                self.local_datetime(self.test_date, time(12)),
            )],
        )

    def test_earlier_plan_sessions_are_subtracted(self):
        """Occupied intervals split free time without consuming adjacent minutes."""
        self.add_window(self.user, self.test_date, time(9), time(12))
        occupied = (
            (
                self.local_datetime(self.test_date, time(10)),
                self.local_datetime(self.test_date, time(10, 30)),
            ),
        )

        windows = self.prepare(occupied_sessions=occupied)

        self.assertEqual(
            windows,
            [
                (
                    self.local_datetime(self.test_date, time(9)),
                    self.local_datetime(self.test_date, time(10)),
                ),
                (
                    self.local_datetime(self.test_date, time(10, 30)),
                    self.local_datetime(self.test_date, time(12)),
                ),
            ],
        )

    def test_past_windows_are_dropped(self):
        """A window that has ended before now is not returned."""
        self.now = self.local_datetime(self.test_date, time(8, 30))
        self.add_window(self.user, self.test_date, time(7), time(8))
        self.add_window(self.user, self.test_date, time(9), time(10))

        windows = self.prepare()

        self.assertEqual(
            windows,
            [(
                self.local_datetime(self.test_date, time(9)),
                self.local_datetime(self.test_date, time(10)),
            )],
        )

    def test_nonexistent_spring_forward_time_shifts_to_next_valid_time(self):
        """A Denver window starting at skipped 2:30 starts at the first valid 3:00."""
        spring_forward_date = date(2026, 3, 8)
        self.test_date = spring_forward_date
        self.now = self.local_datetime(spring_forward_date, time(0))
        self.add_window(self.user, spring_forward_date, time(2, 30), time(4))

        windows = self.prepare()

        self.assertEqual(
            windows,
            [(
                self.local_datetime(spring_forward_date, time(3)),
                self.local_datetime(spring_forward_date, time(4)),
            )],
        )

    def test_repeated_fall_back_time_uses_standard_time(self):
        """A repeated Denver local time resolves to its standard-time occurrence."""
        fall_back_date = date(2026, 11, 1)
        self.test_date = fall_back_date
        self.now = self.local_datetime(fall_back_date, time(0))
        self.add_window(self.user, fall_back_date, time(1, 30), time(2, 30))

        windows = self.prepare()

        expected_start = self.local_datetime(fall_back_date, time(1, 30), fold=1)
        expected_end = self.local_datetime(fall_back_date, time(2, 30))
        self.assertEqual(windows, [(expected_start, expected_end)])
        self.assertEqual(expected_start.utcoffset(), -timedelta(hours=7))

    def test_another_users_availability_is_ignored(self):
        """Only availability owned by the requested student is returned."""
        self.add_window(self.user, self.test_date, time(9), time(10))
        self.add_window(self.other_user, self.test_date, time(11), time(12))

        windows = self.prepare()

        self.assertEqual(
            windows,
            [(
                self.local_datetime(self.test_date, time(9)),
                self.local_datetime(self.test_date, time(10)),
            )],
        )