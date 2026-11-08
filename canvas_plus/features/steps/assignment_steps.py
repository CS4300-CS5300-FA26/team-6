"""Behavior steps for upcoming coursework on the logged-in home page."""
# pylint: disable=import-error,missing-function-docstring,not-callable,duplicate-code

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from behave import given, when, then
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.cache import cache
from django.test import Client, override_settings
from django.utils import timezone as django_timezone
from django.utils.html import escape
from django.utils.text import slugify

from accounts.canvas_client import CanvasAPIError, CanvasAuthenticationError
from accounts.models import CanvasConnection
from assignments.models import Assignment

COURSE = {"id": 42, "name": "CS 4300"}
ASSIGNMENT_TITLE = "Canvas Project 1"
TOKEN = "fake-behave-canvas-token"


def parse_due_date(value):
    """Translate scenario dates into aware UTC values returned by the API."""
    try:
        parsed = datetime.strptime(value, "%B %d, %Y at %I:%M %p")
    except ValueError:
        parsed = datetime.strptime(value, "%b %d, %Y %I:%M %p")
    return parsed.replace(tzinfo=ZoneInfo("America/Denver")).astimezone(timezone.utc)


def assignment_result(due_date):
    """Build one normalized result from the assignment-read contract."""
    return {
        "id": 101,
        "course_id": 42,
        
        "title": ASSIGNMENT_TITLE,
        "course_name": COURSE["name"],
        "canvas_assignment_id": 101, "canvas_course_id": 42,
        "due_date": due_date,
        "submitted": False,
    }


def prepare_student(context, assignments):
    """Use real per-user encrypted connection storage and stub Canvas calls."""
    configured = override_settings(
        CANVAS_BASE_URL="https://canvas.example.edu",
        CANVAS_TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode(),
    )
    configured.enable()
    context.add_cleanup(configured.disable)

    context.user = get_user_model().objects.create_user(username="canvas-student")
    context.connection = CanvasConnection(
        user=context.user,
        canvas_url="https://canvas.example.edu",
    )
    context.connection.set_token(TOKEN)
    context.connection.save()

    context.client = Client()
    context.client.force_login(context.user)
    context.canvas_courses = Mock(return_value=[COURSE])
    context.canvas_assignments = Mock(return_value=assignments)
    context.canvas_all_assignments = Mock(return_value=[])
    context.graded_submissions = Mock(return_value=[])

    targets = (
        ("accounts.connections.list_courses", context.canvas_courses, False),
        ("assignments.views.list_courses", context.canvas_courses, True),
        ("assignments.views.list_upcoming_assignments", context.canvas_assignments, True),
        ("assignments.views.list_all_assignments", context.canvas_all_assignments, True),
        ("assignments.views.list_graded_submissions", context.graded_submissions, False),
    )
    for target, replacement, create in targets:
        patcher = patch(target, replacement, create=create)
        patcher.start()
        context.add_cleanup(patcher.stop)


def get_assignment_for_date(value):
    return [assignment_result(parse_due_date(value))]


def prepare_relative_coursework(context, due_in, submitted=False):
    """Anchor coursework to the current time so scenarios do not age."""
    context.dashboard_now = django_timezone.now()
    assignment = assignment_result(context.dashboard_now + due_in)
    assignment["submitted"] = submitted
    prepare_student(context, [assignment])


@given('I am a connected student with upcoming coursework due on "{due_date}"')
def step_connected_student_with_upcoming_work(context, due_date):
    prepare_student(context, get_assignment_for_date(due_date))


@given("I am a connected student with no upcoming coursework")
def step_connected_student_with_no_upcoming_work(context):
    prepare_student(context, [])


@given("a connected student with upcoming and non-upcoming Canvas assignments")
def step_connected_student_with_upcoming_and_non_upcoming_work(context):
    upcoming = assignment_result(django_timezone.now() + timedelta(days=2))
    upcoming["description"] = "Upcoming assignment details"
    undated = {
        "canvas_assignment_id": 102,
        "canvas_course_id": COURSE["id"],
        "title": "Undated Canvas assignment",
        "course_name": COURSE["name"],
        "due_date": None,
        "submitted": False,
        "description": "Undated assignment details",
    }
    prepare_student(context, [upcoming])
    context.canvas_all_assignments.return_value = [upcoming, undated]


