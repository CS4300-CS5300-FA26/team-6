"""Tests for the assignments list page (URL -> view -> model -> template)."""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from .models import Assignment


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
        """With an empty database, the page still loads instead of crashing."""
        response = self.client.get("/assignments/")

        self.assertEqual(response.status_code, 200)
