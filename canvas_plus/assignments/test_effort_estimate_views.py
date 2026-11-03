"""Tests for manual assignment effort estimate editing."""

import pytest

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from assignments.models import Assignment


@pytest.mark.django_db
def test_owner_can_update_effort_estimate(client):
    """The assignment owner can save a manual effort estimate."""

    # Create the student who owns the assignment.
    user = get_user_model().objects.create_user(
        username="owner",
        password="test-password-123",
    )

    # Create an assignment with an existing automatic estimate.
    assignment = Assignment.objects.create(
        user=user,
        canvas_course_id=1001,
        canvas_assignment_id=2001,
        title="Research Paper",
        course="CS4300",
        due_date=timezone.now(),
        estimated_effort_minutes=90,
        effort_estimate_source="automatic",
    )

    # Log in as the assignment owner.
    client.force_login(user)

    # Submit a new manual estimate.
    response = client.post(
        reverse(
            "edit_effort_estimate",
            args=[
                assignment.canvas_course_id,
                assignment.canvas_assignment_id,
            ],
        ),
        {
            "estimated_effort_minutes": 120,
        },
    )

    # Reload the assignment from the database.
    assignment.refresh_from_db()

    # A valid update should redirect back to the assignment list.
    assert response.status_code == 302

    # The manual value should replace the automatic estimate.
    assert assignment.estimated_effort_minutes == 120

    # The source should now show that the student entered it manually.
    assert assignment.effort_estimate_source == "manual"


@pytest.mark.django_db
def test_other_student_cannot_edit_assignment(client):
    """A student cannot edit another student's assignment."""

    # Create the owner and a different logged-in student.
    owner = get_user_model().objects.create_user(
        username="assignment-owner",
    )
    other_user = get_user_model().objects.create_user(
        username="other-student",
    )

    # Create an assignment owned by the first student.
    assignment = Assignment.objects.create(
        user=owner,
        canvas_course_id=1002,
        canvas_assignment_id=2002,
        title="Lab Report",
        course="CS4300",
        due_date=timezone.now(),
        estimated_effort_minutes=60,
        effort_estimate_source="automatic",
    )

    # Log in as someone who does not own the assignment.
    client.force_login(other_user)

    # Attempt to change the owner's estimate.
    response = client.post(
        reverse(
            "edit_effort_estimate",
            args=[
                assignment.canvas_course_id,
                assignment.canvas_assignment_id,
            ],
        ),
        {
            "estimated_effort_minutes": 180,
        },
    )

    # Reload the assignment to confirm nothing changed.
    assignment.refresh_from_db()

    # get_object_or_404 should hide the record from non-owners.
    assert response.status_code == 302
    assert assignment.estimated_effort_minutes == 60
    assert assignment.effort_estimate_source == "automatic"


@pytest.mark.django_db
def test_anonymous_student_is_redirected_to_login(client):
    """An anonymous user must log in before editing effort estimates."""

    # Create an assignment owner.
    user = get_user_model().objects.create_user(
        username="login-required-owner",
    )

    # Create the assignment.
    assignment = Assignment.objects.create(
        user=user,
        canvas_course_id=1003,
        canvas_assignment_id=2003,
        title="Final Project",
        course="CS4300",
        due_date=timezone.now(),
    )

    # Attempt to access the edit page without logging in.
    response = client.get(
        reverse(
            "edit_effort_estimate",
            args=[
                assignment.canvas_course_id,
                assignment.canvas_assignment_id,
            ],
        )
    )

    # Django's login_required decorator should redirect to login.
    assert response.status_code == 302
    assert "/login" in response.url


@pytest.mark.django_db
def test_invalid_effort_estimate_is_not_saved(client):
    """An invalid manual estimate should be rejected."""

    # Create the assignment owner.
    user = get_user_model().objects.create_user(
        username="invalid-owner",
    )

    # Create an assignment with a valid existing estimate.
    assignment = Assignment.objects.create(
        user=user,
        canvas_course_id=1004,
        canvas_assignment_id=2004,
        title="Programming Assignment",
        course="CS4300",
        due_date=timezone.now(),
        estimated_effort_minutes=90,
        effort_estimate_source="automatic",
    )

    # Log in as the assignment owner.
    client.force_login(user)

    # Submit an invalid zero-minute estimate.
    response = client.post(
        reverse(
            "edit_effort_estimate",
            args=[
                assignment.canvas_course_id,
                assignment.canvas_assignment_id,
            ],
        ),
        {
            "estimated_effort_minutes": 0,
        },
    )

    # Reload the assignment from the database.
    assignment.refresh_from_db()

    # Invalid input should redisplay the form rather than redirect.
    assert response.status_code == 200

    # The original valid estimate should remain unchanged.
    assert assignment.estimated_effort_minutes == 90
    assert assignment.effort_estimate_source == "automatic"

    # The form should display the validation error.
    assert b"greater than zero" in response.content
