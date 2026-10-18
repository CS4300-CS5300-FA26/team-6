"""Tests for the landing page at / (card #82)."""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from assignments.models import Assignment  # pylint: disable=import-error

# Where logged-in users start. Update this when the dashboard replaces it.
LOGGED_IN_HOME = reverse("assignment_list")
LOGIN_ERROR = "Please enter a correct username and password"


@pytest.mark.integration
class LandingPageTests(TestCase):
    """The landing page welcomes logged-out visitors and hands logins to the login page."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="student", password="Correct-Pass-123"
        )

    def test_logged_out_visitor_sees_landing_page(self):
        """Scenario 1: name, login form, register link, and no course data."""
        Assignment(
            title="Private Homework",
            course="CS 4300",
            due_date=timezone.now() + timedelta(days=7),
        ).save()

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Canvas+")
        self.assertContains(response, f'action="{reverse("login")}"')
        self.assertContains(response, 'name="username"')
        self.assertContains(response, 'name="password"')
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertContains(response, f'href="{reverse("register")}"')
        self.assertNotContains(response, "Private Homework")
        self.assertEqual(self.client.get(reverse("register")).status_code, 200)

    def test_logged_in_user_skips_landing_page(self):
        """Scenario 2: a logged-in user who opens / goes to the logged-in home page."""
        self.client.force_login(self.user)

        response = self.client.get("/")

        self.assertRedirects(response, LOGGED_IN_HOME)

    def test_logging_in_from_homepage_lands_on_logged_in_home(self):
        """Scenario 3: valid credentials end on the logged-in home page, not the landing page."""
        response = self.client.post(
            reverse("login"),
            {"username": "student", "password": "Correct-Pass-123"},
            follow=True,
        )

        self.assertEqual(response.redirect_chain[-1][0], LOGGED_IN_HOME)
        self.assertTrue(response.wsgi_request.user.is_authenticated)

    def test_failed_login_from_homepage_shows_error(self):
        """Scenario 4 (outline): wrong password and unknown username get the same error."""
        bad_logins = {
            "the wrong password": {"username": "student", "password": "Wrong-Pass-999"},
            "an unknown username": {"username": "nobody", "password": "Correct-Pass-123"},
        }
        for problem, credentials in bad_logins.items():
            with self.subTest(problem=problem):
                response = self.client.post(reverse("login"), credentials)

                self.assertEqual(response.request["PATH_INFO"], reverse("login"))
                self.assertContains(response, LOGIN_ERROR)
                self.assertNotIn("_auth_user_id", self.client.session)
