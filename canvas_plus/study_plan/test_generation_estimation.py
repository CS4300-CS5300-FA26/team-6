"""Tests for on-demand estimates during study-plan generation."""

from datetime import date, datetime, time, timedelta, timezone as datetime_timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from ai_inference.exceptions import AIProviderError
from accounts.models import CanvasConnection
from assignments.models import Assignment
from availability.models import Availability
from study_plan.generate import generate_plan
from study_plan.models import StudyPlan
from study_plan.schema import StudyPlan as StudyPlanResponse
from study_plan.schema import StudySessionProposal


class GenerationEstimationTests(TestCase):
    """Missing effort estimates are acquired only for selected plan assignments."""

    def create_user_and_window(self, username):
        """Create a student and one future hour of availability."""
        user = get_user_model().objects.create_user(username=username)
        local_timezone = ZoneInfo(settings.TIME_ZONE)
        available_date = date.today() + timedelta(days=1)
        Availability.objects.create(
            user=user,
            date=available_date,
            start_time=time(9),
            end_time=time(10),
        )
        return user, local_timezone, available_date

    def proposal_for(self, assignment, day, local_timezone):
        """Build a valid 30-minute proposal inside the test availability window."""
        return StudyPlanResponse(
            sessions=[
                StudySessionProposal(
                    assignment_id=assignment.id,
                    start=datetime.combine(day, time(9), tzinfo=local_timezone),
                    end=datetime.combine(day, time(9, 30), tzinfo=local_timezone),
                    late=False,
                ),
            ],
        )

    @patch("study_plan.generate.estimate_and_save_assignment_effort")
    @patch("study_plan.generate.infer")
    def test_missing_effort_is_estimated_and_saved_during_generation(
        self,
        mock_infer,
        estimate_assignment_mock,
    ):
        """A selected assignment without an estimate is estimated before planning."""
        user, local_timezone, available_date = self.create_user_and_window(
            "estimate-on-plan-student"
        )
        assignment = Assignment.objects.create(
            user=user,
            canvas_course_id=11,
            canvas_assignment_id=112,
            title="Needs an estimate",
            course="Biology",
            due_date=datetime.combine(
                available_date + timedelta(days=1),
                time(17),
                tzinfo=local_timezone,
            ),
            description="Write a short report.",
        )

        def save_estimate(selected, information):
            self.assertEqual(information, "Write a short report.")
            selected.estimated_effort_minutes = 30
            selected.effort_estimate_source = "automatic"
            selected.save(
                update_fields=["estimated_effort_minutes", "effort_estimate_source"]
            )

        estimate_assignment_mock.side_effect = save_estimate
        mock_infer.return_value = self.proposal_for(
            assignment,
            available_date,
            local_timezone,
        )

        plan = generate_plan(user, [assignment.id])

        assignment.refresh_from_db()
        self.assertEqual(assignment.estimated_effort_minutes, 30)
        self.assertEqual(assignment.effort_estimate_source, "automatic")
        estimate_assignment_mock.assert_called_once_with(assignment, "Write a short report.")
        self.assertEqual(plan.sessions.count(), 1)

    @patch("study_plan.generate.estimate_and_save_assignment_effort")
    @patch("study_plan.generate.infer")
    def test_estimation_failure_skips_assignment_but_plans_other_assignments(
        self,
        mock_infer,
        estimate_assignment_mock,
    ):
        """A failed estimate is noted without blocking other eligible assignments."""
        user, local_timezone, available_date = self.create_user_and_window(
            "estimate-failure-student"
        )
        deadline = datetime.combine(
            available_date + timedelta(days=1),
            time(17),
            tzinfo=local_timezone,
        )
        missing_estimate = Assignment.objects.create(
            user=user,
            canvas_course_id=11,
            canvas_assignment_id=113,
            title="Estimate unavailable",
            course="Biology",
            due_date=deadline,
            description="Assignment details",
        )
        eligible = Assignment.objects.create(
            user=user,
            canvas_course_id=11,
            canvas_assignment_id=114,
            title="Already estimated",
            course="Biology",
            due_date=deadline,
            estimated_effort_minutes=30,
        )
        estimate_assignment_mock.side_effect = AIProviderError("provider unavailable")
        mock_infer.return_value = self.proposal_for(eligible, available_date, local_timezone)

        plan = generate_plan(user, [missing_estimate.id, eligible.id])

        self.assertEqual(
            list(plan.sessions.values_list("assignment_id", flat=True)),
            [eligible.id],
        )
        self.assertTrue(
            any(
                "Estimate unavailable" in notice and "could not be generated" in notice
                for notice in plan.notices
            )
        )
        estimate_assignment_mock.assert_called_once()
        self.assertNotIn("Estimate unavailable", str(mock_infer.call_args.args[1]))
        self.assertEqual(StudyPlan.objects.filter(user=user).count(), 1)

    @override_settings(
        CANVAS_BASE_URL="https://canvas.example.edu",
        CANVAS_TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode(),
    )
    @patch("assignments.canvas_sync.list_courses", return_value=[{"id": 42, "name": "CS 4300"}])
    @patch("assignments.canvas_sync.list_upcoming_assignments")
    @patch("study_plan.generate.infer")
    def test_generation_refreshes_selected_canvas_data_before_inference(
        self,
        mock_infer,
        list_assignments,
        _list_courses,
    ):
        """Plan input and persisted rows use fresh Canvas fields, preserving estimates."""
        user, local_timezone, available_date = self.create_user_and_window(
            "refresh-before-plan-student"
        )
        connection = CanvasConnection(
            user=user,
            canvas_url="https://canvas.example.edu",
        )
        connection.set_token("canvas-test-token")
        connection.save()
        old_due_date = datetime.combine(
            available_date + timedelta(days=1),
            time(17),
            tzinfo=local_timezone,
        )
        new_due_date = datetime.combine(
            available_date + timedelta(days=2),
            time(17),
            tzinfo=local_timezone,
        )
        assignment = Assignment.objects.create(
            user=user,
            canvas_course_id=42,
            canvas_assignment_id=115,
            title="Old Canvas title",
            course="Old course",
            due_date=old_due_date,
            description="Old description",
            estimated_effort_minutes=30,
            effort_estimate_source="manual",
        )
        list_assignments.return_value = [
            {
                "canvas_assignment_id": 115,
                "canvas_course_id": 42,
                "title": "Fresh Canvas title",
                "course_name": "CS 4300",
                "due_date": new_due_date,
                "description": "Fresh assignment description",
            },
        ]
        mock_infer.return_value = self.proposal_for(
            assignment,
            available_date,
            local_timezone,
        )

        plan = generate_plan(user, [assignment.id])

        assignment.refresh_from_db()
        self.assertEqual(assignment.title, "Fresh Canvas title")
        self.assertEqual(assignment.course, "CS 4300")
        self.assertEqual(assignment.due_date, new_due_date)
        self.assertEqual(assignment.description, "Fresh assignment description")
        self.assertEqual(assignment.estimated_effort_minutes, 30)
        self.assertEqual(assignment.effort_estimate_source, "manual")
        self.assertIn("Fresh Canvas title", str(mock_infer.call_args.args[1]))
        expected_due_date = new_due_date.astimezone(datetime_timezone.utc).isoformat()
        self.assertIn(expected_due_date, str(mock_infer.call_args.args[1]))
        self.assertEqual(plan.sessions.count(), 1)
