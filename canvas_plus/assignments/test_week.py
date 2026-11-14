"""Tests for grouping a student's assignments into this week's days."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase

# pylint: disable=import-error
from assignments.models import Assignment
from assignments.week import this_week

TODAY = date(2020, 11, 12)  # a past Thursday, so code ignoring today can't pass
MONDAY = date(2020, 11, 9)
SUNDAY = date(2020, 11, 15)


class ThisWeekTests(TestCase):
    """The week is Monday through Sunday in local time, holding only this student's work."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="planner")
        self.other_user = get_user_model().objects.create_user(username="another-planner")
        self.local_timezone = ZoneInfo(settings.TIME_ZONE)

    def due(self, day, at=time(17)):
        """A Denver-local deadline on day."""
        return datetime.combine(day, at, tzinfo=self.local_timezone)

    def add(self, title, due, **fields):
        """Save an assignment for this student unless fields name another user."""
        return Assignment.objects.create(
            **{"user": self.user, "sync_state": "synced", **fields},
            title=title,
            course="CS 4300",
            due_date=due,
            canvas_course_id=42,
            canvas_assignment_id=Assignment.objects.count() + 1,
        )

    @staticmethod
    def titles_by_day(week):
        """{date: [titles]} for readable failures."""
        return {day: [assignment.title for assignment in items] for day, items in week}

    def titles_on(self, day, today=TODAY):
        """Titles on one day of the week containing today."""
        return self.titles_by_day(this_week(self.user, today))[day]

    def test_week_is_seven_days_monday_through_sunday_even_when_empty(self):
        """An empty week still has all seven days, in order."""
        week = this_week(self.user, TODAY)

        self.assertEqual(
            [day for day, _ in week], [MONDAY + timedelta(days=n) for n in range(7)]
        )
        self.assertTrue(all(items == [] for _, items in week))

    def test_each_assignment_is_on_its_due_day(self):
        """Assignments land on the day they are due."""
        self.add("HW3", self.due(date(2020, 11, 10)))
        self.add("Lab 4", self.due(date(2020, 11, 13)))

        by_day = self.titles_by_day(this_week(self.user, TODAY))

        self.assertEqual(by_day[date(2020, 11, 10)], ["HW3"])
        self.assertEqual(by_day[date(2020, 11, 13)], ["Lab 4"])
        self.assertEqual(sum(len(titles) for titles in by_day.values()), 2)

    def test_same_day_assignments_come_in_due_time_order(self):
        """Within a day, the earliest deadline comes first, whatever the save order."""
        friday = date(2020, 11, 13)
        self.add("Evening", self.due(friday, time(23, 59)))
        self.add("Morning", self.due(friday, time(9)))
        self.add("Noon", self.due(friday, time(12)))

        self.assertEqual(self.titles_on(friday), ["Morning", "Noon", "Evening"])

    def test_last_sunday_and_next_monday_are_excluded(self):
        """The days just outside the week on either side are not part of it."""
        self.add("Old Lab", self.due(MONDAY - timedelta(days=1)))
        self.add("Next Quiz", self.due(SUNDAY + timedelta(days=1)))

        by_day = self.titles_by_day(this_week(self.user, TODAY))

        self.assertEqual([title for titles in by_day.values() for title in titles], [])

    def test_late_sunday_stays_on_sunday(self):
        """11:30 PM Sunday in Denver is Monday in UTC, but it belongs to Sunday."""
        self.add("Late Essay", self.due(SUNDAY, time(23, 30)))
        self.add("Early Quiz", self.due(SUNDAY + timedelta(days=1), time(0, 30)))

        self.assertEqual(self.titles_on(SUNDAY), ["Late Essay"])

    def test_week_bounds_hold_when_today_is_monday_or_sunday(self):
        """The first and last days of the week both map to that same week."""
        for today in (MONDAY, SUNDAY):
            with self.subTest(today=today):
                days = [day for day, _ in this_week(self.user, today)]
                self.assertEqual((days[0], days[-1]), (MONDAY, SUNDAY))

    def test_another_students_assignment_is_not_included(self):
        """A week holds only the requesting student's assignments."""
        self.add("Their Project", self.due(date(2020, 11, 11)), user=self.other_user)

        self.assertEqual(self.titles_on(date(2020, 11, 11)), [])

    def test_missing_assignments_are_excluded_but_failed_ones_are_kept(self):
        """Removed from Canvas means gone; a failed sync elsewhere does not hide real work."""
        thursday = date(2020, 11, 12)
        self.add("Synced", self.due(thursday, time(9)))
        self.add("Failed", self.due(thursday, time(10)), sync_state="failed")
        self.add("Dropped Lab", self.due(thursday, time(11)), sync_state="missing")

        self.assertEqual(self.titles_on(thursday), ["Synced", "Failed"])

    def test_assignment_without_a_due_date_is_not_included(self):
        """An undated assignment has no day to sit on."""
        self.add("Optional Reading", None)

        by_day = self.titles_by_day(this_week(self.user, TODAY))

        self.assertEqual([title for titles in by_day.values() for title in titles], [])

    def test_whole_week_takes_one_query(self):
        """The week is fetched once and grouped in Python, not queried per day."""
        for offset in range(7):
            self.add(f"Day {offset}", self.due(MONDAY + timedelta(days=offset)))

        with self.assertNumQueries(1):
            self.titles_by_day(this_week(self.user, TODAY))
