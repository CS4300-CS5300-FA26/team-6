"""Request tests for synchronizing Canvas assignments into local records."""

from datetime import datetime, timedelta, timezone as datetime_timezone
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache, caches
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.canvas_client import CanvasAPIError
from assignments.models import Assignment, Attachment, StudyFile
from assignments.test_helpers import configure_canvas_user
from assignments.test_models import use_temp_media_root


@pytest.mark.integration
class AssignmentSyncTests(TestCase):
    """The assignments-page request synchronizes records without changing local work."""

    def setUp(self):
        use_temp_media_root(self)
        self.user, self.connection = configure_canvas_user(self)

    def test_sync_upserts_and_marks_missing_without_losing_local_data(self):
        """Refresh Canvas-owned fields while retaining identity and student-owned data."""
        model_fields = {field.name for field in Assignment._meta.get_fields()}
        required_fields = {"description", "sync_state"}
        self.assertTrue(
            required_fields <= model_fields,
            f"Missing assignment sync fields: {required_fields - model_fields}",
        )

        old_due_date = datetime(2026, 10, 20, 18, 30, tzinfo=datetime_timezone.utc)
        new_due_date = datetime(2026, 10, 24, 18, 30, tzinfo=datetime_timezone.utc)
        existing = Assignment.objects.create(
            user=self.user,
            title="Old project title",
            course="Old course name",
            canvas_course_id=42,
            canvas_assignment_id=101,
            due_date=old_due_date,
            description="Old description",
            sync_state="missing",
            estimated_effort_minutes=75,
            effort_estimate_source="manual",
        )
        attachment_file = StudyFile.objects.create(
            user=self.user,
            file=SimpleUploadedFile("notes.pdf", b"notes"),
            original_name="notes.pdf",
            size=5,
        )
        attachment = Attachment.objects.create(
            user=self.user,
            assignment=existing,
            study_file=attachment_file,
        )
        cleared_description = Assignment.objects.create(
            user=self.user,
            title="Old title",
            course="CS 4300",
            canvas_course_id=42,
            canvas_assignment_id=103,
            description="Stale description",
            sync_state="failed",
        )
        active_missing = Assignment.objects.create(
            user=self.user,
            title="No longer returned",
            course="MATH 2250",
            canvas_course_id=84,
            canvas_assignment_id=104,
            sync_state="synced",
        )
        outside_active_courses = Assignment.objects.create(
            user=self.user,
            title="Other course",
            course="History 1010",
            canvas_course_id=999,
            canvas_assignment_id=105,
            sync_state="failed",
        )
        other_user = get_user_model().objects.create_user(username="sync-other-student")
        other_student_assignment = Assignment.objects.create(
            user=other_user,
            title="Another student's title",
            course="CS 4300",
            canvas_course_id=42,
            canvas_assignment_id=101,
            description="Another student's description",
            sync_state="failed",
        )

        courses = [
            {"id": 42, "name": "CS 4300"},
            {"id": 84, "name": "MATH 2250"},
        ]
        all_assignments = [
            {
                "canvas_assignment_id": 101,
                "canvas_course_id": 84,
                "title": "Updated project title",
                "course_name": "MATH 2250",
                "due_date": new_due_date,
                "submitted": False,
                "description": "Updated description",
            },
            {
                "canvas_assignment_id": 102,
                "canvas_course_id": 84,
                "title": "Undated assignment",
                "course_name": "MATH 2250",
                "due_date": None,
                "submitted": False,
                "description": "New assignment description",
            },
            {
                "canvas_assignment_id": 103,
                "canvas_course_id": 42,
                "title": "Description removed",
                "course_name": "CS 4300",
                "due_date": None,
                "submitted": False,
            },
            {
                "canvas_assignment_id": 101,
                "canvas_course_id": 84,
                "title": "Updated project title",
                "course_name": "MATH 2250",
                "due_date": new_due_date,
                "submitted": False,
                "description": "Updated description",
            },
        ]
        upcoming_assignments = [{
            "canvas_assignment_id": 101,
            "canvas_course_id": 84,
            "title": "Updated project title",
            "course_name": "MATH 2250",
            "due_date": new_due_date,
            "submitted": False,
        }]
        with override_settings(CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "assignment-sync-upsert-test",
            },
        }):
            with patch("assignments.views.list_courses", return_value=courses), \
                    patch("assignments.views.list_upcoming_assignments",
                          return_value=upcoming_assignments), \
                    patch("assignments.views.list_graded_submissions", return_value=[]), \
                    patch("assignments.views.list_all_assignments",
                          create=True, return_value=all_assignments):
                response = self.client.get(reverse("assignment_list"))

        self.assertEqual(response.status_code, 200)
        existing.refresh_from_db()
        cleared_description.refresh_from_db()
        active_missing.refresh_from_db()
        outside_active_courses.refresh_from_db()
        other_student_assignment.refresh_from_db()
        created = Assignment.objects.get(user=self.user, canvas_assignment_id=102)
        self.assertEqual(existing.pk, Assignment.objects.get(
            user=self.user, canvas_assignment_id=101
        ).pk)
        self.assertEqual(existing.title, "Updated project title")
        self.assertEqual(existing.course, "MATH 2250")
        self.assertEqual(existing.canvas_course_id, 84)
        self.assertEqual(existing.due_date, new_due_date)
        self.assertEqual(existing.description, "Updated description")
        self.assertEqual(existing.sync_state, "synced")
        self.assertEqual(existing.estimated_effort_minutes, 75)
        self.assertEqual(existing.effort_estimate_source, "manual")
        self.assertEqual(list(existing.attachments.values_list("pk", flat=True)), [attachment.pk])
        self.assertIsNone(created.due_date)
        self.assertEqual(created.description, "New assignment description")
        self.assertEqual(
            Assignment.objects.filter(user=self.user, canvas_assignment_id=101).count(),
            1,
        )
        self.assertIn(cleared_description.description, (None, ""))
        self.assertEqual(cleared_description.sync_state, "synced")
        self.assertEqual(active_missing.sync_state, "missing")
        self.assertEqual(outside_active_courses.sync_state, "failed")
        self.assertEqual(other_student_assignment.title, "Another student's title")
        self.assertEqual(other_student_assignment.sync_state, "failed")

    @override_settings(CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "assignment-sync-cache-test",
        },
    })
    def test_cache_reuse_expiry_reconnection_and_empty_result(self):
        """Cache empty successes, skip writes on hits, and refresh after expiry/reconnect."""
        model_fields = {field.name for field in Assignment._meta.get_fields()}
        required_fields = {"description", "sync_state"}
        self.assertTrue(
            required_fields <= model_fields,
            f"Missing assignment sync fields: {required_fields - model_fields}",
        )

        active_assignment = Assignment.objects.create(
            user=self.user,
            title="Canvas title",
            course="CS 4300",
            canvas_course_id=42,
            canvas_assignment_id=201,
            description="Canvas description",
            sync_state="synced",
        )
        outside_active_course = Assignment.objects.create(
            user=self.user,
            title="Other course title",
            course="History 1010",
            canvas_course_id=999,
            canvas_assignment_id=202,
            sync_state="synced",
        )
        courses = [{"id": 42, "name": "CS 4300"}]
        refreshed_assignment = {
            "canvas_assignment_id": 201,
            "canvas_course_id": 42,
            "title": "Refreshed title",
            "course_name": "CS 4300",
            "due_date": None,
            "submitted": False,
            "description": "Refreshed description",
        }
        cache.clear()
        with patch("assignments.views.list_courses", return_value=courses) as list_courses, \
                patch("assignments.views.list_upcoming_assignments", return_value=[]) as upcoming, \
                patch("assignments.views.list_graded_submissions", return_value=[]), \
                patch(
                    "assignments.views.list_all_assignments",
                    create=True,
                    side_effect=[[], [refreshed_assignment], []],
                ) as all_assignments:
            first_response = self.client.get(reverse("assignment_list"))
            self.assertEqual(first_response.status_code, 200)
            active_assignment.refresh_from_db()
            outside_active_course.refresh_from_db()
            self.assertEqual(active_assignment.sync_state, "missing")
            self.assertEqual(outside_active_course.sync_state, "synced")

            active_assignment.title = "Database sentinel"
            active_assignment.sync_state = "failed"
            active_assignment.save(update_fields=["title", "sync_state"])
            second_response = self.client.get(reverse("assignment_list"))
            self.assertEqual(second_response.status_code, 200)
            active_assignment.refresh_from_db()
            self.assertEqual(active_assignment.title, "Database sentinel")
            self.assertEqual(active_assignment.sync_state, "failed")
            all_assignments.assert_called_once()
            self.assertEqual(upcoming.call_count, 2)

            backend = caches["default"]
            self.assertTrue(backend._expire_info)
            backend._expire_info = {key: 0 for key in backend._expire_info}
            expired_response = self.client.get(reverse("assignment_list"))
            self.assertEqual(expired_response.status_code, 200)
            active_assignment.refresh_from_db()
            self.assertEqual(active_assignment.title, "Refreshed title")
            self.assertEqual(active_assignment.description, "Refreshed description")
            self.assertEqual(active_assignment.sync_state, "synced")
            self.assertEqual(all_assignments.call_count, 2)

            self.connection.set_token("replacement-canvas-token")
            self.connection.save()
            reconnected_response = self.client.get(reverse("assignment_list"))
            self.assertEqual(reconnected_response.status_code, 200)
            active_assignment.refresh_from_db()
            self.assertEqual(active_assignment.sync_state, "missing")
            self.assertEqual(all_assignments.call_count, 3)
            self.assertEqual(list_courses.call_count, 3)

    @override_settings(CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "assignment-sync-failure-test",
        },
    })
    def test_failed_sync_rolls_back_warns_and_retries(self):
        """Retrieval and persistence failures preserve records and allow retry."""
        model_fields = {field.name for field in Assignment._meta.get_fields()}
        required_fields = {"description", "sync_state"}
        self.assertTrue(
            required_fields <= model_fields,
            f"Missing assignment sync fields: {required_fields - model_fields}",
        )

        old_due_date = datetime(2026, 10, 20, 18, 30, tzinfo=datetime_timezone.utc)
        new_due_date = datetime(2026, 10, 25, 18, 30, tzinfo=datetime_timezone.utc)
        first_record = Assignment.objects.create(
            user=self.user,
            title="Original first title",
            course="CS 4300",
            canvas_course_id=42,
            canvas_assignment_id=301,
            due_date=old_due_date,
            description="Original first description",
            sync_state="synced",
            estimated_effort_minutes=60,
            effort_estimate_source="manual",
        )
        second_record = Assignment.objects.create(
            user=self.user,
            title="Original second title",
            course="CS 4300",
            canvas_course_id=42,
            canvas_assignment_id=302,
            description="Original second description",
            sync_state="synced",
        )
        attachment_file = StudyFile.objects.create(
            user=self.user,
            file=SimpleUploadedFile("failure-notes.pdf", b"notes"),
            original_name="failure-notes.pdf",
            size=5,
        )
        attachment = Attachment.objects.create(
            user=self.user,
            assignment=first_record,
            study_file=attachment_file,
        )
        other_user = get_user_model().objects.create_user(username="sync-failure-other")
        other_student_record = Assignment.objects.create(
            user=other_user,
            title="Other student's unchanged title",
            course="CS 4300",
            canvas_course_id=42,
            canvas_assignment_id=301,
            description="Other student's description",
            sync_state="synced",
        )

        courses = [{"id": 42, "name": "CS 4300"}]
        updated_records = [
            {
                "canvas_assignment_id": 301,
                "canvas_course_id": 42,
                "title": "Refreshed first title",
                "course_name": "CS 4300",
                "due_date": new_due_date,
                "submitted": False,
                "description": "Refreshed first description",
            },
            {
                "canvas_assignment_id": 302,
                "canvas_course_id": 42,
                "title": "Refreshed second title",
                "course_name": "CS 4300",
                "due_date": None,
                "submitted": False,
                "description": "Refreshed second description",
            },
        ]
        upcoming_assignment = {
            "canvas_assignment_id": 301,
            "canvas_course_id": 42,
            "title": "Upcoming assignment remains visible",
            "course_name": "CS 4300",
            "due_date": timezone.now() + timedelta(days=1),
            "submitted": False,
        }
        cache.clear()
        with override_settings(CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "assignment-sync-failure-test",
            },
        }):
            with patch("assignments.views.list_courses", return_value=courses), \
                    patch("assignments.views.list_upcoming_assignments",
                          return_value=[upcoming_assignment]) as upcoming, \
                    patch("assignments.views.list_graded_submissions", return_value=[]), \
                    patch(
                        "assignments.views.list_all_assignments",
                        create=True,
                        side_effect=[
                            CanvasAPIError("Canvas sync retrieval failed"),
                            updated_records,
                            updated_records,
                        ],
                    ) as all_assignments:
                retrieval_failure_response = self.client.get(reverse("assignment_list"))
                self.assertEqual(retrieval_failure_response.status_code, 200)
                self.assertContains(retrieval_failure_response, "Upcoming assignment remains visible")
                self.assertContains(retrieval_failure_response, "Unable to sync")
                first_record.refresh_from_db()
                second_record.refresh_from_db()
                self.assertEqual(first_record.title, "Original first title")
                self.assertEqual(first_record.sync_state, "failed")
                self.assertEqual(second_record.title, "Original second title")
                self.assertEqual(second_record.sync_state, "failed")
                self.assertEqual(first_record.attachments.get().pk, attachment.pk)

                original_save = Assignment.save
                save_calls = 0

                def fail_on_second_save(instance, *args, **kwargs):
                    nonlocal save_calls
                    if instance.user_id == self.user.pk:
                        save_calls += 1
                        if save_calls == 2:
                            raise RuntimeError("Injected assignment persistence failure")
                    return original_save(instance, *args, **kwargs)

                with patch.object(Assignment, "save", new=fail_on_second_save):
                    persistence_failure_response = self.client.get(reverse("assignment_list"))
                self.assertEqual(persistence_failure_response.status_code, 200)
                self.assertContains(persistence_failure_response, "Upcoming assignment remains visible")
                self.assertContains(persistence_failure_response, "Unable to sync")
                first_record.refresh_from_db()
                second_record.refresh_from_db()
                self.assertEqual(first_record.title, "Original first title")
                self.assertEqual(first_record.due_date, old_due_date)
                self.assertEqual(first_record.description, "Original first description")
                self.assertEqual(first_record.estimated_effort_minutes, 60)
                self.assertEqual(first_record.effort_estimate_source, "manual")
                self.assertEqual(first_record.sync_state, "failed")
                self.assertEqual(second_record.title, "Original second title")
                self.assertEqual(second_record.description, "Original second description")
                self.assertEqual(second_record.sync_state, "failed")
                self.assertEqual(first_record.attachments.get().pk, attachment.pk)

                retry_response = self.client.get(reverse("assignment_list"))
                self.assertEqual(retry_response.status_code, 200)
                self.assertContains(retry_response, "Upcoming assignment remains visible")
                self.assertNotContains(retry_response, "Unable to sync")
                first_record.refresh_from_db()
                second_record.refresh_from_db()
                self.assertEqual(first_record.title, "Refreshed first title")
                self.assertEqual(first_record.sync_state, "synced")
                self.assertEqual(second_record.title, "Refreshed second title")
                self.assertEqual(second_record.sync_state, "synced")
                other_student_record.refresh_from_db()
                self.assertEqual(other_student_record.title, "Other student's unchanged title")
                self.assertEqual(other_student_record.sync_state, "synced")
                self.assertEqual(upcoming.call_count, 3)
                self.assertEqual(all_assignments.call_count, 3)