@given("a connected student has saved assignments in current and other courses")
def step_saved_assignments_in_current_and_other_courses(context):
    prepare_student(context, [])
    cache.clear()
    context.canvas_courses.return_value = [COURSE, {"id": 84, "name": "MATH 2250"}]
    context.current_assignment = Assignment.objects.create(
        user=context.user, title="Current", course=COURSE["name"],
        canvas_course_id=42, canvas_assignment_id=201, sync_state="synced",
    )
    context.missing_assignment = Assignment.objects.create(
        user=context.user, title="Missing", course="MATH 2250",
        canvas_course_id=84, canvas_assignment_id=202, sync_state="missing",
    )
    context.outside_assignment = Assignment.objects.create(
        user=context.user, title="Other course", course="History",
        canvas_course_id=999, canvas_assignment_id=203, sync_state="synced",
    )


@given("Canvas has updated those current course assignments")
def step_canvas_updated_current_course_assignments(context):
    context.updated_assignments = [
        {
            "canvas_assignment_id": 201,
            "canvas_course_id": 42,
            "title": "Updated current assignment",
            "course_name": COURSE["name"],
            "due_date": django_timezone.now() + timedelta(days=3),
            "submitted": False,
            "description": "Updated current description",
        },
        {
            "canvas_assignment_id": 202,
            "canvas_course_id": 84,
            "title": "Updated missing assignment",
            "course_name": "MATH 2250",
            "due_date": django_timezone.now() + timedelta(days=4),
            "submitted": False,
            "description": "Updated missing description",
        },
    ]
    context.original_assignment_details = {}
    for index, assignment in enumerate(
        (context.current_assignment, context.missing_assignment)
    ):
        assignment.description = f"Original {assignment.title.lower()} description"
        assignment.due_date = django_timezone.now() + timedelta(days=10 + index)
        assignment.save(update_fields=["description", "due_date"])
        context.original_assignment_details[assignment.pk] = {
            field: getattr(assignment, field)
            for field in ("title", "course", "due_date", "description")
        }
    context.canvas_all_assignments.return_value = context.updated_assignments


@given("saving the second assignment fails")
def step_second_assignment_save_fails(context):
    original_save = Assignment.save
    save_count = 0

    def fail_on_second_student_assignment_save(instance, *args, **kwargs):
        nonlocal save_count
        if instance.user_id == context.user.pk:
            save_count += 1
            if save_count == 2:
                raise RuntimeError("Injected assignment persistence failure")
        return original_save(instance, *args, **kwargs)

    context.assignment_save_patcher = patch.object(
        Assignment,
        "save",
        new=fail_on_second_student_assignment_save,
    )
    context.assignment_save_patcher.start()
    context.add_cleanup(context.assignment_save_patcher.stop)


@given("another student has a saved assignment in a current course")
def step_other_student_has_current_assignment(context):
    other_user = get_user_model().objects.create_user(username="other-canvas-student")
    context.other_assignment = Assignment.objects.create(
        user=other_user, title="Other student", course=COURSE["name"],
        canvas_course_id=42, canvas_assignment_id=201, sync_state="synced",
    )


@given("the assignment sync is unavailable")
def step_assignment_sync_unavailable(context):
    context.canvas_all_assignments.side_effect = CanvasAPIError("Canvas sync unavailable")


@given("the student has no current Canvas courses")
def step_student_has_no_current_canvas_courses(context):
    context.assignment_sync_states = {
        assignment.pk: assignment.sync_state
        for assignment in (
            context.current_assignment,
            context.missing_assignment,
            context.outside_assignment,
        )
    }
    context.canvas_courses.return_value = []


@given("Canvas rejects the token during assignment sync")
def step_canvas_rejects_token_during_sync(context):
    context.canvas_all_assignments.side_effect = CanvasAuthenticationError(
        "Rejected during assignment sync"
    )


@then("assignments in the student's current courses are marked failed, including missing assignments")
def step_current_assignments_marked_failed(context):
    for assignment in (context.current_assignment, context.missing_assignment):
        assignment.refresh_from_db()
        assert assignment.sync_state == "failed", assignment.sync_state


