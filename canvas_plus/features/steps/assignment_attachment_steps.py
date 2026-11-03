"""Attachment acceptance steps use real requests/storage and fake Canvas results."""
# Behave registers decorators dynamically; Django supplies managers at runtime.
# pylint: disable=not-callable,missing-function-docstring,import-error,no-member

import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from behave import given, when, then
from bs4 import BeautifulSoup
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse

from assignments.models import Assignment, Attachment, StudyFile


@given("I am viewing an assignment deadline")
def step_viewing_attachment_deadline(context):
    context.execute_steps('''
        Given I am a connected student with upcoming coursework due on "November 10, 2026 at 12:30 PM"
    ''')
    context.canvas_assignments.return_value = [{
        "canvas_assignment_id": 101, "canvas_course_id": 42,
        "title": "Canvas Project 1", "course_name": "CS 4300",
        "due_date": datetime(2026, 11, 10, 18, 30, tzinfo=timezone.utc), "submitted": False,
    }]
    context.user.set_password("attachment-behave-password")
    context.user.save()
    context.client.force_login(context.user)
    context.attachment_media = tempfile.mkdtemp(prefix="canvas_plus_behave_upload_")
    context.add_cleanup(shutil.rmtree, context.attachment_media, ignore_errors=True)
    configured = override_settings(MEDIA_ROOT=context.attachment_media)
    configured.enable()
    context.add_cleanup(configured.disable)
    context.response = context.client.get(reverse("assignment_list"))
    assert context.response.status_code == 200
    assert "Canvas Project 1" in context.response.content.decode()


def submit_attachment_batch(context, files):
    """POST the public multipart contract, following the user-visible result."""
    context.response = context.client.post(
        reverse("upload_attachments", kwargs={"course_id": 42, "assignment_id": 101}),
        {"files": files}, follow=True,
    )
    assert context.response.status_code == 200


@when("I upload a file(s) larger than 25 MB")
def step_upload_oversized_attachment_batch(context):
    submit_attachment_batch(context, [
        SimpleUploadedFile("first.bin", b"a" * 13_107_200),
        SimpleUploadedFile("second.bin", b"b" * 13_107_201),
    ])


@then("no file is attached")
def step_no_attachment_saved(context):
    assert Assignment.objects.count() == 0
    assert StudyFile.objects.count() == 0
    assert Attachment.objects.count() == 0
    assert not any(path.is_file() for path in Path(context.attachment_media).rglob("*"))


@given("I have attached several study files to the assignment")
@when("I attach several study files to the assignment")
def step_attach_several_study_files(context):
    submit_attachment_batch(context, [
        SimpleUploadedFile("lecture-notes.txt", b"lecture notes"),
        SimpleUploadedFile("project-rubric.pdf", b"project rubric"),
    ])


@when("I sign in again")
def step_sign_in_again_for_attachments(context):
    context.client.logout()
    assert context.client.login(
        username="canvas-student", password="attachment-behave-password",
    )
    context.response = context.client.get(reverse("assignment_list"))


@then("I see my study files listed on that assignment")
def step_study_files_listed_on_assignment(context):
    assert context.response.status_code == 200
    cards = BeautifulSoup(context.response.content, "html.parser").select("li.assignment-card")
    card = next(card for card in cards if "Canvas Project 1" in card.get_text())
    assert "lecture-notes.txt" in card.get_text()
    assert "project-rubric.pdf" in card.get_text()
    assert Assignment.objects.filter(user=context.user, canvas_assignment_id=101).count() == 1
    assert Attachment.objects.filter(user=context.user).count() == 2
