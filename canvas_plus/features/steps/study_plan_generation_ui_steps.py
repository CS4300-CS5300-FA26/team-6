"""Behave steps for generating a plan from locally synced assignments."""
# Behave decorators are callable; pylint cannot infer their dynamic registration.
# pylint: disable=not-callable,missing-function-docstring,import-error

from datetime import datetime, time, timedelta
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from behave import given, when, then
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import CanvasConnection
from assignments.models import Assignment
from availability.models import Availability
from study_plan.models import StudyPlan, StudySession


@given("a student with selected eligible assignments and availability")
def step_student_with_selected_assignments(context):
    configured = override_settings(
        CANVAS_BASE_URL="https://canvas.example.edu",
        CANVAS_TOKEN_ENCRYPTION_KEY=Fernet.generate_key().decode(),
    )
    configured.enable()
    context.add_cleanup(configured.disable)

    context.user = get_user_model().objects.create_user(username="plan-ui-behave-student")
    connection = CanvasConnection(
        user=context.user,
        canvas_url="https://canvas.example.edu",
    )
    connection.set_token("fake-plan-ui-behave-token")
    connection.save()
    context.client = Client()
    context.client.force_login(context.user)

    course = {"id": 71, "name": "Biology"}
    context.canvas_assignments = [
        {
            "canvas_assignment_id": 701,
            "canvas_course_id": course["id"],
            "title": "Selected lab report",
            "course_name": course["name"],
            "due_date": timezone.now() + timedelta(days=3),
            "submitted": False,
            "description": "Summarize the experiment.",
        },
        {
            "canvas_assignment_id": 702,
            "canvas_course_id": course["id"],
            "title": "Selected reading response",
            "course_name": course["name"],
            "due_date": timezone.now() + timedelta(days=4),
            "submitted": False,
            "description": "Respond to the assigned reading.",
        },
        {
            "canvas_assignment_id": 703,
            "canvas_course_id": course["id"],
            "title": "Unselected worksheet",
            "course_name": course["name"],
            "due_date": timezone.now() + timedelta(days=5),
            "submitted": False,
            "description": "Complete the worksheet.",
        },
    ]
    canvas_stubs = (
        ("assignments.views.list_courses", Mock(return_value=[course])),
        (
            "assignments.views.list_upcoming_assignments",
            Mock(return_value=context.canvas_assignments),
        ),
        ("assignments.views.list_graded_submissions", Mock(return_value=[])),
        (
            "assignments.views.list_all_assignments",
            Mock(return_value=context.canvas_assignments),
        ),
    )
    for target, replacement in canvas_stubs:
        patcher = patch(target, replacement)
        patcher.start()
        context.add_cleanup(patcher.stop)

    sync_response = context.client.get(reverse("assignment_list"))
    assert sync_response.status_code == 200
    context.assignments = list(
        Assignment.objects.filter(user=context.user).order_by("canvas_assignment_id")
    )
    for assignment in context.assignments:
        assignment.estimated_effort_minutes = 30
        assignment.save(update_fields=["estimated_effort_minutes"])

    context.selected_assignments = context.assignments[:2]
    context.unselected_assignment = context.assignments[2]
    available_date = timezone.localdate() + timedelta(days=1)
    Availability.objects.create(
        user=context.user,
        date=available_date,
        start_time=time(9),
        end_time=time(12),
    )
    context.plan = StudyPlan.objects.create(
        user=context.user,
        notices=["Some selected work could not be scheduled."],
    )
    local_timezone = ZoneInfo(timezone.get_current_timezone_name())
    session_start = datetime.combine(
        available_date,
        time(9),
        tzinfo=local_timezone,
    )
    for offset, assignment in enumerate(context.selected_assignments):
        start = session_start + timedelta(hours=offset)
        StudySession.objects.create(
            plan=context.plan,
            assignment=assignment,
            start=start,
            end=start + timedelta(minutes=30),
        )

    context.generate_plan = Mock(return_value=context.plan)
    generation_stub = patch(
        "assignments.views.generate_plan",
        context.generate_plan,
        create=True,
    )
    generation_stub.start()
    context.add_cleanup(generation_stub.stop)


@when("they generate a plan")
def step_generate_selected_plan(context):
    context.response = context.client.post(
        reverse("generate_plan"),
        {
            "assignment_ids": [
                str(assignment.pk) for assignment in context.selected_assignments
            ]
        },
        follow=True,
    )


@then("the study plan shows the selected assignments and generation notice")
def step_selected_assignments_and_notice_shown(context):
    assert context.response.status_code == 200
    page = context.response.content.decode()
    for assignment in context.selected_assignments:
        assert assignment.title in page
    assert context.plan.notices[0] in page
    context.generate_plan.assert_called_once_with(
        context.user,
        [assignment.pk for assignment in context.selected_assignments],
    )


@then("the study plan omits the unselected assignment")
def step_unselected_assignment_omitted(context):
    assert context.unselected_assignment.title not in context.response.content.decode()