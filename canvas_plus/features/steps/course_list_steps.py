"""Behavior steps for the current course list."""
# pylint: disable=import-error,missing-function-docstring,not-callable,duplicate-code

from unittest.mock import Mock, patch

from behave import given, when, then
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import Client, override_settings
from django.urls import reverse

from accounts.canvas_client import CanvasAPIError, CanvasAuthenticationError
from accounts.models import CanvasConnection

CURRENT_COURSE = {
    "id": 1,
    "name": "Operating Systems I",
    "term": {"end_at": "2099-01-01T00:00:00Z"},
}
ENDED_COURSE = {
    "id": 2,
    "name": "Programming with UNIX",
    "term": {"end_at": "2000-01-01T00:00:00Z"},
}


def connect_student(context):
    """Sign in a student with a saved Canvas connection and fake Canvas courses."""
    configured = override_settings(
        CANVAS_BASE_URL="https://canvas.example.edu",
        CANVAS_TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode(),
    )
    configured.enable()
    context.add_cleanup(configured.disable)
    user = get_user_model().objects.create_user(username="course-student")
    context.connection = CanvasConnection(user=user, canvas_url="https://canvas.example.edu")
    context.connection.set_token("fake-behave-canvas-token")
    context.connection.save()
    context.client = Client()
    context.client.force_login(user)
    context.canvas_courses = Mock(return_value=[])
    patcher = patch("courses.views.list_courses", context.canvas_courses)
    patcher.start()
    context.add_cleanup(patcher.stop)


@given("my Canvas account is connected")
def step_canvas_connected(context):
    connect_student(context)


@given("I am enrolled in a course this semester and a course from a past semester")
def step_current_and_past_course(context):
    context.canvas_courses.return_value = [CURRENT_COURSE, ENDED_COURSE]


@given("I have no current courses")
def step_no_current_courses(context):
    context.canvas_courses.return_value = [ENDED_COURSE]


@given("my Canvas account is not connected")
def step_canvas_not_connected(context):
    connect_student(context)
    context.connection.delete()


@given("my Canvas connection has expired")
def step_canvas_connection_expired(context):
    connect_student(context)
    context.canvas_courses.side_effect = CanvasAuthenticationError("Rejected")


@given("Canvas is down")
def step_canvas_down(context):
    connect_student(context)
    context.canvas_courses.side_effect = CanvasAPIError("Down")


@when("I open Courses from the sidebar")
def step_open_courses_from_sidebar(context):
    url = reverse("course_list")
    context.response = context.client.get(url)
    assert f'href="{url}"' in context.response.content.decode()  # sidebar links here


@when("I open Courses")
def step_open_courses(context):
    context.response = context.client.get(reverse("course_list"))


@then("I see this semester's course")
def step_see_current_course(context):
    assert CURRENT_COURSE["name"] in context.response.content.decode()


@then("I don't see the past semester's course")
def step_not_see_past_course(context):
    assert ENDED_COURSE["name"] not in context.response.content.decode()


# Course page with syllabus

FORMATTED_SYLLABUS = (
    "<h4>Grading</h4><ul><li>Quizzes 10%</li></ul><table><tr><td>Week 1</td></tr></table>"
)
FILE_SYLLABUS = (
    '<p>Syllabus: <a class="instructure_file_link" title="syllabus.pdf" '
    'href="https://canvas.example.edu/courses/1/files/9?wrap=1">syllabus.pdf</a></p>'
)
SCRIPT_SYLLABUS = "<p>Grading policy</p><script>alert('x')</script>"


def course_with_syllabus(context, syllabus):
    """A connected student enrolled in one current course whose syllabus Canvas returns."""
    connect_student(context)
    context.canvas_courses.return_value = [CURRENT_COURSE]
    patcher = patch("courses.views.get_course_syllabus", Mock(return_value=syllabus))
    patcher.start()
    context.add_cleanup(patcher.stop)


def page(context):
    return context.response.content.decode()


@given("my course has a syllabus with headings, lists, and tables")
def step_formatted_syllabus(context):
    course_with_syllabus(context, FORMATTED_SYLLABUS)


@given("my course syllabus links to a file in Canvas")
def step_file_syllabus(context):
    course_with_syllabus(context, FILE_SYLLABUS)


@given("my course has no syllabus in Canvas")
def step_no_syllabus(context):
    course_with_syllabus(context, None)


@given("my course has a blank syllabus")
def step_blank_syllabus(context):
    course_with_syllabus(context, "<p>&nbsp;</p>")


@given("a course syllabus in Canvas contains a script")
def step_script_syllabus(context):
    course_with_syllabus(context, SCRIPT_SYLLABUS)


@given("I am not enrolled in that course")
def step_not_enrolled(context):
    course_with_syllabus(context, FORMATTED_SYLLABUS)
    context.course_id = 999


@when("I select that course from my course list")
def step_select_course(context):
    url = reverse("course_detail", args=[CURRENT_COURSE["id"]])
    assert f'href="{url}"' in context.client.get(reverse("course_list")).content.decode()
    context.response = context.client.get(url)


@when("I open that course")
def step_open_course(context):
    course_id = getattr(context, "course_id", CURRENT_COURSE["id"])
    context.response = context.client.get(reverse("course_detail", args=[course_id]))


