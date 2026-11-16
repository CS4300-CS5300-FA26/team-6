"""Behavior steps for the current grade on a course page."""
# pylint: disable=import-error,missing-function-docstring,not-callable

from behave import given, then
from bs4 import BeautifulSoup

from accounts.canvas_client import CanvasAPIError

GRADES = {
    "97.41 with no letter": (97.41, None),
    "95.69 with letter A": (95.69, "A"),
    "0 with no letter": (0, None),
    "letter A with no score": (None, "A"),
}


def course_with_grade(context, score, letter=None, hidden=False):
    """One current course with a syllabus, where Canvas has this grade for me."""
    context.execute_steps("Given my course has a syllabus with headings, lists, and tables")
    context.canvas_grade.return_value = {
        "hide_final_grades": hidden,
        "enrollments": [{"type": "student", "computed_current_score": score,
                         "computed_current_grade": letter}],
    }


@given("Canvas has my current grade for a course as {grade}")
def step_current_grade(context, grade):
    course_with_grade(context, *GRADES[grade])


@given("nothing in my course has been graded yet")
def step_nothing_graded(context):
    course_with_grade(context, None)


@given("my instructor hides the course total")
def step_hidden_total(context):
    course_with_grade(context, 97.41, "A", hidden=True)


@given("Canvas can't send my grade right now")
def step_grade_unavailable(context):
    course_with_grade(context, None)
    context.canvas_grade.side_effect = CanvasAPIError("Down")


@then('my grade reads "{text}"')
def step_grade_reads(context, text):
    line = BeautifulSoup(context.response.content, "html.parser").find(class_="current-grade")
    assert line is not None and line.get_text(strip=True) == text
