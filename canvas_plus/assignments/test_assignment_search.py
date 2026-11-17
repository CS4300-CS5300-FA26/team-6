"""Tests for assignment keyword search."""

import pytest

from django.contrib.auth import get_user_model
from django.urls import reverse

from accounts.models import CanvasConnection
from assignments.models import Assignment


@pytest.mark.django_db
def test_search_matches_assignment_title(client):
    """A keyword in an assignment title should return that assignment."""

    # Create and log in the student.
    user = get_user_model().objects.create_user(
        username="title-search-user",
    )
    client.force_login(user)

    # Create the student's Canvas connection for result links.
    connection = CanvasConnection.objects.create(
        user=user,
        canvas_url="https://canvas.example.edu",
    )

    # Create a synced assignment whose title contains the search term.
    Assignment.objects.create(
        user=user,
        canvas_course_id=42,
        canvas_assignment_id=101,
        title="Lab 3: Recursion",
        course="CS 4300",
        description="Practice recursive programming techniques.",
        sync_state="synced",
    )

    # Search using a case-insensitive keyword.
    response = client.get(
        reverse("search_assignments"),
        {"q": "recursion"},
    )

    # The matching assignment and its course should appear.
    assert response.status_code == 200
    assert b"Lab 3: Recursion" in response.content
    assert b"CS 4300" in response.content


@pytest.mark.django_db
def test_search_matches_assignment_description(client):
    """A keyword in an assignment description should return that assignment."""

    # Create and log in the student.
    user = get_user_model().objects.create_user(
        username="description-search-user",
    )
    client.force_login(user)

    # Store an assignment where only the description contains the keyword.
    Assignment.objects.create(
        user=user,
        canvas_course_id=43,
        canvas_assignment_id=102,
        title="Essay 1",
        course="ENGL 101",
        description="Follow the provided rubric carefully.",
        sync_state="synced",
    )

    # Search for a word found only in the description.
    response = client.get(
        reverse("search_assignments"),
        {"q": "rubric"},
    )

    # The assignment should still appear in the results.
    assert response.status_code == 200
    assert b"Essay 1" in response.content


@pytest.mark.django_db
def test_search_shows_no_results_message(client):
    """A search with no matches should show the expected message."""

    # Create and log in the student.
    user = get_user_model().objects.create_user(
        username="no-results-user",
    )
    client.force_login(user)

    # Search for a term that does not exist.
    response = client.get(
        reverse("search_assignments"),
        {"q": "zebra"},
    )

    assert response.status_code == 200
    assert b"No results for" in response.content
    assert b"zebra" in response.content


@pytest.mark.django_db
def test_empty_search_prompts_for_term(client):
    """An empty search should prompt the student for a search term."""

    # Create and log in the student.
    user = get_user_model().objects.create_user(
        username="empty-search-user",
    )
    client.force_login(user)

    # Submit the search page without a search term.
    response = client.get(
        reverse("search_assignments"),
        {"q": ""},
    )

    assert response.status_code == 200
    assert b"Enter a search term" in response.content


@pytest.mark.django_db
def test_search_does_not_return_other_students_assignments(client):
    """Search results must remain scoped to the signed-in student."""

    # Create two different students.
    user = get_user_model().objects.create_user(
        username="search-owner",
    )
    other_user = get_user_model().objects.create_user(
        username="other-search-owner",
    )

    client.force_login(user)

    # Store a matching assignment owned by another student.
    Assignment.objects.create(
        user=other_user,
        canvas_course_id=44,
        canvas_assignment_id=103,
        title="Recursion Project",
        course="CS 4300",
        description="Recursion practice.",
        sync_state="synced",
    )

    response = client.get(
        reverse("search_assignments"),
        {"q": "recursion"},
    )

    # The other student's assignment must not leak into these results.
    assert response.status_code == 200
    assert b"Recursion Project" not in response.content