@then("the original assignment details are preserved")
def step_original_assignment_details_preserved(context):
    for assignment in (context.current_assignment, context.missing_assignment):
        assignment.refresh_from_db()
        expected = context.original_assignment_details[assignment.pk]
        actual = {
            field: getattr(assignment, field)
            for field in expected
        }
        assert actual == expected


@then("the updated assignments are synced successfully")
def step_updated_assignments_synced(context):
    for updated in context.updated_assignments:
        assignment = Assignment.objects.get(
            user=context.user,
            canvas_assignment_id=updated["canvas_assignment_id"],
        )
        assert assignment.title == updated["title"]
        assert assignment.course == updated["course_name"]
        assert assignment.due_date == updated["due_date"]
        assert assignment.description == updated["description"]
        assert assignment.sync_state == "synced"


@then("the assignment sync error is no longer shown")
def step_assignment_sync_error_cleared(context):
    assert context.response.status_code == 200
    assert "Unable to sync Canvas assignments. Please try again." not in (
        context.response.content.decode()
    )


@then("all saved assignment sync states remain unchanged")
def step_all_saved_assignment_states_unchanged(context):
    for assignment_id, sync_state in context.assignment_sync_states.items():
        assignment = Assignment.objects.get(pk=assignment_id)
        assert assignment.sync_state == sync_state


@then("assignments outside those courses and the other student's assignment remain unchanged")
def step_other_assignments_unchanged(context):
    for assignment in (context.outside_assignment, context.other_assignment):
        assignment.refresh_from_db()
        assert assignment.sync_state == "synced", assignment.sync_state


@then("I see an assignment sync error")
def step_assignment_sync_error_visible(context):
    assert context.response.status_code == 200
    assert "Unable to sync Canvas assignments. Please try again." in context.response.content.decode()


@when("saving assignments is restored and I reload the logged-in home page")
def step_restore_saving_and_reload(context):
    context.assignment_save_patcher.stop()
    context.response = context.client.get("/assignments/")
    assert context.response.status_code == 200


@given('I am viewing "{title}" for "{course}" due "{due_date}"')
def step_viewing_assignment(context, title, course, due_date):
    prepare_student(context, get_assignment_for_date(due_date))
    context.response = context.client.get("/assignments/")
    assert context.response.status_code == 200
    html = context.response.content.decode()
    assert title in html
    assert course in html
    assert due_date in html


@when("I open the logged-in home page")
def step_open_logged_in_home(context):
    context.response = context.client.get("/assignments/")


@when('Canvas changes its due date to "{due_date}"')
def step_canvas_changes_due_date(context, due_date):
    context.canvas_assignments.return_value = get_assignment_for_date(due_date)


@when("I reload the logged-in home page")
def step_reload_logged_in_home(context):
    context.response = context.client.get("/assignments/")


@then('I see "{title}" for "{course}" due "{due_date}"')
def step_assignment_due_date_is_visible(context, title, course, due_date):
    assert context.response.status_code == 200
    html = context.response.content.decode()
    for expected in (title, course, due_date):
        assert expected in html


@then('I see exactly "{message}"')
def step_exact_empty_state(context, message):
    assert context.response.status_code == 200
    html = context.response.content.decode()
    assert html.count(message) == 1
    assert "Unable to load upcoming assignments" not in html
    assert "Your Canvas connection expired." not in html


@then("both assignments are saved with descriptions while only the existing upcoming selection is displayed")
def step_synced_assignments_do_not_change_upcoming_selection(context):
    assert context.response.status_code == 200
    saved = {
        assignment.canvas_assignment_id: assignment
        for assignment in Assignment.objects.filter(user=context.user)
    }
    assert set(saved) == {101, 102}, f"Expected both Canvas assignments to be saved, got {set(saved)}"
    assert saved[101].description == "Upcoming assignment details"
    assert saved[102].description == "Undated assignment details"
    assert saved[101].sync_state == "synced"
    assert saved[102].sync_state == "synced"
    displayed_ids = [
        assignment["canvas_assignment_id"]
        for assignment in context.response.context["assignments"]
    ]
    assert displayed_ids == [101]
    html = context.response.content.decode()
    assert "Canvas Project 1" in html
    assert "Undated Canvas assignment" not in html


