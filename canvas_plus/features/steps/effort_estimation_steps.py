"""Behave step definitions for assignment effort estimation."""

# Pylint can misread Behave's dynamically created decorators,
# so disable that specific false-positive for this file.
# pylint: disable=not-callable

# Import Python's datetime type for assignment due-date test data.
from datetime import datetime

# Import unittest's patch helper so Behave does not make
# a real AI provider request during acceptance testing.
from unittest.mock import patch

# Import Behave's Given, When, and Then decorators.
from behave import given, when, then

# Import the effort-estimation functions being tested.
from study_plan.effort_estimation import (
    estimate_assignment_effort,
    save_manual_effort_estimate,
)

# Import the structured AI response model.
from study_plan.schema import EffortEstimate
from django.contrib.auth import get_user_model
from django.utils import timezone
from assignments.models import Assignment
from django.urls import reverse

@given("an assignment has enough information for an effort estimate")
def step_complete_assignment_information(context):
    """Prepare complete assignment data for AI effort estimation."""

    # Store representative assignment data in Behave's shared context.
    # Later steps in this scenario can reuse these values.
    context.assignment_title = "Research Paper"
    context.assignment_due_date = datetime(2026, 11, 10, 23, 59)
    context.assignment_information = (
        "Write a five-page research paper using at least "
        "five academic sources."
    )


@when("the application estimates the assignment effort")
def step_estimate_assignment_effort(context):
    """Run effort estimation using a mocked AI response."""

    # Create the structured result we expect the shared AI layer
    # to return after validating the provider response.
    fake_estimate = EffortEstimate(
        estimated_minutes=90,
        reason="The assignment requires research, writing, and revision.",
    )

    # Mock the shared inference call so this acceptance test remains
    # deterministic and does not spend API credits or require network access.
    with patch(
        "study_plan.effort_estimation.infer",
        return_value=fake_estimate,
    ):
        context.effort_estimate = estimate_assignment_effort(
            title=context.assignment_title,
            due_date=context.assignment_due_date,
            assignment_information=context.assignment_information,
        )


@then("an estimated amount of effort should be returned")
def step_effort_estimate_returned(context):
    """Verify that the application produced a valid effort estimate."""

    # A valid estimate should exist.
    assert context.effort_estimate is not None

    # The structured result should contain a positive number of minutes.
    assert context.effort_estimate.estimated_minutes > 0


@given("an assignment is missing information required for effort estimation")
def step_missing_assignment_information(context):
    """Prepare incomplete assignment data."""

    # The missing due date represents an assignment that does not
    # contain enough information to confidently request an AI estimate.
    context.assignment_title = "Research Paper"
    context.assignment_due_date = None
    context.assignment_information = "Write a research paper."


@when("the application attempts to estimate the assignment effort")
def step_attempt_incomplete_effort_estimate(context):
    """Attempt to estimate an incomplete assignment."""

    # Call the real estimator.
    # Because required information is missing, the estimator should
    # return before making an AI provider request.
    context.effort_estimate = estimate_assignment_effort(
        title=context.assignment_title,
        due_date=context.assignment_due_date,
        assignment_information=context.assignment_information,
    )


@then("no automatic effort estimate should be returned")
def step_no_automatic_estimate(context):
    """Verify incomplete assignment data does not produce an estimate."""

    # None signals that the application should fall back to manual entry.
    assert context.effort_estimate is None


@then("the student can enter a manual estimate of 60 minutes")
def step_student_can_enter_manual_estimate(context):
    """Submit a fallback estimate through the real manual-entry form."""

    # Create a local assignment for the fallback flow if this
    # scenario has not already created one.
    if not hasattr(context, "assignment"):
        context.assignment = Assignment.objects.create(
            user=context.user,
            canvas_course_id=7001,
            canvas_assignment_id=8001,
            title="Incomplete Assignment",
            course="CS4300",
            due_date=timezone.now(),
        )

    # Log in as the assignment owner.
    context.test.client.force_login(context.user)
    # Submit the manual estimate through the real edit page.
    context.response = context.test.client.post(
        reverse(
            "edit_effort_estimate",
            args=[
                context.assignment.canvas_course_id,
                context.assignment.canvas_assignment_id,
            ],
        ),
        {
            "estimated_effort_minutes": 60,
        },
    )

    # A successful form submission should redirect.
    assert context.response.status_code == 302


