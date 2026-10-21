"""Behave step definitions for student availability acceptance tests."""

# disable false-positive pylint error
# pylint: disable=not-callable

# Imports needed for tests and file functionality.
from datetime import date, time
from behave import given, when, then
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from availability.models import Availability  # pylint: disable=import-error


@given("I am logged in as a student")
def step_logged_in_availability_student(context):
    """Create and log in a student for the availability scenario."""

    # Get the User model this project.
    user_model = get_user_model()

    # Create a test user in Behave's database.
    context.user = user_model.objects.create_user(
        username="behave_availability_student",
        password="test-password-123",
    )

    # Create Django's simulated browser client.
    context.client = Client()

    # Log the test student in.
    context.client.login(
        username="behave_availability_student",
        password="test-password-123",
    )


@when("I create a valid availability period")
def step_create_valid_availability(context):
    """Submit a valid availability period."""

    # Post valid availability to the application route.
    context.response = context.client.post(
        reverse("availability:list"),
        {
            "date": "2026-10-22",
            "start_time": "14:00",
            "end_time": "16:00",
        },
    )


@then("the availability period should be saved")
def step_valid_availability_saved(context):
    """Verify the valid availability period was saved."""

    # Check the test database for the expected record.
    availability_exists = Availability.objects.filter(
        user=context.user,
        date=date(2026, 10, 22),
        start_time=time(14, 0),
        end_time=time(16, 0),
    ).exists()

    # Fail the scenario if the record is missing.
    assert availability_exists


@given("I have an existing availability period")
def step_existing_availability(context):
    """Create an availability record for editing."""

    # Create a valid saved availability entry.
    context.availability = Availability.objects.create(
        user=context.user,
        date=date(2026, 10, 22),
        start_time=time(14, 0),
        end_time=time(16, 0),
    )


@when("I update the availability period")
def step_update_availability(context):
    """Submit changed availability values."""

    # Post updated values to the edit route.
    context.response = context.client.post(
        reverse(
            "availability:edit",
            args=[context.availability.id],
        ),
        {
            "date": "2026-10-23",
            "start_time": "15:00",
            "end_time": "17:00",
        },
    )


@then("the updated availability should be saved")
def step_updated_availability_saved(context):
    """Verify the updated values were saved."""

    # Reload the record from the database.
    context.availability.refresh_from_db()

    # Confirm the saved values match the edit.
    assert context.availability.date == date(2026, 10, 23)
    assert context.availability.start_time == time(15, 0)
    assert context.availability.end_time == time(17, 0)


@when(
    "I create an availability period with an end time "
    "before the start time"
)
def step_create_invalid_availability(context):
    """Submit an invalid availability period."""

    # Post an invalid time range.
    context.response = context.client.post(
        reverse("availability:list"),
        {
            "date": "2026-10-22",
            "start_time": "16:00",
            "end_time": "14:00",
        },
    )


@then("the invalid availability should not be saved")
def step_invalid_availability_not_saved(context):
    """Verify the invalid record was rejected."""

    # Check that no availability record was created for this user.
    availability_exists = Availability.objects.filter(
        user=context.user
    ).exists()

    assert not availability_exists


@then("I should receive an availability correction message")
def step_availability_error_message(context):
    """Verify the validation error appears in the response."""

    # Decode the rendered HTML response.
    response_text = context.response.content.decode()

    # Confirm the form displayed the expected correction message.
    assert "End time must be later than start time." in response_text
