"""Integration tests for generating and persisting study plans."""

from datetime import date, datetime, time, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase

from assignments.models import Assignment
from availability.models import Availability
from ai_inference.exceptions import AIProviderError
from study_plan.exceptions import StudyPlanRetriesExhaustedError
from study_plan.generate import generate_plan
from study_plan.models import StudyPlan as PersistedStudyPlan
from study_plan.schema import StudyPlan as StudyPlanResponse
from study_plan.schema import StudySessionProposal


class GeneratePlanTests(TestCase):
    """Generated sessions are validated and saved for the selected assignments."""

    def create_retry_case(self, username):
        """Create one eligible assignment and a future availability window."""
        user = get_user_model().objects.create_user(username=username)
        local_timezone = ZoneInfo(settings.TIME_ZONE)
        available_date = date.today() + timedelta(days=1)
        Availability.objects.create(
            user=user,
            date=available_date,
            start_time=time(9),
            end_time=time(10),
        )
        assignment = Assignment.objects.create(
            user=user,
            canvas_course_id=11,
            canvas_assignment_id=401,
            title="Retry test assignment",
            course="Biology",
            due_date=datetime.combine(
                available_date + timedelta(days=1),
                time(17),
                tzinfo=local_timezone,
            ),
            estimated_minutes=30,
        )
        valid_plan = StudyPlanResponse(
            sessions=[
                StudySessionProposal(
                    assignment_id=assignment.id,
                    start=datetime.combine(
                        available_date,
                        time(9),
                        tzinfo=local_timezone,
                    ),
                    end=datetime.combine(
                        available_date,
                        time(9, 30),
                        tzinfo=local_timezone,
                    ),
                    late=False,
                ),
            ],
        )
        return user, assignment, valid_plan

    @patch("study_plan.generate.infer")
    def test_long_assignment_split_into_sessions(self, mock_infer):
        """Effort is split across windows and sub-15-minute remainder is reported."""
        user = get_user_model().objects.create_user(username="long-plan-student")
        local_timezone = ZoneInfo(settings.TIME_ZONE)
        first_date = date.today() + timedelta(days=1)
        dates = [first_date + timedelta(days=offset) for offset in range(3)]
        window_start = time(9)
        window_end = time(10, 15)
        for available_date in dates:
            Availability.objects.create(
                user=user,
                date=available_date,
                start_time=window_start,
                end_time=window_end,
            )

        assignment = Assignment.objects.create(
            user=user,
            canvas_course_id=11,
            canvas_assignment_id=201,
            title="Extended research paper",
            course="Biology",
            due_date=datetime.combine(
                dates[-1],
                time(10),
                tzinfo=local_timezone,
            ),
            estimated_minutes=155,
        )
        proposal_sessions = [
            StudySessionProposal(
                assignment_id=assignment.id,
                start=datetime.combine(available_date, window_start, tzinfo=local_timezone),
                end=datetime.combine(available_date, proposed_end, tzinfo=local_timezone),
                late=False,
            )
            for available_date, proposed_end in zip(
                dates[:2],
                (window_end, window_end),
            )
        ]
        mock_infer.return_value = StudyPlanResponse(sessions=proposal_sessions)

        plan = generate_plan(user, [assignment.id])

        sessions = list(plan.sessions.filter(assignment=assignment).order_by("start"))
        self.assertEqual(len(sessions), 2)
        self.assertEqual(
            sum(int((session.end - session.start).total_seconds() // 60) for session in sessions),
            150,
        )
        self.assertTrue(
            any(session.end - session.start > timedelta(minutes=60) for session in sessions)
        )
        for session in sessions:
            with self.subTest(start=session.start):
                duration_minutes = int(
                    (session.end - session.start).total_seconds() // 60
                )
                self.assertGreater(duration_minutes, 0)
                self.assertEqual(duration_minutes % 15, 0)
                self.assertGreaterEqual(session.start.time(), window_start)
                self.assertLessEqual(session.end.time(), window_end)
                self.assertLessEqual(session.end, assignment.due_date)

        self.assertTrue(
            any(
                assignment.title in notice and "5" in notice
                for notice in plan.notices
            ),
            f"Expected a notice naming {assignment.title!r} and its 5-minute remainder; "
            f"got {plan.notices!r}",
        )

    @patch("study_plan.generate.infer")
    def test_generates_plan_for_multiple_assignments(self, mock_infer):
        """One generation request persists on-time sessions for each assignment."""
        user = get_user_model().objects.create_user(username="plan-student")
        local_timezone = ZoneInfo(settings.TIME_ZONE)
        available_date = date.today() + timedelta(days=1)
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

    @patch("study_plan.generate.infer")
    def test_inference_input_is_deadline_ordered(self, mock_infer):
        """Inference receives deadline-ordered assignments and merged free time."""
        user = get_user_model().objects.create_user(username="ordered-plan-student")
        local_timezone = ZoneInfo(settings.TIME_ZONE)
        available_date = date.today() + timedelta(days=1)
        availability_start = datetime.combine(
            available_date,
            time(9),
            tzinfo=local_timezone,
        )
        Availability.objects.create(
            user=user,
            date=available_date,
            start_time=time(9),
            end_time=time(10),
        )
        Availability.objects.create(
            user=user,
            date=available_date,
            start_time=time(9, 30),
            end_time=time(11),
        )

        later_assignment = Assignment.objects.create(
            user=user,
            canvas_course_id=11,
            canvas_assignment_id=301,
            title="Later deadline report",
            course="Biology",
            due_date=datetime.combine(
                available_date + timedelta(days=3),
                time(17),
                tzinfo=local_timezone,
            ),
            estimated_minutes=30,
        )
        earlier_assignment = Assignment.objects.create(
            user=user,
            canvas_course_id=12,
            canvas_assignment_id=302,
            title="Earlier deadline review",
            course="Chemistry",
            due_date=datetime.combine(
                available_date + timedelta(days=2),
                time(17),
                tzinfo=local_timezone,
            ),
            estimated_minutes=30,
        )
        mock_infer.return_value = StudyPlanResponse(
            sessions=[
                StudySessionProposal(
                    assignment_id=earlier_assignment.id,
                    start=availability_start,
                    end=datetime.combine(
                        available_date,
                        time(9, 30),
                        tzinfo=local_timezone,
                    ),
                    late=False,
                ),
                StudySessionProposal(
                    assignment_id=later_assignment.id,
                    start=datetime.combine(
                        available_date,
                        time(9, 30),
                        tzinfo=local_timezone,
                    ),
                    end=datetime.combine(
                        available_date,
                        time(10),
                        tzinfo=local_timezone,
                    ),
                    late=False,
                ),
            ],
        )

        generate_plan(user, [later_assignment.id, earlier_assignment.id])

        inference_call = mock_infer.call_args
        self.assertIs(inference_call.args[2], StudyPlanResponse)
        inference_text = f"{inference_call.args[0]}\n{inference_call.args[1]}"
        self.assertLess(
            inference_text.index(earlier_assignment.title),
            inference_text.index(later_assignment.title),
        )
        self.assertIn(f"{available_date.isoformat()}T09:00", inference_text)
        self.assertIn(f"{available_date.isoformat()}T11:00", inference_text)
        self.assertNotIn(f"{available_date.isoformat()}T09:30", inference_text)

    @patch("study_plan.generate.infer")
    def test_retries_once_then_fails(self, mock_infer):
        """Provider errors and invalid proposals are retried before success."""
        user, assignment, valid_plan = self.create_retry_case("provider-retry-student")
        mock_infer.side_effect = [AIProviderError("temporary provider failure"), valid_plan]

        plan = generate_plan(user, [assignment.id])

        self.assertEqual(mock_infer.call_count, 2)
        self.assertEqual(plan.sessions.count(), 1)
        self.assertEqual(PersistedStudyPlan.objects.filter(user=user).count(), 1)

        mock_infer.reset_mock()
        user, assignment, valid_plan = self.create_retry_case("empty-retry-student")
        invalid_plan = StudyPlanResponse(
            sessions=[
                StudySessionProposal(
                    assignment_id=assignment.id,
                    start=valid_plan.sessions[0].end + timedelta(minutes=30),
                    end=valid_plan.sessions[0].end + timedelta(minutes=60),
                    late=False,
                ),
            ],
        )
        mock_infer.side_effect = [invalid_plan, valid_plan]

        plan = generate_plan(user, [assignment.id])

        self.assertEqual(mock_infer.call_count, 2)
        self.assertEqual(plan.sessions.count(), 1)
        self.assertEqual(PersistedStudyPlan.objects.filter(user=user).count(), 1)

    @patch("study_plan.generate.infer")
    def test_retry_exhaustion_does_not_persist_plan(self, mock_infer):
        """Two failed inference attempts raise a domain error without persistence."""
        user, assignment, _ = self.create_retry_case("retry-exhausted-student")
        mock_infer.side_effect = [
            AIProviderError("first provider failure"),
            AIProviderError("second provider failure"),
        ]

        with self.assertRaises(StudyPlanRetriesExhaustedError):
            generate_plan(user, [assignment.id])

        self.assertEqual(mock_infer.call_count, 2)
        self.assertFalse(PersistedStudyPlan.objects.filter(user=user).exists())