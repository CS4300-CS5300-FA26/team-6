"""Open and remove contracts: private downloads and reversible confirmation."""
# Django supplies managers dynamically; pytest resolves application imports.
# pylint: disable=no-member,import-error

from pathlib import Path
from unittest.mock import patch

import pytest
from bs4 import BeautifulSoup
from django.contrib.messages import get_messages
from django.test import Client
from django.urls import reverse

from assignments.models import Assignment, Attachment, StudyFile
from assignments.test_models import MediaRootTestCase, make_user, upload


@pytest.mark.integration
class AttachmentActionTests(MediaRootTestCase):
    """As a student, manage linked files without exposing or deleting stored files."""

    def setUp(self):
        """Use real requests and temporary storage with Canvas context faked."""
        super().setUp()
        self.user = make_user("attachment-action-owner")
        self.client.force_login(self.user)
        self.assignment = Assignment.objects.create(
            user=self.user, canvas_course_id=42, canvas_assignment_id=101,
            title="Project", course="CS 4300",
        )
        self.study_file = upload(self.user, "notes.txt")
        self.attachment = Attachment.objects.create(
            user=self.user, assignment=self.assignment, study_file=self.study_file,
        )
        self.enterContext(patch("assignments.views.load_canvas_context", side_effect=lambda _: {
            "assignments_unavailable": False,
            "assignments": [{"canvas_assignment_id": 101, "canvas_course_id": 42,
                             "title": "Project", "course_name": "CS 4300"}],
        }))

    def url(self, route):
        """Resolve an action for the owner's linked file."""
        return reverse(route, kwargs={"attachment_id": self.attachment.pk})

    def test_owner_downloads_exact_bytes_with_original_name(self):
        """Given an owned attachment, opening downloads the original byte stream."""
        response = self.client.get(self.url("open_attachment"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Disposition"], 'attachment; filename="notes.txt"')
        self.assertEqual(b"".join(response.streaming_content), b"tiny study file")
        response.close()

    def test_hostile_original_name_cannot_inject_headers(self):
        """Quotes and a CRLF attempt stay encoded inside the download name."""
        self.study_file.original_name = 'evil"\r\nX-Injected: yes.html'
        self.study_file.save(update_fields=["original_name"])
        response = self.client.get(self.url("open_attachment"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response["Content-Disposition"],
            "attachment; filename*=utf-8''evil%22%0D%0AX-Injected%3A%20yes.html",
        )
        self.assertNotIn("X-Injected", response)
        response.close()

    def test_actions_are_private_and_require_login(self):
        """Other students get 404; anonymous clients go to login; neither unlinks."""
        other = Client()
        other.force_login(make_user("attachment-action-other"))
        for route, method in (("open_attachment", "get"), ("remove_attachment", "get"),
                              ("remove_attachment", "post")):
            with self.subTest(route=route, method=method):
                url = self.url(route)
                self.assertEqual(getattr(other, method)(url).status_code, 404)
                self.assertRedirects(
                    getattr(Client(), method)(url), f'{reverse("login")}?next={url}',
                    fetch_redirect_response=False,
                )
                self.assertTrue(Attachment.objects.filter(pk=self.attachment.pk).exists())

    def test_missing_object_reports_retry_error(self):
        """A missing stored file redirects with the exact error rather than a 500."""
        Path(self.study_file.file.path).unlink()
        response = self.client.get(self.url("open_attachment"))
        self.assertRedirects(response, reverse("assignment_list"))
        self.assertEqual([str(item) for item in get_messages(response.wsgi_request)],
                         ["Unable to open file. Please try again."])
        self.assertTrue(Attachment.objects.filter(pk=self.attachment.pk).exists())

    def test_storage_failures_report_retry_error(self):
        """Both existence and open failures from storage return a logged retry error."""
        storage = self.study_file.file.storage
        for operation in ("exists", "open"):
            with self.subTest(operation=operation):
                with patch.object(storage, operation, side_effect=RuntimeError("Storage down")):
                    with self.assertLogs("assignments.views", level="ERROR"):
                        response = self.client.get(self.url("open_attachment"))
                self.assertRedirects(response, reverse("assignment_list"))
                self.assertEqual([str(item) for item in get_messages(response.wsgi_request)],
                                 ["Unable to open file. Please try again."])

    def test_remove_confirmation_and_cancel_preserve_everything(self):
        """GET names the file and offers a protected form and harmless cancel link."""
        response = self.client.get(self.url("remove_attachment"))
        self.assertContains(response, "notes.txt")
        page = BeautifulSoup(response.content, "html.parser")
        form = page.find("button", string="Remove").find_parent("form")
        self.assertEqual(form["method"], "post")
        self.assertIsNotNone(form.select_one('input[name="csrfmiddlewaretoken"]'))
        self.assertEqual(form.find("button").get_text(strip=True), "Remove")
        cancel = page.find("a", string="Cancel")
        self.assertEqual(cancel["href"], reverse("assignment_list"))
        self.assertContains(self.client.get(cancel["href"]), "notes.txt")
        self.assertEqual(Attachment.objects.count(), 1)
        self.assertEqual(StudyFile.objects.count(), 1)
        self.assertEqual(Assignment.objects.count(), 1)
        self.assertEqual(Path(self.study_file.file.path).read_bytes(), b"tiny study file")

    def test_remove_without_csrf_is_forbidden_and_other_methods_rejected(self):
        """Missing CSRF and unsupported verbs must never remove a link."""
        protected = Client(enforce_csrf_checks=True)
        protected.force_login(self.user)
        self.assertEqual(protected.post(self.url("remove_attachment")).status_code, 403)
        self.assertEqual(self.client.delete(self.url("remove_attachment")).status_code, 405)
        self.assertTrue(Attachment.objects.filter(pk=self.attachment.pk).exists())

    def test_remove_one_preserves_other_links_and_stored_file(self):
        """POST unlinks only the target, preserves bytes, and cannot be repeated."""
        for name in ("rubric.pdf", "lecture.txt"):
            Attachment.objects.create(user=self.user, assignment=self.assignment,
                                      study_file=upload(self.user, name))
        url = self.url("remove_attachment")
        response = self.client.post(url)
        self.assertRedirects(response, reverse("assignment_list"))
        self.assertEqual([str(item) for item in get_messages(response.wsgi_request)],
                         ["File removed."])
        page = self.client.get(reverse("assignment_list"))
        self.assertNotContains(page, "notes.txt")
        self.assertContains(page, "rubric.pdf")
        self.assertContains(page, "lecture.txt")
        self.assertEqual(Attachment.objects.count(), 2)
        self.assertEqual(StudyFile.objects.count(), 3)
        self.assertTrue(StudyFile.objects.filter(pk=self.study_file.pk).exists())
        self.assertTrue(Assignment.objects.filter(pk=self.assignment.pk).exists())
        self.assertEqual(Path(self.study_file.file.path).read_bytes(), b"tiny study file")
        self.assertEqual(self.client.post(url).status_code, 404)

    def test_card_links_have_accessible_names_without_repeating_filename(self):
        """Each card offers an open link and a Remove link labelled with that file."""
        page = BeautifulSoup(self.client.get(reverse("assignment_list")).content, "html.parser")
        name = page.find("a", href=self.url("open_attachment"))
        self.assertIsNotNone(name)
        self.assertEqual(name.get_text(strip=True), "notes.txt")
        remove = page.find("a", href=self.url("remove_attachment"))
        self.assertIsNotNone(remove)
        self.assertEqual(remove.get_text(strip=True), "Remove")
        self.assertEqual(remove["aria-labelledby"].split(), [remove["id"], name["id"]])
