"""Tests for the Recently graded section of the assignments page."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.canvas_client import CanvasAPIError, CanvasAuthenticationError
from accounts.models import CanvasConnection

COURSES = [{"id": 42, "name": "CS 4300"}]
UPCOMING = [{
    "title": "Canvas Project 1",
    "course_name": "CS 4300",
    "due_date": timezone.now() + timedelta(days=7),
    "submitted": False,
}]


@pytest.mark.integration
class RecentlyGradedSectionTests(TestCase):
    """The Recently graded section fails on its own, without hiding the rest of the page."""

    def setUp(self):
        self.settings_override = override_settings(
            CANVAS_BASE_URL="https://canvas.example.edu",
            CANVAS_TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode(),
        )
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.user = get_user_model().objects.create_user(
            username="canvas-student",
            password="test-password-123",
        )
        self.connection = CanvasConnection(user=self.user, canvas_url="https://canvas.example.edu")
        self.connection.set_token("fake-canvas-token")
        self.connection.save()
        self.client.force_login(self.user)

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

        list_graded_submissions_mock.assert_called_once_with("fake-canvas-token", COURSES)

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
