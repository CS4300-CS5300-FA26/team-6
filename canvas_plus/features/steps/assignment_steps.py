"""Step definitions for assignment page Behave tests."""

# Import Behave decorators.
from behave import given, when, then
# Import Django's test client.
from django.test import Client
# import Assignment model so BDD test can test using actual DB records
from assignments.models import Assignment
from datetime import timedelta
from django.utils import timezone

@given("the assignments page exists")
def step_assignments_page_exists(context):
    """Prepare the Django test client for this scenario."""

    # Create a Django test client.
    context.client = Client()

@when("I request the assignments page")
def step_request_assignments_page(context):
    """Request the assignments page."""

    # Sends GET request to the assignments URL, Saves the response in context
    # so the Then step can check what Django returned.
    context.response = context.client.get("/assignments/")


@then("the assignments page loads successfully")
def step_assignments_page_loads(context):
    """Verify that the assignments page returned HTTP 200."""

    # HTTP status code 200 means success
    # If the response is anything other than 200, assertion fails marked as failed.
    assert context.response.status_code == 200

@given("I create a test assignment")
def step_create_test_assignment(context):
    """Create an assignment inside Behave's test database."""

    # Create a database record specifically for this scenario. should be in iso DB
    context.assignment = Assignment.objects.create(
        title="Behave Test Assignment",
        course="CS4300",
        due_date=timezone.now() + timedelta(days=7),
    )


@then("the test assignment exists in the database")
def step_test_assignment_exists(context):
    """Verify the assignment exists during the Behave scenario."""

    # Query the database for the record just created.
    assignment_exists = Assignment.objects.filter(
        title="Behave Test Assignment"
    ).exists()

    # Fail the scenario if the record cannot be found.
    assert assignment_exists