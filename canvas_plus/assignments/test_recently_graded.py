"""Tests for the Recently graded section of the assignments page."""

from datetime import timedelta
from unittest.mock import ANY, patch

import pytest
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.canvas_client import CanvasAPIError, CanvasAuthenticationError
from assignments.grades import RECENT_WINDOW
from assignments.test_helpers import configure_canvas_user

COURSES = [{"id": 42, "name": "CS 4300"}]
UPCOMING = [{
    "id": 101,
    "course_id": 42,
    "title": "Canvas Project 1",
    "course_name": "CS 4300",
    "canvas_assignment_id": 101, "canvas_course_id": 42,
    "due_date": timezone.now() + timedelta(days=7),
    "submitted": False,
}]


@pytest.mark.integration
class RecentlyGradedSectionTests(TestCase):
    """The Recently graded section fails on its own, without hiding the rest of the page."""

    def setUp(self):
        self.user, self.connection = configure_canvas_user(self)
        list_all_assignments = patch(
            "assignments.views.list_all_assignments", return_value=[]
        )
        list_all_assignments.start()
        self.addCleanup(list_all_assignments.stop)

    @patch(
        "assignments.views.list_graded_submissions",
        side_effect=CanvasAPIError("Canvas could not load submissions."),
    )
    @patch("assignments.views.list_courses", return_value=COURSES)
    @patch("assignments.views.list_upcoming_assignments", return_value=UPCOMING)
    def test_grades_outage_keeps_upcoming_assignments(
        self,
        _list_upcoming_assignments_mock,
        _list_courses_mock,
        _list_graded_submissions_mock,
    ):
        """A grades outage shows a retry message but still lists upcoming work."""
        response = self.client.get(reverse("assignment_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Canvas Project 1")
        self.assertContains(response, "Unable to load recently graded work right now.")

    @patch(
        "assignments.views.list_graded_submissions",
        side_effect=CanvasAuthenticationError("Canvas rejected the token."),
    )
    @patch("assignments.views.list_courses", return_value=COURSES)
    @patch("assignments.views.list_upcoming_assignments", return_value=UPCOMING)
    def test_rejected_token_while_loading_grades_expires_connection(
        self,
        _list_upcoming_assignments_mock,
        _list_courses_mock,
        _list_graded_submissions_mock,
    ):
        """A 401 from the grades call is an expired token, not a grades outage."""
        response = self.client.get(reverse("assignment_list"))

        self.connection.refresh_from_db()
        self.assertFalse(self.connection.is_valid)
        self.assertContains(response, "Your Canvas connection expired. Please reconnect.")

    @patch("assignments.views.list_graded_submissions", return_value=[])
    @patch("assignments.views.list_courses", return_value=COURSES)
    @patch("assignments.views.list_upcoming_assignments", return_value=[])
    def test_grades_fetched_with_saved_token_and_courses(
        self,
        _list_upcoming_assignments_mock,
        _list_courses_mock,
        list_graded_submissions_mock,
    ):
        """Grades are requested with the decrypted token and the enrolled courses."""
        self.client.get(reverse("assignment_list"))

        list_graded_submissions_mock.assert_called_once_with(
            "fake-canvas-token", COURSES, ANY, session=ANY
        )
        graded_since = list_graded_submissions_mock.call_args.args[2]
        self.assertAlmostEqual(
            graded_since, timezone.now() - RECENT_WINDOW, delta=timedelta(minutes=1)
        )

    @patch("assignments.views.list_graded_submissions", return_value=[])
    @patch("assignments.views.list_courses", return_value=COURSES)
    @patch("assignments.views.list_upcoming_assignments", return_value=[])
    def test_missing_connection_hides_recently_graded(
        self,
        _list_upcoming_assignments_mock,
        _list_courses_mock,
        _list_graded_submissions_mock,
    ):
        """Without a Canvas connection there are no grades to show, so no section."""
        self.connection.delete()

        response = self.client.get(reverse("assignment_list"))

        self.assertNotContains(response, "Recently graded")
