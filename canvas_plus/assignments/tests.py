"""Tests for the Canvas-backed assignments page."""

from datetime import timedelta, timezone as datetime_timezone
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.canvas_client import CanvasAPIError, CanvasAuthenticationError
from accounts.models import CanvasConnection
from assignments.models import Assignment


@pytest.mark.integration
class CanvasAssignmentsPageTests(TestCase):
    """The logged-in assignments page displays current Canvas API results."""

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

    @patch("assignments.views.list_graded_submissions", return_value=[])
    @patch("assignments.views.list_courses", create=True)
    @patch("assignments.views.list_upcoming_assignments", create=True)
    def test_page_renders_assignments_from_canvas(
        self,
        list_upcoming_assignments_mock,
        list_courses_mock,
        _list_graded_submissions_mock,
    ):
        """Canvas assignment title, course name, and due date appear in the page."""
        due_date = timezone.datetime(
            2026, 10, 22, 18, 30, tzinfo=datetime_timezone.utc
        )
        courses = [{"id": 42, "name": "CS 4300"}]
        assignments = [{
            "title": "Canvas Project 1",
            "course_name": "CS 4300",
            "due_date": due_date,
            "submitted": False,
        }]
        list_courses_mock.return_value = courses
        list_upcoming_assignments_mock.return_value = assignments

        response = self.client.get(reverse("assignment_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Canvas Project 1")
        self.assertContains(response, "CS 4300")
        self.assertContains(response, "Oct 22, 2026 12:30 PM")
        self.assertContains(response, 'class="assignment-card"')
        self.assertContains(response, 'class="assignment-status assignment-status--')
        self.assertEqual(response.context["assignments"], assignments)
        list_courses_mock.assert_called_once_with("fake-canvas-token")
        list_upcoming_assignments_mock.assert_called_once_with(
            "fake-canvas-token",
            courses,
        )

    @patch("assignments.views.list_graded_submissions", return_value=[])
    @patch("assignments.views.list_courses", create=True)
    @patch("assignments.views.list_upcoming_assignments", create=True)
    def test_each_card_shows_its_urgency_label(
        self,
        list_upcoming_assignments_mock,
        list_courses_mock,
        _list_graded_submissions_mock,
    ):
        """Each card's badge shows the label recomputed from its due date and submission."""
        now = timezone.now()
        courses = [{"id": 42, "name": "CS 4300"}]
        assignments = [
            {
                "title": "Turned in",
                "course_name": "CS 4300",
                "due_date": now + timedelta(hours=30),
                "submitted": True,
            },
            {
                "title": "Missed",
                "course_name": "CS 4300",
                "due_date": now - timedelta(hours=2),
                "submitted": False,
            },
            {
                "title": "Close",
                "course_name": "CS 4300",
                "due_date": now + timedelta(hours=30),
                "submitted": False,
            },
            {
                "title": "Far",
                "course_name": "CS 4300",
                "due_date": now + timedelta(days=6),
                "submitted": False,
            },
        ]
        list_courses_mock.return_value = courses
        list_upcoming_assignments_mock.return_value = assignments

        response = self.client.get(reverse("assignment_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'assignment-status--submitted">Submitted</span>')
        self.assertContains(response, 'assignment-status--past-due">Past due</span>')
        self.assertContains(response, 'assignment-status--due-soon">Due soon</span>')
        self.assertContains(response, 'assignment-status--upcoming">Upcoming</span>')
        self.assertEqual(
            [assignment["priority"] for assignment in response.context["assignments"]],
            ["Submitted", "Past due", "Due soon", "Upcoming"],
        )

    @patch("assignments.views.list_graded_submissions", return_value=[])
    @patch("assignments.views.list_courses", create=True, return_value=[])
    @patch("assignments.views.list_upcoming_assignments", create=True, return_value=[])
    def test_empty_canvas_result_shows_agreed_empty_message(
        self,
        _list_upcoming_assignments_mock,
        _list_courses_mock,
        _list_graded_submissions_mock,
    ):
        """A successful empty Canvas response uses the agreed empty-state copy."""
        response = self.client.get(reverse("assignment_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No upcoming assignments")

    @patch("assignments.views.list_graded_submissions", return_value=[])
    @patch("assignments.views.list_courses", create=True, return_value=[])
    @patch("assignments.views.list_upcoming_assignments", create=True)
    def test_reload_fetches_current_canvas_assignment_data(
        self,
        list_upcoming_assignments_mock,
        _list_courses_mock,
        _list_graded_submissions_mock,
    ):
        """Two requests render the latest due date returned by Canvas."""
        earlier_due_date = timezone.datetime(
            2026, 10, 22, 18, 30, tzinfo=datetime_timezone.utc
        )
        revised_due_date = timezone.datetime(
            2026, 10, 24, 18, 30, tzinfo=datetime_timezone.utc
        )
        list_upcoming_assignments_mock.side_effect = [
            [{
                "title": "Canvas Project 1",
                "course_name": "CS 4300",
                "due_date": earlier_due_date,
                "submitted": False,
            }],
            [{
                "title": "Canvas Project 1",
                "course_name": "CS 4300",
                "due_date": revised_due_date,
                "submitted": False,
            }],
        ]

        first_response = self.client.get(reverse("assignment_list"))
        second_response = self.client.get(reverse("assignment_list"))

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(first_response.context["assignments"][0]["due_date"], earlier_due_date)
        self.assertEqual(second_response.context["assignments"][0]["due_date"], revised_due_date)
        self.assertEqual(list_upcoming_assignments_mock.call_count, 2)

    @patch("assignments.views.list_courses", create=True, return_value=[])
    @patch(
        "assignments.views.list_upcoming_assignments",
        create=True,
        side_effect=CanvasAPIError("Canvas is temporarily unavailable. Please try again."),
    )
    def test_canvas_api_failure_is_not_rendered_as_empty_assignments(
        self,
        _list_upcoming_assignments_mock,
        _list_courses_mock,
    ):
        """An API failure produces a retry state rather than the empty state."""
        response = self.client.get(reverse("assignment_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Please try again")
        self.assertNotContains(response, "No upcoming assignments")

    @patch("assignments.views.list_courses", create=True)
    @patch("assignments.views.list_upcoming_assignments", create=True)
    def test_rejected_token_persists_expired_state_without_retrying_canvas(
        self,
        list_upcoming_assignments_mock,
        list_courses_mock,
    ):
        """A rejected token invalidates the connection for subsequent requests."""
        list_courses_mock.side_effect = CanvasAuthenticationError("Rejected")

        first_response = self.client.get(reverse("assignment_list"))

        self.connection.refresh_from_db()
        self.assertFalse(self.connection.is_valid)
        self.assertEqual(first_response.status_code, 200)
        self.assertContains(first_response, "Your Canvas connection expired. Please reconnect.")
        self.assertContains(first_response, reverse("connect_canvas"))
        self.assertEqual(
            first_response.content.decode().count("Your Canvas connection expired."),
            1,
        )
        self.assertNotContains(first_response, "Your Canvas connection has expired.")
        self.assertNotContains(first_response, "No upcoming assignments")

        second_response = self.client.get(reverse("assignment_list"))

        self.assertEqual(second_response.status_code, 200)
        self.assertContains(second_response, "Your Canvas connection expired. Please reconnect.")
        self.assertContains(second_response, reverse("connect_canvas"))
        self.assertNotContains(second_response, "No upcoming assignments")
        list_courses_mock.assert_called_once_with("fake-canvas-token")
        list_upcoming_assignments_mock.assert_not_called()

    def test_anonymous_visitor_is_redirected_to_sign_in(self):
        """Only a signed-in student can access the assignments home page."""
        self.client.logout()

        response = self.client.get(reverse("assignment_list"))

        self.assertRedirects(
            response,
            f"{reverse('login')}?next={reverse('assignment_list')}",
        )

    def test_missing_connection_shows_connect_state_not_empty_state(self):
        """A missing connection is distinct from a successful empty result."""
        self.connection.delete()

        response = self.client.get(reverse("assignment_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Connect Canvas to see your upcoming assignments")
        self.assertContains(response, reverse("connect_canvas"))
        self.assertNotContains(response, "No upcoming assignments.")

PAGES_USING_BASE_TEMPLATE = ["/assignments/"]

@pytest.mark.integration
class SharedTemplateTests(TestCase):
    """The shared template is reflected across all pages listed above"""

    def setUp(self):
        self.settings_override = override_settings(
            CANVAS_BASE_URL="https://canvas.example.edu",
            CANVAS_TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode(),
        )
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        user = get_user_model().objects.create_user(username="template-student")
        connection = CanvasConnection(user=user, canvas_url="https://canvas.example.edu")
        connection.set_token("template-canvas-token")
        connection.save()
        self.client.force_login(user)

    @patch("assignments.views.list_graded_submissions", return_value=[])
    @patch("assignments.views.list_courses", return_value=[])
    @patch("assignments.views.list_upcoming_assignments", return_value=[])
    def test_every_page_uses_base_template(self, _assignments_mock, _courses_mock,
                                           _graded_mock):
        """The shared base template is used across all canvas+ pages in a list"""

        for url in PAGES_USING_BASE_TEMPLATE:

            with self.subTest(url=url):
                response = self.client.get(url)

                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, "base.html")

    @patch("assignments.views.list_graded_submissions", return_value=[])
    @patch("assignments.views.list_courses", return_value=[])
    @patch("assignments.views.list_upcoming_assignments", return_value=[])
    def test_every_page_links_assignments(self, _assignments_mock, _courses_mock,
                                          _graded_mock):
        """The assignments list page is displayed on every page through the navigation bar"""
        assignments_url = reverse("assignment_list")

        for url in PAGES_USING_BASE_TEMPLATE:
            with self.subTest(url=url):
                response = self.client.get(url)

                self.assertEqual(response.status_code, 200)
                self.assertContains(
                    response,
                    f'<a href="{assignments_url}">Assignments</a>',
                    html=True,
                )
                