def step_insufficient_time_detected(context):
    """Verify insufficient study time is detected."""

    # False means the available study time cannot cover the estimate.
    assert context.has_enough_time is False

@given("the student has an assignment with an estimated effort of 90 minutes")
def step_assignment_has_existing_estimate(context):
    """Create an assignment that already has an automatic effort estimate."""

    # Create a student who owns the assignment.
    user = get_user_model().objects.create_user(
        username="behave-effort-student",
    )

    # Save the user on the Behave context so later steps can reuse it.
    context.user = user

    # Create an assignment with an existing automatic estimate.
    context.assignment = Assignment.objects.create(
        user=user,
        canvas_course_id=5001,
        canvas_assignment_id=6001,
        title="Behave Assignment",
        course="CS4300",
        due_date=timezone.now(),
        estimated_effort_minutes=90,
        effort_estimate_source="automatic",
    )


@when("the student changes the effort estimate to 120 minutes through the edit page")
def step_student_changes_estimate_through_page(context):
    """Submit the manual override through the real Django edit form."""

    # Log in as the student who owns the assignment.
    context.test.client.force_login(context.user)

    # Submit the new estimate through the actual edit page.
    context.response = context.test.client.post(
        reverse(
            "edit_effort_estimate",
            args=[
                context.assignment.canvas_course_id,
                context.assignment.canvas_assignment_id,
            ],
        ),
        {
            "estimated_effort_minutes": 120,
        },
    )

    # A successful update should redirect back to the assignment list.
    assert context.response.status_code == 302


@then("the new effort estimate should be saved as 120 minutes")
def step_new_estimate_is_saved(context):
    """Verify the student's new estimate was persisted."""

    # Reload the assignment so this assertion checks the database.
    context.assignment.refresh_from_db()

    # Confirm the updated value is stored.
    assert context.assignment.estimated_effort_minutes == 120

    # Confirm the estimate is now marked as manual.
    assert context.assignment.effort_estimate_source == "manual"


@given("the assignment is missing information needed for an effort estimate")
def step_assignment_missing_information(context):
    """Create an incomplete assignment state that cannot be estimated automatically."""

    # Create a student for the fallback/manual-entry flow.
    context.user = get_user_model().objects.create_user(
        username="behave-fallback-student",
    )

    # Store incomplete assignment information.
    # The missing due date prevents automatic estimation.
    context.assignment_title = "Incomplete Assignment"
    context.assignment_due_date = None
    context.assignment_information = "Complete the assignment."


@then("no automatic effort estimate should be created")
def step_no_automatic_estimate_created(context):
    """Verify incomplete assignment data did not produce an automatic estimate."""

    # The estimation step should have stored its result on the context.
    assert context.effort_estimate is None


@then("the manual effort estimate should be saved as 60 minutes")
def step_manual_effort_estimate_saved(context):
    """Verify the manual fallback value was persisted through the edit form."""

    # Reload the assignment from the database so we verify
    # the values that were actually persisted.
    context.assignment.refresh_from_db()

    # Include the actual values in assertion messages so a
    # failing Behave scenario tells us exactly what is wrong.
    assert context.assignment.estimated_effort_minutes == 60, (
        "Expected estimated_effort_minutes to be 60, "
        f"but got {context.assignment.estimated_effort_minutes!r}"
    )

    assert context.assignment.effort_estimate_source == "manual", (
        "Expected effort_estimate_source to be 'manual', "
        f"but got {context.assignment.effort_estimate_source!r}"
    )
