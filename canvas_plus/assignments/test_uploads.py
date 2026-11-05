"""Upload contract: student-owned batches are validated and saved atomically."""
# Django creates managers dynamically; app imports resolve through pytest's pythonpath.
# pylint: disable=no-member,import-error

from datetime import datetime, timezone
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from bs4 import BeautifulSoup
from cryptography.fernet import Fernet
from django.contrib.messages import get_messages
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, override_settings
from django.urls import reverse

from accounts.canvas_client import CanvasAPIError, CanvasAuthenticationError
from accounts.models import CanvasConnection
from assignments.models import Assignment, Attachment, StudyFile
from assignments.test_models import MediaRootTestCase, make_user, upload


@pytest.mark.unit
@pytest.mark.parametrize("sizes", [(26_214_399,), (26_214_400,), (13_107_200, 13_107_200)])
def test_batch_accepts_up_to_binary_limit(sizes):
    """Given at most 25 MiB total, validation accepts size-only file stubs."""
    uploads = import_module("assignments.uploads")
    uploads.validate_batch([SimpleNamespace(size=size) for size in sizes])


@pytest.mark.unit
@pytest.mark.parametrize("sizes,message", [
    ((26_214_401,), "File batch exceeds 25 MB limit"),
    ((13_107_200, 13_107_201), "File batch exceeds 25 MB limit"),
    ((), "Choose at least one file to upload."),
])
def test_batch_rejects_excess_total_or_empty_input(sizes, message):
    """Given an oversized or empty batch, report the contract's exact message."""
    uploads = import_module("assignments.uploads")
    with pytest.raises(ValidationError) as caught:
        uploads.validate_batch([SimpleNamespace(size=size) for size in sizes])
    assert caught.value.messages == [message]


