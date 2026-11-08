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
