"""Integration tests for the current course list page."""
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

# pylint: disable=import-error
from accounts.canvas_client import CanvasAPIError, CanvasAuthenticationError
from accounts.models import CanvasConnection

CURRENT_COURSE = {
    "id": 1,
    "name": "Operating Systems I",
    "term": {"end_at": "2099-01-01T00:00:00Z"},
}
ENDED_COURSE = {
    "id": 2,
    "name": "Programming with UNIX",
    "term": {"end_at": "2000-01-01T00:00:00Z"},
}


@pytest.mark.integration
class CourseListPageTests(TestCase):
    """The Courses page lists the student's current Canvas courses."""

    def setUp(self):
        settings_override = override_settings(
            CANVAS_BASE_URL="https://canvas.example.edu",
            CANVAS_TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode(),
        )
        settings_override.enable()
        self.addCleanup(settings_override.disable)
        self.user = get_user_model().objects.create_user(username="course-student")
        self.connection = CanvasConnection(user=self.user, canvas_url="https://canvas.example.edu")
        self.connection.set_token("fake-canvas-token")
        self.connection.save()
        self.client.force_login(self.user)

    @patch("courses.views.list_courses", return_value=[CURRENT_COURSE, ENDED_COURSE])
    def test_course_list_shows_only_current_courses(self, _list_courses):
        """A course from an ended semester is left out of the list."""
        response = self.client.get(reverse("course_list"))

        self.assertContains(response, "Operating Systems I")
        self.assertNotContains(response, "Programming with UNIX")

    @patch("courses.views.list_courses", return_value=[ENDED_COURSE])
    def test_no_current_courses_shows_message(self, _list_courses):
        """Only ended courses means an empty list with a clear message."""
        response = self.client.get(reverse("course_list"))

        self.assertContains(response, "No current courses found")

    @patch("courses.views.list_courses")
    def test_missing_connection_asks_to_connect(self, list_courses):
        """Without a saved connection, Canvas is never asked."""
        self.connection.delete()

        response = self.client.get(reverse("course_list"))

        self.assertContains(response, "Connect Canvas to see your courses")
        list_courses.assert_not_called()

    @patch("courses.views.list_courses", side_effect=CanvasAuthenticationError("Rejected"))
    def test_expired_connection_asks_to_reconnect(self, _list_courses):
        """A rejected token is saved as expired and the student is told to reconnect."""
        response = self.client.get(reverse("course_list"))

        self.connection.refresh_from_db()
        self.assertFalse(self.connection.is_valid)
        self.assertContains(response, "Your Canvas connection expired. Please reconnect.")

    @patch("courses.views.list_courses", side_effect=CanvasAPIError("Down"))
    def test_canvas_outage_asks_to_try_again(self, _list_courses):
        """A Canvas outage is not shown as an empty course list."""
        response = self.client.get(reverse("course_list"))

        self.assertContains(response, "Unable to load your courses. Please try again.")
        self.assertNotContains(response, "No current courses found")
