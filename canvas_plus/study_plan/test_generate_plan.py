"""Integration tests for generating and persisting study plans."""

from datetime import date, datetime, time, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from assignments.models import Assignment
from availability.models import Availability
from ai_inference.exceptions import AIProviderError
from study_plan.exceptions import (
    EmptyAssignmentSelectionError,
    InaccessibleAssignmentError,
    NoEligibleAssignmentsError,
    NoUsableAvailabilityError,
    StudyPlanRetriesExhaustedError,
)
from study_plan.generate import generate_plan
from study_plan.models import StudyPlan as PersistedStudyPlan
from study_plan.models import StudySession
from study_plan.schema import EffortEstimate
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
            estimated_effort_minutes=30,
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

    def create_long_assignment_case(self):
        """Create a multi-day assignment with two full study windows."""
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
            estimated_effort_minutes=155,
        )
        proposal_sessions = [
            StudySessionProposal(
                assignment_id=assignment.id,
                start=datetime.combine(
                    available_date,
                    window_start,
                    tzinfo=local_timezone,
                ),
                end=datetime.combine(
                    available_date,
                    window_end,
                    tzinfo=local_timezone,
                ),
                late=False,
            )
            for available_date in dates[:2]
        ]
        return user, assignment, local_timezone, window_start, window_end, proposal_sessions

    @patch("study_plan.generate.infer")
    def test_long_assignment_split_into_sessions(self, mock_infer):
        """Effort is split across windows and sub-15-minute remainder is reported."""
        (
            user,
            assignment,
            local_timezone,
            window_start,
            window_end,
            proposal_sessions,
        ) = self.create_long_assignment_case()
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
                local_start = session.start.astimezone(local_timezone)
                local_end = session.end.astimezone(local_timezone)
                duration_minutes = int(
                    (session.end - session.start).total_seconds() // 60
                )
                self.assertGreater(duration_minutes, 0)
                self.assertEqual(duration_minutes % 15, 0)
                self.assertGreaterEqual(local_start.time(), window_start)
                self.assertLessEqual(local_end.time(), window_end)
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
    def test_remaining_effort_reported(self, mock_infer):
        """Unscheduled pre-deadline effort is reported without creating late sessions."""
        user = get_user_model().objects.create_user(username="remaining-effort-student")
        local_timezone = ZoneInfo(settings.TIME_ZONE)
        available_date = date.today() + timedelta(days=1)
        Availability.objects.create(
            user=user,
            date=available_date,
            start_time=time(9),
            end_time=time(12),
        )
        deadline = datetime.combine(
            available_date,
            time(10),
            tzinfo=local_timezone,
        )
        assignment = Assignment.objects.create(
            user=user,
            canvas_course_id=11,
            canvas_assignment_id=105,
            title="Deadline-limited assignment",
            course="Biology",
            due_date=deadline,
            estimated_effort_minutes=120,
        )
        mock_infer.return_value = StudyPlanResponse(
            sessions=[
                StudySessionProposal(
                    assignment_id=assignment.id,
                    start=datetime.combine(
                        available_date,
                        time(9),
                        tzinfo=local_timezone,
                    ),
                    end=deadline,
                    late=False,
                ),
            ],
        )

        plan = generate_plan(user, [assignment.id])

        sessions = list(plan.sessions.filter(assignment=assignment))
        self.assertEqual(len(sessions), 1)
        self.assertLessEqual(sessions[0].end, deadline)
        self.assertFalse(any(session.late for session in sessions))
        self.assertTrue(
            any(
                assignment.title in notice and "60 minutes" in notice
                for notice in plan.notices
            ),
            f"Expected a notice naming {assignment.title!r} with 60 unscheduled minutes; "
            f"got {plan.notices!r}",
        )

    @patch("study_plan.generate.infer")
    def test_late_sessions_flagged(self, mock_infer):
        """An opted-in session after its deadline persists with late=True."""
        user = get_user_model().objects.create_user(username="late-session-student")
        local_timezone = ZoneInfo(settings.TIME_ZONE)
        available_date = date.today() + timedelta(days=1)
        deadline = datetime.combine(
            available_date,
            time(10),
            tzinfo=local_timezone,
        )
        late_end = datetime.combine(
            available_date,
            time(10, 30),
            tzinfo=local_timezone,
        )
        Availability.objects.create(
            user=user,
            date=available_date,
            start_time=time(9),
            end_time=time(10, 30),
        )
        assignment = Assignment.objects.create(
            user=user,
            canvas_course_id=11,
            canvas_assignment_id=106,
            title="Late-eligible assignment",
            course="Biology",
            due_date=deadline,
            estimated_effort_minutes=30,
        )
        mock_infer.return_value = StudyPlanResponse(
            sessions=[
                StudySessionProposal(
                    assignment_id=assignment.id,
                    start=deadline,
                    end=late_end,
                    late=True,
                ),
            ],
        )

        plan = generate_plan(user, [assignment.id], allow_late=True)

        session = plan.sessions.get(assignment=assignment)
        self.assertGreater(session.end, assignment.due_date)
        self.assertTrue(session.late)

    @patch("study_plan.generate.infer")
    def test_invalid_assignments_skipped_with_notice(self, mock_infer):
        """Assignments missing dates or positive effort are skipped with notices."""
        user = get_user_model().objects.create_user(username="eligibility-student")
        local_timezone = ZoneInfo(settings.TIME_ZONE)
        available_date = date.today() + timedelta(days=1)
        Availability.objects.create(
            user=user,
            date=available_date,
            start_time=time(9),
            end_time=time(10),
        )
        due_date = datetime.combine(
            available_date + timedelta(days=1),
            time(17),
            tzinfo=local_timezone,
        )
        assignments = [
            Assignment.objects.create(
                user=user,
                canvas_course_id=11,
                canvas_assignment_id=107,
                title="Missing due date",
                course="Biology",
                due_date=None,
                estimated_effort_minutes=30,
            ),
            Assignment.objects.create(
                user=user,
                canvas_course_id=11,
                canvas_assignment_id=108,
                title="Missing effort estimate",
                course="Biology",
                due_date=due_date,
                estimated_effort_minutes=None,
            ),
            Assignment.objects.create(
                user=user,
                canvas_course_id=11,
                canvas_assignment_id=109,
                title="Zero effort estimate",
                course="Biology",
                due_date=due_date,
                estimated_effort_minutes=0,
            ),
            Assignment.objects.create(
                user=user,
                canvas_course_id=11,
                canvas_assignment_id=110,
                title="Eligible assignment",
                course="Biology",
                due_date=due_date,
                estimated_effort_minutes=30,
            ),
        ]
        eligible_assignment = assignments[-1]
        mock_infer.return_value = StudyPlanResponse(
            sessions=[
                StudySessionProposal(
                    assignment_id=eligible_assignment.id,
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

        plan = generate_plan(user, [assignment.id for assignment in assignments])

        sessions = list(plan.sessions.select_related("assignment"))
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].assignment_id, eligible_assignment.id)
        self.assertTrue(
            any(
                "Missing due date" in notice and "no due date" in notice
                for notice in plan.notices
            )
        )
        for title in ("Missing effort estimate", "Zero effort estimate"):
            with self.subTest(assignment=title):
                self.assertTrue(
                    any(
                        title in notice and "positive effort estimate" in notice
                        for notice in plan.notices
                    )
                )
        inference_input = str(mock_infer.call_args.args[1])
        self.assertIn("Eligible assignment", inference_input)
        for title in ("Missing due date", "Missing effort estimate", "Zero effort estimate"):
            with self.subTest(excluded_assignment=title):
                self.assertNotIn(title, inference_input)

    def test_generates_missing_estimate_and_reuses_saved_estimates(self):
        """Generation estimates missing effort and preserves saved manual and automatic values."""
        user = get_user_model().objects.create_user(username="estimate-during-generation")
        local_timezone = ZoneInfo(settings.TIME_ZONE)
        available_date = date.today() + timedelta(days=1)
        Availability.objects.create(
            user=user,
            date=available_date,
            start_time=time(9),
            end_time=time(11, 15),
        )
        due_date = datetime.combine(
            available_date + timedelta(days=1),
            time(17),
            tzinfo=local_timezone,
        )
        missing_estimate = Assignment.objects.create(
            user=user,
            canvas_course_id=21,
            canvas_assignment_id=201,
            title="New estimate assignment",
            course="Biology",
            due_date=due_date,
            description="Write a short analysis of the assigned reading.",
        )
        manual_estimate = Assignment.objects.create(
            user=user,
            canvas_course_id=21,
            canvas_assignment_id=202,
            title="Manual estimate assignment",
            course="Biology",
            due_date=due_date,
            description="Complete the provided problem set.",
            estimated_effort_minutes=45,
            effort_estimate_source="manual",
        )
        automatic_estimate = Assignment.objects.create(
            user=user,
            canvas_course_id=21,
            canvas_assignment_id=203,
            title="Existing automatic estimate assignment",
            course="Biology",
            due_date=due_date,
            description="Prepare the lab report.",
            estimated_effort_minutes=60,
            effort_estimate_source="automatic",
        )
        proposal = StudyPlanResponse(
            sessions=[
                StudySessionProposal(
                    assignment_id=missing_estimate.id,
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
                StudySessionProposal(
                    assignment_id=manual_estimate.id,
                    start=datetime.combine(
                        available_date,
                        time(9, 30),
                        tzinfo=local_timezone,
                    ),
                    end=datetime.combine(
                        available_date,
                        time(10, 15),
                        tzinfo=local_timezone,
                    ),
                    late=False,
                ),
                StudySessionProposal(
                    assignment_id=automatic_estimate.id,
                    start=datetime.combine(
                        available_date,
                        time(10, 15),
                        tzinfo=local_timezone,
                    ),
                    end=datetime.combine(
                        available_date,
                        time(11, 15),
                        tzinfo=local_timezone,
                    ),
                    late=False,
                ),
            ],
        )

        with (
            patch(
                "study_plan.effort_estimation.infer",
                return_value=EffortEstimate(
                    estimated_minutes=30,
                    reason="A short analysis requires focused reading and writing.",
                ),
            ) as estimate_infer,
            patch("study_plan.generate.infer", return_value=proposal) as plan_infer,
        ):
            plan = generate_plan(
                user,
                [missing_estimate.id, manual_estimate.id, automatic_estimate.id],
            )

        missing_estimate.refresh_from_db()
        manual_estimate.refresh_from_db()
        automatic_estimate.refresh_from_db()
        self.assertEqual(missing_estimate.estimated_effort_minutes, 30)
        self.assertEqual(missing_estimate.effort_estimate_source, "automatic")
        self.assertEqual(manual_estimate.estimated_effort_minutes, 45)
        self.assertEqual(manual_estimate.effort_estimate_source, "manual")
        self.assertEqual(automatic_estimate.estimated_effort_minutes, 60)
        self.assertEqual(automatic_estimate.effort_estimate_source, "automatic")
        self.assertEqual(plan.sessions.count(), 3)
        estimate_infer.assert_called_once()
        plan_infer.assert_called_once()
        planning_input = str(plan_infer.call_args.args[1])
        for expected_minutes in (30, 45, 60):
            self.assertIn(f'"estimated_effort_minutes": {expected_minutes}', planning_input)

    def test_unestimable_assignments_are_skipped_with_notice(self):
        """Assignments without details or with estimation failure do not block planning."""
        user = get_user_model().objects.create_user(username="unestimable-assignments")
        local_timezone = ZoneInfo(settings.TIME_ZONE)
        available_date = date.today() + timedelta(days=1)
        Availability.objects.create(
            user=user,
            date=available_date,
            start_time=time(9),
            end_time=time(10),
        )
        due_date = datetime.combine(
            available_date + timedelta(days=1),
            time(17),
            tzinfo=local_timezone,
        )
        missing_information = Assignment.objects.create(
            user=user,
            canvas_course_id=22,
            canvas_assignment_id=221,
            title="Missing assignment details",
            course="Biology",
            due_date=due_date,
            description="",
        )
        provider_failure = Assignment.objects.create(
            user=user,
            canvas_course_id=22,
            canvas_assignment_id=222,
            title="Estimator unavailable assignment",
            course="Biology",
            due_date=due_date,
            description="Complete a short lab report.",
        )
        eligible_assignment = Assignment.objects.create(
            user=user,
            canvas_course_id=22,
            canvas_assignment_id=223,
            title="Already estimated assignment",
            course="Biology",
            due_date=due_date,
            description="Review the course notes.",
            estimated_effort_minutes=30,
            effort_estimate_source="manual",
        )
        proposal = StudyPlanResponse(
            sessions=[
                StudySessionProposal(
                    assignment_id=eligible_assignment.id,
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

        with (
            patch(
                "study_plan.effort_estimation.infer",
                side_effect=AIProviderError("temporary estimate provider failure"),
            ) as estimate_infer,
            patch("study_plan.generate.infer", return_value=proposal),
        ):
            plan = generate_plan(
                user,
                [
                    missing_information.id,
                    provider_failure.id,
                    eligible_assignment.id,
                ],
            )

        estimate_infer.assert_called_once()
        self.assertEqual(
            list(plan.sessions.values_list("assignment_id", flat=True)),
            [eligible_assignment.id],
        )
        for assignment in (missing_information, provider_failure):
            self.assertTrue(
                any(assignment.title in notice for notice in plan.notices),
                f"Expected a skip notice for {assignment.title!r}; got {plan.notices!r}",
            )

    def test_no_eligible_assignments_after_estimation(self):
        """No plan is persisted when estimation leaves every selection ineligible."""
        user = get_user_model().objects.create_user(username="no-usable-estimate")
        assignment = Assignment.objects.create(
            user=user,
            canvas_course_id=23,
            canvas_assignment_id=231,
            title="Unestimable assignment",
            course="Biology",
            due_date=timezone.now() + timedelta(days=2),
            description="Details are present, but estimation returns no result.",
        )

        with (
            patch(
                "study_plan.effort_estimation.infer",
                return_value=None,
            ) as estimate_infer,
            patch("study_plan.generate.infer") as plan_infer,
        ):
            with self.assertRaises(NoEligibleAssignmentsError):
                generate_plan(user, [assignment.id])

        estimate_infer.assert_called_once()
        plan_infer.assert_not_called()
        self.assertFalse(PersistedStudyPlan.objects.filter(user=user).exists())

    def test_estimate_survives_plan_generation_failure(self):
        """A saved automatic estimate remains when plan inference exhausts its retries."""
        user = get_user_model().objects.create_user(username="estimate-before-plan-failure")
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
            canvas_course_id=24,
            canvas_assignment_id=241,
            title="Estimate survives plan failure",
            course="Biology",
            due_date=datetime.combine(
                available_date + timedelta(days=1),
                time(17),
                tzinfo=local_timezone,
            ),
            description="Write a report based on the provided experiment.",
        )

        with (
            patch(
                "study_plan.effort_estimation.infer",
                return_value=EffortEstimate(
                    estimated_minutes=60,
                    reason="The report requires analysis and writing.",
                ),
            ) as estimate_infer,
            patch(
                "study_plan.generate.infer",
                side_effect=[
                    AIProviderError("temporary planning provider failure"),
                    AIProviderError("planning provider remains unavailable"),
                ],
            ) as plan_infer,
        ):
            with self.assertRaises(StudyPlanRetriesExhaustedError):
                generate_plan(user, [assignment.id])

        assignment.refresh_from_db()
        estimate_infer.assert_called_once()
        self.assertEqual(plan_infer.call_count, 2)
        self.assertEqual(assignment.estimated_effort_minutes, 60)
        self.assertEqual(assignment.effort_estimate_source, "automatic")
        self.assertFalse(PersistedStudyPlan.objects.filter(user=user).exists())

    @patch("study_plan.generate.infer")
    def test_empty_assignment_selection_raises_error(self, mock_infer):
        """An empty selection is rejected without inference or plan creation."""
        empty_user = get_user_model().objects.create_user(username="empty-selection-student")
        with self.assertRaises(EmptyAssignmentSelectionError):
            generate_plan(empty_user, [])
        self.assertFalse(PersistedStudyPlan.objects.filter(user=empty_user).exists())
        mock_infer.assert_not_called()

    @patch("study_plan.generate.infer")
    def test_no_eligible_assignments_raises_error(self, mock_infer):
        """A selection with no eligible assignments is rejected before inference."""
        ineligible_user = get_user_model().objects.create_user(
            username="no-eligible-assignment-student"
        )
        ineligible_assignment = Assignment.objects.create(
            user=ineligible_user,
            canvas_course_id=11,
            canvas_assignment_id=111,
            title="Undated assignment",
            course="Biology",
            due_date=None,
            estimated_effort_minutes=30,
        )
        with self.assertRaises(NoEligibleAssignmentsError):
            generate_plan(ineligible_user, [ineligible_assignment.id])
        self.assertFalse(PersistedStudyPlan.objects.filter(user=ineligible_user).exists())
        mock_infer.assert_not_called()

    @patch("study_plan.generate.infer")
    def test_no_availability_raises_error(self, mock_infer):
        """An eligible assignment without availability is rejected before inference."""
        no_availability_user, no_availability_assignment, _ = self.create_retry_case(
            "no-availability-student"
        )
        Availability.objects.filter(user=no_availability_user).delete()
        with self.assertRaises(NoUsableAvailabilityError):
            generate_plan(no_availability_user, [no_availability_assignment.id])
        self.assertFalse(
            PersistedStudyPlan.objects.filter(user=no_availability_user).exists()
        )
        mock_infer.assert_not_called()

    @patch("study_plan.generate.infer")
    def test_past_availability_raises_error(self, mock_infer):
        """Availability windows that have ended are rejected before inference."""
        expired_user, expired_assignment, _ = self.create_retry_case("expired-windows-student")
        Availability.objects.filter(user=expired_user).update(
            date=date.today() - timedelta(days=1)
        )
        with self.assertRaises(NoUsableAvailabilityError):
            generate_plan(expired_user, [expired_assignment.id])
        self.assertFalse(PersistedStudyPlan.objects.filter(user=expired_user).exists())
        mock_infer.assert_not_called()

    @patch("study_plan.generate.infer")
    def test_consumed_availability_raises_error(self, mock_infer):
        """A fully occupied availability window creates no additional plan."""
        consumed_user, consumed_assignment, valid_plan = self.create_retry_case(
            "consumed-windows-student"
        )
        existing_plan = PersistedStudyPlan.objects.create(user=consumed_user, notices=[])
        earlier_start = valid_plan.sessions[0].start
        earlier_end = earlier_start + timedelta(hours=1)
        StudySession.objects.create(
            plan=existing_plan,
            assignment=consumed_assignment,
            start=earlier_start,
            end=earlier_end,
        )
        with self.assertRaises(NoUsableAvailabilityError):
            generate_plan(consumed_user, [consumed_assignment.id])
        self.assertEqual(PersistedStudyPlan.objects.filter(user=consumed_user).count(), 1)
        self.assertEqual(existing_plan.sessions.count(), 1)
        mock_infer.assert_not_called()

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
            due_date=datetime.combine(
                available_date,
                time(12),
                tzinfo=local_timezone,
            ),
            estimated_effort_minutes=60,
        )
        second_assignment = Assignment.objects.create(
            user=user,
            canvas_course_id=12,
            canvas_assignment_id=102,
            title="Problem set",
            course="Chemistry",
            due_date=datetime.combine(
                available_date + timedelta(days=1),
                time(12),
                tzinfo=local_timezone,
            ),
            estimated_effort_minutes=60,
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
    def test_sessions_only_in_availability(self, mock_infer):
        """Every persisted session fits within one of the student's windows."""
        user = get_user_model().objects.create_user(username="narrow-window-student")
        local_timezone = ZoneInfo(settings.TIME_ZONE)
        available_date = date.today() + timedelta(days=1)
        windows = [
            (
                datetime.combine(available_date, time(9), tzinfo=local_timezone),
                datetime.combine(available_date, time(9, 30), tzinfo=local_timezone),
            ),
            (
                datetime.combine(available_date, time(11), tzinfo=local_timezone),
                datetime.combine(available_date, time(11, 30), tzinfo=local_timezone),
            ),
        ]
        for start, end in windows:
            Availability.objects.create(
                user=user,
                date=available_date,
                start_time=start.time(),
                end_time=end.time(),
            )

        assignment = Assignment.objects.create(
            user=user,
            canvas_course_id=11,
            canvas_assignment_id=103,
            title="Narrow-window assignment",
            course="Biology",
            due_date=datetime.combine(
                available_date + timedelta(days=1),
                time(17),
                tzinfo=local_timezone,
            ),
            estimated_effort_minutes=60,
        )
        mock_infer.return_value = StudyPlanResponse(
            sessions=[
                StudySessionProposal(
                    assignment_id=assignment.id,
                    start=start,
                    end=end,
                    late=False,
                )
                for start, end in windows
            ],
        )

        plan = generate_plan(user, [assignment.id])

        sessions = list(plan.sessions.filter(assignment=assignment))
        self.assertEqual(len(sessions), len(windows))
        for session in sessions:
            with self.subTest(start=session.start):
                self.assertTrue(
                    any(
                        window_start <= session.start and session.end <= window_end
                        for window_start, window_end in windows
                    ),
                    f"Session {session.start} - {session.end} does not fit an availability window.",
                )

    @patch("study_plan.generate.infer")
    def test_out_of_availability_proposal_rejected(self, mock_infer):
        """Repeated out-of-window proposals exhaust retries without saving a plan."""
        user, assignment, _ = self.create_retry_case("outside-window-student")
        local_timezone = ZoneInfo(settings.TIME_ZONE)
        available_date = date.today() + timedelta(days=1)
        invalid_plan = StudyPlanResponse(
            sessions=[
                StudySessionProposal(
                    assignment_id=assignment.id,
                    start=datetime.combine(
                        available_date,
                        time(10),
                        tzinfo=local_timezone,
                    ),
                    end=datetime.combine(
                        available_date,
                        time(10, 30),
                        tzinfo=local_timezone,
                    ),
                    late=False,
                ),
            ],
        )
        mock_infer.return_value = invalid_plan

        with self.assertRaises(StudyPlanRetriesExhaustedError):
            generate_plan(user, [assignment.id])

        self.assertEqual(mock_infer.call_count, 2)
        self.assertFalse(PersistedStudyPlan.objects.filter(user=user).exists())

    @patch("study_plan.generate.infer")
    def test_new_plan_avoids_earlier_plans(self, mock_infer):
        """New sessions use remaining time and leave the earlier plan unchanged."""
        (
            user,
            assignment,
            earlier_start,
            earlier_end,
            earlier_session,
            proposed_windows,
            expected_free_windows,
        ) = self.create_existing_plan_case()
        mock_infer.return_value = StudyPlanResponse(
            sessions=[
                StudySessionProposal(
                    assignment_id=assignment.id,
                    start=start,
                    end=end,
                    late=False,
                )
                for start, end in proposed_windows
            ],
        )

        new_plan = generate_plan(user, [assignment.id])

        self.assertEqual(PersistedStudyPlan.objects.filter(user=user).count(), 2)
        earlier_session.refresh_from_db()
        self.assertEqual(earlier_session.start, earlier_start)
        self.assertEqual(earlier_session.end, earlier_end)
        new_sessions = list(new_plan.sessions.filter(assignment=assignment))
        self.assertEqual(len(new_sessions), len(proposed_windows))
        for session in new_sessions:
            with self.subTest(start=session.start):
                self.assertFalse(
                    session.start < earlier_session.end
                    and earlier_session.start < session.end
                )

        inference_content = str(mock_infer.call_args.args[1])
        for window_start, window_end in expected_free_windows:
            with self.subTest(window=(window_start, window_end)):
                self.assertIn(f'"start": "{window_start.isoformat()}"', inference_content)
                self.assertIn(
                    f'"end": "{window_end.isoformat()}"',
                    inference_content,
                )

    def create_existing_plan_case(self):
        """Create a plan occupying the middle of one availability window."""
        user = get_user_model().objects.create_user(username="existing-plan-student")
        local_timezone = ZoneInfo(settings.TIME_ZONE)
        available_date = date.today() + timedelta(days=1)
        Availability.objects.create(
            user=user,
            date=available_date,
            start_time=time(9),
            end_time=time(12),
        )
        assignment = Assignment.objects.create(
            user=user,
            canvas_course_id=11,
            canvas_assignment_id=104,
            title="Assignment alongside existing plan",
            course="Biology",
            due_date=datetime.combine(
                available_date + timedelta(days=1),
                time(17),
                tzinfo=local_timezone,
            ),
            estimated_effort_minutes=60,
        )
        earlier_start = datetime.combine(
            available_date,
            time(10),
            tzinfo=local_timezone,
        )
        earlier_end = datetime.combine(
            available_date,
            time(10, 30),
            tzinfo=local_timezone,
        )
        earlier_plan = PersistedStudyPlan.objects.create(user=user, notices=[])
        earlier_session = earlier_plan.sessions.create(
            assignment=assignment,
            start=earlier_start,
            end=earlier_end,
        )
        proposed_windows = [
            (
                datetime.combine(available_date, time(9), tzinfo=local_timezone),
                datetime.combine(available_date, time(9, 30), tzinfo=local_timezone),
            ),
            (
                datetime.combine(available_date, time(10, 30), tzinfo=local_timezone),
                datetime.combine(available_date, time(11), tzinfo=local_timezone),
            ),
        ]
        expected_free_windows = [
            (
                datetime.combine(available_date, time(9), tzinfo=local_timezone),
                earlier_start,
            ),
            (
                earlier_end,
                datetime.combine(available_date, time(12), tzinfo=local_timezone),
            ),
        ]
        return (
            user,
            assignment,
            earlier_start,
            earlier_end,
            earlier_session,
            proposed_windows,
            expected_free_windows,
        )

    @patch("study_plan.generate.infer")
    def test_other_users_data_rejected(self, mock_infer):
        """A foreign assignment is rejected before inference or plan creation."""
        requester = get_user_model().objects.create_user(username="requesting-student")
        owner, foreign_assignment, _ = self.create_retry_case("foreign-assignment-owner")
        Availability.objects.create(
            user=requester,
            date=date.today() + timedelta(days=1),
            start_time=time(9),
            end_time=time(10),
        )

        with self.assertRaises(InaccessibleAssignmentError):
            generate_plan(requester, [foreign_assignment.id])

        mock_infer.assert_not_called()
        self.assertFalse(PersistedStudyPlan.objects.filter(user=requester).exists())
        self.assertFalse(PersistedStudyPlan.objects.filter(user=owner).exists())

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
            estimated_effort_minutes=30,
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
            estimated_effort_minutes=30,
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
