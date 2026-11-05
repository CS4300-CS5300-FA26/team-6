"""Tests for refreshing selected assignment snapshots from Canvas."""

from datetime import datetime, timezone as datetime_timezone
from unittest.mock import patch

from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from accounts.canvas_client import CanvasAPIError, CanvasAuthenticationError
from accounts.models import CanvasConnection
from assignments.canvas_sync import refresh_selected_assignment_snapshots
from assignments.models import Assignment


@override_settings(
    CANVAS_BASE_URL="https://canvas.example.edu",
    CANVAS_TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode(),
)
class SelectedAssignmentRefreshTests(TestCase):
    """Canvas refresh changes selected snapshot fields and leaves local estimates intact."""

    def setUp(self):
        self.user = get_user_model().objects.create_user(username="snapshot-owner")
        self.connection = CanvasConnection(
            user=self.user,
            canvas_url="https://canvas.example.edu",
        )
        self.connection.set_token("canvas-test-token")
        self.connection.save()
        self.selected = Assignment.objects.create(
            user=self.user,
            canvas_course_id=42,
            canvas_assignment_id=101,
            title="Old title",
            course="Old course",
            due_date=datetime(2026, 11, 10, tzinfo=datetime_timezone.utc),
            description="Old description",
            estimated_effort_minutes=75,
            effort_estimate_source="manual",
        )
        self.unselected = Assignment.objects.create(
            user=self.user,
            canvas_course_id=42,
            canvas_assignment_id=102,
            title="Unselected title",
            course="CS 4300",
            description="Unselected description",
            estimated_effort_minutes=45,
            effort_estimate_source="manual",
        )

    @patch("assignments.canvas_sync.list_courses", return_value=[{"id": 42, "name": "CS 4300"}])
    @patch("assignments.canvas_sync.list_upcoming_assignments")
    def test_refresh_updates_only_selected_canvas_fields(self, list_assignments, _list_courses):
        """Refresh selected Canvas fields and preserve unselected rows and estimates."""
        revised_due_date = datetime(2026, 11, 12, tzinfo=datetime_timezone.utc)
        list_assignments.return_value = [
            {
                "canvas_assignment_id": 101,
                "canvas_course_id": 43,
                "title": "Updated title",
                "course_name": "CS 4301",
                "due_date": revised_due_date,
                "description": "Updated description",
            },
            {
                "canvas_assignment_id": 102,
                "canvas_course_id": 42,
                "title": "Canvas title that must not sync",
                "course_name": "CS 4300",
                "due_date": None,
                "description": "Changed unselected data",
            },
        ]

        notices = refresh_selected_assignment_snapshots(self.user, [self.selected])

        self.selected.refresh_from_db()
        self.unselected.refresh_from_db()
        self.assertEqual(notices, [])
        self.assertEqual(
            (
                self.selected.title,
                self.selected.course,
                self.selected.canvas_course_id,
                self.selected.due_date,
                self.selected.description,
            ),
            ("Updated title", "CS 4301", 43, revised_due_date, "Updated description"),
        )
        self.assertEqual(self.selected.estimated_effort_minutes, 75)
        self.assertEqual(self.selected.effort_estimate_source, "manual")
        self.assertEqual(self.unselected.title, "Unselected title")
        self.assertEqual(self.unselected.description, "Unselected description")
        self.assertEqual(self.unselected.estimated_effort_minutes, 45)

    @patch("assignments.canvas_sync.list_courses", side_effect=CanvasAPIError("Canvas down"))
    def test_canvas_failure_keeps_snapshot_and_returns_notice(self, _list_courses):
        """Keep the persisted assignment snapshot when Canvas is unavailable."""
        notices = refresh_selected_assignment_snapshots(self.user, [self.selected])

        self.selected.refresh_from_db()
        self.assertEqual(self.selected.title, "Old title")
        self.assertEqual(self.selected.description, "Old description")
        self.assertEqual(self.selected.estimated_effort_minutes, 75)
        self.assertEqual(len(notices), 1)
        self.assertIn("used saved Canvas details", notices[0])

    @patch("assignments.canvas_sync.list_courses", return_value=[{"id": 42, "name": "CS 4300"}])
    @patch("assignments.canvas_sync.list_upcoming_assignments", return_value=[])
    def test_missing_canvas_result_keeps_snapshot_and_returns_notice(
        self,
        _list_assignments,
        _list_courses,
    ):
        """Keep the snapshot and report when Canvas omits a selected assignment."""
        notices = refresh_selected_assignment_snapshots(self.user, [self.selected])

        self.selected.refresh_from_db()
        self.assertEqual(self.selected.title, "Old title")
        self.assertEqual(self.selected.description, "Old description")
        self.assertEqual(len(notices), 1)
        self.assertIn("was not returned by Canvas", notices[0])

    @patch(
        "assignments.canvas_sync.list_courses",
        side_effect=CanvasAuthenticationError("Canvas rejected token"),
    )
    def test_expired_canvas_token_is_marked_invalid_and_snapshot_is_kept(self, _list_courses):
        """Invalidate rejected credentials while preserving the local snapshot."""
        notices = refresh_selected_assignment_snapshots(self.user, [self.selected])

        self.connection.refresh_from_db()
        self.selected.refresh_from_db()
        self.assertFalse(self.connection.is_valid)
        self.assertEqual(self.selected.title, "Old title")
        self.assertEqual(len(notices), 1)
        self.assertIn("used saved Canvas details", notices[0])

