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