@pytest.mark.django_db
def test_search_ignores_unsynced_assignments(client):
    """Missing or failed assignments should not appear in normal search results."""

    # Create and log in the student.
    user = get_user_model().objects.create_user(
        username="sync-search-user",
    )
    client.force_login(user)

    # Create matching assignments that are not currently synced.
    Assignment.objects.create(
        user=user,
        canvas_course_id=45,
        canvas_assignment_id=104,
        title="Missing Recursion Assignment",
        course="CS 4300",
        sync_state="missing",
    )

    Assignment.objects.create(
        user=user,
        canvas_course_id=45,
        canvas_assignment_id=105,
        title="Failed Recursion Assignment",
        course="CS 4300",
        sync_state="failed",
    )

    response = client.get(
        reverse("search_assignments"),
        {"q": "recursion"},
    )

    assert response.status_code == 200
    assert b"Missing Recursion Assignment" not in response.content
    assert b"Failed Recursion Assignment" not in response.content


@pytest.mark.django_db
def test_search_result_links_to_canvas_in_new_tab(client):
    """A result should link to its Canvas assignment in a new tab."""

    # Create and log in the student.
    user = get_user_model().objects.create_user(
        username="canvas-link-user",
    )
    client.force_login(user)

    # Create the student's Canvas connection.
    connection = CanvasConnection.objects.create(
        user=user,
        canvas_url="https://canvas.example.edu",
    )

    # Create a searchable assignment.
    Assignment.objects.create(
        user=user,
        canvas_course_id=42,
        canvas_assignment_id=101,
        title="Lab 3: Recursion",
        course="CS 4300",
        description="Practice recursion.",
        sync_state="synced",
    )

    response = client.get(
        reverse("search_assignments"),
        {"q": "recursion"},
    )

    assert response.status_code == 200
    assert (
        b"https://canvas.example.edu/courses/42/assignments/101"
        in response.content
    )
    assert b'target="_blank"' in response.content


@pytest.mark.django_db
def test_anonymous_search_redirects_to_login(client):
    """Students must log in before using assignment search."""

    response = client.get(
        reverse("search_assignments"),
        {"q": "recursion"},
    )

    assert response.status_code == 302
    assert "/login" in response.url

@pytest.mark.django_db
def test_search_result_keeps_canvas_link_for_invalid_connection(client):
    """A saved Canvas host should still be used when the token is invalid."""

    # Create and log in the student.
    user = get_user_model().objects.create_user(
        username="invalid-connection-search-user",
    )
    client.force_login(user)

    # Save a Canvas connection whose token has been marked invalid.
    # The Canvas host is still usable for constructing assignment URLs.
    CanvasConnection.objects.create(
        user=user,
        canvas_url="https://canvas.example.edu",
        is_valid=False,
    )

    # Create a synced assignment that should appear in search results.
    Assignment.objects.create(
        user=user,
        canvas_course_id=42,
        canvas_assignment_id=101,
        title="Lab 3: Recursion",
        course="CS 4300",
        description="Practice recursion.",
        sync_state="synced",
    )

    # Search for the assignment.
    response = client.get(
        reverse("search_assignments"),
        {"q": "recursion"},
    )

    # The result should still link back to Canvas even though
    # the saved token is no longer valid.
    assert response.status_code == 200
    assert (
        b"https://canvas.example.edu/courses/42/assignments/101"
        in response.content
    )
    assert b'target="_blank"' in response.content

@pytest.mark.django_db
def test_assignment_list_links_to_search_page(client):
    """The assignments page should provide navigation to keyword search."""

    # Create and authenticate the student.
    user = get_user_model().objects.create_user(
        username="assignment-search-link-user",
    )
    client.force_login(user)

    # Open the assignments page.
    response = client.get(
        reverse("assignment_list")
    )

    # The page should render and expose the search route.
    assert response.status_code == 200
    assert reverse("search_assignments").encode() in response.content
    assert b"Search" in response.content
    