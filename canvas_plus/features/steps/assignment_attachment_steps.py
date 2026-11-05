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
    assert Assignment.objects.filter(
        user=context.user,
        canvas_assignment_id=101,
    ).count() == 1
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


@given("a document is linked to an assignment block")
@given("several files are connected to a single deadline")
@given("a resource is saved on a calendar assignment")
def step_saved_attachment_resources(context):
    step_viewing_attachment_deadline(context)
    step_attach_several_study_files(context)
    context.target_attachment = Attachment.objects.get(
        user=context.user, study_file__original_name="lecture-notes.txt",
    )


@when("I click on the document from the calendar entry")
def step_open_attachment_from_card(context):
    page = BeautifulSoup(context.response.content, "html.parser")
    link = page.find("a", string="lecture-notes.txt")
    assert link is not None
    context.response = context.client.get(link["href"])


@then("I can preview or download the resource immediately")
def step_attachment_downloaded(context):
    assert context.response.status_code == 200
    assert context.response["Content-Disposition"] == 'attachment; filename="lecture-notes.txt"'
    assert b"".join(context.response.streaming_content) == b"lecture notes"
    context.response.close()


@when("I unbind a single target resource")
def step_remove_target_attachment(context):
    url = reverse("remove_attachment", kwargs={"attachment_id": context.target_attachment.pk})
    confirmation = context.client.get(url)
    assert confirmation.status_code == 200
    assert "lecture-notes.txt" in confirmation.content.decode()
    context.response = context.client.post(url, follow=True)


@then("that specific item is removed from the view")
def step_target_attachment_removed(context):
    assert context.response.status_code == 200
    assert "lecture-notes.txt" not in context.response.content.decode()
    assert not Attachment.objects.filter(pk=context.target_attachment.pk).exists()
    study_file = StudyFile.objects.get(pk=context.target_attachment.study_file_id)
    assert Path(study_file.file.path).read_bytes() == b"lecture notes"


@then("all other linked materials stay attached to the task")
def step_other_attachments_remain(context):
    assert "project-rubric.pdf" in context.response.content.decode()
    assert Attachment.objects.filter(
        assignment=context.target_attachment.assignment,
        study_file__original_name="project-rubric.pdf",
    ).count() == 1
    assert Assignment.objects.filter(pk=context.target_attachment.assignment_id).exists()


@when("I start removing the item but dismiss the prompt")
def step_cancel_attachment_removal(context):
    page = BeautifulSoup(context.response.content, "html.parser")
    remove = page.find("a", href=reverse(
        "remove_attachment", kwargs={"attachment_id": context.target_attachment.pk},
    ))
    assert remove is not None
    confirmation = context.client.get(remove["href"])
    assert confirmation.status_code == 200
    page = BeautifulSoup(confirmation.content, "html.parser")
    cancel = page.find("a", string="Cancel")
    assert cancel is not None
    context.response = context.client.get(cancel["href"])


@then("the document remains present on the record card")
def step_cancelled_attachment_remains(context):
    step_study_files_listed_on_assignment(context)
    assert Attachment.objects.filter(pk=context.target_attachment.pk).exists()


@given("a task contains zero uploaded files")
def step_task_without_uploaded_files(context):
    step_viewing_attachment_deadline(context)
    assert Assignment.objects.filter(
        user=context.user,
        canvas_assignment_id=101,
    ).count() == 1
    assert StudyFile.objects.count() == 0
    assert Attachment.objects.count() == 0


@when("I open the task record card")
def step_open_task_record_card(context):
    context.response = context.client.get(reverse("assignment_list"))
    assert context.response.status_code == 200


@then("I see no file attachments listed for that entry")
def step_no_attachments_listed_on_card(context):
    assert context.response.status_code == 200
    page = BeautifulSoup(context.response.content, "html.parser")
    cards = [
        card for card in page.select("li.assignment-card")
        if "Canvas Project 1" in card.get_text()
    ]
    assert len(cards) == 1, 'Expected one card for "Canvas Project 1"'
    card = cards[0]
    assert card.select_one(".assignment-attachments") is None, (
        "Assignment card unexpectedly lists attachments"
    )
    upload_form = card.find(
        "form",
        action=reverse(
            "upload_attachments", kwargs={"course_id": 42, "assignment_id": 101},
        ),
    )
    assert upload_form is not None, "Upload form is missing from the assignment card"
    assert upload_form.find("input", attrs={"name": "files"}) is not None
    assert Assignment.objects.filter(
        user=context.user,
        canvas_assignment_id=101,
    ).count() == 1, "Canvas assignment was not synchronized"
    assert StudyFile.objects.count() == 0, "Viewing created a StudyFile row"
    assert Attachment.objects.count() == 0, "Viewing created an Attachment row"
