"""Tests for generating a study plan from the availability page."""

from datetime import datetime, time, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from assignments.models import Assignment
from availability.models import Availability
from study_plan.models import StudyPlan as PersistedStudyPlan
from study_plan.models import StudySession
from study_plan.schema import StudyPlan as ProposedStudyPlan
from study_plan.exceptions import StudyPlanRetriesExhaustedError
from study_plan.generate import generate_plan


class StudyPlanGenerationViewTests(TestCase):
    """Exercise the page action through the real generation orchestration."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="planner")
        self.client.force_login(self.user)
        self.local_timezone = ZoneInfo(timezone.get_current_timezone_name())
        self.study_day = timezone.localdate() + timedelta(days=1)
        self.start = datetime.combine(self.study_day, time(9)).replace(
            tzinfo=self.local_timezone
        )
        self.assignment = Assignment.objects.create(
            user=self.user,
            title="Essay",
            course="Writing",
            due_date=self.start + timedelta(days=2),
            canvas_course_id=1,
            canvas_assignment_id=1,
        )
        Availability.objects.create(
            user=self.user,
            date=self.study_day,
            start_time=time(9),
            end_time=time(12),
        )
        self.proposal = ProposedStudyPlan(
            sessions=[{
                "assignment_id": self.assignment.pk,
                "start": self.start,
                "end": self.start + timedelta(hours=1),
                "late": False,
            }],
            notices=[],
        )

    def test_study_plan_page_has_generation_form(self):
        response = self.client.get(reverse("availability:list"))

        self.assertContains(response, "Generate plan")
        self.assertContains(response, 'name="assignment_ids"')

    @patch("study_plan.generate.infer")
    def test_button_generates_and_persists_selected_assignment_session(self, infer):
        infer.return_value = self.proposal

        response = self.client.post(
            reverse("availability:list"),
            {"action": "generate_plan", "assignment_ids": [str(self.assignment.pk)]},
        )

        self.assertRedirects(response, reverse("availability:list"))
        plan = PersistedStudyPlan.objects.get(user=self.user)
        session = StudySession.objects.get(plan=plan)
        self.assertEqual(session.assignment, self.assignment)
        self.assertEqual(session.start, self.start)
        self.assertEqual(session.end, self.start + timedelta(hours=1))
        infer.assert_called_once()
        self.assertIs(infer.call_args.args[2], ProposedStudyPlan)

    @patch("study_plan.generate.infer")
    def test_invalid_ai_proposal_is_retried_and_not_persisted(self, infer):
        invalid_proposal = ProposedStudyPlan(
            sessions=[{
                "assignment_id": self.assignment.pk,
                "start": self.start + timedelta(days=4),
                "end": self.start + timedelta(days=5),
                "late": False,
            }],
            notices=[],
        )
        infer.return_value = invalid_proposal

        with self.assertRaises(StudyPlanRetriesExhaustedError):
            generate_plan(self.user, [self.assignment.pk])

        self.assertEqual(infer.call_count, 2)
        self.assertFalse(PersistedStudyPlan.objects.filter(user=self.user).exists())

    @patch("study_plan.generate.infer")
    def test_post_rejects_another_users_assignment(self, infer):
        other_user = get_user_model().objects.create_user(username="other")
        other_assignment = Assignment.objects.create(
            user=other_user,
            title="Private essay",
            course="Writing",
            due_date=self.start + timedelta(days=2),
            canvas_course_id=2,
            canvas_assignment_id=2,
        )

        response = self.client.post(
            reverse("availability:list"),
            {"action": "generate_plan", "assignment_ids": [str(other_assignment.pk)]},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "selected assignments are unavailable")
        infer.assert_not_called()
        self.assertFalse(PersistedStudyPlan.objects.filter(user=self.user).exists())
