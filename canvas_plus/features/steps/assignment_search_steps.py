"""Behave steps for assignment keyword search."""

# Import Behave decorators for acceptance-test steps.
from behave import given, when, then

# Import Django helpers used by the test client and URL resolver.
from django.contrib.auth import get_user_model
from django.urls import reverse

# Import the local Assignment model searched by the feature.
from assignments.models import Assignment

# Import the student's Canvas connection so search results can build Canvas links.
from accounts.models import CanvasConnection


@given('my Canvas assignment index contains "Lab 3: Recursion" in course "CS 4300"')
def step_index_contains_assignment(context):
    """Create a searchable local assignment for the logged-in student."""

    # Create a student for this scenario.
    context.user = get_user_model().objects.create_user(
        username="behave-assignment-search-user",
    )

    # Log the student into Django's test client.
    context.test.client.force_login(context.user)

    # Create the student's Canvas connection so the search result
    # can construct the assignment's Canvas URL.
    CanvasConnection.objects.create(
        user=context.user,
        canvas_url="https://canvas.example.edu",
    )

    # Create a synced assignment in the student's local Canvas index.
    context.assignment = Assignment.objects.create(
        user=context.user,
        canvas_course_id=42,
        canvas_assignment_id=101,
        title="Lab 3: Recursion",
        course="CS 4300",
        description="Practice recursive programming techniques.",
        sync_state="synced",
    )


@given('my assignment "Essay 1" has description "Follow the provided rubric carefully"')
def step_assignment_has_description(context):
    """Create an assignment whose searchable term appears in its description."""

    # Create and authenticate the student.
    context.user = get_user_model().objects.create_user(
        username="behave-description-search-user",
    )
    context.test.client.force_login(context.user)

    # Store a synced assignment whose title does not contain "rubric".
    context.assignment = Assignment.objects.create(
        user=context.user,
        canvas_course_id=43,
        canvas_assignment_id=102,
        title="Essay 1",
        course="ENGL 101",
        description="Follow the provided rubric carefully",
        sync_state="synced",
    )


@given('my assignment index does not contain "zebra"')
def step_index_has_no_zebra(context):
    """Create a student whose local assignment index has no matching term."""

    # Create and authenticate the student.
    context.user = get_user_model().objects.create_user(
        username="behave-no-results-user",
    )
    context.test.client.force_login(context.user)

    # Add a non-matching assignment so this is a real search against
    # a populated local assignment index.
    Assignment.objects.create(
        user=context.user,
        canvas_course_id=44,
        canvas_assignment_id=103,
        title="Networking Lab",
        course="CS 4300",
        description="Configure routing between two networks.",
        sync_state="synced",
    )


@given("I am on the assignment search page")
def step_on_assignment_search_page(context):
    """Open the search page as an authenticated student."""

    # Create and authenticate the student.
    context.user = get_user_model().objects.create_user(
        username="behave-empty-search-user",
    )
    context.test.client.force_login(context.user)

    # Open the search page without performing a search yet.
    context.response = context.test.client.get(
        reverse("search_assignments")
    )


@when('I search assignments for "{search_term}"')
def step_search_assignments(context, search_term):
    """Submit a keyword search through the real Django view."""

    context.response = context.test.client.get(
        reverse("search_assignments"),
        {"q": search_term},
    )


@when("I search assignments without entering a term")
def step_search_without_term(context):
    """Submit an empty assignment search."""

    context.response = context.test.client.get(
        reverse("search_assignments"),
        {"q": ""},
    )


@then('I see "{assignment_title}" in the assignment search results')
def step_assignment_title_visible(context, assignment_title):
    """Verify the matching assignment appears in the rendered page."""

    assert context.response.status_code == 200
    assert assignment_title.encode() in context.response.content


@then('I see course "{course_name}" in the assignment search results')
def step_course_name_visible(context, course_name):
    """Verify the result includes the assignment's course name."""

    assert course_name.encode() in context.response.content


@then("the assignment result opens Canvas in a new tab")
def step_result_opens_new_tab(context):
    """Verify assignment result links use a new browser tab."""

    assert b'target="_blank"' in context.response.content


@then('I see no assignment results for "{search_term}"')
def step_no_results_message(context, search_term):
    """Verify the no-results message identifies the searched term."""

    assert b"No results for" in context.response.content
    assert search_term.encode() in context.response.content


@then("I am prompted to enter a search term")
def step_empty_search_prompt(context):
    """Verify an empty search displays the expected prompt."""

    assert b"Enter a search term" in context.response.content