@pytest.mark.integration
class AttachmentUploadTests(MediaRootTestCase):
    """Exercise requests, real rows, and real files with Canvas faked at its boundary."""

    def setUp(self):
        """A signed-in student with an encrypted connection and two live assignments."""
        super().setUp()
        configured = override_settings(
            CANVAS_BASE_URL="https://canvas.example.edu",
            CANVAS_TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode(),
        )
        configured.enable()
        self.addCleanup(configured.disable)
        self.user = make_user("upload-student")
        self.connection = CanvasConnection(user=self.user, canvas_url="https://canvas.example.edu")
        self.connection.set_token("fake-upload-token")
        self.connection.save()
        self.client.force_login(self.user)
        self.canvas_assignments = self.enterContext(patch(
            "assignments.views.list_upcoming_assignments", create=True, return_value=[
                {
                    "canvas_assignment_id": 101, "canvas_course_id": 42,
                    "title": "Canvas Project 1", "course_name": "CS 4300",
                    "due_date": datetime(2026, 11, 10, 18, 30, tzinfo=timezone.utc),
                    "submitted": False,
                },
                {
                    "canvas_assignment_id": 102, "canvas_course_id": 42,
                    "title": "Canvas Essay", "course_name": "CS 4300",
                    "due_date": None, "submitted": False,
                },
            ],
        ))
        self.enterContext(patch(
            "assignments.views.list_courses", create=True,
            return_value=[{"id": 42, "name": "CS 4300"}],
        ))
        self.enterContext(patch(
            "assignments.views.list_graded_submissions", create=True, return_value=[],
        ))

    def post_batch(self, files, **fields):
        """Submit multipart files using the public endpoint name and Canvas identity."""
        return self.client.post(
            reverse("upload_attachments", kwargs={"course_id": 42, "assignment_id": 101}),
            {"files": files, **fields},
        )

    def assert_nothing_saved(self):
        """Rejected uploads leave no files or links beyond Canvas assignment sync."""
        self.assertTrue(
            set(
                Assignment.objects.filter(user=self.user).values_list(
                    "canvas_assignment_id", flat=True
                )
            ).issubset({101, 102})
        )
        for model in (StudyFile, Attachment):
            self.assertEqual(model.objects.count(), 0)
        self.assertEqual([path for path in Path(self.media_root).rglob("*") if path.is_file()], [])

    def assert_redirect_message(self, response, message):
        """Validation failures redirect and display their exact message."""
        self.assertEqual(response.status_code, 302)
        page = self.client.get(response.url, follow=True)
        self.assertContains(page, message)
        self.assertIn(message, list(BeautifulSoup(page.content, "html.parser").stripped_strings))

    def test_multiple_files_use_canvas_snapshot_and_render_after_redirect(self):
        """Given forged snapshot fields, a successful batch still trusts only Canvas."""
        response = self.post_batch(
            [SimpleUploadedFile("notes.txt", b"notes"),
             SimpleUploadedFile("rubric.pdf", b"rubric")],
            title="Forged title", course="Forged course", course_name="Forged course",
            due_date="2000-01-01T00:00:00Z", canvas_course_id=999,
        )
        self.assertRedirects(response, reverse("assignment_list"))
        assignment = Assignment.objects.get(
            user=self.user,
            canvas_assignment_id=101,
        )
        self.assertEqual(
            (assignment.user_id, assignment.canvas_assignment_id, assignment.canvas_course_id,
             assignment.title, assignment.course, assignment.due_date),
            (self.user.pk, 101, 42, "Canvas Project 1", "CS 4300",
             datetime(2026, 11, 10, 18, 30, tzinfo=timezone.utc)),
        )
        self.assertEqual(StudyFile.objects.count(), 2)
        self.assertEqual(Attachment.objects.count(), 2)
        self.assertEqual(
            set(StudyFile.objects.values_list("original_name", "size")),
            {("notes.txt", 5), ("rubric.pdf", 6)},
        )
        for link in Attachment.objects.select_related("study_file"):
            self.assertEqual((link.user_id, link.assignment_id, link.category),
                             (self.user.pk, assignment.pk, ""))
            self.assertEqual(link.study_file.user_id, self.user.pk)
            self.assertEqual(Path(link.study_file.file.path).read_bytes(),
                             {"notes.txt": b"notes", "rubric.pdf": b"rubric"}[
                                 link.study_file.original_name])
        page = self.client.get(response.url)
        self.assertContains(page, "notes.txt")
        self.assertContains(page, "rubric.pdf")

    def test_second_batch_reuses_assignment_and_preserves_duplicate_names(self):
        """Given two batches with the same original name, both byte streams survive."""
        first = self.post_batch([SimpleUploadedFile("notes.txt", b"first")])
        self.assertEqual(first.status_code, 302)
        original_pk = Assignment.objects.get(
            user=self.user,
            canvas_assignment_id=101,
        ).pk
        second = self.post_batch([SimpleUploadedFile("notes.txt", b"second")])
        self.assertRedirects(second, reverse("assignment_list"))
        self.assertEqual(
            Assignment.objects.filter(
                user=self.user,
                canvas_assignment_id=101,
            ).values_list("pk", flat=True).get(),
            original_pk,
        )
        files = list(StudyFile.objects.order_by("pk"))
        self.assertEqual([item.original_name for item in files], ["notes.txt", "notes.txt"])
        self.assertNotEqual(files[0].file.name, files[1].file.name)
        self.assertEqual([Path(item.file.path).read_bytes() for item in files],
                         [b"first", b"second"])
        self.assertEqual(Attachment.objects.filter(assignment_id=original_pk).count(), 2)
        self.assertContains(self.client.get(second.url), "notes.txt", count=2)

    def test_unknown_assignment_or_wrong_course_is_not_saved(self):
        """Neither an unknown assignment nor a known assignment in another course is allowed."""
        for course_id, assignment_id in ((42, 999), (84, 101)):
            with self.subTest(course_id=course_id, assignment_id=assignment_id):
                response = self.client.post(
                    reverse("upload_attachments", kwargs={
                        "course_id": course_id, "assignment_id": assignment_id,
                    }), {"files": [SimpleUploadedFile("private.txt", b"secret")]},
                )
                self.assertEqual(response.status_code, 404)
                self.assert_nothing_saved()

    def test_upload_requires_sign_in_and_csrf(self):
        """Anonymous requests go to login and signed-in requests without CSRF are forbidden."""
        url = reverse("upload_attachments", kwargs={"course_id": 42, "assignment_id": 101})
        anonymous = Client().post(url, {"files": [SimpleUploadedFile("a.txt", b"a")]})
        self.assertRedirects(anonymous, f'{reverse("login")}?next={url}',
                             fetch_redirect_response=False)
        protected = Client(enforce_csrf_checks=True)
        protected.force_login(self.user)
        response = protected.post(url, {"files": [SimpleUploadedFile("b.txt", b"b")]})
        self.assertEqual(response.status_code, 403)
        self.assert_nothing_saved()

    def test_oversized_real_batch_is_rejected_without_rows_or_files(self):
        """Two individually small files totaling 26,214,401 bytes reject the whole batch."""
        response = self.post_batch([
            SimpleUploadedFile("part-one.bin", b"a" * 13_107_200),
            SimpleUploadedFile("part-two.bin", b"b" * 13_107_201),
        ])
        self.assert_redirect_message(response, "File batch exceeds 25 MB limit")
        self.assert_nothing_saved()

    def test_empty_batch_is_rejected_without_rows_or_files(self):
        """A multipart request with no files displays the exact empty-batch message."""
        response = self.post_batch([])
        self.assert_redirect_message(response, "Choose at least one file to upload.")
        self.assert_nothing_saved()

    def test_canvas_authentication_failure_invalidates_connection_without_saving(self):
        """Expired Canvas credentials cannot create an attachment or cause a server error."""
        self.canvas_assignments.side_effect = CanvasAuthenticationError("Expired token")
        response = self.post_batch([SimpleUploadedFile("notes.txt", b"notes")])
        self.assertLess(response.status_code, 500)
        self.connection.refresh_from_db()
        self.assertFalse(self.connection.is_valid)
        self.assert_nothing_saved()

    def test_canvas_api_failure_does_not_save_or_return_server_error(self):
        """An unavailable Canvas response leaves all local state untouched."""
        self.canvas_assignments.side_effect = CanvasAPIError("Canvas unavailable")
        response = self.post_batch([SimpleUploadedFile("notes.txt", b"notes")])
        self.assertLess(response.status_code, 500)
        self.assert_nothing_saved()

    def test_second_storage_failure_removes_first_file_and_all_rows(self):
        """A partial batch rolls back its rows and removes its stored bytes."""
        # FileField's public metadata API is exposed as Django's conventional _meta.
        storage = StudyFile._meta.get_field("file").storage  # pylint: disable=protected-access
        real_save = storage.save
        written = []

        def fail_second_save(name, content, **kwargs):
            if written:
                raise OSError("Storage unavailable")
            stored_name = real_save(name, content, **kwargs)
            written.append(Path(storage.path(stored_name)))
            self.assertTrue(written[0].is_file())
            return stored_name

        with patch.object(storage, "save", side_effect=fail_second_save):
            response = self.post_batch([
                SimpleUploadedFile("first.txt", b"first"),
                SimpleUploadedFile("second.txt", b"second"),
            ])
        self.assertEqual(len(written), 1, "The failure must follow a real file write")
        self.assertLess(response.status_code, 500)
        page = (self.client.get(response.url, follow=True)
                if response.status_code == 302 else response)
        errors = [item for item in get_messages(page.wsgi_request) if item.level_tag == "error"]
        self.assertTrue(errors, "The failed upload must display an error")
        self.assertContains(page, str(errors[0]))
        self.assert_nothing_saved()
        self.assertFalse(written[0].exists())

    def test_list_syncs_assignments_and_matches_attachments_by_identity_and_owner(self):
        """GET syncs Canvas rows; names appear only on the matching owner's Canvas card."""
        page = self.client.get(reverse("assignment_list"))
        self.assertEqual(page.status_code, 200)
        self.assert_nothing_saved()
        other = make_user("other-upload-student")
        for owner, canvas_id, name in (
            (self.user, 101, "my-project-notes.txt"),
            (self.user, 102, "my-essay-notes.txt"),
            (other, 101, "private-other-student.txt"),
        ):
            assignment = Assignment.objects.filter(
                user=owner,
                canvas_assignment_id=canvas_id,
            ).first()
            if assignment is None:
                assignment = Assignment.objects.create(
                    user=owner,
                    canvas_assignment_id=canvas_id,
                    canvas_course_id=42,
                    title="Stale local title",
                    course="Stale local course",
                )
            Attachment.objects.create(
                user=owner, assignment=assignment, study_file=upload(owner, name),
            )
        page = self.client.get(reverse("assignment_list"))
        self.assertContains(page, "my-project-notes.txt")
        self.assertContains(page, "my-essay-notes.txt")
        self.assertNotContains(page, "private-other-student.txt")
        # Use the established assignment-card markup, allowing nested attachment lists.
        cards = BeautifulSoup(page.content, "html.parser").select("li.assignment-card")
        project = next(card for card in cards if "Canvas Project 1" in card.get_text())
        essay = next(card for card in cards if "Canvas Essay" in card.get_text())
        self.assertIn("my-project-notes.txt", project.get_text())
        self.assertNotIn("my-essay-notes.txt", project.get_text())
        self.assertIn("my-essay-notes.txt", essay.get_text())
        self.assertNotIn("my-project-notes.txt", essay.get_text())
        self.assertEqual(Assignment.objects.filter(user=self.user).count(), 2)
        self.assertEqual(Assignment.objects.filter(user=other).count(), 1)