@then('I see the revised due date "{revised}" instead of "{original}"')
def step_revised_due_date_is_visible(context, revised, original):
    assert context.response.status_code == 200
    html = context.response.content.decode()
    assert revised in html
    assert original not in html


@given("I am a signed-in student without a Canvas connection")
def step_student_without_canvas_connection(context):
    prepare_student(context, [])
    context.connection.delete()


@given("my saved Canvas token is rejected while loading assignments")
def step_saved_token_rejected_for_assignments(context):
    prepare_student(context, [])
    context.canvas_courses.side_effect = CanvasAuthenticationError("Rejected")


@given("Canvas is temporarily unavailable while loading assignments")
def step_canvas_unavailable_for_assignments(context):
    prepare_student(context, [])
    context.canvas_assignments.side_effect = CanvasAPIError("Canvas unavailable")


@then("I see the Canvas connection prompt instead of the empty state")
def step_connection_prompt_not_empty_state(context):
    assert context.response.status_code == 200
    html = context.response.content.decode()
    assert "Connect Canvas to see your upcoming assignments." in html
    assert 'href="/accounts/connect-canvas/"' in html
    assert "No upcoming assignments" not in html


@then("I see the expired Canvas connection message and reconnect link")
def step_expired_connection_message(context):
    assert context.response.status_code == 200
    html = context.response.content.decode()
    assert html.count("Your Canvas connection expired.") == 1
    assert 'href="/accounts/connect-canvas/"' in html
    assert "No upcoming assignments" not in html


@then("I see the assignments unavailable message instead of the empty state")
def step_assignments_unavailable_not_empty_state(context):
    assert context.response.status_code == 200
    html = context.response.content.decode()
    assert "Unable to load upcoming assignments. Please try again." in html
    assert "No upcoming assignments" not in html


@given("I am a connected student with unsubmitted coursework due in {amount:d} {unit}")
def step_unsubmitted_coursework_due(context, amount, unit):
    prepare_relative_coursework(context, timedelta(**{unit: amount}))


@given("I am a connected student with unsubmitted coursework that was due {hours:d} hours ago")
def step_unsubmitted_coursework_past_due(context, hours):
    prepare_relative_coursework(context, timedelta(hours=-hours))


@given("I am a connected student who has submitted coursework due in {hours:d} hours")
def step_submitted_coursework_due(context, hours):
    prepare_relative_coursework(context, timedelta(hours=hours), submitted=True)


@given('my dashboard shows "{title}" marked "{label}"')
def step_dashboard_shows_priority(context, title, label):
    step_open_logged_in_home(context)
    step_assignment_marked(context, title, label)


@when("{hours:d} hours pass")
def step_hours_pass(context, hours):
    context.dashboard_now += timedelta(hours=hours)
    clock = patch("django.utils.timezone.now", return_value=context.dashboard_now)
    clock.start()
    context.add_cleanup(clock.stop)


@then('I see "{title}" marked "{label}"')
def step_assignment_marked(context, title, label):
    assert context.response.status_code == 200
    assignments = [
        assignment for assignment in context.response.context["assignments"]
        if assignment["title"] == title
    ]
    assert len(assignments) == 1, f'Expected one assignment titled "{title}"'
    actual = assignments[0]["priority"]
    assert actual == label, f'Expected "{title}" marked "{label}", got "{actual}"'

    html = context.response.content.decode()
    heading = f'<h2 class="assignment-title">{escape(title)}</h2>'
    cards = [
        fragment.split("</li>", 1)[0]
        for fragment in html.split('<li class="assignment-card">')[1:]
    ]
    matching_cards = [card for card in cards if heading in card]
    assert len(matching_cards) == 1, f'Expected one card titled "{title}"'
    badge = (
        f'<span class="assignment-status assignment-status--{slugify(label)}">'
        f'{escape(label)}</span>'
    )
    assert badge in matching_cards[0], f'Card for "{title}" has no "{label}" badge'


@then("I see no high-priority marker")
def step_no_high_priority_marker(context):
    assert context.response.status_code == 200
    html = context.response.content.decode()
    for slug in ("due-soon", "past-due"):
        # The CSS defines both classes even when no card carries either marker.
        assert f'assignment-status--{slug}">' not in html
