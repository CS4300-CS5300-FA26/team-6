"""Executable issue #143 scenarios for the This Week panel on the dashboard."""
# Behave decorators are callable; pylint cannot infer their dynamic registration.
# pylint: disable=not-callable,missing-function-docstring,import-error

import re
from datetime import datetime, time, timedelta

from behave import given, then
from django.contrib.auth import get_user_model
from django.utils import timezone

from accounts.canvas_client import CanvasAPIError
from assignments.models import Assignment

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
COURSE_ID, COURSE_NAME = 42, "CS 4300"  # the course prepare_student fakes
DEFAULT_CLOCK = time(17, 0)
UNAVAILABLE_MESSAGE = "This Week cannot be loaded right now."
WHEN = re.compile(r"(?:at (\d{1,2}:\d\d [AP]M) )?(this|last|next) (\w+)")


def due_at(when):
    """Denver-local datetime for "this Tuesday", "next Monday" or "at 11:30 PM this Sunday"."""
    match = WHEN.fullmatch(when)
    assert match, f"cannot read the due date {when!r}"
    clock, week, day_name = match.groups()
    today = timezone.localdate()
    monday = today - timedelta(days=today.weekday())
    offset = {"last": -7, "this": 0, "next": 7}[week]
    day = monday + timedelta(days=offset + DAYS.index(day_name))
    at = datetime.strptime(clock, "%I:%M %p").time() if clock else DEFAULT_CLOCK
    return timezone.make_aware(datetime.combine(day, at))


def add_canvas_assignment(context, title, due_date):
    """Make the faked Canvas return this assignment, so the real sync saves it."""
    context.week_assignments.append({
        "canvas_assignment_id": 1000 + len(context.week_assignments),
        "canvas_course_id": COURSE_ID,
        "title": title,
        "course_name": COURSE_NAME,
        "due_date": due_date,
        "submitted": False,
    })


def page(context):
    return context.response.content.decode()


def week_days(context):
    """{"Monday": that day's HTML, ...} for each day section of This Week, in page order."""
    sections = re.findall(
        r'<section class="week-day" aria-label="(\w+)">(.*?)</section>', page(context), re.S
    )
    return dict(sections)


# Givens

@given("I am a student with a connected Canvas account")
def step_connected(context):
    context.execute_steps("Given I am a connected student with no upcoming coursework")
    # The fake returns this same list object, so later Givens can append to it.
    context.week_assignments = []
    context.canvas_all_assignments.return_value = context.week_assignments


@given("I have an assignment \"{title}\" due {when}")
def step_assignment_due(context, title, when):
    add_canvas_assignment(context, title, due_at(when))


@given("I have an assignment \"{title}\" with no due date")
def step_assignment_undated(context, title):
    add_canvas_assignment(context, title, None)


@given("I have no assignments due this Saturday")
def step_nothing_on_saturday(context):
    saturday = due_at("this Saturday").date()
    due_dates = [a["due_date"] for a in context.week_assignments if a["due_date"]]
    assert all(timezone.localdate(d) != saturday for d in due_dates), "something is due Saturday"


@given("another student has an assignment \"{title}\" due {when}")
def step_other_students_assignment(_context, title, when):
    other = get_user_model().objects.create_user(username="other-student")
    Assignment.objects.create(
        user=other, title=title, course=COURSE_NAME, due_date=due_at(when),
        canvas_course_id=COURSE_ID, canvas_assignment_id=9001, sync_state="synced",
    )


@given("an assignment \"{title}\" due {when} was removed from Canvas")
def step_removed_assignment(context, title, when):
    # Saved earlier but no longer returned by Canvas, so the real sync marks it missing.
    Assignment.objects.create(
        user=context.user, title=title, course=COURSE_NAME, due_date=due_at(when),
        canvas_course_id=COURSE_ID, canvas_assignment_id=9002, sync_state="synced",
    )


@given("syncing my Canvas assignments fails")
def step_sync_fails(context):
    context.canvas_all_assignments.side_effect = CanvasAPIError("down")


# Thens

@then("I see a This Week section with columns for Monday through Sunday")
def step_week_columns(context):
    shown = list(week_days(context))
    assert shown == DAYS, f"no This Week section with Monday through Sunday, got {shown}"


@then("This Week shows \"{title}\" on {day}")
def step_week_shows(context, title, day):
    days = week_days(context)
    assert day in days, f"no {day} in This Week"
    assert title in days[day], f"{title} is not on {day} in This Week"


@then("This Week does not show \"{title}\"")
def step_week_does_not_show(context, title):
    shown_on = [day for day, html in week_days(context).items() if title in html]
    assert not shown_on, f"{title} is shown on {shown_on}"


@then("This Week shows {day} with no assignments")
def step_week_day_empty(context, day):
    days = week_days(context)
    assert day in days, f"no {day} in This Week"
    assert "week-chip" not in days[day], f"{day} has assignments in This Week"


@then("I see Upcoming Assignments, then Recently Graded, then the This Week calendar")
def step_dashboard_order(context):
    headings = ["<h2>Upcoming Assignments</h2>", "<h2>Recently Graded</h2>", "<h2>This Week</h2>"]
    missing = [h for h in headings if h not in page(context)]
    assert not missing, f"missing headings: {missing}"
    positions = [page(context).index(h) for h in headings]
    assert positions == sorted(positions), "sections are not in wireframe order"


@then("I am told This Week cannot be loaded right now")
def step_week_unavailable(context):
    assert UNAVAILABLE_MESSAGE in page(context), "This Week unavailable message not shown"
    assert not week_days(context), "an empty week is shown alongside the message"


@then("I do not see the This Week calendar")
def step_no_week(context):
    assert 'class="this-week"' not in page(context), "This Week calendar is shown"
