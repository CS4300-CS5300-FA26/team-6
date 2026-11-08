"""Executable issue #52 scenarios for the study plan on the availability page."""
# Behave decorators are callable; pylint cannot infer their dynamic registration.
# pylint: disable=not-callable,missing-function-docstring,import-error

import re
from datetime import datetime, timedelta

from behave import given, when, then
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from assignments.models import Assignment
from study_plan.models import StudyPlan, StudySession

NO_PLAN_MESSAGE = "No study plan has been generated yet."
INVALID_DAY_MESSAGE = "That day is not a valid date."
EMPTY_DAY_MESSAGE = "No study sessions on this day."
EMPTY_PLAN_MESSAGE = "Your study plans have no sessions."
DEFAULT_DAY, DEFAULT_START, DEFAULT_END = "2026-11-05", "2:00 PM", "3:00 PM"


def my_plan(context):
    """The current student's most recent plan, created on first use so sessions share it."""
    if not hasattr(context, "plan"):
        context.plan = StudyPlan.objects.create(user=context.user)
    return context.plan


def at(day, clock):
    """A Denver-local aware datetime from "2026-11-05" and "2:00 PM"."""
    return timezone.make_aware(datetime.strptime(f"{day} {clock}", "%Y-%m-%d %I:%M %p"))


def add_session(plan, title, day=DEFAULT_DAY, start=DEFAULT_START, end=DEFAULT_END):
    assignment, _ = Assignment.objects.get_or_create(
        user=plan.user,
        title=title,
        defaults={
            "course": "CS4300",
            "canvas_course_id": 1,
            "canvas_assignment_id": Assignment.objects.count() + 1,
        },
    )
    StudySession.objects.create(
        plan=plan, assignment=assignment, start=at(day, start), end=at(day, end)
    )


def shown_day(day):
    """How the page writes a day: "2026-11-05" becomes "Nov 5, 2026"."""
    d = datetime.strptime(day, "%Y-%m-%d")
    return f"{d:%b} {d.day}, {d.year}"


def session_cards(context):
    html = context.response.content.decode()
    return re.findall(r'<li class="assignment-card study-session">(.*?)</li>', html, re.S)


def assert_session_shown(context, title, *details):
    cards = session_cards(context)
    assert any(title in card and all(d in card for d in details) for card in cards), (
        f"no session card found for {title} {' '.join(details)}"
    )


# Givens

@given("my most recent study plan has a session for \"{title}\" on {day} from {start} to {end}")
def step_session_at(context, title, day, start, end):
    add_session(my_plan(context), title, day, start, end)


@given("my most recent study plan has a session for \"{title}\"")
def step_session(context, title):
    add_session(my_plan(context), title)


@given("my most recent study plan has a session for \"{title}\" today")
def step_session_today(context, title):
    add_session(my_plan(context), title, day=timezone.localdate().isoformat())


@given("my most recent study plan has no sessions")
def step_plan_without_sessions(context):
    my_plan(context)


@given("I had an older study plan with a session for \"{title}\"")
def step_older_plan(context, title):
    # Not stored on context.plan, so my_plan() still creates the most recent one.
    older = StudyPlan.objects.create(user=context.user)
    StudyPlan.objects.filter(pk=older.pk).update(created_at=timezone.now() - timedelta(days=7))
    add_session(older, title)


@given("another student made a study plan after mine with a session for \"{title}\"")
def step_other_students_plan(context, title):
    other = get_user_model().objects.create_user(username="other-student")
    theirs = StudyPlan.objects.create(user=other)
    later = my_plan(context).created_at + timedelta(hours=1)
    StudyPlan.objects.filter(pk=theirs.pk).update(created_at=later)
    add_session(theirs, title)


@given("I have not generated a study plan")
def step_no_plan(context):
    assert not StudyPlan.objects.filter(user=context.user).exists(), "student already has a plan"


# Whens

@when("I open my availability page")
def step_open_availability(context):
    context.response = context.client.get(reverse("availability:list"))


@when("I open my availability page for all days")
def step_open_availability_all_days(context):
    context.response = context.client.get(reverse("availability:list"), {"date": ""})


@when("I open my availability page for \"{day}\"")
def step_open_availability_for_day(context, day):
    context.response = context.client.get(reverse("availability:list"), {"date": day})


@when("I open Study Plan from the sidebar")
def step_open_study_plan_from_sidebar(context):
    url = reverse("availability:list")
    context.response = context.client.get(url)
    sidebar = re.search(r"<nav[^>]*>(.*?)</nav>", context.response.content.decode(), re.S)
    link = f'href="{url}">Study Plan</a>'
    assert sidebar and link in sidebar.group(1), "sidebar has no Study Plan link"


# Thens

@then("I see a study session for \"{title}\" on {day} from {start} to {end}")
def step_see_session_at(context, title, day, start, end):
    assert_session_shown(context, title, shown_day(day), f"{start} to {end}")


@then("I see a study session for \"{title}\"")
def step_see_session(context, title):
    assert_session_shown(context, title)


@then("I do not see a study session for \"{title}\"")
def step_not_see_session(context, title):
    assert not any(title in card for card in session_cards(context)), f"{title} is shown"


@then("I see these study sessions:")
def step_see_sessions_table(context):
    for row in context.table:
        assert_session_shown(context, row["assignment"], row["time"])


@then("I am told I have no study plan yet")
def step_told_no_plan(context):
    assert NO_PLAN_MESSAGE in context.response.content.decode(), "no-study-plan message not shown"


@then("I am told that day is not a valid date")
def step_told_invalid_day(context):
    assert context.response.status_code == 200, f"page returned {context.response.status_code}"
    assert INVALID_DAY_MESSAGE in context.response.content.decode(), "invalid-day message not shown"


@then("I am told I have no study sessions that day")
def step_told_empty_day(context):
    assert EMPTY_DAY_MESSAGE in context.response.content.decode(), "empty-day message not shown"


@then("I am told my study plan has no sessions")
def step_told_empty_plan(context):
    assert EMPTY_PLAN_MESSAGE in context.response.content.decode(), "empty-plan message not shown"