@then("I see a page titled with the course name")
def step_course_title(context):
    assert f"<h1>{CURRENT_COURSE['name']}</h1>" in page(context)


@then("I see the syllabus with its headings, lists, and tables")
def step_formatted_syllabus_shown(context):
    for part in ("<h4>Grading</h4>", "<li>Quizzes 10%</li>", "<td>Week 1</td>"):
        assert part in page(context)


@then("I can go back to my course list")
def step_back_link(context):
    assert f'<a href="{reverse("course_list")}">← All courses</a>' in page(context)


@then("I see the file's name")
def step_file_name(context):
    assert "syllabus.pdf" in page(context)


@then("nothing on the page takes me to Canvas")
def step_no_canvas_links(context):
    assert 'href="https://canvas.example.edu' not in page(context)


@then("I see the syllabus text")
def step_syllabus_text(context):
    assert "Grading policy" in page(context)


@then("the script does not run")
def step_script_removed(context):
    assert "alert(" not in page(context)  # the sidebar has its own <script>, so check the payload


# Syllabus files

WORD_SYLLABUS = (
    '<p>Notes: <a class="instructure_file_link" title="notes.docx" '
    'href="https://canvas.example.edu/courses/1/files/10?wrap=1">notes.docx</a></p>'
)


def course_with_file(context, syllabus, file_id, size=184910, error=None):
    """A course whose syllabus links one file, with Canvas's file requests faked."""
    course_with_syllabus(context, syllabus)
    context.file_url = reverse("course_file", args=[CURRENT_COURSE["id"], file_id])
    info = {"name": "syllabus.pdf" if file_id == 9 else "notes.docx", "size": size, "url": "x"}
    context.canvas_file = Mock(return_value=info, side_effect=error)
    opened = Mock()
    opened.iter_content.return_value = [b"file bytes"]
    for target, fake in (
        ("courses.views.get_course_file", context.canvas_file),
        ("courses.views.download_course_file", Mock(return_value=b"%PDF-1.7 pages")),
        ("courses.views.open_course_file", Mock(return_value=opened)),
    ):
        patcher = patch(target, fake)
        patcher.start()
        context.add_cleanup(patcher.stop)


def download(context):
    """Follow a file's download link the way a student's browser would."""
    response = context.client.get(context.file_url + "?download=1")
    assert response["Content-Disposition"].startswith("attachment")
    return response


@given("my course syllabus links to a PDF in Canvas")
def step_pdf_in_syllabus(context):
    course_with_file(context, FILE_SYLLABUS, 9)


@given("my course syllabus links to a Word file in Canvas")
def step_word_file_in_syllabus(context):
    course_with_file(context, WORD_SYLLABUS, 10)


@given("my course syllabus links to a PDF over 25 MB")
def step_large_pdf_in_syllabus(context):
    course_with_file(context, FILE_SYLLABUS, 9, size=26 * 1024 * 1024)


@given("a linked file was deleted, is locked by my professor, or Canvas is down")
def step_file_cant_be_loaded(context):
    course_with_file(context, FILE_SYLLABUS, 9, error=CanvasAPIError("Locked"))


@given("a file belongs to a course not in my current list")
def step_file_from_another_course(context):
    course_with_file(context, FILE_SYLLABUS, 9)
    context.file_url = reverse("course_file", args=[999, 9])


@when("I open that course and expand the file")
@when("I expand the file")
def step_expand_file(context):
    # Opening the dropdown makes the browser load the viewer's address, so load it the same way.
    context.course_page = context.client.get(
        reverse("course_detail", args=[CURRENT_COURSE["id"]])
    ).content.decode()
    assert f'<iframe src="{context.file_url}"' in context.course_page
    context.response = context.client.get(context.file_url)


@when("I try to open it")
def step_try_to_open_file(context):
    context.response = context.client.get(context.file_url)


@when("I try to download it")
def step_try_to_download_file(context):
    context.response = context.client.get(context.file_url + "?download=1")


@then("I see the PDF on the course page")
def step_pdf_shown(context):
    assert context.response["Content-Type"] == "application/pdf"
    assert context.response["X-Frame-Options"] == "SAMEORIGIN"


@then("I can download the Word file from the syllabus")
def step_word_file_download_link(context):
    assert f'href="{context.file_url}?download=1"' in page(context)


@then("downloading it doesn't take me to Canvas")
def step_word_download_stays_in_canvas_plus(context):
    assert 'href="https://canvas.example.edu' not in page(context)
    assert download(context)["Content-Disposition"] == 'attachment; filename="notes.docx"'


@then("I can download it without going to Canvas")
def step_download_from_viewer(context):
    assert 'href="?download=1"' in page(context)
    download(context)


@then("the rest of the course page still shows")
def step_course_page_still_shows(context):
    assert f"<h1>{CURRENT_COURSE['name']}</h1>" in context.course_page
    assert "Syllabus:" in context.course_page


@then("I can go back to the course")
def step_back_to_course(context):
    course_url = reverse("course_detail", args=[CURRENT_COURSE["id"]])
    assert f'<a href="{course_url}">← Back to course</a>' in page(context)


@then("Canvas is never asked for it")
def step_file_never_requested(context):
    context.canvas_file.assert_not_called()
