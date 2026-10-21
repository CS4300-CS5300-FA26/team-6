"""Tests for the assignments list page (URL -> view -> model -> template)."""

from datetime import timedelta

import pytest
from django.test import TestCase
from django.utils import timezone
from django.urls import reverse

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
