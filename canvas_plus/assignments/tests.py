"""Tests for the assignments list page (URL -> view -> model -> template)."""

from datetime import timedelta, timezone as datetime_timezone
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone
from django.urls import reverse

from accounts.canvas_client import CanvasAPIError
from accounts.models import CanvasConnection
from .models import Assignment


@pytest.mark.integration
class AssignmentsPageTests(TestCase):
    """The assignments page shows assignments stored in the database."""

    def test_assignments_page_shows_saved_assignment(self):
        """An assignment saved in the database appears on the page."""
        Assignment(
            title="Test Assignment 123",
            course="CS 4300",
            due_date=timezone.now() + timedelta(days=7),
        ).save()

        response = self.client.get("/assignments/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Test Assignment 123")

    def test_assignments_page_loads_with_no_assignments(self):
        """With an empty database, the page loads and says there are no assignments."""
        response = self.client.get("/assignments/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "You have no assignments.")


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

    @patch("assignments.views.connection_status", return_value={})
    @patch("assignments.views.list_courses", create=True)
    @patch("assignments.views.list_upcoming_assignments", create=True)
    def test_page_renders_assignments_from_canvas(
        self,
        list_upcoming_assignments_mock,
        list_courses_mock,
        _connection_status_mock,
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
        }]
        list_courses_mock.return_value = courses
        list_upcoming_assignments_mock.return_value = assignments

        response = self.client.get(reverse("assignment_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Canvas Project 1")
        self.assertContains(response, "CS 4300")
        self.assertContains(response, "Oct 22, 2026 12:30 PM")
        self.assertEqual(response.context["assignments"], assignments)
        list_courses_mock.assert_called_once_with("fake-canvas-token")
        list_upcoming_assignments_mock.assert_called_once_with(
            "fake-canvas-token",
            courses,
        )

    @patch("assignments.views.connection_status", return_value={})
    @patch("assignments.views.list_courses", create=True, return_value=[])
    @patch("assignments.views.list_upcoming_assignments", create=True, return_value=[])
    def test_empty_canvas_result_shows_agreed_empty_message(
        self,
        _list_upcoming_assignments_mock,
        _list_courses_mock,
        _connection_status_mock,
    ):
        """A successful empty Canvas response uses the agreed empty-state copy."""
        response = self.client.get(reverse("assignment_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No upcoming assignments")

    @patch("assignments.views.connection_status", return_value={})
    @patch("assignments.views.list_courses", create=True, return_value=[])
    @patch("assignments.views.list_upcoming_assignments", create=True)
    def test_reload_fetches_current_canvas_assignment_data(
        self,
        list_upcoming_assignments_mock,
        _list_courses_mock,
        _connection_status_mock,
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
            }],
            [{
                "title": "Canvas Project 1",
                "course_name": "CS 4300",
                "due_date": revised_due_date,
            }],
        ]

        first_response = self.client.get(reverse("assignment_list"))
        second_response = self.client.get(reverse("assignment_list"))

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(first_response.context["assignments"][0]["due_date"], earlier_due_date)
        self.assertEqual(second_response.context["assignments"][0]["due_date"], revised_due_date)
        self.assertEqual(list_upcoming_assignments_mock.call_count, 2)

    @patch("assignments.views.connection_status", return_value={})
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
        _connection_status_mock,
    ):
        """An API failure produces a retry state rather than the empty state."""
        response = self.client.get(reverse("assignment_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Please try again")
        self.assertNotContains(response, "You have no assignments.")

    def test_anonymous_visitor_is_redirected_to_sign_in(self):
        """Only a signed-in student can access the assignments home page."""
        self.client.logout()

        response = self.client.get(reverse("assignment_list"))

        self.assertRedirects(
            response,
            f"{reverse('login')}?next={reverse('assignment_list')}",
        )

PAGES_USING_BASE_TEMPLATE = ["/assignments/"]

@pytest.mark.integration
class SharedTemplateTests(TestCase):
    """The shared template is reflected across all pages listed above"""

    def test_every_page_uses_base_template(self):
        """The shared base template is used across all canvas+ pages in a list"""

        for url in PAGES_USING_BASE_TEMPLATE:

            with self.subTest(url=url):
                response = self.client.get(url)

                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, "base.html")

    def test_every_page_links_assignments(self):
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
