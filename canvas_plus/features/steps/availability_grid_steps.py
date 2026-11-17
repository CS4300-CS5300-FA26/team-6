"""Behave steps for the weekly availability grid on the Study Plan page."""
# Behave decorators are callable; pylint cannot infer their dynamic registration.
# pylint: disable=not-callable,import-error,missing-function-docstring

import re
from datetime import datetime, timedelta
from unittest.mock import patch

from behave import given, when, then
from bs4 import BeautifulSoup
from django.contrib.auth import get_user_model
from django.urls import reverse

from availability.models import Availability

DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
GRID_HOURS = range(8, 20)  # one-hour blocks from 8 AM up to 8 PM
HOUR_LABELS = [f"{h % 12 or 12} {'AM' if h < 12 else 'PM'}" for h in range(8, 21)]
PERIOD = re.compile(r"from (\d{1,2}:\d\d [AP]M) to (\d{1,2}:\d\d [AP]M)")
NEXT_MONDAY_HOUR = 10


# Helpers

def block_value(day, hour):
    """The value a grid checkbox carries: 2020-11-19 at 10 AM is "2020-11-19T10"."""
    return f"{day:%Y-%m-%d}T{hour:02d}"


def day_date(context, name):
    """A day name like "Thursday" or "next Monday" as a date in the week of the fixed today."""
    monday = context.today - timedelta(days=context.today.weekday())
    if name.startswith("next "):
        return monday + timedelta(days=7 + DAY_NAMES.index(name[len("next "):]))
    return monday + timedelta(days=DAY_NAMES.index(name))


def clock(text):
    """ "10:00 AM" as a time."""
    return datetime.strptime(text, "%I:%M %p").time()


def hours(text):
    """ "10 AM and 2 PM" as [10, 14]."""
    return [datetime.strptime(h, "%I %p").hour for h in re.findall(r"\d{1,2} [AP]M", text)]


def periods_on(user, day):
    """Every (start, end) a user has on a day, earliest first."""
    rows = Availability.objects.filter(user=user, date=day).order_by("start_time")
    return list(rows.values_list("start_time", "end_time"))


def view_page(context):
    """Open the Study Plan page and keep its parsed HTML."""
    context.response = context.client.get(reverse("availability:list"))
    assert context.response.status_code == 200, context.response.status_code
    context.soup = BeautifulSoup(context.response.content, "html.parser")
    return context.soup


def checkbox(soup, value):
    """The grid checkbox for one block; fails the step if the page has none."""
    box = soup.find("input", attrs={"type": "checkbox", "name": "block", "value": value})
    assert box is not None, f"no grid block {value} on the page"
    return box


def submitted_blocks(soup):
    """What a browser would send: ticked boxes, minus disabled ones (browsers never send those)."""
    return {
        box["value"]
        for box in soup.select('input[name="block"][checked]')
        if not box.has_attr("disabled")
    }


def form_action(soup):
    """Where the grid's form posts to, read from the page as a browser would."""
    box = soup.find("input", attrs={"name": "block"})
    assert box is not None, "the page has no grid"
    form = box.find_parent("form")
    assert form is not None and form.get("action"), "the grid is not in a form with an action"
    return form["action"]


def save(context, blocks, url=None):
    """Post a set of block values to the save URL, as the grid's form does.

    A save redirects back to the Study Plan page (post, redirect, get), so a
    404, 405 or login redirect fails here instead of looking like "nothing saved".
    """
    context.response = context.client.post(
        url or reverse("availability:save_week"), {"block": sorted(blocks)}
    )
    assert context.response.status_code == 302, context.response.status_code
    assert context.response.url == reverse("availability:list"), context.response.url


def assert_periods(context, user, day, periods):
    """The user's periods on the day are exactly the "from X to Y" pairs listed."""
    expected = [(clock(s), clock(e)) for s, e in PERIOD.findall(f"from {periods}")]
    actual = periods_on(user, day_date(context, day))
    assert actual == expected, f"{day}: expected {expected}, found {actual}"


def add_period(user, context, day, start, end):
    Availability.objects.create(
        user=user, date=day_date(context, day), start_time=clock(start), end_time=clock(end)
    )


def other_student(context):
    if not hasattr(context, "other_user"):
        context.other_user = get_user_model().objects.create_user(
            username="behave_other_grid_student", password="test-password-123"
        )
    return context.other_user


# Givens

@given("today is {date_text}")
def step_today_is(context, date_text):
    """Fix today's date; every timezone.localdate() call sees it until the scenario ends."""
    today = datetime.strptime(date_text, "%A, %B %d, %Y").date()
    patcher = patch("django.utils.timezone.localdate", return_value=today)
    patcher.start()
    context.add_cleanup(patcher.stop)


@given("I have no availability this week")
def step_no_availability_this_week(context):
    monday = day_date(context, "Monday")
    week = (monday, monday + timedelta(days=6))
    assert not Availability.objects.filter(user=context.user, date__range=week).exists()


