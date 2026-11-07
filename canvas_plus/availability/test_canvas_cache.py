"""Tests for Canvas synchronization on the availability page."""

from unittest.mock import patch

from django.core.cache import cache
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.canvas_client import CanvasAPIError
from assignments.test_helpers import configure_canvas_user


@override_settings(CACHES={
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "availability-canvas-cache-test",
    },
})
class AvailabilityCanvasCacheTests(TestCase):
    """The planning page uses the shared assignment synchronization cache."""

    def setUp(self):
        cache.clear()
        self.user, self.connection = configure_canvas_user(self)

    @patch("assignments.views.list_graded_submissions", return_value=[])
    @patch("assignments.views.list_upcoming_assignments", return_value=[])
    @patch("assignments.views.list_all_assignments", return_value=[])
    @patch("assignments.views.list_courses", return_value=[{"id": 42, "name": "Course"}])
    def test_repeated_visits_reuse_cached_sync(
        self, courses, all_assignments, upcoming, graded
    ):
        """Only the first visit fetches data needed by the planning page."""
        first = self.client.get(reverse("availability:list"))
        second = self.client.get(reverse("availability:list"))

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        courses.assert_called_once()
        all_assignments.assert_called_once()
        upcoming.assert_not_called()
        graded.assert_not_called()

    @patch("assignments.views.list_graded_submissions", return_value=[])
    @patch("assignments.views.list_upcoming_assignments", return_value=[])
    @patch("assignments.views.list_all_assignments", return_value=[])
    @patch("assignments.views.list_courses", return_value=[])
    def test_shared_cache_miss_and_reconnection(
        self, courses, all_assignments, upcoming, graded
    ):
        """Both pages share cached syncs, which expire or change on reconnect."""
        self.client.get(reverse("assignment_list"))
        self.client.get(reverse("availability:list"))
        courses.assert_called_once()
        all_assignments.assert_called_once()
        upcoming.assert_called_once()
        graded.assert_called_once()

        cache.clear()
        self.client.get(reverse("availability:list"))
        self.assertEqual(courses.call_count, 2)
        self.assertEqual(all_assignments.call_count, 2)

        self.connection.set_token("replacement-canvas-token")
        self.connection.save()
        self.client.get(reverse("availability:list"))
        self.assertEqual(courses.call_count, 3)
        self.assertEqual(all_assignments.call_count, 3)
        self.assertEqual(all_assignments.call_args.args[0], "replacement-canvas-token")
        upcoming.assert_called_once()
        graded.assert_called_once()

    @patch("assignments.views.list_graded_submissions", return_value=[])
    @patch("assignments.views.list_upcoming_assignments", return_value=[])
    @patch("assignments.views.list_all_assignments", side_effect=[CanvasAPIError("Down"), []])
    @patch("assignments.views.list_courses", return_value=[])
    def test_failed_sync_is_reported_and_retried(
        self, courses, all_assignments, upcoming, graded
    ):
        """A failed sync does not become a cache hit on the next visit."""
        first = self.client.get(reverse("availability:list"))
        second = self.client.get(reverse("availability:list"))

        self.assertTrue(first.context["planning_assignments_unavailable"])
        self.assertFalse(second.context["planning_assignments_unavailable"])
        courses.assert_called_once()
        self.assertEqual(all_assignments.call_count, 2)
        upcoming.assert_not_called()
        graded.assert_not_called()
