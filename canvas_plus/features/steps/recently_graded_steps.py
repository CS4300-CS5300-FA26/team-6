"""Executable issue #40 scenarios; Canvas grade data is faked."""
# Behave decorators are callable; pylint cannot infer their dynamic registration.
# pylint: disable=not-callable,missing-function-docstring,import-error

from datetime import timedelta
from unittest.mock import patch

from behave import given, when, then
from django.utils import timezone


def fake_graded_work(context, grades):
    """Make the dashboard receive `grades` instead of calling Canvas."""
    context.grades = grades
    replacement = patch("assignments.views.list_graded_submissions", return_value=grades)
    replacement.start()
    context.add_cleanup(replacement.stop)


def graded(title, score, days_ago):
    """One graded submission, shaped like list_graded_submissions' results."""
    return {
        "assignment": title,
        "course": "Software Engineering",
        "score": score,
        "graded_at": timezone.now() - timedelta(days=days_ago),
    }


def page(context):
    return context.response.content.decode()


def newest_first(grades):
    return sorted(grades, key=lambda grade: grade["graded_at"], reverse=True)


# Scenario 1: Student views newly evaluated coursework

@given("I have newly published assignment scores")
def step_new_scores(context):
    fake_graded_work(context, [graded("Sprint 1", 92.0, days_ago=1)])


@when("I navigate to the main dashboard")
def step_open_dashboard(context):
    # Follow the logged-in home redirect so this keeps working if the dashboard moves.
    context.response = context.client.get("/", follow=True)
    assert context.response.status_code == 200


@then("I see my recent grades listed")
def step_grades_listed(context):
    for grade in context.grades:
        assert grade["assignment"] in page(context)


@then("I see the earned score alongside each entry")
def step_scores_alongside(context):
    html = page(context)
    for grade in context.grades:
        start = html.index(grade["assignment"])
        card = html[start:html.index("</li>", start)]  # from the title to the end of its card
        assert f'{grade["score"]:g}' in card, f'no score in the card for {grade["assignment"]}'


# Scenario 2: Multiple coursework items are evaluated

@given("I have multiple newly published assignment scores")
def step_multiple_new_scores(context):
    # Deliberately out of order, so the dashboard must do the sorting.
    fake_graded_work(context, [
        graded("Test 1 Part A", 88.0, days_ago=3),
        graded("Sprint 1", 92.0, days_ago=1),
        graded("Sprint 0-3", 75.0, days_ago=6),
    ])


@then("I see all recent feedback sorted by evaluation time, newest first")
def step_sorted_newest_first(context):
    html = page(context)
    expected = [grade["assignment"] for grade in newest_first(context.grades)]
    assert all(title in html for title in expected), "a recent grade is missing"
    shown = sorted(expected, key=html.index)
    assert shown == expected, f"shown in order {shown}"


# Scenario 3: Student has no recent evaluations

@given("no new scores have been posted")
def step_no_new_scores(context):
    fake_graded_work(context, [])


# Scenario 4: Older grades are not shown as recent

@given("I have a score that was graded more than 14 days ago")
def step_old_score(context):
    context.old_grade = graded("Project Proposal", 81.0, days_ago=15)
    fake_graded_work(context, [context.old_grade])


@then("I do not see that assignment")
def step_old_score_hidden(context):
    assert context.old_grade["assignment"] not in page(context)