@given("I am available on {day} from {start} to {end}")
def step_i_am_available(context, day, start, end):
    add_period(context.user, context, day, start, end)


@given("another student is available on {day} from {start} to {end}")
def step_other_student_available(context, day, start, end):
    add_period(other_student(context), context, day, start, end)


# Whens

@when("I view the Study Plan page")
def step_view_page(context):
    view_page(context)


@when("I select the {day} {blocks} blocks and save")
@when("I select the {day} {blocks} block and save")
def step_select_and_save(context, day, blocks):
    """Tick more boxes on top of what the page already shows, then save the whole form."""
    soup = view_page(context)
    chosen = submitted_blocks(soup)
    for hour in hours(blocks):
        value = block_value(day_date(context, day), hour)
        assert not checkbox(soup, value).has_attr("disabled"), f"{value} cannot be selected"
        chosen.add(value)
    save(context, chosen, form_action(soup))


@when("I deselect the {day} {blocks} block and save")
def step_deselect_and_save(context, day, blocks):
    """Untick boxes the page shows as selected, then save the whole form."""
    soup = view_page(context)
    chosen = submitted_blocks(soup)
    for hour in hours(blocks):
        value = block_value(day_date(context, day), hour)
        assert checkbox(soup, value).has_attr("checked"), f"{value} was not selected"
        chosen.discard(value)
    save(context, chosen, form_action(soup))


# These two forge a request on purpose: no page, just a value a browser would never
# send, alongside a valid block so the scenario can show the request was processed.

@when("I submit the {day} {blocks} block together with the {valid_day} {valid_blocks} block")
def step_submit_block(context, day, blocks, valid_day, valid_blocks):
    forged = {block_value(day_date(context, day), hour) for hour in hours(blocks)}
    valid = {block_value(day_date(context, valid_day), hour) for hour in hours(valid_blocks)}
    save(context, forged | valid)


@when("I submit a block for next Monday together with the {valid_day} {valid_blocks} block")
def step_submit_next_monday(context, valid_day, valid_blocks):
    forged = {block_value(day_date(context, "next Monday"), NEXT_MONDAY_HOUR)}
    valid = {block_value(day_date(context, valid_day), hour) for hour in hours(valid_blocks)}
    save(context, forged | valid)


# Thens

@then("on {day} I am available only from {periods}")
def step_i_am_available_only(context, day, periods):
    assert_periods(context, context.user, day, periods)


@then("on {day} the other student is available only from {periods}")
def step_other_student_available_only(context, day, periods):
    assert_periods(context, context.other_user, day, periods)


@then("I have no availability on {day}")
def step_no_availability_on(context, day):
    actual = periods_on(context.user, day_date(context, day))
    assert not actual, f"{day}: expected nothing, found {actual}"


@then("the {day} {blocks} blocks are selected")
def step_blocks_selected(context, day, blocks):
    for hour in hours(blocks):
        value = block_value(day_date(context, day), hour)
        assert checkbox(context.soup, value).has_attr("checked"), f"{value} is not selected"


@then("the {day} {blocks} block is not selected")
def step_block_not_selected(context, day, blocks):
    for hour in hours(blocks):
        value = block_value(day_date(context, day), hour)
        assert not checkbox(context.soup, value).has_attr("checked"), f"{value} is selected"


@then("the {days} blocks cannot be selected")
def step_days_disabled(context, days):
    for day in days.split(" and "):
        for hour in GRID_HOURS:
            value = block_value(day_date(context, day), hour)
            assert checkbox(context.soup, value).has_attr("disabled"), f"{value} can be selected"


@then("the {day} blocks can be selected")
def step_day_enabled(context, day):
    for hour in GRID_HOURS:
        value = block_value(day_date(context, day), hour)
        assert not checkbox(context.soup, value).has_attr("disabled"), f"{value} cannot be selected"


@then("no blocks are selected")
def step_no_blocks_selected(context):
    assert context.soup.select('input[name="block"]'), "the page has no grid"
    assert not context.soup.select('input[name="block"][checked]'), "some blocks are selected"


@then("I see My Availability with a Monday to Sunday grid from 8 AM to 8 PM")
def step_grid_layout(context):
    grid = context.soup.find(class_="availability-grid")
    assert grid is not None, "no element with class availability-grid"
    labels = set(grid.stripped_strings)
    missing = [label for label in HOUR_LABELS if label not in labels]
    assert not missing, f"hour labels missing from the grid: {missing}"
    for name in DAY_NAMES:
        assert name[:3] in labels or name in labels, f"no {name} header in the grid"
        for hour in GRID_HOURS:
            checkbox(grid, block_value(day_date(context, name), hour))


@then("I see My Availability and then Generated Plan")
def step_availability_before_plan(context):
    html = context.response.content.decode()
    for heading in ("<h2>My Availability</h2>", "<h2>Generated Plan</h2>"):
        assert heading in html, f"{heading} is not on the page"
    assert html.index("<h2>My Availability</h2>") < html.index("<h2>Generated Plan</h2>")
