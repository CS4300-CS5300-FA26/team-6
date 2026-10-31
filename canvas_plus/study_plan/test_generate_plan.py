"""Integration tests for generating and persisting study plans."""

from datetime import date, datetime, time
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase

from assignments.models import Assignment
from availability.models import Availability
from study_plan.generate import generate_plan
from study_plan.models import StudyPlan as PersistedStudyPlan
from study_plan.schema import StudyPlan as StudyPlanResponse
from study_plan.schema import StudySessionProposal


class GeneratePlanTests(TestCase):
    """Generated sessions are validated and saved for the selected assignments."""

    @patch("study_plan.generate.infer")
    def test_generates_plan_for_multiple_assignments(self, mock_infer):
        """One generation request persists on-time sessions for each assignment."""
        user = get_user_model().objects.create_user(username="plan-student")
        local_timezone = ZoneInfo(settings.TIME_ZONE)
        available_date = date(2026, 11, 2)
        availability_start = datetime.combine(
            available_date,
            time(9),
            tzinfo=local_timezone,
        )
        availability_end = datetime.combine(
            available_date,
            time(12),
            tzinfo=local_timezone,
        )
        Availability.objects.create(
            user=user,
            date=available_date,
            start_time=time(9),
            end_time=time(12),
        )

        first_assignment = Assignment.objects.create(
            user=user,
            canvas_course_id=11,
            canvas_assignment_id=101,
            title="Research outline",
            course="Biology",
            due_date=datetime(2026, 11, 3, 12, tzinfo=local_timezone),
            estimated_minutes=60,
        )
        second_assignment = Assignment.objects.create(
            user=user,
            canvas_course_id=12,
            canvas_assignment_id=102,
            title="Problem set",
            course="Chemistry",
            due_date=datetime(2026, 11, 4, 12, tzinfo=local_timezone),
            estimated_minutes=60,
        )
        mock_infer.return_value = StudyPlanResponse(
            sessions=[
                StudySessionProposal(
                    assignment_id=first_assignment.id,
                    start=availability_start,
                    end=datetime.combine(
                        available_date,
                        time(10),
                        tzinfo=local_timezone,
                    ),
                    late=False,
                ),
                StudySessionProposal(
                    assignment_id=second_assignment.id,
                    start=datetime.combine(
                        available_date,
                        time(10),
                        tzinfo=local_timezone,
                    ),
                    end=datetime.combine(
                        available_date,
                        time(11),
                        tzinfo=local_timezone,
                    ),
                    late=False,
                ),
            ],
        )

        plan = generate_plan(
            user,
            [first_assignment.id, second_assignment.id],
        )

        self.assertEqual(PersistedStudyPlan.objects.count(), 1)
        self.assertEqual(plan.pk, PersistedStudyPlan.objects.get().pk)
        sessions = list(plan.sessions.select_related("assignment").order_by("start"))
        self.assertEqual(len(sessions), 2)
        self.assertEqual(
            {session.assignment_id for session in sessions},
            {first_assignment.id, second_assignment.id},
        )
        deadlines = {
            first_assignment.id: first_assignment.due_date,
            second_assignment.id: second_assignment.due_date,
        }
        for session in sessions:
            with self.subTest(assignment=session.assignment_id):
                self.assertGreater(session.end, session.start)
                self.assertGreaterEqual(session.start, availability_start)
                self.assertLessEqual(session.end, availability_end)
                self.assertLessEqual(session.end, deadlines[session.assignment_id])
                self.assertFalse(session.late)