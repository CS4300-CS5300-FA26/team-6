"""Unit tests for grouping Course Hub coursework by local due day."""
from datetime import datetime, timedelta, timezone as dt_timezone

from django.test import SimpleTestCase, override_settings

# pylint: disable=import-error
from courses.upcoming import due_this_week, group_by_day

# Wednesday, November 11, 2026 at 5:00 PM in America/Denver (MST, UTC-7).
NOW = datetime(2026, 11, 12, 0, 0, tzinfo=dt_timezone.utc)


def work(title, due_date):
    """The two assignment fields grouping reads."""
    return {"title": title, "due_date": due_date}


def utc(*args):
    """A UTC datetime, as Canvas due dates arrive normalized."""
    return datetime(*args, tzinfo=dt_timezone.utc)


@override_settings(TIME_ZONE="America/Denver")
class GroupByDayTests(SimpleTestCase):
    """Day headers follow the student's local calendar, not UTC."""

    def test_groups_sorted_work_under_local_day_headers(self):
        """Today gets its own label; later days show the weekday and date."""
        retro = work("Sprint 4 retrospective", utc(2026, 11, 12, 6, 59))  # Wed 11:59 PM
        problems = work("Problem set 7", utc(2026, 11, 12, 16, 0))         # Thu 9:00 AM
        biblio = work("Bibliography draft", utc(2026, 11, 13, 6, 59))       # Thu 11:59 PM
        reading = work("Reading response", utc(2026, 11, 17, 0, 0))         # Mon 5:00 PM

        groups = group_by_day([retro, problems, biblio, reading], NOW)

        self.assertEqual(
            [(group["label"], group["assignments"]) for group in groups],
            [
                ("Today · Wed Nov 11", [retro]),
                ("Thursday · Nov 12", [problems, biblio]),
                ("Monday · Nov 16", [reading]),
            ],
        )

    def test_late_evening_work_stays_on_its_local_day(self):
        """11:59 PM Wednesday in Denver is already Thursday in UTC."""
        groups = group_by_day([work("Late", utc(2026, 11, 12, 6, 59))], NOW)

        self.assertEqual(groups[0]["label"], "Today · Wed Nov 11")

    def test_today_follows_the_local_date_of_now(self):
        """At 11:30 PM local, today is still the local date even though UTC has rolled over."""
        late_night = utc(2026, 11, 12, 6, 30)  # Wed 11:30 PM in Denver

        groups = group_by_day([work("Due Thursday", utc(2026, 11, 12, 18, 0))], late_night)

        self.assertEqual(groups[0]["label"], "Thursday · Nov 12")

    def test_work_without_a_due_date_is_grouped_last(self):
        """Undated work, already sorted last, gets its own header."""
        dated = work("Dated", utc(2026, 11, 13, 0, 0))
        undated = work("Undated", None)

        groups = group_by_day([dated, undated], NOW)

        self.assertEqual([group["label"] for group in groups], ["Thursday · Nov 12", "No due date"])

    def test_no_work_means_no_groups(self):
        """An empty week renders no headers."""
        self.assertEqual(group_by_day([], NOW), [])


class DueThisWeekTests(SimpleTestCase):
    """The hub shows only work due between now and seven days from now."""

    def test_keeps_only_work_due_in_the_next_seven_days(self):
        """Both window edges are inclusive; overdue and undated work drop out."""
        overdue = work("Overdue", NOW - timedelta(minutes=1))
        due_now = work("Due now", NOW)
        last_moment = work("Last moment", NOW + timedelta(days=7))
        next_week = work("Next week", NOW + timedelta(days=7, minutes=1))
        undated = work("Undated", None)

        kept = due_this_week([overdue, due_now, last_moment, next_week, undated], NOW)

        self.assertEqual(kept, [due_now, last_moment])
