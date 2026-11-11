"""Behavior steps for the current course list."""
# pylint: disable=import-error,missing-function-docstring,not-callable,duplicate-code

from unittest.mock import Mock, patch

from behave import given, when, then
from bs4 import BeautifulSoup
from cryptography.fernet import Fernet
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, override_settings
from django.urls import reverse

from accounts.canvas_client import CanvasAPIError, CanvasAuthenticationError, list_courses
from accounts.models import CanvasConnection
from courses.test_hub_helpers import (
    active_hub_courses,
    course_links,
    excluded_hub_courses,
    hub_cache_clock,
    hub_course,
    install_hub_canvas,
)

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
    '<p>Syllabus: <a class="instructure_file_link" '
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


# Issue #137: tests only; course navigation and assignments await implementation.

@given("I am a connected Course Hub student")
def step_hub_student(context):
    connect_student(context)
    # Keep the existing connection setup but exercise the real Canvas client
    # against a fake HTTP service, including its active-student query filters.
    context.canvas_courses.side_effect = list_courses
    context.hub_active = active_hub_courses()
    context.hub_excluded = excluded_hub_courses()
    context.hub_canvas = install_hub_canvas(
        context.add_cleanup, context.hub_active + context.hub_excluded,
    )


@given("Canvas also has ended, concluded, invited, and teacher courses")
def step_hub_excluded_courses(context):
    assert all(course in context.hub_canvas.courses for course in context.hub_excluded)


@given("every course has distinct upcoming assignments")
def step_hub_assignments(context):
    titles = [assignment["name"] for assignments in context.hub_canvas.assignments.values()
              for assignment in assignments]
    assert len(titles) == len(context.hub_canvas.courses)
    assert len(set(titles)) == len(titles)


@given("I have zero active Course Hub courses")
def step_hub_zero_courses(context):
    context.hub_canvas.courses = context.hub_excluded


@given("I have twenty-one active Course Hub courses")
def step_hub_twenty_one_courses(context):
    context.hub_canvas.courses = [
        hub_course(50000 + index, f"CS {index}", f"Course {index}") for index in range(21)
    ]


@when("I open the Course Hub dashboard")
def step_open_hub(context):
    context.response = context.client.get(reverse("course_list"))
    assert context.response.status_code == 200


@then("I see exactly these Course Hub tabs")
def step_hub_tabs(context):
    links = course_links(context.response, context.hub_canvas.courses)
    actual = [link.get_text(strip=True) for link in links]
    expected = [row["course_code"] for row in context.table]
    assert sorted(actual) == sorted(expected), (actual, expected)


@then("the excluded courses have no dashboard entry")
def step_hub_excluded_entries(context):
    assert not course_links(context.response, context.hub_excluded)
    for course in context.hub_excluded:
        assert course["name"] not in page(context)
        assert course["course_code"] not in page(context)


@then("opening any excluded course shows Course not found")
def step_hub_excluded_pages(context):
    for course in context.hub_excluded:
        response = context.client.get(reverse("course_detail", args=[course["id"]]))
        assert response.status_code == 404
        assert "Course not found" in response.content.decode()


@then("each short-code tab links to its Canvas course ID and opens its matching heading")
def step_hub_destinations(context):
    links = course_links(context.response, context.hub_canvas.courses)
    for course in context.hub_active:
        matching = [link for link in links if link.get_text(strip=True) == course["course_code"]]
        assert len(matching) == 1, f"Expected one tab for {course['course_code']}"
        assert matching[0]["href"] == reverse("course_detail", args=[course["id"]])
        response = context.client.get(matching[0]["href"])
        assert response.status_code == 200
        heading = BeautifulSoup(response.content, "html.parser").select_one("main h1")
        assert heading is not None
        assert heading.get_text(strip=True) == course["name"]


@when("I visit each active course page")
def step_hub_visit_course_pages(context):
    context.hub_pages = {
        course["id"]: context.client.get(reverse("course_detail", args=[course["id"]]))
        for course in context.hub_active
    }


@then("each page shows only that course's upcoming assignments")
def step_hub_course_assignments(context):
    for course_id, response in context.hub_pages.items():
        assert response.status_code == 200
        for owner_id, assignments in context.hub_canvas.assignments.items():
            for assignment in assignments:
                assert (assignment["name"] in response.content.decode()) == (owner_id == course_id)


@then("I see upcoming assignments from every active course only")
def step_hub_all_assignments(context):
    active_ids = {course["id"] for course in context.hub_active}
    for owner_id, assignments in context.hub_canvas.assignments.items():
        for assignment in assignments:
            assert (assignment["name"] in page(context)) == (owner_id in active_ids)


@then("the Course Hub shows No current courses found and no course tabs")
def step_hub_empty_message(context):
    assert "No current courses found" in page(context)
    assert not course_links(context.response, context.hub_canvas.courses)


@then("I see exactly twenty distinct course tabs")
def step_hub_tab_cap(context):
    links = course_links(context.response, context.hub_canvas.courses)
    assert len(links) == 20, f"Expected 20 course tabs, got {len(links)}"
    assert len({link["href"] for link in links}) == 20


@given("Course Hub course caching is enabled")
def step_hub_cache_enabled(context):
    configured = override_settings(CACHES=settings.LOCMEM_CACHE)
    configured.enable()
    context.add_cleanup(configured.disable)
    cache.clear()
    context.add_cleanup(cache.clear)
    context.hub_cache_key = (
        f"canvas-courses:{context.connection.pk}:{context.connection.updated_at.timestamp()}"
    )
    context.hub_clock = hub_cache_clock(context.add_cleanup)


@given("my courses are already cached under the assignments-page key")
def step_hub_cache_seeded(context):
    cache.set(context.hub_cache_key, context.hub_active, 3600)


@when("I reopen the Course Hub just before an hour has passed")
def step_hub_cache_within_hour(context):
    context.hub_clock.return_value += 3599
    step_open_hub(context)


@then("Canvas has been asked for courses only once")
def step_hub_one_course_call(context):
    assert context.hub_canvas.course_calls == 1, context.hub_canvas.course_calls


@then("the courses are stored under the shared course-list cache key")
def step_hub_shared_cache_key(context):
    assert cache.get(context.hub_cache_key) is not None


@when("I reopen the Course Hub after the hour has passed")
def step_hub_cache_expired(context):
    context.hub_clock.return_value += 2
    step_open_hub(context)


@then("Canvas has been asked for courses twice")
def step_hub_two_course_calls(context):
    assert context.hub_canvas.course_calls == 2, context.hub_canvas.course_calls


@then("Canvas has not been asked for courses")
def step_hub_no_course_call(context):
    assert context.hub_canvas.course_calls == 0, context.hub_canvas.course_calls
