"""Acceptance steps for the per-course assignments summary."""
# pylint: disable=import-error,missing-function-docstring,not-callable
from datetime import datetime, timezone
from unittest.mock import patch

from behave import given, when, then
from bs4 import BeautifulSoup
from django.urls import reverse

from features.steps.course_list_steps import connect_student


def prepare_summary(context):
    """Arrange live Canvas responses for the selected course."""
    context.canvas_courses.return_value = [{"id": 1, "name": "CS 4300"}]
    for name, result in (("get_course_syllabus", None), ("list_all_assignments", [])):
        patcher = patch(f"courses.views.{name}", return_value=result)
        mock = patcher.start()
        context.add_cleanup(patcher.stop)
        if name == "list_all_assignments":
            context.summary_assignments = mock


def assignment(title, year=2099, score=None):
    return {"title": title, "due_date": datetime(year, 1, 2, 18, 30, tzinfo=timezone.utc),
            "score": score, "points_possible": 100}


@given("I am on the Course Hub with CS 4300 selected")
@given("I am on the Course Hub with a course selected")
def selected_course(context):
    connect_student(context)
    prepare_summary(context)


@given("CS 4300 has upcoming assignments")
def upcoming_assignments(context):
    prepare_summary(context)
    context.summary_assignments.return_value = [assignment("Project"), assignment("Quiz")]


@given("CS 4300 has at least one past or graded assignment")
def past_assignments(context):
    context.summary_assignments.return_value = [assignment("Exam", 2000, 92)]


@given("CS 4300 has 12 assignments")
def twelve_assignments(context):
    context.summary_assignments.return_value = [assignment(f"Task {i}") for i in range(12)]


@given("that course has no upcoming assignments")
def no_upcoming(context):
    context.summary_assignments.return_value = []


@when("I open the Course Hub")
@when("the CS 4300 tab and the Upcoming toggle are selected")
@when("the Upcoming toggle is selected")
@when("the assignments summary is shown")
def open_summary(context):
    context.response = context.client.get(reverse("course_detail", args=[1]))


@when("I click the Past/Graded toggle")
def open_past(context):
    context.response = context.client.get(reverse("course_detail", args=[1]), {"view": "past"})


@then("I see those CS 4300 assignments listed")
def see_upcoming(context):
    page = context.response.content.decode()
    assert "Project" in page and "Quiz" in page


@then("I see the due date for each item")
def see_due_dates(context):
    dates = BeautifulSoup(context.response.content, "html.parser").select(".assignment-list time")
    assert len(dates) == 2
    assert all(date.get_text() == "Jan 2, 2099 11:30 AM" for date in dates)


@then("I see those past or graded CS 4300 assignments")
def see_past(context):
    assert "Exam" in context.response.content.decode()


@then("I see the score next to each graded item")
def see_score(context):
    assert "92 / 100" in context.response.content.decode()


@then('I see a "View all 12 assignments" link')
def see_view_all(context):
    page = BeautifulSoup(context.response.content, "html.parser")
    link = page.find("a", string="View all 12 assignments")
    assert link is not None
    assert link["href"] == "?view=upcoming&all=1"  # in-page: the student stays in Canvas+


@then('I see "No upcoming assignments"')
def see_empty(context):
    assert "No upcoming assignments" in context.response.content.decode()
