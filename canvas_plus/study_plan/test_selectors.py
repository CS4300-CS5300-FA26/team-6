"""Tests for reading a student's most recent study plan for display."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

# pylint: disable=import-error
from assignments.models import Assignment
from study_plan.models import StudyPlan, StudySession
from study_plan.selectors import latest_plan_sessions


class LatestPlanSessionsTests(TestCase):
    """Only the signed-in student's newest plan is shown, in order, by local day."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="planner")
        self.other_user = get_user_model().objects.create_user(username="another-planner")
        self.local_timezone = ZoneInfo(settings.TIME_ZONE)
        self.day = date(2026, 11, 5)

    def local_datetime(self, day, at):
        """Create a Denver-local aware datetime."""
        return datetime.combine(day, at).replace(tzinfo=self.local_timezone)

    def make_plan(self, user, created_at=None):
        """Create a plan, optionally backdated past auto_now_add."""
        plan = StudyPlan.objects.create(user=user)
        if created_at is not None:
            StudyPlan.objects.filter(pk=plan.pk).update(created_at=created_at)
        return plan

    def add_session(self, plan, title, start):
        """Add a one-hour session for a new assignment owned by the plan's student."""
        assignment = Assignment.objects.create(
            user=plan.user,
            title=title,
            course="CS4300",
            canvas_course_id=1,
            canvas_assignment_id=Assignment.objects.count() + 1,
        )
        return StudySession.objects.create(
            plan=plan, assignment=assignment, start=start, end=start + timedelta(hours=1)
        )

    @staticmethod
    def titles(sessions):
        """Assignment titles, in the order returned, for readable failures."""
        return [session.assignment.title for session in sessions]

    def test_no_plan_returns_none(self):
        """A student who never generated a plan gets None, not an empty list."""
        self.assertIsNone(latest_plan_sessions(self.user))

    def test_no_plan_with_a_day_returns_none(self):
        """Choosing a day still reports no plan, rather than an empty day."""
        self.assertIsNone(latest_plan_sessions(self.user, day=self.day))

    def test_sessions_come_back_in_start_order(self):
        """Sessions are ordered by start time, not by when they were saved."""
        plan = self.make_plan(self.user)
        self.add_session(plan, "Afternoon", self.local_datetime(self.day, time(15)))
        self.add_session(plan, "Morning", self.local_datetime(self.day, time(9)))
        next_day = self.day + timedelta(days=1)
        self.add_session(plan, "Next Day", self.local_datetime(next_day, time(8)))

        self.assertEqual(
            self.titles(latest_plan_sessions(self.user)),
            ["Morning", "Afternoon", "Next Day"],
        )

    def test_older_plan_sessions_are_excluded(self):
        """Only the most recent plan counts; earlier plans are superseded."""
        older = self.make_plan(self.user, created_at=timezone.now() - timedelta(days=7))
        self.add_session(older, "Old Essay", self.local_datetime(self.day, time(9)))
        latest = self.make_plan(self.user)
        self.add_session(latest, "Lab 4", self.local_datetime(self.day, time(10)))

        self.assertEqual(self.titles(latest_plan_sessions(self.user)), ["Lab 4"])

    def test_another_students_newer_plan_is_not_returned(self):
        """A newer plan belonging to someone else never replaces mine."""
        mine = self.make_plan(self.user)
        self.add_session(mine, "Lab 4", self.local_datetime(self.day, time(10)))
        theirs = self.make_plan(self.other_user, created_at=timezone.now() + timedelta(hours=1))
        self.add_session(theirs, "Their Thesis", self.local_datetime(self.day, time(11)))

        self.assertEqual(self.titles(latest_plan_sessions(self.user)), ["Lab 4"])

    def test_only_another_student_has_a_plan_returns_none(self):
        """Someone else's plan does not count as mine."""
        theirs = self.make_plan(self.other_user)
        self.add_session(theirs, "Their Thesis", self.local_datetime(self.day, time(11)))

        self.assertIsNone(latest_plan_sessions(self.user))

    def test_day_returns_only_that_days_sessions(self):
        """Choosing a day narrows the plan to sessions starting on it."""
        plan = self.make_plan(self.user)
        self.add_session(plan, "HW3", self.local_datetime(self.day, time(14)))
        self.add_session(plan, "Lab 4", self.local_datetime(self.day + timedelta(days=1), time(9)))

        self.assertEqual(self.titles(latest_plan_sessions(self.user, day=self.day)), ["HW3"])

    def test_plan_with_nothing_that_day_returns_empty_not_none(self):
        """A plan with a free day is different from having no plan at all."""
        plan = self.make_plan(self.user)
        self.add_session(plan, "Lab 4", self.local_datetime(self.day + timedelta(days=1), time(9)))

        self.assertEqual(list(latest_plan_sessions(self.user, day=self.day)), [])

    def test_late_evening_session_counts_on_its_local_day(self):
        """11:30 PM Denver on Nov 5 is Nov 6 in UTC, but belongs to Nov 5 for the student."""
        plan = self.make_plan(self.user)
        self.add_session(plan, "Late Night", self.local_datetime(self.day, time(23, 30)))
        self.add_session(
            plan, "Early Morning", self.local_datetime(self.day + timedelta(days=1), time(0, 30))
        )

        self.assertEqual(
            self.titles(latest_plan_sessions(self.user, day=self.day)), ["Late Night"]
        )

    def test_reading_assignment_titles_takes_two_queries(self):
        """One query finds the plan, one loads its sessions with their assignments."""
        plan = self.make_plan(self.user)
        for hour in (9, 10, 11):
            self.add_session(plan, f"Session {hour}", self.local_datetime(self.day, time(hour)))

        with self.assertNumQueries(2):
            self.titles(latest_plan_sessions(self.user))
