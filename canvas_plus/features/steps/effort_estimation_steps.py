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
    has_enough_available_time,
    save_manual_effort_estimate,
)

# Import the structured AI response model.
from study_plan.schema import EffortEstimate
from django.contrib.auth import get_user_model
from django.utils import timezone
from assignments.models import Assignment

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


@then("the student should be able to enter an estimate manually")
def step_manual_estimate_available(context):
    """Represent the manual-entry fallback required by the story."""

    # The UI for persistence will be added after the shared Assignment
    # model dependency lands. For now, confirm the estimator produced
    # the state that tells the future UI to request manual input.
    assert context.effort_estimate is None


@given("an assignment requires more effort than the student has available")
def step_insufficient_available_time(context):
    """Prepare an estimate that exceeds available study time."""

    # Example: the assignment requires three hours of work.
    context.estimated_minutes = 180

    # The student currently has only two hours available.
    context.available_minutes = 120


@when("the application compares estimated effort with available study time")
def step_compare_effort_and_availability(context):
    """Compare required effort against available study time."""

    # Store the comparison result for the Then step.
    context.has_enough_time = has_enough_available_time(
        estimated_minutes=context.estimated_minutes,
        available_minutes=context.available_minutes,
    )


@then(
    "the student should be notified that there is not enough "
    "available study time"
)
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


@when("the student changes the effort estimate to 120 minutes")
def step_student_changes_estimate(context):
    """Replace the existing estimate with the student's manual value."""

    # Save the student's new manual estimate.
    save_manual_effort_estimate(
        assignment=context.assignment,
        estimated_minutes=120,
    )


@then("the new effort estimate should be saved as 120 minutes")
def step_new_estimate_is_saved(context):
    """Verify the student's new estimate was persisted."""

    # Reload the assignment so this assertion checks the database.
    context.assignment.refresh_from_db()

    # Confirm the updated value is stored.
    assert context.assignment.estimated_effort_minutes == 120

    # Confirm the estimate is now marked as manual.
    assert context.assignment.effort_estimate_source == "manual"


@then("the updated effort estimate should be used for future scheduling")
def step_updated_estimate_used_for_scheduling(context):
    """Verify future scheduling logic uses the new persisted estimate."""

    # Reload the assignment to use the persisted estimate.
    context.assignment.refresh_from_db()

    # Simulate the student having only 100 minutes of available study time.
    enough_time = has_enough_available_time(
        estimated_minutes=context.assignment.estimated_effort_minutes,
        available_minutes=100,
    )

    # The new 120-minute estimate should be used, so 100 minutes is insufficient.
    assert enough_time is False
    